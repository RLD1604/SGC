"""Etapa 4: mídia, concorrência e encerramento seguro da importação global."""
import base64, io, json, os, sys, uuid
sys.path.insert(0, "/site")
from PIL import Image
from auth import hash_password
from server import app, connect, initialize

PASSWORD="SenhaSegura1!"

def expect(response,status,label):
    if response.status_code!=status:
        raise AssertionError(f"{label}: esperado {status}, recebido {response.status_code}: {response.get_data(as_text=True)}")
    return response.get_json(silent=True)

def seed(login,condo="sqa",role="encarregado"):
    uid,mid=uuid.uuid4(),uuid.uuid4()
    with connect() as conn,conn.cursor() as cur:
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,activated_at,password_changed_at) VALUES(%s,%s,%s,%s,%s,'active',now(),now())",(uid,login,login,login,hash_password(PASSWORD)))
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id,status,starts_at) VALUES(%s,%s,%s,'active',now())",(mid,uid,condo))
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,starts_at,basis) VALUES(%s,%s,%s,%s,%s,now(),'QA Etapa 4')",(uuid.uuid4(),mid,uid,condo,role))

def login(name):
    client=app.test_client();body=expect(client.post('/api/auth/login',json={'login':name,'password':PASSWORD}),200,'login')
    return client,body['csrf_token']

def call(client,csrf,method,path,payload):
    return client.open(path,method=method,json=payload,headers={'X-CSRF-Token':csrf})

def photo_uri():
    image=Image.new('RGB',(1080,1920),'#4b7f52');buffer=io.BytesIO();image.save(buffer,'PNG')
    return 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()

def document(record_id,title,photo=None):
    return {'id':record_id,'title':title,'text':'Registro operacional.','textHtml':'<p>Registro operacional.</p>','category':'Serviço','local':'Área comum','date':'2026-10-03','who':'Equipe','progress':'Concluído','status':'draft','revision':1,'history':[],'photos':([{'src':photo,'masterSrc':photo,'originalSrc':photo,'caption':'Legenda QA'}] if photo else [])}

def main():
    if os.environ.get('QA_DISPOSABLE_DATABASE')!='YES':raise SystemExit('Use banco descartável.')
    initialize()
    with connect() as conn,conn.cursor() as cur:cur.execute("INSERT INTO condominiums(id,name) VALUES('outro','Outro QA') ON CONFLICT DO NOTHING")
    seed('operador.sqa');seed('operador.outro','outro');seed('editor.sqa',role='editor')
    owner,csrf=login('operador.sqa');foreign,foreign_csrf=login('operador.outro');editor,editor_csrf=login('editor.sqa')
    record_id='media-'+uuid.uuid4().hex
    created=expect(call(owner,csrf,'POST','/api/records',{'document':document(record_id,'Mídia QA',photo_uri())}),201,'registro com foto')['document']
    denied=document('editor-'+uuid.uuid4().hex,'Editor sem criação')
    expect(call(editor,editor_csrf,'POST','/api/records',{'document':denied}),403,'editor puro sem criação de registro')
    photo=created['photos'][0]
    if not photo['src'].startswith(f'/api/documents/record/{record_id}/media/'):
        raise AssertionError('Mídia não recebeu URL contextual do documento.')
    media_path=photo['src']
    response=owner.get(media_path);expect(response,200,'mídia autorizada')
    if not response.content_type.startswith('image/'):raise AssertionError('MIME da mídia inválido.')
    expect(foreign.get(media_path),404,'mídia entre condomínios ocultada')
    invalid=document('external-'+uuid.uuid4().hex,'Mídia externa','https://example.com/photo.jpg')
    expect(call(owner,csrf,'POST','/api/records',{'document':invalid}),400,'mídia externa recusada')

    current=created['revision']
    first=document(record_id,'Primeira gravação');first['revision']=current
    saved=expect(call(owner,csrf,'PATCH',f'/api/records/{record_id}',{'expectedRevision':current,'document':first}),200,'primeira gravação')['document']
    second=document(record_id,'Gravação obsoleta');second['revision']=current
    expect(call(owner,csrf,'PATCH',f'/api/records/{record_id}',{'expectedRevision':current,'document':second}),409,'concorrência otimista')
    state=expect(owner.get('/api/workspace'),200,'workspace')['state']
    actual=next(item for item in state['records'] if item['id']==record_id)
    if actual['title']!='Primeira gravação' or actual['revision']!=saved['revision']:
        raise AssertionError('Conflito alterou o documento vencedor.')
    expect(owner.post('/api/import',json={'state':{}}),410,'importação global encerrada')
    print(json.dumps({'passed':True,'checks':9,'mediaScoped':True,'crossCondominiumBlocked':True,'editorCreateDenied':True,'conflictPreservedWinner':True,'legacyImportClosed':True}))

if __name__=='__main__':main()
