"""Stage 6 integration/pilot against an explicitly disposable PostgreSQL."""
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("AI_FREE_TIER_CONFIRMED", "false")

from auth import hash_password
from server import app, connect, initialize

PASSWORD = "Frase de teste segura!2026"


def assert_status(response, expected, label):
    if response.status_code != expected:
        raise AssertionError(f"{label}: esperado {expected}, recebido {response.status_code}: {response.get_data(as_text=True)}")
    return response.get_json(silent=True)


def seed_user(login, role):
    user_id, membership_id, grant_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,activated_at,password_changed_at) VALUES(%s,%s,%s,%s,%s,'active',now(),now())", (user_id, login.title(), login, login, hash_password(PASSWORD)))
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id,status,starts_at) VALUES(%s,%s,'sqa','active',now())", (membership_id, user_id))
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,starts_at,basis) VALUES(%s,%s,%s,'sqa',%s,now(),'Piloto automatizado da etapa 6')", (grant_id, membership_id, user_id, role))
    return str(user_id)


def login(login):
    client = app.test_client()
    result = assert_status(client.post("/api/auth/login", json={"login": login, "password": PASSWORD}), 200, f"login {login}")
    return client, result["csrf_token"]


def mutate(client, csrf, method, path, payload=None, headers=None):
    combined = {"X-CSRF-Token": csrf, **(headers or {})}
    return client.open(path, method=method, json=payload if payload is not None else {}, headers=combined)


def record_document(record_id, title):
    return {"id": record_id, "title": title, "text": "Serviço realizado e documentado.", "textHtml": "<p>Serviço realizado e documentado.</p>", "category": "Serviço", "local": "Área comum", "date": "2026-09-24", "who": "Equipe", "progress": "Concluído", "status": "draft", "revision": 1, "history": [], "photos": []}


def edition_document(edition_id, source):
    return {"id": edition_id, "title": "Informe piloto", "period": "Setembro de 2026", "status": "draft", "version": 1, "cover": "/images/jardim.jpg", "blocks": [{"id": "bloco-piloto", "type": "Manutenção", "title": "Serviço concluído", "body": "<p>Conteúdo aprovado.</p>", "photos": [], "sources": [{"id": source["id"], "revision": source["revision"], "title": source["title"]}]}]}


