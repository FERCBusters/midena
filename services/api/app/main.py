from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import anyio
from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import String
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.api.routes import router as api_router
from app.core.config import settings
from app.core.datetime_utils import utc_now_naive
from app.db.models import AuditLog, User
from app.db.session import SessionLocal
from app.realtime.notifications import hub
from app.security.auth import (
    create_user,
    get_current_user_from_headers_cookies,
    get_current_user_from_request,
    still_signed_in,
)
from app.security.client_addr import (
    allowance_address,
    request_client_address,
    socket_peer_trusted,
)
from app.security.csrf import (
    csrf_valid,
    generate_csrf_token,
    get_csrf_token_from_request,
    request_origin_allowed,
    session_csrf_token,
    set_csrf_cookie,
)
from app.security.headers import SecurityHeadersMiddleware
from app.security.local_allowance import LocalAllowance
from app.security.permissions import has_permission, seed_default_permissions
from app.security.redaction import redact_query_string
from app.security.request_limits import (
    RequestLimitMiddleware,
    validation_error_response,
)
from app.security.roles import ROLE_ADMIN, attach_effective_role, lock_admin_changes
from app.security.route_policy import (
    ACCOUNT,
    ADMIN,
    OBJECT,
    PUBLIC,
    UNSAFE_METHODS,
    audit_path,
    is_public,
    needs_admin,
    route_template,
    write_requirement,
)

log = logging.getLogger(__name__)


# The interactive API pages and the schema they read describe every route to
# whoever can reach the API, and the pages load their scripts from another
# site, so the application serves none of them.
def _bootstrap() -> None:
    """Seed idempotent data and the optional first administrator."""
    db = SessionLocal()
    try:
        seed_default_permissions(db)
    finally:
        db.close()
    bootstrap_initial_admin()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _bootstrap()
    yield


