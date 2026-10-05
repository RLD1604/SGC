"""Full HTTP probe restricted to a dedicated synthetic database, never production."""
import os
import io
import contextlib
import secrets
import base64
import uuid
import time
from pathlib import Path
from unittest.mock import patch
from psycopg2.extras import Json

assert os.environ.get('DB_NAME','').startswith('sgc_owner_qa_'), 'Dedicated QA database required'
key=base64.b32encode(secrets.token_bytes(20)).decode()
secret_file=Path('/tmp/owner-test-key')
secret_file.write_text(key)
os.environ['OWNER_TOTP_FILE']=str(secret_file)
from server import app,connect,initialize
from flask.testing import FlaskClient
class MountedClient(FlaskClient):
    def open(self,*args,**kwargs):
        if args and isinstance(args[0],str):
            base=app.config.get('APP_BASE_PATH','')
            if base and not args[0].startswith(base+'/'):args=(base+args[0],)+args[1:]
        return super().open(*args,**kwargs)
app.test_client_class=MountedClient
from auth import hash_password
from owner_console import totp
initialize()
password='QA-'+secrets.token_urlsafe(20)+'!9A'
ids={login:str(uuid.uuid4()) for login in ('rodrigo','qa.operator','qa.admin')}
old_diagnostic,old_business=str(uuid.uuid4()),str(uuid.uuid4())
with connect() as conn,conn.cursor() as cur:
    cur.execute("INSERT INTO diagnostic_events(id,occurred_at,request_id,source,action,result) VALUES(%s,now()-interval '100 days',%s,'server','qa.old','success')",(old_diagnostic,str(uuid.uuid4())))
    cur.execute("INSERT INTO audit_events(id,occurred_at,action,result,correlation_id) VALUES(%s,now()-interval '100 days','qa.immutable','success',%s)",(old_business,str(uuid.uuid4())))
    for login,uid in ids.items():
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status,password_hash) VALUES(%s,%s,%s,%s,'active',%s)",(uid,login,login,login,hash_password(password)))
        member=str(uuid.uuid4())
        cur.execute('INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,\'sqa\')',(member,uid))
        role='operador' if login=='qa.operator' else 'administrador'
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa',%s,'Synthetic QA')",(str(uuid.uuid4()),member,uid,role))
    cur.execute('INSERT INTO platform_owner_grants(user_id) VALUES(%s)',(ids['rodrigo'],))

capture=io.StringIO()
def login(name):
    client=app.test_client()
    response=client.post('/api/auth/login',json={'login':name,'password':password})
    assert response.status_code==200,response.status_code
    return client,{'X-CSRF-Token':response.get_json()['csrf_token']}

