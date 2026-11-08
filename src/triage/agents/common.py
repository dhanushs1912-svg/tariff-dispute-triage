"""Shared helpers for both agents: step recording (DB + metrics + spans) and model calls."""
from __future__ import annotations

import concurrent.futures
import logging
import time

from .. import db
from ..llm import LLMBadOutput, complete, parse_json
from ..metrics import AGENT_LLM_CALLS, AGENT_RETRIES, STEP_COST, STEP_LAT, TOKENS
from ..obs import log, tracer

logger = logging.getLogger("agents")
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


class StepRecorder:
    def __init__(self, run_id: str, agent: str, attempt: int) -> None:
        self.run_id, self.agent, self.attempt = run_id, agent, attempt
        self.step_no = 0
        self.cost = 0.0
        self.llm_calls = 0
        self.tool_calls = 0

    def record(self, kind: str, name: str, input_, output, status: str, latency_s: float, *, usage: dict | None = None,
               prompt_version: str | None = None) -> None:
        self.step_no += 1
        usage = usage or {}
        cost = float(usage.get("cost_usd") or 0)
        self.cost += cost
        db.add_step(self.run_id, self.agent, self.attempt, self.step_no, kind, name, input_, output, status,
                    int(latency_s * 1000), int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                    cost, prompt_version, int(usage.get("retries") or 0))
        STEP_LAT.labels(self.agent, kind, name).observe(latency_s)
        if kind == "llm":
            STEP_COST.labels(self.agent, name).inc(cost)
            TOKENS.labels(self.agent, "prompt").inc(int(usage.get("prompt_tokens") or 0))
            TOKENS.labels(self.agent, "completion").inc(int(usage.get("completion_tokens") or 0))
        log(logger, logging.INFO, "step", run_id=self.run_id, step_no=self.step_no, kind=kind, name=name,
            status=status, latency_ms=int(latency_s * 1000), cost_usd=round(cost, 6))

    def llm_json(self, name: str, messages: list[dict], prompt_tag: str, max_tokens: int = 800,
                 tools: list[dict] | None = None) -> dict:
        """One model call that must return JSON. One repair attempt on malformed output."""
        with tracer().start_as_current_span(f"llm:{self.agent}:{name}") as span:
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("prompt_version", prompt_tag)
            for repair in (False, True):
                t0 = time.perf_counter()
                msgs = messages if not repair else messages + [
                    {"role": "user", "content": "Your previous reply was not a single valid JSON object. Reply again with JSON only."}]
                out = complete(msgs, run_id=self.run_id, agent=self.agent, step=name, max_tokens=max_tokens, tools=tools)
                self.llm_calls += 1
                AGENT_LLM_CALLS.labels(self.agent).inc()
                if out.get("retries"):
                    AGENT_RETRIES.labels(self.agent).inc(out["retries"])
                span.set_attribute("retries", out.get("retries", 0))
                try:
                    parsed = parse_json(out["content"])
                    self.record("llm", name, {"messages": msgs[-1:], "chars": sum(len(m["content"]) for m in msgs)},
                                {"raw": out["content"][:4000], "provider": out.get("provider"), "degraded": out.get("degraded")},
                                "ok", time.perf_counter() - t0, usage=out, prompt_version=prompt_tag)
                    return parsed
                except LLMBadOutput as e:
                    self.record("llm", name, {"chars": sum(len(m["content"]) for m in msgs)}, {"raw": out["content"][:2000],
                                "error": str(e)}, "bad_output", time.perf_counter() - t0, usage=out, prompt_version=prompt_tag)
            raise LLMBadOutput(f"{name}: model did not return JSON after repair")

    def tool(self, name: str, fn, args: dict, timeout: float):
        """Run a tool with a hard timeout."""
        self.tool_calls += 1
        t0 = time.perf_counter()
        with tracer().start_as_current_span(f"tool:{name}") as span:
            span.set_attribute("run_id", self.run_id)
            fut = _pool.submit(fn, **args)
            try:
                result = fut.result(timeout=timeout)
                status = "ok"
            except concurrent.futures.TimeoutError:
                result, status = {"error": f"tool timed out after {timeout}s"}, "timeout"
            except Exception as e:  # noqa: BLE001 - tool errors are reported back to the agent
                result, status = {"error": f"{type(e).__name__}: {e}"}, "error"
            span.set_attribute("status", status)
        return result, status, time.perf_counter() - t0
