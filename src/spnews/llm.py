"""Thin wrapper around the LLM API."""

from __future__ import annotations

import httpx

from .config import LLM_BASE_URL, LLM_MODEL

_TIMEOUT = httpx.Timeout(240, connect=10)


def chat(prompt: str, temperature: float = 0.7, reasoning_limit: int = -1) -> str:
    """Send a single-turn chat completion and return the text."""
    resp = httpx.post(
        f"{LLM_BASE_URL}/chat/completions",
        json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            # --- 新增推理预算参数 ---
            "thinking_budget_tokens": reasoning_limit,  # 限制推理 Token 数量，-1:无限制，0:禁用
            "thinking_budget_message": "\n\nConsidering the limited time by the user, I have to give the solution based on the thinking directly now.\n",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
