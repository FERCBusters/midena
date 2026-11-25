"""API tokens: another application (KEEN, say) lists and opens diagrams as
one account, with that account's visibility, and reaches nothing else."""

from __future__ import annotations

import uuid

import pytest
from app.core.config import settings
from app.db.models import ApiToken
from app.db.session import SessionLocal
from app.main import app
from app.security.route_policy import MIDENA_POLICY
from fastapi.testclient import TestClient
from mosp.security import api_token_format

from tests.conftest import auth_client, peer_wrapper
from tests.support import csrf, make_diagram, make_flowchart, ok, share


@pytest.fixture(autouse=True)
def tokens_on(monkeypatch):
    """The deployment turns API tokens on (they are off by default)."""
    monkeypatch.setattr(settings, "api_tokens_enabled", True)


def _issue(admin, user_id, **fields) -> str:
    response = admin.post(
        "/v1/admin/api-tokens",
        json={"name": "KEEN", "user_id": str(user_id), **fields},
        headers=csrf(admin),
    )
    return ok(response, 201)["token"]


def _machine() -> TestClient:
    """A client with no cookies, as another application calls the API."""
    return TestClient(peer_wrapper(app), base_url="https://testserver")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_only_listing_and_opening_diagrams_are_open_to_tokens():
    assert MIDENA_POLICY.token_reads.routes == {
        "GET": ("/v1/diagrams", "/v1/diagrams/{diagram_ref}")
    }


def test_a_token_lists_and_opens_diagrams_with_its_accounts_visibility(client):
    admin, _ = auth_client(role="admin")
    author, _ = auth_client(role="contributor")
    _, reader = auth_client(role="viewer")
    internal = make_flowchart(author, "Access review", visibility="internal")
    hidden = make_diagram(author, "Board only", visibility="private")
    token = _issue(admin, reader.id)
    assert token.startswith("midena_at_")
    machine = _machine()

    listed = ok(machine.get("/v1/diagrams?q=review", headers=_bearer(token)))
    assert [item["uuid"] for item in listed["items"]] == [internal["uuid"]]
    every = ok(machine.get("/v1/diagrams", headers=_bearer(token)))
    assert hidden["uuid"] not in [item["uuid"] for item in every["items"]]

    detail = ok(machine.get(f"/v1/diagrams/{internal['uuid']}", headers=_bearer(token)))
    assert detail["name"] == "Access review"
    assert detail["svg_xml"].startswith("<svg")
    # A private diagram is the same 404 as one that does not exist, until it
    # is shared with the token's account.
    path = f"/v1/diagrams/{hidden['uuid']}"
    assert machine.get(path, headers=_bearer(token)).status_code == 404
    share(author, hidden["uuid"], reader.username)
    assert machine.get(path, headers=_bearer(token)).status_code == 200


def test_a_token_reaches_nothing_else(client):
    admin, admin_user = auth_client(role="admin")
    diagram = make_diagram(admin, visibility="internal")
    token = _issue(admin, admin_user.id)
    machine = _machine()
    refused = {"detail": "API tokens reach only the routes listed for them"}
    for method, path in (
        ("GET", f"/v1/diagrams/{diagram['uuid']}/versions"),
        ("GET", f"/v1/diagrams/{diagram['uuid']}/export/svg"),
        ("GET", "/v1/me"),
        ("GET", "/v1/admin/api-tokens"),
        ("GET", "/v1/admin/users"),
        ("PATCH", f"/v1/diagrams/{diagram['uuid']}"),
        ("POST", "/v1/diagrams"),
        ("DELETE", f"/v1/diagrams/{diagram['uuid']}"),
    ):
        response = machine.request(
            method,
            path,
            json={},
            headers={**_bearer(token), "Origin": "https://testserver"},
        )
        assert (response.status_code, response.json()) == (403, refused), path


def test_revoked_tokens_and_deactivated_accounts_read_nothing(client):
    admin, _ = auth_client(role="admin")
    _, reader = auth_client(role="viewer")
    token = _issue(admin, reader.id)
    machine = _machine()
    assert machine.get("/v1/diagrams", headers=_bearer(token)).status_code == 200

    items = ok(admin.get("/v1/admin/api-tokens"))["items"]
    (item,) = [row for row in items if row["user_id"] == str(reader.id)]
    assert "token" not in item and item["hint"] == token[-4:]
    ok(admin.post(f"/v1/admin/api-tokens/{item['id']}/revoke", headers=csrf(admin)))
    assert machine.get("/v1/diagrams", headers=_bearer(token)).status_code == 401

    second = _issue(admin, reader.id)
    account = f"/v1/admin/users/{reader.id}"
    ok(admin.patch(account, json={"is_active": False}, headers=csrf(admin)))
    assert machine.get("/v1/diagrams", headers=_bearer(second)).status_code == 401
    statuses = {
        row["hint"]: row["status"]
        for row in ok(admin.get("/v1/admin/api-tokens"))["items"]
    }
    assert statuses[second[-4:]] == "revoked"
    # Activated again, the account's earlier tokens stay revoked, as its
    # sessions stay ended; a token issued now works.
    ok(admin.patch(account, json={"is_active": True}, headers=csrf(admin)))
    assert machine.get("/v1/diagrams", headers=_bearer(second)).status_code == 401
    third = _issue(admin, reader.id)
    assert machine.get("/v1/diagrams", headers=_bearer(third)).status_code == 200


def test_a_password_reset_leaves_the_accounts_tokens_working(client):
    admin, _ = auth_client(role="admin")
    _, reader = auth_client(role="viewer")
    token = _issue(admin, reader.id)
    machine = _machine()
    ok(
        admin.post(
            f"/v1/admin/users/{reader.id}/password",
            json={"new_password": "Synthetic-reset-passphrase-for-tests"},
            headers=csrf(admin),
        )
    )
    assert machine.get("/v1/diagrams", headers=_bearer(token)).status_code == 200


def test_only_administrators_issue_tokens(client):
    viewer, viewer_user = auth_client(role="maintainer")
    response = viewer.post(
        "/v1/admin/api-tokens",
        json={"name": "mine", "user_id": str(viewer_user.id)},
        headers=csrf(viewer),
    )
    assert response.status_code == 403
    assert viewer.get("/v1/admin/api-tokens").status_code == 403


def test_the_database_keeps_only_the_tokens_digest(client):
    admin, admin_user = auth_client(role="admin")
    token = _issue(admin, admin_user.id, expires_in_days=90)
    with SessionLocal() as s:
        (row,) = s.query(ApiToken).all()
        assert row.token_hash == api_token_format.digest(token)
        assert row.expires_at is not None
        assert isinstance(row.id, uuid.UUID)
        assert token not in (row.token_hash, row.hint, row.name)


def test_api_tokens_are_off_unless_the_deployment_turns_them_on(client, monkeypatch):
    admin, admin_user = auth_client(role="admin")
    token = _issue(admin, admin_user.id)
    monkeypatch.setattr(settings, "api_tokens_enabled", False)
    assert _machine().get("/v1/diagrams", headers=_bearer(token)).status_code == 401
    refused = admin.post(
        "/v1/admin/api-tokens",
        json={"name": "KEEN", "user_id": str(admin_user.id)},
        headers=csrf(admin),
    )
    assert refused.status_code == 409
    assert "MIDENA_API_TOKENS_ENABLED" in refused.json()["detail"]
    listing = ok(admin.get("/v1/admin/api-tokens"))
    assert listing["enabled"] is False and len(listing["items"]) == 1


def test_the_shipped_default_is_off():
    from app.core.config import Settings

    assert Settings.model_fields["api_tokens_enabled"].default is False
