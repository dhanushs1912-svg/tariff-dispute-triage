"""Verifier agent (agent 2 of 2). Runs in the `verifier` worker container.

LangGraph topology:
    load -> (escalation from research) -> finalize
         -> check (deterministic: citations resolve, quotes found, no superseded text,
                   output filter, route/category consistency)
              -> judge (model reads only the cited passages)
              -> decide -> finalize | retry (back to the research queue, new strategy) | escalate

An unverified answer is never returned: if the judge cannot run (provider down) the run is
escalated, and after MAX_VERIFY_ATTEMPTS failed verifications the run is escalated too.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .. import db, guardrails, prompts
from ..cache import index_version, request_hash, run_cache_put
from ..config import settings
from ..llm import LLMBadOutput, LLMUnavailable
from ..metrics import (AGENT_LAT, AGENT_RUNS, AGENT_STEPS, ESCALATIONS, GUARD, LIVE_LAST, LIVE_SCORE, ROUTES,
                       RUN_COST, RUN_E2E, VERIFY)
from ..obs import correlation_id, current_agent, extract_context, log, tracer
from ..quality import context_relevance, repair_citations, resolve_citations
from .common import StepRecorder

logger = logging.getLogger("verifier")
AGENT = "verifier"
CACHEABLE_ESCALATIONS = {"input_flagged", "outside_corpus"}


class State(TypedDict, total=False):
    run: dict
    handoff: dict
    passages: dict
    checks: dict
    judge: dict
    decision: str
    reason: str
    escalation: dict


def build_graph(rec: StepRecorder):
    s = settings()
    judge_prompt = prompts.load("verifier", s.verifier_prompt_version)

    def check(state: State) -> dict:
        t0 = time.perf_counter()
        h, run = state["handoff"], state["run"]
        draft = h.get("draft") or {}
        claims = draft.get("claims") or []
        repaired = repair_citations(claims, state["passages"])
        res = resolve_citations(claims, state["passages"])
        res["citations_repaired"] = repaired
        problems = []
        if not claims:
            problems.append("draft has no claims")
        if not res["all_ok"]:
            problems.append(f"{res['citations_bad']} of {res['citations_total']} citations do not resolve to retrieved text")
        texts = [draft.get("position", "")] + [c.get("text", "") for c in claims]
        violations = guardrails.output_violations(texts)
        if violations:
            GUARD.labels("output_filter").inc()
            problems.extend(violations)
        billed = run["request"]["billed_category"]
        cat, route = draft.get("determined_category"), draft.get("route")
        dtype = (h.get("intake") or {}).get("dispute_type")
        if dtype in (None, "tariff_category"):
            if route == "revision-recommended" and cat == billed:
                problems.append("route is revision-recommended but the determined category equals the billed category")
            if route == "bill-stands-with-reason" and cat not in (None, billed):
                problems.append(f"route is bill-stands but the determined category {cat} differs from billed {billed}")
        checks = {**res, "problems": problems, "output_violations": violations, "passed": not problems}
        rec.record("check", "deterministic_checks", {"claims": len(claims)}, checks,
                   "ok" if not problems else "failed", time.perf_counter() - t0)
        return {"checks": checks}

    def judge(state: State) -> dict:
        h, run = state["handoff"], state["run"]
        draft = h["draft"]
        blocks = []
        for i, c in enumerate(draft["claims"]):
            texts = []
            for x in c["citations"]:
                p = state["passages"].get(x["chunk_id"])
                if p:
                    texts.append(f"[{x['chunk_id']}] {p['locator']}\n{p['text'][:1400]}")
            blocks.append(f"CLAIM {i}: {c['text']}\nCITED PASSAGES:\n" + "\n---\n".join(texts))
        case = (h.get("intake") or {}).get("summary") or run["request"]["description"][:300]
        msgs = judge_prompt.render(case=case, route=draft["route"], category=draft.get("determined_category"),
                                   position=draft.get("position", ""), claims="\n\n".join(blocks))
        try:
            out = rec.llm_json("judge", msgs, judge_prompt.tag, max_tokens=700)
        except LLMUnavailable as e:
            return {"judge": {"error": "provider_unavailable", "detail": str(e)[:200]}}
        except LLMBadOutput as e:
            return {"judge": {"error": "bad_output", "detail": str(e)[:200]}}
        flags = {int(c.get("index", -1)): bool(c.get("supported")) for c in out.get("claims", []) if isinstance(c, dict)}
        supported = [flags.get(i, False) for i in range(len(draft["claims"]))]
        return {"judge": {"supported": supported, "conclusion_follows": bool(out.get("conclusion_follows")),
                          "reason": str(out.get("reason", ""))[:400], "raw": out}}

    def decide(state: State) -> dict:
        h = state["handoff"]
        checks, j = state.get("checks", {}), state.get("judge", {})
        attempt = int(h.get("attempt", 0))
        if j.get("error") == "provider_unavailable":
            return {"decision": "escalate", "escalation": {"reason": "provider_unavailable", "explanation":
                    "The draft could not be verified because the model provider is unavailable; an unverified "
                    "answer is never returned."}}
        problems = list(checks.get("problems", []))
        for cl in checks.get("claims", []):
            for c in cl.get("citations", []):
                if c["status"] != "ok":
                    problems.append(f"claim {cl['index']} citation {c['chunk_id']}: {c['status']}")
        if j.get("error"):
            problems.append(f"judge failed: {j['error']}")
        elif j:
            raw = {int(c.get("index", -1)): c.get("reason", "") for c in (j.get("raw") or {}).get("claims", [])
                   if isinstance(c, dict)}
            for i, ok in enumerate(j.get("supported", [])):
                if not ok:
                    problems.append(f"claim {i} not supported by its cited passages ({str(raw.get(i, ''))[:120]})")
            if not j.get("conclusion_follows"):
                problems.append("route/category does not follow from the supported claims")
        if not problems:
            VERIFY.labels("pass").inc()
            return {"decision": "finalize", "reason": "verified"}
        if any("states an amount" in p or "bill determination" in p for p in problems) and attempt + 1 >= s.max_verify_attempts:
            VERIFY.labels("output_filtered").inc()
            return {"decision": "escalate", "escalation": {"reason": "unauthorised_determination", "explanation":
                    "The draft tried to state an amount or revise the bill, which this service may not do."}}
        if attempt + 1 < s.max_verify_attempts:
            VERIFY.labels("retry").inc()
            return {"decision": "retry", "reason": "; ".join(problems)[:600]}
        VERIFY.labels("fail").inc()
        return {"decision": "escalate", "escalation": {"reason": "verification_failed", "explanation":
                f"The draft failed verification after {attempt + 1} attempts: {'; '.join(problems)[:400]}"}}

    def route_after_load(state: State) -> str:
        return "escalate" if state["handoff"].get("escalation") or not state["handoff"].get("draft") else "check"

    def route_after_check(state: State) -> str:
        c = state["checks"]
        structural = any(p.startswith("draft has no claims") or "do not resolve" in p for p in c["problems"])
        return "decide" if structural else "judge"

    g = StateGraph(State)
    g.add_node("check", check)
    g.add_node("judge", judge)
    g.add_node("decide", decide)
    g.add_node("escalate", lambda state: {"decision": "escalate",
                                          "escalation": state["handoff"].get("escalation") or {
                                              "reason": "agent_failure", "explanation": "research produced no draft"}})
    g.add_conditional_edges(START, route_after_load, {"escalate": "escalate", "check": "check"})
    g.add_conditional_edges("check", route_after_check, {"decide": "decide", "judge": "judge"})
    g.add_edge("judge", "decide")
    g.add_edge("decide", END)
    g.add_edge("escalate", END)
    return g.compile()


def _citations(claims: list[dict], passages: dict, only_ok: bool, checks: dict | None) -> list[dict]:
    out, seen = [], set()
    status = {}
    for cr in (checks or {}).get("claims", []):
        for c in cr.get("citations", []):
            status[c["chunk_id"]] = c["status"]
    for c in claims:
        for x in c.get("citations", []):
            cid = x.get("chunk_id")
            p = passages.get(cid)
            if not p or cid in seen or (only_ok and status.get(cid, "ok") != "ok"):
                continue
            seen.add(cid)
            out.append({"chunk_id": cid, "doc_id": p["doc_id"],
                        "doc_title": "KERC Tariff Order 2025" if p["doc_id"] == "kerc_to_2025" else "KERC Conditions of Supply",
                        "locator": p["locator"], "quote": x.get("quote", "")})
    return out


def finalize(rec: StepRecorder, state: State, final: State) -> dict:
    run, h, passages = state["run"], state["handoff"], state["passages"]
    run_id = run["run_id"]
    draft = h.get("draft") or {}
    claims = draft.get("claims") or []
    escalated = final.get("decision") == "escalate"
    esc = final.get("escalation")
    j = final.get("judge") or {}
    supported = j.get("supported") or []
    out_claims = [{"text": c.get("text", ""), "citation_ids": [x["chunk_id"] for x in c.get("citations", [])],
                   "supported": supported[i] if i < len(supported) else None} for i, c in enumerate(claims)]
    steps = db.get_steps(run_id)
    cost = round(sum(st["cost_usd"] for st in steps), 8)
    latency_ms = int((time.time() - run["created_at"]) * 1000)
    route = "escalated-to-officer" if escalated else draft["route"]
    if escalated:
        position = (f"Escalated to a grievance officer: {esc['explanation']}" if esc else "Escalated to a grievance officer.")
        if draft.get("position") and esc and esc["reason"] in ("mixed_category", "provisions_conflict", "insufficient_evidence"):
            position += f" Research notes: {draft['position']}"
    else:
        position = draft.get("position", "")
    result = {
        "run_id": run_id, "route": route, "dispute_type": (h.get("intake") or {}).get("dispute_type"),
        "billed_category": run["request"]["billed_category"],
        "determined_category": None if escalated and (esc or {}).get("reason") not in ("mixed_category",) else draft.get("determined_category"),
        "position": position, "claims": out_claims,
        "citations": _citations(claims, passages, only_ok=True,
                                checks=final.get("checks") or resolve_citations(claims, passages)),
        "escalation": esc if escalated else None,
        "verification": {"decision": final.get("decision"), "attempts": int(h.get("attempt", 0)) + 1,
                         "checks": {k: v for k, v in (final.get("checks") or {}).items() if k != "claims"},
                         "judge": {k: v for k, v in j.items() if k != "raw"}},
        "prompt_versions": run.get("prompt_versions") or {},
        "cost_usd": cost, "latency_ms": latency_ms,
        "disclaimer": "Recommendation only. This service never revises or recomputes a bill; the grievance officer makes the decision.",
    }
    status = "escalated" if escalated else "completed"
    db.update_run(run_id, result=result, route=route, status=status, stage="done", finished_at=time.time())
    RUN_E2E.labels(route).observe(latency_ms / 1000)
    ROUTES.labels(route).inc()
    RUN_COST.observe(cost)
    if escalated and esc:
        ESCALATIONS.labels(esc["reason"]).inc()
    if settings().run_cache_enabled and (not escalated or (esc or {}).get("reason") in CACHEABLE_ESCALATIONS):
        key = request_hash(run["request"], run.get("prompt_versions") or {}, index_version())
        run_cache_put(key, result)
    if not escalated and random.random() < settings().live_score_sample_rate:
        _live_score(run, result, final, passages)
    return result


def _live_score(run: dict, result: dict, final: State, passages: dict) -> None:
    try:
        from ..retrieval import get_store

        j = final.get("judge") or {}
        sup = j.get("supported") or []
        checks = final.get("checks") or {}
        texts = [passages[c["chunk_id"]]["text"] for c in result["citations"] if c["chunk_id"] in passages]
        scores = {
            "groundedness": (sum(sup) / len(sup)) if sup else None,
            "faithfulness": 1.0 if j.get("conclusion_follows") else 0.0,
            "hallucination_rate": checks.get("hallucination_rate"),
            "context_relevance": context_relevance(get_store().embedder, run["request"]["description"], texts),
        }
        with db.cursor() as cur:
            cur.execute("INSERT INTO live_scores (run_id, groundedness, context_relevance, faithfulness,"
                        " hallucination_rate, scored_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING",
                        (run["run_id"], scores["groundedness"], scores["context_relevance"], scores["faithfulness"],
                         scores["hallucination_rate"], time.time()))
        for k, v in scores.items():
            if v is not None:
                LIVE_SCORE.labels(k).observe(v)
                LIVE_LAST.labels(k).set(v)
    except Exception as e:  # noqa: BLE001 - scoring must never break a run
        log(logger, logging.WARNING, "live scoring failed", run_id=run["run_id"], error=repr(e))


def run_verify(run_id: str) -> None:
    """RQ job: verify the research hand-off and finalize, retry or escalate."""
    from ..queueing import enqueue_research

    run = db.get_run(run_id)
    if run is None or run["status"] in ("completed", "escalated", "failed"):
        return
    correlation_id.set(run_id)
    current_agent.set(AGENT)
    h = run.get("draft") or {}
    attempt = int(h.get("attempt", 0))
    from ..locks import acquire

    if not acquire("verify", run_id, attempt):
        return
    t0 = time.time()
    rec = StepRecorder(run_id, AGENT, attempt)
    with tracer().start_as_current_span("agent:verifier", context=extract_context(run.get("trace_carrier"))) as span:
        span.set_attribute("run_id", run_id)
        db.update_run(run_id, stage="verify")
        state: State = {"run": run, "handoff": h, "passages": db.get_passages(run_id)}
        try:
            final = build_graph(rec).invoke(state)
        except Exception as e:  # noqa: BLE001
            log(logger, logging.ERROR, "verifier crashed", run_id=run_id, error=repr(e))
            final = {**state, "decision": "escalate",
                     "escalation": {"reason": "agent_failure", "explanation": f"Verifier error: {type(e).__name__}"}}
        decision = final.get("decision")
        span.set_attribute("decision", decision)
        rec.record("check", "decision", {"attempt": attempt}, {"decision": decision, "reason": final.get("reason"),
                   "escalation": final.get("escalation")}, decision, 0.0)
        if decision == "retry":
            fb = {"attempt": attempt + 1, "summary": final.get("reason"), "mode": "keyword",
                  "strategy_hint": "switch search_corpus to mode 'keyword', fetch provisions by identifier with "
                                   "get_clause, and copy quotes word for word from the passages shown"}
            db.update_run(run_id, feedback_for_research=fb, status="running", stage="research")
            enqueue_research(run_id, attempt + 1)
            outcome = "retry"
        else:
            finalize(rec, state, final)
            outcome = "pass" if decision == "finalize" else "escalated"
        AGENT_RUNS.labels(AGENT, outcome).inc()
        AGENT_STEPS.labels(AGENT).observe(rec.step_no)
        AGENT_LAT.labels(AGENT).observe(time.time() - t0)
        log(logger, logging.INFO, "verification done", run_id=run_id, decision=decision, attempt=attempt)
