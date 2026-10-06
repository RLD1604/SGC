import sys
import json
import os
import uuid
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from flask import Flask,g
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observability import register_observability

class Diagnostics(unittest.TestCase):
    def app(self,broken=False):
        app=Flask(__name__)
        conn=MagicMock()
        cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(1,42)
        def connect():
            if broken: raise RuntimeError('sensitive body must never appear')
            return conn
        report=register_observability(app,connect)
        @app.before_request
        def actor():g.principal={'user_id':'00000000-0000-0000-0000-000000000001','memberships':['sqa']}
        app.add_url_rule('/api/diagnostics/client','client_diagnostics',report,methods=['POST'])
        app.add_url_rule('/api/test/<item>','test',lambda item: ({'ok':True},200))
        app.add_url_rule('/api/denied','denied',lambda: ({'error':'Denied'},403))
        return app,cur

    @patch('observability.emit')
    def test_server_ids_safe_routes_and_denials(self,emit):
        app,cur=self.app()
        response=app.test_client().get('/api/test/SECRET-TOKEN?password=PRIVATE',headers={'X-Request-ID':'forged'})
        rid=response.headers['X-Request-ID']
        self.assertNotEqual(rid,'forged')
        event=emit.call_args.args[0]
        self.assertEqual(event['metadata']['route'],'/api/test/<item>')
        self.assertNotIn('SECRET',json.dumps(event))
        self.assertNotIn('PRIVATE',json.dumps(event))
        self.assertEqual(app.test_client().get('/api/denied').status_code,403)
        self.assertEqual(emit.call_args.args[0]['result'],'denied')

    @patch('observability.emit')
    def test_database_failure_falls_back_without_breaking_response(self,emit):
        app,_=self.app(True)
        response=app.test_client().get('/api/test/example')
        self.assertEqual(response.status_code,200)
        self.assertEqual(emit.call_args.args[0]['action'],'diagnostics.persist_failed')
        self.assertNotIn('sensitive',str(emit.call_args_list))

    @patch('observability.emit')
    def test_malformed_and_oversized_reports_are_rejected(self,emit):
        app,_=self.app()
        for body in ({'kind':{},'page':'editor'},{'kind':'script_error','page':[]},[],None):
            self.assertEqual(app.test_client().post('/api/diagnostics/client',json=body).status_code,400)
        self.assertEqual(app.test_client().post('/api/diagnostics/client',json={'kind':'script_error','page':'editor','content':'x'*3000}).status_code,413)

    @patch('observability.emit')
    def test_browser_payload_is_reported_and_sanitized(self,emit):
        app,cur=self.app()
        response=app.test_client().post('/api/diagnostics/client',json={'kind':'script_error','page':'editor','userId':'forged','condominiumId':'other','password':'PRIVATE','message':'SECRET'})
        self.assertEqual(response.status_code,202)
        event=emit.call_args_list[0].args[0]
        self.assertEqual(event['result'],'reported')
        self.assertEqual(event['condominiumId'],'sqa')
        self.assertNotIn('SECRET',json.dumps(event))
        self.assertNotIn('PRIVATE',json.dumps(event))
        cur.fetchone.return_value=(121,42)
        response=app.test_client().post('/api/diagnostics/client',json={'kind':'navigation','page':'inicio'})
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.headers['Retry-After'],'42')

    @patch('observability.emit')
    def test_document_report_id_is_sanitized_and_actor_is_server_owned(self,emit):
        app,cur=self.app()
        app.config['AUTH_DIAGNOSTIC_RESOURCE']=lambda actor,kind,rid: {'id':rid,'type':kind} if rid=='allowed' else None
        report_id='00000000-0000-0000-0000-000000000035'
        response=app.test_client().post('/api/diagnostics/client',json={'kind':'document_view','page':'editor','resourceType':'edition','resourceId':'allowed','reportId':report_id,'userId':'forged'})
        self.assertEqual(response.status_code,202)
        event=emit.call_args_list[0].args[0]
        self.assertEqual(event['metadata']['reportId'],report_id)
        self.assertNotEqual(event['userId'],'forged')
        self.assertEqual(app.test_client().post('/api/diagnostics/client',json={'kind':'document_view','page':'editor','resourceType':'edition','resourceId':'denied'}).status_code,404)
        emit.reset_mock()
        cur.fetchone.return_value=(120,42)
        self.assertEqual(app.test_client().post('/api/diagnostics/client',json={'kind':'navigation','page':'inicio','reportId':'SECRET-invalid'}).status_code,202)
        self.assertNotIn('reportId',emit.call_args_list[0].args[0]['metadata'])
        self.assertNotIn('SECRET',str(emit.call_args_list))

    @patch('observability.emit')
    def test_client_persistence_failure_is_retryable_without_breaking_normal_api(self,emit):
        app,cur=self.app()
        with patch('observability.record',return_value=False):
            result=app.test_client().post('/api/diagnostics/client',json={'kind':'navigation','page':'inicio'})
            self.assertEqual(result.status_code,503)
            self.assertEqual(result.headers['Retry-After'],'5')
            self.assertEqual(app.test_client().get('/api/test/example').status_code,200)
        broken,_=self.app(True)
        self.assertEqual(broken.test_client().post('/api/diagnostics/client',json={'kind':'navigation','page':'inicio'}).status_code,503)