def main():
    if os.environ.get("QA_DISPOSABLE_DATABASE") != "YES":
        raise SystemExit("Recusado: defina QA_DISPOSABLE_DATABASE=YES somente no banco temporário.")
    initialize()
    users = {role: seed_user(role, role) for role in ("encarregado", "supervisor", "editor", "gestor", "sindico", "administrador_tecnico")}
    clients = {role: login(role) for role in users}

    anonymous = app.test_client()
    assert_status(anonymous.get("/api/workspace"), 401, "workspace anônimo")
    assert_status(anonymous.get("/api/state"), 410, "API global fechada")
    assert_status(anonymous.get("/api/media/" + "a" * 64), 404, "mídia global fechada")

    staff, staff_csrf = clients["encarregado"]
    supervisor, supervisor_csrf = clients["supervisor"]
    manager, manager_csrf = clients["gestor"]
    editor, editor_csrf = clients["editor"]
    admin, admin_csrf = clients["administrador_tecnico"]

    draft_id, submitted_id = "pilot-draft", "pilot-submitted"
    draft = assert_status(mutate(staff, staff_csrf, "POST", "/api/records", {"document": record_document(draft_id, "Rascunho privado")}), 201, "criar rascunho")["document"]
    submitted = assert_status(mutate(staff, staff_csrf, "POST", "/api/records", {"document": record_document(submitted_id, "Registro enviado")}), 201, "criar registro")["document"]
    submitted = assert_status(mutate(staff, staff_csrf, "POST", f"/api/records/{submitted_id}/submit"), 200, "enviar registro")["document"]

    supervisor_state = assert_status(supervisor.get("/api/workspace"), 200, "workspace supervisor")["state"]
    if {item["id"] for item in supervisor_state["records"]} & {draft_id, submitted_id}:
        raise AssertionError("Supervisor leu documento de outra pessoa sem atribuição.")
    assert_status(mutate(supervisor, supervisor_csrf, "POST", f"/api/records/{submitted_id}/review", {"decision": "ready"}), 404, "supervisor não confere")
    assert_status(mutate(supervisor, supervisor_csrf, "PATCH", f"/api/records/{draft_id}", {"expectedRevision": 1, "document": record_document(draft_id, "Tentativa IDOR")}), 404, "IDOR bloqueado")

    manager_state = assert_status(manager.get("/api/workspace"), 200, "workspace gestor")["state"]
    visible = {item["id"] for item in manager_state["records"]}
    if submitted_id not in visible or draft_id in visible:
        raise AssertionError("Filtro de rascunhos/enviados do gestor está incorreto.")
    ready = assert_status(mutate(manager, manager_csrf, "POST", f"/api/records/{submitted_id}/review", {"decision": "ready"}), 200, "conferência do gestor")["document"]

    assert_status(admin.get("/api/workspace"), 200, "workspace admin técnico")
    assert_status(mutate(admin, admin_csrf, "POST", "/api/records", {"document": record_document("admin-forbidden", "Negado")}), 403, "admin técnico sem editorial")

    edition_id = "pilot-edition"
    edition = assert_status(mutate(editor, editor_csrf, "POST", "/api/editions", {"document": edition_document(edition_id, ready)}), 201, "editor cria informe")["document"]
    submitted_edition = assert_status(mutate(editor, editor_csrf, "POST", f"/api/editions/{edition_id}/submit", {"expectedRevision": edition["version"]}), 201, "editor envia informe")
    revision_id = submitted_edition["revisionId"]
    assert_status(mutate(editor, editor_csrf, "POST", f"/api/edition-revisions/{revision_id}/decisions", {"decision": "approved"}), 404, "editor não aprova")
    assert_status(mutate(manager, manager_csrf, "PATCH", f"/api/editions/{edition_id}", {"expectedRevision": edition["version"], "document": edition}), 404, "revisão congelada não edita")
    assert_status(mutate(manager, manager_csrf, "POST", f"/api/edition-revisions/{revision_id}/decisions", {"decision": "approved"}), 200, "gestor aprova")
    publication = assert_status(mutate(manager, manager_csrf, "POST", f"/api/edition-revisions/{revision_id}/publish", {}, {"Idempotency-Key": "pilot-publication"}), 201, "publicação oficial")
    repeated = assert_status(mutate(manager, manager_csrf, "POST", f"/api/edition-revisions/{revision_id}/publish", {}, {"Idempotency-Key": "pilot-publication"}), 200, "idempotência publicação")
    if publication["publicationId"] != repeated["publicationId"]:
        raise AssertionError("Repetição idempotente criou outra publicação.")
    artifact = manager.get(f"/api/publications/{publication['publicationId']}/artifact")
    assert_status(artifact, 200, "download oficial")
    if hashlib.sha256(artifact.data).hexdigest() != publication["artifactHash"]:
        raise AssertionError("Bytes oficiais divergem do hash aprovado.")

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM record_metadata WHERE legacy_import AND author_user_id IS NOT NULL")
        if cur.fetchone()[0]:
            raise AssertionError("Migração inventou autoria para conteúdo legado.")
        cur.execute("UPDATE users SET status='disabled',auth_generation=auth_generation+1,disabled_at=now() WHERE id=%s", (users["encarregado"],))
        cur.execute("UPDATE sessions SET revoked_at=now(),revoke_reason='pilot_disable' WHERE user_id=%s AND revoked_at IS NULL", (users["encarregado"],))
        cur.execute("SELECT count(*) FROM audit_events WHERE action IN ('record.create','record.submit','record.review','edition.submit','edition.approved','publication.create') AND result='success'")
        audited = cur.fetchone()[0]
    assert_status(staff.get("/api/workspace"), 401, "desativação imediata")
    if audited < 6:
        raise AssertionError(f"Auditoria crítica incompleta: {audited} eventos.")

    print(json.dumps({"passed": True, "profiles": len(users), "globalApiClosed": True, "idorBlocked": True, "legacyAuthorshipPreserved": True, "officialArtifactHash": publication["artifactHash"], "auditEvents": audited}, ensure_ascii=False))


if __name__ == "__main__":
    main()
