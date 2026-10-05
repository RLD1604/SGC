"""Individual MFA and human-approved recovery. Credentials never enter diagnostics."""
import base64
import hashlib
import hmac
import os
import secrets
import uuid
from pathlib import Path
from datetime import datetime,timezone
from functools import wraps
from urllib.parse import quote
from cryptography.fernet import Fernet
from flask import g,request,jsonify
from auth import tokens_match,generate_token,normalize_login,utcnow,RECOVERY_TIMEOUT,INVITATION_TIMEOUT
from owner_console import matching_counter,enrollment_qr


def cipher():
    return Fernet(Path(os.environ['USER_MFA_KEY_FILE']).read_bytes().strip())


def register_user_security(app,connect,auth):
    def mfa_check(actor):
        with connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT u.mfa_required,s.mfa_verified FROM users u JOIN sessions s ON s.user_id=u.id WHERE u.id=%s AND s.id=%s',(actor['user_id'],actor['session_id']))
            row=cur.fetchone()
        return bool(row and (not row[0] or row[1]))
    app.config['AUTH_MFA_CHECK']=mfa_check

    def pending_required(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            actor=getattr(g,'pending_principal',None) or getattr(g,'principal',None)
            if not actor:return jsonify(error='Entre com sua senha primeiro.'),401
            csrf=request.headers.get('X-CSRF-Token','')
            cookie=request.cookies.get(app.config.get('AUTH_CSRF_COOKIE_NAME','sqa_csrf'),'')
            if not csrf or not hmac.compare_digest(csrf,cookie) or not tokens_match(csrf,g.auth_session['csrf_hash']):
                return jsonify(error='Confirmação de segurança inválida.'),403
            g.mfa_actor=actor
            g.diagnostic_user_id=actor['user_id']
            return view(*args,**kwargs)
        return wrapped

    @app.post('/api/auth/mfa/setup')
    @pending_required
    def user_mfa_setup():
        actor=g.mfa_actor
        with connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT mfa_required,login_display FROM users WHERE id=%s FOR UPDATE',(actor['user_id'],))
            required,login=cur.fetchone()
            if not required:return jsonify(error='Configuração não exigida para esta conta.'),409
            cur.execute('SELECT secret_ciphertext,enrolled_at FROM user_mfa WHERE user_id=%s',(actor['user_id'],))
            row=cur.fetchone()
            if row and row[1]:return jsonify(enrolled=True)
            f=cipher()
            key=f.decrypt(bytes(row[0])).decode() if row else base64.b32encode(secrets.token_bytes(20)).decode()
            if not row:cur.execute('INSERT INTO user_mfa(user_id,secret_ciphertext) VALUES(%s,%s)',(actor['user_id'],f.encrypt(key.encode())))
        uri=f'otpauth://totp/{quote("SGC:"+login,safe="")}?secret={key}&issuer=SGC&algorithm=SHA1&digits=6&period=30'
        return jsonify(enrolled=False,setupKey=key,setupQr=enrollment_qr(uri))

    @app.post('/api/auth/mfa/verify')
    @pending_required
    def user_mfa_verify():
        actor=g.mfa_actor
        body=request.get_json(silent=True)
        if not isinstance(body,dict):return jsonify(error='Código inválido.'),400
        with connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT secret_ciphertext,last_counter,attempts,attempt_window FROM user_mfa WHERE user_id=%s FOR UPDATE',(actor['user_id'],))
            row=cur.fetchone()
            if not row:return jsonify(error='Configure o autenticador primeiro.'),409
            ciphertext,last,attempts,window=row
            attempts=attempts+1 if (datetime.now(timezone.utc)-window).total_seconds()<600 else 1
            cur.execute("UPDATE user_mfa SET attempts=%s,attempt_window=CASE WHEN attempt_window<now()-interval '10 minutes' THEN now() ELSE attempt_window END WHERE user_id=%s",(attempts,actor['user_id']))
            if attempts>5:return jsonify(error='Muitas tentativas. Aguarde dez minutos.'),429
            code=matching_counter(cipher().decrypt(bytes(ciphertext)).decode(),body.get('code'),last_counter=last)
            if code is None:return jsonify(error='Código inválido ou já utilizado.'),403
            cur.execute('UPDATE user_mfa SET enrolled_at=COALESCE(enrolled_at,now()),last_counter=%s,attempts=0 WHERE user_id=%s',(code,actor['user_id']))
            cur.execute("UPDATE sessions SET mfa_verified=true WHERE id=%s AND user_id=%s AND revoked_at IS NULL",(actor['session_id'],actor['user_id']))
        return jsonify(status='confirmed')

    @app.post('/api/auth/mfa/cancel')
    @pending_required
    def user_mfa_cancel():
        with connect() as conn,conn.cursor() as cur:
            cur.execute("UPDATE sessions SET revoked_at=now(),revoke_reason='mfa_cancel' WHERE id=%s",(g.mfa_actor['session_id'],))
        response=jsonify(status='ok');auth._clear_cookies(response);return response

    def request_access_recovery():
        body=request.get_json(silent=True)
        if not isinstance(body,dict):body={}
        try:login=normalize_login(body.get('login'))
        except ValueError:login='invalid-login'
        kind=body.get('kind') if body.get('kind') in ('password','authenticator','activation') else 'password'
        # Proxy must supply client address. Store only a keyed digest, never IP.
        address=request.remote_addr or 'unknown'
        key=hmac.new(Path(os.environ['USER_MFA_KEY_FILE']).read_bytes(),address.encode(),hashlib.sha256).digest()
        with connect() as conn,conn.cursor() as cur:
            cur.execute("INSERT INTO public_recovery_quotas(key,window_started_at,hits) VALUES(%s,now(),1) ON CONFLICT(key) DO UPDATE SET hits=CASE WHEN public_recovery_quotas.window_started_at>now()-interval '10 minutes' THEN public_recovery_quotas.hits+1 ELSE 1 END,window_started_at=CASE WHEN public_recovery_quotas.window_started_at>now()-interval '10 minutes' THEN public_recovery_quotas.window_started_at ELSE now() END RETURNING hits",(key,))
            hits=cur.fetchone()[0]
            if hits<=20:
                cur.execute("SELECT id,status FROM users WHERE login_normalized=%s AND status IN ('active','invited')",(login,))
                row=cur.fetchone()
                if row:
                    cur.execute("INSERT INTO access_recovery_requests(id,user_id,kind) VALUES(%s,%s,%s) ON CONFLICT(user_id) WHERE status='pending' DO NOTHING",(uuid.uuid4(),row[0],'activation' if row[1]=='invited' else kind))
        return jsonify(status='accepted',message='Se a conta existir, a solicitação ficará disponível para o dono. Entre em contato com ele para confirmar sua identidade.'),202
    app.config['AUTH_ASSISTED_REQUEST']=request_access_recovery

    owner_required=app.extensions['owner_require']

    @app.get('/api/owner/recovery-requests')
    @owner_required
    def recovery_queue():
        with connect() as conn,conn.cursor() as cur:
            cur.execute("SELECT r.id,u.display_name,u.login_display,r.kind,r.created_at,u.status FROM access_recovery_requests r JOIN users u ON u.id=r.user_id WHERE r.status='pending' ORDER BY r.created_at LIMIT 100")
            rows=cur.fetchall()
        return jsonify(requests=[dict(id=str(r[0]),name=r[1],login=r[2],kind=r[3],at=r[4].isoformat(),accountStatus=r[5]) for r in rows])

    @app.post('/api/owner/recovery-requests/<request_id>/resolve')
    @owner_required
    @auth.require_csrf
    def resolve_recovery(request_id):
        try:request_id=str(uuid.UUID(request_id))
        except ValueError:return jsonify(error='Solicitação inválida.'),400
        body=request.get_json(silent=True)
        if not isinstance(body,dict):return jsonify(error='Solicitação inválida.'),400
        decision=body.get('decision')
        reason=body.get('reason')
        if decision not in ('issue','reject') or not isinstance(reason,str) or not 10<=len(reason.strip())<=500:
            return jsonify(error='Informe a decisão e o registro da verificação de identidade (10 a 500 caracteres).'),400
        if decision=='issue' and body.get('identityConfirmed') is not True:return jsonify(error='Confirme a identidade por um contato conhecido.'),400
        reset=body.get('resetAuthenticator') is True
        actor=g.principal
        raw=None
        with connect() as conn,conn.cursor() as cur:
            cur.execute("SELECT r.user_id,u.status FROM access_recovery_requests r JOIN users u ON u.id=r.user_id WHERE r.id=%s AND r.status='pending' FOR UPDATE OF r,u",(request_id,))
            row=cur.fetchone()
            if not row:return jsonify(error='Solicitação não disponível.'),404
            user_id,status=row
            cur.execute('SELECT 1 FROM platform_owner_grants WHERE user_id=%s AND revoked_at IS NULL',(user_id,))
            if cur.fetchone() and decision=='issue':return jsonify(error='A recuperação do dono exige manutenção autenticada no servidor.'),403
            cur.execute("UPDATE access_recovery_requests SET status=%s,resolved_at=now(),resolved_by=%s WHERE id=%s",('issued' if decision=='issue' else 'rejected',actor['user_id'],request_id))
            if decision=='issue':
                raw,digest=generate_token()
                kind='activation' if status=='invited' else 'recovery'
                expiry=utcnow()+(INVITATION_TIMEOUT if kind=='activation' else RECOVERY_TIMEOUT)
                if kind=='activation':
                    cur.execute('UPDATE invitations SET revoked_at=now() WHERE user_id=%s AND used_at IS NULL AND revoked_at IS NULL',(user_id,))
                    cur.execute('INSERT INTO invitations(id,user_id,token_hash,issued_by,expires_at) VALUES(%s,%s,%s,%s,%s)',(uuid.uuid4(),user_id,digest,actor['user_id'],expiry))
                else:
                    cur.execute('UPDATE recovery_tokens SET revoked_at=now() WHERE user_id=%s AND used_at IS NULL AND revoked_at IS NULL',(user_id,))
                    cur.execute("INSERT INTO recovery_tokens(id,user_id,token_hash,issued_by,delivery_kind,reason,expires_at,reset_mfa) VALUES(%s,%s,%s,%s,'assisted',%s,%s,%s)",(uuid.uuid4(),user_id,digest,actor['user_id'],reason.strip(),expiry,reset))
            cur.execute("INSERT INTO audit_events(id,actor_user_id,subject_user_id,action,result,correlation_id,metadata) VALUES(%s,%s,%s,'access.recovery.resolve','success',%s,jsonb_build_object('decision',%s,'resetAuthenticator',%s))",(uuid.uuid4(),actor['user_id'],user_id,g.request_id,decision,reset))
        return jsonify(status='issued',token=raw,kind=kind,expiresAt=expiry.isoformat()) if raw else jsonify(status='rejected')
