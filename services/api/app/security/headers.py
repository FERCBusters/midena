"""Response policy for every API answer, refusals from middleware included.

Ported from KEEN's ``app/security/headers.py``. The supplied nginx adds its
own set only where the API set none, so these hold however the API is
reached.
"""

from app.core.config import settings


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secured(message):
            if message["type"] == "http.response.start":
                policy = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-origin",
                    b"x-permitted-cross-domain-policies": b"none",
                    b"permissions-policy": b"geolocation=(), microphone=(), camera=()",
                    b"cache-control": b"no-store",
                }
                if settings.cookie_secure:
                    policy[b"strict-transport-security"] = b"max-age=31536000"
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in policy
                ]
                # API answers are data, never documents: a response that sets
                # no policy of its own gets one that runs nothing.
                if not any(k.lower() == b"content-security-policy" for k, _ in headers):
                    headers.append(
                        (
                            b"content-security-policy",
                            b"default-src 'none'; frame-ancestors 'none'; sandbox",
                        )
                    )
                message = {**message, "headers": headers + list(policy.items())}
            await send(message)

        await self.app(scope, receive, secured)
