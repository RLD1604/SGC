"""Pure authorization rules for the authenticated condominium beta.

This module deliberately has no Flask or psycopg2 dependency.  HTTP handlers can
build a :class:`Principal` and a :class:`Resource`, call :func:`authorize` for a
boolean gate, or call :func:`authorize_decision` when they must translate a
stable denial reason to an HTTP response and an audit event.

Roles supplied by a browser must never be used to construct a Principal.  Grants
are loaded from the database with :func:`load_active_grants` (or equivalent
repository code) for every request that changes protected state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Union


ITEM_CREATE = "item.create"
ITEM_READ = "item.read"
ITEM_EDIT = "item.edit"
ITEM_SUBMIT = "item.submit"
ITEM_REVIEW = "item.review"
EDITION_READ = "edition.read"
EDITION_EDIT = "edition.edit"
EDITION_SUBMIT = "edition.submit"
EDITION_APPROVE = "edition.approve"
PUBLICATION_EXPORT = "publication.export"
PUBLICATION_READ = "publication.read"
AI_REVISE = "ai.revise"
ACCOUNTS_MANAGE = "accounts.manage"

ALL_PERMISSIONS = frozenset(
    {
        ITEM_CREATE,
        ITEM_READ,
        ITEM_EDIT,
        ITEM_SUBMIT,
        ITEM_REVIEW,
        EDITION_READ,
        EDITION_EDIT,
        EDITION_SUBMIT,
        EDITION_APPROVE,
        PUBLICATION_EXPORT,
        PUBLICATION_READ,
        AI_REVISE,
        ACCOUNTS_MANAGE,
    }
)

# The latest documented matrix is authoritative.  In particular, supervisor is
# not a reviewer merely because of the job title, optional editor does not
# approve/export, and technical administrator receives no editorial access.
ROLE_PERMISSIONS = {
    "encarregado": frozenset({ITEM_CREATE, ITEM_READ, ITEM_EDIT, ITEM_SUBMIT, PUBLICATION_READ, AI_REVISE}),
    "supervisor": frozenset({ITEM_CREATE, ITEM_READ, ITEM_EDIT, ITEM_SUBMIT, PUBLICATION_READ, AI_REVISE}),
    "editor": frozenset({ITEM_READ, EDITION_READ, EDITION_EDIT, EDITION_SUBMIT, PUBLICATION_READ, AI_REVISE}),
    "gestor": frozenset(
        {
            ITEM_CREATE,
            ITEM_READ,
            ITEM_EDIT,
            ITEM_SUBMIT,
            ITEM_REVIEW,
            EDITION_READ,
            EDITION_EDIT,
            EDITION_SUBMIT,
            EDITION_APPROVE,
            PUBLICATION_EXPORT,
            PUBLICATION_READ,
            AI_REVISE,
        }
    ),
    "sindico": frozenset(
        {
            ITEM_CREATE,
            ITEM_READ,
            ITEM_EDIT,
            ITEM_SUBMIT,
            ITEM_REVIEW,
            EDITION_READ,
            EDITION_EDIT,
            EDITION_SUBMIT,
            EDITION_APPROVE,
            PUBLICATION_EXPORT,
            PUBLICATION_READ,
            AI_REVISE,
        }
    ),
    "administrador_tecnico": frozenset({ACCOUNTS_MANAGE}),
    "responsavel_acessos": frozenset({ACCOUNTS_MANAGE}),
}

# Public profiles; legacy roles remain readable for historical approvals.
PUBLIC_ROLES = ("operador", "administrador")
ROLE_PERMISSIONS["operador"] = ROLE_PERMISSIONS["encarregado"] | ROLE_PERMISSIONS["editor"]
ROLE_PERMISSIONS["administrador"] = ALL_PERMISSIONS

ITEM_EDITABLE_STATES = frozenset({"draft", "fix"})
ITEM_SUBMITTED_STATES = frozenset({"review", "ready"})
EDITION_EDITABLE_STATES = frozenset({"draft", "preparation", "returned"})
EDITION_PENDING_STATES = frozenset({"pending_approval"})
EDITION_APPROVED_STATES = frozenset({"approved", "published"})


def _utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, rejecting ambiguous naive values."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("authorization timestamps must include a timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Grant:
    """A server-issued role grant; ``valid_until`` is an exclusive boundary."""

    role: str
    condominium_id: str
    membership_id: str
    grant_id: Optional[str] = None
    valid_from: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    valid_until: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.role not in ROLE_PERMISSIONS:
            raise ValueError(f"unknown role: {self.role}")
        _utc(self.valid_from)
        if self.valid_until is not None:
            _utc(self.valid_until)
            if _utc(self.valid_until) <= _utc(self.valid_from):
                raise ValueError("valid_until must be after valid_from")
        if self.revoked_at is not None:
            _utc(self.revoked_at)


@dataclass(frozen=True)
class Principal:
    membership_id: str
    condominium_id: str
    grants: tuple[Grant, ...] = ()
    active: bool = True


@dataclass(frozen=True)
class Resource:
    """The authorization-relevant projection of a domain document.

    ``kind`` is one of ``item``, ``edition``, ``edition_revision`` or
    ``publication``.  Immutable revision contents are never editable.
    """

    kind: str
    condominium_id: str
    status: str
    author_membership_id: Optional[str] = None
    assigned_membership_ids: frozenset[str] = frozenset()
    immutable: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"item", "edition", "edition_revision", "publication"}:
            raise ValueError(f"unknown resource kind: {self.kind}")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    permission: str
    acting_role: Optional[str] = None
    grant_id: Optional[str] = None
    conceal_resource: bool = False

    def __bool__(self) -> bool:
        return self.allowed


def grant_is_active(grant: Grant, at: datetime) -> bool:
    instant = _utc(at)
    if grant.revoked_at is not None and _utc(grant.revoked_at) <= instant:
        return False
    if instant < _utc(grant.valid_from):
        return False
    return grant.valid_until is None or instant < _utc(grant.valid_until)


def principal_from_mapping(values: Mapping[str, Any]) -> Principal:
    """Build a Principal from server-owned values.

    The mapping contains ``membership_id``, ``condominium_id``, optional
    boolean ``active`` and iterable ``grants``.  Each grant is either a Grant
    or a mapping accepted by its constructor.  Unknown top-level values,
    including a browser-supplied ``role``, do not grant anything.
    """
    grants = tuple(
        item if isinstance(item, Grant) else Grant(**item)
        for item in values.get("grants", ())
    )
    return Principal(
        membership_id=str(values["membership_id"]),
        condominium_id=str(values["condominium_id"]),
        grants=grants,
        active=bool(values.get("active", True)),
    )


def _principal(value: Union[Principal, Mapping[str, Any]]) -> Principal:
    if isinstance(value, Principal):
        return value
    if isinstance(value, Mapping):
        return principal_from_mapping(value)
    raise TypeError("principal must be Principal or a mapping")


def active_grants(
    principal: Union[Principal, Mapping[str, Any]], at: datetime
) -> tuple[Grant, ...]:
    """Return only grants belonging to this active membership and condominium."""
    principal = _principal(principal)
    if not principal.active:
        return ()
    return tuple(
        grant
        for grant in principal.grants
        if grant.membership_id == principal.membership_id
        and grant.condominium_id == principal.condominium_id
        and grant_is_active(grant, at)
    )


def active_roles(
    principal: Union[Principal, Mapping[str, Any]],
    now: Optional[datetime] = None,
) -> frozenset[str]:
    instant = _utc(now or datetime.now(timezone.utc))
    return frozenset(grant.role for grant in active_grants(principal, instant))


def permissions_for_roles(roles: Iterable[str]) -> frozenset[str]:
    """Return the permission union for known roles; unknown roles add nothing."""
    permissions: set[str] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, ()))
    return frozenset(permissions)


def permissions_for(
    principal: Union[Principal, Mapping[str, Any]], at: datetime
) -> frozenset[str]:
    permissions: set[str] = set()
    for grant in active_grants(principal, at):
        permissions.update(ROLE_PERMISSIONS[grant.role])
    return frozenset(permissions)


def _candidate_grants(principal: Principal, permission: str, at: datetime) -> tuple[Grant, ...]:
    return tuple(
        grant
        for grant in active_grants(principal, at)
        if permission in ROLE_PERMISSIONS[grant.role]
    )


def _allow(permission: str, grant: Grant) -> Decision:
    return Decision(True, "allowed", permission, grant.role, grant.grant_id)


def _deny(permission: str, reason: str, *, conceal: bool = False) -> Decision:
    return Decision(False, reason, permission, conceal_resource=conceal)


def _owns_or_is_assigned(principal: Principal, resource: Resource) -> bool:
    return (
        resource.author_membership_id == principal.membership_id
        or principal.membership_id in resource.assigned_membership_ids
    )


def authorize_decision(
    principal: Union[Principal, Mapping[str, Any]],
    permission: str,
    resource: Optional[Union[Resource, Mapping[str, Any]]] = None,
    *,
    now: Optional[datetime] = None,
) -> Decision:
    """Make a deny-by-default authorization decision.

    Cross-condominium resources are concealed so an API adapter can return 404.
    State and scope denials are 403-class decisions; stale revisions remain a
    separate domain-level 409 check.
    """
    principal = _principal(principal)
    if resource is not None and not isinstance(resource, Resource):
        resource = resource_from_mapping(resource, kind=str(resource["kind"]))
    if permission not in ALL_PERMISSIONS:
        return _deny(permission, "unknown_permission")
    instant = _utc(now or datetime.now(timezone.utc))
    if not principal.active:
        return _deny(permission, "inactive_principal")
    if resource is not None and resource.condominium_id != principal.condominium_id:
        return _deny(permission, "cross_condominium", conceal=True)

    candidates = _candidate_grants(principal, permission, instant)
    if not candidates:
        return _deny(permission, "permission_denied")

    # Creation and account management have no document scope.  Their grant is
    # nevertheless tied to the principal's current condominium above.
    if permission in {ITEM_CREATE, ACCOUNTS_MANAGE}:
        return _allow(permission, candidates[0])

    if resource is None:
        return _deny(permission, "resource_required")

    if permission == ITEM_READ:
        if resource.kind != "item":
            return _deny(permission, "resource_kind_denied")
        if _owns_or_is_assigned(principal, resource):
            return _allow(permission, candidates[0])
        # Gestor/sindico see submitted items in their condominium.  Optional
        # editors see only conferred sources needed to compose an edition.
        for grant in candidates:
            if grant.role in {"gestor", "sindico", "administrador"} and resource.status in ITEM_SUBMITTED_STATES:
                return _allow(permission, grant)
            if grant.role in {"editor", "operador"} and resource.status == "ready":
                return _allow(permission, grant)
        return _deny(permission, "scope_denied")

    if permission == EDITION_READ:
        if resource.kind not in {"edition", "edition_revision"}:
            return _deny(permission, "resource_kind_denied")
        return _allow(permission, candidates[0])

    if permission == PUBLICATION_READ:
        if resource.kind != "publication":
            return _deny(permission, "resource_kind_denied")
        return _allow(permission, candidates[0])

    if permission in {ITEM_EDIT, ITEM_SUBMIT}:
        if resource.kind != "item":
            return _deny(permission, "resource_kind_denied")
        if resource.immutable:
            return _deny(permission, "immutable_revision")
        if resource.status not in ITEM_EDITABLE_STATES:
            return _deny(permission, "state_denied")
        if not _owns_or_is_assigned(principal, resource):
            return _deny(permission, "scope_denied")
        return _allow(permission, candidates[0])

    if permission == ITEM_REVIEW:
        if resource.kind != "item":
            return _deny(permission, "resource_kind_denied")
        if resource.status != "review":
            return _deny(permission, "state_denied")
        return _allow(permission, candidates[0])

    if permission in {EDITION_EDIT, EDITION_SUBMIT}:
        if resource.kind != "edition":
            return _deny(permission, "resource_kind_denied")
        if resource.immutable:
            return _deny(permission, "immutable_revision")
        if resource.status not in EDITION_EDITABLE_STATES:
            return _deny(permission, "state_denied")
        return _allow(permission, candidates[0])

    if permission == EDITION_APPROVE:
        if resource.kind != "edition_revision":
            return _deny(permission, "resource_kind_denied")
        if resource.status not in EDITION_PENDING_STATES:
            return _deny(permission, "state_denied")
        # Only an active gestor/sindico grant can reach this branch because no
        # other role contains edition.approve.  Preserve its id in the decision
        # so an approval row can reference the exact mandate/delegation.
        return _allow(permission, candidates[0])

    if permission == PUBLICATION_EXPORT:
        if resource.kind not in {"edition_revision", "publication"}:
            return _deny(permission, "resource_kind_denied")
        if resource.status not in EDITION_APPROVED_STATES:
            return _deny(permission, "state_denied")
        return _allow(permission, candidates[0])

    if permission == AI_REVISE:
        if resource.kind == "item":
            if resource.status not in ITEM_EDITABLE_STATES:
                return _deny(permission, "state_denied")
            if not _owns_or_is_assigned(principal, resource):
                return _deny(permission, "scope_denied")
        elif resource.kind == "edition":
            if resource.status not in EDITION_EDITABLE_STATES:
                return _deny(permission, "state_denied")
            # Encarregado/supervisor can possess ai.revise but not revise an
            # edition unless an accumulated editor/manager grant also permits it.
            editorial = tuple(
                grant
                for grant in active_grants(principal, instant)
                if EDITION_EDIT in ROLE_PERMISSIONS[grant.role]
            )
            if not editorial:
                return _deny(permission, "permission_denied")
            return _allow(permission, editorial[0])
        else:
            return _deny(permission, "resource_kind_denied")
        return _allow(permission, candidates[0])

    return _deny(permission, "permission_denied")


def authorize(
    principal: Union[Principal, Mapping[str, Any]],
    permission: str,
    resource: Optional[Union[Resource, Mapping[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Return whether ``permission`` is allowed for the current request.

    ``principal`` accepts the dataclass or the server-owned mapping documented
    by :func:`principal_from_mapping`. ``resource`` accepts the dataclass or a
    mapping with ``kind``, ``condominium_id`` and ``status``; optional fields
    are ``author_membership_id``, ``assigned_membership_ids`` and ``immutable``.
    Use :func:`authorize_decision` when the denial reason or exact grant id is
    also needed for HTTP handling, auditing or an approval record.
    """
    return authorize_decision(principal, permission, resource, now=now).allowed


