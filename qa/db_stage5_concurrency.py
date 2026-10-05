"""Stage 5: real concurrent writes against an explicitly disposable database."""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid

sys.path.insert(0, "/site")

from auth import hash_password
from server import app, connect, initialize


PASSWORD = "Concorrencia1!"


def expect(response, status, label):
    if response.status_code != status:
        raise AssertionError(f"{label}: esperado {status}, recebido {response.status_code}: {response.get_data(as_text=True)}")
    return response.get_json(silent=True)


def seed(login, roles):
    user_id, membership_id = uuid.uuid4(), uuid.uuid4()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,activated_at,password_changed_at) VALUES(%s,%s,%s,%s,%s,'active',now(),now())",
            (user_id, login, login, login, hash_password(PASSWORD)),
        )
        cur.execute(
            "INSERT INTO memberships(id,user_id,condominium_id,status,starts_at) VALUES(%s,%s,'sqa','active',now())",
            (membership_id, user_id),
        )
        for role in roles:
            cur.execute(
                "INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,starts_at,basis) VALUES(%s,%s,%s,'sqa',%s,now(),'QA concorrência')",
                (uuid.uuid4(), membership_id, user_id, role),
            )


def login(identifier):
    client = app.test_client()
    body = expect(client.post("/api/auth/login", json={"login": identifier, "password": PASSWORD}), 200, f"login {identifier}")
    return client, body["csrf_token"]


def mutate(client, csrf, method, path, payload=None, headers=None):
    return client.open(
        path,
        method=method,
        json=payload if payload is not None else {},
        headers={"X-CSRF-Token": csrf, **(headers or {})},
    )


def record_document(record_id, title, revision=1):
    return {
        "id": record_id,
        "title": title,
        "text": "Teste transacional.",
        "textHtml": "<p>Teste transacional.</p>",
        "category": "Serviço",
        "local": "Área comum",
        "date": "2026-10-04",
        "who": "Equipe",
        "progress": "Concluído",
        "status": "draft",
        "revision": revision,
        "history": [],
        "photos": [],
    }


def edition_document(edition_id, source):
    return {
        "id": edition_id,
        "title": "Informe concorrente",
        "period": "Outubro de 2026",
        "status": "draft",
        "version": 1,
        "cover": "/images/jardim.jpg",
        "blocks": [{
            "id": "bloco-concorrente",
            "type": "Manutenção",
            "title": "Serviço concluído",
            "body": "<p>Conteúdo aprovado.</p>",
            "photos": [],
            "sources": [{"id": source["id"], "revision": source["revision"], "title": source["title"]}],
        }],
    }


def race(callables):
    barrier = threading.Barrier(len(callables))
    results = [None] * len(callables)
    errors = []

    def worker(index, callback):
        try:
            barrier.wait(timeout=10)
            response = callback()
            results[index] = (response.status_code, response.get_json(silent=True))
        except BaseException as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(index, callback), daemon=True) for index, callback in enumerate(callables)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    if errors or any(thread.is_alive() for thread in threads):
        raise AssertionError(f"falha no executor concorrente: errors={errors}, alive={[t.is_alive() for t in threads]}")
    return results


