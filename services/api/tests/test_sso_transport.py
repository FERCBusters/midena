"""Identity providers are reached through a bounded transport: answers are read
uncompressed, at most 1 MiB, within a deadline, with no redirects and no proxy
settings from the environment. (KEEN's transport and its test.)"""

import asyncio
import re
from pathlib import Path

import httpx2
import pytest
from app.security import sso_http
from app.security.sso_http import MAX_RESPONSE_BYTES, SsoTransport, client_options


class Body(httpx2.AsyncByteStream):
    """A provider response body that arrives in chunks."""

    def __init__(self, size):
        self.size, self.closed = size, False

    async def __aiter__(self):
        remaining = self.size
        while remaining:
            chunk = min(64 * 1024, remaining)
            remaining -= chunk
            yield b"x" * chunk

    async def aclose(self):
        self.closed = True


def _fetch(provider, url="https://idp.example/jwks", **params):
    async def fetch():
        options = client_options()
        transport = options.pop("transport")
        await transport.transport.aclose()
        transport.transport = httpx2.MockTransport(provider)
        async with httpx2.AsyncClient(transport=transport, **options) as client:
            response = await client.get(url, params=params)
            return response

    return asyncio.run(fetch())


def test_identity_provider_responses_are_read_through_the_size_limit():
    sent, bodies = [], []

    def provider(request):
        sent.append(request.headers["accept-encoding"])
        bodies.append(Body(int(request.url.params["size"])))
        return httpx2.Response(200, stream=bodies[-1])

    assert _fetch(provider, size=MAX_RESPONSE_BYTES).content == (
        b"x" * MAX_RESPONSE_BYTES
    )
    with pytest.raises(ValueError, match="^Identity provider response exceeds 1 MiB$"):
        _fetch(provider, size=MAX_RESPONSE_BYTES + 1)
    assert sent == ["identity", "identity"]
    # The body is closed whether it was read whole or refused part-way.
    assert [body.closed for body in bodies] == [True, True]


def test_a_compressed_answer_is_refused_before_it_is_read():
    body = Body(16)

    def provider(request):
        return httpx2.Response(200, headers={"Content-Encoding": "gzip"}, stream=body)

    with pytest.raises(ValueError, match="must honour Accept-Encoding: identity"):
        _fetch(provider)
    assert body.closed


def test_a_redirect_is_returned_and_never_followed():
    seen = []

    def provider(request):
        seen.append(str(request.url))
        return httpx2.Response(302, headers={"Location": "http://169.254.169.254/"})

    response = _fetch(provider)
    assert response.status_code == 302
    assert seen == ["https://idp.example/jwks"]


def test_a_provider_past_its_deadline_is_abandoned(monkeypatch):
    monkeypatch.setattr(sso_http, "REQUEST_SECONDS", 0.05)

    class Slow(httpx2.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(1)
            yield b"late"

        async def aclose(self):
            pass

    def provider(request):
        return httpx2.Response(200, stream=Slow())

    with pytest.raises(TimeoutError):
        _fetch(provider)


def test_the_client_options_ignore_the_environment_and_verify_tls():
    options = client_options()
    assert options["verify"] is True
    assert options["trust_env"] is False
    assert options["follow_redirects"] is False
    assert isinstance(options["transport"], SsoTransport)
    asyncio.run(options["transport"].aclose())


def _app_sources() -> dict[str, str]:
    app_root = Path(__file__).resolve().parents[1] / "app"
    return {
        str(path.relative_to(app_root)): path.read_text()
        for path in app_root.rglob("*.py")
    }


def test_every_identity_provider_client_uses_the_bounded_transport():
    """A client built without these options would follow redirects, honour
    proxy variables and read an answer of any size."""
    call = re.compile(r"\b(?:AsyncClient|AsyncOAuth2Client)\(")

    def unbounded(text: str) -> bool:
        for found in call.finditer(text):
            depth, end = 1, found.end()
            while depth and end < len(text):
                depth += {"(": 1, ")": -1}.get(text[end], 0)
                end += 1
            if "**client_options()" not in text[found.end() : end]:
                return True
        return False

    homes = {"security/oidc.py", "security/sso_emails.py"}

    def offenders(sources: dict[str, str]) -> list[str]:
        return sorted(
            name for name, text in sources.items() if name in homes and unbounded(text)
        )

    assert offenders(_app_sources()) == []
    copy = "async with httpx.AsyncClient(timeout=10.0) as client:"
    assert offenders({"security/oidc.py": copy}) == ["security/oidc.py"]


def test_tokens_are_signed_and_verified_with_joserfc_only():
    """authlib's own JOSE module is deprecated and admits any algorithm the
    token names unless told otherwise; one library keeps one policy."""

    def offenders(sources: dict[str, str]) -> list[str]:
        return sorted(name for name, text in sources.items() if "authlib.jose" in text)

    assert offenders(_app_sources()) == []
    assert offenders({"x.py": "from authlib.jose import jwt"}) == ["x.py"]


def test_stored_times_come_from_one_helper():
    """``datetime.utcnow`` is deprecated; stored times share one source."""
    pattern = re.compile(r"\butcnow\b")

    def offenders(sources: dict[str, str]) -> list[str]:
        return sorted(name for name, text in sources.items() if pattern.search(text))

    assert offenders(_app_sources()) == []
    assert offenders({"x.py": "now = datetime.utcnow()"}) == ["x.py"]
