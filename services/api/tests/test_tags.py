"""Diagram tags: listed with the counts a reader may see, and managed by
administrators, with a rename carried to every diagram that uses the tag."""

from __future__ import annotations

from tests.support import csrf, make_diagram, ok, signed_in


def test_tags_are_counted_over_the_diagrams_each_reader_sees():
    owner, _ = signed_in("contributor")
    make_diagram(owner, name="Shared", tags=["Billing", "ops"], visibility="internal")
    make_diagram(owner, name="Mine", tags=["billing"], visibility="private")
    reader, _ = signed_in("viewer")
    counts = {t["name"]: t["count"] for t in ok(reader.get("/v1/tags"))["items"]}
    assert counts == {"Billing": 1, "ops": 1}
    counts = {t["name"]: t["count"] for t in ok(owner.get("/v1/tags"))["items"]}
    assert counts == {"Billing": 2, "ops": 1}


def test_administrators_create_and_rename_tags_everywhere_they_are_used():
    admin, _ = signed_in("admin")
    owner, _ = signed_in("contributor")
    first = make_diagram(owner, name="One", tags=["prod", "ops"], visibility="internal")
    second = make_diagram(owner, name="Two", tags=["production"])

    created = ok(
        admin.post(
            "/v1/tags", json={"name": "Review", "color": "#AA00ff"}, headers=csrf(admin)
        )
    )
    assert (created["name"], created["color"]) == ("Review", "#aa00ff")
    taken = admin.post("/v1/tags", json={"name": "review"}, headers=csrf(admin))
    assert taken.json() == {"detail": "A tag with that name already exists"}

    (prod,) = [t for t in ok(admin.get("/v1/tags"))["items"] if t["name"] == "prod"]
    url = f"/v1/tags/{prod['id']}"
    clash = admin.patch(url, json={"name": "OPS"}, headers=csrf(admin))
    assert clash.status_code == 409
    renamed = ok(admin.patch(url, json={"name": "Live"}, headers=csrf(admin)))
    assert renamed["name"] == "Live"
    # Only the exact tag changes: "production" is another tag.
    assert ok(owner.get(f"/v1/diagrams/{first['uuid']}"))["tags"] == ["Live", "ops"]
    assert ok(owner.get(f"/v1/diagrams/{second['uuid']}"))["tags"] == ["production"]

    # A case-only rename keeps the diagrams; a colour can be reset.
    ok(admin.patch(url, json={"name": "live"}, headers=csrf(admin)))
    recoloured = ok(admin.patch(url, json={"color": None}, headers=csrf(admin)))
    assert recoloured["color"].startswith("#")
    missing = admin.patch("/v1/tags/999999", json={"name": "x"}, headers=csrf(admin))
    assert missing.status_code == 404


def test_only_administrators_manage_tags():
    member, _ = signed_in("contributor")
    refused = member.post("/v1/tags", json={"name": "Mine"}, headers=csrf(member))
    assert refused.json() == {"detail": "Admin role required"}
