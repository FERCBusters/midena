"""A group gives its members the role it holds, never a neighbour of equal rank.

MIDENA's first resolver mapped a rank back to the first role with that rank,
so a group holding diagram_admin (rank 6, no diagram.write) gave its members
maintainer (rank 6, diagram.write): a privilege escalation.
"""

from __future__ import annotations

import pytest
from app.db.models import Group
from app.security.permissions import PERM_DIAGRAM_WRITE, has_permission
from app.security.roles import (
    _ROLE_PRECEDENCE,
    attach_effective_role,
    resolve_group_role,
)

from tests.conftest import make_user
from tests.support import csrf, make_diagram, make_group, signed_in


def _member_of(db, *roles):
    user = make_user(
        f"member-{'-'.join(roles)}", "Synthetic-group-role-passphrase", role="inherit"
    )
    for index, role in enumerate(roles):
        make_group(f"g-{index}-{role}", role=role, members=[user.id])
    return db.merge(user)


@pytest.mark.parametrize(
    "role", sorted(r for r in _ROLE_PRECEDENCE if r != "framework_admin")
)
def test_a_group_role_is_inherited_as_the_role_the_group_holds(db, role):
    assert attach_effective_role(db, _member_of(db, role)) == role


def test_a_diagram_admin_group_writes_folders_and_no_diagrams(db, client):
    member = _member_of(db, "diagram_admin")
    assert attach_effective_role(db, member) == "diagram_admin"
    assert has_permission(db, member, PERM_DIAGRAM_WRITE) is False


def test_the_legacy_framework_admin_spelling_is_a_diagram_admin(db):
    member = _member_of(db, "framework_admin")
    assert resolve_group_role(db, member.id) == "diagram_admin"
    assert has_permission(db, member, PERM_DIAGRAM_WRITE) is False


@pytest.mark.parametrize(
    "roles", [("maintainer", "diagram_admin"), ("diagram_admin", "maintainer")]
)
def test_holding_both_tied_roles_resolves_to_maintainer_whatever_the_order(db, roles):
    assert attach_effective_role(db, _member_of(db, *roles)) == "maintainer"


def test_the_highest_group_role_wins_and_unusable_group_roles_are_ignored(db):
    member = _member_of(db, "viewer", "architect", "pending")
    assert attach_effective_role(db, member) == "architect"
    db.query(Group).filter(Group.role == "architect").update({"role": "sorcerer"})
    db.commit()
    assert attach_effective_role(db, member) == "viewer"


def test_a_direct_role_is_not_changed_by_group_roles(db):
    user = make_user("direct", "Synthetic-group-role-passphrase", role="viewer")
    make_group("admins", role="admin", members=[user.id])
    assert attach_effective_role(db, db.merge(user)) == "viewer"


def test_the_escalation_is_refused_at_the_api(client):
    _, owner_id = signed_in(role="contributor")
    member, member_id = signed_in(role="inherit")
    make_group("diagram-admins", role="diagram_admin", members=[member_id])
    response = member.post(
        "/v1/diagrams", json={"name": "Escalated"}, headers=csrf(member)
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "diagram.write permission required"}
    # Folders, which the role does manage, are open to it.
    assert (
        member.post("/v1/folders", json={"name": "F"}, headers=csrf(member)).status_code
        == 200
    )
    _ = (owner_id, make_diagram)


def test_the_check_would_have_caught_the_first_resolver(db):
    """The rank-to-first-role mapping MIDENA shipped, against the same groups."""
    member = _member_of(db, "diagram_admin")
    rank = max(_ROLE_PRECEDENCE[r] for r in ("diagram_admin",))
    first_with_rank = next(r for r, p in _ROLE_PRECEDENCE.items() if p == rank)
    assert first_with_rank == "maintainer"
    assert resolve_group_role(db, member.id) != first_with_rank
