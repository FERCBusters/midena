"""Who reads, changes, shares, clones and deletes each diagram."""

from __future__ import annotations

import uuid

from app.db.models import Diagram, DiagramShare
from app.db.session import SessionLocal

from tests.conftest import auth_client, make_user
from tests.support import BPMN, csrf, make_diagram, ok, share


def test_private_diagrams_are_their_authors_and_sharees_alone(client):
    owner, _ = auth_client(role="contributor")
    other, other_user = auth_client(role="viewer")
    diagram = make_diagram(owner, visibility="private")
    path = f"/v1/diagrams/{diagram['uuid']}"

    # A reader without the private-read permission learns nothing about it:
    # the same 404 as a diagram that does not exist.
    assert other.get(path).status_code == 404
    assert other.get(f"/v1/diagrams/{uuid.uuid4()}").status_code == 404
    assert diagram["uuid"] not in [
        d["uuid"] for d in ok(other.get("/v1/diagrams"))["items"]
    ]
    versions = ok(owner.get(f"{path}/versions"))["items"]
    assert other.get(f"/v1/diagram-versions/{versions[0]['id']}").status_code == 404

    share(owner, diagram["uuid"], other_user.username)
    assert other.get(path).status_code == 200


def test_internal_diagrams_are_read_by_every_account_and_changed_by_few(client):
    owner, _ = auth_client(role="contributor")
    reader, _ = auth_client(role="viewer")
    writer, _ = auth_client(role="contributor")
    diagram = make_diagram(owner, visibility="internal")
    path = f"/v1/diagrams/{diagram['uuid']}"
    assert reader.get(path).status_code == 200
    # Holding diagram.write is not enough: the diagram is someone else's.
    response = writer.patch(path, json={"name": "Taken"}, headers=csrf(writer))
    assert response.status_code == 403
    # A viewer is refused at the middleware before the route runs.
    response = reader.patch(path, json={"name": "Taken"}, headers=csrf(reader))
    assert response.status_code == 403


def test_an_editor_share_needs_the_write_permission_too(client):
    owner, _ = auth_client(role="contributor")
    viewer, viewer_user = auth_client(role="viewer")
    contributor, contributor_user = auth_client(role="contributor")
    diagram = make_diagram(owner)
    share(owner, diagram["uuid"], viewer_user.username, role="editor")
    share(owner, diagram["uuid"], contributor_user.username, role="editor")
    body = {"diagram_type": "bpmn", "bpmn_xml": BPMN}
    path = f"/v1/diagrams/{diagram['uuid']}/save"
    assert viewer.post(path, json=body, headers=csrf(viewer)).status_code == 403
    assert (
        contributor.post(path, json=body, headers=csrf(contributor)).status_code == 200
    )


def test_only_the_author_or_an_administrator_deletes_or_manages_sharing(client):
    owner, _ = auth_client(role="contributor")
    editor, editor_user = auth_client(role="contributor")
    admin, _ = auth_client(role="admin")
    diagram = make_diagram(owner)
    share(owner, diagram["uuid"], editor_user.username, role="editor")
    path = f"/v1/diagrams/{diagram['uuid']}"
    assert editor.delete(path, headers=csrf(editor)).status_code == 403
    refused = editor.post(
        f"{path}/shares", json={"identifier": "someone"}, headers=csrf(editor)
    )
    assert refused.status_code == 403
    assert admin.delete(path, headers=csrf(admin)).status_code == 200


def test_share_targets_are_named_exactly_never_as_patterns(client):
    owner, _ = auth_client(role="contributor")
    make_user("alice-exact", "Synthetic-share-target-passphrase", role="viewer")
    diagram = make_diagram(owner)
    for pattern in ("%", "alice%", "_lice-exact", "ALICE-EXACT%"):
        response = owner.post(
            f"/v1/diagrams/{diagram['uuid']}/shares",
            json={"identifier": pattern, "notify": False},
            headers=csrf(owner),
        )
        assert response.status_code == 404, pattern
    # Case aside, the exact name finds the account.
    share(owner, diagram["uuid"], "ALICE-EXACT")


def test_account_addresses_are_shown_only_to_who_manages_sharing(client):
    owner, _ = auth_client(role="contributor")
    reader, reader_user = auth_client(role="viewer")
    make_user(
        "mailed",
        "Synthetic-share-mail-passphrase",
        role="viewer",
        email="mailed@example.com",
    )
    diagram = make_diagram(owner)
    share(owner, diagram["uuid"], "mailed")
    share(owner, diagram["uuid"], reader_user.username)
    managers_view = ok(owner.get(f"/v1/diagrams/{diagram['uuid']}/shares"))
    readers_view = ok(reader.get(f"/v1/diagrams/{diagram['uuid']}/shares"))
    assert "mailed@example.com" in [s["email"] for s in managers_view["items"]]
    assert all(s["email"] is None for s in readers_view["items"])
    assert readers_view["can_manage"] is False


