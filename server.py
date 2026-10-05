"""Transactional PostgreSQL persistence for the condominium editorial workspace."""
import base64
import copy
import hashlib
import html
import io
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import Json, register_uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Flask, jsonify, request, send_from_directory, Response, g
from rich_text import sanitize_documents
from ai_review import register_ai
from auth import register_auth, current_principal, require_session
from authorization import Grant, Principal, Resource, authorize_decision
from editorial_api import register_editorial
from observability import register_observability
from owner_console import register_owner
from user_security import register_user_security

ROOT = Path(__file__).parent
register_uuid()
app = Flask(__name__, static_folder=None)
def normalize_base_path(value):
    """Return an empty path or a normalized mount path such as ``/SGC``."""
    value = (value or '').strip()
    if not value or value == '/':
        return ''
    return '/' + value.strip('/')


APP_BASE_PATH = normalize_base_path(os.getenv('APP_BASE_PATH', ''))
app.config['APP_BASE_PATH'] = APP_BASE_PATH
if APP_BASE_PATH:
    cookie_scope = re.sub(r'[^a-z0-9]+', '_', APP_BASE_PATH.strip('/').lower()).strip('_')
    app.config['AUTH_COOKIE_NAME'] = f'sqa_{cookie_scope}_session'
    app.config['AUTH_CSRF_COOKIE_NAME'] = f'sqa_{cookie_scope}_csrf'
    app.config['AUTH_COOKIE_PATH'] = APP_BASE_PATH
else:
    app.config['AUTH_COOKIE_PATH'] = '/'
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 25000000
TABLES = ('records', 'editions', 'publications')
RECORD_STATUSES = {'draft', 'review', 'ready', 'fix'}
CATEGORIES = {'Obra', 'Compra', 'Manutenção', 'Reparo', 'Serviço', 'Evento', 'Nota solta', 'Outro'}
PROGRESS_VALUES = {'Não informado', 'Em andamento', 'Concluído'}


def connect():
    password = Path(os.environ['DB_PASSWORD_FILE']).read_text().strip()
    return psycopg2.connect(host=os.getenv('DB_HOST', 'database'), dbname=os.getenv('DB_NAME', 'condominio'), user=os.getenv('DB_USER', 'condominio'), password=password, connect_timeout=5)


def audit_event(cur, actor, action, entity_type, entity_id, result, *, revision_id=None, metadata=None):
    """Write a content-free operational audit event in the caller transaction."""
    actor_user = actor.get('user_id') if isinstance(actor, dict) else None
    session_id = actor.get('session_id') if isinstance(actor, dict) else None
    condominium_id = (metadata or {}).get('condominium_id') or ((actor.get('memberships') or [None])[0] if isinstance(actor, dict) else None)
    scope_tables={'record':('record_metadata','record_id'),'edition':('edition_metadata','edition_id'),'publication':('official_publications','id')}
    if entity_type in scope_tables:
        scope_table,scope_column=scope_tables[entity_type]
        cur.execute('SELECT condominium_id FROM '+scope_table+' WHERE '+scope_column+'=%s',(entity_id,))
        scope=cur.fetchone()
        if scope:condominium_id=scope[0]
    g.business_action=action
    g.business_condominium_id=condominium_id
    cur.execute(
        'INSERT INTO audit_events(id,condominium_id,actor_user_id,session_id,action,entity_type,entity_id,revision_id,result,correlation_id,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (uuid.uuid4(), condominium_id, actor_user, session_id, action, entity_type, entity_id,
         revision_id, result, getattr(g,'request_id',str(uuid.uuid4())), Json(metadata or {})))


def auth_audit(action, *, actor_user_id=None, subject_user_id=None, outcome='success', details=None):
    """Authentication failures need their own short transaction."""
    result = outcome if outcome in ('success', 'denied', 'error') else ('denied' if outcome in ('rejected',) else 'success')
    g.diagnostic_user_id=actor_user_id or subject_user_id
    with connect() as conn, conn.cursor() as cur:
        if g.diagnostic_user_id:
            cur.execute("SELECT condominium_id FROM memberships WHERE user_id=%s AND status='active' ORDER BY condominium_id LIMIT 1",(g.diagnostic_user_id,))
            scope=cur.fetchone()
            if scope:g.business_condominium_id=scope[0]
        cur.execute(
            'INSERT INTO audit_events(id,actor_user_id,subject_user_id,action,result,correlation_id,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s)',
            (uuid.uuid4(), actor_user_id, subject_user_id, action, result,
             getattr(g,'request_id',str(uuid.uuid4())), Json(details or {})))


