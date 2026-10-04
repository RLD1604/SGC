"""Etapa 2: autenticação, CSRF e administração de contas em PostgreSQL descartável."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/site")

from auth import hash_password
from server import app, connect, initialize

PASSWORD = "SenhaSegura1!"
NEW_PASSWORD = "NovaSenha2@"


def expect(response, status, label):
    if response.status_code != status:
        raise AssertionError(
            f"{label}: esperado {status}, recebido {response.status_code}: "
            f"{response.get_data(as_text=True)}"
        )
    return response.get_json(silent=True)


def seed_user(login, roles, condominium="sqa"):
    user_id, membership_id = uuid.uuid4(), uuid.uuid4()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users
               (id,display_name,login_display,login_normalized,password_hash,status,activated_at,password_changed_at)
               VALUES(%s,%s,%s,%s,%s,'active',now(),now())""",
            (user_id, login.title(), login, login, hash_password(PASSWORD)),
        )
        cur.execute(
            "INSERT INTO memberships(id,user_id,condominium_id,status,starts_at) VALUES(%s,%s,%s,'active',now())",
            (membership_id, user_id, condominium),
        )
        for role in roles:
            cur.execute(
                """INSERT INTO role_grants
                   (id,membership_id,user_id,condominium_id,role,starts_at,basis)
                   VALUES(%s,%s,%s,%s,%s,now(),'QA descartável da Etapa 2')""",
                (uuid.uuid4(), membership_id, user_id, condominium, role),
            )
    return str(user_id)


def login(identifier, password=PASSWORD):
    client = app.test_client()
    response = client.post("/api/auth/login", json={"login": identifier, "password": password})
    return client, response


def csrf_post(client, path, csrf, payload=None):
    return client.post(path, json=payload or {}, headers={"X-CSRF-Token": csrf})


