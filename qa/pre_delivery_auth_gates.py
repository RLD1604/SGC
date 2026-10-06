"""Stage 2 supplementary HTTP gates; dedicated NEW QA database only.

Run with server modules on PYTHONPATH. Never reads .secrets. Output is sanitized.
"""
import base64
import contextlib
import io
import json
import os
import secrets
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

dbname = os.environ.get('DB_NAME', '')
if not dbname.startswith('sgc_owner_qa_'):
    raise RuntimeError('Dedicated QA database required')

checks = []
step = 'database_guard'
capture = io.StringIO()


def require(condition, label):
    if not condition:
        raise AssertionError(label)


def run():
    global step
    with tempfile.TemporaryDirectory(prefix='pre-delivery-auth-', dir='/tmp') as temp:
        owner_key = base64.b32encode(secrets.token_bytes(20)).decode()
        owner_file = Path(temp) / 'owner-key'
        cipher_file = Path(temp) / 'cipher-key'
        owner_file.write_text(owner_key)
        cipher_file.write_bytes(Fernet.generate_key())
        owner_file.chmod(0o600)
        cipher_file.chmod(0o600)
        os.environ['OWNER_TOTP_FILE'] = str(owner_file)
        os.environ['USER_MFA_KEY_FILE'] = str(cipher_file)
        from server import app, connect, initialize
        from flask.testing import FlaskClient
        from auth import hash_password
        from owner_console import totp

        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT current_database()')
            require(cur.fetchone()[0] == dbname, 'Actual database mismatch')
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            require(cur.fetchone()[0] == 0, 'Database must be freshly created and empty')
        initialize()

        class MountedClient(FlaskClient):
            def open(self, *args, **kwargs):
                base = app.config.get('APP_BASE_PATH', '')
                if args and isinstance(args[0], str) and base and not args[0].startswith(base + '/'):
                    args = (base + args[0],) + args[1:]
                return super().open(*args, **kwargs)

        app.test_client_class = MountedClient
        old_password = 'Old-' + secrets.token_urlsafe(18) + '!9A'
        new_password = 'New-' + secrets.token_urlsafe(18) + '!9A'
        owner_id = str(uuid.uuid4())

        def create_user(name, mfa=True, owner=False):
            uid = str(uuid.uuid4()) if not owner else owner_id
            with connect() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,mfa_required) VALUES(%s,%s,%s,%s,%s,'active',%s)",
                            (uid, name, name, name, hash_password(old_password), mfa))
                if owner:
                    cur.execute('INSERT INTO platform_owner_grants(user_id) VALUES(%s)', (uid,))
                else:
                    mid = str(uuid.uuid4())
                    cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,'sqa')", (mid, uid))
                    cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa','administrador','QA')", (uuid.uuid4(), mid, uid))
            return uid

        def login(name, password=old_password):
            client = app.test_client()
            response = client.post('/api/auth/login', json={'login': name, 'password': password})
            require(response.status_code == 200, 'Login failed')
            return client, {'X-CSRF-Token': response.get_json()['csrf_token']}, response.get_json()

        def enroll(client, headers):
            setup = client.post('/api/auth/mfa/setup', json={}, headers=headers)
            require(setup.status_code == 200, 'MFA setup failed')
            response = client.post('/api/auth/mfa/verify', json={'code': totp(setup.get_json()['setupKey'], int(time.time() // 30))}, headers=headers)
            require(response.status_code == 200, 'MFA enrollment failed')

        def denied(client, headers):
            require(client.get('/api/workspace').status_code == 401, 'Expired read permitted')
            require(client.post('/api/records', json={}, headers=headers).status_code == 401, 'Expired mutation permitted')
            require(client.post('/api/auth/mfa/setup', json={}, headers=headers).status_code == 401, 'Expired MFA setup permitted')
            require(client.post('/api/auth/mfa/verify', json={'code': '000000'}, headers=headers).status_code == 401, 'Expired MFA verification permitted')

        step = 'session_expiry'
        for column in ('idle_expires_at', 'absolute_expires_at'):
            name = 'qa-' + column
            uid = create_user(name)
            client, headers, _ = login(name)
            enroll(client, headers)
            require(client.get('/api/workspace').status_code == 200, 'Session was not usable')
            with connect() as conn, conn.cursor() as cur:
                # Fixed whitelist above; no external SQL identifier.
                cur.execute(f"UPDATE sessions SET {column}=now()-interval '1 second' WHERE user_id=%s", (uid,))
            denied(client, headers)
            checks.append(column + '_read_mutation_mfa_denied')

        step = 'logout_replay'
        uid = create_user('qa-logout')
        client, headers, _ = login('qa-logout')
        enroll(client, headers)
        cookie_name = app.config.get('AUTH_COOKIE_NAME', 'sqa_session')
        csrf_name = app.config.get('AUTH_CSRF_COOKIE_NAME', 'sqa_csrf')
        cookie_path = app.config.get('AUTH_COOKIE_PATH', '/')
        old_cookie = client.get_cookie(cookie_name, path=cookie_path).value
        old_csrf = client.get_cookie(csrf_name, path=cookie_path).value
        require(client.post('/api/auth/logout', json={}, headers=headers).status_code == 200, 'Logout failed')
        require(client.get_cookie(cookie_name, path=cookie_path) is None, 'Logout cookie remains')
        replay = app.test_client()
        replay.set_cookie(cookie_name, old_cookie, path=cookie_path)
        replay.set_cookie(csrf_name, old_csrf, path=cookie_path)
        denied(replay, headers)
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sessions WHERE user_id=%s AND revoked_at IS NULL", (uid,))
            require(cur.fetchone()[0] == 0, 'Logout session remains live')
        checks.append('logout_old_cookie_denied')

        step = 'recovery_without_mfa_reset'
        uid = create_user('qa-recovery')
        first, first_headers, _ = login('qa-recovery')
        enroll(first, first_headers)
        second, second_headers, _ = login('qa-recovery')
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT secret_ciphertext,enrolled_at,last_counter FROM user_mfa WHERE user_id=%s', (uid,))
            mfa_before = cur.fetchone()
            cur.execute('SELECT count(*) FROM sessions WHERE user_id=%s AND revoked_at IS NULL', (uid,))
            require(cur.fetchone()[0] == 2, 'Expected two live recovery sessions')
        create_user('qa-owner', mfa=False, owner=True)
        owner, owner_headers, _ = login('qa-owner')
        require(owner.post('/api/owner/enroll', json={'password': old_password}, headers=owner_headers).status_code == 200, 'Owner enrollment failed')
        require(owner.post('/api/owner/verify', json={'password': old_password, 'code': totp(owner_key, int(time.time() // 30))}, headers=owner_headers).status_code == 200, 'Owner proof failed')
        public = app.test_client()
        require(public.post('/api/auth/recovery/request', json={'login': 'qa-recovery', 'kind': 'password'}).status_code == 202, 'Recovery request failed')
        queue = owner.get('/api/owner/recovery-requests')
        require(queue.status_code == 200 and len(queue.get_json()['requests']) == 1, 'Recovery queue mismatch')
        rid = queue.get_json()['requests'][0]['id']
        body = {'decision': 'issue', 'reason': 'Synthetic verified identity for QA', 'identityConfirmed': True, 'resetAuthenticator': False}
        issued = owner.post('/api/owner/recovery-requests/' + rid + '/resolve', json=body, headers=owner_headers)
        require(issued.status_code == 200, 'Recovery issuance failed')
        token = issued.get_json()['token']
        require(new_password != old_password, 'Recovery password must differ')
        require(public.post('/api/auth/recovery/complete', json={'token': token, 'password': new_password}).status_code == 200, 'Recovery completion failed')
        denied(first, first_headers)
        denied(second, second_headers)
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM sessions WHERE user_id=%s AND revoked_at IS NULL', (uid,))
            require(cur.fetchone()[0] == 0, 'Recovery left a live session')
            cur.execute('SELECT secret_ciphertext,enrolled_at,last_counter FROM user_mfa WHERE user_id=%s', (uid,))
            require(cur.fetchone() == mfa_before, 'Recovery unexpectedly changed MFA')
        require(app.test_client().post('/api/auth/login', json={'login': 'qa-recovery', 'password': old_password}).status_code == 401, 'Old password accepted')
        recovered, recovered_headers, data = login('qa-recovery', new_password)
        require(data['mfaRequired'] and recovered.get('/api/workspace').status_code == 401, 'Recovered login skipped MFA')
        require(recovered.post('/api/auth/mfa/setup', json={}, headers=recovered_headers).get_json() == {'enrolled': True}, 'Recovered MFA enrollment missing')
        checks.extend(['different_password_old_denied_new_accepted', 'all_recovery_sessions_revoked', 'recovery_preserves_mfa'])

        step = 'owner_reject_no_token'
        rejected_uid = create_user('qa-rejected')
        require(public.post('/api/auth/recovery/request', json={'login': 'qa-rejected'}).status_code == 202, 'Reject fixture request failed')
        queue = owner.get('/api/owner/recovery-requests').get_json()['requests']
        require(len(queue) == 1, 'Reject queue mismatch')
        rejected_rid = queue[0]['id']
        response = owner.post('/api/owner/recovery-requests/' + rejected_rid + '/resolve', json={**body, 'decision': 'reject'}, headers=owner_headers)
        require(response.status_code == 200 and response.get_json() == {'status': 'rejected'}, 'Reject response contains unexpected fields')
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM recovery_tokens WHERE user_id=%s', (rejected_uid,))
            require(cur.fetchone()[0] == 0, 'Reject issued recovery token')
            cur.execute('SELECT count(*) FROM invitations WHERE user_id=%s', (rejected_uid,))
            require(cur.fetchone()[0] == 0, 'Reject issued invitation')
            cur.execute('SELECT status FROM access_recovery_requests WHERE id=%s', (rejected_rid,))
            require(cur.fetchone()[0] == 'rejected', 'Reject request state mismatch')
        checks.append('owner_reject_no_token')
        for secret in (old_password, new_password, owner_key, token, old_cookie, old_csrf):
            require(secret not in capture.getvalue(), 'Sensitive output detected')


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            run()
    except Exception:
        # Do not print database errors, response payloads or traceback with secrets.
        print(json.dumps({'passed': False, 'failedStep': step, 'checksPassed': checks}))
        raise SystemExit(1)
    print(json.dumps({'passed': True, 'stage': 2, 'checksPassed': checks}))
