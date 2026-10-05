"""Prepare a NEW database; never deletes or replaces an existing database."""
import argparse,json,os,uuid
from pathlib import Path
import psycopg2
from psycopg2.extras import register_uuid
from psycopg2 import sql
from auth import generate_token,utcnow,INVITATION_TIMEOUT

PEOPLE=[('marcelo','Marcelo Síndico','administrador'),('elcio','Élcio Subsíndico','administrador'),('grangeiro','Grangeiro Conselheiro','administrador'),('andre','André','operador'),('claudio','Cláudio','administrador')]
register_uuid()

def prepare(target,output):
    if not target.startswith(('sgc_beta_clean_','sgc_owner_qa_')):raise ValueError('New dedicated database required')
    password=Path(os.environ['DB_PASSWORD_FILE']).read_text().strip()
    options=dict(host=os.environ['DB_HOST'],user=os.environ['DB_USER'],password=password,connect_timeout=5)
    with psycopg2.connect(dbname=os.environ.get('DB_NAME','condominio'),**options) as source,source.cursor() as cur:
        cur.execute("SELECT u.id,u.display_name,u.login_display,u.login_normalized,u.password_hash,u.activated_at,u.password_changed_at FROM users u JOIN platform_owner_grants o ON o.user_id=u.id WHERE u.status='active' AND o.revoked_at IS NULL AND u.login_normalized='rodrigo'")
        owner=cur.fetchone()
        if not owner:raise ValueError('Active owner rodrigo required')
        cur.execute('SELECT secret_fingerprint,enrolled_at,last_counter FROM owner_access_state WHERE user_id=%s',(owner[0],))
        owner_mfa=cur.fetchone()
    admin=psycopg2.connect(dbname='postgres',**options);admin.autocommit=True
    with admin.cursor() as cur:cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
    admin.close()
    invitations=[]
    with psycopg2.connect(dbname=target,**options) as dest,dest.cursor() as cur:
        cur.execute(Path('/site/schema.sql').read_text())
        cur.execute("UPDATE condominiums SET name='Condomínio SQA' WHERE id='sqa'")
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,activated_at,password_changed_at) VALUES(%s,%s,%s,%s,%s,'active',%s,%s)",owner)
        membership=uuid.uuid4()
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,'sqa')",(membership,owner[0]))
        cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa','administrador','Dono preservado na base inicial limpa')",(uuid.uuid4(),membership,owner[0]))
        cur.execute('INSERT INTO platform_owner_grants(user_id) VALUES(%s)',(owner[0],))
        if owner_mfa:cur.execute('INSERT INTO owner_access_state(user_id,secret_fingerprint,enrolled_at,last_counter) VALUES(%s,%s,%s,%s)',(owner[0],*owner_mfa))
        for login,name,role in PEOPLE:
            user_id,membership=uuid.uuid4(),uuid.uuid4();raw,digest=generate_token();expiry=utcnow()+INVITATION_TIMEOUT
            cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status,mfa_required) VALUES(%s,%s,%s,%s,'invited',true)",(user_id,name,login,login))
            cur.execute("INSERT INTO memberships(id,user_id,condominium_id) VALUES(%s,%s,'sqa')",(membership,user_id))
            cur.execute("INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,'sqa',%s,'Convite nominal do dono para Beta')",(uuid.uuid4(),membership,user_id,role))
            cur.execute('INSERT INTO invitations(id,user_id,token_hash,issued_by,expires_at) VALUES(%s,%s,%s,%s,%s)',(uuid.uuid4(),user_id,digest,owner[0],expiry))
            invitations.append(dict(login=login,name=name,role=role,token=raw,expiresAt=expiry.isoformat()))
        cur.execute("INSERT INTO audit_events(id,actor_user_id,action,result,correlation_id,metadata) VALUES(%s,%s,'beta.clean.initialize','success',%s,'{}')",(uuid.uuid4(),owner[0],str(uuid.uuid4())))
    output=Path(output)
    with output.open('x',encoding='utf-8') as handle:json.dump(invitations,handle,ensure_ascii=False)
    output.chmod(0o600)
    print('NEW_BETA_DATABASE_PREPARED: content=0; activeOwner=1; invitedUsers=5; private token file written')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target',required=True);parser.add_argument('--output',required=True);args=parser.parse_args();prepare(args.target,args.output)