@unittest.skipUnless(os.environ.get('QA_DIAGNOSTICS_DB')=='1','isolated PostgreSQL opt-in')
class DiagnosticsPostgres(unittest.TestCase):
    @patch('observability.emit')
    def test_35_views_and_repeated_report_id_persist_once(self,emit):
        if not os.environ.get('DB_NAME','').startswith('sgc_owner_qa_'):
            self.fail('Refusing non-QA database')
        from server import connect
        user_id=str(uuid.uuid4());login='qa-diagnostics-'+uuid.uuid4().hex
        app=Flask(__name__);report=register_observability(app,connect)
        @app.before_request
        def actor():g.principal={'user_id':user_id,'memberships':['sqa']}
        app.config['AUTH_DIAGNOSTIC_RESOURCE']=lambda actor,kind,rid: {'type':kind,'id':rid} if kind=='edition' else None
        app.add_url_rule('/api/diagnostics/client','client_diagnostics',report,methods=['POST'])
        try:
            with connect() as conn,conn.cursor() as cur:
                cur.execute('SELECT current_database()');self.assertEqual(cur.fetchone()[0],os.environ['DB_NAME'])
                cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='diagnostic_events_browser_report'");self.assertIsNotNone(cur.fetchone(),'initialize schema 11 before QA')
                cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status) VALUES(%s,'Synthetic diagnostics',%s,%s,'active')",(user_id,login,login))
            ids=[str(uuid.uuid4()) for _ in range(35)]
            client=app.test_client()
            for report_id in ids:
                body={'kind':'document_view','page':'editor','resourceType':'edition','resourceId':'synthetic','reportId':report_id}
                self.assertEqual(client.post('/api/diagnostics/client',json=body).status_code,202)
            # Acknowledgement lost after commit: a retry preserves its UUID.
            self.assertEqual(client.post('/api/diagnostics/client',json=body).status_code,202)
            with connect() as conn,conn.cursor() as cur:
                cur.execute("SELECT count(*),count(DISTINCT metadata->>'reportId') FROM diagnostic_events WHERE actor_user_id=%s AND source='browser'",(user_id,))
                self.assertEqual(cur.fetchone(),(35,35))
        finally:
            with connect() as conn,conn.cursor() as cur:
                cur.execute('DELETE FROM diagnostic_events WHERE actor_user_id=%s',(user_id,))
                cur.execute('DELETE FROM diagnostic_quotas WHERE user_id=%s',(user_id,))
                cur.execute('DELETE FROM users WHERE id=%s',(user_id,))

if __name__=='__main__':unittest.main()
