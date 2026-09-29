"""Adversarial API checks against a disposable database; never writes the real acervo."""
import copy
import json
import os
import sys
import uuid
sys.path.insert(0, '/site')
import server
from psycopg2 import sql

original=os.getenv('DB_NAME','condominio')
test_name='sqa_adversarial_'+uuid.uuid4().hex
conn=server.connect();conn.autocommit=True
with conn.cursor() as cur:cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(test_name)))
conn.close()
os.environ['DB_NAME']=test_name
results=[]
try:
    server.initialize();client=server.app.test_client()
    base=client.get('/api/state').get_json()
    base['state']['records']=[dict(id='qa-record',title='Teste',status='draft',text='Texto',photos=[],revision=1)]
    def probe(name,mutate,expected=400,method='put'):
        # Roll back any accepted adversarial case by restoring a valid state with its fresh revision.
        payload=copy.deepcopy(base);payload['revision']=client.get('/api/state').get_json()['revision']
        mutate(payload)
        response=getattr(client,method)('/api/state',json=payload)
        results.append(dict(name=name,expected=expected,actual=response.status_code,passed=response.status_code==expected))
        if response.status_code==200:
            clean=copy.deepcopy(base);clean['revision']=response.get_json()['revision']
            assert client.put('/api/state',json=clean).status_code==200
    probe('Título ausente',lambda p:p['state']['records'][0].pop('title'))
    probe('Título numérico',lambda p:p['state']['records'][0].update(title=123))
    probe('Título acima de 1000',lambda p:p['state']['records'][0].update(title='x'*1001))
    probe('ID duplicado',lambda p:p['state']['records'].append(copy.deepcopy(p['state']['records'][0])))
    probe('Situação inválida',lambda p:p['state']['records'][0].update(status='unknown'))
    for field in ['text','category','local','date','who','progress','feedback']:
        probe('Tipo inválido: '+field,lambda p,f=field:p['state']['records'][0].update({f:[]}))
    probe('Data impossível',lambda p:p['state']['records'][0].update(date='2026-99-99'))
    probe('Categoria fora das opções',lambda p:p['state']['records'][0].update(category='INVALID'))
    probe('Andamento fora das opções',lambda p:p['state']['records'][0].update(progress='INVALID'))
    probe('Revisão com tipo inválido',lambda p:p['state']['records'][0].update(revision={}))
    probe('Histórico com tipo inválido',lambda p:p['state']['records'][0].update(history={}))
    probe('Período com tipo inválido',lambda p:p['state']['editions'][0].update(period=[]))
    probe('Registro pronto sem texto',lambda p:p['state']['records'][0].update(status='ready',title='',text=''))
    probe('Foto externa',lambda p:p['state']['records'][0].update(photos=[{'src':'https://example.com/test.jpg'}]))
    probe('Foto corrompida',lambda p:p['state']['records'][0].update(photos=[{'src':'data:image/png;base64,AAAA'}]))
    probe('Cópia de edição inválida',lambda p:p['state']['records'][0].update(photos=[{'src':'/images/jardim.jpg','masterSrc':[]}]))
    probe('Nenhum informe',lambda p:p['state'].update(editions=[]))
    probe('Revisão concorrente',lambda p:p.update(revision=-1),409)
    current=client.get('/api/state').get_json()
    key='qa-operation-'+uuid.uuid4().hex
    first=client.put('/api/state',json=current,headers={'Idempotency-Key':key})
    repeated=client.put('/api/state',json=current,headers={'Idempotency-Key':key})
    changed=copy.deepcopy(current);changed['state']['editions'][0]['title']='Outro conteúdo'
    conflict=client.put('/api/state',json=changed,headers={'Idempotency-Key':key})
    results.extend([
        dict(name='Repetição idempotente da mesma operação',expected=200,actual=repeated.status_code,passed=first.status_code==200 and repeated.status_code==200 and repeated.get_json()==first.get_json()),
        dict(name='Chave de operação não aceita conteúdo diferente',expected=409,actual=conflict.status_code,passed=conflict.status_code==409),
    ])
    for field in ['title','type']:
        probe('Bloco: '+field+' inválido',lambda p,f=field:p['state']['editions'][0].update(blocks=[{'id':'b','body':'<p>Texto</p>',f:[]}]))
    response=client.put('/api/state',json=base,headers={'Origin':'https://other.example'})
    results.append(dict(name='Origem externa bloqueada',expected=403,actual=response.status_code,passed=response.status_code==403))
    for segments in [[],[{'id':1,'text':'Texto'}],[{'id':0,'text':'x'*6001}],[{'id':i,'text':'x'} for i in range(101)]]:
        response=client.post('/api/ai/review',json={'consent':True,'segments':segments})
        results.append(dict(name='Limite/estrutura de IA: '+str(len(segments)),expected=400,actual=response.status_code,passed=response.status_code==400))
    response=client.post('/api/import',json={'importId':'qa-invalid','state':{}})
    results.append(dict(name='Importação inválida',expected=400,actual=response.status_code,passed=response.status_code==400))
    print(json.dumps({'checks':results,'passed':sum(r['passed'] for r in results),'total':len(results)},ensure_ascii=False))
finally:
    os.environ['DB_NAME']=original
    conn=server.connect();conn.autocommit=True
    with conn.cursor() as cur:cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(test_name)))
    conn.close()