app = FastAPI(
    title=settings.app_title,
    lifespan=lifespan,
    exception_handlers={RequestValidationError: validation_error_response},
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_MAX_NOTIFICATION_SOCKETS_PER_USER = 8

# Requests without a signed-in account carry no identity, so each client
# address (each /64 network for IPv6) adds at most this many audit records a
# minute, whatever their status: refusals, and public routes such as signing
# in. Signed-in requests are always recorded. The same figure as KEEN's.
_ANONYMOUS_AUDIT_PER_MINUTE = 60
# WebSocket handshakes cost a session checkout and a user lookup each.
_WS_HANDSHAKES_PER_MINUTE = 30
_anonymous_audit = LocalAllowance(_ANONYMOUS_AUDIT_PER_MINUTE, 60)
_ws_handshakes = LocalAllowance(_WS_HANDSHAKES_PER_MINUTE, 60)

# Public read-only documents and pollers that anyone may fetch at any rate.
_UNAUDITED_PUBLIC_READS = frozenset({"/v1/system/health", "/v1/auth/methods"})
# Authorisation codes and state are single-use, but are still credentials
# while a sign-in is in progress; their values never reach the audit trail.
# (KEEN's rule: the callback is recorded, its credentials are not.)
_OAUTH_CALLBACK_TEMPLATES = frozenset(
    {"/v1/auth/oidc/callback", "/v1/auth/sso/{provider_key}/callback"}
)


class _TrustedProxySchemeMiddleware:
    """Trust X-Forwarded-Proto from a trusted socket peer only.

    Uvicorn's ProxyHeadersMiddleware cannot gate by CIDR networks and, when
    trusted broadly, lets any client rewrite the connection's peer address and
    scheme, so forwarded headers are handled here instead and the server's
    proxy-header rewriting must stay disabled.
    """

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and settings.trust_proxy_headers:
            client = scope.get("client") or (None, None)
            if client[0] and socket_peer_trusted(client[0]):
                proto = None
                for key, value in scope.get("headers") or []:
                    if key == b"x-forwarded-proto":
                        proto = value.decode("latin-1").strip().lower()
                        break
                if proto in ("http", "https"):
                    scope = dict(scope)
                    scope["scheme"] = proto
        await self.asgi_app(scope, receive, send)


def _refuse(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def _authenticate(request: Request, template: str | None) -> JSONResponse | None:
    """Attach the request's user, or return the response refusing the request.

    The account is loaded in a short-lived session that closes before the
    route runs, so no connection is held for the length of a request. The
    instance is detached: a route that changes it adds it to its own session.

    Deny by default (KEEN's model): a route not listed as public needs an
    account, a write to a route not listed in the write policy is refused,
    and the administration namespace needs the administrator role. Routes
    keep their own checks; these are the second lock.
    """
    method = request.method.upper()
    db = SessionLocal()
    try:
        user = get_current_user_from_request(request, db)
        if user is not None:
            # Loads every column, so the detached instance stays readable.
            role = attach_effective_role(db, user)
            request.state.audit_username = user.username
        if user is None:
            if is_public(method, template):
                return None
            return _refuse(401, "Not authenticated")
        if needs_admin(method, template) and role != ROLE_ADMIN:
            return _refuse(403, "Admin role required")
        if method in UNSAFE_METHODS:
            needed = write_requirement(method, template)
            if needed is None:
                return _refuse(403, "This route accepts no changes")
            if needed == ADMIN and role != ROLE_ADMIN:
                return _refuse(403, "Admin role required")
            if needed not in (PUBLIC, ACCOUNT, OBJECT, ADMIN) and not has_permission(
                db, user, needed
            ):
                return _refuse(403, f"{needed} permission required")
        db.expunge(user)
        request.state.user = user
        return None
    finally:
        db.close()


@app.middleware("http")
async def load_user_and_enforce_csrf(request: Request, call_next):
    template = route_template(request.app, request.scope)
    request.state.route_template = template
    # Database work runs in the thread pool, so one slow lookup never holds up
    # the requests the event loop is serving.
    refused = await run_in_threadpool(_authenticate, request, template)
    if refused is not None:
        return refused
    user = getattr(request.state, "user", None)

    if request.method.upper() in UNSAFE_METHODS:
        # A browser sends every write from MIDENA's own origin, including
        # writes before anyone is signed in (signing in, a second factor in
        # progress), which have no CSRF token to check.
        if not request_origin_allowed(request):
            return _refuse(403, "Request origin is not allowed")
        # Every signed-in write needs the token, whether the account came from
        # a session cookie or a trusted identity header.
        path = request.url.path or ""
        if user is not None and path != "/v1/auth/login" and not csrf_valid(request):
            return _refuse(403, "CSRF token missing or invalid")

    response = await call_next(request)

    # Browsers signed in by a trusted proxy get no MIDENA sign-in response to
    # carry the CSRF cookie, and a browser may lose the cookie before its
    # session ends; either receives a token with this response: the session's
    # own where there is a session.
    if user is not None and not get_csrf_token_from_request(request):
        try:
            set_csrf_cookie(
                response, session_csrf_token(request) or generate_csrf_token()
            )
        except Exception:
            pass
    return response


@app.middleware("http")
async def audit_trail_middleware(request: Request, call_next):
    """Persist a KEEN-style request audit trail for UI/API calls.

    The semantic before/after details of diagram and folder mutations are
    stored in entity_changelogs; this table records request metadata, status,
    duration and caller context.
    """

    path = request.url.path or ""
    if not path.startswith("/v1") or (
        request.method.upper() == "GET" and path in _UNAUDITED_PUBLIC_READS
    ):
        return await call_next(request)

    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        status_code = getattr(response, "status_code", 500)
        duration_ms = int((time.perf_counter() - start) * 1000)
        try:
            # Written in the thread pool, off the event loop, and kept even
            # when the client goes away before it is written.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(
                    _record_request, request, path, status_code, duration_ms
                )
        except Exception as error:
            # Audit logging must never break the request path. The loss is
            # logged without anything the request carried.
            log.warning(
                "A request audit record could not be written (%s)",
                type(error).__name__,
            )


def _referer_for_audit(value: str | None) -> str | None:
    """The page a request came from, as the audit trail keeps it: its query
    redacted like the request's own, its path's public tokens masked, and no
    fragment."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            audit_path(parts.path),
            redact_query_string(parts.query) or "",
            "",
        )
    )


def _record_request(
    request: Request, path: str, status_code: int, duration_ms: int
) -> None:
    username = getattr(request.state, "audit_username", None)
    client_ip = request_client_address(request)
    if username is None and not _anonymous_audit.allow(allowance_address(client_ip)):
        return

    template = getattr(request.state, "route_template", None)
    if template in _OAUTH_CALLBACK_TEMPLATES:
        query_string = "REDACTED" if request.url.query else None
    else:
        query_string = redact_query_string(request.url.query)
    if query_string and len(query_string) > 4096:
        query_string = query_string[:4096]

    user_agent = (request.headers.get("user-agent") or "").strip() or None
    referer = _referer_for_audit(request.headers.get("referer"))
    if user_agent and len(user_agent) > 256:
        user_agent = user_agent[:256]
    if referer and len(referer) > 512:
        referer = referer[:512]
    # Every value the caller chooses is cut to its column's width: one the
    # column refused would cost the whole record, and the request would be
    # served without a trace. (KEEN's rule.)
    columns = AuditLog.__table__.c
    method = request.method[: cast(String, columns.method.type).length]
    stored_path = audit_path(path)[: cast(String, columns.path.type).length]

    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                ts=utc_now_naive(),
                username=username,
                method=method,
                path=stored_path,
                query_string=query_string,
                status_code=int(status_code or 0),
                duration_ms=duration_ms,
                client_ip=client_ip,
                user_agent=user_agent,
                referer=referer,
            )
        )
        db.commit()
    finally:
        db.close()


def bootstrap_initial_admin() -> None:
    """Create the first administrator on an empty installation (KEEN's rule).

    MIDENA_BOOTSTRAP_ADMIN_USERNAME and MIDENA_BOOTSTRAP_ADMIN_PASSWORD are
    read only while the database holds no account at all, so a value left in
    the environment never creates or resets an account later. The password
    meets the rules every new password does, and never an example file's
    placeholder.
    """
    username = settings.bootstrap_admin_username.strip()
    password = settings.bootstrap_admin_password
    if not username and not password:
        return
    db = SessionLocal()
    try:
        # API processes start together; one creates the account while the
        # others wait, then find it.
        lock_admin_changes(db)
        if db.query(User.id).first() is not None:
            return
        if not username or not password:
            raise ValueError("Supply both bootstrap credentials")
        if _is_placeholder(password):
            raise ValueError("Replace the placeholder bootstrap password")
        create_user(
            db,
            username=username,
            password=password,
            email=settings.bootstrap_admin_email.strip() or None,
            role=ROLE_ADMIN,
        )
        log.warning("Bootstrapped the initial administrator account")
    except Exception:
        db.rollback()
        # Neither the password nor database diagnostics reach the log.
        raise RuntimeError(
            "Initial administrator creation failed; on an empty installation "
            "supply both MIDENA_BOOTSTRAP_ADMIN_USERNAME and "
            "MIDENA_BOOTSTRAP_ADMIN_PASSWORD (at least "
            f"{settings.password_min_length} characters, hard to guess, and never "
            "an example file's placeholder), and check database availability"
        ) from None
    finally:
        db.close()


def _is_placeholder(value: str) -> bool:
    """Whether a value is written as an example file's placeholder."""
    text = value.strip()
    return len(text) >= 2 and text.startswith("<") and text.endswith(">")


# How often an open notification socket asks whether it is still signed in.
_WS_RECHECK_SECONDS = 60.0


def _socket_still_signed_in(ws: WebSocket, user_id: int, peer: str | None) -> bool:
    db = SessionLocal()
    try:
        return still_signed_in(ws.headers, ws.cookies, db, user_id, socket_peer=peer)
    finally:
        db.close()


@app.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket):
    """WebSocket notifications endpoint.

    Uses the same authentication sources as HTTP requests (session cookie or
    the configured trusted identity header). The authentication database
    session is released as soon as the handshake completes; it never spans the
    idle lifetime of the connection.
    """

    # Cross-site WebSocket hijacking: browsers always send Origin, and it must
    # name MIDENA itself.
    if not request_origin_allowed(ws, require_origin=True):
        await ws.close(code=4403)
        return

    # Handshake attempts themselves are floodable work (one session checkout
    # and user lookup each), so each client address gets a small allowance
    # before the database is touched. Behind the proxy every socket peer is
    # the proxy itself, so the allowance counts the resolved client address.
    peer = getattr(getattr(ws, "client", None), "host", None)
    if not _ws_handshakes.allow(allowance_address(request_client_address(ws))):
        await ws.close(code=4429)
        return

    user = None
    db = SessionLocal()
    try:
        user = get_current_user_from_headers_cookies(
            ws.headers, ws.cookies, db, socket_peer=peer
        )
        if not user:
            await ws.close(code=4401)
            return

        if not await hub.connect_if_capacity(
            user.id, ws, _MAX_NOTIFICATION_SOCKETS_PER_USER
        ):
            user = None
            return
    finally:
        # Authentication work is done; the connection itself holds no session.
        db.close()

    if user is None:
        return

    try:
        # The socket was authenticated once, at its handshake. A sign-out,
        # password change, expiry or deactivation since then ends it, as it
        # ends the session's requests. The check follows the clock, not the
        # client's silence: frames from the client do not put it off.
        checked = time.monotonic()
        while True:
            wait = _WS_RECHECK_SECONDS - (time.monotonic() - checked)
            if wait > 0:
                # Keep the socket alive and detect disconnects. Client text
                # is ignored; the server bounds the size of each frame.
                try:
                    _ = await asyncio.wait_for(ws.receive_text(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                continue
            still = await run_in_threadpool(_socket_still_signed_in, ws, user.id, peer)
            if not still:
                await ws.close(code=4401)
                break
            checked = time.monotonic()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await hub.disconnect(user.id, ws)


@app.get("/")
def root():
    return {"ok": True, "service": "midena-api"}


app.include_router(api_router)

# Byte, shape, target and cookie limits apply before any middleware reads the
# request.
app.add_middleware(RequestLimitMiddleware)

# Response policy also covers refusals from every inner middleware (KEEN's).
app.add_middleware(SecurityHeadersMiddleware)

# Outermost, so every middleware and route sees the forwarded scheme.
if settings.trust_proxy_headers:
    app.add_middleware(_TrustedProxySchemeMiddleware)
