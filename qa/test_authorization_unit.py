import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from authorization import (  # noqa: E402
    ACCOUNTS_MANAGE,
    AI_REVISE,
    EDITION_APPROVE,
    EDITION_EDIT,
    ITEM_CREATE,
    ITEM_EDIT,
    ITEM_READ,
    ITEM_REVIEW,
    ITEM_SUBMIT,
    PUBLICATION_EXPORT,
    Grant,
    Principal,
    Resource,
    active_roles,
    authorize,
    authorize_decision,
    grant_is_active,
    load_active_assignments,
    load_active_grants,
    permissions_for,
    permissions_for_roles,
    resource_from_mapping,
)


NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)


def principal(role, *, member="m1", condo="c1", **grant_values):
    grant = Grant(
        role=role,
        condominium_id=condo,
        membership_id=member,
        grant_id=f"g-{role}",
        valid_from=NOW - timedelta(days=1),
        **grant_values,
    )
    return Principal(member, condo, (grant,))


def resource(kind="item", status="draft", *, condo="c1", author="m1", assigned=(), immutable=False):
    return Resource(kind, condo, status, author, frozenset(assigned), immutable)


class RoleMatrixTests(unittest.TestCase):
    def test_staff_roles_create_edit_and_submit_own_item(self):
        for role in ("encarregado", "supervisor"):
            actor = principal(role)
            self.assertTrue(authorize(actor, ITEM_CREATE, now=NOW))
            self.assertTrue(authorize(actor, ITEM_READ, resource(), now=NOW))
            self.assertTrue(authorize(actor, ITEM_EDIT, resource(), now=NOW))
            self.assertTrue(authorize(actor, ITEM_SUBMIT, resource(), now=NOW))

    def test_supervisor_title_does_not_grant_review_or_approval(self):
        actor = principal("supervisor")
        self.assertEqual(authorize_decision(actor, ITEM_REVIEW, resource(status="review"), now=NOW).reason, "permission_denied")
        pending = resource("edition_revision", "pending_approval")
        self.assertFalse(authorize(actor, EDITION_APPROVE, pending, now=NOW))

    def test_optional_editor_composes_but_does_not_approve_or_export(self):
        actor = principal("editor")
        self.assertTrue(authorize(actor, EDITION_EDIT, resource("edition", "preparation"), now=NOW))
        self.assertFalse(authorize(actor, ITEM_REVIEW, resource(status="review"), now=NOW))
        self.assertFalse(authorize(actor, EDITION_APPROVE, resource("edition_revision", "pending_approval"), now=NOW))
        self.assertFalse(authorize(actor, PUBLICATION_EXPORT, resource("edition_revision", "approved"), now=NOW))

    def test_technical_admin_has_no_editorial_permission_by_default(self):
        actor = principal("administrador_tecnico")
        self.assertEqual(permissions_for(actor, NOW), frozenset({ACCOUNTS_MANAGE}))
        self.assertTrue(authorize(actor, ACCOUNTS_MANAGE, now=NOW))
        self.assertFalse(authorize(actor, ITEM_READ, resource(), now=NOW))
        self.assertFalse(authorize(actor, EDITION_APPROVE, resource("edition_revision", "pending_approval"), now=NOW))

    def test_manager_and_syndic_can_review_approve_and_export(self):
        for role in ("gestor", "sindico"):
            actor = principal(role)
            self.assertTrue(authorize(actor, ITEM_REVIEW, resource(status="review", author="m2"), now=NOW))
            approved = resource("edition_revision", "approved", author="m2")
            approval = authorize_decision(actor, EDITION_APPROVE, resource("edition_revision", "pending_approval"), now=NOW)
            self.assertTrue(approval)
            self.assertEqual(approval.grant_id, f"g-{role}")
            self.assertTrue(authorize(actor, PUBLICATION_EXPORT, approved, now=NOW))


class GrantTests(unittest.TestCase):
    def test_public_bool_contract_accepts_server_mapping(self):
        actor = principal("gestor")
        mapped = {
            "membership_id": actor.membership_id,
            "condominium_id": actor.condominium_id,
            "grants": actor.grants,
            # A top-level role is untrusted and irrelevant.
            "role": "administrador_tecnico",
        }
        self.assertIs(authorize(mapped, ITEM_CREATE, now=NOW), True)
        self.assertEqual(active_roles(mapped, NOW), frozenset({"gestor"}))

    def test_permissions_for_roles_denies_unknown_role_by_default(self):
        permissions = permissions_for_roles(("editor", "papel_inventado"))
        self.assertIn(EDITION_EDIT, permissions)
        self.assertNotIn(EDITION_APPROVE, permissions)

    def test_validity_is_start_inclusive_end_exclusive(self):
        grant = Grant("gestor", "c1", "m1", valid_from=NOW, valid_until=NOW + timedelta(hours=1))
        self.assertTrue(grant_is_active(grant, NOW))
        self.assertFalse(grant_is_active(grant, NOW + timedelta(hours=1)))

    def test_expired_or_revoked_manager_cannot_approve(self):
        pending = resource("edition_revision", "pending_approval")
        expired = principal("gestor", valid_until=NOW)
        revoked = principal("sindico", revoked_at=NOW - timedelta(minutes=1))
        self.assertFalse(authorize(expired, EDITION_APPROVE, pending, now=NOW))
        self.assertFalse(authorize(revoked, EDITION_APPROVE, pending, now=NOW))

    def test_inactive_membership_denies_everything(self):
        base = principal("sindico")
        actor = Principal(base.membership_id, base.condominium_id, base.grants, active=False)
        decision = authorize_decision(actor, EDITION_APPROVE, resource("edition_revision", "pending_approval"), now=NOW)
        self.assertEqual(decision.reason, "inactive_principal")

    def test_grant_from_another_membership_is_ignored(self):
        alien = Grant("sindico", "c1", "other", valid_from=NOW - timedelta(days=1))
        actor = Principal("m1", "c1", (alien,))
        self.assertFalse(authorize(actor, EDITION_APPROVE, resource("edition_revision", "pending_approval"), now=NOW))

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            Grant("gestor", "c1", "m1", valid_from=datetime(2026, 1, 1))