def main():
    if os.environ.get("QA_DISPOSABLE_DATABASE") != "YES":
        raise SystemExit("Recusado: use somente banco descartável.")
    initialize()
    seed("operador.concurrent", ("encarregado",))
    seed("editor.concurrent", ("editor",))
    seed("gestor.concurrent", ("gestor",))

    operator_a, csrf_a = login("operador.concurrent")
    operator_b, csrf_b = login("operador.concurrent")
    editor, editor_csrf = login("editor.concurrent")
    manager_a, manager_csrf_a = login("gestor.concurrent")
    manager_b, manager_csrf_b = login("gestor.concurrent")

    record_id = "concurrent-record"
    created = expect(
        mutate(operator_a, csrf_a, "POST", "/api/records", {"document": record_document(record_id, "Inicial")}),
        201,
        "criação inicial",
    )["document"]

    updates = race([
        lambda: mutate(operator_a, csrf_a, "PATCH", f"/api/records/{record_id}", {"expectedRevision": created["revision"], "document": record_document(record_id, "Vencedor A", created["revision"])}),
        lambda: mutate(operator_b, csrf_b, "PATCH", f"/api/records/{record_id}", {"expectedRevision": created["revision"], "document": record_document(record_id, "Vencedor B", created["revision"])}),
    ])
    if sorted(status for status, _ in updates) != [200, 409]:
        raise AssertionError(f"atualizações simultâneas não produziram um vencedor: {updates}")
    winning_update = next(body["document"] for status, body in updates if status == 200)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT document FROM records WHERE id=%s", (record_id,))
        stored = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM record_revisions WHERE record_id=%s", (record_id,))
        revision_count_after_update = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM audit_events WHERE action='record.edit' AND entity_id=%s", (record_id,))
        edit_audits = cur.fetchone()[0]
    if stored["title"] != winning_update["title"] or revision_count_after_update != 2 or edit_audits != 1:
        raise AssertionError("a transação perdedora deixou efeito parcial")

    submitted = race([
        lambda: mutate(operator_a, csrf_a, "POST", f"/api/records/{record_id}/submit", {"expectedRevision": winning_update["revision"]}),
        lambda: mutate(operator_b, csrf_b, "POST", f"/api/records/{record_id}/submit", {"expectedRevision": winning_update["revision"]}),
    ])
    if sorted(status for status, _ in submitted) != [200, 409]:
        raise AssertionError(f"envio simultâneo não foi serializado: {submitted}")
    submitted_doc = next(body["document"] for status, body in submitted if status == 200)

    reviewed = race([
        lambda: mutate(manager_a, manager_csrf_a, "POST", f"/api/records/{record_id}/review", {"decision": "ready", "expectedRevision": submitted_doc["revision"]}),
        lambda: mutate(manager_b, manager_csrf_b, "POST", f"/api/records/{record_id}/review", {"decision": "ready", "expectedRevision": submitted_doc["revision"]}),
    ])
    if sorted(status for status, _ in reviewed) != [200, 409]:
        raise AssertionError(f"revisão simultânea não foi serializada: {reviewed}")
    ready = next(body["document"] for status, body in reviewed if status == 200)

    edition_id = "concurrent-edition"
    edition = expect(
        mutate(editor, editor_csrf, "POST", "/api/editions", {"document": edition_document(edition_id, ready)}),
        201,
        "criação da edição",
    )["document"]
    submitted_edition = expect(
        mutate(editor, editor_csrf, "POST", f"/api/editions/{edition_id}/submit", {"expectedRevision": edition["version"]}),
        201,
        "envio da edição",
    )
    revision_id = submitted_edition["revisionId"]
    expect(
        mutate(manager_a, manager_csrf_a, "POST", f"/api/edition-revisions/{revision_id}/decisions", {"decision": "approved"}),
        200,
        "aprovação",
    )

    publications = race([
        lambda: mutate(manager_a, manager_csrf_a, "POST", f"/api/edition-revisions/{revision_id}/publish", {}, {"Idempotency-Key": "same-publication"}),
        lambda: mutate(manager_b, manager_csrf_b, "POST", f"/api/edition-revisions/{revision_id}/publish", {}, {"Idempotency-Key": "same-publication"}),
    ])
    if sorted(status for status, _ in publications) != [200, 201]:
        raise AssertionError(f"publicação idempotente simultânea falhou: {publications}")
    publication_ids = {body["publicationId"] for _, body in publications}
    if len(publication_ids) != 1:
        raise AssertionError("a mesma chave idempotente produziu publicações diferentes")

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_publications WHERE edition_revision_id=%s", (revision_id,))
        publication_rows = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM audit_events WHERE action='publication.create' AND revision_id=%s", (revision_id,))
        publication_audits = cur.fetchone()[0]
        cur.execute("SELECT count(*),max(revision_number),count(DISTINCT revision_number) FROM record_revisions WHERE record_id=%s", (record_id,))
        total_revisions, max_revision, distinct_revisions = cur.fetchone()
    if publication_rows != 1 or publication_audits != 1:
        raise AssertionError("a repetição idempotente duplicou publicação ou auditoria")
    if (total_revisions, max_revision, distinct_revisions) != (4, 4, 4):
        raise AssertionError("a sequência de revisões contém lacuna ou duplicação")

    print(json.dumps({
        "passed": True,
        "recordUpdateStatuses": sorted(status for status, _ in updates),
        "recordSubmitStatuses": sorted(status for status, _ in submitted),
        "recordReviewStatuses": sorted(status for status, _ in reviewed),
        "publicationStatuses": sorted(status for status, _ in publications),
        "recordRevisions": total_revisions,
        "distinctRecordRevisions": distinct_revisions,
        "editAuditEvents": edit_audits,
        "publicationRows": publication_rows,
        "publicationAuditEvents": publication_audits,
        "loserPartialEffects": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
