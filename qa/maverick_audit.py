"""Read-only consistency and trace audit of synthetic Maverick QA."""
import os,json,hashlib
from pathlib import Path
assert os.environ.get('DB_NAME','').startswith('sgc_owner_qa_maverick')
from server import connect
from auth import token_digest
people=json.loads(Path('/verify/credentials.json').read_text(encoding='utf-8'))
with connect() as conn,conn.cursor() as cur:
 cur.execute('SELECT artifact_html,artifact_hash FROM official_publications')
 artifacts=cur.fetchall();assert artifacts
 assert all(hashlib.sha256(bytes(body)).hexdigest()==digest for body,digest in artifacts)
 cur.execute("SELECT count(*) FROM official_publications p JOIN approval_decisions a ON a.id=p.approval_id JOIN edition_revisions r ON r.id=p.edition_revision_id WHERE a.approver_user_id=r.author_user_id")
 assert cur.fetchone()[0]==0
 cur.execute("SELECT action,count(*) FROM audit_events WHERE action LIKE 'record.%' OR action LIKE 'edition.%' OR action LIKE 'publication.%' GROUP BY action")
 actions=dict(cur.fetchall());assert {'record.create','record.edit','record.submit','record.review','record.trash','record.restore','edition.create','edition.edit','edition.submit','edition.returned','edition.approved','publication.create'}<=set(actions)
 cur.execute("SELECT count(*) FROM audit_events WHERE (action LIKE 'record.%' OR action LIKE 'edition.%' OR action LIKE 'publication.%') AND actor_user_id IS NULL")
 assert cur.fetchone()[0]==0
 cur.execute("SELECT count(*) FROM diagnostic_events WHERE source='browser' AND action='document_view' AND actor_user_id IS NOT NULL AND metadata ? 'resource'")
 reads=cur.fetchone()[0];assert reads>0
 cur.execute("SELECT count(*) FROM access_recovery_requests r JOIN users u ON u.id=r.user_id WHERE u.login_normalized='maverick' AND r.status='pending'")
 assert cur.fetchone()[0]==1
 cur.execute('SELECT metadata FROM diagnostic_events UNION ALL SELECT metadata FROM audit_events')
 logs=json.dumps(cur.fetchall(),ensure_ascii=False)
 assert all(person[field] not in logs for person in people for field in ('password','token'))
 session_file=Path(os.getenv('QA_SESSION_FILE','/verify/sessions.json'))
 if session_file.is_file():
  sessions=json.loads(session_file.read_text(encoding='utf-8'))
  for session in sessions.values():
   if session.get('key'):assert session['key'] not in logs
   for cookie in session.get('state',{}).get('cookies',[]):
    if cookie.get('value'):assert cookie['value'] not in logs
 cur.execute("SELECT document->>'text' FROM records")
 assert all(not content or len(content)<20 or content not in logs for (content,) in cur.fetchall())
print(json.dumps({'status':'passed','officialArtifactsVerified':len(artifacts),'businessActions':len(actions),'identifiedDocumentViews':reads,'recoveryQueued':True,'credentialLeak':False}))
