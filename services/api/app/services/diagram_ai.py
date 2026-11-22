from __future__ import annotations

import json
import logging
from typing import Any

import httpx2 as httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class DiagramAIError(RuntimeError):
    """Raised when the configured OpenAI-compatible provider cannot generate code."""


# The provider's answer is one chat completion; a diagram is a few kilobytes.
_MAX_ANSWER_BYTES = 1024 * 1024


def ai_is_configured() -> bool:
    return bool(
        settings.ai_api_key.strip()
        and settings.ai_model.strip()
        and settings.ai_api_base_url.strip()
    )


def ai_status() -> dict[str, Any]:
    configured = ai_is_configured()
    return {
        "enabled": configured,
        "model": settings.ai_model if configured else None,
        "provider": "OpenAI-compatible",
    }


def _diagram_instructions(diagram_type: str) -> str:
    if diagram_type == "sequence":
        return """
Generate Mermaid-compatible sequence diagram source for MIDENA.
Return only diagram source code, with no Markdown fences, prose, heading, explanation, or comments outside the syntax.
Prefer this shape:
sequenceDiagram
    participant User
    participant System
    User->>System: Message
    System-->>User: Response
Use valid Mermaid sequence constructs such as participant, actor, note over, loop, alt/else/end, opt/end, and message arrows.
Do not include HTML, JavaScript, XML, SVG, external links, or unsafe markup.
""".strip()
    return """
Generate Mermaid-compatible flowchart source for MIDENA.
Return only diagram source code, with no Markdown fences, prose, heading, explanation, or comments outside the syntax.
The first non-empty line must be a Mermaid flowchart or graph directive, preferably: flowchart LR or flowchart TD.
Use quoted node labels when labels contain punctuation or spaces, for example A["Review request"].
Use clear node IDs and edges such as A --> B, B -->|Approved| C, and B -->|Rejected| D.
Do not include HTML, JavaScript, XML, SVG, external links, or unsafe markup.
""".strip()


# A diagram's source is a few thousand characters; an answer is cut to this
# before it is read, so the scanning below has a fixed budget.
_MAX_CONTENT_CHARS = 200_000
_DIRECTIVES = ("sequencediagram", "flowchart", "graph")


def _strip_markdown_fence(text: str) -> str:
    """The diagram source in a model's answer.

    Linear in the answer's length: the provider's text is shaped by prompts
    users write, so it is scanned with plain searches, never a backtracking
    pattern.
    """
    value = text[:_MAX_CONTENT_CHARS].strip()
    if not value:
        return ""
    start = value.find("```")
    if start >= 0:
        # Skip the info string (a language name) on the opening fence's line.
        body_start = value.find("\n", start + 3)
        if body_start >= 0:
            end = value.find("```", body_start)
            if end >= 0:
                return value[body_start + 1 : end].strip()
    # Some models still prefix a sentence. Keep the first line that starts a
    # Mermaid directive and everything after it rather than returning prose.
    offset = 0
    for line in value.splitlines(keepends=True):
        if line.strip().lower().startswith(_DIRECTIVES):
            return value[offset:].strip()
        offset += len(line)
    return value


def _normalised_messages(
    *, diagram_type: str, messages: list[dict[str, str]], current_source: str | None
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = [
        {"role": "system", "content": _diagram_instructions(diagram_type)}
    ]
    source = str(current_source or "").strip()
    if source:
        out.append(
            {
                "role": "user",
                "content": (
                    "The current editor source is below. Use it as context when the user asks "
                    "for a refinement; otherwise replace it with a complete improved diagram.\n\n"
                    f"```\n{source[:12000]}\n```"
                ),
            }
        )
    for msg in messages[-16:]:
        role = str(msg.get("role") or "").strip().lower()
        content = str(msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        out.append({"role": role, "content": content})
    return out


async def generate_diagram_code(
    *,
    diagram_type: str,
    messages: list[dict[str, str]],
    current_source: str | None = None,
) -> str:
    """Ask the configured provider for diagram source.

    The base URL is HTTPS (config refuses anything else outside localhost),
    redirects are not followed, the answer is read up to a fixed size, and no
    part of a refusal from the provider reaches the browser: provider errors
    can quote the request, the key's account or internal detail.
    """
    if not ai_is_configured():
        raise DiagramAIError("AI diagram generation is not configured.")
    request_body: dict[str, Any] = {
        "model": settings.ai_model.strip(),
        "messages": _normalised_messages(
            diagram_type=diagram_type, messages=messages, current_source=current_source
        ),
        "temperature": settings.ai_temperature,
        "max_tokens": settings.ai_max_tokens,
    }
    url = f"{settings.ai_api_base_url.rstrip('/')}/chat/completions"
    body = b""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ai_timeout_seconds),
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {settings.ai_api_key.strip()}",
                    "Accept": "application/json",
                },
                json=request_body,
            ) as response:
                status = response.status_code
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > _MAX_ANSWER_BYTES:
                        raise DiagramAIError(
                            "The AI provider returned an unexpectedly large answer."
                        )
    except httpx.TimeoutException as exc:
        raise DiagramAIError(
            "The AI provider timed out while generating the diagram."
        ) from exc
    except httpx.HTTPError as exc:
        raise DiagramAIError("The AI provider could not be reached.") from exc

    if status != 200:
        log.warning("AI provider answered HTTP %s", status)
        raise DiagramAIError(f"The AI provider refused the request (HTTP {status}).")
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise DiagramAIError(
            "The AI provider returned an unexpected response shape."
        ) from exc
    if not isinstance(content, str):
        raise DiagramAIError("The AI provider returned an unexpected response shape.")
    code = _strip_markdown_fence(content)
    if not code:
        raise DiagramAIError("The AI provider returned an empty diagram.")
    return code
