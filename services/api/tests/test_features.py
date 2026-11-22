"""Feature switches gate every surface (routes, tasks, seeding)."""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.core.features import FEATURE_KEYS, is_enabled, public_dict

from tests.conftest import auth_client


@pytest.mark.parametrize("key", FEATURE_KEYS)
def test_public_dict_and_is_enabled(key):
    assert public_dict()[key] is True
    assert is_enabled(key) is True
    saved = getattr(settings, f"feature_{key}")
    try:
        setattr(settings, f"feature_{key}", False)
        assert is_enabled(key) is False
    finally:
        setattr(settings, f"feature_{key}", saved)


def _toggle(monkeypatch, key, value):

    monkeypatch.setenv(f"MIDENA_FEATURE_{key.upper()}", str(value).lower())
    # Settings are frozen at import; flip the live object like the env would.
    saved = getattr(settings, f"feature_{key}")
    setattr(settings, f"feature_{key}", value)
    return saved


def _csrf(c):
    return {"X-CSRF-Token": c.cookies.get("__Host-midena_csrf") or ""}


def test_public_diagrams_off_withdraws_every_public_link(client):
    from tests.support import make_diagram

    c, _ = auth_client("FeatPublic", role="admin")
    diagram = make_diagram(c, visibility="public")
    token = diagram["public_token"]
    base = f"/v1/public/diagrams/{diagram['uuid']}/{token}"
    anonymous = client
    assert anonymous.get(base).status_code == 200
    assert _admin_put(c, 0, {"public_diagrams": False}).status_code == 200
    for path in (base, f"{base}/source", f"{base}/svg"):
        assert anonymous.get(path).status_code == 404
    # The owner no longer sees a public link either.
    detail = c.get(f"/v1/diagrams/{diagram['uuid']}").json()
    assert detail["public_token"] is None
    assert detail["embed_url"] is None


def test_ai_generation_off_404s_its_routes(client):
    c, _ = auth_client("FeatAI", role="admin")
    assert _admin_put(c, 0, {"ai_generation": False}).status_code == 200
    body = {"diagram_type": "flowchart", "prompt": "two boxes"}
    assert (
        c.post("/v1/diagram-ai/generate", json=body, headers=_csrf(c)).status_code
        == 404
    )
    assert c.get("/v1/diagram-ai/status").json()["enabled"] is False


def test_google_drive_off_404s_its_route(client):
    from tests.support import make_diagram

    c, _ = auth_client("FeatDrive", role="admin")
    diagram = make_diagram(c)
    assert _admin_put(c, 0, {"google_drive_export": False}).status_code == 200
    response = c.post(
        f"/v1/diagrams/{diagram['uuid']}/export/google-drive",
        json={"format": "source"},
        headers=_csrf(c),
    )
    assert response.status_code == 404


def _toggle_off(key: str):
    saved = getattr(settings, f"feature_{key}")
    setattr(settings, f"feature_{key}", False)
    return saved


def _restore(key: str, saved) -> None:
    setattr(settings, f"feature_{key}", saved)


# --- Administrator-managed switches (ported from KEEN) ----------------------


def _admin_put(c, version, changes):
    return c.put(
        "/v1/admin/features",
        json={"version": version, "changes": changes},
        headers={"X-CSRF-Token": c.cookies.get("__Host-midena_csrf") or ""},
    )


def test_administrators_read_every_switch(client):
    c, _ = auth_client("FeatAdminRead", role="admin")
    body = c.get("/v1/admin/features").json()
    assert body["version"] == 0
    assert [item["key"] for item in body["items"]] == list(FEATURE_KEYS)
    assert body["enabled"] == {key: True for key in FEATURE_KEYS}
    assert body["configured"] == body["enabled"] == body["deployment"]


@pytest.mark.parametrize("role", ["viewer", "architect"])
def test_only_administrators_see_or_change_switches(client, role):
    c, _ = auth_client(f"FeatNonAdmin{role}", role=role)
    assert c.get("/v1/admin/features").status_code == 403
    assert _admin_put(c, 0, {"ai_generation": False}).status_code == 403
    assert is_enabled("ai_generation") is True


