"""Dedicated PostgreSQL HTTP tests. Never run against production."""
import os,secrets,uuid,base64,time,json,io,contextlib
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
assert os.environ.get('DB_NAME','').startswith('sgc_owner_qa_')
key=base64.b32encode(secrets.token_bytes(20)).decode();Path('/tmp/qa-owner-key').write_text(key);os.environ['OWNER_TOTP_FILE']='/tmp/qa-owner-key'
Path('/tmp/qa-cipher-key').write_bytes(Fernet.generate_key());os.environ['USER_MFA_KEY_FILE']='/tmp/qa-cipher-key'
from server import app,connect,initialize
from flask.testing import FlaskClient
class MountedClient(FlaskClient):
    def open(self,*args,**kwargs):
        if args and isinstance(args[0],str):
            base=app.config.get('APP_BASE_PATH','')
            if base and not args[0].startswith(base+'/'):args=(base+args[0],)+args[1:]
        return super().open(*args,**kwargs)
app.test_client_class=MountedClient
from auth import hash_password,generate_token
from owner_console import totp
from user_security import cipher
initialize();password='Beta-'+secrets.token_urlsafe(16)+'!9A';owner_id=str(uuid.uuid4());accounts=[]
with connect() as conn,conn.cursor() as cur:
    cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status) VALUES(%s,'Dono QA','rodrigo','rodrigo',%s,'active')",(owner_id,hash_password(password)))
    cur.execute('INSERT INTO platform_owner_grants(user_id) VALUES(%s)',(owner_id,))
    for name,role in [('marcelo','administrador'),('elcio','administrador'),('grangeiro','administrador'),('andre','operador'),('claudio','administrador')]:
        uid=str(uuid.uuid4());mid=str(uuid.uuid4());raw,digest=generate_token()
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status,mfa_required) VALUES(%s,%s,%s,%s,'invited',true)",(uid,name,name,name))
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,'sqa')",(mid,uid))
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa',%s,'QA')",(uuid.uuid4(),mid,uid,role))
        cur.execute("INSERT INTO invitations(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,now()+interval '48 hours')",(uuid.uuid4(),uid,digest))
        accounts.append((name,uid,raw))

def login(client,name):
    response=client.post('/api/auth/login',json={'login':name,'password':password});assert response.status_code==200
    return response.get_json(),{'X-CSRF-Token':response.get_json()['csrf_token']}

