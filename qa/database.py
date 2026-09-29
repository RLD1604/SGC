"""Integration checks: creates and drops ONLY a uniquely named temporary test DB."""
import base64
import copy
import io
import os
import sys
import unittest
from unittest.mock import patch
import uuid
sys.path.insert(0, '/site')
import server
from psycopg2 import sql
from PIL import Image


class DatabaseTests(unittest.TestCase):
    def test_ai_safety(self):
        import ai_review
        source=[{'id':0,'text':'Os serviço foi feito em 10/09.'}]
        proposed={'segments':[{'id':0,'text':'Os serviços foram feitos em 10/09.','reason':'Concordância verbal e nominal.'}]}
        changes=ai_review.validate_answer(source,proposed)
        self.assertEqual(changes[0]['id'],0)
        bad=copy.deepcopy(proposed);bad['segments'][0]['text']='Os serviços foram feitos em 11/09.'
        with self.assertRaises(ValueError): ai_review.validate_answer(source,bad)
        with self.assertRaises(ValueError): ai_review.validate_segments([{'id':0,'text':'x'*6001}])
        with self.assertRaises(ValueError): ai_review.validate_answer(source,{'segments':[]})
        initial=self.client.get('/api/state').get_json()
        self.assertEqual(self.client.post('/api/ai/review',json={'segments':source}).status_code,400)
        with patch('ai_review.enabled',return_value=False),patch('ai_review.cloud_review') as cloud:
            self.assertEqual(self.client.post('/api/ai/review',json={'segments':source,'consent':True}).status_code,503)
            cloud.assert_not_called()
        with patch('ai_review.enabled',return_value=True),patch('ai_review.cloud_review',return_value=changes) as cloud:
            for _ in range(2):
                response=self.client.post('/api/ai/review',json={'segments':source,'consent':True})
                self.assertEqual(response.status_code,200,response.get_json())
            self.assertEqual(self.client.post('/api/ai/review',json={'segments':source,'consent':True}).status_code,429)
            self.assertEqual(cloud.call_count,2)
        self.assertEqual(self.client.get('/api/state').get_json(),initial)
        print('AI safety: consent, missing key, answer structure, number preservation, quotas and no document mutation verified. Cloud responses mocked; no external request.')

    @classmethod
    def setUpClass(cls):
        cls.original=os.environ.get('DB_NAME','condominio')
        cls.test_name='sqa_test_'+uuid.uuid4().hex
        conn=server.connect();conn.autocommit=True
        with conn.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.test_name)))
        conn.close()
        os.environ['DB_NAME']=cls.test_name
        server.initialize()
        cls.client=server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ['DB_NAME']=cls.original
        conn=server.connect();conn.autocommit=True
        with conn.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.test_name)))
        conn.close()

    def test_complete_persistence_flow(self):
        initial=self.client.get('/api/state').get_json()
        state=initial['state']
        image=Image.new('RGB',(1080,1920),'green');buf=io.BytesIO();image.save(buf,'PNG')
        src='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
        state['records']=[{'id':'test-record','title':'Manutenção de teste','text':'Concluída','textHtml':'<p onclick="alert(1)" style="font-family: Georgia; color: #684b91; position: fixed">Concluída<script>alert(1)</script><img src="x" onerror="alert(1)"></p>','status':'ready','revision':1,'photos':[{'src':src,'masterSrc':src,'originalSrc':src},{'src':src}]}]
        saved=self.client.put('/api/state',json={'revision':initial['revision'],'state':state})
        self.assertEqual(saved.status_code,200,saved.get_json())
        doc=saved.get_json();state=doc['state'];photo=state['records'][0]['photos'][0]
        html=state['records'][0]['textHtml']
        self.assertNotIn('script',html);self.assertNotIn('onclick',html);self.assertNotIn('onerror',html);self.assertNotIn('position',html)
        self.assertIn('font-family: Georgia',html)
        self.assertEqual((photo['width'],photo['height']),(599,1065))
        self.assertEqual(photo['masterSrc'],photo['originalSrc'])
        self.assertNotEqual(photo['masterSrc'],photo['src'])
        with Image.open(io.BytesIO(self.client.get(photo['masterSrc']).data)) as master:
            self.assertEqual(master.size,(1080,1920))
        self.assertEqual(state['records'][0]['photos'][1]['src'],photo['src'])
        with server.connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM media');self.assertEqual(cur.fetchone()[0],3) # derivative + master + cover
        self.assertEqual(self.client.get(photo['src']).status_code,200)
        self.assertEqual(self.client.put('/api/state',json={'revision':0,'state':state}).status_code,409)
        server.initialize() # startup rerun must retain records
        self.assertEqual(self.client.get('/api/state').get_json()['state'],state)
        published=copy.deepcopy(state['editions'][0]);published['id']='published-1'
        published['blocks']=[{'id':'b1','title':'Trabalho','body':'<p>Texto</p>','photos':[photo],'sources':[{'id':'test-record','revision':1}]}]
        state['publications'].append(published)
        doc=self.client.put('/api/state',json={'revision':doc['revision'],'state':state}).get_json()
        changed=copy.deepcopy(doc['state']);changed['publications'][0]['title']='Não pode mudar'
        self.assertEqual(self.client.put('/api/state',json={'revision':doc['revision'],'state':changed}).status_code,400)
        self.assertEqual(self.client.get('/api/state').get_json()['revision'],doc['revision'])
        legacy=copy.deepcopy(doc['state']);legacy['publications']=[]
        imported=self.client.post('/api/import',json={'importId':'test-browser','state':legacy})
        self.assertEqual(imported.status_code,200,imported.get_json())
        again=self.client.post('/api/import',json={'importId':'test-browser','state':legacy}).get_json()
        self.assertTrue(again['alreadyImported'])
        self.assertEqual(len(again['state']['records']),2)
        self.assertEqual(len({row['id'] for row in again['state']['records']}),2)
        self.assertEqual(self.client.post('/api/import',json={'importId':'bad','state':{} }).status_code,400)
        self.assertEqual(self.client.put('/api/state',json=doc,headers={'Origin':'https://other.example'}).status_code,403)
        final=self.client.get('/api/state').get_json()
        bad=copy.deepcopy(final);bad['state']['records'][0]['photos'][0]['src']='https://example.com/photo.jpg'
        self.assertEqual(self.client.put('/api/state',json=bad).status_code,400)
        self.assertEqual(self.client.get('/api/state').get_json(),final)
        with server.connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM change_history');self.assertEqual(cur.fetchone()[0],3)
        print('Verified: persistence, restart initialization, portrait resizing, deduplication, conflicts, immutable publication, idempotent import, rollback, origin protection and audit history.')


if __name__=='__main__':
    unittest.main()