def test_user_search_lists_usernames_only_and_needs_two_characters(client):
    searcher, _ = auth_client(role="viewer")
    make_user(
        "bobby-search",
        "Synthetic-search-target-passphrase",
        role="viewer",
        email="bobby@example.com",
    )
    assert ok(searcher.get("/v1/users/search?q=b"))["items"] == []
    items = ok(searcher.get("/v1/users/search?q=bobby"))["items"]
    assert items == [{"id": items[0]["id"], "username": "bobby-search"}]
    # An address is not a way to find an account here.
    assert ok(searcher.get("/v1/users/search?q=bobby@example"))["items"] == []
    # Wildcards are literal characters.
    assert ok(searcher.get("/v1/users/search?q=%25%25"))["items"] == []


def test_a_clone_is_private_and_carries_none_of_the_sources_sharing(client):
    owner, _ = auth_client(role="contributor")
    cloner, cloner_user = auth_client(role="contributor")
    _, friend = auth_client(role="viewer")
    diagram = make_diagram(owner, visibility="public")
    share(owner, diagram["uuid"], cloner_user.username)
    share(owner, diagram["uuid"], friend.username)
    clone = ok(
        cloner.post(f"/v1/diagrams/{diagram['uuid']}/clone", headers=csrf(cloner))
    )
    assert clone["visibility"] == "private"
    assert clone["public_token"] is None
    with SessionLocal() as s:
        clone_id = (
            s.query(Diagram.id)
            .filter(Diagram.uuid == uuid.UUID(clone["uuid"]))
            .scalar()
        )
        assert (
            s.query(DiagramShare).filter(DiagramShare.diagram_id == clone_id).count()
            == 0
        )


def test_diagrams_are_addressed_by_uuid_only(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner, name="Order flow")
    for ref in (str(diagram["id"]), diagram["slug"], "order-flow", "1 OR 1=1"):
        assert owner.get(f"/v1/diagrams/{ref}").status_code == 404, ref


def test_search_text_is_literal(client):
    owner, _ = auth_client(role="contributor")
    make_diagram(owner, name="Plain")
    make_diagram(owner, name="100% done")

    def names(q):
        return [
            d["name"] for d in ok(owner.get("/v1/diagrams", params={"q": q}))["items"]
        ]  # noqa: E731

    assert names("%") == ["100% done"]
    assert names("_lain") == []
    assert names("plain") == ["Plain"]


def test_comment_element_ids_are_held_to_their_shape(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner)
    path = f"/v1/diagrams/{diagram['uuid']}/comments"
    for bad in ('"><img src=x>', "a b", "x" * 300, "<svg>"):
        response = owner.post(
            path, json={"body": "hi", "element_id": bad}, headers=csrf(owner)
        )
        assert response.status_code == 422, bad
    ok(
        owner.post(
            path, json={"body": "hi", "element_id": "Task_1"}, headers=csrf(owner)
        )
    )


def test_link_metadata_is_flat_and_bounded(client):
    owner, _ = auth_client(role="contributor")
    diagram = make_diagram(owner)
    path = f"/v1/diagrams/{diagram['uuid']}/entity-links"
    base = {"element_id": "Task_1", "label": "Runbook", "url": "https://wiki.example/x"}
    for metadata in (
        {"nested": {"a": 1}},
        {f"k{i}": i for i in range(51)},
        {"long": "x" * 2001},
        {"list": [1, 2]},
    ):
        response = owner.post(
            path, json={**base, "metadata": metadata}, headers=csrf(owner)
        )
        assert response.status_code == 422, metadata
    for url in ("javascript:alert(1)", "data:text/html,x", "//evil.example"):
        response = owner.post(path, json={**base, "url": url}, headers=csrf(owner))
        assert response.status_code == 422, url
    ok(
        owner.post(
            path, json={**base, "metadata": {"system": "erp"}}, headers=csrf(owner)
        )
    )
    duplicate = owner.post(
        path, json={**base, "entity_ref": "same"}, headers=csrf(owner)
    )
    assert duplicate.status_code == 200
    again = owner.post(path, json={**base, "entity_ref": "same"}, headers=csrf(owner))
    assert again.status_code == 409