# SQL helpers intentionally select only server-owned grants.  They assume the
# schema named in the Stage 6 design; callers can keep repository concerns out
# of the pure decision functions above.
ACTIVE_GRANTS_SQL = """
SELECT rg.role, m.condominium_id::text, rg.membership_id::text, rg.id::text,
       rg.starts_at, rg.ends_at, rg.revoked_at
  FROM role_grants AS rg
  JOIN memberships AS m ON m.id = rg.membership_id
 WHERE rg.membership_id = %s
   AND m.condominium_id = %s
   AND m.status = 'active'
   AND rg.starts_at <= %s
   AND (rg.ends_at IS NULL OR rg.ends_at > %s)
   AND (rg.revoked_at IS NULL OR rg.revoked_at > %s)
 ORDER BY rg.role, rg.id
""".strip()


ACTIVE_ASSIGNMENTS_SQL = """
SELECT membership_id::text
  FROM document_assignments
 WHERE document_type = %s
   AND document_id = %s
   AND valid_from <= %s
   AND (valid_until IS NULL OR valid_until > %s)
   AND (revoked_at IS NULL OR revoked_at > %s)
""".strip()


def load_active_grants(
    cursor: Any,
    membership_id: str,
    condominium_id: str,
    *,
    at: Optional[datetime] = None,
) -> tuple[Grant, ...]:
    """Load current grants using a DB-API cursor and return validated objects."""
    instant = _utc(at or datetime.now(timezone.utc))
    cursor.execute(
        ACTIVE_GRANTS_SQL,
        (membership_id, condominium_id, instant, instant, instant),
    )
    grants = []
    for role, condo, member, grant_id, valid_from, valid_until, revoked_at in cursor.fetchall():
        grants.append(
            Grant(
                role=role,
                condominium_id=condo,
                membership_id=member,
                grant_id=grant_id,
                valid_from=valid_from,
                valid_until=valid_until,
                revoked_at=revoked_at,
            )
        )
    return tuple(grants)


def load_active_assignments(
    cursor: Any,
    document_type: str,
    document_id: str,
    *,
    at: Optional[datetime] = None,
) -> frozenset[str]:
    instant = _utc(at or datetime.now(timezone.utc))
    cursor.execute(
        ACTIVE_ASSIGNMENTS_SQL,
        (document_type, document_id, instant, instant, instant),
    )
    return frozenset(str(row[0]) for row in cursor.fetchall())


def resource_from_mapping(
    document: Mapping[str, Any],
    *,
    kind: str,
    assigned_membership_ids: Optional[Iterable[str]] = None,
    immutable: Optional[bool] = None,
) -> Resource:
    """Create the safe projection handlers need without trusting client roles."""
    return Resource(
        kind=kind,
        condominium_id=str(document["condominium_id"]),
        status=str(document["status"]),
        author_membership_id=(
            str(document["author_membership_id"])
            if document.get("author_membership_id") is not None
            else None
        ),
        assigned_membership_ids=frozenset(
            str(value)
            for value in (
                assigned_membership_ids
                if assigned_membership_ids is not None
                else document.get("assigned_membership_ids", ())
            )
        ),
        immutable=(bool(document.get("immutable", False)) if immutable is None else immutable),
    )
