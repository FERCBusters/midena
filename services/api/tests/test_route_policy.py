"""Deny by default: every write is declared in MIDENA's route policy or
mosp's, every declaration names a served route, and anything not declared is
refused, with or without an account."""

from __future__ import annotations

import re

import pytest
from app.main import app
from app.security.route_policy import MIDENA_POLICY
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from mosp.security.route_policy import UNSAFE_METHODS, RouteSet, policy

from tests.conftest import auth_client, peer_wrapper
from tests.support import csrf


def _walk(routes, prefix=""):
    for route in routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                yield method, prefix + route.path
        elif hasattr(route, "original_router"):
            # An included router keeps its own routes under its prefix.
            context = getattr(route, "include_context", None)
            yield from _walk(
                route.original_router.routes,
                prefix + (getattr(context, "prefix", "") or ""),
            )


def served_routes(application) -> set[tuple[str, str]]:
    return set(_walk(application.routes))


SERVED = served_routes(app)
WRITES = {(m, p) for m, p in SERVED if m in UNSAFE_METHODS}


_UNSET = object()


def _declared(method: str, path: str) -> bool:
    rules = policy()
    return (
        rules.public.matches(method, path)
        or rules.self_service.matches(method, path)
        or path.startswith(rules.self_service_prefixes)
        or rules.object_checked.matches(method, path)
        or rules.gated.lookup(method, path, _UNSET) is not _UNSET
        or any(path.startswith(rule.prefix) for rule in rules.prefix_rules)
        or path.startswith(rules.admin_prefixes)
        or rules.admin_writes.matches(method, path)
    )


def _templates(routes: RouteSet) -> set[tuple[str, str]]:
    return {(m, p) for m, paths in routes.routes.items() for p in paths}


def test_every_write_is_declared_and_every_declaration_is_served():
    # The walk reached the included routers.
    assert len(SERVED) > 80
    assert {(m, p) for m, p in WRITES if not _declared(m, p)} == set()
    declared = (
        _templates(MIDENA_POLICY.public)
        | _templates(MIDENA_POLICY.self_service)
        | _templates(MIDENA_POLICY.object_checked)
        | _templates(MIDENA_POLICY.admin_exempt)
        | _templates(MIDENA_POLICY.admin_writes)
        | _templates(MIDENA_POLICY.token_reads)
        | set(MIDENA_POLICY.gated.entries)
    )
    assert declared - SERVED == set()


def test_the_check_notices_a_route_added_without_a_decision():
    probe = APIRouter()

    @probe.post("/v1/undeclared-probe")
    def _probe():  # pragma: no cover - refused before it runs
        return {"ran": True}

    app.include_router(probe)
    try:
        assert not _declared("POST", "/v1/undeclared-probe")
        client, _ = auth_client(role="admin")
        response = client.post("/v1/undeclared-probe", headers=csrf(client))
        assert response.status_code == 403
        assert response.json() == {"detail": "This route accepts no changes"}
    finally:
        app.router.routes.pop()


def test_signed_out_clients_reach_only_the_public_routes(client):
    anonymous = TestClient(peer_wrapper(app), base_url="https://testserver")
    rules = policy()
    for method, path in sorted(SERVED):
        if rules.public.matches(method, path) or method == "HEAD":
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        response = anonymous.request(
            method, concrete, json={}, headers={"Origin": "https://testserver"}
        )
        assert response.status_code in (401, 403), (method, path, response.status_code)


def test_the_administration_namespace_is_refused_before_its_routes(client):
    viewer, _ = auth_client(role="viewer")
    for method, path in sorted(SERVED):
        if not path.startswith("/v1/admin/") or method == "HEAD":
            continue
        if MIDENA_POLICY.admin_exempt.matches(method, path):
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        response = viewer.request(method, concrete, json={}, headers=csrf(viewer))
        assert response.status_code == 403, (method, path)
        assert response.json()["detail"] == "Admin role required"


def test_tags_are_written_by_administrators_only(client):
    viewer, _ = auth_client(role="contributor")
    for method, path in (("POST", "/v1/tags"), ("PATCH", "/v1/tags/1")):
        response = viewer.request(method, path, json={}, headers=csrf(viewer))
        assert response.json() == {"detail": "Admin role required"}, path


ID_PARAMS = sorted(
    (m, p) for m, p in SERVED if re.search(r"\{[a-z_]*_id\}", p) and m != "HEAD"
)


@pytest.mark.parametrize("value", [2**31, 2**63, 10**30, -1, 0, "not-an-id"])
def test_identifiers_beyond_the_database_range_are_refused_not_crashed(client, value):
    admin, _ = auth_client(role="admin")
    assert ID_PARAMS
    for method, path in ID_PARAMS:
        concrete = re.sub(r"\{[a-z_]*_id\}", str(value), path)
        concrete = re.sub(r"\{[^}]+\}", "x", concrete)
        response = admin.request(method, concrete, json={}, headers=csrf(admin))
        assert response.status_code < 500, (method, path, value, response.text)


@pytest.mark.parametrize(
    "params",
    [
        {"offset": 10**30},
        {"offset": -1},
        {"limit": 10**9},
        {"folder_id": 2**40},
        {"q": "x" * 5000},
    ],
)
def test_list_parameters_are_bounded(client, params):
    admin, _ = auth_client(role="admin")
    response = admin.get("/v1/diagrams", params=params)
    assert response.status_code == 422, response.text


def test_folder_ordering_is_bounded(client):
    admin, _ = auth_client(role="admin")
    response = admin.post(
        "/v1/folders", json={"name": "Deep", "sort_order": 2**40}, headers=csrf(admin)
    )
    assert response.status_code == 422
