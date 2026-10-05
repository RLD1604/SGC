"""Host-only bootstrap for the explicitly authorized owner account rodrigo."""
import uuid
import os,re
from pathlib import Path
from psycopg2.extras import Json
from server import connect
assert re.fullmatch(r'[A-Z2-7]{32}',Path(os.environ['OWNER_TOTP_FILE']).read_text().strip()), 'MFA secret must be configured before bootstrap'

with connect() as conn,conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE login_normalized='rodrigo' AND status='active'")
    row=cur.fetchone()
    if not row:raise RuntimeError('Active rodrigo account not found; no grant issued')
    cur.execute('SELECT user_id FROM platform_owner_grants FOR UPDATE')
    owners=cur.fetchall()
    if owners and str(owners[0][0])!=str(row[0]):raise RuntimeError('Another owner exists; refuse change')
    cur.execute('INSERT INTO platform_owner_grants(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING RETURNING user_id',(row[0],))
    if cur.fetchone():
        cur.execute("INSERT INTO audit_events(id,subject_user_id,action,result,correlation_id,metadata) VALUES(%s,%s,'platform.owner.bootstrap','success',%s,%s)",(uuid.uuid4(),row[0],str(uuid.uuid4()),Json({'mfaRequired':True,'provisionedBy':'host-cli'})))
print('OWNER_PREPARED: rodrigo; MFA enrollment required; no global editorial access')
