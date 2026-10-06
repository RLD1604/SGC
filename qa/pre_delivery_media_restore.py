"""Compare synthetic QA restoration by counts and hashes; never print content."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet
from psycopg2 import sql

SOURCE = 'sgc_owner_qa_maverick_preentrega20261006_final'
TARGET = 'sgc_owner_qa_maverick_restore20261006'
mode = os.environ.get('QA_RESTORE_MODE')
expected = SOURCE if mode == 'baseline' else TARGET
assert mode in ('baseline', 'verify') and os.environ.get('DB_NAME') == expected


def snapshot():
    from server import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute('SELECT current_database()')
        assert cur.fetchone()[0] == expected
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
        tables = [row[0] for row in cur.fetchall()]
        counts = {}
        for table in tables:
            cur.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
            counts[table] = cur.fetchone()[0]
        cur.execute('SELECT id,content FROM media ORDER BY id')
        media = [(mid, hashlib.sha256(bytes(content)).hexdigest()) for mid, content in cur.fetchall()]
        assert media and all(mid == digest for mid, digest in media)
        cur.execute('SELECT id,artifact_html,artifact_hash FROM official_publications ORDER BY id')
        artifacts = [(str(pid), hashlib.sha256(bytes(content)).hexdigest(), digest) for pid, content, digest in cur.fetchall()]
        assert len(artifacts) == 1 and all(actual == saved for _, actual, saved in artifacts)
        f = Fernet(Path(os.environ['USER_MFA_KEY_FILE']).read_bytes().strip())
        cur.execute('SELECT user_id,secret_ciphertext FROM user_mfa ORDER BY user_id')
        mfa = [(str(uid), hashlib.sha256(f.decrypt(bytes(value))).hexdigest()) for uid, value in cur.fetchall()]
        assert mfa
        cur.execute('SELECT count(*) FROM pg_index WHERE NOT indisvalid OR NOT indisready')
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated")
        assert cur.fetchone()[0] == 0
        return dict(counts=counts, media=media, artifacts=artifacts, mfa=mfa)


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            data = json.loads(json.dumps(snapshot()))
            baseline = Path('/verify/baseline.json')
            if mode == 'baseline':
                baseline.write_text(json.dumps(data))
                baseline.chmod(0o600)
            else:
                assert data == json.loads(baseline.read_text())
                import runpy
                runpy.run_module('qa.maverick_audit', run_name='__main__')
        print(json.dumps(dict(passed=True, mode=mode, tablesCount=len(data['counts']),
                             restoredMediaCount=len(data['media']), restoredArtifactsCount=len(data['artifacts']),
                             decryptedMfaRows=len(data['mfa']), allTableCountsMatch=mode == 'verify',
                             mediaHashesMatch=True, artifactHashesMatch=True, mfaHashesMatch=mode == 'verify',
                             maverickAuditPassed=mode == 'verify')))
    except Exception as error:
        print(json.dumps(dict(passed=False, mode=mode, errorType=type(error).__name__)))
        raise SystemExit(1)
