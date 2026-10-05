"""Content-free diagnostics, independent fallback and bounded browser reports."""
import json
import time
import uuid
from datetime import datetime, timezone
from flask import g, request, jsonify
from psycopg2.extras import Json


def emit(event):
    # Deliberately omit bodies, exception text, cookies, IP and query strings.
    try:print(json.dumps(event, ensure_ascii=True, separators=(',', ':')), flush=True)
    except (OSError,ValueError):pass


def record(connect, event):
    emit(event)
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SET LOCAL statement_timeout=2000')
            cur.execute('INSERT INTO diagnostic_retention_runs(day) VALUES(current_date) ON CONFLICT DO NOTHING RETURNING day')
            if cur.fetchone():
                cur.execute("DELETE FROM diagnostic_events WHERE occurred_at<now()-interval '90 days'")
            cur.execute('INSERT INTO diagnostic_events(id,actor_user_id,condominium_id,request_id,source,action,result,http_status,duration_ms,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (uuid.uuid4(),event.get('userId'),event.get('condominiumId'),event['requestId'],event['source'],event['action'],event['result'],event.get('httpStatus'),event.get('durationMs'),Json(event.get('metadata',{}))))
    except Exception:
        emit({'action':'diagnostics.persist_failed','result':'error','source':'server','requestId':event['requestId']})


def register_observability(app, connect):
    @app.before_request
    def begin():
        g.request_id=str(uuid.uuid4())
        g.request_started=time.monotonic()

    @app.after_request
    def finish(response):
        request_id=getattr(g,'request_id',str(uuid.uuid4()))
        response.headers['X-Request-ID']=request_id
        if request.path.startswith(('/api/owner/','/api/auth/','/api/diagnostics/')):
            response.headers['Cache-Control']='no-store'
        if request.path.startswith('/api/') and request.path!='/api/health':
            actor=getattr(g,'principal',None) or {}
            status=response.status_code
            event={'at':datetime.now(timezone.utc).isoformat(),'source':'server','action':getattr(g,'business_action',None) or request.endpoint or 'unknown',
                'result':'success' if status<400 else 'denied' if status in (401,403,404) else 'error',
                'requestId':request_id,'userId':actor.get('user_id') or getattr(g,'diagnostic_user_id',None),
                'condominiumId':getattr(g,'business_condominium_id',None) or (actor.get('memberships') or [None])[0],
                'httpStatus':status,'durationMs':round((time.monotonic()-getattr(g,'request_started',time.monotonic()))*1000),
                'metadata':{'method':request.method,'route':request.url_rule.rule if request.url_rule else 'unknown'}}
            if request.endpoint=='client_diagnostics':
                emit(event)  # Quota denials must not amplify database volume.
            else:
                record(connect,event)
        return response

    def client_report():
        actor=getattr(g,'principal',None) or {}
        request.max_content_length=2048
        body=request.get_json(silent=True)
        allowed={'script_error','promise_error','network_error','validation_blocked','navigation','action_attempt'}
        pages={'inicio','registros','novo','nota','registro','revisao','informes','selecionar','editor','previa','publicado','lixeira','owner','unknown'}
        if not isinstance(body,dict) or not isinstance(body.get('kind'),str) or not isinstance(body.get('page'),str) or body.get('kind') not in allowed or body.get('page') not in pages:
            return jsonify(error='Relato inválido.'),400
        # Cross-worker quota; identities and tenant come only from the session.
        with connect() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO diagnostic_quotas(user_id,window_start,hits) VALUES(%s,date_trunc(\'minute\',now()),1) ON CONFLICT(user_id) DO UPDATE SET hits=CASE WHEN diagnostic_quotas.window_start=date_trunc(\'minute\',now()) THEN diagnostic_quotas.hits+1 ELSE 1 END,window_start=date_trunc(\'minute\',now()) RETURNING hits',(actor['user_id'],))
            hits=cur.fetchone()[0]
        if hits>30:
            return jsonify(error='Limite de relatos atingido.'),429
        metadata={'page':body['page'],'untrustedClientReport':True}
        # Only validated UUIDs can refer to a preceding server response.
        try: metadata['relatedRequestId']=str(uuid.UUID(body.get('relatedRequestId','')))
        except (ValueError,TypeError,AttributeError): pass
        try: metadata['clientIncidentId']=str(uuid.UUID(body.get('clientIncidentId','')))
        except (ValueError,TypeError,AttributeError): pass
        record(connect,{'source':'browser','action':body['kind'],'result':'reported','requestId':g.request_id,
            'userId':actor['user_id'],'condominiumId':(actor.get('memberships') or [None])[0], 'metadata':metadata})
        return jsonify(status='received'),202
    return client_report
