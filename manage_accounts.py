"""Local, auditable bootstrap for accounts. Never accepts a password argument."""
import argparse
import json
import uuid
from datetime import timedelta

from auth import INVITATION_TIMEOUT, RECOVERY_TIMEOUT, generate_token, normalize_login, utcnow
from server import connect, initialize

ROLES = ('encarregado','supervisor','editor','gestor','sindico','administrador_tecnico','responsavel_acessos')


def invite(login, name, roles, condominium='sqa'):
    normalized = normalize_login(login)
    raw, token_hash = generate_token()
    user_id, membership_id, invitation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT 1 FROM users WHERE login_normalized=%s', (normalized,))
        if cur.fetchone():
            raise SystemExit('A conta já existe; nenhum convite foi criado.')
        cur.execute("INSERT INTO users(id,display_name,login_display,login_normalized,status) VALUES(%s,%s,%s,%s,'invited')", (user_id, name.strip(), login.strip(), normalized))
        cur.execute("INSERT INTO memberships(id,user_id,condominium_id,status) VALUES(%s,%s,%s,'active')", (membership_id, user_id, condominium))
        for role in roles:
            cur.execute('INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,basis) VALUES(%s,%s,%s,%s,%s,%s)', (uuid.uuid4(), membership_id, user_id, condominium, role, 'Bootstrap local documentado'))
        cur.execute('INSERT INTO invitations(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,%s)', (invitation_id, user_id, token_hash, utcnow() + INVITATION_TIMEOUT))
        cur.execute("INSERT INTO audit_events(id,condominium_id,subject_user_id,action,result,correlation_id,metadata) VALUES(%s,%s,%s,'account.bootstrap','success',%s,%s)", (uuid.uuid4(), condominium, user_id, str(uuid.uuid4()), json.dumps({'roles': list(roles)})))
    print(json.dumps({'userId': str(user_id), 'login': normalized, 'roles': list(roles), 'activationToken': raw, 'expiresAt': (utcnow() + INVITATION_TIMEOUT).isoformat()}, ensure_ascii=False))


def assisted_recovery(login, reason):
    raw, token_hash = generate_token()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE login_normalized=%s AND status='active' FOR UPDATE", (normalize_login(login),))
        row = cur.fetchone()
        if not row:
            raise SystemExit('Conta ativa não encontrada.')
        user_id = row[0]
        cur.execute("UPDATE recovery_tokens SET revoked_at=now() WHERE user_id=%s AND used_at IS NULL AND revoked_at IS NULL", (user_id,))
        cur.execute("INSERT INTO recovery_tokens(id,user_id,token_hash,delivery_kind,reason,expires_at) VALUES(%s,%s,%s,'assisted',%s,%s)", (uuid.uuid4(), user_id, token_hash, reason, utcnow() + RECOVERY_TIMEOUT))
        cur.execute("INSERT INTO audit_events(id,subject_user_id,action,result,correlation_id,metadata) VALUES(%s,%s,'account.assisted_recovery','success',%s,%s)", (uuid.uuid4(), user_id, str(uuid.uuid4()), json.dumps({'reason': reason})))
    print(json.dumps({'userId': str(user_id), 'recoveryToken': raw, 'expiresAt': (utcnow() + RECOVERY_TIMEOUT).isoformat()}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='Administração local de contas, sem senha padrão.')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('invite')
    create.add_argument('--login', required=True)
    create.add_argument('--name', required=True)
    create.add_argument('--role', action='append', choices=ROLES, required=True)
    create.add_argument('--condominium', default='sqa')
    recovery = commands.add_parser('recover')
    recovery.add_argument('--login', required=True)
    recovery.add_argument('--reason', required=True)
    args = parser.parse_args()
    initialize()
    if args.command == 'invite':
        invite(args.login, args.name, tuple(dict.fromkeys(args.role)), args.condominium)
    else:
        assisted_recovery(args.login, args.reason)


if __name__ == '__main__':
    main()
