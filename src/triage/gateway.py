"""llm-gateway: the only service that talks to the model provider (A5, L5).

Agents call POST /v1/complete. The gateway owns the provider configuration, per-call timeouts,
bounded retries with exponential backoff and full jitter, a circuit breaker per provider, an
optional fallback provider, and token/cost accounting at the time of the call. When every
path fails it answers 503 provider_unavailable and the caller degrades (escalates) instead of
guessing. Fault injection (ENABLE_FAULT_INJECTION=true) lets the demo take the provider down.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from .config import GatewaySettings
from .obs import correlation_id, log, setup_logging, setup_tracing

logger = setup_logging("llm-gateway")
setup_tracing("llm-gateway")
cfg = GatewaySettings()

LLM_REQ = Counter("llm_requests_total", "Provider calls by outcome", ["provider", "outcome"])
LLM_LAT = Histogram("llm_call_latency_seconds", "Provider call latency", ["provider"],
                    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 60))
LLM_RETRY = Counter("llm_retries_total", "Retries against the provider", ["provider", "agent"])
LLM_TOK = Counter("llm_tokens_total", "Tokens by direction", ["agent", "kind"])
LLM_COST = Counter("llm_cost_usd_total", "Cost at call time (USD)", ["agent", "step"])
BREAKER = Gauge("llm_breaker_state", "0 closed, 1 half-open, 2 open", ["provider"])
BREAKER_TRANSITIONS = Counter("llm_breaker_transitions_total", "Breaker state changes", ["provider", "to"])
DEGRADED = Counter("llm_degraded_total", "Requests served by fallback or refused", ["path"])
RATE_WAIT = Counter("llm_rate_limit_wait_seconds_total", "Seconds spent waiting because every provider was rate-limited")


class Breaker:
    def __init__(self, name: str, threshold: int, reset_seconds: float) -> None:
        self.name, self.threshold, self.reset_seconds = name, threshold, reset_seconds
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.half_open_inflight = False
        BREAKER.labels(name).set(0)

    def _to(self, state: str) -> None:
        if state != self.state:
            self.state = state
            BREAKER.labels(self.name).set({"closed": 0, "half_open": 1, "open": 2}[state])
            BREAKER_TRANSITIONS.labels(self.name, state).inc()
            log(logger, logging.WARNING, "breaker transition", provider=self.name, state=state, failures=self.failures)

    def allow(self) -> bool:
        if self.state == "open":
            if time.time() - self.opened_at >= self.reset_seconds:
                self._to("half_open")
            else:
                return False
        if self.state == "half_open":
            if self.half_open_inflight:
                return False
            self.half_open_inflight = True
        return True

    def success(self) -> None:
        self.failures = 0
        self.half_open_inflight = False
        self._to("closed")

    def failure(self) -> None:
        self.failures += 1
        self.half_open_inflight = False
        if self.state == "half_open" or self.failures >= self.threshold:
            self.opened_at = time.time()
            self._to("open")

    def snapshot(self) -> dict:
        return {"provider": self.name, "state": self.state, "consecutive_failures": self.failures,
                "opened_seconds_ago": round(time.time() - self.opened_at, 1) if self.state != "closed" else None}


class Provider:
    def __init__(self, name: str, base_url: str, api_key: str, model: str) -> None:
        self.name, self.base_url, self.api_key, self.model = name, base_url.rstrip("/"), api_key, model
        self.breaker = Breaker(name, cfg.breaker_fail_threshold, cfg.breaker_reset_seconds)


providers = [Provider("primary", cfg.base_url, cfg.api_key, cfg.model)]
if cfg.fallback_base_url and cfg.fallback_model:
    # LLM_FALLBACK_MODEL may list several models (comma separated); each gets its own breaker and quota.
    for n, model in enumerate(m.strip() for m in cfg.fallback_model.split(",") if m.strip()):
        providers.append(Provider("fallback" if n == 0 else f"fallback{n + 1}", cfg.fallback_base_url,
                                  cfg.fallback_api_key, model))
if cfg.fallback2_base_url and cfg.fallback2_model:
    # A second provider (different company, different quota) tried last.
    providers.append(Provider("provider2", cfg.fallback2_base_url, cfg.fallback2_api_key, cfg.fallback2_model))

fault = {"mode": "none", "until": 0.0}
client = httpx.AsyncClient(limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))
app = FastAPI(title="llm-gateway", version="1.0.0")


class CompleteRequest(BaseModel):
    messages: list[dict] = Field(min_length=1)
    run_id: str = "-"
    agent: str = "-"
    step: str = "-"
    json_mode: bool = True
    max_tokens: int = Field(default=800, ge=16, le=4000)
    temperature: float = Field(default=0.0, ge=0, le=1.5)
    tools: list[dict] | None = None


class ProviderError(Exception):
    def __init__(self, kind: str, retryable: bool, detail: str = "", retry_after: float | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.retryable, self.detail, self.retry_after = kind, retryable, detail, retry_after


def _fault_active() -> str:
    if fault["mode"] != "none" and (fault["until"] == 0 or time.time() < fault["until"]):
        return fault["mode"]
    return "none"


async def _call(p: Provider, req: CompleteRequest) -> dict:
    mode = _fault_active()
    if p.name == "primary" and mode == "down":
        raise ProviderError("connect", True, "fault injection: provider down")
    if p.name == "primary" and mode == "error500":
        raise ProviderError("http_500", True, "fault injection: 500")
    if p.name == "primary" and mode == "slow":
        await asyncio.sleep(cfg.call_timeout + 1)
        raise ProviderError("timeout", True, "fault injection: slow")
    body = {"model": p.model, "messages": req.messages, "temperature": req.temperature,
            "max_tokens": min(req.max_tokens, cfg.max_tokens_cap)}
    if req.tools:
        body["tools"] = req.tools
        body["tool_choice"] = "required"
    elif req.json_mode and cfg.json_mode:
        body["response_format"] = {"type": "json_object"}
    if cfg.reasoning_effort:
        body["reasoning_effort"] = cfg.reasoning_effort
    headers = {"Content-Type": "application/json"}
    if p.api_key:
        headers["Authorization"] = f"Bearer {p.api_key}"
    try:
        r = await client.post(f"{p.base_url}/chat/completions", json=body, headers=headers, timeout=cfg.call_timeout)
    except httpx.TimeoutException as e:
        raise ProviderError("timeout", True, str(e)) from e
    except httpx.HTTPError as e:
        raise ProviderError("connect", True, str(e)) from e
    if r.status_code == 429:
        raise ProviderError("rate_limited", True, r.text[:300], _retry_after(r))
    if r.status_code == 400 and "reasoning_effort" in body and "reasoning" in r.text.lower():
        body.pop("reasoning_effort")
        r = await client.post(f"{p.base_url}/chat/completions", json=body, headers=headers, timeout=cfg.call_timeout)
    if r.status_code == 400 and "response_format" in body and "json" in r.text.lower() and "tool_use_failed" not in r.text:
        body.pop("response_format")
        r = await client.post(f"{p.base_url}/chat/completions", json=body, headers=headers, timeout=cfg.call_timeout)
    if r.status_code == 400 and "tool_use_failed" in r.text:
        generated = ""
        try:
            generated = (r.json().get("error") or {}).get("failed_generation") or ""
        except ValueError:
            pass
        recovered = _recover_tool_call(generated)
        if recovered is None:
            raise ProviderError("tool_use_failed", True, r.text[:200])
        LLM_REQ.labels(p.name, "recovered_tool_call").inc()
        return {"content": recovered, "prompt_tokens": sum(len(str(m.get("content", ""))) for m in req.messages) // 4,
                "completion_tokens": len(generated) // 4}
    if r.status_code >= 500:
        raise ProviderError(f"http_{r.status_code}", True, r.text[:200])
    if r.status_code >= 400:
        raise ProviderError(f"http_{r.status_code}", False, r.text[:300])
    data = r.json()
    try:
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError("bad_response", True, str(data)[:200]) from e
    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        content = json.dumps({"thought": content[:300], "action": fn.get("name"), "args": args})
    usage = data.get("usage") or {}
    pt = int(usage.get("prompt_tokens") or sum(len(str(m.get("content", ""))) for m in req.messages) // 4)
    ct = int(usage.get("completion_tokens") or len(content) // 4)
    return {"content": content, "prompt_tokens": pt, "completion_tokens": ct}


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds until the provider's limit resets: Retry-After header, else 'try again in 1m2.5s'."""
    ra = r.headers.get("retry-after")
    if ra:
        try:
            return float(ra)
        except ValueError:
            pass
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", r.text)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))
    return None