def test_an_administrator_switches_a_feature_off_and_on(client, db):
    from app.db.models import ManagedConfigurationRevision

    c, admin = auth_client("FeatAdminSave", role="admin")
    response = _admin_put(c, 0, {"ai_generation": False})
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
    assert response.json()["enabled"]["ai_generation"] is False
    # Every process sees the change straight away: routes, the UI's switches
    # and checks made outside any request.
    assert c.get("/v1/system/features").json()["ai_generation"] is False
    assert is_enabled("ai_generation") is False
    assert c.get("/v1/diagrams").status_code == 200

    assert _admin_put(c, 1, {"ai_generation": True}).status_code == 200
    assert is_enabled("ai_generation") is True
    revisions = (
        db.query(ManagedConfigurationRevision)
        .order_by(ManagedConfigurationRevision.version)
        .all()
    )
    assert [
        (r.version, r.document["ai_generation"], r.updated_by) for r in revisions
    ] == [
        (1, False, admin.id),
        (2, True, admin.id),
    ]


def test_a_stale_save_is_refused(client):
    c, _ = auth_client("FeatAdminStale", role="admin")
    assert _admin_put(c, 0, {"ai_generation": False}).status_code == 200
    stale = _admin_put(c, 0, {"public_diagrams": False})
    assert stale.status_code == 409
    assert stale.json() == {
        "detail": "Features changed in another session. Reload before saving."
    }
    assert is_enabled("public_diagrams") is True


@pytest.mark.parametrize(
    "body",
    [
        {"version": 0, "changes": {"unknown": False}},
        {"version": 0, "changes": {"ai_generation": "false"}},
        {"version": 0, "changes": {"ai_generation": 0}},
        {"version": True, "changes": {"ai_generation": False}},
        {"version": -1, "changes": {"ai_generation": False}},
        {"version": 0, "changes": {}},
        {"version": 0},
    ],
)
def test_malformed_saves_are_refused(client, body):
    c, _ = auth_client("FeatAdminBad", role="admin")
    response = c.put(
        "/v1/admin/features",
        json=body,
        headers={"X-CSRF-Token": c.cookies.get("__Host-midena_csrf") or ""},
    )
    assert response.status_code == 422
    assert c.get("/v1/admin/features").json()["version"] == 0


def test_the_deployment_setting_is_a_ceiling(client, monkeypatch):
    monkeypatch.setattr(settings, "feature_google_drive_export", False)
    c, _ = auth_client("FeatCeiling", role="admin")
    body = c.get("/v1/admin/features").json()
    assert body["deployment"]["google_drive_export"] is False
    assert body["configured"]["google_drive_export"] is True
    assert body["enabled"]["google_drive_export"] is False
    refused = _admin_put(c, 0, {"google_drive_export": True})
    assert refused.status_code == 409
    assert "MIDENA_FEATURE_GOOGLE_DRIVE_EXPORT=false" in refused.json()["detail"]
    # Other switches still save.
    assert _admin_put(c, 0, {"ai_generation": False}).status_code == 200


def test_a_change_saved_elsewhere_is_seen_without_a_restart(client, db):
    from app.db.models import ManagedConfiguration

    assert is_enabled("public_diagrams") is True
    db.add(
        ManagedConfiguration(
            name="features", document={"public_diagrams": False}, version=7
        )
    )
    db.commit()
    assert is_enabled("public_diagrams") is False
    assert public_dict()["public_diagrams"] is False


def test_unknown_feature_names_are_programming_errors():
    with pytest.raises(ValueError):
        is_enabled("nonsense")


def test_the_navbar_learns_the_features_with_the_account(client):
    c, _ = auth_client("FeatNavbar", role="admin")
    assert c.get("/v1/me").json()["features"] == {key: True for key in FEATURE_KEYS}
    assert _admin_put(c, 0, {"ai_generation": False}).status_code == 200
    features = c.get("/v1/me").json()["features"]
    assert features["ai_generation"] is False
    assert features["public_diagrams"] is True
