import os,hashlib,uuid
from pathlib import Path
from server import connect
from auth import hash_password,generate_token
assert os.environ.get('DB_NAME','').startswith('sgc_owner_qa_')
password=Path('/run/secrets/qa_password').read_text().strip()
key=Path(os.environ['OWNER_TOTP_FILE']).read_text().strip()
with connect() as conn,conn.cursor() as cur:
    cur.execute("UPDATE users SET password_hash=%s WHERE login_normalized IN ('rodrigo','marcelo','elcio','grangeiro','andre','claudio')",(hash_password(password),))
    cur.execute('UPDATE sessions SET revoked_at=now()')
    cur.execute('DELETE FROM user_mfa')
    cur.execute('UPDATE owner_access_state SET secret_fingerprint=%s,enrolled_at=NULL,last_counter=-1,attempts=0,attempt_window=now()',(hashlib.sha256(key.encode()).hexdigest(),))
    cur.execute("UPDATE access_recovery_requests SET status='rejected' WHERE status='pending'")
    cur.execute("UPDATE users SET status='invited',password_hash=NULL WHERE login_normalized='andre' RETURNING id")
    uid=cur.fetchone()[0];raw,digest=generate_token()
    cur.execute('UPDATE invitations SET revoked_at=now() WHERE user_id=%s AND used_at IS NULL',(uid,))
    cur.execute("INSERT INTO invitations(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,now()+interval '48 hours')",(uuid.uuid4(),uid,digest))
Path('/tmp/qa-beta-invitation').write_text(raw)
print('BETA_BROWSER_FIXTURE_READY: synthetic only')
