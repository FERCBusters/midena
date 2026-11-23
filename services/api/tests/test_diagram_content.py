"""Diagram content is data: parsed within bounds, stored sanitised, served
so that no browser runs it, and validated in time linear in its size."""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest
from app.api.routes import diagrams
from fastapi import HTTPException
from myf.security.svg import sanitise_svg

from tests.conftest import auth_client
from tests.support import SVG, csrf, make_diagram, make_flowchart, ok

_BPMN_OPEN = (
    '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
    'id="D" targetNamespace="https://example.com">'
)


def _save(client, diagram_uuid, **body):
    return client.post(
        f"/v1/diagrams/{diagram_uuid}/save", json=body, headers=csrf(client)
    )


@pytest.mark.parametrize(
    "xml",
    [
        # Entity expansion (billion laughs) needs an internal subset.
        '<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        + _BPMN_OPEN
        + "&b;</bpmn:definitions>",
        # External entities and any document type declaration at all.
        '<!DOCTYPE d SYSTEM "file:///etc/passwd">' + _BPMN_OPEN + "</bpmn:definitions>",
        # A style sheet a browser would apply if the file were opened.
        '<?xml-stylesheet href="https://evil.example/x.xsl"?>'
        + _BPMN_OPEN
        + "</bpmn:definitions>",
        # The right local name in the wrong namespace.
        '<definitions xmlns="urn:other"/>',
        # Not BPMN at all.
        '<svg xmlns="http://www.w3.org/2000/svg"/>',
        "not xml",
        # A namespace name long enough to multiply the tree's cost.
        f'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:x="urn:{"x" * 200}"/>',
    ],
)
def test_hostile_or_foreign_bpmn_is_refused(client, xml):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner)
    response = _save(owner, diagram["uuid"], diagram_type="bpmn", bpmn_xml=xml)
    assert response.status_code == 400, response.text


def test_bpmn_over_the_document_bound_is_refused_before_parsing():
    huge = _BPMN_OPEN + "<!--" + "x" * (3 * 1024 * 1024) + "--></bpmn:definitions>"
    with pytest.raises(HTTPException) as refused:
        diagrams._validate_bpmn_xml(huge)
    assert refused.value.status_code == 400


def test_stored_svg_is_rebuilt_from_the_allowlist(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_flowchart(owner)
    hostile = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">'
        "<script>alert(2)</script><style>@import url(https://evil.example/x.css);</style>"
        '<a xlink:href="javascript:alert(3)"><text>Go</text></a>'
        '<rect width="5" style="fill:url(https://evil.example/t.png)"/>'
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>'
        '<animate attributeName="href" to="javascript:alert(4)"/>'
        '<g data-id="A"><path d="M0 0L1 1"/></g></svg>'
    )
    ok(
        _save(
            owner,
            diagram["uuid"],
            diagram_type="flowchart",
            flowchart_text="flowchart LR\n A-->B",
            svg_xml=hostile,
        )
    )
    stored = ok(owner.get(f"/v1/diagrams/{diagram['uuid']}"))["svg_xml"]
    for bad in (
        "onload",
        "<script",
        "@import",
        "javascript:",
        "evil.example",
        "foreignObject",
        "<animate",
    ):
        assert bad not in stored, bad
    assert '<g data-id="A"><path d="M0 0L1 1" /></g>' in stored
    assert "<text>Go</text>" in stored


def test_a_flowchart_save_needs_a_rendering():
    with pytest.raises(HTTPException):
        diagrams._validate_rendered_svg_for_save("", "flowchart")
    with pytest.raises(HTTPException):
        diagrams._validate_rendered_svg_for_save("<html/>", "flowchart")


def test_sanitising_keeps_mixed_text_in_order():
    out = sanitise_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>a<tspan>b</tspan>c<script>x</script>d</text></svg>'
    )
    assert out.endswith("<text>a<tspan>b</tspan>cd</text></svg>")


# -- served so that no browser runs it ----------------------------------------


