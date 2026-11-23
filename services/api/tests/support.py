"""Shared builders for API tests: signed-in clients and diagram data.

Data a user enters goes through the API; rows are written directly only for
state the application itself produces (sessions, locks past their expiry).
"""

from __future__ import annotations

from app.db.models import Group, Permission, User, user_groups
from app.db.session import SessionLocal
from mosp.security.permissions import bump_authz_versions

from tests.conftest import ROLE_PERMISSIONS, auth_client

BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  id="Definitions_1" targetNamespace="https://example.com/bpmn">
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1" name="Start" />
  </bpmn:process>
</bpmn:definitions>"""

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<g id="StartEvent_1"><rect width="5" height="5" fill="#fff"/>'
    "<text>Start</text></g></svg>"
)

FLOWCHART = 'flowchart LR\n    A["Start"] --> B["End"]\n'
SEQUENCE = "sequenceDiagram\n    User->>MIDENA: Open\n"


def csrf(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("__Host-midena_csrf") or ""}


def signed_in(role: str = "admin", *, email: str | None = None):
    """A signed-in client and its user id."""
    client, user = auth_client(role=role)
    if email is not None:
        with SessionLocal() as s:
            s.get(User, user.id).email = email
            s.commit()
    return client, user.id


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def make_group(name: str, *, role: str | None = None, members=()):
    """A group with mosp's role (admin or normal), or one of MIDENA's former
    role names given as the permissions it held."""
    codes = ROLE_PERMISSIONS.get(role or "", ())
    if role in ROLE_PERMISSIONS:
        role = "normal"
    with SessionLocal() as s:
        group = Group(name=name, role=role)
        group.permissions = s.query(Permission).filter(Permission.code.in_(codes)).all()
        s.add(group)
        s.flush()
        for user_id in members:
            s.execute(user_groups.insert().values(user_id=user_id, group_id=group.id))
        # As the administration routes do: members' sessions pick up the change.
        bump_authz_versions(s, list(members))
        s.commit()
        return group.id


def make_diagram(client, name: str = "Order flow", **fields) -> dict:
    body = {"name": name, "diagram_type": "bpmn", "bpmn_xml": BPMN, **fields}
    return ok(client.post("/v1/diagrams", json=body, headers=csrf(client)))


def make_flowchart(client, name: str = "Flow", **fields) -> dict:
    body = {
        "name": name,
        "diagram_type": "flowchart",
        "flowchart_text": FLOWCHART,
        "svg_xml": SVG,
        **fields,
    }
    return ok(client.post("/v1/diagrams", json=body, headers=csrf(client)))


def share(client, diagram_uuid: str, identifier: str, role: str = "viewer") -> dict:
    return ok(
        client.post(
            f"/v1/diagrams/{diagram_uuid}/shares",
            json={"identifier": identifier, "role": role, "notify": False},
            headers=csrf(client),
        )
    )
