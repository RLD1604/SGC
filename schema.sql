CREATE TABLE IF NOT EXISTS schema_versions (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS workspace_state (id integer PRIMARY KEY CHECK (id=1), revision bigint NOT NULL DEFAULT 0);
INSERT INTO workspace_state(id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS records (id text PRIMARY KEY, document jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS editions (id text PRIMARY KEY, document jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS publications (id text PRIMARY KEY, document jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS media (id text PRIMARY KEY, mime text NOT NULL, width integer NOT NULL, height integer NOT NULL, content bytea NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS change_history (revision bigint PRIMARY KEY, changes jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS browser_imports (id text PRIMARY KEY, revision bigint NOT NULL, imported_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS records_status ON records ((document->>'status'));
CREATE INDEX IF NOT EXISTS records_date ON records ((document->>'date'));
CREATE INDEX IF NOT EXISTS editions_period ON editions ((document->>'period'));
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS ai_requests (id uuid PRIMARY KEY, model text NOT NULL, characters integer NOT NULL, status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ai_requests_created ON ai_requests(created_at);
INSERT INTO schema_versions(version) VALUES (2) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS operation_requests (id text PRIMARY KEY, payload_hash text NOT NULL, response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_versions(version) VALUES (3) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS migration_reports (version integer NOT NULL, collection text NOT NULL, document_id text NOT NULL, message text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(version,collection,document_id,message));

-- Schema 5: isolated identities, document ownership, immutable revisions and audit.
-- Existing JSON documents are preserved.  Their authors remain NULL on purpose:
-- migration must never invent authorship or an authenticated approval.
CREATE TABLE IF NOT EXISTS condominiums (
  id text PRIMARY KEY,
  name text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO condominiums(id,name) VALUES ('sqa','Super Quadra Atlantica') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY,
  display_name text NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 160),
  login_display text NOT NULL,
  login_normalized text NOT NULL UNIQUE,
  email text,
  password_hash text,
  status text NOT NULL CHECK (status IN ('invited','active','disabled')),
  auth_generation bigint NOT NULL DEFAULT 1,
  activated_at timestamptz,
  disabled_at timestamptz,
  password_changed_at timestamptz,
  disabled_by uuid REFERENCES users(id),
  disable_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  condominium_id text NOT NULL REFERENCES condominiums(id),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  starts_at timestamptz,
  ends_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id,condominium_id),
  CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS role_grants (
  id uuid PRIMARY KEY,
  membership_id uuid REFERENCES memberships(id),
  user_id uuid NOT NULL REFERENCES users(id),
  condominium_id text NOT NULL REFERENCES condominiums(id),
  role text NOT NULL CHECK (role IN ('operador','administrador','encarregado','supervisor','editor','gestor','sindico','administrador_tecnico','responsavel_acessos')),
  starts_at timestamptz NOT NULL DEFAULT now(),
  ends_at timestamptz,
  revoked_at timestamptz,
  granted_by uuid REFERENCES users(id),
  basis text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS role_grants_membership_active ON role_grants(user_id,condominium_id,role,starts_at,ends_at,revoked_at);

CREATE TABLE IF NOT EXISTS sessions (
  id uuid PRIMARY KEY,
  token_hash bytea NOT NULL UNIQUE,
  user_id uuid NOT NULL REFERENCES users(id),
  auth_generation bigint NOT NULL,
  csrf_hash bytea NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  idle_expires_at timestamptz NOT NULL,
  absolute_expires_at timestamptz NOT NULL,
  authenticated_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  revoke_reason text,
  user_agent text,
  origin_fingerprint text
);
CREATE INDEX IF NOT EXISTS sessions_user_active ON sessions(user_id,revoked_at,absolute_expires_at);

CREATE TABLE IF NOT EXISTS invitations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  token_hash bytea NOT NULL UNIQUE,
  issued_by uuid REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recovery_tokens (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  token_hash bytea NOT NULL UNIQUE,
  issued_by uuid REFERENCES users(id),
  delivery_kind text NOT NULL CHECK (delivery_kind IN ('email','assisted')),
  reason text,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (delivery_kind <> 'assisted' OR length(trim(reason)) > 0)
);

CREATE TABLE IF NOT EXISTS auth_throttles (
  throttle_key bytea PRIMARY KEY,
  window_started_at timestamptz NOT NULL,
  failures integer NOT NULL DEFAULT 0,
  blocked_until timestamptz
);

CREATE TABLE IF NOT EXISTS record_metadata (
  record_id text PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
  condominium_id text NOT NULL REFERENCES condominiums(id),
  author_user_id uuid REFERENCES users(id),
  current_revision integer NOT NULL DEFAULT 1 CHECK (current_revision > 0),
  legacy_import boolean NOT NULL DEFAULT false,
  archived_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS edition_metadata (
  edition_id text PRIMARY KEY REFERENCES editions(id) ON DELETE CASCADE,
  condominium_id text NOT NULL REFERENCES condominiums(id),
  author_user_id uuid REFERENCES users(id),
  current_revision integer NOT NULL DEFAULT 1 CHECK (current_revision > 0),
  workflow_state text NOT NULL DEFAULT 'draft' CHECK (workflow_state IN ('draft','pending_approval','returned','approved','published')),
  legacy_import boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO record_metadata(record_id,condominium_id,author_user_id,current_revision,legacy_import)
SELECT id,'sqa',NULL,GREATEST(COALESCE((document->>'revision')::integer,1),1),true FROM records
ON CONFLICT DO NOTHING;
INSERT INTO edition_metadata(edition_id,condominium_id,author_user_id,current_revision,workflow_state,legacy_import)
SELECT id,'sqa',NULL,GREATEST(COALESCE((document->>'version')::integer,1),1),'draft',true FROM editions
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS document_assignments (
  id uuid PRIMARY KEY,
  condominium_id text NOT NULL REFERENCES condominiums(id),
  document_type text NOT NULL CHECK (document_type IN ('record','edition')),
  document_id text NOT NULL,
  membership_id uuid REFERENCES memberships(id),
  user_id uuid NOT NULL REFERENCES users(id),
  assigned_by uuid NOT NULL REFERENCES users(id),
  reason text NOT NULL,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  revoked_at timestamptz
);
CREATE INDEX IF NOT EXISTS document_assignments_lookup ON document_assignments(condominium_id,document_type,document_id,user_id,revoked_at);

CREATE TABLE IF NOT EXISTS record_revisions (
  id uuid PRIMARY KEY,
  record_id text NOT NULL REFERENCES records(id),
  revision_number integer NOT NULL CHECK (revision_number > 0),
  author_user_id uuid REFERENCES users(id),
  snapshot jsonb NOT NULL,
  snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[a-f0-9]{64}$'),
  workflow_state text NOT NULL CHECK (workflow_state IN ('draft','review','fix','ready')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(record_id,revision_number)
);

CREATE TABLE IF NOT EXISTS edition_revisions (
  id uuid PRIMARY KEY,
  edition_id text NOT NULL REFERENCES editions(id),
  revision_number integer NOT NULL CHECK (revision_number > 0),
  author_user_id uuid REFERENCES users(id),
  snapshot jsonb NOT NULL,
  snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[a-f0-9]{64}$'),
  renderer_version text NOT NULL,
  artifact_html bytea NOT NULL,
  artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[a-f0-9]{64}$'),
  state text NOT NULL CHECK (state IN ('pending_approval','returned','approved','published')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(edition_id,revision_number)
);

CREATE TABLE IF NOT EXISTS approval_decisions (
  id uuid PRIMARY KEY,
  edition_revision_id uuid NOT NULL REFERENCES edition_revisions(id),
  approver_user_id uuid NOT NULL REFERENCES users(id),
  role_grant_id uuid NOT NULL REFERENCES role_grants(id),
  decision text NOT NULL CHECK (decision IN ('approved','returned')),
  reason text,
  snapshot_hash text NOT NULL,
  artifact_hash text NOT NULL,
  decided_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(edition_revision_id,approver_user_id)
);

CREATE TABLE IF NOT EXISTS official_publications (
  id uuid PRIMARY KEY,
  condominium_id text NOT NULL REFERENCES condominiums(id),
  edition_revision_id uuid NOT NULL UNIQUE REFERENCES edition_revisions(id),
  approval_id uuid NOT NULL REFERENCES approval_decisions(id),
  created_by uuid NOT NULL REFERENCES users(id),
  artifact_html bytea NOT NULL,
  artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[a-f0-9]{64}$'),
  idempotency_key text NOT NULL,
  corrects_publication_id uuid REFERENCES official_publications(id),
  published_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(condominium_id,idempotency_key)
);

CREATE TABLE IF NOT EXISTS media_references (
  media_id text NOT NULL REFERENCES media(id) ON DELETE CASCADE,
  condominium_id text NOT NULL REFERENCES condominiums(id),
  document_type text NOT NULL CHECK (document_type IN ('record','edition','edition_revision','official_publication')),
  document_id text NOT NULL,
  PRIMARY KEY(media_id,document_type,document_id)
);
CREATE INDEX IF NOT EXISTS media_references_document ON media_references(document_type,document_id,media_id);

CREATE TABLE IF NOT EXISTS audit_events (
  id uuid PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  condominium_id text REFERENCES condominiums(id),
  actor_user_id uuid REFERENCES users(id),
  subject_user_id uuid REFERENCES users(id),
  session_id uuid,
  action text NOT NULL,
  entity_type text,
  entity_id text,
  revision_id text,
  result text NOT NULL CHECK (result IN ('success','denied','error')),
  correlation_id text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_events_time ON audit_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_actor ON audit_events(actor_user_id,occurred_at DESC);

CREATE OR REPLACE FUNCTION reject_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable operational record';
END $$;
DROP TRIGGER IF EXISTS record_revisions_immutable ON record_revisions;
CREATE TRIGGER record_revisions_immutable BEFORE UPDATE OR DELETE ON record_revisions FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
DROP TRIGGER IF EXISTS approval_decisions_immutable ON approval_decisions;
CREATE TRIGGER approval_decisions_immutable BEFORE UPDATE OR DELETE ON approval_decisions FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
DROP TRIGGER IF EXISTS official_publications_immutable ON official_publications;
CREATE TRIGGER official_publications_immutable BEFORE UPDATE OR DELETE ON official_publications FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO schema_versions(version) VALUES (5) ON CONFLICT DO NOTHING;

-- Schema 6: the operational audit trail is append-only at the database layer.
-- Application sessions may insert events, but existing evidence cannot be
-- rewritten or removed through the same database credential.
DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events;
CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO schema_versions(version) VALUES (6) ON CONFLICT DO NOTHING;

-- Schema 7: two public profiles. Old grant IDs remain for historical approvals.
ALTER TABLE role_grants DROP CONSTRAINT IF EXISTS role_grants_role_check;
ALTER TABLE role_grants ADD CONSTRAINT role_grants_role_check CHECK
  (role IN ('operador','administrador','encarregado','supervisor','editor','gestor','sindico','administrador_tecnico','responsavel_acessos'));
DO $$
DECLARE old_grant record; new_id uuid; new_role text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version=7) THEN
    FOR old_grant IN
      SELECT g.*,u.login_normalized FROM role_grants g JOIN users u ON u.id=g.user_id
      WHERE g.role NOT IN ('operador','administrador')
        AND (g.revoked_at IS NULL OR g.revoked_at>now())
        AND (g.ends_at IS NULL OR g.ends_at>now())
      FOR UPDATE OF g
    LOOP
      new_id := gen_random_uuid();
      new_role := CASE
        WHEN old_grant.condominium_id='sqa' AND old_grant.login_normalized='testador.sqa.03' THEN 'administrador'
        WHEN old_grant.condominium_id='sqa' AND old_grant.login_normalized IN ('testador.sqa.01','testador.sqa.02') THEN 'operador'
        WHEN old_grant.role IN ('encarregado','supervisor','editor') THEN 'operador'
        ELSE 'administrador' END;
      INSERT INTO role_grants(id,membership_id,user_id,condominium_id,role,starts_at,ends_at,revoked_at,granted_by,basis)
        VALUES(new_id,old_grant.membership_id,old_grant.user_id,old_grant.condominium_id,new_role,
          old_grant.starts_at,old_grant.ends_at,old_grant.revoked_at,old_grant.granted_by,'Migração auditada para dois perfis; origem '||old_grant.id);
      INSERT INTO audit_events(id,condominium_id,subject_user_id,action,result,correlation_id,metadata)
        VALUES(gen_random_uuid(),old_grant.condominium_id,old_grant.user_id,'roles.migrate.two_profiles','success',new_id::text,
          jsonb_build_object('oldGrantId',old_grant.id,'newGrantId',new_id,'oldRole',old_grant.role,'newRole',new_role));
      UPDATE role_grants SET revoked_at=now() WHERE id=old_grant.id;
    END LOOP;
    INSERT INTO schema_versions(version) VALUES(7);
  END IF;
END $$;
