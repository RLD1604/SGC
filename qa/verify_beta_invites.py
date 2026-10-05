"""Read-only receipt verification; prints neither tokens nor hashes."""
import json
from pathlib import Path
from server import connect
from auth import token_digest
people=json.loads(Path('/verify/invitations.json').read_text())
assert len(people)==5 and len({p['token'] for p in people})==5
with connect() as conn,conn.cursor() as cur:
    for person in people:
        cur.execute("SELECT i.token_hash,u.status,u.mfa_required,r.role,i.expires_at>now() FROM users u JOIN invitations i ON i.user_id=u.id JOIN role_grants r ON r.user_id=u.id WHERE u.login_normalized=%s AND i.used_at IS NULL AND i.revoked_at IS NULL AND r.revoked_at IS NULL",(person['login'],))
        rows=cur.fetchall();assert len(rows)==1
        digest,status,mfa,role,valid=rows[0]
        assert bytes(digest)==token_digest(person['token']) and status=='invited' and mfa and valid and role==person['role']
    for table in ('records','editions','publications','media','official_publications'):
        cur.execute('SELECT count(*) FROM '+table);assert cur.fetchone()[0]==0
    cur.execute("SELECT count(*) FROM users WHERE status='active'");assert cur.fetchone()[0]==1
    cur.execute('SELECT count(*) FROM platform_owner_grants WHERE revoked_at IS NULL');assert cur.fetchone()[0]==1
print('FIVE_PRIVATE_INVITES_VALID_AND_MATCH_MANUALS; content=0; activeOwner=1; ownerGrant=1')