def _authorization_principal(actor, condominium_id, cur):
    """Reload grants from PostgreSQL; browser roles are never trusted."""
    cur.execute("SELECT id FROM memberships WHERE user_id=%s AND condominium_id=%s AND status='active' AND (starts_at IS NULL OR starts_at<=now()) AND (ends_at IS NULL OR ends_at>now())", (actor['user_id'], condominium_id))
    membership = cur.fetchone()
    if not membership:
        return None
    membership_id = str(membership[0])
    cur.execute("SELECT id,role,starts_at,ends_at,revoked_at FROM role_grants WHERE user_id=%s AND condominium_id=%s", (actor['user_id'], condominium_id))
    grants = tuple(Grant(role=row[1], condominium_id=condominium_id, membership_id=membership_id,
                         grant_id=str(row[0]), valid_from=row[2], valid_until=row[3], revoked_at=row[4])
                   for row in cur.fetchall())
    return Principal(membership_id, condominium_id, grants, True)


def authorize_request(actor, permission, resource=None, *, cur=None, return_grant=False):
    own_connection = cur is None
    conn = connect() if own_connection else None
    cursor = conn.cursor() if own_connection else cur
    try:
        condominium_id = str((resource or {}).get('condominium_id') or ((actor.get('memberships') or [''])[0]))
        principal = _authorization_principal(actor, condominium_id, cursor)
        if not principal:
            return None if return_grant else False
        projected = None
        if permission not in ('item.create', 'accounts.manage'):
            kind = ('item' if permission.startswith('item.') else
                    'publication' if permission.startswith('publication.') and permission.endswith('.read') else
                    'edition_revision' if permission in ('edition.approve', 'publication.export') else 'edition')
            status = str((resource or {}).get('state') or (resource or {}).get('status') or ('published' if kind == 'publication' else 'draft'))
            author_membership_id = None
            author_user_id = (resource or {}).get('author_user_id')
            if author_user_id:
                cursor.execute("SELECT id FROM memberships WHERE user_id=%s AND condominium_id=%s", (author_user_id, condominium_id))
                author_row = cursor.fetchone()
                author_membership_id = str(author_row[0]) if author_row else None
            assigned = set()
            document_id = (resource or {}).get('document_id')
            if document_id:
                cursor.execute("SELECT 1 FROM document_assignments WHERE condominium_id=%s AND document_type=%s AND document_id=%s AND user_id=%s AND revoked_at IS NULL AND valid_from<=now() AND (valid_until IS NULL OR valid_until>now())", (condominium_id, 'record' if kind == 'item' else 'edition', document_id, actor['user_id']))
                if cursor.fetchone():
                    assigned.add(principal.membership_id)
            projected = Resource(kind, condominium_id, status, author_membership_id, frozenset(assigned), kind in ('edition_revision', 'publication'))
        decision = authorize_decision(principal, permission, projected)
        return decision.grant_id if return_grant and decision.allowed else (None if return_grant else decision.allowed)
    finally:
        if own_connection:
            cursor.close()
            conn.close()


def initialize():
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(90012026)')
        cur.execute((ROOT / 'schema.sql').read_text())
        migrate_v4(cur)
        cur.execute("INSERT INTO edition_metadata(edition_id,condominium_id,current_revision,workflow_state,legacy_import) SELECT id,'sqa',GREATEST(COALESCE((document->>'version')::integer,1),'1'::integer),'draft',true FROM editions ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO record_metadata(record_id,condominium_id,current_revision,legacy_import) SELECT id,'sqa',GREATEST(COALESCE((document->>'revision')::integer,1),'1'::integer),true FROM records ON CONFLICT DO NOTHING")
        backfill_media_references(cur)


