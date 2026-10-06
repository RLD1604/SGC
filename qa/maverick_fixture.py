"""Synthetic pilot users only, in a freshly created isolated QA database."""
import os,uuid,json,secrets
from pathlib import Path
assert os.environ.get('DB_NAME','').startswith('sgc_owner_qa_maverick')
from server import initialize,connect
from auth import generate_token
initialize()
people=[]
with connect() as conn,conn.cursor() as cur:
    cur.execute('SELECT count(*) FROM users');assert cur.fetchone()[0]==0
    for name,role in [('maverick','operador'),('viper','administrador'),('iceman','operador')]:
        uid,mid=uuid.uuid4(),uuid.uuid4();raw,digest=generate_token()
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status,mfa_required) VALUES(%s,%s,%s,%s,'invited',true)",(uid,name.title(),name,name))
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,'sqa')",(mid,uid))
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa',%s,'Synthetic Maverick browser QA')",(uuid.uuid4(),mid,uid,role))
        cur.execute("INSERT INTO invitations(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,now()+interval '48 hours')",(uuid.uuid4(),uid,digest))
        people.append({'login':name,'token':raw,'password':'QA-'+secrets.token_urlsafe(18)+'!9A'})
Path('/tmp/maverick-credentials.json').write_text(json.dumps(people))
print('MAVERICK_FIXTURE_READY: three synthetic invitees, no production data')
