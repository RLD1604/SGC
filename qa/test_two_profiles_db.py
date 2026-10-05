"""Transactional integration probe: all synthetic data is rolled back."""
import os
import uuid
from pathlib import Path
import psycopg2
from psycopg2.extras import register_uuid
from flask import Flask, g
from auth import register_auth
register_uuid()

conn=psycopg2.connect(host=os.getenv('DB_HOST','database'),dbname=os.getenv('DB_NAME','condominio'),user=os.getenv('DB_USER','condominio'),password=Path(os.environ['DB_PASSWORD_FILE']).read_text().strip())
class Borrowed:
    def __enter__(self): return conn
    def __exit__(self,*args): return False

tag=uuid.uuid4().hex
actor,target=str(uuid.uuid4()),str(uuid.uuid4())
c1,c2='qa1-'+tag,'qa2-'+tag
app=Flask(__name__)
app.config['AUTH_CAN_MANAGE_ACCOUNTS']=lambda principal, condo: condo==c1
app.config['AUTH_DELIVER_TOKEN']=lambda *args: (_ for _ in ()).throw(AssertionError('unexpected token delivery'))
service=register_auth(app,lambda:Borrowed(),None)
try:
    with conn.cursor() as cur:
        for condo in (c1,c2):
            cur.execute('INSERT INTO condominiums(id,name) VALUES(%s,%s)',(condo,'Synthetic QA'))
        for uid in (actor,target):
            cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status) VALUES(%s,'Synthetic QA',%s,%s,'invited')",(uid,uid,uid))
        for condo in (c1,c2):
            member=str(uuid.uuid4())
            cur.execute('INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,%s)',(member,target,condo))
            cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,%s,'operador','Synthetic QA')",(str(uuid.uuid4()),member,target,condo))
    principal={'user_id':actor,'memberships':[c1]}
    with app.test_request_context('/',method='POST',json={'login':target,'displayName':'Changed','roles':['operador'],'condominiumId':c1}):
        g.principal=principal
        response=app.make_response(service.issue_invitation())
        assert response.status_code==409,response.get_json()
    with app.test_request_context('/',method='POST',json={'reason':'Synthetic test','condominiumId':c1}):
        g.principal=principal
        response=app.make_response(service.disable_user(target))
        assert response.status_code==200,response.get_json()
    with conn.cursor() as cur:
        cur.execute('SELECT status,display_name FROM users WHERE id=%s',(target,))
        assert cur.fetchone()==('invited','Synthetic QA')
        cur.execute('SELECT condominium_id,status FROM memberships WHERE user_id=%s ORDER BY condominium_id',(target,))
        assert dict(cur.fetchall())=={c1:'inactive',c2:'active'}
        cur.execute('SELECT condominium_id,revoked_at IS NULL FROM role_grants WHERE user_id=%s',(target,))
        assert dict(cur.fetchall())=={c1:False,c2:True}
    print('PASS: invitation identity and account disabling isolated by condominium')
finally:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM users WHERE id IN (%s,%s)',(actor,target))
        assert cur.fetchone()[0]==0
    conn.close()
    print('PASS: all synthetic fixtures rolled back')