def backfill_media_references(cur):
    """Associate legacy media without assigning legacy authorship."""
    cur.execute('SELECT id,document FROM records')
    record_rows = cur.fetchall()
    cur.execute('SELECT id,document FROM editions')
    edition_rows = cur.fetchall()
    from editorial_api import _photo_ids
    for document_id, document in record_rows:
        for media_id in _photo_ids(document):
            cur.execute("INSERT INTO media_references(media_id,condominium_id,document_type,document_id) VALUES(%s,'sqa','record',%s) ON CONFLICT DO NOTHING", (media_id, document_id))
    for document_id, document in edition_rows:
        for media_id in _photo_ids(document):
            cur.execute("INSERT INTO media_references(media_id,condominium_id,document_type,document_id) VALUES(%s,'sqa','edition',%s) ON CONFLICT DO NOTHING", (media_id, document_id))


def read_state(cur):
    result = {}
    for table in TABLES:
        cur.execute(f'SELECT document FROM {table} ORDER BY updated_at,id')
        result[table] = [row[0] for row in cur.fetchall()]
    return result


def migration_report(cur, collection, document_id, message):
    cur.execute('INSERT INTO migration_reports(version,collection,document_id,message) VALUES(4,%s,%s,%s) ON CONFLICT DO NOTHING', (collection, document_id, message))


def migrate_v4(cur):
    """Apply recognized legacy shapes atomically; flag ambiguous data without guessing."""
    cur.execute('SELECT 1 FROM schema_versions WHERE version=4')
    if cur.fetchone():
        return
    for collection in TABLES:
        cur.execute(f'SELECT id,document FROM {collection} FOR UPDATE')
        for document_id, document in cur.fetchall():
            changed = False
            if collection == 'records' and 'history' not in document:
                document['history'] = []
                changed = True
            if isinstance(document.get('title'), str) and len(document['title']) > 160 and collection == 'records':
                migration_report(cur, collection, document_id, 'Assunto antigo acima de 160 caracteres; corrija-o antes de salvar novamente.')
            if changed:
                cur.execute(f'UPDATE {collection} SET document=%s,updated_at=now() WHERE id=%s', (Json(document), document_id))
    cur.execute('INSERT INTO schema_versions(version) VALUES(4)')


def fail(path, message):
    raise ValueError(f'{path}: {message}')


def text(value, path, *, required=False, maximum=1000):
    if not isinstance(value, str):
        fail(path, 'deve ser um texto.')
    if len(value) > maximum:
        fail(path, f'não pode ultrapassar {maximum} caracteres.')
    if required and not value.strip():
        fail(path, 'não pode ficar vazio.')


def identifier(value, path):
    if not isinstance(value, str) or not re.fullmatch(r'[\w-]{1,100}', value):
        fail(path, 'identificador inválido.')


def real_date(value, path):
    if value == '':
        return
    text(value, path, maximum=10)
    try:
        date.fromisoformat(value)
    except ValueError:
        fail(path, 'a data informada não existe.')


def iso_time(value, path):
    text(value, path, maximum=40)
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        fail(path, 'data e hora inválidas.')


def validate_photo(photo, path):
    if not isinstance(photo, dict):
        fail(path, 'deve ser uma foto.')
    text(photo.get('src'), path + '.src', required=True, maximum=20_000_000)
    for field in ('caption', 'phase', 'orientation', 'masterSrc', 'originalSrc'):
        if field in photo:
            text(photo[field], path + '.' + field, maximum=20_000_000 if field.endswith('Src') else 1000)


def validate_history(history, path):
    if not isinstance(history, list):
        fail(path, 'deve ser uma lista.')
    if len(history) > 1000:
        fail(path, 'ultrapassa o limite permitido.')
    for index, item in enumerate(history, 1):
        item_path = f'{path} {index}'
        if not isinstance(item, dict):
            fail(item_path, 'deve ser um item de histórico.')
        iso_time(item.get('at'), item_path + '.at')
        text(item.get('text'), item_path + '.text', required=True)


def meaningful_rich_text(value):
    if not isinstance(value, str):
        return False
    plain = html.unescape(re.sub(r'<[^>]*>', ' ', value)).replace('\xa0', ' ')
    return bool(plain.strip())


