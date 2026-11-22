"""Which requests may proceed without an account, and what each write needs.

KEEN's deny-by-default model, adapted to MIDENA's routes. The authentication
middleware refuses a request with no signed-in account unless its route is
listed in PUBLIC_ROUTES; it refuses a write (POST, PUT, PATCH, DELETE) whose
route is not listed in WRITE_POLICY, so a route added without a decision
about who may call it is refused rather than open. Each listed write states
the coarse authority the middleware checks before the route runs:

- ``PUBLIC``: the route itself decides (signing in, second-factor ceremonies,
  signing out); it runs whether or not anyone is signed in.
- ``ACCOUNT``: any signed-in account acting on its own records.
- ``ADMIN``: the administrator role.
- ``OBJECT``: any signed-in account; the route authorises the named object
  (its owner, the lock holder, a comment's author) and refuses everyone else.
- a permission code: the account must hold it; the route still checks the
  object (ownership, sharing, locks).

The route keeps its own checks in every case: this table is the second lock,
not the only one. tests/test_route_policy.py fails when a route is missing
from the table or the table names a route that does not exist.
"""

from __future__ import annotations

import re

from starlette.routing import Match

from app.security.permissions import (
    PERM_DIAGRAM_COMMENT,
    PERM_DIAGRAM_EXPORT,
    PERM_DIAGRAM_WRITE,
    PERM_FOLDER_MANAGE,
)

PUBLIC = "public"
ACCOUNT = "account"
ADMIN = "admin"
OBJECT = "object"

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes reachable without a signed-in account, by path template. Each answers
# for itself: sign-in flows hold their own state, public diagram routes check
# the diagram's public token and feature switch, and the checks answer 401.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/v1/system/health"),
        ("GET", "/v1/auth/methods"),
        ("POST", "/v1/auth/login"),
        ("GET", "/v1/auth/oidc/start"),
        ("GET", "/v1/auth/oidc/callback"),
        ("GET", "/v1/auth/sso/{provider_key}/start"),
        ("GET", "/v1/auth/sso/{provider_key}/callback"),
        ("POST", "/v1/auth/logout"),
        ("GET", "/v1/auth/logout"),
        ("GET", "/v1/auth/check"),
        ("GET", "/v1/auth/check-admin"),
        # Second-factor ceremonies run on a pending challenge, which outlives
        # the sessions an enrolment change ends; each step re-decides its
        # stage, origin and allowances itself (app/api/routes/mfa.py).
        ("POST", "/v1/auth/mfa/manage/start"),
        ("POST", "/v1/auth/mfa/state"),
        ("POST", "/v1/auth/mfa/verify-code"),
        ("POST", "/v1/auth/mfa/totp/start"),
        ("POST", "/v1/auth/mfa/totp/confirm"),
        ("POST", "/v1/auth/mfa/webauthn/options"),
        ("POST", "/v1/auth/mfa/webauthn/verify"),
        ("POST", "/v1/auth/mfa/webauthn/register-options"),
        ("POST", "/v1/auth/mfa/webauthn/register"),
        ("POST", "/v1/auth/mfa/remove"),
        ("POST", "/v1/auth/mfa/recovery/regenerate"),
        ("POST", "/v1/auth/mfa/finish"),
        ("POST", "/v1/auth/mfa/cancel"),
        # Public diagrams: the diagram's own public token is the credential.
        ("GET", "/v1/public/diagrams/{diagram_uuid}/{public_token}"),
        ("GET", "/v1/public/diagrams/{diagram_uuid}/{public_token}/source"),
        ("GET", "/v1/public/diagrams/{diagram_uuid}/{public_token}/svg"),
    }
)

