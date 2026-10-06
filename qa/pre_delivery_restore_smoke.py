"""Stage 6 smoke on the fixed restored snapshot; NEVER initialize/migrate it.

Keys must be provided from the decrypted recovery package by the isolated runner.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import secrets
import time
import traceback
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

EXPECTED_RUN = '20261006T010242Z-6f9a2a78'
step = 'restore_guard'
safe_assertions = set()
result = {'passed': False, 'stage': 6, 'runId': EXPECTED_RUN}


def require(value, label):
    safe_assertions.add(label)
    if not value:
        raise AssertionError(label)


def run():
    global step
    dbname = os.environ.get('DB_NAME', '')
    require(dbname.startswith('sgc_owner_qa_restore'), 'Restored QA database required')
    require(os.environ.get('SGC_RESTORE_RUN_ID') == EXPECTED_RUN, 'Snapshot run mismatch')
    from server import app, connect
    from flask.testing import FlaskClient
    from auth import generate_token
    from owner_console import totp

    class MountedClient(FlaskClient):
        def open(self, *args, **kwargs):
            base = app.config.get('APP_BASE_PATH', '')
            if args and isinstance(args[0], str) and base and not args[0].startswith(base + '/'):
                args = (base + args[0],) + args[1:]
            return super().open(*args, **kwargs)

    app.test_client_class = MountedClient
    step = 'snapshot_baseline'
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT current_database()')
        require(cur.fetchone()[0] == dbname, 'Actual database mismatch')
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
        table_count = cur.fetchone()[0]
        require(table_count == 37, 'Restored table count differs')
        cur.execute('SELECT version FROM schema_versions ORDER BY version')
        schema_versions = [row[0] for row in cur.fetchall()]
        cur.execute('SELECT count(*) FROM records UNION ALL SELECT count(*) FROM editions UNION ALL SELECT count(*) FROM publications UNION ALL SELECT count(*) FROM official_publications UNION ALL SELECT count(*) FROM media')
        counts = [row[0] for row in cur.fetchall()]
        require(sum(counts) == 0, 'Snapshot content must be empty')
        cur.execute("SELECT count(*) FROM users WHERE status='active'")
        require(cur.fetchone()[0] == 1, 'Expected one active snapshot user')
        cur.execute("SELECT count(*) FROM platform_owner_grants g JOIN users u ON u.id=g.user_id WHERE g.revoked_at IS NULL AND g.starts_at<=now() AND u.status='active'")
        require(cur.fetchone()[0] == 1, 'Expected one active owner')
        cur.execute("SELECT count(*) FROM users WHERE status='invited'")
        require(cur.fetchone()[0] == 5, 'Expected five invited snapshot users')
        cur.execute('SELECT count(*) FROM pg_index WHERE NOT indisvalid OR NOT indisready')
        require(cur.fetchone()[0] == 0, 'Invalid restored indexes')
        cur.execute("SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated")
        require(cur.fetchone()[0] == 0, 'Unvalidated restored constraints')
        cur.execute('SELECT count(*) FROM role_grants g LEFT JOIN memberships m ON m.id=g.membership_id WHERE m.id IS NULL OR g.user_id<>m.user_id OR g.condominium_id<>m.condominium_id')
        require(cur.fetchone()[0] == 0, 'Restored grant membership mismatch')
        cur.execute('SELECT id,user_id,token_hash,expires_at,used_at,revoked_at FROM invitations ORDER BY id')
        original_invites = cur.fetchall()
        require(len(original_invites) == 5 and all(row[4] is None and row[5] is None for row in original_invites), 'Expected five untouched invitations')
        cur.execute('SELECT user_id,secret_ciphertext FROM user_mfa ORDER BY user_id')
        existing_mfa = cur.fetchall()
        cur.execute('SELECT secret_fingerprint FROM owner_access_state')
        owner_fingerprints = [row[0] for row in cur.fetchall()]
    result.update(tablesCount=table_count, initialContentCount=sum(counts), schema=schema_versions,
                  invalidIndexes=0, unvalidatedConstraints=0, grantsConsistent=True)

    step = 'recovered_keys'
    # Only paths injected by the restoration runner; no local .secrets access.
    key_paths = [Path(os.environ[name]) for name in ('USER_MFA_KEY_FILE', 'OWNER_TOTP_FILE')]
    require(all('.secrets' not in path.parts for path in key_paths), 'Local secrets paths forbidden')
    restored_cipher = Fernet(key_paths[0].read_bytes().strip())
    owner_key = key_paths[1].read_text().strip()
    require(len(base64.b32decode(owner_key, casefold=True)) == 20, 'Recovered owner key invalid')
    fingerprint = hashlib.sha256(owner_key.encode()).hexdigest()
    require(all(value == fingerprint for value in owner_fingerprints), 'Recovered owner fingerprint mismatch')
    for _, ciphertext in existing_mfa:
        plaintext = restored_cipher.decrypt(bytes(ciphertext)).decode()
        require(len(base64.b32decode(plaintext, casefold=True)) == 20, 'Recovered user MFA secret invalid')
    result['existingMfaRowsValidated'] = len(existing_mfa)

    step = 'synthetic_authentication'
    uid, mid, grant, invite_id = [str(uuid.uuid4()) for _ in range(4)]
    login = 'restore.' + secrets.token_hex(8)
    password = 'Restore-' + secrets.token_urlsafe(18) + '!9A'
    raw, token_hash = generate_token()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status,mfa_required) VALUES(%s,'Synthetic restore QA',%s,%s,'invited',true)", (uid, login, login))
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,'sqa')", (mid, uid))
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa','operador','Synthetic restore QA')", (grant, mid, uid))
        cur.execute("INSERT INTO invitations(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,now()+interval '1 hour')", (invite_id, uid, token_hash))
    client = app.test_client()
    require(client.post('/api/auth/activate', json={'token': raw, 'password': password}).status_code == 200, 'Synthetic activation failed')
    logged = client.post('/api/auth/login', json={'login': login, 'password': password})
    require(logged.status_code == 200 and logged.get_json()['mfaRequired'], 'Synthetic login MFA gate failed')
    headers = {'X-CSRF-Token': logged.get_json()['csrf_token']}
    require(client.get('/api/workspace').status_code == 401, 'Synthetic pending MFA accessed workspace')
    setup = client.post('/api/auth/mfa/setup', json={}, headers=headers)
    require(setup.status_code == 200, 'Synthetic MFA setup failed')
    synthetic_key = setup.get_json()['setupKey']
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT secret_ciphertext FROM user_mfa WHERE user_id=%s', (uid,))
        require(restored_cipher.decrypt(bytes(cur.fetchone()[0])).decode() == synthetic_key, 'Recovered cipher cannot decrypt synthetic MFA')
    require(client.post('/api/auth/mfa/verify', json={'code': totp(synthetic_key, int(time.time() // 30))}, headers=headers).status_code == 200, 'Synthetic MFA verification failed')
    require(client.get('/api/workspace').status_code == 200, 'Synthetic workspace failed')
    result['recoveredMfaKeysValid'] = True

    step = 'synthetic_record_write'
    document = {'id': str(uuid.uuid4()), 'title': 'Synthetic restore QA', 'text': '<p>Synthetic restoration smoke</p>', 'category': 'Obra', 'local': 'QA', 'date': '2026-10-06', 'who': 'QA', 'progress': 'Em andamento', 'photos': [], 'status': 'draft', 'revision': 1}
    created = client.post('/api/records', json={'document': document, 'condominiumId': 'sqa'}, headers=headers)
    require(created.status_code == 201, 'Synthetic record creation failed')
    canonical = created.get_json()['document']
    edited = client.patch('/api/records/' + document['id'], json={'document': {**canonical, 'title': 'Synthetic restore QA edited'}, 'expectedRevision': 1}, headers=headers)
    require(edited.status_code == 200 and edited.get_json()['document']['revision'] == 2, 'Synthetic record edit failed')
    workspace = client.get('/api/workspace')
    require(workspace.status_code == 200 and document['id'] in [row['id'] for row in workspace.get_json()['state']['records']], 'Synthetic record not visible')

    step = 'original_invites_preserved'
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT id,user_id,token_hash,expires_at,used_at,revoked_at FROM invitations WHERE id<>%s ORDER BY id', (invite_id,))
        require(cur.fetchall() == original_invites, 'Original invitations changed')
        cur.execute("SELECT count(*) FROM users WHERE status='invited'")
        require(cur.fetchone()[0] == 5, 'Original invited users changed')
        cur.execute('SELECT count(*) FROM media')
        require(cur.fetchone()[0] == 0, 'Unexpected media changes')
    result.update(fiveOriginalInvitesPreserved=True, syntheticFlowPassed=True,
                  initialMediaCount=0, mediaIntegrity='empty_snapshot_no_media_to_hash', passed=True)


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run()
    except Exception as error:
        frames = traceback.extract_tb(error.__traceback__)
        result.update(passed=False, failedStep=step, errorType=type(error).__name__,
                      failedAssertion=str(error) if isinstance(error, AssertionError) and str(error) in safe_assertions else 'Unhandled restore runner error',
                      lineNumber=frames[-1].lineno if frames else None)
        print(json.dumps(result))
        raise SystemExit(1)
    print(json.dumps(result))
