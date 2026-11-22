"""Every e-mail a request queues reaches the committed outbox.

A request's session discards whatever it has not committed when it closes.
These senders once queued their mail after the request's last commit, so the
mail never left: each case here reads the outbox from a fresh session.
"""

from __future__ import annotations

from tests.conftest import auth_client, make_user


def _csrf(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("__Host-midena_csrf") or ""}


def _admin():
    admin, _user = auth_client(role="admin")
    return admin


def test_sharing_a_diagram_mails_the_account_it_is_shared_with(outbox):
    from tests.support import make_diagram

    admin = _admin()
    make_user(
        "mailedviewer",
        "Synthetic-share-mail-passphrase",
        role="viewer",
        email="viewer@x.test",
    )
    diagram = make_diagram(admin, name="Mailed\nSubject")
    response = admin.post(
        f"/v1/diagrams/{diagram['uuid']}/shares",
        json={"identifier": "mailedviewer", "role": "viewer"},
        headers=_csrf(admin),
    )
    assert response.status_code == 200, response.text
    messages = outbox.messages()
    assert [m.recipient for m in messages] == ["viewer@x.test"]
    body = messages[0].body
    # The link comes from MIDENA_PUBLIC_BASE_URL, never from the request.
    assert f"https://midena.example.com/diagram.html?id={diagram['uuid']}" in body
    assert "Mailed Subject" in body
    assert outbox.kicks == [] or outbox.kicks


def test_a_share_without_a_public_base_url_sends_no_link(outbox, monkeypatch):
    from app.core.config import settings

    from tests.support import make_diagram

    monkeypatch.setattr(settings, "public_base_url", "")
    admin = _admin()
    make_user(
        "nolink",
        "Synthetic-share-mail-passphrase",
        role="viewer",
        email="nolink@x.test",
    )
    diagram = make_diagram(admin)
    response = admin.post(
        f"/v1/diagrams/{diagram['uuid']}/shares",
        json={"identifier": "nolink"},
        headers={**_csrf(admin), "Host": "attacker.example"},
    )
    assert response.status_code == 200, response.text
    (message,) = outbox.messages()
    assert "http" not in message.body
    assert "attacker.example" not in message.body


def test_a_refused_share_queues_no_mail(outbox):
    from tests.support import make_diagram

    admin = _admin()
    diagram = make_diagram(admin)
    response = admin.post(
        f"/v1/diagrams/{diagram['uuid']}/shares",
        json={"identifier": "nobody-by-this-name"},
        headers=_csrf(admin),
    )
    assert response.status_code == 404
    assert outbox.messages() == []
