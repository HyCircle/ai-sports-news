"""Async OpenAI-compatible Chat and Embedding clients with retries and metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Self, TypeVar

import httpx
import numpy as np
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("spnews.llm")

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass
class UsageStats:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    elapsed_s: float = 0.0

    def record(self, usage: dict[str, Any] | None, elapsed: float) -> None:
        self.calls += 1
        self.elapsed_s += elapsed
        if usage:
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
            self.total_tokens += int(usage.get("total_tokens") or 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "elapsed_s": round(self.elapsed_s, 2),
        }


def _endpoint(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    if base.endswith("/v1"):
        return f"{base}{suffix}"
    return f"{base}/v1{suffix}"


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else text[3:]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"LLM response missing choices: {str(data)[:200]}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type", "text") == "text"
        ]
        if parts:
            return "".join(parts)
    raise ValueError("LLM response missing message content")


def truncate_and_normalize(vec: list[float], dim: int) -> np.ndarray:
    """Slice to MRL target dimension and L2-normalize into float32."""
    if len(vec) < dim:
        raise ValueError(f"Embedding dimension {len(vec)} < required {dim}")
    arr = np.asarray(vec[:dim], dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        raise ValueError("Received zero-norm embedding vector")
    return arr / norm


class ChatClient:
    """Async OpenAI-compatible Chat Completions client."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        concurrency: int = 6,
        timeout_s: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self.url = _endpoint(base_url, "/chat/completions")
        self.model = model
        self.api_key = api_key
        self._sem = asyncio.Semaphore(concurrency)
        self._timeout = httpx.Timeout(timeout_s, connect=15.0)
        self._max_retries = max_retries
        self.usage = UsageStats()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("ChatClient must be used inside 'async with'")
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                async with self._sem:
                    t0 = time.monotonic()
                    resp = await self._client.post(self.url, json=payload)
                    elapsed = time.monotonic() - t0
                if resp.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    delay = 1.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM HTTP %d (attempt %d/%d), retrying in %.1fs",
                        resp.status_code, attempt, self._max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                self.usage.record(data.get("usage"), elapsed)
                return data
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = 1.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM network error %s (attempt %d/%d), retrying in %.1fs",
                        exc, attempt, self._max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise RuntimeError(f"LLM request failed after retries: {last_exc}")

    async def chat_text(
        self,
        user: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        for attempt in range(1, 3):
            data = await self._post(
                {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                }
            )
            text = _extract_content(data).strip()
            if text:
                return text
            finish_reason = (data.get("choices") or [{}])[0].get("finish_reason")
            logger.warning(
                "LLM returned empty content (attempt %d/2, finish_reason=%s), retrying",
                attempt,
                finish_reason,
            )
        raise RuntimeError(f"LLM {self.model} returned empty content after 2 attempts")

    async def chat_json(
        self,
        user: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.1,
    ) -> T:
        """Request JSON output and strictly validate against a Pydantic schema.

        Retries once with the exact validation error on parse/schema mismatch,
        then raises explicitly rather than returning a degraded fallback.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        last_err = ""
        for attempt in range(2):
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            data = await self._post(payload)
            raw = _extract_content(data)
            cleaned = _strip_json_fences(raw)
            try:
                parsed = json.loads(cleaned)
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_err = str(exc)
                logger.warning("Structured JSON validation failed (attempt %d/2): %s", attempt + 1, last_err[:300])
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"上一次回复未通过 JSON Schema 校验，错误如下：\n{last_err[:600]}\n\n"
                            "请修正后严格输出合法的 JSON 对象，不要包含其他说明。"
                        ),
                    }
                )
        raise RuntimeError(f"LLM failed structured output validation for {schema.__name__}: {last_err}")


class EmbedClient:
    """Async OpenAI-compatible Embeddings client with client-side MRL truncation."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        dim: int = 1024,
        batch_size: int = 64,
        timeout_s: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.url = _endpoint(base_url, "/embeddings")
        self.model = model
        self.api_key = api_key
        self.dim = dim
        self.batch_size = batch_size
        self._timeout = httpx.Timeout(timeout_s, connect=15.0)
        self._max_retries = max_retries
        self.usage = UsageStats()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _embed_chunk(self, texts: list[str]) -> list[np.ndarray]:
        if self._client is None:
            raise RuntimeError("EmbedClient must be used inside 'async with'")
        payload = {"model": self.model, "input": texts}
        for attempt in range(1, self._max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = await self._client.post(self.url, json=payload)
                if resp.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    delay = 1.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Embed HTTP %d (attempt %d/%d), retrying in %.1fs",
                        resp.status_code, attempt, self._max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                body = resp.json()
                self.usage.record(body.get("usage"), time.monotonic() - t0)
                rows = sorted(body["data"], key=lambda r: r.get("index", 0))
                if len(rows) != len(texts):
                    raise RuntimeError(
                        f"Embedding count mismatch: sent {len(texts)}, got {len(rows)}"
                    )
                return [truncate_and_normalize(r["embedding"], self.dim) for r in rows]
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                if attempt < self._max_retries:
                    delay = 1.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Embed network error %s (attempt %d/%d), retrying in %.1fs",
                        exc, attempt, self._max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise RuntimeError("Embedding request failed after retries")

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        out: list[np.ndarray] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(await self._embed_chunk(texts[i : i + self.batch_size]))
        return out
