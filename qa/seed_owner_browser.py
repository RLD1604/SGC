import os,hashlib
from pathlib import Path
from server import connect
from auth import hash_password
assert os.environ.get('DB_NAME','').startswith('sgc_owner_qa_')
password=Path('/run/secrets/qa_password').read_text().strip()
key=Path(os.environ['OWNER_TOTP_FILE']).read_text().strip()
with connect() as conn,conn.cursor() as cur:
    cur.execute("UPDATE users SET password_hash=%s WHERE login_normalized IN ('rodrigo','qa.operator','qa.admin')",(hash_password(password),))
    cur.execute('UPDATE owner_session_proofs SET expires_at=now()')
    cur.execute('UPDATE owner_access_state SET secret_fingerprint=%s,enrolled_at=NULL,last_counter=-1,attempts=0,attempt_window=now()',(hashlib.sha256(key.encode()).hexdigest(),))
print('SYNTHETIC_QA_BROWSER_READY')
