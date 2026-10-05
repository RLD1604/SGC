"""Authenticated per-document editorial API and immutable approval flow.

The module deliberately has no compatibility endpoint for the former global
``/api/state`` write.  Authorization is evaluated for every document and every
action.  Approved artifacts are rendered once, stored as bytes, hashed, and
published by copying those exact bytes.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from flask import Response, jsonify, request, g
from psycopg2.extras import Json

RENDERER_VERSION = "sqa-server-html-1"
MEDIA_PATTERN = re.compile(r"/api/media/([a-f0-9]{64})")
CONTEXT_MEDIA_PATTERN = re.compile(r"/api/documents/(?:record|edition|edition_revision|official_publication)/[^/]+/media/([a-f0-9]{64})")


def _actor_user(actor):
    return actor["user_id"] if isinstance(actor, dict) else actor.user_id


def _actor_condominiums(actor):
    return actor.get("memberships", []) if isinstance(actor, dict) else actor.condominium_ids


def canonical_bytes(value):
    """Stable UTF-8 representation used for all approval hashes."""
    def normalize(item):
        if isinstance(item, str):
            return unicodedata.normalize("NFC", item)
        if isinstance(item, list):
            return [normalize(value) for value in item]
        if isinstance(item, dict):
            return {key: normalize(item[key]) for key in sorted(item)}
        return item
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical_bytes(value)).hexdigest()


def _photo_ids(document):
    found = set()
    for match in MEDIA_PATTERN.finditer(json.dumps(document, ensure_ascii=False)):
        found.add(match.group(1))
    return found


def _internalize_media(document):
    """Convert authorized contextual URLs back to stable internal references."""
    encoded = json.dumps(document, ensure_ascii=False)
    return json.loads(CONTEXT_MEDIA_PATTERN.sub(lambda match: "/api/media/" + match.group(1), encoded))


def _contextualize_media(document, document_type, document_id):
    encoded = json.dumps(document, ensure_ascii=False)
    prefix = f"/api/documents/{document_type}/{document_id}/media/"
    return json.loads(MEDIA_PATTERN.sub(lambda match: prefix + match.group(1), encoded))


def _replace_media_with_data(document, cur):
    """Embed immutable media so the approved HTML is self-contained."""
    encoded = {}
    for media_id in _photo_ids(document):
        cur.execute("SELECT mime,content FROM media WHERE id=%s", (media_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Uma imagem da revisão não está mais disponível.")
        encoded[media_id] = f"data:{row[0]};base64,{base64.b64encode(bytes(row[1])).decode('ascii')}"
    return MEDIA_PATTERN.sub(lambda match: encoded[match.group(1)], json.dumps(document, ensure_ascii=False))


def render_edition(document, cur, *, draft=False):
    # Work from a round-trip copy after replacing media references. This also
    # guarantees the exact bytes shown to the approver are the bytes published.
    materialized = json.loads(_replace_media_with_data(document, cur))
    def esc(value):
        return html.escape(str(value or ""), quote=True)
    sections = []
    for block in materialized.get("blocks", []):
        photos = "".join(
            f'<figure><img src="{esc(photo.get("src"))}" alt="{esc(photo.get("caption") or photo.get("phase"))}">'
            f'<figcaption>{esc(photo.get("caption"))}</figcaption></figure>'
            for photo in block.get("photos", []) if not photo.get("hidden")
        )
        # Body has already passed the server rich-text sanitizer before submit.
        sections.append(f'<section><p class="kind">{esc(block.get("type"))}</p>'
                        f'<h2>{esc(block.get("title"))}</h2>{block.get("body", "")}<div class="photos">{photos}</div></section>')
    watermark = '<div class="draft">RASCUNHO — NÃO APROVADO</div>' if draft else ""
    css = "body{font:16px system-ui;color:#17222d;max-width:900px;margin:auto;padding:40px}header{padding:48px;background:#243247;color:white}section{padding:32px 0;border-bottom:1px solid #ddd}.photos{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.photos img{width:100%;height:auto}.draft{position:fixed;inset:42% 0;text-align:center;font-size:42px;color:#a00;opacity:.28;transform:rotate(-18deg)}.kind{font-size:12px;text-transform:uppercase;letter-spacing:.12em}"
    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>"
            + esc(materialized.get("title")) + "</title><style>" + css + "</style></head><body>" + watermark
            + "<header><h1>" + esc(materialized.get("title")) + "</h1><p>" + esc(materialized.get("period"))
            + "</p></header>" + "".join(sections) + "</body></html>").encode("utf-8")


def register_editorial(app, connect, current_principal, require_session, require_mutation, can, validate_state, normalize_state, read_state, audit):
    def principal():
        value = current_principal()
        if not value:
            raise PermissionError("Autenticação necessária.")
        return value

    def resource(metadata, document=None):
        return {
            "condominium_id": metadata[0], "author_user_id": str(metadata[1]) if metadata[1] else None,
            "revision": metadata[2], "state": (metadata[3] if len(metadata) > 3 else (document or {}).get("status")),
            "document": document, "document_id": (document or {}).get("id"),
        }

    def deny(hidden=True):
        return jsonify(error="Documento não encontrado." if hidden else "Ação não permitida."), 404 if hidden else 403

    @app.errorhandler(PermissionError)
    def auth_required(error):
        return jsonify(error=str(error)), 401

    @app.get("/api/workspace")
    @require_session
    def workspace_filtered():
        actor = principal()
        output = {"records": [], "editions": [], "publications": []}
        g.delivered_resources=[]
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT r.document,m.condominium_id,m.author_user_id,m.current_revision,r.id FROM records r JOIN record_metadata m ON m.record_id=r.id ORDER BY r.updated_at,r.id")
            for document, condominium_id, author_id, revision, _ in cur.fetchall():
                if can(actor, "item.read", resource((condominium_id, author_id, revision), document), cur=cur):
                    output["records"].append(_contextualize_media(document, "record", document["id"]))
                    g.delivered_resources.append({"type":"record","id":document["id"]})
            cur.execute("SELECT e.document,m.condominium_id,m.author_user_id,m.current_revision,m.workflow_state,e.id FROM editions e JOIN edition_metadata m ON m.edition_id=e.id ORDER BY e.updated_at,e.id")
            for document, condominium_id, author_id, revision, state, _ in cur.fetchall():
                if can(actor, "edition.read", resource((condominium_id, author_id, revision, state), document), cur=cur):
                    item = _contextualize_media(document, "edition", document["id"])
                    item["_workflowState"] = state
                    item["_serverRevision"] = revision
                    cur.execute("SELECT id FROM edition_revisions WHERE edition_id=%s ORDER BY created_at DESC LIMIT 1", (document["id"],))
                    latest = cur.fetchone()
                    item["_pendingRevisionId"] = str(latest[0]) if latest and state in ("pending_approval","approved") else None
                    output["editions"].append(item)
                    g.delivered_resources.append({"type":"edition","id":document["id"]})
            cur.execute("SELECT p.id,e.snapshot,p.published_at,p.condominium_id FROM official_publications p JOIN edition_revisions e ON e.id=p.edition_revision_id WHERE p.condominium_id = ANY(%s) ORDER BY p.published_at", (list(_actor_condominiums(actor)),))
            for publication_id, snapshot, published_at, condominium_id in cur.fetchall():
                if not can(actor, "publication.read", {"condominium_id": condominium_id}, cur=cur):
                    continue
                item = dict(snapshot)
                item.update(id=str(publication_id), at=published_at.isoformat(), official=True)
                output["publications"].append(_contextualize_media(item, "official_publication", str(publication_id)))
                g.delivered_resources.append({'type':'publication','id':str(publication_id)})
        return jsonify(state=output)

    @app.post("/api/records")
    @require_mutation
    def create_record():
        actor = principal()
        body = request.get_json() or {}
        document = body.get("document")
        condominium_id = body.get("condominiumId", "sqa")
        if not can(actor, "item.create", {"condominium_id": condominium_id}, cur=None):
            return deny(False)
        if not isinstance(document, dict):
            raise ValueError("Documento inválido.")
        document = _internalize_media(dict(document))
        document["revision"] = 1
        document["status"] = "draft"
        with connect() as conn, conn.cursor() as cur:
            state = read_state(cur)
            if any(row["id"] == document.get("id") for row in state["records"]):
                return jsonify(error="O registro já existe."), 409
            state["records"].append(document)
            validate_state(state)
            normalize_state(state, cur)
            document = next(row for row in state["records"] if row["id"] == document["id"])
            cur.execute("INSERT INTO records(id,document) VALUES(%s,%s)", (document["id"], Json(document)))
            cur.execute("INSERT INTO record_metadata(record_id,condominium_id,author_user_id,current_revision,legacy_import) VALUES(%s,%s,%s,1,false)", (document["id"], condominium_id, _actor_user(actor)))
            revision_id = uuid.uuid4()
            cur.execute("INSERT INTO record_revisions(id,record_id,revision_number,author_user_id,snapshot,snapshot_hash,workflow_state) VALUES(%s,%s,1,%s,%s,%s,%s)", (revision_id, document["id"], _actor_user(actor), Json(document), digest(document), document["status"]))
            _sync_media_refs(cur, condominium_id, "record", document["id"], document)
            audit(cur, actor, "record.create", "record", document["id"], "success", revision_id=str(revision_id))
        return jsonify(document=_contextualize_media(document, "record", document["id"])), 201

    @app.patch("/api/records/<record_id>")
    @require_mutation
    def update_record(record_id):
        actor = principal()
        body = request.get_json() or {}
        expected = body.get("expectedRevision")
        incoming = body.get("document")
        if not isinstance(expected, int) or not isinstance(incoming, dict):
            raise ValueError("Informe o documento e a revisão esperada.")
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT r.document,m.condominium_id,m.author_user_id,m.current_revision FROM records r JOIN record_metadata m ON m.record_id=r.id WHERE r.id=%s FOR UPDATE", (record_id,))
            row = cur.fetchone()
            if not row or not can(actor, "item.edit", resource((row[1], row[2], row[3]), row[0]), cur=cur):
                return deny()
            if row[3] != expected:
                return jsonify(error="O registro foi alterado por outra pessoa.", currentRevision=row[3]), 409
            document = _internalize_media(dict(incoming))
            document["id"] = record_id
            document["revision"] = expected + 1
            # Workflow changes use dedicated action endpoints.
            document["status"] = row[0].get("status", "draft")
            trash_changed=bool(document.get('deletedAt'))!=bool(row[0].get('deletedAt'))
            if trash_changed and not can(actor,'accounts.manage',{'condominium_id':row[1]},cur=cur):
                return deny(False)
            changed_fields=[key for key in ('title','text','category','local','date','who','progress','photos','deletedAt','feedback','feedbackHtml') if document.get(key)!=row[0].get(key)]
            state = read_state(cur)
            state["records"] = [document if item["id"] == record_id else item for item in state["records"]]
            validate_state(state)
            normalize_state(state, cur)
            document = next(item for item in state["records"] if item["id"] == record_id)
            cur.execute("UPDATE records SET document=%s,updated_at=now() WHERE id=%s", (Json(document), record_id))
            cur.execute("UPDATE record_metadata SET current_revision=%s,updated_at=now() WHERE record_id=%s", (expected + 1, record_id))
            revision_id = uuid.uuid4()
            cur.execute("INSERT INTO record_revisions(id,record_id,revision_number,author_user_id,snapshot,snapshot_hash,workflow_state) VALUES(%s,%s,%s,%s,%s,%s,%s)", (revision_id, record_id, expected + 1, _actor_user(actor), Json(document), digest(document), document["status"]))
            _sync_media_refs(cur, row[1], "record", record_id, document)
            action=('record.trash' if document.get('deletedAt') else 'record.restore') if trash_changed else 'record.edit'
            g.diagnostic_changed_fields=changed_fields
            audit(cur, actor, action, "record", record_id, "success", revision_id=str(revision_id),metadata={'changedFields':changed_fields})
        return jsonify(document=_contextualize_media(document, "record", record_id))

    @app.post("/api/records/<record_id>/submit")
    @require_mutation
    def submit_record(record_id):
        return _record_transition(record_id, "review", "item.submit", "record.submit", connect, principal(), can, audit, expected_revision=(request.get_json(silent=True) or {}).get("expectedRevision"))

    @app.post("/api/records/<record_id>/review")
    @require_mutation
    def review_record(record_id):
        decision = (request.get_json() or {}).get("decision")
        if decision not in ("ready", "fix"):
            raise ValueError("Decisão de conferência inválida.")
        body = request.get_json(silent=True) or {}
        return _record_transition(record_id, decision, "item.review", "record.review", connect, principal(), can, audit, reason=body.get("reason"), expected_revision=body.get("expectedRevision"))

    @app.post("/api/editions")
    @require_mutation
    def create_edition():
        actor = principal()
        body = request.get_json() or {}
        document = body.get("document")
        condominium_id = body.get("condominiumId", "sqa")
        if not can(actor, "edition.edit", {"condominium_id": condominium_id, "state": "draft"}, cur=None):
            return deny(False)
        if not isinstance(document, dict):
            raise ValueError("Informe inválido.")
        document = _internalize_media(dict(document))
        document["version"] = 1
        document["status"] = "draft"
        with connect() as conn, conn.cursor() as cur:
            state = read_state(cur)
            if any(row["id"] == document.get("id") for row in state["editions"]):
                return jsonify(error="O informe já existe."), 409
            state["editions"].append(document)
            validate_state(state)
            normalize_state(state, cur)
            document = next(row for row in state["editions"] if row["id"] == document["id"])
            cur.execute("INSERT INTO editions(id,document) VALUES(%s,%s)", (document["id"], Json(document)))
            cur.execute("INSERT INTO edition_metadata(edition_id,condominium_id,author_user_id,current_revision,workflow_state,legacy_import) VALUES(%s,%s,%s,1,'draft',false)", (document["id"], condominium_id, _actor_user(actor)))
            _sync_media_refs(cur, condominium_id, "edition", document["id"], document)
            audit(cur, actor, "edition.create", "edition", document["id"], "success")
        return jsonify(document=_contextualize_media(document, "edition", document["id"])), 201

    @app.patch("/api/editions/<edition_id>")
    @require_mutation
    def update_edition(edition_id):
        actor = principal()
        body = request.get_json() or {}
        expected, incoming = body.get("expectedRevision"), body.get("document")
        if not isinstance(expected, int) or not isinstance(incoming, dict):
            raise ValueError("Informe o documento e a revisão esperada.")
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT e.document,m.condominium_id,m.author_user_id,m.current_revision,m.workflow_state FROM editions e JOIN edition_metadata m ON m.edition_id=e.id WHERE e.id=%s FOR UPDATE", (edition_id,))
            row = cur.fetchone()
            if not row or not can(actor, "edition.edit", resource((row[1], row[2], row[3], row[4]), row[0]), cur=cur):
                return deny()
            if row[3] != expected:
                return jsonify(error="O informe foi alterado por outra pessoa.", currentRevision=row[3]), 409
            document = _internalize_media(dict(incoming))
            document.update(id=edition_id, version=expected + 1, status="draft")
            state = read_state(cur)
            state["editions"] = [document if item["id"] == edition_id else item for item in state["editions"]]
            validate_state(state)
            normalize_state(state, cur)
            document = next(item for item in state["editions"] if item["id"] == edition_id)
            cur.execute("UPDATE editions SET document=%s,updated_at=now() WHERE id=%s", (Json(document), edition_id))
            cur.execute("UPDATE edition_metadata SET current_revision=%s,workflow_state='draft',updated_at=now() WHERE edition_id=%s", (expected + 1, edition_id))
            _sync_media_refs(cur, row[1], "edition", edition_id, document)
            audit(cur, actor, "edition.edit", "edition", edition_id, "success")
        return jsonify(document=_contextualize_media(document, "edition", edition_id))

    @app.post("/api/editions/<edition_id>/submit")
    @require_mutation
    def submit_edition(edition_id):
        actor = principal()
        body = request.get_json() or {}
        expected = body.get("expectedRevision")
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT e.document,m.condominium_id,m.author_user_id,m.current_revision,m.workflow_state FROM editions e JOIN edition_metadata m ON m.edition_id=e.id WHERE e.id=%s FOR UPDATE", (edition_id,))
            row = cur.fetchone()
            if not row or not can(actor, "edition.submit", resource((row[1], row[2], row[3], row[4]), row[0]), cur=cur):
                return deny()
            if row[3] != expected or row[4] not in ("draft", "returned"):
                return jsonify(error="O informe não está na revisão esperada para envio."), 409
            if not row[0].get("blocks"):
                raise ValueError("Adicione ao menos um bloco antes de enviar.")
            snapshot = dict(row[0])
            artifact = render_edition(snapshot, cur)
            revision_id = uuid.uuid4()
            cur.execute("INSERT INTO edition_revisions(id,edition_id,revision_number,author_user_id,snapshot,snapshot_hash,renderer_version,artifact_html,artifact_hash,state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending_approval')", (revision_id, edition_id, row[3], _actor_user(actor), Json(snapshot), digest(snapshot), RENDERER_VERSION, artifact, digest(artifact)))
            cur.execute("UPDATE edition_metadata SET workflow_state='pending_approval',updated_at=now() WHERE edition_id=%s", (edition_id,))
            _sync_media_refs(cur, row[1], "edition_revision", str(revision_id), snapshot)
            audit(cur, actor, "edition.submit", "edition", edition_id, "success", revision_id=str(revision_id))
        return jsonify(revisionId=str(revision_id), snapshotHash=digest(snapshot), artifactHash=digest(artifact)), 201

    @app.post("/api/edition-revisions/<revision_id>/decisions")
    @require_mutation
    def decide_revision(revision_id):
        actor = principal()
        body = request.get_json() or {}
        decision, reason = body.get("decision"), body.get("reason")
        if decision not in ("approved", "returned") or (decision == "returned" and not str(reason or "").strip()):
            raise ValueError("Decisão ou motivo inválido.")
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT r.edition_id,r.snapshot,r.snapshot_hash,r.artifact_html,r.artifact_hash,r.state,m.condominium_id FROM edition_revisions r JOIN edition_metadata m ON m.edition_id=r.edition_id WHERE r.id=%s FOR UPDATE", (revision_id,))
            row = cur.fetchone()
            target = {"condominium_id": row[6], "state": row[5], "revision_id": revision_id} if row else None
            grant = can(actor, "edition.approve", target, cur=cur, return_grant=True) if row else None
            if not row or not grant:
                return deny()
            if row[5] != "pending_approval":
                return jsonify(error="Essa revisão já recebeu uma decisão."), 409
            if digest(row[1]) != row[2] or digest(bytes(row[3])) != row[4]:
                return jsonify(error="A revisão preservada não passou na verificação de integridade."), 409
            decision_id = uuid.uuid4()
            cur.execute("INSERT INTO approval_decisions(id,edition_revision_id,approver_user_id,role_grant_id,decision,reason,snapshot_hash,artifact_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (decision_id, revision_id, _actor_user(actor), grant, decision, reason, row[2], row[4]))
            cur.execute("UPDATE edition_revisions SET state=%s WHERE id=%s", (decision, revision_id))
            cur.execute("UPDATE edition_metadata SET workflow_state=%s,updated_at=now() WHERE edition_id=%s", (decision, row[0]))
            audit(cur, actor, "edition." + decision, "edition", row[0], "success", revision_id=revision_id)
        return jsonify(decisionId=str(decision_id), decision=decision)

    @app.post("/api/edition-revisions/<revision_id>/publish")
    @require_mutation
    def publish_revision(revision_id):
        actor = principal()
        operation_id = request.headers.get("Idempotency-Key")
        if not operation_id or not re.fullmatch(r"[\w-]{1,100}", operation_id):
            raise ValueError("Identificação idempotente da publicação é obrigatória.")
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT r.edition_id,r.artifact_html,r.artifact_hash,r.state,m.condominium_id,d.id,d.approver_user_id,g.ends_at,g.revoked_at,u.status,r.snapshot,am.status,am.starts_at,am.ends_at FROM edition_revisions r JOIN edition_metadata m ON m.edition_id=r.edition_id JOIN approval_decisions d ON d.edition_revision_id=r.id AND d.decision='approved' JOIN role_grants g ON g.id=d.role_grant_id JOIN users u ON u.id=d.approver_user_id JOIN memberships am ON am.id=g.membership_id AND am.user_id=d.approver_user_id AND am.condominium_id=m.condominium_id WHERE r.id=%s FOR UPDATE", (revision_id,))
            row = cur.fetchone()
            target = {"condominium_id": row[4], "state": row[3], "revision_id": revision_id} if row else None
            if not row or not can(actor, "publication.export", target, cur=cur):
                return deny()
            cur.execute("SELECT id,artifact_hash FROM official_publications WHERE condominium_id=%s AND idempotency_key=%s", (row[4], operation_id))
            previous = cur.fetchone()
            if previous:
                if previous[1] != row[2]:
                    return jsonify(error="A chave já foi usada para outro conteúdo."), 409
                return jsonify(publicationId=str(previous[0]), artifactHash=previous[1])
            now = datetime.now(timezone.utc)
            if row[3] != "approved" or row[9] != "active" or row[8] is not None or (row[7] is not None and row[7] <= now) or row[11] != "active" or (row[12] is not None and row[12] > now) or (row[13] is not None and row[13] <= now):
                return jsonify(error="A aprovação precisa ser ratificada por aprovador vigente."), 409
            artifact = bytes(row[1])
            if digest(artifact) != row[2]:
                return jsonify(error="O artefato aprovado não passou na verificação de integridade."), 409
            publication_id = uuid.uuid4()
            cur.execute("INSERT INTO official_publications(id,condominium_id,edition_revision_id,approval_id,created_by,artifact_html,artifact_hash,idempotency_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (publication_id, row[4], revision_id, row[5], _actor_user(actor), artifact, row[2], operation_id))
            _sync_media_refs(cur, row[4], "official_publication", str(publication_id), row[10])
            cur.execute("UPDATE edition_revisions SET state='published' WHERE id=%s", (revision_id,))
            cur.execute("UPDATE edition_metadata SET workflow_state='published',updated_at=now() WHERE edition_id=%s", (row[0],))
            audit(cur, actor, "publication.create", "publication", str(publication_id), "success", revision_id=revision_id)
        return jsonify(publicationId=str(publication_id), artifactHash=row[2]), 201

    @app.get("/api/publications/<publication_id>/artifact")
    @require_session
    def publication_artifact(publication_id):
        actor = principal()
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT artifact_html,artifact_hash,condominium_id FROM official_publications WHERE id=%s", (publication_id,))
            row = cur.fetchone()
            if not row or not can(actor, "publication.read", {"condominium_id": row[2]}, cur=cur):
                return deny()
            artifact = bytes(row[0])
            if digest(artifact) != row[1]:
                return jsonify(error="Falha de integridade no artefato oficial."), 503
        return Response(artifact, mimetype="text/html", headers={"Content-Disposition": f'attachment; filename="informe-{publication_id}.html"', "ETag": row[1]})

    @app.get("/api/editions/<edition_id>/draft-export")
    @require_session
    def draft_export(edition_id):
        actor = principal()
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT e.document,m.condominium_id,m.author_user_id,m.current_revision,m.workflow_state FROM editions e JOIN edition_metadata m ON m.edition_id=e.id WHERE e.id=%s", (edition_id,))
            row = cur.fetchone()
            if not row or not can(actor, "edition.read", resource((row[1], row[2], row[3], row[4]), row[0]), cur=cur):
                return deny()
            artifact = render_edition(row[0], cur, draft=True)
        return Response(artifact, mimetype="text/html", headers={"Content-Disposition": f'attachment; filename="rascunho-{edition_id}.html"'})

    @app.get("/api/documents/<document_type>/<document_id>/media/<media_id>")
    @require_session
    def contextual_media(document_type, document_id, media_id):
        actor = principal()
        if document_type not in ("record", "edition", "edition_revision", "official_publication") or not re.fullmatch(r"[a-f0-9]{64}", media_id):
            return deny()
        permission = "item.read" if document_type == "record" else "edition.read"
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT condominium_id FROM media_references WHERE media_id=%s AND document_type=%s AND document_id=%s", (media_id, document_type, document_id))
            ref = cur.fetchone()
            target = {"condominium_id": ref[0], "document_type": document_type, "document_id": document_id} if ref else None
            if target and document_type == "record":
                cur.execute("SELECT m.author_user_id,r.document FROM record_metadata m JOIN records r ON r.id=m.record_id WHERE m.record_id=%s", (document_id,))
                record = cur.fetchone()
                if not record:
                    return deny()
                target.update(author_user_id=record[0], state=record[1].get("status", "draft"))
            if not target or not can(actor, permission, target, cur=cur):
                return deny()
            cur.execute("SELECT mime,content FROM media WHERE id=%s", (media_id,))
            row = cur.fetchone()
            if not row:
                return deny()
        return Response(bytes(row[1]), mimetype=row[0], headers={"Cache-Control": "private, max-age=3600", "ETag": media_id})


def _sync_media_refs(cur, condominium_id, document_type, document_id, document):
    media_ids = _photo_ids(document)
    for media_id in media_ids:
        cur.execute("SELECT DISTINCT condominium_id FROM media_references WHERE media_id=%s", (media_id,))
        owners = {str(row[0]) for row in cur.fetchall()}
        if owners and str(condominium_id) not in owners:
            raise ValueError("Uma foto pertence a outro condomínio.")
    cur.execute("DELETE FROM media_references WHERE document_type=%s AND document_id=%s", (document_type, document_id))
    for media_id in media_ids:
        cur.execute("INSERT INTO media_references(media_id,condominium_id,document_type,document_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING", (media_id, condominium_id, document_type, document_id))


def _record_transition(record_id, target_state, permission, action, connect, actor, can, audit, reason=None, expected_revision=None):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT r.document,m.condominium_id,m.author_user_id,m.current_revision FROM records r JOIN record_metadata m ON m.record_id=r.id WHERE r.id=%s FOR UPDATE", (record_id,))
        row = cur.fetchone()
        target = {"condominium_id": row[1], "author_user_id": str(row[2]) if row[2] else None, "revision": row[3], "state": row[0].get("status"), "document_id": record_id} if row else None
        if not row:
            return jsonify(error="Documento não encontrado."), 404
        if not isinstance(expected_revision, int) or expected_revision != row[3]:
            # A concurrent winner may already have moved the workflow to a
            # state where this transition permission no longer applies.  Keep
            # cross-condominium and out-of-scope documents concealed, but tell
            # an actor who can still read this record to reload instead of
            # incorrectly claiming that the document disappeared.
            if not can(actor, "item.read", target, cur=cur):
                return jsonify(error="Documento não encontrado."), 404
            return jsonify(error="Outra sessão alterou este registro. Recarregue antes de continuar."), 409
        if not can(actor, permission, target, cur=cur):
            return jsonify(error="Documento não encontrado."), 404
        allowed = {("draft", "review"), ("fix", "review"), ("review", "ready"), ("review", "fix")}
        if (row[0].get("status"), target_state) not in allowed:
            return jsonify(error="Transição editorial inválida."), 409
        document = dict(row[0])
        document["status"] = target_state
        document["revision"] = row[3] + 1
        if target_state == "fix":
            if not str(reason or "").strip():
                raise ValueError("Informe o complemento necessário.")
            document["feedback"] = str(reason).strip()
        elif target_state == "ready":
            document["feedback"] = ""
            document["feedbackHtml"] = ""
        cur.execute("UPDATE records SET document=%s,updated_at=now() WHERE id=%s", (Json(document), record_id))
        cur.execute("UPDATE record_metadata SET current_revision=%s,updated_at=now() WHERE record_id=%s", (row[3] + 1, record_id))
        revision_id = uuid.uuid4()
        cur.execute("INSERT INTO record_revisions(id,record_id,revision_number,author_user_id,snapshot,snapshot_hash,workflow_state) VALUES(%s,%s,%s,%s,%s,%s,%s)", (revision_id, record_id, row[3] + 1, _actor_user(actor), Json(document), digest(document), target_state))
        audit(cur, actor, action, "record", record_id, "success", revision_id=str(revision_id), metadata={"decision": target_state})
    return jsonify(document=_contextualize_media(document, "record", record_id))