def _recover_tool_call(generated: str) -> str | None:
    """The model sometimes writes its tool call as text; the provider then rejects it. Rebuild the
    action from that text when it is a well-formed call, so one formatting slip does not fail the run."""
    text = generated.strip()
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("action") or data.get("name")
    args = data.get("args") or data.get("arguments") or data.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not name:
        return None
    return json.dumps({"thought": str(data.get("thought", ""))[:300], "action": name, "args": args})


async def _with_retries(p: Provider, req: CompleteRequest, max_retries: int) -> tuple[dict, int]:
    attempt = 0
    while True:
        if not p.breaker.allow():
            raise ProviderError("breaker_open", False, f"{p.name} circuit open")
        t0 = time.perf_counter()
        try:
            out = await _call(p, req)
            p.breaker.success()
            LLM_REQ.labels(p.name, "ok").inc()
            LLM_LAT.labels(p.name).observe(time.perf_counter() - t0)
            return out, attempt
        except ProviderError as e:
            LLM_LAT.labels(p.name).observe(time.perf_counter() - t0)
            LLM_REQ.labels(p.name, e.kind).inc()
            # A rate limit means "slow down", not "the provider is broken": it does not trip the breaker.
            if e.kind not in ("breaker_open", "rate_limited"):
                p.breaker.failure()
            log(logger, logging.WARNING, "provider call failed", provider=p.name, kind=e.kind, attempt=attempt,
                retryable=e.retryable, detail=e.detail[:240], run_id=req.run_id, agent=req.agent)
            if e.kind == "rate_limited":
                raise
            if not e.retryable or attempt >= max_retries:
                raise
            attempt += 1
            LLM_RETRY.labels(p.name, req.agent).inc()
            delay = min(cfg.backoff_max, cfg.backoff_base * (2 ** (attempt - 1)))
            delay = random.uniform(0, delay)
            if e.retry_after:
                delay = min(max(delay, e.retry_after), cfg.backoff_max)
            await asyncio.sleep(delay)