def main():
    if os.environ.get("QA_DISPOSABLE_DATABASE") != "YES":
        raise SystemExit("Recusado: use somente banco descartável.")
    initialize()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO condominiums(id,name) VALUES('outro','Outro Condomínio QA') ON CONFLICT DO NOTHING")
    manager_id = seed_user("gestor.qa", ("gestor", "responsavel_acessos"))
    worker_id = seed_user("operador.qa", ("encarregado",))
    seed_user("editor.qa", ("editor",))
    seed_user("gestor.outro", ("gestor", "responsavel_acessos"), "outro")

    deliveries = []
    app.config["AUTH_DELIVER_TOKEN"] = lambda kind, user, token: deliveries.append(
        {"kind": kind, "user": dict(user), "token": token}
    )

    anonymous = app.test_client()
    expect(anonymous.get("/api/workspace"), 401, "workspace anônimo")
    expect(anonymous.get("/api/state"), 410, "API global encerrada")
    for identifier, password in (("inexistente", PASSWORD), ("gestor.qa", "Errada1!x"), ("", PASSWORD)):
        expect(anonymous.post("/api/auth/login", json={"login": identifier, "password": password}), 401, "login negado")

    manager, response = login("gestor.qa")
    manager_session = expect(response, 200, "login gestor")
    csrf = manager_session["csrf_token"]
    if any(key in manager_session for key in ("session_token", "access_token", "refresh_token")):
        raise AssertionError("Resposta de sessão expôs token opaco.")
    expect(manager.get("/api/auth/session"), 200, "sessão ativa")
    expect(manager.post("/api/auth/logout", json={}), 403, "logout sem CSRF")
    expect(manager.post("/api/auth/logout", json={}, headers={"X-CSRF-Token": "incorreto"}), 403, "logout com CSRF incorreto")

    expect(manager.post("/api/records", json={"document": {}}), 403, "mutação sem CSRF")
    cross = csrf_post(manager, "/api/auth/invitations", csrf, {
        "login": "fora.escopo", "displayName": "Fora do Escopo", "roles": ["editor"], "condominiumId": "outro"
    })
    expect(cross, 403, "convite fora do condomínio")

    editor, editor_response = login("editor.qa")
    editor_csrf = expect(editor_response, 200, "login editor")["csrf_token"]
    expect(csrf_post(editor, "/api/auth/invitations", editor_csrf, {
        "login": "sem.permissao", "displayName": "Sem Permissão", "roles": ["editor"]
    }), 403, "editor não administra contas")

    invitation = csrf_post(manager, "/api/auth/invitations", csrf, {
        "login": "novo.qa", "displayName": "Novo QA", "roles": ["editor", "gestor"], "condominiumId": "sqa"
    })
    invitation_body = expect(invitation, 201, "convite válido")
    activation = next(item for item in deliveries if item["kind"] == "activation" and item["user"]["login"] == "novo.qa")
    if activation["token"] in invitation.get_data(as_text=True):
        raise AssertionError("Resposta do convite expôs o token de ativação.")
    expect(anonymous.post("/api/auth/activate", json={"token": activation["token"], "password": "fraca"}), 400, "senha fraca")
    expect(anonymous.post("/api/auth/activate", json={"token": activation["token"], "password": PASSWORD}), 200, "ativação")
    expect(anonymous.post("/api/auth/activate", json={"token": activation["token"], "password": PASSWORD}), 400, "token de ativação de uso único")
    invited, invited_response = login("novo.qa")
    invited_csrf = expect(invited_response, 200, "login ativado")["csrf_token"]

    # Recuperação responde do mesmo modo para login existente ou desconhecido.
    unknown = expect(anonymous.post("/api/auth/recovery/request", json={"login": "ninguem.qa"}), 202, "recuperação desconhecida")
    known = expect(anonymous.post("/api/auth/recovery/request", json={"login": "novo.qa"}), 202, "recuperação conhecida")
    if unknown != known:
        raise AssertionError("Recuperação permite enumerar contas.")
    recovery = next(item for item in deliveries if item["kind"] == "recovery" and item["user"]["login"] == "novo.qa")
    expect(anonymous.post("/api/auth/recovery/complete", json={"token": recovery["token"], "password": "fraca"}), 400, "senha fraca na recuperação")
    expect(anonymous.post("/api/auth/recovery/complete", json={"token": recovery["token"], "password": NEW_PASSWORD}), 200, "recuperação concluída")
    expect(invited.get("/api/auth/session"), 401, "sessão anterior revogada")
    expect(login("novo.qa", PASSWORD)[1], 401, "senha anterior revogada")
    recovered, recovered_response = login("novo.qa", NEW_PASSWORD)
    expect(recovered_response, 200, "login com nova senha")
    expect(anonymous.post("/api/auth/recovery/complete", json={"token": recovery["token"], "password": PASSWORD}), 400, "token de recuperação de uso único")

    # Desativação exige motivo, impede autodesativação e revoga imediatamente a sessão alvo.
    worker, worker_response = login("operador.qa")
    expect(worker_response, 200, "login operador")
    expect(csrf_post(manager, f"/api/auth/users/{worker_id}/disable", csrf, {}), 400, "desativação sem motivo")
    expect(csrf_post(manager, f"/api/auth/users/{manager_id}/disable", csrf, {"reason": "autoteste"}), 409, "autodesativação")
    expect(csrf_post(manager, f"/api/auth/users/{worker_id}/disable", csrf, {"reason": "encerramento do teste"}), 200, "desativação")
    expect(worker.get("/api/auth/session"), 401, "sessão do desativado revogada")
    expect(csrf_post(manager, f"/api/auth/users/{worker_id}/disable", csrf, {"reason": "repetição"}), 404, "desativação idempotente segura")

    # Expiração no banco invalida a sessão sem depender do relógio do navegador.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE sessions SET idle_expires_at=now()-interval '1 second' WHERE user_id=%s AND revoked_at IS NULL", (manager_id,))
        cur.execute("SELECT token_hash FROM invitations WHERE user_id=%s ORDER BY created_at DESC LIMIT 1", (invitation_body["userId"],))
        invitation_hash = cur.fetchone()[0]
        cur.execute("SELECT token_hash FROM recovery_tokens WHERE user_id=%s ORDER BY created_at DESC LIMIT 1", (invitation_body["userId"],))
        recovery_hash = cur.fetchone()[0]
    expect(manager.get("/api/auth/session"), 401, "sessão expirada")
    if len(bytes(invitation_hash)) != 32 or len(bytes(recovery_hash)) != 32:
        raise AssertionError("Tokens não foram persistidos como SHA-256.")
    if activation["token"].encode() in bytes(invitation_hash) or recovery["token"].encode() in bytes(recovery_hash):
        raise AssertionError("Token bruto foi persistido.")

    # Logout correto encerra uma sessão ainda válida.
    recovered_csrf = expect(recovered_response, 200, "sessão recuperada")["csrf_token"]
    expect(csrf_post(recovered, "/api/auth/logout", recovered_csrf), 200, "logout")
    expect(recovered.get("/api/auth/session"), 401, "sessão após logout")

    print(json.dumps({
        "passed": True,
        "checks": 30,
        "csrf": True,
        "activation": True,
        "recovery": True,
        "crossCondominium": True,
        "sessionRevocation": True,
        "rawTokensPersisted": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
