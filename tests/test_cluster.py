"""Deterministic tests for vector micro-clustering, MRL normalization, and structured LLM validation."""

import json

import httpx
import numpy as np
import pytest

from spnews.cluster import ClusteringOutput, centroid_vector, micro_cluster_embeddings
from spnews.llm import ChatClient, truncate_and_normalize


def test_truncate_and_normalize_slices_and_unit_norms():
    raw = [3.0, 4.0] + [0.0] * 10
    vec = truncate_and_normalize(raw, dim=4)
    assert vec.shape == (4,)
    assert vec.dtype == np.float32
    assert pytest.approx(float(np.linalg.norm(vec)), abs=1e-5) == 1.0
    assert pytest.approx(float(vec[0]), abs=1e-5) == 0.6
    assert pytest.approx(float(vec[1]), abs=1e-5) == 0.8


def test_truncate_and_normalize_rejects_bad_vectors():
    with pytest.raises(ValueError):
        truncate_and_normalize([1.0, 2.0], dim=4)
    with pytest.raises(ValueError):
        truncate_and_normalize([0.0, 0.0, 0.0, 0.0], dim=4)


def test_micro_cluster_merges_similar_and_avoids_chaining():
    # Two clear stories: story A (0, 1) and story B (2, 3), plus an unrelated item (4)
    a1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    a2 = np.array([0.96, 0.28, 0.0, 0.0], dtype=np.float32)
    b1 = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
    b2 = np.array([0.0, 0.0, 0.95, 0.31], dtype=np.float32)
    c1 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    groups = micro_cluster_embeddings([a1, a2, b1, b2, c1], threshold=0.75)
    assert sorted(groups) == [[0, 1], [2, 3], [4]]

    # Bridge test: A and C are orthogonal (sim=0), B sits at 45 deg (sim=0.707 to both).
    # Average linkage at 0.65 merges (A, B), then avg_sim({A,B}, {C}) = 0.353 < 0.65 -> does NOT chain C.
    va = np.array([1.0, 0.0], dtype=np.float32)
    vb = np.array([0.7071, 0.7071], dtype=np.float32)
    vc = np.array([0.0, 1.0], dtype=np.float32)
    chained = micro_cluster_embeddings([va, vb, vc], threshold=0.65)
    assert len(chained) == 2

    cent = centroid_vector([a1, a2])
    assert pytest.approx(float(np.linalg.norm(cent)), abs=1e-5) == 1.0


@pytest.mark.asyncio
async def test_chat_json_repairs_once_and_fails_loudly_when_invalid():
    attempts = {"n": 0}

    def repair_handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            content = "not valid json"
        else:
            content = json.dumps(
                {
                    "events": [
                        {
                            "title": "湖人击败火箭晋级",
                            "importance": "high",
                            "micro_cluster_ids": [0],
                            "parent_event_id": None,
                        }
                    ]
                }
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    client = ChatClient("https://example.test", "mock-model", "test-key")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(repair_handler))
    try:
        res = await client.chat_json("cluster these", ClusteringOutput)
        assert len(res.events) == 1
        assert res.events[0].title == "湖人击败火箭晋级"
        assert attempts["n"] == 2
    finally:
        await client._client.aclose()

    # Persistent bad output must raise RuntimeError rather than returning a degraded cluster
    def always_bad_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{bad"}}]},
        )

    client2 = ChatClient("https://example.test", "mock-model", "test-key")
    client2._client = httpx.AsyncClient(transport=httpx.MockTransport(always_bad_handler))
    try:
        with pytest.raises(RuntimeError, match="ClusteringOutput"):
            await client2.chat_json("cluster these", ClusteringOutput)
    finally:
        await client2._client.aclose()


@pytest.mark.asyncio
async def test_chat_text_retries_empty_content_and_fails_loudly():
    calls = {"n": 0}

    def empty_then_ok(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        content = "" if calls["n"] == 1 else "有效中文摘要。"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    c1 = ChatClient("https://example.test", "mock-model", "test-key")
    c1._client = httpx.AsyncClient(transport=httpx.MockTransport(empty_then_ok))
    try:
        assert await c1.chat_text("hi") == "有效中文摘要。"
        assert calls["n"] == 2
    finally:
        await c1._client.aclose()

    def always_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
        )

    c2 = ChatClient("https://example.test", "mock-model", "test-key")
    c2._client = httpx.AsyncClient(transport=httpx.MockTransport(always_empty))
    try:
        with pytest.raises(RuntimeError, match="empty content"):
            await c2.chat_text("hi")
    finally:
        await c2._client.aclose()