def test_exports_are_attachments_no_browser_renders(client):
    owner, _ = auth_client(role="contributor")
    xhtml = (
        _BPMN_OPEN.replace(">", ' xmlns:h="http://www.w3.org/1999/xhtml">', 1)
        + "<h:script>alert(1)</h:script></bpmn:definitions>"
    )
    diagram = make_diagram(owner, name='Ev"il\r\nName', bpmn_xml=xhtml, svg_xml=SVG)
    for fmt in ("bpmn", "svg"):
        response = owner.get(f"/v1/diagrams/{diagram['uuid']}/export/{fmt}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="')
        assert "\r" not in disposition and "\n" not in disposition
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in response.headers["content-security-policy"]


def test_every_served_media_type_goes_through_the_download_rule():
    """A Response built in the diagram routes takes its media type from
    attachment_media_type, so no route can serve markup as a document."""
    tree = ast.parse(Path(diagrams.__file__).read_text())
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Response":
            found += 1
            media = next(k.value for k in node.keywords if k.arg == "media_type")
            assert isinstance(media, ast.Call)
            assert getattr(media.func, "id", "") == "attachment_media_type"
    assert found >= 2


# -- public views ----------------------------------------------------------------


def test_a_public_link_shows_the_drawing_and_nothing_about_accounts(client):
    owner, owner_user = auth_client(role="contributor")
    diagram = make_diagram(owner, visibility="public", svg_xml=SVG)
    ok(
        owner.post(
            f"/v1/diagrams/{diagram['uuid']}/metadata-links",
            json={
                "label": "Spec",
                "url": "https://wiki.example/spec",
                "notes": "internal only",
            },
            headers=csrf(owner),
        )
    )
    anonymous = client
    base = f"/v1/public/diagrams/{diagram['uuid']}/{diagram['public_token']}"
    body = ok(anonymous.get(base))
    flat = repr(body)
    for leaked in (
        "created_by",
        "internal only",
        owner_user.username,
        "public_token",
        "can_delete",
        "shares",
        "locked_by",
    ):
        assert leaked not in flat, leaked
    assert body["metadata_links"] == [
        {
            "id": body["metadata_links"][0]["id"],
            "label": "Spec",
            "url": "https://wiki.example/spec",
        }
    ]
    source = anonymous.get(f"{base}/source")
    assert source.headers["content-type"] == "application/octet-stream"


def test_wrong_tokens_and_private_diagrams_all_answer_the_same(client):
    owner, _ = auth_client(role="contributor")
    public = make_diagram(owner, visibility="public")
    private = make_diagram(owner, visibility="private")
    anonymous = client
    for path in (
        f"/v1/public/diagrams/{public['uuid']}/wrong-token",
        f"/v1/public/diagrams/{public['uuid']}/{'x' * 97}",
        f"/v1/public/diagrams/{private['uuid']}/{private['public_token'] or 'x'}",
        f"/v1/public/diagrams/not-a-uuid/{public['public_token']}",
    ):
        response = anonymous.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Diagram not found"}


def test_withdrawing_a_public_diagram_retires_its_links_for_good(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner, visibility="public")
    old = f"/v1/public/diagrams/{diagram['uuid']}/{diagram['public_token']}"
    path = f"/v1/diagrams/{diagram['uuid']}"
    ok(owner.patch(path, json={"visibility": "private"}, headers=csrf(owner)))
    republished = ok(
        owner.patch(path, json={"visibility": "public"}, headers=csrf(owner))
    )
    assert republished["public_token"] != diagram["public_token"]
    assert client.get(old).status_code == 404
    new = f"/v1/public/diagrams/{diagram['uuid']}/{republished['public_token']}"
    assert client.get(new).status_code == 200


def test_public_tokens_never_reach_the_audit_trail(client):
    from app.db.models import AuditLog
    from app.db.session import SessionLocal

    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner, visibility="public")
    token = diagram["public_token"]
    client.get(
        f"/v1/public/diagrams/{diagram['uuid']}/{token}",
        headers={
            "Referer": f"https://midena.example/public/diagrams/{diagram['uuid']}/{token}.html?x=1"
        },
    )
    with SessionLocal() as s:
        rows = s.query(AuditLog).all()
    assert rows
    for row in rows:
        assert token not in row.path
        assert token not in (row.referer or "")


# -- linear validation -------------------------------------------------------------


def _timed(fn, *args) -> float:
    start = time.perf_counter()
    try:
        fn(*args)
    except HTTPException:
        pass
    return time.perf_counter() - start


@pytest.mark.parametrize(
    "text",
    [
        # A tag opener repeated with no closer: a backtracking search for
        # "<x...>" restarts at every one of them.
        "<a" * 500_000,
        "\n" * 1_000_000,
        "-" * 1_000_000,
        "sequenceDiagram\n" + "A->B: x\n" * 120_000,
    ],
)
def test_source_checks_are_linear_at_the_largest_accepted_size(text):
    assert len(text) <= diagrams.MAX_TEXT_SOURCE_CHARS
    assert _timed(diagrams._validate_sequence_text, text) < 1.0
    assert _timed(diagrams._validate_flowchart_text, text) < 1.0


def test_ai_answers_are_read_in_linear_time():
    from app.services.diagram_ai import _strip_markdown_fence

    for answer in ("```a" * 60_000, "x\n" * 100_000, "`" * 200_000):
        start = time.perf_counter()
        _strip_markdown_fence(answer)
        assert time.perf_counter() - start < 0.5
    assert diagrams._validate_ai_generated_code("sequence", "A->B: hi")
    assert _timed(diagrams._validate_ai_generated_code, "sequence", "-" * 200_000) < 0.5


def test_markup_detection_matches_the_pattern_it_replaced():
    import re

    old = re.compile(r"<[a-zA-Z/!][^>]*>")
    for sample in (
        "a < b",
        "<b>",
        "x <1> y",
        "<!-- x -->",
        "</p",
        "a<b c>d",
        "<",
        "<>",
    ):
        assert diagrams._has_markup_tag(sample) == bool(old.search(sample)), sample