with contextlib.redirect_stdout(capture):
    anon=app.test_client()
    assert anon.get('/api/owner/events').status_code==401
    operator,op_headers=login('qa.operator')
    admin,admin_headers=login('qa.admin')
    for client,headers in ((operator,op_headers),(admin,admin_headers)):
        response=client.get('/api/owner/events')
        assert response.status_code==403,('tenant_owner_denial',response.status_code)
        assert client.post('/api/owner/enroll',headers=headers,json={'password':password}).status_code==403
    response=operator.get('/api/workspace')
    assert response.status_code==200
    request_id=response.headers['X-Request-ID']
    assert operator.post('/api/diagnostics/client',json={'kind':'script_error','page':'editor'}).status_code==403
    assert operator.post('/api/diagnostics/client',headers=op_headers,json={'kind':'script_error','page':'editor','message':'PRIVATE_EDITORIAL','password':password,'userId':ids['rodrigo'],'condominiumId':'forged'}).status_code==202
    for _ in range(30):operator.post('/api/diagnostics/client',headers=op_headers,json={'kind':'navigation','page':'inicio'})
    assert operator.post('/api/diagnostics/client',headers=op_headers,json={'kind':'navigation','page':'inicio'}).status_code==429
    document={'id':str(uuid.uuid4()),'title':'Synthetic QA','text':'<p>PRIVATE_EDITORIAL_CONTENT</p>','category':'Obra','local':'QA','date':'2026-10-05','who':'QA','progress':'Em andamento','photos':[],'status':'draft','revision':1}
    response=operator.post('/api/records',headers=op_headers,json={'document':document,'condominiumId':'sqa'})
    assert response.status_code==201,('record_create',response.status_code)
    owner,owner_headers=login('rodrigo')
    assert owner.get('/api/owner/events').status_code==403
    assert owner.post('/api/owner/enroll',json={'password':password}).status_code==403
    assert owner.post('/api/owner/enroll',headers=owner_headers,json={'password':'wrong'}).status_code==403
    response=owner.post('/api/owner/enroll',headers=owner_headers,json={'password':password})
    assert response.status_code==200
    assert response.get_json()['setupKey']==key
    instant=time.time()
    code=totp(key,int(instant//30))
    with patch('owner_console.time.time',return_value=instant):
        assert owner.post('/api/owner/verify',headers=owner_headers,json={'password':password,'code':code}).status_code==200
        assert owner.post('/api/owner/verify',headers=owner_headers,json={'password':password,'code':code}).status_code==403
    response=owner.get('/api/owner/events?requestId='+request_id)
    assert response.status_code==200
    events=response.get_json()['events']
    assert any(event['userId']==ids['qa.operator'] and event['result']=='success' for event in events)
    response=owner.get('/api/owner/events?action=record.create')
    assert any(event['userId']==ids['qa.operator'] and event['result']=='success' and event['httpStatus']==201 for event in response.get_json()['events'])
    assert owner.get('/api/owner/events?action=auth_login&userId='+ids['rodrigo']).get_json()['events']
    assert owner.get('/api/owner/overview').status_code==200
    assert owner.get('/api/owner/events?userId='+'-'*36).status_code==400
    assert owner.get('/api/owner/events?limit=101').status_code==400
    # Identical timestamps must not lose events when paging.
    now='2026-10-05T18:00:00+00:00'
    with connect() as conn,conn.cursor() as cur:
        for _ in range(3):
            cur.execute("INSERT INTO diagnostic_events(id,occurred_at,request_id,source,action,result) VALUES(%s,%s,%s,'server','qa.same_time','success')",(str(uuid.uuid4()),now,str(uuid.uuid4())))
    first=owner.get('/api/owner/events?action=qa.same_time&limit=2').get_json()
    second=owner.get('/api/owner/events?action=qa.same_time&limit=2&before='+first['nextBefore'].replace('+','%2B')+'&beforeId='+first['nextId']).get_json()
    assert len(first['events'])==2 and len(second['events'])==1
    assert owner.post('/api/owner/lock',headers=owner_headers,json={}).status_code==200
    assert owner.get('/api/owner/events').status_code==403
    # A tenant invitation cannot grant platform ownership.
    app.config['AUTH_DELIVER_TOKEN']=lambda *args:None
    assert admin.post('/api/auth/invitations',headers=admin_headers,json={'login':'qa.promote','displayName':'QA','roles':['platform_owner']}).status_code==400
    html=anon.get('/SGC/owner.html') if app.config.get('APP_BASE_PATH') else anon.get('/owner.html')
    assert html.status_code==200
    assert html.headers.get('Cache-Control')=='no-store'
    assert 'frame-ancestors' in html.headers.get('Content-Security-Policy','')
    if app.config.get('APP_BASE_PATH'):assert '/SGC/owner-ui.js' in html.get_data(as_text=True)

logs=capture.getvalue()
assert password not in logs and key not in logs and 'PRIVATE_EDITORIAL' not in logs
with connect() as conn,conn.cursor() as cur:
    cur.execute('SELECT count(*) FROM diagnostic_events WHERE id=%s',(old_diagnostic,))
    assert cur.fetchone()[0]==0
    cur.execute('SELECT count(*) FROM audit_events WHERE id=%s',(old_business,))
    assert cur.fetchone()[0]==1
    cur.execute("SELECT actor_user_id,condominium_id,metadata FROM diagnostic_events WHERE source='browser' AND action='script_error'")
    uid,condo,metadata=cur.fetchone()
    assert str(uid)==ids['qa.operator'] and condo=='sqa'
    assert metadata=={'page':'editor','untrustedClientReport':True}
print('PASS: login, CSRF, owner isolation, MFA enrollment, replay denial, quota, privacy, filters, pagination and panel lock')
print('PASS: all fixtures confined to dedicated QA database; customer database untouched')
print('PASS: 90-day diagnostic retention preserves immutable business audit')