captured=io.StringIO()
with contextlib.redirect_stdout(captured):
    clients=[]
    for name,uid,raw in accounts:
        client=app.test_client()
        with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE invitations SET expires_at=now()-interval '1 minute' WHERE user_id=%s",(uid,))
        assert client.post('/api/auth/activate',json={'token':raw,'password':password}).status_code==400
        with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE invitations SET expires_at=now()+interval '48 hours' WHERE user_id=%s",(uid,))
        assert client.post('/api/auth/activate',json={'token':raw,'password':'weak'}).status_code==400
        assert client.post('/api/auth/activate',json={'token':raw,'password':password}).status_code==200
        assert client.post('/api/auth/activate',json={'token':raw,'password':password}).status_code==400
        data,headers=login(client,name);assert data['mfaRequired']
        assert client.get('/api/workspace').status_code==401
        assert client.get('/api/owner/overview').status_code==401
        assert client.post('/api/auth/mfa/setup',json={}).status_code==403
        setup=client.post('/api/auth/mfa/setup',json={},headers=headers).get_json()
        assert setup['setupQr'].startswith('data:image/png;base64,') and not setup['enrolled']
        with connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT secret_ciphertext FROM user_mfa WHERE user_id=%s',(uid,));stored=bytes(cur.fetchone()[0]);assert setup['setupKey'].encode() not in stored;assert cipher().decrypt(stored).decode()==setup['setupKey']
        assert client.post('/api/auth/mfa/verify',json={'code':'invalid'},headers=headers).status_code==403
        code=totp(setup['setupKey'],int(time.time()//30))
        assert client.post('/api/auth/mfa/verify',json={'code':code},headers=headers).status_code==200
        assert client.post('/api/auth/mfa/verify',json={'code':code},headers=headers).status_code==403
        assert client.get('/api/workspace').status_code==200
        assert client.get('/api/owner/overview').status_code==403
        assert client.post('/api/auth/mfa/setup',json={},headers=headers).get_json()=={'enrolled':True}
        assert not any(client.get('/api/workspace').get_json()['state'][k] for k in ('records','editions','publications'))
        clients.append((client,headers))
    # Password-only login is gated again even after prior enrollment.
    repeat=app.test_client();data,headers=login(repeat,'marcelo');assert data['mfaRequired'];assert repeat.get('/api/workspace').status_code==401
    for _ in range(6):response=repeat.post('/api/auth/mfa/verify',json={'code':'invalid'},headers=headers)
    assert response.status_code==429
    public=app.test_client()
    # Identify reads, edits and archive without leaking editorial values.
    operator,op_headers=clients[3];document_id=str(uuid.uuid4())
    document={'id':document_id,'title':'Synthetic QA','text':'<p>PRIVATE_QA_CONTENT</p>','category':'Obra','local':'QA','date':'2026-10-05','who':'QA','progress':'Em andamento','photos':[],'status':'draft','revision':1}
    created=operator.post('/api/records',json={'document':document,'condominiumId':'sqa'},headers=op_headers)
    assert created.status_code==201,(created.status_code,created.get_json().get('error'))
    assert operator.get('/api/workspace').status_code==200
    report=operator.post('/api/diagnostics/client',json={'kind':'document_view','page':'registro','resourceType':'record','resourceId':document_id},headers=op_headers)
    assert report.status_code==202
    assert operator.post('/api/diagnostics/client',json={'kind':'document_view','page':'publicado','resourceType':'publication','resourceId':'invalid'},headers=op_headers).status_code==404
    assert operator.post('/api/diagnostics/client',json={'kind':'document_view','page':'publicado','resourceType':'publication','resourceId':str(uuid.uuid4())},headers=op_headers).status_code==404
    assert operator.patch('/api/records/'+document_id,json={'document':document,'expectedRevision':1},headers=op_headers).status_code==200
    assert operator.patch('/api/records/'+document_id,json={'document':document,'expectedRevision':1},headers=op_headers).status_code==409
    trashed={**document,'deletedAt':'2026-10-05T20:00:00Z'}
    assert operator.patch('/api/records/'+document_id,json={'document':trashed,'expectedRevision':2},headers=op_headers).status_code==403
    admin,admin_headers=clients[4]
    # Existing policy conceals another author's unassigned draft even from admin.
    assert admin.patch('/api/records/'+document_id,json={'document':trashed,'expectedRevision':2},headers=admin_headers).status_code==404
    admin_doc={**document,'id':str(uuid.uuid4())}
    admin_created=admin.post('/api/records',json={'document':admin_doc,'condominiumId':'sqa'},headers=admin_headers)
    assert admin_created.status_code==201
    admin_doc=admin_created.get_json()['document']
    admin_trash={**admin_doc,'deletedAt':'2026-10-05T20:00:00Z'}
    assert admin.patch('/api/records/'+admin_doc['id'],json={'document':admin_trash,'expectedRevision':1},headers=admin_headers).status_code==200
    assert admin.patch('/api/records/'+admin_doc['id'],json={'document':admin_doc,'expectedRevision':2},headers=admin_headers).status_code==200
    with connect() as conn,conn.cursor() as cur:
        cur.execute("UPDATE records SET document=jsonb_set(document,'{status}','\"ready\"') WHERE id=%s",(admin_doc['id'],))
    ready=next(row for row in admin.get('/api/workspace').get_json()['state']['records'] if row['id']==admin_doc['id'])
    ready_trash={**ready,'deletedAt':'2026-10-05T20:00:00Z'}
    assert admin.patch('/api/records/'+ready['id'],json={'document':{**ready_trash,'title':'tampered'},'expectedRevision':3},headers=admin_headers).status_code==400
    archived=admin.patch('/api/records/'+ready['id'],json={'document':ready_trash,'expectedRevision':3},headers=admin_headers)
    assert archived.status_code==200,archived.get_json()
    restored=admin.patch('/api/records/'+ready['id'],json={'document':ready,'expectedRevision':4},headers=admin_headers)
    assert restored.status_code==200 and restored.get_json()['document']['status']=='ready'
    assert restored.get_json()['document']['title']==ready['title']
    with connect() as conn,conn.cursor() as cur:
        cur.execute("SELECT metadata FROM diagnostic_events WHERE actor_user_id=%s AND action='document_view'",(accounts[3][1],));metadata=cur.fetchone()[0];assert metadata['resource']['id']==document_id
        cur.execute("SELECT count(*) FROM diagnostic_events WHERE actor_user_id=%s AND action='record.edit' AND metadata->'resource'->>'record_id'=%s",(accounts[3][1],document_id));assert cur.fetchone()[0]==1
        cur.execute("SELECT count(*) FROM diagnostic_events WHERE metadata::text LIKE '%%PRIVATE_QA_CONTENT%%'");assert cur.fetchone()[0]==0
    known=public.post('/api/auth/recovery/request',json={'login':'marcelo','kind':'authenticator'})
    unknown=public.post('/api/auth/recovery/request',json={'login':'nonexistent'})
    assert known.status_code==unknown.status_code==202 and known.get_json()==unknown.get_json()
    for _ in range(4):assert public.post('/api/auth/recovery/request',json={'login':'marcelo'}).status_code==202
    assert public.post('/api/auth/recovery/request',json=[]).status_code==400
    owner=app.test_client();_,owner_headers=login(owner,'rodrigo')
    assert owner.get('/api/owner/recovery-requests').status_code==403
    assert owner.post('/api/owner/enroll',json={'password':password},headers=owner_headers).status_code==200
    assert owner.post('/api/owner/verify',json={'password':password,'code':totp(key,int(time.time()//30))},headers=owner_headers).status_code==200
    queue=owner.get('/api/owner/recovery-requests').get_json()['requests'];assert len(queue)==1
    rid=queue[0]['id'];route='/api/owner/recovery-requests/'+rid+'/resolve'
    assert clients[0][0].post(route,json={},headers=clients[0][1]).status_code==403
    body={'decision':'issue','reason':'Verified personally using known contact','identityConfirmed':True,'resetAuthenticator':True}
    assert owner.post(route,json=body).status_code==403
    assert owner.post(route,json={**body,'identityConfirmed':False},headers=owner_headers).status_code==400
    response=owner.post(route,json=body,headers=owner_headers);assert response.status_code==200;recovery=response.get_json()['token']
    assert owner.post(route,json=body,headers=owner_headers).status_code==404
    with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE recovery_tokens SET expires_at=now()-interval '1 minute' WHERE user_id=%s",(accounts[0][1],))
    assert public.post('/api/auth/recovery/complete',json={'token':recovery,'password':password}).status_code==400
    with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE recovery_tokens SET expires_at=now()+interval '30 minutes' WHERE user_id=%s",(accounts[0][1],))
    assert public.post('/api/auth/recovery/complete',json={'token':recovery,'password':password}).status_code==200
    assert public.post('/api/auth/recovery/complete',json={'token':recovery,'password':password}).status_code==400
    assert clients[0][0].get('/api/workspace').status_code==401
    with connect() as conn,conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM user_mfa WHERE user_id=%s',(accounts[0][1],));assert cur.fetchone()[0]==0
    recovered=app.test_client();data,headers=login(recovered,'marcelo');assert data['mfaRequired'];assert not recovered.post('/api/auth/mfa/setup',json={},headers=headers).get_json()['enrolled']
    public.post('/api/auth/recovery/request',json={'login':'rodrigo'})
    rid=owner.get('/api/owner/recovery-requests').get_json()['requests'][0]['id']
    assert owner.post('/api/owner/recovery-requests/'+rid+'/resolve',json=body,headers=owner_headers).status_code==403
    # Owner selects every space under a live proof; ordinary admins stay isolated.
    assert clients[4][0].post('/api/owner/spaces/sqa/enter',json={},headers=clients[4][1]).status_code==403
    assert owner.post('/api/owner/spaces/sqa/enter',json={}).status_code==403
    assert owner.post('/api/owner/spaces/missing/enter',json={},headers=owner_headers).status_code==404
    assert owner.post('/api/owner/spaces/sqa/enter',json={},headers=owner_headers).status_code==200
    original=next(r for r in owner.get('/api/workspace').get_json()['state']['records'] if r['id']==document_id)
    assert owner.patch('/api/records/'+document_id,json={'document':{**original,'title':'Owner edit'},'expectedRevision':original['revision']},headers=owner_headers).status_code==200
    with connect() as conn,conn.cursor() as cur:
        cur.execute("INSERT INTO condominiums(id,name) VALUES('qa-other-space','Other QA')")
        other_id=str(uuid.uuid4())
        from psycopg2.extras import Json
        cur.execute('INSERT INTO records(id,document) VALUES(%s,%s)',(other_id,Json({**document,'id':other_id})))
        cur.execute("INSERT INTO record_metadata(record_id,condominium_id,author_user_id,current_revision) VALUES(%s,'qa-other-space',%s,1)",(other_id,accounts[3][1]))
    assert owner.post('/api/owner/spaces/qa-other-space/enter',json={},headers=owner_headers).status_code==200
    workspace=owner.get('/api/workspace').get_json()['state']
    assert [r['id'] for r in workspace['records']]==[other_id]
    assert owner.get('/api/workspace',headers={'X-SGC-Owner-Space':'sqa'}).status_code==409
    assert owner.patch('/api/records/'+other_id,json={'document':document,'expectedRevision':1},headers={**owner_headers,'X-SGC-Owner-Space':'sqa'}).status_code==404
    session=owner.get('/api/auth/session').get_json()['principal']
    assert session['ownerSpace']['id']=='qa-other-space' and session['ownerVerified']
    clients[4][0].set_cookie('sgc_owner_space','qa-other-space',path=app.config.get('AUTH_COOKIE_PATH','/'))
    assert other_id not in [r['id'] for r in clients[4][0].get('/api/workspace').get_json()['state']['records']]
    assert clients[4][0].patch('/api/records/'+other_id,json={'document':document,'expectedRevision':1},headers=clients[4][1]).status_code==404
    with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE owner_session_proofs SET expires_at=now()-interval '1 second' WHERE user_id=%s",(owner_id,))
    assert owner.get('/api/workspace').status_code==403
    assert owner.post('/api/owner/spaces/sqa/enter',json={},headers=owner_headers).status_code==403
    with connect() as conn,conn.cursor() as cur:
        cur.execute("UPDATE owner_session_proofs SET expires_at=now()+interval '15 minutes' WHERE user_id=%s",(owner_id,))
        cur.execute("UPDATE platform_owner_grants SET revoked_at=now() WHERE user_id=%s",(owner_id,))
    assert not owner.get('/api/workspace').get_json()['state']['records']
    for secret in [password,key,recovery,*[a[2] for a in accounts]]:assert secret not in captured.getvalue()
print('PASS: five activations, password policy, encrypted MFA, pending-session isolation, CSRF, replay/rate limits, generic recovery, owner-only issuance, MFA reset, token reuse rejection, session revocation, clean initial content and identified read/edit logs without content')
