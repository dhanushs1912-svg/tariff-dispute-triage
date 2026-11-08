"""Client for the llm-gateway. Agents never hold provider keys or model ids."""
from __future__ import annotations

import json
import re
import time

import httpx

from .config import settings
from .obs import correlation_id, inject_context


class LLMUnavailable(Exception):
    """The gateway could not get an answer from any provider (breaker open, outage, timeout)."""


class LLMBadOutput(Exception):
    pass


_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=settings().gateway_client_timeout)
    return _client


def complete(messages: list[dict], *, run_id: str, agent: str, step: str, max_tokens: int = 800,
             tools: list[dict] | None = None) -> dict:
    headers = {"x-correlation-id": correlation_id.get(), **inject_context()}
    t0 = time.perf_counter()
    try:
        r = _http().post(f"{settings().gateway_url}/v1/complete", headers=headers,
                         json={"messages": messages, "run_id": run_id, "agent": agent, "step": step,
                               "json_mode": True, "max_tokens": max_tokens, "tools": tools})
    except httpx.HTTPError as e:
        raise LLMUnavailable(f"gateway unreachable: {e}") from e
    if r.status_code == 503:
        raise LLMUnavailable(json.dumps(r.json())[:300])
    if r.status_code >= 400:
        raise LLMUnavailable(f"gateway error {r.status_code}: {r.text[:200]}")
    out = r.json()
    out["wall_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def parse_json(text: str) -> dict:
    """Parse the first JSON object in a model reply (tolerates code fences and leading prose)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    depth = 0
    for i in range(start, len(text)) if start != -1 else []:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    break
    raise LLMBadOutput(f"no JSON object in model output: {text[:200]}")