class ScopeAndStateTests(unittest.TestCase):
    def test_cross_condominium_is_denied_and_concealed(self):
        decision = authorize_decision(principal("sindico"), ITEM_READ, resource(condo="c2"), now=NOW)
        self.assertFalse(decision)
        self.assertEqual(decision.reason, "cross_condominium")
        self.assertTrue(decision.conceal_resource)

    def test_staff_cannot_read_another_members_draft(self):
        actor = principal("supervisor")
        decision = authorize_decision(actor, ITEM_READ, resource(author="m2"), now=NOW)
        self.assertEqual(decision.reason, "scope_denied")

    def test_assignment_grants_read_edit_and_submit(self):
        actor = principal("encarregado")
        assigned = resource(author="m2", assigned={"m1"})
        self.assertTrue(authorize(actor, ITEM_READ, assigned, now=NOW))
        self.assertTrue(authorize(actor, ITEM_EDIT, assigned, now=NOW))
        self.assertTrue(authorize(actor, ITEM_SUBMIT, assigned, now=NOW))

    def test_manager_reads_submitted_but_not_unassigned_draft(self):
        actor = principal("gestor")
        self.assertTrue(authorize(actor, ITEM_READ, resource(status="review", author="m2"), now=NOW))
        self.assertFalse(authorize(actor, ITEM_READ, resource(status="draft", author="m2"), now=NOW))

    def test_editor_reads_only_conferred_sources(self):
        actor = principal("editor")
        self.assertTrue(authorize(actor, ITEM_READ, resource(status="ready", author="m2"), now=NOW))
        self.assertFalse(authorize(actor, ITEM_READ, resource(status="review", author="m2"), now=NOW))

    def test_item_cannot_be_edited_after_submission(self):
        decision = authorize_decision(principal("sindico"), ITEM_EDIT, resource(status="review"), now=NOW)
        self.assertEqual(decision.reason, "state_denied")

    def test_frozen_revision_is_immutable(self):
        frozen = resource(status="draft", immutable=True)
        self.assertEqual(authorize_decision(principal("gestor"), ITEM_EDIT, frozen, now=NOW).reason, "immutable_revision")

    def test_approval_requires_pending_revision(self):
        decision = authorize_decision(principal("sindico"), EDITION_APPROVE, resource("edition_revision", "approved"), now=NOW)
        self.assertEqual(decision.reason, "state_denied")

    def test_official_export_requires_approved_revision(self):
        actor = principal("gestor")
        self.assertFalse(authorize(actor, PUBLICATION_EXPORT, resource("edition_revision", "pending_approval"), now=NOW))
        self.assertTrue(authorize(actor, PUBLICATION_EXPORT, resource("edition_revision", "approved"), now=NOW))

    def test_ai_revision_follows_document_edit_scope(self):
        staff = principal("encarregado")
        self.assertTrue(authorize(staff, AI_REVISE, resource(), now=NOW))
        self.assertFalse(authorize(staff, AI_REVISE, resource(author="m2"), now=NOW))
        self.assertFalse(authorize(staff, AI_REVISE, resource("edition", "preparation"), now=NOW))
        self.assertTrue(authorize(principal("editor"), AI_REVISE, resource("edition", "preparation"), now=NOW))

    def test_unknown_permission_is_denied(self):
        self.assertEqual(authorize_decision(principal("sindico"), "root.everything", now=NOW).reason, "unknown_permission")


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class IntegrationHelperTests(unittest.TestCase):
    def test_load_grants_uses_parameterized_query(self):
        rows = [("gestor", "c1", "m1", "g1", NOW - timedelta(days=1), None, None)]
        cursor = FakeCursor(rows)
        grants = load_active_grants(cursor, "m1", "c1", at=NOW)
        self.assertEqual(grants[0].role, "gestor")
        self.assertEqual(cursor.params, ("m1", "c1", NOW, NOW, NOW))
        self.assertIn("rg.membership_id = %s", cursor.sql)

    def test_load_assignments_returns_frozen_ids(self):
        cursor = FakeCursor([("m1",), ("m2",)])
        result = load_active_assignments(cursor, "item", "r1", at=NOW)
        self.assertEqual(result, frozenset({"m1", "m2"}))
        self.assertEqual(cursor.params, ("item", "r1", NOW, NOW, NOW))

    def test_mapping_projection_does_not_accept_roles(self):
        projected = resource_from_mapping(
            {
                "condominium_id": "c1",
                "status": "draft",
                "author_membership_id": "m2",
                "role": "sindico",
            },
            kind="item",
            assigned_membership_ids=("m1",),
        )
        self.assertEqual(projected.author_membership_id, "m2")
        self.assertNotIn("role", projected.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
