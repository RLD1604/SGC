"""Stage 3 isolation gates. Only a new empty sgc_owner_qa_ database."""
import contextlib
import base64
import hashlib
import io
import json
import os
import secrets
import traceback
import tempfile
import uuid
from pathlib import Path
from cryptography.fernet import Fernet

if not os.environ.get('DB_NAME', '').startswith('sgc_owner_qa_'):
    raise RuntimeError('Dedicated QA database required')

step = 'database_guard'
checks = []
safe_assertions = set()
last_http_status = None
last_validation_error = None


def require(value, label):
    safe_assertions.add(label)
    if not value:
        raise AssertionError(label)


def run():
    global step
    from server import app, connect, initialize
    from auth import hash_password
    from flask.testing import FlaskClient
    from psycopg2.extras import Json
    from editorial_api import digest

    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT current_database()')
        require(cur.fetchone()[0] == os.environ['DB_NAME'], 'Actual database mismatch')
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        require(cur.fetchone()[0] == 0, 'Database must be new and empty')
    initialize()

    class MountedClient(FlaskClient):
        def open(self, *args, **kwargs):
            global last_http_status, last_validation_error
            base = app.config.get('APP_BASE_PATH', '')
            if args and isinstance(args[0], str) and base and not args[0].startswith(base + '/'):
                args = (base + args[0],) + args[1:]
            response = super().open(*args, **kwargs)
            last_http_status = response.status_code
            last_validation_error = None
            if response.status_code == 400:
                body = response.get_json(silent=True) or {}
                # Exact, content-independent validator strings only.
                if body.get('error') in {'Blocos inválidos.', 'Estrutura do acervo inválida.', 'Quantidade de documentos inválida.'}:
                    last_validation_error = body['error']
            return response

    app.test_client_class = MountedClient
    password = 'Isolation-' + secrets.token_urlsafe(18) + '!9A'

    def user(name, condo):
        uid, mid, grant = [str(uuid.uuid4()) for _ in range(3)]
        with connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,mfa_required) VALUES(%s,%s,%s,%s,%s,'active',false)", (uid, name, name, name, hash_password(password)))
            cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,%s)", (mid, uid, condo))
            cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,%s,'administrador','QA')", (grant, mid, uid, condo))
        client = app.test_client()
        response = client.post('/api/auth/login', json={'login': name, 'password': password})
        require(response.status_code == 200, 'Synthetic login failed')
        return uid, mid, grant, client, {'X-CSRF-Token': response.get_json()['csrf_token']}

    def record(uid, condo):
        rid = str(uuid.uuid4())
        document = {'id': rid, 'title': 'Synthetic isolation QA', 'text': '<p>synthetic</p>', 'category': 'Obra', 'local': 'QA', 'date': '2026-10-06', 'who': 'QA', 'progress': 'Em andamento', 'photos': [], 'status': 'draft', 'revision': 1}
        with connect() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO records(id,document) VALUES(%s,%s)', (rid, Json(document)))
            cur.execute('INSERT INTO record_metadata(record_id,condominium_id,author_user_id,current_revision) VALUES(%s,%s,%s,1)', (rid, condo, uid))
        return rid, document

    def visible(client, rid):
        response = client.get('/api/workspace')
        require(response.status_code == 200, 'Authenticated workspace failed')
        return rid in [row['id'] for row in response.get_json()['state']['records']]

    step = 'immediate_access_revocation'
    for kind in ('role', 'membership'):
        uid, mid, grant, client, headers = user('qa-' + kind, 'sqa')
        rid, document = record(uid, 'sqa')
        require(visible(client, rid), 'Initial resource not visible')
        with connect() as conn, conn.cursor() as cur:
            if kind == 'role':
                cur.execute('UPDATE role_grants SET revoked_at=now() WHERE id=%s', (grant,))
            else:
                cur.execute("UPDATE memberships SET status='inactive' WHERE id=%s", (mid,))
        require(not visible(client, rid), 'Revoked access still visible')
        require(client.patch('/api/records/' + rid, json={'document': document, 'expectedRevision': 1}, headers=headers).status_code in (403, 404), 'Revoked mutation permitted')
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT current_revision FROM record_metadata WHERE record_id=%s', (rid,))
            require(cur.fetchone()[0] == 1, 'Denied mutation changed revision')
            cur.execute('SELECT count(*) FROM sessions WHERE user_id=%s AND revoked_at IS NULL', (uid,))
            require(cur.fetchone()[0] == 1, 'Access gate tested an inactive session')
        checks.append(kind + '_revocation_immediate_read_mutation_denied')

    step = 'cross_condominium_direct_downloads'
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO condominiums(id,name) VALUES('qa-isolation-other','Synthetic other QA')")
    author, _, author_grant, authorized, good_headers = user('qa-author', 'sqa')
    _, _, _, foreign, foreign_headers = user('qa-foreign', 'qa-isolation-other')
    rid, document = record(author, 'sqa')
    media_bytes = b'synthetic-media-fixture'
    media_id = hashlib.sha256(media_bytes).hexdigest()
    eid, revision, approval, publication = [str(uuid.uuid4()) for _ in range(4)]
    artifact = b'<!doctype html><title>Synthetic isolation QA</title>'
    snapshot = {'id': eid, 'title': 'Synthetic edition', 'records': [],
                'blocks': [], 'period': '2026-10', 'version': 1}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO media(id,mime,width,height,content) VALUES(%s,'image/png',1,1,%s)", (media_id, media_bytes))
        cur.execute("INSERT INTO media_references(media_id,condominium_id,document_type,document_id) VALUES(%s,'sqa','record',%s)", (media_id, rid))
        cur.execute('INSERT INTO editions(id,document) VALUES(%s,%s)', (eid, Json(snapshot)))
        cur.execute("INSERT INTO edition_metadata(edition_id,condominium_id,author_user_id,workflow_state) VALUES(%s,'sqa',%s,'published')", (eid, author))
        cur.execute("INSERT INTO edition_revisions(id,edition_id,revision_number,author_user_id,snapshot,snapshot_hash,renderer_version,artifact_html,artifact_hash,state) VALUES(%s,%s,1,%s,%s,%s,'synthetic-qa',%s,%s,'published')", (revision, eid, author, Json(snapshot), digest(snapshot), artifact, digest(artifact)))
        cur.execute("INSERT INTO approval_decisions(id,edition_revision_id,approver_user_id,role_grant_id,decision,snapshot_hash,artifact_hash) VALUES(%s,%s,%s,%s,'approved',%s,%s)", (approval, revision, author, author_grant, digest(snapshot), digest(artifact)))
        cur.execute("INSERT INTO official_publications(id,condominium_id,edition_revision_id,approval_id,created_by,artifact_html,artifact_hash,idempotency_key) VALUES(%s,'sqa',%s,%s,%s,%s,%s,'qa-isolation')", (publication, revision, approval, author, artifact, digest(artifact)))
    media_route = '/api/documents/record/' + rid + '/media/' + media_id
    artifact_route = '/api/publications/' + publication + '/artifact'
    require(authorized.get(media_route).status_code == 200, 'Authorized media control failed')
    require(authorized.get(artifact_route).status_code == 200, 'Authorized artifact control failed')
    require(foreign.get(media_route).status_code == 404, 'Cross condominium media disclosed')
    require(foreign.get(artifact_route).status_code == 404, 'Cross condominium artifact disclosed')
    require(authorized.get('/api/media/' + media_id).status_code == 404, 'Unscoped media route permitted')
    checks.append('cross_condominium_media_artifact_denied_with_positive_controls')

    step = 'csrf_and_external_origin'
    mutation = '/api/records/' + rid
    payload = {'document': {**document, 'title': 'Synthetic edited'}, 'expectedRevision': 1}
    for headers in ({}, {'X-CSRF-Token': 'incorrect'}, foreign_headers):
        require(authorized.patch(mutation, json=payload, headers=headers).status_code == 403, 'Invalid CSRF accepted')
    require(authorized.patch(mutation, json=payload, headers={**good_headers, 'Origin': 'https://external-qa.invalid'}).status_code == 403, 'External origin accepted')
    require(authorized.patch(mutation, json=payload, headers={**good_headers, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403, 'Cross-site fetch accepted')
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT current_revision FROM record_metadata WHERE record_id=%s', (rid,))
        require(cur.fetchone()[0] == 1, 'Rejected requests changed record')
    require(authorized.patch(mutation, json=payload, headers=good_headers).status_code == 200, 'Valid CSRF control failed')
    checks.append('missing_wrong_other_session_csrf_and_external_origin_denied')


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory(prefix='pre-delivery-isolation-', dir='/tmp') as temp:
            owner_file = Path(temp) / 'owner-key'
            cipher_file = Path(temp) / 'cipher-key'
            owner_file.write_text(base64.b32encode(secrets.token_bytes(20)).decode())
            cipher_file.write_bytes(Fernet.generate_key())
            owner_file.chmod(0o600)
            cipher_file.chmod(0o600)
            os.environ['OWNER_TOTP_FILE'] = str(owner_file)
            os.environ['USER_MFA_KEY_FILE'] = str(cipher_file)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                run()
    except Exception as error:
        frames = traceback.extract_tb(error.__traceback__)
        safe_message = str(error) if isinstance(error, AssertionError) and str(error) in safe_assertions else 'Unhandled runner or application error'
        print(json.dumps({'passed': False, 'stage': 3, 'failedStep': step, 'checksPassed': checks,
                          'errorType': type(error).__name__, 'failedAssertion': safe_message,
                          'lineNumber': frames[-1].lineno if frames else None,
                          'lastHttpStatus': last_http_status,
                          'validationError': last_validation_error}))
        raise SystemExit(1)
    print(json.dumps({'passed': True, 'stage': 3, 'checksPassed': checks}))
