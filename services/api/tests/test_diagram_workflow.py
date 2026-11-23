"""Versions, locks, request sizes, cookies, bootstrap and housekeeping."""

from __future__ import annotations

import threading

import pytest
from app.core.config import settings
from app.db.models import DiagramVersion, User
from app.db.session import SessionLocal
from fastapi.testclient import TestClient

from tests.conftest import auth_client, generated_password
from tests.support import BPMN, csrf, make_diagram, ok


def test_saves_sent_together_each_get_their_own_version(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner)
    path = f"/v1/diagrams/{diagram['uuid']}/save"
    results: list[int] = []

    def save():
        response = owner.post(
            path, json={"diagram_type": "bpmn", "bpmn_xml": BPMN}, headers=csrf(owner)
        )
        results.append(response.status_code)

    threads = [threading.Thread(target=save) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [200] * 6
    with SessionLocal() as s:
        numbers = sorted(n for (n,) in s.query(DiagramVersion.version_number).all())
    assert numbers == list(range(1, 8))


def test_a_lock_holds_others_off_until_it_ends(client):
    owner, _ = auth_client(role="contributor")
    editor, editor_user = auth_client(role="contributor")
    diagram = make_diagram(owner)
    from tests.support import share

    share(owner, diagram["uuid"], editor_user.username, role="editor")
    base = f"/v1/diagrams/{diagram['uuid']}"
    ok(owner.post(f"{base}/lock", json={"ttl_seconds": 600}, headers=csrf(owner)))
    assert editor.post(f"{base}/lock", json={}, headers=csrf(editor)).status_code == 423
    saved = editor.post(
        f"{base}/save",
        json={"diagram_type": "bpmn", "bpmn_xml": BPMN},
        headers=csrf(editor),
    )
    assert saved.status_code == 423
    # Only the holder or an administrator ends it.
    assert editor.delete(f"{base}/lock", headers=csrf(editor)).status_code == 403
    ok(owner.delete(f"{base}/lock", headers=csrf(owner)))
    ok(editor.post(f"{base}/lock", json={}, headers=csrf(editor)))


def test_lock_lifetimes_are_bounded(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner)
    for ttl in (0, 59, 14401, 10**12):
        response = owner.post(
            f"/v1/diagrams/{diagram['uuid']}/lock",
            json={"ttl_seconds": ttl},
            headers=csrf(owner),
        )
        assert response.status_code == 422, ttl


def test_diagram_saves_take_more_than_a_form_and_no_more_than_their_class(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner)
    path = f"/v1/diagrams/{diagram['uuid']}/save"
    padding = "x" * (2 * 1024 * 1024)
    big = BPMN.replace("</bpmn:definitions>", f"<!--{padding}--></bpmn:definitions>")
    ok(
        owner.post(
            path, json={"diagram_type": "bpmn", "bpmn_xml": big}, headers=csrf(owner)
        )
    )
    over = owner.post(
        path,
        content=b'{"bpmn_xml": "' + b"x" * (9 * 1024 * 1024) + b'"}',
        headers={**csrf(owner), "Content-Type": "application/json"},
    )
    assert over.status_code == 413
    # Other routes keep the form limit.
    form = owner.patch(
        f"/v1/diagrams/{diagram['uuid']}",
        content=b'{"description": "' + b"x" * (3 * 1024 * 1024) + b'"}',
        headers={**csrf(owner), "Content-Type": "application/json"},
    )
    assert form.status_code == 413


def test_a_cookie_name_with_hidden_bytes_is_not_read_as_the_session(client):
    from myf.security.request_limits import screen_cookies

    scope = {
        "type": "http",
        "headers": [
            (
                b"cookie",
                b"__Host-midena_session\x85=planted; theme=ink; \xa0__Host-midena_csrf=x",
            )
        ],
    }
    screen_cookies(scope)
    assert scope["headers"] == [(b"cookie", b" theme=ink")]


# -- first administrator ---------------------------------------------------------


@pytest.fixture()
def bootstrap(monkeypatch):
    from myf.middleware import bootstrap_initial_admin

    def run(username, password):
        monkeypatch.setattr(settings, "bootstrap_admin_username", username)
        monkeypatch.setattr(settings, "bootstrap_admin_password", password)
        bootstrap_initial_admin()

    return run


def test_the_first_administrator_is_created_on_an_empty_installation_only(
    client, bootstrap
):
    password = generated_password()
    bootstrap("first-admin", password)
    with SessionLocal() as s:
        assert [(u.username, u.role) for u in s.query(User).all()] == [
            ("first-admin", "admin")
        ]
    # Left in the environment, the values never create or reset anything.
    bootstrap("second-admin", generated_password())
    with SessionLocal() as s:
        assert [u.username for u in s.query(User).all()] == ["first-admin"]


def test_the_application_creates_the_first_administrator_as_it_starts(
    client, monkeypatch
):
    from app import main
    from app.main import app

    async def nothing():
        return None

    # The client fixture's application already listens for notices; a second
    # listener in another event loop is not what this test is about.
    monkeypatch.setattr(main, "start_notification_listener", nothing)
    monkeypatch.setattr(main, "stop_notification_listener", nothing)
    monkeypatch.setattr(settings, "bootstrap_admin_username", "started-admin")
    monkeypatch.setattr(settings, "bootstrap_admin_password", generated_password())
    with TestClient(app):
        pass
    with SessionLocal() as s:
        assert [(u.username, u.role) for u in s.query(User).all()] == [
            ("started-admin", "admin")
        ]


@pytest.mark.parametrize(
    "password", ["<GENERATE_STRONG_PASSWORD>", "short", "password123456789"]
)
def test_a_placeholder_or_weak_bootstrap_password_is_refused(
    client, bootstrap, password
):
    with pytest.raises(RuntimeError) as refused:
        bootstrap("first-admin", password)
    assert password not in str(refused.value)
    with SessionLocal() as s:
        assert s.query(User).count() == 0


def test_half_a_bootstrap_configuration_is_refused(client, bootstrap):
    with pytest.raises(RuntimeError):
        bootstrap("first-admin", "")
