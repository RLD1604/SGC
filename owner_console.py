"""Read-only platform diagnostics behind an exclusive grant and step-up MFA."""
import base64
import hashlib
import hmac
import io
import os
import re
import struct
import time
from functools import wraps
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
from flask import g, request, jsonify
from auth import verify_password
import qrcode


def enrollment_qr(uri):
    """Render locally in memory; never send the enrollment secret to a QR service."""
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    output=io.BytesIO()
    qr.make_image(fill_color='black',back_color='white').save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii')


def totp(secret,counter):
    raw=base64.b32decode(secret,casefold=True)
    digest=hmac.new(raw,struct.pack('>Q',counter),hashlib.sha1).digest()
    offset=digest[-1]&15
    value=struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff
    return f'{value%1000000:06d}'


def matching_counter(secret,code,now=None,last_counter=-1):
    if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code):return None
    counter=int((time.time() if now is None else now)//30)
    for candidate in (counter,counter-1,counter+1):
        if candidate>last_counter and candidate>=0 and hmac.compare_digest(totp(secret,candidate),code):return candidate
    return None


def register_owner(app,connect,require_session,require_mutation):
    def secret():
        value=Path(os.environ['OWNER_TOTP_FILE']).read_text().strip()
        if not re.fullmatch(r'[A-Z2-7]{32}',value):raise ValueError('MFA configuration invalid')
        return value

    def grant(cur):
        actor=getattr(g,'principal',None) or {}
        cur.execute('SELECT user_id FROM platform_owner_grants WHERE user_id=%s AND revoked_at IS NULL AND starts_at<=now()',(actor.get('user_id'),))
        return bool(cur.fetchone())

    def protected(view):
        @wraps(view)
        @require_session
        def wrapped(*args,**kw):
            actor=g.principal
            with connect() as conn,conn.cursor() as cur:
                if not grant(cur):return jsonify(error='Área exclusiva do dono.'),403
                cur.execute('SELECT p.expires_at FROM owner_session_proofs p JOIN owner_access_state a ON a.user_id=%s WHERE p.session_id=%s AND p.user_id=%s AND p.expires_at>now() AND a.enrolled_at IS NOT NULL AND p.secret_fingerprint=a.secret_fingerprint',
                    (actor['user_id'],actor['session_id'],actor['user_id']))
                proof=cur.fetchone()
                if not proof:return jsonify(error='Confirme sua senha e o código do autenticador.'),403
                g.owner_expires_at=proof[0].isoformat()
            return view(*args,**kw)
        return wrapped

    app.extensions['owner_require']=protected

    @app.get('/api/owner/status')
    @require_session
    def owner_status():
        with connect() as conn,conn.cursor() as cur:
            if not grant(cur):return jsonify(error='Área exclusiva do dono.'),403
            cur.execute('SELECT enrolled_at IS NOT NULL FROM owner_access_state WHERE user_id=%s',(g.principal['user_id'],))
            row=cur.fetchone()
        return jsonify(owner=True,enrolled=bool(row and row[0]))

    def step_up(enrollment=False):
        actor=g.principal
        body=request.get_json(silent=True)
        if not isinstance(body,dict):return jsonify(error='Confirmação inválida.'),400
        with connect() as conn,conn.cursor() as cur:
            if not grant(cur):return jsonify(error='Área exclusiva do dono.'),403
            cur.execute('SELECT password_hash FROM users WHERE id=%s AND status=\'active\'',(actor['user_id'],))
            row=cur.fetchone()
            key=secret()
            fingerprint=hashlib.sha256(key.encode()).hexdigest()
            cur.execute("INSERT INTO owner_access_state(user_id,secret_fingerprint) VALUES(%s,%s) ON CONFLICT(user_id) DO NOTHING",(actor['user_id'],fingerprint))
            cur.execute('SELECT enrolled_at,last_counter,attempts,attempt_window,secret_fingerprint FROM owner_access_state WHERE user_id=%s FOR UPDATE',(actor['user_id'],))
            enrolled,last,attempts,window,stored=cur.fetchone()
            if stored!=fingerprint:return jsonify(error='Configuração de segurança divergente. Procure o suporte.'),503
            now=datetime.now(timezone.utc)
            attempts=attempts+1 if (now-window).total_seconds()<600 else 1
            cur.execute('UPDATE owner_access_state SET attempts=%s,attempt_window=CASE WHEN attempt_window<now()-interval \'10 minutes\' THEN now() ELSE attempt_window END WHERE user_id=%s',(attempts,actor['user_id']))
            if attempts>5:return jsonify(error='Muitas tentativas. Aguarde dez minutos.'),429
            password=body.get('password')
            if not isinstance(password,str) or len(password)>1024 or not row or not verify_password(row[0],password):
                return jsonify(error='Confirmação inválida.'),403
            if enrollment:
                if enrolled:return jsonify(error='Autenticador já configurado.'),409
                # Returned only after authenticated owner + CSRF + password.
                uri=f'otpauth://totp/{quote("SGC:rodrigo")}?secret={key}&issuer=SGC&algorithm=SHA1&digits=6&period=30'
                return jsonify(setupKey=key,setupUri=uri,setupQr=enrollment_qr(uri))
            counter=matching_counter(key,body.get('code'),last_counter=last)
            if counter is None:return jsonify(error='Confirmação inválida ou código já utilizado.'),403
            cur.execute('UPDATE owner_access_state SET last_counter=%s,enrolled_at=COALESCE(enrolled_at,now()),attempts=0 WHERE user_id=%s',(counter,actor['user_id']))
            cur.execute('INSERT INTO owner_session_proofs(session_id,user_id,secret_fingerprint,expires_at) VALUES(%s,%s,%s,now()+interval \'15 minutes\') ON CONFLICT(session_id) DO UPDATE SET secret_fingerprint=EXCLUDED.secret_fingerprint,expires_at=EXCLUDED.expires_at',
                (actor['session_id'],actor['user_id'],fingerprint))
        return jsonify(status='confirmed',expiresInSeconds=900)

    app.add_url_rule('/api/owner/enroll','owner_enroll',require_mutation(lambda:step_up(True)),methods=['POST'])
    app.add_url_rule('/api/owner/verify','owner_verify',require_mutation(step_up),methods=['POST'])

    @app.post('/api/owner/lock')
    @require_mutation
    def owner_lock():
        with connect() as conn,conn.cursor() as cur:
            cur.execute('DELETE FROM owner_session_proofs WHERE session_id=%s AND user_id=%s',(g.principal['session_id'],g.principal['user_id']))
        return jsonify(status='locked')

    @app.get('/api/owner/events')
    @protected
    def owner_events():
        args=request.args
        try:
            limit=int(args.get('limit','50'))
            if limit<1 or limit>100:raise ValueError()
            before=datetime.fromisoformat(args['before']) if args.get('before') else None
            if before and before.tzinfo is None:raise ValueError()
            periods={name:datetime.fromisoformat(args[name]) for name in ('from','until') if args.get(name)}
            if any(value.tzinfo is None for value in periods.values()):raise ValueError()
            if periods.get('from') and periods.get('until') and periods['from']>=periods['until']:raise ValueError()
            before_id=None
            if args.get('beforeId'):
                import uuid
                before_id=str(uuid.UUID(args['beforeId']))
                if not before:raise ValueError()
        except (ValueError,TypeError):return jsonify(error='Filtro inválido.'),400
        clauses=['occurred_at>=now()-interval \'90 days\''];values=[]
        for name,column in [('userId','actor_user_id'),('condominiumId','condominium_id'),('action','action'),('result','result')]:
            value=args.get(name)
            if value:
                if len(value)>160:return jsonify(error='Filtro inválido.'),400
                if name=='userId':
                    import uuid
                    try:value=str(uuid.UUID(value))
                    except ValueError:return jsonify(error='Filtro inválido.'),400
                clauses.append(column+'=%s');values.append(value)
        code=args.get('requestId','').removeprefix('LOCAL-')
        if code:
            import uuid
            try:code=str(uuid.UUID(code))
            except ValueError:return jsonify(error='Código inválido.'),400
            clauses.append("(request_id=%s OR metadata->>'relatedRequestId'=%s OR metadata->>'clientIncidentId'=%s)");values.extend([code,code,code])
        for name,operator in [('from','>='),('until','<')]:
            if name in periods:clauses.append('occurred_at'+operator+'%s');values.append(periods[name])
        if before and before_id:clauses.append('(occurred_at,id)<(%s,%s)');values.extend([before,before_id])
        elif before:clauses.append('occurred_at<%s');values.append(before)
        with connect() as conn,conn.cursor() as cur:
            cur.execute('SELECT id,occurred_at,actor_user_id,condominium_id,request_id,source,action,result,http_status,duration_ms,metadata FROM diagnostic_events WHERE '+' AND '.join(clauses)+' ORDER BY occurred_at DESC,id DESC LIMIT %s',values+[limit])
            rows=cur.fetchall()
        # Only diagnostics; never return audit metadata that may contain reasons.
        names=('id','at','userId','condominiumId','requestId','source','action','result','httpStatus','durationMs','metadata')
        events=[]
        for row in rows:
            event=dict(zip(names,row))
            for key in ('id','userId','requestId'):event[key]=str(event[key]) if event[key] else None
            event['at']=row[1].isoformat()
            events.append(event)
        return jsonify(events=events,nextBefore=events[-1]['at'] if len(events)==limit else None,nextId=events[-1]['id'] if len(events)==limit else None)

    @app.get('/api/owner/overview')
    @protected
    def owner_overview():
        with connect() as conn,conn.cursor() as cur:
            cur.execute("SELECT result,count(*) FROM diagnostic_events WHERE occurred_at>now()-interval '24 hours' GROUP BY result")
            results=dict(cur.fetchall())
            cur.execute('SELECT id,name,active FROM condominiums ORDER BY name LIMIT 200')
            condos=[{'id':row[0],'name':row[1],'active':row[2]} for row in cur.fetchall()]
            cur.execute('SELECT login_display,id FROM users WHERE id IN (SELECT DISTINCT actor_user_id FROM diagnostic_events WHERE occurred_at>now()-interval \'90 days\') ORDER BY login_display LIMIT 200')
            users=[{'id':str(row[1]),'name':row[0]} for row in cur.fetchall()]
        backup={'status':'unavailable'}
        filename=os.getenv('OWNER_BACKUP_STATUS_FILE')
        if filename:
            import json
            try:
                data=json.loads(Path(filename).read_text())
                backup={key:data.get(key) for key in ('status','runId','verifiedAtUtc','files','source','timersActive')}
                if backup.get('status')=='success':
                    verified=datetime.fromisoformat(backup['verifiedAtUtc'].replace('Z','+00:00'))
                    if (datetime.now(timezone.utc)-verified).total_seconds()>30*3600:backup['status']='stale'
            except (OSError,ValueError):pass
        return jsonify(status='ok',database='ok',last24Hours=results,condominiums=condos,users=users,backup=backup,accessExpiresAt=g.owner_expires_at)
