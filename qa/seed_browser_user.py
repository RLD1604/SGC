"""Seed one synthetic browser-test account in an explicitly disposable DB."""
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth import hash_password, normalize_login
from server import connect, initialize


def main():
    if os.environ.get("QA_DISPOSABLE_DATABASE") != "YES":
        raise SystemExit("Recusado: use somente banco descartável.")
    login = normalize_login(os.environ.get("QA_BROWSER_LOGIN", ""))
    password = os.environ.get("QA_BROWSER_PASSWORD", "")
    initialize()
    user_id, membership_id = uuid.uuid4(), uuid.uuid4()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users(id,display_name,login_display,login_normalized,password_hash,status,activated_at,password_changed_at) VALUES(%s,'QA Navegador',%s,%s,%s,'active',now(),now())",
            (user_id, login, login, hash_password(password)),
        )
        cur.execute(
            "INSERT INTO memberships(id,user_id,condominium_id,status,starts_at) VALUES(%s,%s,'sqa','active',now())",
            (membership_id, user_id),
        )
        for role in ("editor", "gestor"):
            cur.execute(
                "INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,starts_at,basis) VALUES(%s,%s,%s,'sqa',%s,now(),'QA descartável de navegador')",
                (uuid.uuid4(), membership_id, user_id, role),
            )
    print("Conta sintética criada no banco descartável.")


if __name__ == "__main__":
    main()
