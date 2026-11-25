"""MIDENA's routes in mosp's route policy (mosp.security.route_policy).

mosp declares its own routes (signing in and out, second factors, single
sign-on, the account's own password and SSO addresses); this module declares
MIDENA's, and mosp applies the two together. MIDENA closes every write it does
not declare (``refuse_undeclared_writes``): a route added without a decision
about who may call it is refused for everyone, administrators included.

- public: reached without an account; each answers for itself (public
  diagrams check their token and feature switch).
- self-service: the signed-in account acting on its own records.
- object-checked: any signed-in account; the route authorises the named
  object (its owner, the lock holder, a comment's author).
- gated: the account must hold the permission; the route still checks the
  object (ownership, sharing, locks).
- admin writes and the /v1/admin/ namespace: the administrator role, apart
  from the audit readers, which the audittrail.read permission also opens and
  whose routes check it. API tokens are issued and revoked there.
- token reads: the only routes an API token reaches, as its account.

Routes keep their own checks in every case: this table is the second lock.
tests/test_route_policy.py fails when a write is undeclared or a declaration
names a route that does not exist.
"""

from __future__ import annotations

from mosp.security.regex import scan_pattern
from mosp.security.route_policy import RouteCodes, RoutePolicy, RouteSet

from app.security.permissions import (
    PERM_DIAGRAM_COMMENT,
    PERM_DIAGRAM_EXPORT,
    PERM_DIAGRAM_WRITE,
    PERM_FOLDER_MANAGE,
)

PUBLIC_ROUTES = RouteSet(
    {
        "GET": (
            "/",
            "/v1/system/health",
            # Public diagrams: the diagram's own public token is the
            # credential.
            "/v1/public/diagrams/{diagram_uuid}/{public_token}",
            "/v1/public/diagrams/{diagram_uuid}/{public_token}/source",
            "/v1/public/diagrams/{diagram_uuid}/{public_token}/svg",
        )
    }
)

GATED_WRITES = {
    # Folders.
    ("POST", "/v1/folders"): PERM_FOLDER_MANAGE,
    ("PATCH", "/v1/folders/{folder_id}"): PERM_FOLDER_MANAGE,
    ("DELETE", "/v1/folders/{folder_id}"): PERM_FOLDER_MANAGE,
    # Diagrams.
    ("POST", "/v1/diagram-ai/generate"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/ai/generate"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/clone"): PERM_DIAGRAM_WRITE,
    ("PATCH", "/v1/diagrams/{diagram_ref}"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/save"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/lock"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/comments"): PERM_DIAGRAM_COMMENT,
    ("POST", "/v1/diagrams/{diagram_ref}/entity-links"): PERM_DIAGRAM_WRITE,
    ("DELETE", "/v1/entity-links/{link_id}"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/metadata-links"): PERM_DIAGRAM_WRITE,
    ("DELETE", "/v1/metadata-links/{link_id}"): PERM_DIAGRAM_WRITE,
    ("POST", "/v1/diagrams/{diagram_ref}/export/google-drive"): PERM_DIAGRAM_EXPORT,
}

OBJECT_CHECKED = RouteSet(
    {
        "DELETE": (
            "/v1/diagrams/{diagram_ref}",
            "/v1/diagrams/{diagram_ref}/lock",
            "/v1/comments/{comment_id}",
            "/v1/diagram-shares/{share_id}",
        ),
        "PATCH": ("/v1/comments/{comment_id}",),
        "POST": ("/v1/diagrams/{diagram_ref}/shares",),
    }
)

SELF_SERVICE = RouteSet(
    {
        "PUT": ("/v1/me/preferences",),
        "POST": ("/v1/me/shortcuts",),
        "DELETE": ("/v1/me/shortcuts/{shortcut_id}",),
    }
)

ADMIN_WRITES = RouteSet({"POST": ("/v1/tags",), "PATCH": ("/v1/tags/{tag_id}",)})

# The reads an API token may make (mosp.security.api_tokens): listing and
# opening diagrams, which apply the token's account's visibility as they do
# for a browser. A token reaches no other route.
TOKEN_READS = RouteSet({"GET": ("/v1/diagrams", "/v1/diagrams/{diagram_ref}")})

MIDENA_POLICY = RoutePolicy(
    public=PUBLIC_ROUTES,
    self_service=SELF_SERVICE,
    object_checked=OBJECT_CHECKED,
    gated=RouteCodes(GATED_WRITES),
    admin_prefixes=("/v1/admin/",),
    admin_exempt=RouteSet({"GET": ("/v1/admin/audit", "/v1/admin/entity-changelog")}),
    admin_writes=ADMIN_WRITES,
    refuse_undeclared_writes=True,
    token_reads=TOKEN_READS,
    unaudited_public_reads=frozenset({"/v1/system/health"}),
)

# A public diagram's token in any of the addresses that carry one: the API's
# public routes, the public page and the embed page.
_PUBLIC_DIAGRAM_PATH = scan_pattern(
    r"((?:/v1)?/public/diagrams/[^/]+/|/embed/[^/]+/)[^/.]+"
)


def audit_path(path: str) -> str:
    """A path as the audit trail keeps it: a public diagram's token, which
    grants read access to anyone holding it, is masked."""
    return _PUBLIC_DIAGRAM_PATH.sub(r"\1REDACTED", path)
