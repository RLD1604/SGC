import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from flask import Flask,g
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from owner_console import matching_counter,totp,register_owner,enrollment_qr
import base64,io
from PIL import Image
from auth import require_session

KEY='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
class Owner(unittest.TestCase):
    def test_enrollment_qr_is_in_memory_png(self):
        uri='otpauth://totp/SGC:qa?secret='+KEY+'&issuer=SGC&algorithm=SHA1&digits=6&period=30'
        data=enrollment_qr(uri)
        self.assertTrue(data.startswith('data:image/png;base64,'))
        image=Image.open(io.BytesIO(base64.b64decode(data.split(',',1)[1])))
        self.assertEqual(image.format,'PNG')
        self.assertEqual(image.width,image.height)
        self.assertGreater(image.width,200)
        self.assertEqual(image.convert('L').getpixel((0,0)),255)

    def test_rfc_totp_and_replay(self):
        self.assertEqual(totp(KEY,1),'287082')
        self.assertEqual(matching_counter(KEY,'287082',now=59,last_counter=-1),1)
        self.assertIsNone(matching_counter(KEY,'287082',now=59,last_counter=1))
        for code in ('','123','abcdef',123456):self.assertIsNone(matching_counter(KEY,code,now=59))

    def app(self,owner=False,proof=False,actor=True):
        app=Flask(__name__)
        conn=MagicMock()
        cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        answers=iter([(True,) if owner else None,(datetime.now(timezone.utc)+timedelta(minutes=15),) if proof else None])
        cur.fetchone.side_effect=lambda:next(answers,None)
        @app.before_request
        def identity():g.principal={'user_id':'u','session_id':'s','memberships':['sqa']} if actor else None
        register_owner(app,lambda:conn,require_session,lambda view:require_session(view))
        return app,cur

    def test_anonymous_and_tenant_admin_are_denied(self):
        for actor in (False,True):
            app,cur=self.app(actor=actor)
            response=app.test_client().get('/api/owner/events')
            self.assertEqual(response.status_code,403 if actor else 401)
            self.assertFalse(any('diagnostic_events' in call.args[0] for call in cur.execute.call_args_list))

    def test_owner_without_mfa_is_denied(self):
        app,cur=self.app(owner=True)
        self.assertEqual(app.test_client().get('/api/owner/events').status_code,403)

    def test_pagination_limits_and_invalid_filters(self):
        for query in ('?limit=101','?limit=0','?requestId=invalid','?before=2026-01-01'):
            app,cur=self.app(owner=True,proof=True)
            self.assertEqual(app.test_client().get('/api/owner/events'+query).status_code,400)

    def test_owner_metadata_only_query(self):
        app,cur=self.app(owner=True,proof=True)
        cur.fetchall.return_value=[]
        response=app.test_client().get('/api/owner/events?action=record_create')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['events'],[])
        sql,args=cur.execute.call_args.args
        self.assertIn('action=%s',sql)
        self.assertNotIn('records',sql)
        self.assertEqual(args,['record_create',50])

if __name__=='__main__':unittest.main()
