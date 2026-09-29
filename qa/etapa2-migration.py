"""Rehearses schema v3 -> v4 on a disposable PostgreSQL database."""
import json
import os
import sys
import uuid
from pathlib import Path
from psycopg2 import sql
from psycopg2.extras import Json

sys.path.insert(0, '/site')
import server

original = os.environ.get('DB_NAME', 'condominio')
database = 'sqa_migration_' + uuid.uuid4().hex
admin = server.connect(); admin.autocommit = True
with admin.cursor() as cur:
    cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
admin.close()

try:
    os.environ['DB_NAME'] = database
    with server.connect() as conn, conn.cursor() as cur:
        cur.execute((Path('/site') / 'schema.sql').read_text())
        legacy = {'id':'legacy-record','title':'Legado','text':'Texto','status':'draft','revision':1,'photos':[]}
        cur.execute('INSERT INTO records(id,document) VALUES(%s,%s)', ('legacy-record', Json(legacy)))
        long_title = dict(legacy, id='legacy-long', title='x' * 161)
        cur.execute('INSERT INTO records(id,document) VALUES(%s,%s)', ('legacy-long', Json(long_title)))
    server.initialize()
    with server.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT document FROM records WHERE id='legacy-record'")
        assert cur.fetchone()[0]['history'] == []
        cur.execute('SELECT count(*) FROM migration_reports WHERE version=4 AND document_id=%s', ('legacy-long',))
        assert cur.fetchone()[0] == 1
        cur.execute('SELECT count(*) FROM schema_versions WHERE version=4')
        assert cur.fetchone()[0] == 1
    server.initialize()
    with server.connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM migration_reports WHERE version=4 AND document_id=%s', ('legacy-long',))
        assert cur.fetchone()[0] == 1
    print('PASS: migração v4 atômica, idempotente e sem truncamento silencioso.')
finally:
    os.environ['DB_NAME'] = original
    admin = server.connect(); admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
    admin.close()