def validate_status_transitions(previous, incoming):
    """Central server-side gate for review and approval, including direct API writes."""
    before = {row['id']: row for row in previous['records']}
    for index, record in enumerate(incoming['records'], 1):
        old = before.get(record['id'])
        if old and old.get('status') == record['status']:
            continue
        if record['status'] not in ('review', 'ready'):
            continue
        path = f'Registro {index}'
        if not meaningful_rich_text(record.get('title')):
            fail(path + '.assunto', 'é obrigatório para enviar à revisão ou conferir.')
        if not meaningful_rich_text(record.get('textHtml', record.get('text'))):
            fail(path + '.texto', 'é obrigatório para enviar à revisão ou conferir.')


def migrate_legacy_state(data):
    """Normalize only recognized, unambiguous legacy omissions."""
    migrated = copy.deepcopy(data)
    if isinstance(migrated, dict) and isinstance(migrated.get('records'), list):
        for record in migrated['records']:
            if isinstance(record, dict) and 'history' not in record:
                record['history'] = []
    return migrated


def validate(data):
    if not isinstance(data, dict) or set(data) != set(TABLES):
        raise ValueError('Estrutura do acervo inválida.')
    records_by_id = {row.get('id'): row for row in data.get('records', []) if isinstance(row, dict)}
    record_ids = set(records_by_id)
    for table in TABLES:
        rows = data[table]
        if not isinstance(rows, list) or len(rows) > 20000:
            raise ValueError('Quantidade de documentos inválida.')
        seen = set()
        for index, row in enumerate(rows):
            path = f'{"Registro" if table == "records" else "Informe" if table == "editions" else "Publicação"} {index + 1}'
            if not isinstance(row, dict):
                fail(path, 'deve ser um documento.')
            identifier(row.get('id'), path + '.id')
            if row['id'] in seen:
                fail(path + '.id', 'está repetido.')
            seen.add(row['id'])
            text(row.get('title'), path + '.título', required=table != 'records' or row.get('status') in ('review', 'ready'), maximum=160 if table == 'records' else 1000)
            if row.get('cover') is not None and not isinstance(row['cover'],str):
                fail(path + '.capa', 'deve ser um texto.')
            if table == 'records':
                if 'deletedAt' in row: iso_time(row['deletedAt'], path + '.data da lixeira')
                if row.get('status') not in RECORD_STATUSES:
                    fail(path + '.situação', 'é inválida.')
                for field in ('text', 'textHtml', 'category', 'local', 'date', 'who', 'progress', 'feedback', 'feedbackHtml'):
                    if field in row: text(row[field], path + '.' + field, maximum=100000 if field in ('text', 'textHtml', 'feedback', 'feedbackHtml') else 5000)
                real_date(row.get('date', ''), path + '.data')
                if row.get('category', '') not in ('', *CATEGORIES): fail(path + '.categoria', 'não é uma opção permitida.')
                if row.get('progress', 'Não informado') not in PROGRESS_VALUES: fail(path + '.andamento', 'não é uma opção permitida.')
                if not isinstance(row.get('revision'), int) or row['revision'] < 1: fail(path + '.revisão', 'deve ser um número inteiro positivo.')
                validate_history(row.get('history', []), path + '.histórico')
                if row['status'] in ('review', 'ready') and not meaningful_rich_text(row.get('textHtml', row.get('text', ''))):
                    fail(path + '.texto', 'é obrigatório para enviar à revisão.')
                row.setdefault('photos', [])
            photos = row.get('photos', []) if table == 'records' else []
            if table != 'records':
                if not isinstance(row.get('blocks'), list) or len(row['blocks']) > 1000:
                    raise ValueError('Blocos inválidos.')
                block_ids = set()
                for block_index, block in enumerate(row['blocks']):
                    block_path = f'{path}, bloco {block_index + 1}'
                    if not isinstance(block, dict): fail(block_path, 'deve ser um bloco.')
                    identifier(block.get('id'), block_path + '.id')
                    if block['id'] in block_ids: fail(block_path + '.id', 'está repetido.')
                    text(block.get('type'), block_path + '.tipo', required=True, maximum=100)
                    text(block.get('title'), block_path + '.título', required=True)
                    text(block.get('body'), block_path + '.texto', maximum=100000)
                    block_ids.add(block['id'])
                    if not isinstance(block.get('photos', []), list):
                        fail(block_path + '.fotos', 'deve ser uma lista.')
                    if not isinstance(block.get('sources',[]),list): fail(block_path + '.fontes', 'deve ser uma lista.')
                    for source_index, source in enumerate(block.get('sources', []), 1):
                        if not isinstance(source, dict): fail(f'{block_path}, fonte {source_index}', 'deve ser uma fonte.')
                        identifier(source.get('id'), f'{block_path}, fonte {source_index}.id')
                        if source['id'] not in record_ids: fail(f'{block_path}, fonte {source_index}.id', 'não referencia um registro existente.')
                        if 'revision' in source and (not isinstance(source['revision'], int) or source['revision'] < 1): fail(f'{block_path}, fonte {source_index}.revisão', 'deve ser um número inteiro positivo.')
                        if source.get('revision') > records_by_id[source['id']].get('revision', 0): fail(f'{block_path}, fonte {source_index}.revisão', 'é posterior à revisão do registro referenciado.')
                        if 'title' in source: text(source['title'], f'{block_path}, fonte {source_index}.título')
                    photos += block.get('photos', [])
                text(row.get('period'), path + '.período', required=True)
                if not isinstance(row.get('version'), int) or row['version'] < 1: fail(path + '.versão', 'deve ser um número inteiro positivo.')
            if not isinstance(photos, list): fail(path + '.fotos', 'deve ser uma lista.')
            for photo_index, photo in enumerate(photos, 1): validate_photo(photo, f'{path}, foto {photo_index}')