WRITE_POLICY: dict[tuple[str, str], str] = {
    # Sign-in, second factor and sign-out decide for themselves.
    **{key: PUBLIC for key in PUBLIC_ROUTES if key[0] in UNSAFE_METHODS},
    ("POST", "/v1/auth/change-password"): ACCOUNT,
    ("POST", "/v1/me/sso-emails/request"): ACCOUNT,
    ("POST", "/v1/me/sso-emails/confirm"): ACCOUNT,
    ("POST", "/v1/me/sso-emails/remove"): ACCOUNT,
    ("PUT", "/v1/me/preferences"): ACCOUNT,
    ("POST", "/v1/me/shortcuts"): ACCOUNT,
    ("DELETE", "/v1/me/shortcuts/{shortcut_id}"): ACCOUNT,
    # Folders and tags.
    ("POST", "/v1/folders"): PERM_FOLDER_MANAGE,
    ("PATCH", "/v1/folders/{folder_id}"): PERM_FOLDER_MANAGE,
    ("DELETE", "/v1/folders/{folder_id}"): PERM_FOLDER_MANAGE,
    ("POST", "/v1/tags"): ADMIN,
    ("PATCH", "/v1/tags/{tag_id}"): ADMIN,
    # Diagrams.
    ("POST", "/v1/diagram-ai/generate"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/ai/generate"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/clone"): PERM_DIAGRAM_WRITE,
    ("PATCH", "/v1/diagrams/{diagram_ref}"): PERM_DIAGRAM_WRITE,
    ("DELETE", "/v1/diagrams/{diagram_ref}"): OBJECT,
    ("POST", "/v1/diagrams/{diagram_ref}/save"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/lock"): PERM_DIAGRAM_WRITE,
    ("DELETE", "/v1/diagrams/{diagram_ref}/lock"): OBJECT,
    ("POST", "/v1/diagrams/{diagram_ref}/comments"): PERM_DIAGRAM_COMMENT,
    ("PATCH", "/v1/comments/{comment_id}"): OBJECT,
    ("DELETE", "/v1/comments/{comment_id}"): OBJECT,
    ("POST", "/v1/diagrams/{diagram_ref}/entity-links"): PERM_DIAGRAM_WRITE,
    ("DELETE", "/v1/entity-links/{link_id}"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/metadata-links"): PERM_DIAGRAM_WRITE,
    ("DELETE", "/v1/metadata-links/{link_id}"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/shares"): OBJECT,
    ("DELETE", "/v1/diagram-shares/{share_id}"): OBJECT,
    ("POST", "/v1/diagrams/{diagram_ref}/export/google-drive"): PERM_DIAGRAM_EXPORT,
}

# Every route under /v1/admin/ needs the administrator role at the middleware,
# except the audit readers, which the audittrail.read permission also opens
# and whose routes check it.
_ADMIN_PREFIX = "/v1/admin/"
_AUDIT_READERS = frozenset(
    {("GET", "/v1/admin/audit"), ("GET", "/v1/admin/entity-changelog")}
)
# A public diagram's token in any of the addresses that carry one: the API's
# public routes, the public page and the embed page.
_PUBLIC_DIAGRAM_PATH = re.compile(
    r"((?:/v1)?/public/diagrams/[^/]+/|/embed/[^/]+/)[^/.]+"
)


def _leaf_routes(routes) -> list:
    """Every route the application serves, included routers flattened.

    FastAPI keeps an included router as one entry that it expands when it
    routes, so its routes are reached through ``original_router``. MIDENA's
    routes carry their whole path; an include with a prefix would make a
    route's own template differ from the path it answers, so it is refused
    here rather than silently missed.
    """
    leaves = []
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            if route.include_context.prefix:
                raise RuntimeError("route_policy expects routers without a prefix")
            leaves.extend(_leaf_routes(inner.routes))
        else:
            leaves.append(route)
    return leaves


_LEAVES: dict[int, list] = {}


def route_template(app, scope) -> str | None:
    """The path template of the route a request reaches, or None."""
    leaves = _LEAVES.get(id(app))
    if leaves is None:
        leaves = _LEAVES[id(app)] = _leaf_routes(app.router.routes)
    for route in leaves:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "path", None)
    return None


def served_routes(app) -> list[tuple[str, str]]:
    """(method, template) for every HTTP route, for the policy's own test."""
    pairs = []
    for route in _leaf_routes(app.router.routes):
        for method in sorted(getattr(route, "methods", None) or ()):
            pairs.append((method, route.path))
    return pairs


def is_public(method: str, template: str | None) -> bool:
    # HEAD is answered by the GET route.
    verb = "GET" if method == "HEAD" else method
    return template is not None and (verb, template) in PUBLIC_ROUTES


def write_requirement(method: str, template: str | None) -> str | None:
    """What a write to this route needs, or None when it is not declared."""
    if template is None:
        return None
    if template.startswith(_ADMIN_PREFIX):
        # The administration namespace is administrators' throughout.
        return ADMIN
    return WRITE_POLICY.get((method, template))


def needs_admin(method: str, template: str | None) -> bool:
    if template is None or not template.startswith(_ADMIN_PREFIX):
        return False
    return (method, template) not in _AUDIT_READERS


def audit_path(path: str) -> str:
    """A request path as the audit trail keeps it: a public diagram's token,
    which grants read access to anyone holding it, is masked."""
    return _PUBLIC_DIAGRAM_PATH.sub(r"\1REDACTED", path)
