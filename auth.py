"""Account and opaque-session support for the authenticated beta.

``register_auth(app, connect, audit_callback)`` expects ``connect()`` to return a
psycopg2-compatible connection and the following PostgreSQL contract.  UUID
columns may be native ``uuid`` values; the module converts them to strings at
the HTTP boundary.

Required columns::

    users(id, display_name, login_display, login_normalized, email,
          password_hash, status, auth_generation, activated_at, disabled_at,
          password_changed_at, created_at, updated_at, disabled_by,
          disable_reason)
    memberships(user_id, condominium_id, status, starts_at, ends_at)
    role_grants(user_id, condominium_id, role, starts_at, ends_at, revoked_at)
    sessions(id, token_hash, user_id, auth_generation, csrf_hash, created_at,
             last_seen_at, idle_expires_at, absolute_expires_at,
             authenticated_at, revoked_at, revoke_reason, user_agent)
    invitations(id, user_id, token_hash, issued_by, expires_at, used_at,
                revoked_at, created_at)
    recovery_tokens(id, user_id, token_hash, delivery_kind, reason, expires_at,
                    used_at, revoked_at, created_at)

``token_hash`` and ``csrf_hash`` are ``bytea``.  User states are ``invited``,
``active`` and ``disabled``.  Membership state is ``active``.  Date ranges are
half-open: ``starts_at <= now() < ends_at``; a null bound is open.

Configuration hooks:

``AUTH_CAN_MANAGE_ACCOUNTS(principal)``
    Mandatory for HTTP invitation and deactivation.  Missing means deny.
``AUTH_DELIVER_TOKEN(kind, user, raw_token)``
    Delivers activation/recovery tokens.  Tokens are never logged.
``AUTH_COOKIE_SECURE``
    Whether cookies receive ``Secure`` (default false for the loopback pilot).

The optional audit callback is called as
``callback(action, actor_user_id=..., subject_user_id=..., outcome=...,
details=...)`` and must never persist credentials or raw tokens.
"""

from __future__ import annotations

import hashlib
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import g, jsonify, request


COOKIE_NAME = "sqa_session"
CSRF_COOKIE_NAME = "sqa_csrf"
IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=12)
INVITATION_TIMEOUT = timedelta(hours=48)
RECOVERY_TIMEOUT = timedelta(minutes=30)
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024
PASSWORD_HASHER = PasswordHasher()
_dummy_password_hash: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_login(value: str) -> str:
    """Return the stable unique-login representation used by the database."""
    if not isinstance(value, str):
        raise ValueError("Identificador inválido.")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not normalized or len(normalized) > 254 or any(ch.isspace() for ch in normalized):
        raise ValueError("Identificador inválido.")
    return normalized


def validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise ValueError("A senha deve ser um texto.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("A senha ultrapassa o limite permitido.")
    if (
        len(password) < MIN_PASSWORD_LENGTH
        or not any(ch.isdigit() for ch in password)
        or not any(ch.isupper() for ch in password)
        or not any(not ch.isalnum() and not ch.isspace() for ch in password)
    ):
        raise ValueError(
            "Use uma senha com ao menos 8 caracteres, incluindo número, "
            "letra maiúscula e caractere especial."
        )


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError, UnicodeError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.check_needs_rehash(stored_hash)
    except (InvalidHashError, TypeError):
        return False


def generate_token() -> tuple[str, bytes]:
    """Generate a high-entropy opaque token and the SHA-256 value to persist."""
    raw = secrets.token_urlsafe(32)
    return raw, token_digest(raw)


def token_digest(raw: str) -> bytes:
    if not isinstance(raw, str) or not raw:
        return b""
    return hashlib.sha256(raw.encode("utf-8")).digest()


def tokens_match(raw: str, expected_digest: bytes) -> bool:
    return secrets.compare_digest(token_digest(raw), bytes(expected_digest))


def current_principal() -> dict[str, Any] | None:
    """Return the principal loaded from the opaque session, never a CSRF token."""
    return getattr(g, "principal", None)


def require_session(view: Callable[..., Any]) -> Callable[..., Any]:
    """Require ``register_auth`` to have loaded a valid active session."""
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        if current_principal() is None:
            return jsonify(error="Entre novamente para continuar."), 401
        return view(*args, **kwargs)
    return wrapped


def _dummy_hash() -> str:
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = PASSWORD_HASHER.hash(secrets.token_urlsafe(24))
    return _dummy_password_hash


class AuthService:
    def __init__(self, app, connect: Callable[[], Any], audit_callback=None):
        self.app = app
        self.connect = connect
        self.audit_callback = audit_callback

    def _audit(self, action: str, **fields: Any) -> None:
        if not self.audit_callback:
            return
        try:
            self.audit_callback(action, **fields)
        except Exception:
            self.app.logger.error("Authentication audit callback failed")

    def _cookie_options(self, *, httponly: bool) -> dict[str, Any]:
        return {
            "httponly": httponly,
            "secure": bool(self.app.config.get("AUTH_COOKIE_SECURE", False)),
            "samesite": "Lax",
            "path": self.app.config.get("AUTH_COOKIE_PATH", "/"),
            "max_age": int(ABSOLUTE_TIMEOUT.total_seconds()),
        }

    def _set_cookies(self, response, session_token: str, csrf_token: str) -> None:
        response.set_cookie(self.app.config.get("AUTH_COOKIE_NAME", COOKIE_NAME), session_token, **self._cookie_options(httponly=True))
        response.set_cookie(self.app.config.get("AUTH_CSRF_COOKIE_NAME", CSRF_COOKIE_NAME), csrf_token, **self._cookie_options(httponly=False))

    def _clear_cookies(self, response) -> None:
        options = self._cookie_options(httponly=True)
        options.pop("max_age", None)
        response.delete_cookie(self.app.config.get("AUTH_COOKIE_NAME", COOKIE_NAME), **options)
        options["httponly"] = False
        response.delete_cookie(self.app.config.get("AUTH_CSRF_COOKIE_NAME", CSRF_COOKIE_NAME), **options)

    @staticmethod
    def _principal(user_id, session_id, display_name, memberships, grants):
        return {
            "user_id": str(user_id),
            "session_id": str(session_id),
            "display_name": display_name,
            "memberships": [str(value) for value in memberships],
            "grants": [
                {"condominium_id": str(condominium_id), "role": role}
                for condominium_id, role in grants
            ],
        }

    def _load_access(self, cur, user_id):
        cur.execute(
            """SELECT condominium_id FROM memberships
               WHERE user_id=%s AND status='active'
                 AND (starts_at IS NULL OR starts_at <= now())
                 AND (ends_at IS NULL OR ends_at > now())
               ORDER BY condominium_id""",
            (user_id,),
        )
        memberships = [row[0] for row in cur.fetchall()]
        cur.execute(
            """SELECT condominium_id,role FROM role_grants
               WHERE user_id=%s AND revoked_at IS NULL
                 AND (starts_at IS NULL OR starts_at <= now())
                 AND (ends_at IS NULL OR ends_at > now())
               ORDER BY condominium_id,role""",
            (user_id,),
        )
        return memberships, cur.fetchall()

    def load_request_principal(self) -> None:
        g.principal = None
        g.pending_principal = None
        g.auth_session = None
        raw = request.cookies.get(self.app.config.get("AUTH_COOKIE_NAME", COOKIE_NAME), "")
        if not raw:
            return
        digest = token_digest(raw)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT s.id,s.user_id,s.csrf_hash,u.display_name
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=%s AND s.revoked_at IS NULL
                     AND s.auth_generation=u.auth_generation
                     AND u.status='active'
                     AND s.idle_expires_at > now()
                     AND s.absolute_expires_at > now()
                   FOR UPDATE OF s""",
                (digest,),
            )
            row = cur.fetchone()
            if not row:
                return
            session_id, user_id, csrf_hash, display_name = row
            cur.execute(
                """UPDATE sessions SET last_seen_at=now(),
                   idle_expires_at=LEAST(absolute_expires_at,now()+interval '30 minutes')
                   WHERE id=%s""",
                (session_id,),
            )
            memberships, grants = self._load_access(cur, user_id)
        g.auth_session = {"id": str(session_id), "csrf_hash": bytes(csrf_hash)}
        g.principal = self._principal(user_id, session_id, display_name, memberships, grants)
        owner_context=self.app.config.get('AUTH_OWNER_CONTEXT')
        if owner_context:g.principal=owner_context(g.principal)
        checker=self.app.config.get('AUTH_MFA_CHECK')
        if checker and not checker(g.principal):
            g.pending_principal=g.principal
            g.diagnostic_user_id=g.principal['user_id']
            g.principal=None

    def require_csrf(self, view):
        @wraps(view)
        @require_session
        def wrapped(*args, **kwargs):
            raw = request.headers.get("X-CSRF-Token", "")
            cookie = request.cookies.get(self.app.config.get("AUTH_CSRF_COOKIE_NAME", CSRF_COOKIE_NAME), "")
            expected = g.auth_session["csrf_hash"]
            if not raw or not cookie or not secrets.compare_digest(raw, cookie) or not tokens_match(raw, expected):
                return jsonify(error="Confirmação de segurança inválida. Recarregue e tente novamente."), 403
            return view(*args, **kwargs)
        return wrapped

    def _new_session(self, cur, user_id, auth_generation):
        session_token, session_hash = generate_token()
        csrf_token, csrf_hash = generate_token()
        session_id = uuid.uuid4()
        now = utcnow()
        cur.execute(
            """INSERT INTO sessions
               (id,token_hash,user_id,auth_generation,csrf_hash,created_at,
                last_seen_at,idle_expires_at,absolute_expires_at,
                authenticated_at,user_agent)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                session_id, session_hash, user_id, auth_generation, csrf_hash,
                now, now, now + IDLE_TIMEOUT, now + ABSOLUTE_TIMEOUT, now,
                request.headers.get("User-Agent", "")[:500],
            ),
        )
        return session_id, session_token, csrf_token

    def login(self):
        body = request.get_json(silent=True) or {}
        try:
            login = normalize_login(body.get("login"))
        except ValueError:
            login = "invalid-login"
        password = body.get("password") if isinstance(body.get("password"), str) else ""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,display_name,password_hash,status,auth_generation
                   FROM users WHERE login_normalized=%s FOR UPDATE""",
                (login,),
            )
            row = cur.fetchone()
            candidate_hash = row[2] if row and row[2] else _dummy_hash()
            valid = verify_password(candidate_hash, password)
            if not row or row[3] != "active" or not valid:
                self._audit("auth.login", outcome="denied", details={"login_known": bool(row)})
                return jsonify(error="Identificador ou senha inválidos."), 401
            user_id, display_name, stored_hash, _, generation = row
            if password_needs_rehash(stored_hash):
                cur.execute(
                    "UPDATE users SET password_hash=%s,updated_at=now() WHERE id=%s",
                    (PASSWORD_HASHER.hash(password), user_id),
                )
            old = request.cookies.get(self.app.config.get("AUTH_COOKIE_NAME", COOKIE_NAME), "")
            if old:
                cur.execute(
                    "UPDATE sessions SET revoked_at=now(),revoke_reason='rotated_login' WHERE token_hash=%s AND revoked_at IS NULL",
                    (token_digest(old),),
                )
            session_id, session_token, csrf_token = self._new_session(cur, user_id, generation)
            memberships, grants = self._load_access(cur, user_id)
        principal = self._principal(user_id, session_id, display_name, memberships, grants)
        g.principal = principal  # Successful login diagnostics identify the user.
        checker=self.app.config.get('AUTH_MFA_CHECK')
        pending=bool(checker and not checker(principal))
        if pending:
            g.pending_principal=principal
            g.principal=None
            g.diagnostic_user_id=str(user_id)
        response = jsonify(principal=principal, csrf_token=csrf_token, mfaRequired=pending)
        self._set_cookies(response, session_token, csrf_token)
        self._audit("auth.login", actor_user_id=str(user_id), outcome="success")
        return response

    def session_info(self):
        principal = current_principal()
        pending=getattr(g,'pending_principal',None)
        if pending:
            return jsonify(principal=pending,mfaRequired=True,csrf_token=request.cookies.get(self.app.config.get('AUTH_CSRF_COOKIE_NAME',CSRF_COOKIE_NAME),''))
        if principal is None:
            response = jsonify(error="Entre novamente para continuar.")
            self._clear_cookies(response)
            return response, 401
        csrf_token = request.cookies.get(self.app.config.get("AUTH_CSRF_COOKIE_NAME", CSRF_COOKIE_NAME), "")
        if not csrf_token or not tokens_match(csrf_token, g.auth_session["csrf_hash"]):
            csrf_token, csrf_hash = generate_token()
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET csrf_hash=%s WHERE id=%s AND revoked_at IS NULL",
                    (csrf_hash, principal["session_id"]),
                )
        response = jsonify(principal=principal, csrf_token=csrf_token)
        if request.cookies.get(self.app.config.get("AUTH_CSRF_COOKIE_NAME", CSRF_COOKIE_NAME), "") != csrf_token:
            response.set_cookie(self.app.config.get("AUTH_CSRF_COOKIE_NAME", CSRF_COOKIE_NAME), csrf_token, **self._cookie_options(httponly=False))
        return response

    def logout(self):
        principal = current_principal()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET revoked_at=now(),revoke_reason='logout' WHERE id=%s AND revoked_at IS NULL",
                (principal["session_id"],),
            )
        response = jsonify(status="ok")
        self._clear_cookies(response)
        self._audit("auth.logout", actor_user_id=principal["user_id"], outcome="success")
        return response

    def _can_manage(self, condominium_id=None) -> bool:
        callback = self.app.config.get("AUTH_CAN_MANAGE_ACCOUNTS")
        return bool(callback and callback(current_principal(), condominium_id))

    def issue_invitation(self):
        delivery = self.app.config.get("AUTH_DELIVER_TOKEN")
        if not delivery:
            return jsonify(error="Entrega de convite não configurada."), 503
        body = request.get_json(silent=True) or {}
        try:
            login = normalize_login(body.get("login"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        display_name = body.get("displayName")
        if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 200:
            return jsonify(error="Nome inválido."), 400
        roles = body.get("roles")
        allowed_roles = {"operador", "administrador"}
        if not isinstance(roles, list) or len(roles) != 1 or any(not isinstance(role, str) or role not in allowed_roles for role in roles):
            return jsonify(error="Selecione um perfil: Operador ou Administrador."), 400
        condominium_id = body.get("condominiumId") or ((current_principal() or {}).get("memberships") or [None])[0]
        if condominium_id not in (current_principal() or {}).get("memberships", []):
            return jsonify(error="Condomínio fora do seu escopo."), 403
        if not self._can_manage(condominium_id):
            return jsonify(error="Ação não permitida."), 403
        raw, digest = generate_token()
        invitation_id = uuid.uuid4()
        actor = current_principal()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users
                   (id,display_name,login_display,login_normalized,email,status,auth_generation,created_at,updated_at)
                   VALUES(%s,%s,%s,%s,%s,'invited',1,now(),now())
                   ON CONFLICT(login_normalized) DO UPDATE SET
                     display_name=EXCLUDED.display_name,login_display=EXCLUDED.login_display,
                     email=EXCLUDED.email,updated_at=now()
                   WHERE users.status='invited' AND NOT EXISTS
                     (SELECT 1 FROM memberships existing_membership
                      WHERE existing_membership.user_id=users.id AND existing_membership.condominium_id<>%s)
                   RETURNING id""",
                (uuid.uuid4(), display_name.strip(), body.get("login").strip(), login, body.get("email"), condominium_id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify(error="A conta não pode receber um novo convite."), 409
            user_id = row[0]
            cur.execute('UPDATE users SET mfa_required=true WHERE id=%s',(user_id,))
            cur.execute("SELECT id FROM memberships WHERE user_id=%s AND condominium_id=%s", (user_id, condominium_id))
            membership = cur.fetchone()
            if membership:
                membership_id = membership[0]
                cur.execute("UPDATE memberships SET status='active',starts_at=COALESCE(starts_at,now()),ends_at=NULL WHERE id=%s", (membership_id,))
            else:
                membership_id = uuid.uuid4()
                cur.execute("INSERT INTO memberships(id,user_id,condominium_id,status,starts_at) VALUES(%s,%s,%s,'active',now())", (membership_id, user_id, condominium_id))
            cur.execute("UPDATE role_grants SET revoked_at=now() WHERE user_id=%s AND condominium_id=%s AND revoked_at IS NULL", (user_id, condominium_id))
            for role in dict.fromkeys(roles):
                cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,starts_at,granted_by,basis) VALUES(%s,%s,%s,%s,%s,now(),%s,%s)", (uuid.uuid4(), membership_id, user_id, condominium_id, role, actor["user_id"], "Convite emitido por responsável de acessos"))
            cur.execute("UPDATE invitations SET revoked_at=now() WHERE user_id=%s AND used_at IS NULL AND revoked_at IS NULL", (user_id,))
            cur.execute(
                "INSERT INTO invitations(id,user_id,token_hash,issued_by,expires_at,created_at) VALUES(%s,%s,%s,%s,%s,now())",
                (invitation_id, user_id, digest, actor["user_id"], utcnow() + INVITATION_TIMEOUT),
            )
        delivery("activation", {"id": str(user_id), "login": login, "display_name": display_name.strip()}, raw)
        self._audit("account.invite", actor_user_id=actor["user_id"], subject_user_id=str(user_id), outcome="success")
        return jsonify(status="created", userId=str(user_id)), 201

    def activate(self):
        body = request.get_json(silent=True) or {}
        try:
            validate_password(body.get("password"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        digest = token_digest(body.get("token"))
        if not digest:
            return jsonify(error="Convite inválido ou expirado."), 400
        password_hash = PASSWORD_HASHER.hash(body["password"])
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,user_id FROM invitations
                   WHERE token_hash=%s AND used_at IS NULL AND revoked_at IS NULL
                     AND expires_at>now() FOR UPDATE""",
                (digest,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify(error="Convite inválido ou expirado."), 400
            invitation_id, user_id = row
            cur.execute(
                """UPDATE users SET password_hash=%s,status='active',activated_at=now(),
                   password_changed_at=now(),auth_generation=auth_generation+1,updated_at=now()
                   WHERE id=%s AND status='invited' RETURNING id""",
                (password_hash, user_id),
            )
            if not cur.fetchone():
                return jsonify(error="Convite inválido ou expirado."), 400
            cur.execute("UPDATE invitations SET used_at=now() WHERE id=%s", (invitation_id,))
            cur.execute("UPDATE invitations SET revoked_at=now() WHERE user_id=%s AND id<>%s AND used_at IS NULL AND revoked_at IS NULL", (user_id, invitation_id))
            cur.execute("UPDATE sessions SET revoked_at=now(),revoke_reason='activation' WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
        self._audit("account.activate", subject_user_id=str(user_id), outcome="success")
        return jsonify(status="ok")

    def request_recovery(self):
        handler=self.app.config.get('AUTH_ASSISTED_REQUEST')
        if handler:return handler()
        body = request.get_json(silent=True) or {}
        try:
            login = normalize_login(body.get("login"))
        except ValueError:
            login = "invalid-login"
        delivery = self.app.config.get("AUTH_DELIVER_TOKEN")
        delivered = False
        if delivery:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT id,display_name FROM users WHERE login_normalized=%s AND status='active' FOR UPDATE", (login,))
                row = cur.fetchone()
                if row:
                    user_id, display_name = row
                    raw, digest = generate_token()
                    cur.execute("UPDATE recovery_tokens SET revoked_at=now() WHERE user_id=%s AND used_at IS NULL AND revoked_at IS NULL", (user_id,))
                    cur.execute(
                        """INSERT INTO recovery_tokens
                           (id,user_id,token_hash,delivery_kind,reason,expires_at,created_at)
                           VALUES(%s,%s,%s,'email',NULL,%s,now())""",
                        (uuid.uuid4(), user_id, digest, utcnow() + RECOVERY_TIMEOUT),
                    )
                    delivered = True
            if delivered:
                delivery("recovery", {"id": str(user_id), "login": login, "display_name": display_name}, raw)
        self._audit("auth.recovery_request", outcome="accepted", details={"delivery_configured": bool(delivery)})
        return jsonify(status="accepted"), 202

    def complete_recovery(self):
        body = request.get_json(silent=True) or {}
        try:
            validate_password(body.get("password"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        digest = token_digest(body.get("token"))
        if not digest:
            return jsonify(error="Recuperação inválida ou expirada."), 400
        password_hash = PASSWORD_HASHER.hash(body["password"])
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,user_id FROM recovery_tokens
                   WHERE token_hash=%s AND used_at IS NULL AND revoked_at IS NULL
                     AND expires_at>now() FOR UPDATE""",
                (digest,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify(error="Recuperação inválida ou expirada."), 400
            recovery_id, user_id = row
            cur.execute(
                """UPDATE users SET password_hash=%s,password_changed_at=now(),
                   auth_generation=auth_generation+1,updated_at=now()
                   WHERE id=%s AND status='active' RETURNING id""",
                (password_hash, user_id),
            )
            if not cur.fetchone():
                return jsonify(error="Recuperação inválida ou expirada."), 400
            cur.execute("UPDATE recovery_tokens SET used_at=now() WHERE id=%s", (recovery_id,))
            cur.execute("UPDATE recovery_tokens SET revoked_at=now() WHERE user_id=%s AND id<>%s AND used_at IS NULL AND revoked_at IS NULL", (user_id, recovery_id))
            cur.execute("UPDATE sessions SET revoked_at=now(),revoke_reason='password_recovery' WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            cur.execute('SELECT reset_mfa FROM recovery_tokens WHERE id=%s',(recovery_id,))
            if cur.fetchone()[0]:
                cur.execute('DELETE FROM user_mfa WHERE user_id=%s',(user_id,))
        self._audit("auth.recovery_complete", subject_user_id=str(user_id), outcome="success")
        response = jsonify(status="ok")
        self._clear_cookies(response)
        return response

    def disable_user(self, user_id):
        try:
            target = uuid.UUID(user_id)
        except (ValueError, TypeError):
            return jsonify(error="Conta não encontrada."), 404
        body = request.get_json(silent=True) or {}
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            return jsonify(error="Informe o motivo da desativação."), 400
        actor = current_principal()
        condominium_id = body.get('condominiumId') or (actor.get('memberships') or [None])[0]
        if condominium_id not in actor.get('memberships', []) or not self._can_manage(condominium_id):
            return jsonify(error="Ação não permitida."), 403
        if actor["user_id"] == str(target):
            return jsonify(error="Use outro administrador para desativar esta conta."), 409
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE memberships SET status='inactive',ends_at=now()
                   WHERE user_id=%s AND condominium_id=%s AND status='active' RETURNING id""",
                (target, condominium_id),
            )
            if not cur.fetchone():
                return jsonify(error="Conta não encontrada ou já desativada."), 404
            cur.execute("UPDATE role_grants SET revoked_at=now() WHERE user_id=%s AND condominium_id=%s AND revoked_at IS NULL", (target, condominium_id))
        self._audit("membership.disable", actor_user_id=actor["user_id"], subject_user_id=str(target), outcome="success", details={"reason": reason.strip(), "condominiumId": condominium_id})
        return jsonify(status="ok")


def register_auth(app, connect: Callable[[], Any], audit_callback=None) -> AuthService:
    """Register account routes and request principal loading on ``app``."""
    service = AuthService(app, connect, audit_callback)
    app.extensions["sqa_auth"] = service
    app.before_request(service.load_request_principal)
    app.add_url_rule("/api/auth/login", "auth_login", service.login, methods=["POST"])
    app.add_url_rule("/api/auth/session", "auth_session", service.session_info, methods=["GET"])
    app.add_url_rule("/api/auth/me", "auth_me", service.session_info, methods=["GET"])
    app.add_url_rule("/api/auth/logout", "auth_logout", service.require_csrf(service.logout), methods=["POST"])
    app.add_url_rule("/api/auth/invitations", "auth_invitation", service.require_csrf(service.issue_invitation), methods=["POST"])
    app.add_url_rule("/api/auth/activate", "auth_activate", service.activate, methods=["POST"])
    app.add_url_rule("/api/auth/recovery/request", "auth_recovery_request", service.request_recovery, methods=["POST"])
    app.add_url_rule("/api/auth/recovery/complete", "auth_recovery_complete", service.complete_recovery, methods=["POST"])
    app.add_url_rule("/api/auth/users/<user_id>/disable", "auth_disable", service.require_csrf(service.disable_user), methods=["POST"])
    return service