def store_image(src, cur, mapping, master=False):
    key=(src,master)
    if key in mapping:
        return mapping[key]
    if re.fullmatch(r'/api/media/[a-f0-9]{64}', src):
        cur.execute('SELECT mime,width,height,octet_length(content) FROM media WHERE id=%s', (src.rsplit('/',1)[1],))
        row = cur.fetchone()
        if not row:
            raise ValueError('Uma foto não foi encontrada no banco.')
        result = dict(src=src, mime=row[0], width=row[1], height=row[2], bytes=row[3])
        mapping[key] = result
        return result
    if src.startswith('data:image/'):
        try:
            header, payload = src.split(',',1)
            if ';base64' not in header:
                raise ValueError()
            raw = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError):
            raise ValueError('Foto codificada incorretamente.')
    elif src in ('/images/jardim.jpg','/images/hall.jpg','/images/luzes.jpg'):
        raw = (ROOT / 'public' / src.lstrip('/')).read_bytes()
    else:
        raise ValueError('Use fotos enviadas ao sistema, sem endereços externos.')
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError('A foto ultrapassa 12 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('JPEG','PNG','WEBP'):
                raise ValueError('Use fotos JPG, PNG ou WebP.')
            im = ImageOps.exif_transpose(source)
            im.thumbnail((2048,2048) if master else (600,1065) if im.height > im.width else (1065,600), Image.Resampling.LANCZOS)
            im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
            output = io.BytesIO()
            im.save(output, format='WEBP', quality=88)
            encoded, mime = output.getvalue(), 'image/webp'
            png = io.BytesIO()
            im.save(png, format='PNG')
            if len(png.getvalue()) < len(encoded):
                encoded, mime = png.getvalue(), 'image/png'
            # Keep already optimized, metadata-free bytes stable across publications.
            if source.size == im.size and source.format in ('PNG','WEBP') and not source.info.get('exif') and not source.info.get('icc_profile') and not getattr(source,'is_animated',False):
                encoded, mime = raw, 'image/png' if source.format == 'PNG' else 'image/webp'
            digest = hashlib.sha256(encoded).hexdigest()
            cur.execute('INSERT INTO media(id,mime,width,height,content) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING', (digest,mime,im.width,im.height,encoded))
            result = dict(src='/api/media/'+digest, mime=mime, width=im.width, height=im.height, bytes=len(encoded), optimizationVersion=2)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('Não foi possível ler a foto.')
    mapping[key] = result
    return result


def normalize(data, cur):
    sanitize_documents(data,cur)
    mapping = {}
    for table in TABLES:
        for row in data[table]:
            containers = [row] if table == 'records' else row['blocks']
            for container in containers:
                for photo in container.get('photos', []):
                    photo.update(store_image(photo['src'],cur,mapping))
                    for field in ('masterSrc','originalSrc'):
                        if field in photo:
                            if not isinstance(photo[field],str):
                                raise ValueError('Cópia de edição inválida.')
                            stored=store_image(photo[field],cur,mapping,master=True)
                            photo[field]=stored['src']
                            if field=='masterSrc':photo['masterBytes']=stored['bytes']
            if row.get('cover'):
                row['cover'] = store_image(row['cover'],cur,mapping)['src']
    return data


def write_state(cur, data, revision):
    changes = []
    for table in TABLES:
        cur.execute(f'SELECT id,document FROM {table}')
        previous = dict(cur.fetchall())
        incoming = {row['id']:row for row in data[table]}
        if table == 'publications' and any(incoming.get(k) != v for k,v in previous.items()):
            raise ValueError('Informes finalizados são preservados. Crie uma revisão para corrigir.')
        for key, row in incoming.items():
            if previous.get(key) != row:
                changes.append({'collection':table,'id':key,'before':previous.get(key),'after':row})
                cur.execute(f'INSERT INTO {table}(id,document) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET document=EXCLUDED.document,updated_at=now()', (key,Json(row)))
        for key in previous.keys() - incoming.keys():
            changes.append({'collection':table,'id':key,'before':previous[key],'after':None})
            cur.execute(f'DELETE FROM {table} WHERE id=%s',(key,))
    revision += 1
    cur.execute('UPDATE workspace_state SET revision=%s WHERE id=1',(revision,))
    cur.execute('INSERT INTO change_history(revision,changes) VALUES(%s,%s)',(revision,Json(changes)))
    return revision


@app.before_request
def same_origin():
    if request.method in ('POST','PUT','DELETE','PATCH'):
        if request.path.startswith('/api/auth/'):
            request.max_content_length=4096
        if request.is_json and not isinstance(request.get_json(silent=True),dict):
            return jsonify(error='Envie um objeto JSON válido.'),400
        origin = request.headers.get('Origin')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlsplit(origin).netloc != request.host):
            return jsonify(error='Origem da solicitação não permitida.'),403
        if not request.is_json:
            return jsonify(error='Envie dados JSON.'),415


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    if request.path.startswith('/api/') and not request.path.startswith('/api/media/'):
        response.headers['Cache-Control']='no-store'
    # Keep media references canonical in PostgreSQL and prefix only the HTTP
    # representation. The matching request normalizer below removes this
    # mount prefix before application code can persist a submitted document.
    if APP_BASE_PATH and response.is_json:
        payload = response.get_json(silent=True)
        if payload is not None:
            response.set_data(json.dumps(_rewrite_media_urls(payload, APP_BASE_PATH), ensure_ascii=False, separators=(',', ':')))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