@app.middleware("http")
async def _correlation(request: Request, call_next):
    correlation_id.set(request.headers.get("x-correlation-id", "-"))
    return await call_next(request)


@app.post("/v1/complete")
async def complete(req: CompleteRequest):
    t0 = time.perf_counter()
    deadline = time.time() + cfg.rate_limit_wait
    waited = 0
    while True:
        errors, waits = [], []
        for idx, p in enumerate(providers):
            try:
                out, retries = await _with_retries(p, req, cfg.max_retries)
            except ProviderError as e:
                errors.append({"provider": p.name, "error": e.kind})
                if e.kind == "rate_limited":
                    waits.append(e.retry_after or 5.0)
                continue
            return _served(req, p, idx, out, retries + waited, t0)
        # Every provider refused. If at least one only asked us to slow down, wait for the
        # earliest reset and go round again, within the time limit; otherwise give up.
        if waits and time.time() + min(waits) < deadline:
            delay = min(min(waits), 20.0) + random.uniform(0.2, 1.0)
            RATE_WAIT.inc(delay)
            log(logger, logging.INFO, "all providers rate-limited; waiting", seconds=round(delay, 1), run_id=req.run_id)
            await asyncio.sleep(delay)
            waited += 1
            continue
        break
    DEGRADED.labels("refused").inc()
    return JSONResponse(status_code=503, content={"error": "provider_unavailable", "attempts": errors,
                                                   "breakers": [p.breaker.snapshot() for p in providers]})


def _served(req: CompleteRequest, p: "Provider", idx: int, out: dict, retries: int, t0: float) -> dict:
    cost = out["prompt_tokens"] * cfg.price_in_per_mtok / 1e6 + out["completion_tokens"] * cfg.price_out_per_mtok / 1e6
    LLM_TOK.labels(req.agent, "prompt").inc(out["prompt_tokens"])
    LLM_TOK.labels(req.agent, "completion").inc(out["completion_tokens"])
    LLM_COST.labels(req.agent, req.step).inc(cost)
    if idx > 0:
        DEGRADED.labels("fallback").inc()
    return {**out, "cost_usd": round(cost, 8), "provider": p.name, "retries": retries,
            "degraded": idx > 0, "latency_ms": int((time.perf_counter() - t0) * 1000)}


@app.get("/health")
def health():
    return {"status": "ok", "breakers": [p.breaker.snapshot() for p in providers], "fault": _fault_active()}


@app.get("/admin/breaker")
def breaker():
    return {"breakers": [p.breaker.snapshot() for p in providers], "fault": _fault_active()}


class FaultRequest(BaseModel):
    mode: str = Field(pattern="^(none|down|slow|error500)$")
    seconds: float = Field(default=0, ge=0, le=3600)


@app.post("/admin/fault")
def set_fault(req: FaultRequest):
    if not cfg.fault_injection:
        return JSONResponse(status_code=403, content={"error": "fault injection disabled"})
    fault["mode"] = req.mode
    fault["until"] = time.time() + req.seconds if req.seconds else 0.0
    log(logger, logging.WARNING, "fault injection set", mode=req.mode, seconds=req.seconds)
    return {"fault": req.mode, "seconds": req.seconds}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
