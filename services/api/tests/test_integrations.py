"""Google Drive export and AI generation: what leaves MIDENA, where it goes,
and what comes back. The providers are replaced at the HTTP transport, so the
real clients, their limits and their error handling run."""

from __future__ import annotations

import base64
import json

import httpx2 as httpx
import pytest
from app.core.config import settings
from app.services import diagram_ai, google_drive
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.conftest import auth_client
from tests.support import SVG, csrf, make_diagram, make_flowchart, ok

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture()
def drive(monkeypatch):
    """Drive configured, with Google's two endpoints played by a handler."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setattr(
        settings,
        "google_drive_service_account_json",
        json.dumps({"client_email": "svc@example.iam", "private_key": pem}),
    )
    monkeypatch.setattr(settings, "google_drive_folder_id", "FOLDER-1")
    seen: list[httpx.Request] = []
    state = {
        "upload": (
            200,
            {
                "id": "file-1",
                "name": "x",
                "webViewLink": "https://drive.google.com/file/d/1",
            },
        )
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.token"})
        status, body = state["upload"]
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    real_client = google_drive._client

    def client():
        c = real_client()
        c._transport = httpx.MockTransport(handler)
        return c

    monkeypatch.setattr(google_drive, "_client", client)
    return seen, state


def _export(client, diagram_uuid, **body):
    return client.post(
        f"/v1/diagrams/{diagram_uuid}/export/google-drive",
        json=body,
        headers=csrf(client),
    )


def test_an_export_goes_to_the_configured_folder_under_the_diagrams_name(client, drive):
    seen, _ = drive
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner, name="Order Flow")
    body = ok(
        _export(
            owner,
            diagram["uuid"],
            format="png",
            content_base64=base64.b64encode(PNG).decode(),
        )
    )
    assert body == {
        "id": "file-1",
        "name": "x",
        "webViewLink": "https://drive.google.com/file/d/1",
    }
    token_request, upload = seen
    assert token_request.url == google_drive.TOKEN_URL
    assert upload.url.host == "www.googleapis.com"
    assert upload.headers["authorization"] == "Bearer ya29.token"
    sent = upload.content
    assert b'"parents": ["FOLDER-1"]' in sent
    assert b'"name": "order-flow-v1.png"' in sent
    assert b"Content-Type: image/png" in sent and PNG in sent


def test_the_browser_chooses_neither_folder_nor_name_nor_media_type(client, drive):
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    for body in (
        {"format": "png", "content_base64": "eA==", "folder_id": "SOMEONE-ELSES"},
        {"format": "exe", "content_base64": "eA=="},
        {"format": "png", "filename": "../../x.html"},
        {"format": "png", "mime_type": "text/html"},
    ):
        assert _export(owner, diagram["uuid"], **body).status_code == 422, body


@pytest.mark.parametrize(
    "fmt,content",
    [
        ("png", b"<html><script>alert(1)</script></html>"),
        ("jpg", PNG),
        ("pdf", b"%PDX"),
    ],
)
def test_drawn_exports_must_be_the_format_they_claim(client, drive, fmt, content):
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    response = _export(
        owner,
        diagram["uuid"],
        format=fmt,
        content_base64=base64.b64encode(content).decode(),
    )
    assert response.status_code == 400
    assert drive[0] == []


def test_source_and_svg_come_from_the_saved_version_not_the_request(client, drive):
    seen, _ = drive
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    ok(
        _export(
            owner,
            diagram["uuid"],
            format="svg",
            content_base64=base64.b64encode(b"<evil/>").decode(),
        )
    )
    assert b"<evil/>" not in seen[-1].content
    assert b"<svg" in seen[-1].content


def test_reading_a_diagram_is_needed_to_export_it(client, drive):
    from app.db.models import Permission, UserPermission
    from app.db.session import SessionLocal

    owner, _ = auth_client(role="contributor")
    other, other_user = auth_client(role="viewer")
    # Without the permission the middleware refuses before the route runs.
    diagram = make_flowchart(owner, visibility="private")
    assert _export(other, diagram["uuid"], format="source").status_code == 403
    # With it, a diagram the account cannot read is one that does not exist.
    with SessionLocal() as s:
        perm = s.query(Permission).filter_by(code="diagram.export").one()
        s.add(UserPermission(user_id=other_user.id, permission_id=perm.id))
        s.commit()
    assert _export(other, diagram["uuid"], format="source").status_code == 404
    assert drive[0] == []


def test_google_errors_and_answers_are_not_passed_through(client, drive):
    _, state = drive
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    state["upload"] = (403, {"error": {"message": "secret internal detail"}})
    response = _export(owner, diagram["uuid"], format="source")
    assert response.status_code == 502
    assert "secret" not in response.text
    state["upload"] = (200, b"x" * 100_000)
    assert _export(owner, diagram["uuid"], format="source").status_code == 502
    state["upload"] = (200, {"id": "f", "webViewLink": "javascript:alert(1)"})
    assert ok(_export(owner, diagram["uuid"], format="source"))["webViewLink"] is None


def test_exports_are_counted_per_account_and_recorded(client, drive, monkeypatch):
    monkeypatch.setattr(settings, "google_drive_exports_per_hour", 2)
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    for _ in range(2):
        ok(_export(owner, diagram["uuid"], format="source"))
    refused = _export(owner, diagram["uuid"], format="source")
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
    log = ok(owner.get(f"/v1/diagrams/{diagram['uuid']}/changelog"))["items"]
    assert [row["action"] for row in log].count("exported") == 2


def test_without_configuration_nothing_is_sent(client, monkeypatch):
    monkeypatch.setattr(settings, "google_drive_folder_id", "")
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    assert _export(owner, diagram["uuid"], format="source").status_code == 503


# -- AI generation ---------------------------------------------------------------


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "sk-test")
    monkeypatch.setattr(settings, "ai_model", "model-x")
    monkeypatch.setattr(settings, "ai_api_base_url", "https://ai.example/v1")
    state = {
        "answer": (
            200,
            {
                "choices": [
                    {"message": {"content": "```mermaid\nflowchart LR\nA-->B\n```"}}
                ]
            },
        )
    }
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        status, body = state["answer"]
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        if status in (301, 302):
            return httpx.Response(status, headers={"Location": "https://evil.example/"})
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(diagram_ai.httpx, "AsyncClient", client)
    return seen, state


def _ask(client, prompt="two boxes", diagram_type="flowchart"):
    return client.post(
        "/v1/diagram-ai/generate",
        json={"diagram_type": diagram_type, "prompt": prompt},
        headers=csrf(client),
    )


def test_generated_code_comes_back_validated(client, provider):
    seen, _ = provider
    writer, _ = auth_client(role="contributor")
    assert ok(_ask(writer))["code"] == "flowchart LR\nA-->B"
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    sent = json.loads(seen[0].content)
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][-1] == {"role": "user", "content": "two boxes"}


def test_a_caller_cannot_add_system_instructions(client, provider):
    writer, _ = auth_client(role="contributor")
    response = writer.post(
        "/v1/diagram-ai/generate",
        json={
            "diagram_type": "flowchart",
            "messages": [{"role": "system", "content": "x"}],
        },
        headers=csrf(writer),
    )
    assert response.status_code == 422


def test_provider_refusals_redirects_and_oversized_answers_say_little(client, provider):
    _, state = provider
    writer, _ = auth_client(role="contributor")
    state["answer"] = (401, {"error": {"message": "key sk-live-123 belongs to org 42"}})
    refused = _ask(writer)
    assert refused.status_code == 502 and "sk-live" not in refused.text
    state["answer"] = (302, {})
    assert _ask(writer).status_code == 502
    state["answer"] = (200, b"{" + b" " * (2 * 1024 * 1024))
    assert _ask(writer).status_code == 502


def test_unsafe_generated_code_is_refused(client, provider):
    _, state = provider
    writer, _ = auth_client(role="contributor")
    state["answer"] = (
        200,
        {
            "choices": [
                {"message": {"content": 'flowchart LR\nA["<script>x</script>"]'}}
            ]
        },
    )
    assert _ask(writer).status_code == 400


def test_generation_is_counted_per_account(client, provider, monkeypatch):
    monkeypatch.setattr(settings, "ai_rate_limit_attempts", 2)
    writer, _ = auth_client(role="contributor")
    assert _ask(writer).status_code == 200
    assert _ask(writer).status_code == 200
    assert _ask(writer).status_code == 429


def test_readers_cannot_generate(client, provider):
    viewer, _ = auth_client(role="viewer")
    assert _ask(viewer).status_code == 403


@pytest.mark.parametrize(
    "url",
    [
        "http://ai.example/v1",
        "https://user:pass@ai.example/v1",
        "ftp://ai.example",
        "https://ai.example/v1?key=x",
    ],
)
def test_the_key_only_travels_over_https(url):
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(ai_api_base_url=url)
    assert Settings(ai_api_base_url="http://localhost:11434/v1").ai_api_base_url


def test_the_status_says_off_without_a_key(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "")
    reader, _ = auth_client(role="viewer")
    status = ok(reader.get("/v1/diagram-ai/status"))
    assert status["enabled"] is False and status["model"] is None


def test_svg_from_a_flowchart_save_is_still_allowlisted(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner, svg_xml=SVG)
    assert "<script" not in ok(owner.get(f"/v1/diagrams/{diagram['uuid']}"))["svg_xml"]