def _rewrite_media_urls(value, base_path, *, inbound=False):
    """Translate only known media URL fields at the HTTP boundary."""
    if isinstance(value, list):
        return [_rewrite_media_urls(item, base_path, inbound=inbound) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ('src', 'originalSrc', 'masterSrc', 'cover') and isinstance(item, str):
                if inbound and item.startswith(base_path + '/'):
                    item = item[len(base_path):]
                elif not inbound and item.startswith(('/api/', '/images/')):
                    item = base_path + item
            result[key] = _rewrite_media_urls(item, base_path, inbound=inbound)
        return result
    return value


@app.before_request
def canonicalize_submitted_media_urls():
    if APP_BASE_PATH and request.is_json:
        payload = request.get_json(silent=True)
        if payload is not None:
            request._cached_json = (_rewrite_media_urls(payload, APP_BASE_PATH, inbound=True),
                                    _rewrite_media_urls(payload, APP_BASE_PATH, inbound=True))


@app.errorhandler(ValueError)
def invalid(error):
    return jsonify(error=str(error)),400


@app.errorhandler(psycopg2.Error)
def database_error(error):
    app.logger.error('Database operation failed; request_id=%s; type=%s',getattr(g,'request_id','unknown'),type(error).__name__)
    return jsonify(error='O banco está indisponível. Seu trabalho não foi confirmado; tente salvar novamente.'),503


@app.get('/api/health')
def health():
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1')
        return jsonify(status='ok', database='PostgreSQL', schema=cur.fetchone()[0], application=json.loads((ROOT/'public/version.json').read_text()))


@app.route('/api/state', methods=['GET','PUT'])
def workspace():
    return jsonify(error='A API global foi desativada. Use a API autenticada por documento.'),410
    # Historical implementation retained below temporarily for rollback review;
    # the unconditional return above makes it unreachable to every account.
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT revision FROM workspace_state WHERE id=1 FOR UPDATE')
        revision = cur.fetchone()[0]
        if request.method == 'GET':
            return jsonify(state=read_state(cur),revision=revision)
        body = request.get_json()
        operation_id=request.headers.get('Idempotency-Key')
        payload_hash=None
        if operation_id:
            if not re.fullmatch(r'[\w-]{1,100}',operation_id):
                raise ValueError('Identificação da operação inválida.')
            payload_hash=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            cur.execute('SELECT payload_hash,response FROM operation_requests WHERE id=%s FOR UPDATE',(operation_id,))
            previous=cur.fetchone()
            if previous:
                if previous[0]!=payload_hash:
                    return jsonify(error='A mesma operação não pode ser reutilizada com conteúdo diferente.'),409
                return jsonify(previous[1])
        if not isinstance(body,dict) or body.get('revision') != revision:
            return jsonify(error='Outra sessão salvou alterações. Exporte seu rascunho e recarregue para revisar a versão atual.'),409
        data = body.get('state')
        validate(data)
        validate_status_transitions(read_state(cur), data)
        normalize(data,cur)
        revision = write_state(cur,data,revision)
        response=dict(state=data,revision=revision)
        if operation_id:
            cur.execute('INSERT INTO operation_requests(id,payload_hash,response) VALUES(%s,%s,%s)',(operation_id,payload_hash,Json(response)))
        return jsonify(response)


@app.post('/api/import')
def import_browser():
    return jsonify(error='A importação global foi desativada; use a ferramenta administrativa auditada.'),410
    body = request.get_json()
    if not isinstance(body,dict) or not isinstance(body.get('importId'), str) or not re.fullmatch(r'[\w-]{1,100}',body['importId']):
        raise ValueError('Identificador da importação inválido.')
    legacy = migrate_legacy_state(body.get('state'))
    validate(legacy)
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT revision FROM workspace_state WHERE id=1 FOR UPDATE')
        revision = cur.fetchone()[0]
        cur.execute('SELECT 1 FROM browser_imports WHERE id=%s',(body['importId'],))
        if cur.fetchone():
            return jsonify(state=read_state(cur),revision=revision,alreadyImported=True)
        existing = read_state(cur)
        ids = {r['id']:str(uuid.uuid4()) for r in legacy['records']}
        for table in TABLES:
            for row in legacy[table]:
                row['id'] = ids[row['id']] if table == 'records' else str(uuid.uuid4())
                for block in row.get('blocks',[]):
                    block['id']=str(uuid.uuid4())
                    for source in block.get('sources',[]):
                        if source.get('id') in ids:
                            source['id']=ids[source['id']]
        normalize(legacy,cur)
        for table in TABLES:
            existing[table].extend(legacy[table])
        revision=write_state(cur,existing,revision)
        cur.execute('INSERT INTO browser_imports(id,revision) VALUES(%s,%s)',(body['importId'],revision))
        return jsonify(state=existing,revision=revision)


@app.get('/api/media/<digest>')
def media(digest):
    return jsonify(error='Use a rota de mídia vinculada a um documento autorizado.'),404
    if not re.fullmatch(r'[a-f0-9]{64}',digest):
        return '',404
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT mime,content FROM media WHERE id=%s',(digest,))
        row=cur.fetchone()
    if not row:
        return '',404
    response=Response(bytes(row[1]),mimetype=row[0])
    response.set_etag(digest)
    response.cache_control.max_age=31536000
    response.cache_control.private=True
    return response.make_conditional(request)


@app.get('/')
def index():
    return _html_file('index.html')


def _html_file(filename):
    public_root = (ROOT / 'public').resolve()
    path = (public_root / filename).resolve()
    try:
        path.relative_to(public_root)
    except ValueError:
        return '', 404
    if not path.is_file():
        return '', 404
    content = path.read_text(encoding='utf-8')
    content = content.replace('<head>', '<head><script src="/base-path.js"></script>', 1)
    if APP_BASE_PATH:
        # Root-relative assets and links in first-party HTML belong to this
        # app mount. API calls made by inline/page scripts are handled by the
        # base-path fetch adapter.
        content = re.sub(r'((?:src|href)="?)/(?!/)', lambda match: match.group(1) + APP_BASE_PATH + '/', content)
        content = content.replace('<head>', f'<head><base href="{APP_BASE_PATH}/"><meta name="sqa-base-path" content="{APP_BASE_PATH}">', 1)
    headers={'Cache-Control':'no-cache'}
    if filename=='owner.html':
        headers.update({'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'})
    return Response(content, mimetype='text/html', headers=headers)


@app.get('/<path:filename>')
def static_file(filename):
    if filename in {'beta.html', 'ia.html', 'owner.html'}:
        return _html_file(filename)
    return send_from_directory(ROOT / 'public',filename,max_age=0)


app.config['AUTH_COOKIE_SECURE'] = os.getenv('AUTH_COOKIE_SECURE', 'false').lower() == 'true'
client_report = register_observability(app, connect)
auth_service = register_auth(app, connect, auth_audit)
app.add_url_rule('/api/diagnostics/client','client_diagnostics',auth_service.require_csrf(client_report),methods=['POST'])
app.config['AUTH_CAN_MANAGE_ACCOUNTS'] = lambda actor, condominium_id=None: authorize_request(
    actor, 'accounts.manage', {'condominium_id': condominium_id} if condominium_id else None
)
register_editorial(app, connect, current_principal, require_session, auth_service.require_csrf,
                   authorize_request, validate, normalize, read_state, audit_event)
register_ai(app,connect,current_principal,require_session,auth_service.require_csrf,authorize_request)
register_owner(app,connect,require_session,auth_service.require_csrf)
register_user_security(app,connect,auth_service)

def diagnostic_resource(actor,kind,document_id):
    if kind not in ('record','edition','publication') or not isinstance(document_id,str) or not re.fullmatch(r'[\w-]{1,100}',document_id):return None
    if kind=='publication':
        try:document_id=str(uuid.UUID(document_id))
        except ValueError:return None
    table,key,permission={'record':('record_metadata','record_id','item.read'),'edition':('edition_metadata','edition_id','edition.read'),'publication':('official_publications','id','publication.read')}[kind]
    with connect() as conn,conn.cursor() as cur:
        cur.execute('SELECT condominium_id,'+('NULL' if kind=='publication' else 'author_user_id')+' FROM '+table+' WHERE '+key+'=%s',(document_id,))
        row=cur.fetchone()
        if not row or not authorize_request(actor,permission,{'condominium_id':row[0],'author_user_id':str(row[1]) if row[1] else None,'document_id':document_id},cur=cur):return None
    return {'type':kind,'id':document_id}
app.config['AUTH_DIAGNOSTIC_RESOURCE']=diagnostic_resource



class BasePathMiddleware:
    """Allow either direct prefix forwarding or a proxy that strips the prefix."""
    def __init__(self, application, base_path):
        self.application = application
        self.base_path = base_path

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if self.base_path and path == self.base_path:
            start_response('308 Permanent Redirect', [('Location', self.base_path + '/'), ('Content-Length', '0')])
            return [b'']
        if self.base_path and path.startswith(self.base_path + '/'):
            environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + self.base_path
            environ['PATH_INFO'] = path[len(self.base_path):] or '/'
        return self.application(environ, start_response)


app.wsgi_app = BasePathMiddleware(app.wsgi_app, APP_BASE_PATH)

if __name__ == '__main__':
    initialize()
