import sys
import json
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
        cur.fetchone.return_value=(1,)
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
        cur.fetchone.return_value=(31,)
        response=app.test_client().post('/api/diagnostics/client',json={'kind':'navigation','page':'inicio'})
        self.assertEqual(response.status_code,429)

if __name__=='__main__':unittest.main()
