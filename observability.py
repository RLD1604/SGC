"""Content-free diagnostics, independent fallback and bounded browser reports."""
import json
import time
import uuid
import re
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
            cur.execute('INSERT INTO diagnostic_events(id,actor_user_id,condominium_id,request_id,source,action,result,http_status,duration_ms,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                (uuid.uuid4(),event.get('userId'),event.get('condominiumId'),event['requestId'],event['source'],event['action'],event['result'],event.get('httpStatus'),event.get('durationMs'),Json(event.get('metadata',{}))))
        return True
    except Exception:
        emit({'action':'diagnostics.persist_failed','result':'error','source':'server','requestId':event['requestId']})
        return False


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
            resources={key:str(value) for key,value in (request.view_args or {}).items() if key in ('record_id','edition_id','document_id','document_type','publication_id','revision_id','media_id') and re.fullmatch(r'[\w-]{1,100}',str(value))}
            if resources:event['metadata']['resource']=resources
            changed=getattr(g,'diagnostic_changed_fields',None)
            if changed is not None:event['metadata']['changedFields']=changed
            delivered=getattr(g,'delivered_resources',None)
            if delivered is not None:event['metadata']['deliveredResources']=delivered[:100]
            if request.endpoint=='client_diagnostics':
                emit(event)  # Quota denials must not amplify database volume.
            else:
                record(connect,event)
        return response

    def client_report():
        actor=getattr(g,'principal',None) or {}
        request.max_content_length=2048
        body=request.get_json(silent=True)
        allowed={'script_error','promise_error','network_error','validation_blocked','navigation','action_attempt','document_view'}
        pages={'inicio','registros','novo','nota','registro','revisao','informes','selecionar','editor','previa','publicado','lixeira','owner','unknown'}
        if not isinstance(body,dict) or not isinstance(body.get('kind'),str) or not isinstance(body.get('page'),str) or body.get('kind') not in allowed or body.get('page') not in pages:
            return jsonify(error='Relato inválido.'),400
        # Cross-worker quota; identities and tenant come only from the session.
        try:
            with connect() as conn, conn.cursor() as cur:
                cur.execute('INSERT INTO diagnostic_quotas(user_id,window_start,hits) VALUES(%s,date_trunc(\'minute\',now()),1) ON CONFLICT(user_id) DO UPDATE SET hits=CASE WHEN diagnostic_quotas.window_start=date_trunc(\'minute\',now()) THEN diagnostic_quotas.hits+1 ELSE 1 END,window_start=date_trunc(\'minute\',now()) RETURNING hits,GREATEST(1,CEIL(EXTRACT(EPOCH FROM window_start+interval \'1 minute\'-now())))::integer',(actor['user_id'],))
                hits,retry_after=cur.fetchone()
        except Exception:
            response=jsonify(error='Relato temporariamente indisponível.');response.status_code=503
            response.headers['Retry-After']='5'
            return response
        if hits>120:
            response=jsonify(error='Limite de relatos atingido.');response.status_code=429
            response.headers['Retry-After']=str(retry_after)
            return response
        metadata={'page':body['page'],'untrustedClientReport':True}
        if body['kind']=='document_view':
            checker=app.config.get('AUTH_DIAGNOSTIC_RESOURCE')
            resource=checker(actor,body.get('resourceType'),body.get('resourceId')) if checker else None
            if not resource:return jsonify(error='Documento não encontrado.'),404
            metadata['resource']=resource
        # Only validated UUIDs can refer to a preceding server response.
        try: metadata['relatedRequestId']=str(uuid.UUID(body.get('relatedRequestId','')))
        except (ValueError,TypeError,AttributeError): pass
        try: metadata['clientIncidentId']=str(uuid.UUID(body.get('clientIncidentId','')))
        except (ValueError,TypeError,AttributeError): pass
        try: metadata['reportId']=str(uuid.UUID(body.get('reportId','')))
        except (ValueError,TypeError,AttributeError): pass
        persisted=record(connect,{'source':'browser','action':body['kind'],'result':'reported','requestId':g.request_id,
            'userId':actor['user_id'],'condominiumId':(actor.get('memberships') or [None])[0], 'metadata':metadata})
        if not persisted:
            response=jsonify(error='Relato temporariamente indisponível.');response.status_code=503
            response.headers['Retry-After']='5'
            return response
        return jsonify(status='received'),202
    return client_report
