from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class DiagramAIError(RuntimeError):
    """Raised when the configured OpenAI-compatible provider cannot generate code."""


def _configured_base_url() -> str:
    base = str(getattr(settings, "ai_api_base_url", "") or "").strip().rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DiagramAIError("MIDENA_AI_API_BASE_URL must be an absolute http(s) URL")
    return base


def ai_is_configured() -> bool:
    if not bool(getattr(settings, "ai_enabled", True)):
        return False
    return bool(
        str(getattr(settings, "ai_api_key", "") or "").strip()
        and str(getattr(settings, "ai_model", "") or "").strip()
        and str(getattr(settings, "ai_api_base_url", "") or "").strip()
    )


def ai_status() -> dict[str, Any]:
    configured = ai_is_configured()
    return {
        "enabled": configured,
        "model": str(getattr(settings, "ai_model", "") or "") if configured else None,
        "provider": "OpenAI-compatible",
        "base_url_configured": bool(
            str(getattr(settings, "ai_api_base_url", "") or "").strip()
        ),
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


def _strip_markdown_fence(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    fenced = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)```", value, flags=re.S)
    if fenced:
        return fenced.group(1).strip()
    # Some models still prefix a single sentence. Keep the first plausible
    # Mermaid directive and everything after it rather than returning prose.
    directive = re.search(
        r"(?im)^\s*(sequenceDiagram|flowchart\s+\w+|graph\s+\w+)\b", value
    )
    if directive and directive.start() > 0:
        value = value[directive.start() :]
    return value.strip()


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
    if not ai_is_configured():
        raise DiagramAIError(
            "AI diagram generation is not configured. Set MIDENA_AI_API_KEY and MIDENA_AI_MODEL."
        )
    base = _configured_base_url()
    api_key = str(getattr(settings, "ai_api_key", "") or "").strip()
    model = str(getattr(settings, "ai_model", "") or "").strip()
    timeout_seconds = max(
        5, min(int(getattr(settings, "ai_timeout_seconds", 45) or 45), 120)
    )
    max_tokens = max(
        256, min(int(getattr(settings, "ai_max_tokens", 2500) or 2500), 12000)
    )
    temperature = float(getattr(settings, "ai_temperature", 0.2) or 0.2)
    request_body: dict[str, Any] = {
        "model": model,
        "messages": _normalised_messages(
            diagram_type=diagram_type, messages=messages, current_source=current_source
        ),
        "temperature": max(0.0, min(temperature, 1.0)),
        "max_tokens": max_tokens,
    }
    url = f"{base}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise DiagramAIError(
            "The AI provider timed out while generating the diagram."
        ) from exc
    except httpx.HTTPError as exc:
        raise DiagramAIError("The AI provider could not be reached.") from exc

    if response.status_code >= 400:
        detail = ""
        try:
            data = response.json()
            err = data.get("error") if isinstance(data, dict) else None
            detail = str(
                err.get("message") if isinstance(err, dict) else data.get("detail", "")
            )
        except Exception:
            detail = response.text[:300]
        suffix = f": {detail}" if detail else ""
        raise DiagramAIError(
            f"The AI provider returned HTTP {response.status_code}{suffix}"
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise DiagramAIError(
            "The AI provider returned an unexpected response shape."
        ) from exc
    code = _strip_markdown_fence(str(content or ""))
    if not code:
        raise DiagramAIError("The AI provider returned an empty diagram.")
    return code
