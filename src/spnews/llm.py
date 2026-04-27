"""Thin wrapper around OpenAI-compatible LLM APIs."""

from __future__ import annotations

import httpx

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_TIMEOUT = httpx.Timeout(240, connect=10)


def _chat_completions_url() -> str:
    base_url = LLM_BASE_URL.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    return headers


def _request_payload(prompt: str, temperature: float) -> dict:
    return {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }


def _extract_message_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM response missing choices")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type", "text") == "text"
        ]
        if text_parts:
            return "".join(text_parts)

    raise ValueError("LLM response missing message content")


def chat(prompt: str, temperature: float = 0.7) -> str:
    """Send a single-turn chat completion and return the text."""
    resp = httpx.post(
        _chat_completions_url(),
        headers=_request_headers(),
        json=_request_payload(prompt, temperature),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return _extract_message_text(resp.json())
