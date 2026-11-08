r"""Research agent (agent 1 of 2). Runs in the `researcher` worker containers.

LangGraph topology:
    guard -> intake -> decide <-> act -> handoff
                 \                 \-> (budget exhausted) -> handoff
                  \-> (input flagged / outside corpus / provider down) -> handoff

`decide` is a model call that picks the next tool; retrieval is a tool the model chooses, not a
fixed stage. The loop is bounded by steps, tool calls and wall-clock time. `act` enforces the
modifier gate: the agent may not finish on its first retrieval; it must look for provisions that
modify what it found (brief section 5, step 2). The result (a draft position or an escalation) is
saved to Postgres and handed to the verifier through the `verify` queue.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import db, guardrails, prompts
from ..config import settings
from ..contracts import HT_CATEGORIES, LT_CATEGORIES
from ..llm import LLMBadOutput, LLMUnavailable
from ..metrics import AGENT_LAT, AGENT_RUNS, AGENT_STEPS, AGENT_TOOLS, GUARD, TOOL_CALLS
from ..obs import correlation_id, current_agent, extract_context, log, tracer
from ..retrieval import get_store
from .common import StepRecorder

logger = logging.getLogger("researcher")
AGENT = "researcher"
ROUTES = {"bill-stands-with-reason", "revision-recommended", "site-inspection-required", "escalate"}
ESC_REASONS = {"mixed_category", "provisions_conflict", "insufficient_evidence"}
CATEGORIES = set(LT_CATEGORIES + HT_CATEGORIES)
PASSAGE_CHARS = 550


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOL_SCHEMAS = [
    _fn("search_corpus", "Search the KERC tariff order and Conditions of Supply. Returns passages with ids.", {
        "query": {"type": "string"},
        "doc": {"type": "string", "enum": ["tariff_order", "conditions_of_supply"]},
        "k": {"type": "integer", "minimum": 1, "maximum": 8},
        "mode": {"type": "string", "enum": ["hybrid", "keyword", "dense"]}}, ["query"]),
    _fn("get_clause", "Fetch a provision by identifier, e.g. LT-1, LT-3(a), LT-5, 42.02, 3.04, 39.01, GT-29, LTB-14.",
        {"ref": {"type": "string"}}, ["ref"]),
    _fn("follow_references", "List the clauses that a retrieved passage refers to.",
        {"chunk_id": {"type": "string"}}, ["chunk_id"]),
    _fn("get_request_field", "Read one field of the consumer's request.", {"name": {"type": "string"}}, ["name"]),
    _fn("finish", "Submit the tariff position. Every claim must cite passages you were shown, with exact quotes.", {
        "route": {"type": "string", "enum": sorted(ROUTES)},
        "determined_category": {"type": ["string", "null"]},
        "position": {"type": "string"},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object", "properties": {
                "chunk_id": {"type": "string"}, "quote": {"type": "string"}}, "required": ["chunk_id", "quote"]}}},
            "required": ["text", "citations"]}},
        "escalation": {"type": ["object", "null"], "properties": {
            "reason": {"type": "string", "enum": sorted(ESC_REASONS)}, "explanation": {"type": "string"}}}},
        ["route", "position", "claims"]),
]


class State(TypedDict, total=False):
    run_id: str
    attempt: int
    request: dict
    intake: dict
    case_text: str
    scratch: list
    retrieved: dict
    steps: int
    tool_calls: int
    retrieval_calls: int
    queries: list
    started: float
    nudges: int
    action: dict
    draft: dict
    escalation: dict
    feedback: dict
    guard: dict
    done_calls: list


def _covered_escoms() -> set[str]:
    import os

    import yaml

    with open(os.path.join(settings().corpus_dir, "manifest.yaml"), encoding="utf-8") as f:
        docs = yaml.safe_load(f)["documents"]
    out: set[str] = set()
    for d in docs:
        out.update(d.get("covers_escoms", []))
    return out


_GENERIC = {"small", "business", "house", "room", "premises", "domestic", "residential", "commercial", "activity",
            "running", "using", "other", "services", "service", "consumer", "portion", "front"}


def _competing_provisions(state: dict, cited: set[str]) -> list[str]:
    """Retrieved tariff-schedule chunks of different categories that name the consumer's activity
    but were not cited. Returns '[chunk_id] locator' strings."""
    activity = str((state.get("intake") or {}).get("activity") or "").lower()
    words = [w for w in activity.replace("/", " ").replace("-", " ").split() if len(w) >= 5 and w not in _GENERIC]
    if not words:
        return []
    cited_refs = {p.get("clause_ref") for cid, p in state.get("retrieved", {}).items() if cid in cited}
    out, seen_refs = [], set()
    for cid, p in state.get("retrieved", {}).items():
        ref = p.get("clause_ref", "")
        if cid in cited or ref in cited_refs or ref in seen_refs or not ref.startswith(("TO-LT-", "TO-HT-")):
            continue
        body = p.get("text", "").lower()
        if any(w[:-1] in body for w in words):
            seen_refs.add(ref)
            out.append(f"[{cid}] {p['locator']}")
    return out[:3]


MAX_SHOWN_PASSAGES = 7


def render_work(state: dict) -> str:
    """Each retrieved passage is shown once, in full, in one block; the history lists actions and
    passage ids only. Keeps each model call small without the agent losing what it has read."""
    retrieved = list(state.get("retrieved", {}).items())[-MAX_SHOWN_PASSAGES:]
    block = "\n\n".join(fmt_passage({"chunk_id": cid, **p}) for cid, p in retrieved) or "(none yet)"
    history = "\n".join(state.get("scratch", [])[-20:]) or "(nothing yet)"
    return f"PASSAGES RETRIEVED SO FAR (cite only these ids):\n{block}\n\nHISTORY:\n{history}"


def fmt_passage(p: dict, chars: int = PASSAGE_CHARS) -> str:
    text = p["text"]
    if len(text) > chars:
        text = text[:chars].rsplit(" ", 1)[0] + " ..."
    flag = " [SUPERSEDED]" if p.get("superseded") else ""
    return f"[{p['chunk_id']}] {p['locator']}{flag}\n{text}"


def build_case_text(req: dict, intake: dict | None) -> str:
    fields = {k: v for k, v in req.items() if k != "description"}
    lines = [f"Request fields: {json.dumps(fields, default=str)}"]
    if intake:
        lines.append(f"Intake analysis: {json.dumps(intake, default=str)[:900]}")
    lines.append(f"<consumer_text>\n{guardrails.wrap_consumer_text(req['description'])}\n</consumer_text>")
    return "\n".join(lines)


def build_graph(rec: StepRecorder, versions: dict | None = None):
    s = settings()
    versions = versions or {}
    store = get_store()
    intake_prompt = prompts.load("intake", s.intake_prompt_version)
    research_prompt = prompts.load("research", versions.get("research_version") or s.research_prompt_version)
    modifier_gate = versions.get("modifier_gate", s.require_modifier_search)

    def guard(state: State) -> dict:
        t0 = time.perf_counter()
        result = guardrails.screen_input(state["request"]["description"])
        status = "flagged" if (result["injection_flagged"] or result["threat"]) else "ok"
        rec.record("check", "input_guardrail", {"chars": len(state["request"]["description"])}, result, status,
                   time.perf_counter() - t0)
        if result["injection_flagged"]:
            GUARD.labels("prompt_injection").inc()
            return {"guard": result, "escalation": {"reason": "input_flagged", "explanation":
                    "The free-text description contains instructions aimed at the system (prompt injection). "
                    "It was not passed to a model holding tools; an officer should read the request directly."}}
        if result["toxic"]:
            GUARD.labels("toxic_input").inc()
        if result["threat"]:
            GUARD.labels("threat_input").inc()
            return {"guard": result, "escalation": {"reason": "input_flagged", "explanation":
                    "The description contains threatening language; routed to an officer."}}
        return {"guard": result}

    def intake(state: State) -> dict:
        req = state["request"]
        if req["escom"] not in _covered_escoms():
            # Decided from the manifest before any model call: no provider dependency, no tokens spent.
            rec.record("check", "corpus_coverage", {"escom": req["escom"]}, {"covered": False}, "outside", 0.0)
            return {"case_text": build_case_text(req, None), "escalation": {
                "reason": "outside_corpus",
                "explanation": f"{req['escom']} is not covered by the indexed KERC Combined Tariff Order 2025 "
                               "(BESCOM, MESCOM, CESC, HESCOM, GESCOM). Its own tariff order is not in the corpus."}}
        fields = json.dumps({k: v for k, v in req.items() if k != "description"}, default=str)
        msgs = intake_prompt.render(fields=fields, description=guardrails.wrap_consumer_text(req["description"]))
        try:
            data = rec.llm_json("intake", msgs, intake_prompt.tag, max_tokens=500)
        except LLMUnavailable as e:
            return {"escalation": {"reason": "provider_unavailable",
                                   "explanation": f"The model provider is unavailable ({str(e)[:120]}); no position was formed."}}
        except LLMBadOutput:
            data = {"dispute_type": req.get("claimed_dispute_type") or "other", "summary": "intake output unusable"}
        db.update_run(state["run_id"], intake=data)
        return {"intake": data, "case_text": build_case_text(req, data)}

    def budget_left(state: State) -> tuple[bool, str]:
        elapsed = time.time() - state["started"]
        steps_left = s.max_steps - state.get("steps", 0)
        tools_left = s.max_tool_calls - state.get("tool_calls", 0)
        secs_left = s.max_wall_seconds - elapsed
        ok = steps_left > 0 and tools_left > 0 and secs_left > 0
        text = f"{steps_left} steps, {tools_left} tool calls, {int(secs_left)} s."
        if steps_left <= 1 or tools_left <= 0 or secs_left < 15:
            text += " You must call finish now."
        return ok, text

    def decide(state: State) -> dict:
        ok, budget = budget_left(state)
        fb = state.get("feedback")
        feedback = ""
        if fb:
            feedback = ("VERIFIER FEEDBACK on your previous draft (attempt "
                        f"{fb.get('attempt')}): {fb.get('summary')}. Use a different retrieval strategy: {fb.get('strategy_hint')}.\n")
        scratch = render_work(state)
        msgs = research_prompt.render(case=state["case_text"], feedback=feedback, budget=budget, scratch=scratch)
        try:
            action = rec.llm_json("decide", msgs, research_prompt.tag, max_tokens=1800, tools=TOOL_SCHEMAS)
        except LLMUnavailable as e:
            return {"escalation": {"reason": "provider_unavailable",
                                   "explanation": f"The model provider became unavailable mid-run ({str(e)[:120]})."},
                    "steps": state.get("steps", 0) + 1}
        except LLMBadOutput:
            action = {"action": "invalid", "args": {}}
        return {"action": action, "steps": state.get("steps", 0) + 1}

    def act(state: State) -> dict:
        action = state.get("action") or {}
        name = str(action.get("action") or action.get("name") or "").strip()
        args = action.get("args") or action.get("arguments") or action.get("parameters") or {}
        if not isinstance(args, dict):
            args = {}
        if name not in ("search_corpus", "get_clause", "follow_references", "get_request_field") and "route" in args:
            name = "finish"
        scratch = list(state.get("scratch", []))
        scratch.append("ACTION: " + json.dumps({"thought": str(action.get("thought", ""))[:300], "action": name, "args": args}))
        update: dict[str, Any] = {}

        if name == "finish":
            route = args.get("route")
            if route not in ROUTES:
                scratch.append(f"OBSERVATION: invalid route {route!r}. Use one of {sorted(ROUTES)}.")
                return {"scratch": scratch}
            needs_modifier = (modifier_gate and route != "escalate"
                              and state.get("retrieval_calls", 0) < 2 and state.get("nudges", 0) < 2)
            if needs_modifier:
                rec.record("check", "modifier_gate", {"retrieval_calls": state.get("retrieval_calls", 0)},
                           {"result": "blocked finish"}, "blocked", 0.0)
                scratch.append("OBSERVATION: GATE - you have retrieved only once. Before finishing, check whether any "
                               "other provision modifies or overrides what you found. Search the consumer's activity "
                               "word on its own with mode 'keyword' (for example just 'tailoring') to see every "
                               "category that lists it, and check notes, part-use lists, misuse 42.02, "
                               "reclassification 3.04, change of use 39 and general terms 23/29.")
                return {"scratch": scratch, "nudges": state.get("nudges", 0) + 1}
            cited = {str(x.get("chunk_id", "")).strip("[] ") for c in (args.get("claims") or []) if isinstance(c, dict)
                     for x in (c.get("citations") or []) if isinstance(x, dict)}
            competing = _competing_provisions(state, cited)
            if modifier_gate and route != "escalate" and competing and state.get("nudges", 0) < 2:
                rec.record("check", "competing_provision_gate", {"cited": sorted(cited)},
                           {"uncited": competing}, "blocked", 0.0)
                scratch.append("OBSERVATION: GATE - you retrieved other provisions that list the same activity "
                               f"but did not cite them: {', '.join(competing)}. Finish again, citing each of them "
                               "with an exact quote, and say in the position whether it applies and why.")
                return {"scratch": scratch, "nudges": state.get("nudges", 0) + 1}
            cat = args.get("determined_category")
            if cat is not None and cat not in CATEGORIES:
                cat = None
            claims = []
            for c in args.get("claims") or []:
                if not isinstance(c, dict):
                    continue
                cites = [x for x in (c.get("citations") or []) if isinstance(x, dict) and x.get("chunk_id")]
                claims.append({"text": str(c.get("text", ""))[:600], "citations": [
                    {"chunk_id": str(x["chunk_id"]).strip("[] "), "quote": str(x.get("quote", ""))[:400]} for x in cites]})
            draft = {"route": route, "determined_category": cat, "position": str(args.get("position", ""))[:1500],
                     "claims": claims}
            if route == "escalate":
                esc = args.get("escalation") or {}
                reason = esc.get("reason") if esc.get("reason") in ESC_REASONS else "insufficient_evidence"
                return {"scratch": scratch, "escalation": {"reason": reason,
                        "explanation": str(esc.get("explanation") or draft["position"])[:800]}, "draft": draft}
            return {"scratch": scratch, "draft": draft}

        tools = {
            "search_corpus": lambda query, doc=None, k=5, mode=None, **_: store.search(
                str(query), k=int(k or 5), mode=(mode or state.get("feedback", {}).get("mode") or "hybrid")
                if mode in (None, "hybrid", "keyword", "dense") else "hybrid", doc=doc),
            "get_clause": lambda ref, **_: store.get_clause(str(ref)),
            "follow_references": lambda chunk_id, **_: store.cross_references(str(chunk_id).strip("[] ")),
            "get_request_field": lambda name, **_: {"name": name, "value": state["request"].get(str(name), "unknown field")},
        }
        if name not in tools:
            scratch.append(f"OBSERVATION: unknown action {name!r}. Use one of {sorted(tools)} or finish.")
            return {"scratch": scratch}
        key = json.dumps([name, args], sort_keys=True, default=str).lower()
        if name in ("search_corpus", "get_clause") and key in state.get("done_calls", []):
            scratch.append("OBSERVATION: you already ran exactly this; its passages are in PASSAGES RETRIEVED SO FAR. "
                           "Search for something different, or finish.")
            return {"scratch": scratch}
        update["done_calls"] = state.get("done_calls", []) + [key]
        result, status, latency = rec.tool(name, tools[name], args if isinstance(args, dict) else {}, s.tool_timeout_seconds)
        TOOL_CALLS.labels(AGENT, name, status).inc()
        update["tool_calls"] = state.get("tool_calls", 0) + 1
        retrieved = dict(state.get("retrieved", {}))
        if name in ("search_corpus", "get_clause") and isinstance(result, list):
            update["retrieval_calls"] = state.get("retrieval_calls", 0) + 1
            query = args.get("query") or args.get("ref") or ""
            update["queries"] = state.get("queries", []) + [str(query)]
            db.add_passages(state["run_id"], result, str(query), name)
            new = [p for p in result if p["chunk_id"] not in retrieved]
            for p in result:
                retrieved.pop(p["chunk_id"], None)
                retrieved[p["chunk_id"]] = {"locator": p["locator"], "superseded": p.get("superseded", False),
                                            "clause_ref": p.get("clause_ref", ""), "text": p["text"]}
            obs = "\n".join(f"[{p['chunk_id']}] {p['locator']}" + ("" if p in new else " (already had)")
                            for p in result) if result else "no passages found"
            rec.record("tool", name, args, {"chunk_ids": [p["chunk_id"] for p in result],
                                            "locators": [p["locator"] for p in result]}, status, latency)
        else:
            obs = json.dumps(result, default=str)[:1500]
            rec.record("tool", name, args, result, status, latency)
        update["retrieved"] = retrieved
        scratch.append(f"OBSERVATION ({name}):\n{obs}")
        update["scratch"] = scratch
        return update

    def exhausted(state: State) -> dict:
        ids = list(state.get("retrieved", {}).keys())[:6]
        rec.record("check", "loop_bound", {"steps": state.get("steps", 0), "tool_calls": state.get("tool_calls", 0),
                                           "elapsed_s": round(time.time() - state["started"], 1)},
                   {"result": "budget exhausted"}, "exhausted", 0.0)
        return {"escalation": {"reason": "budget_exhausted",
                               "explanation": "The agent reached its step, tool-call or time limit before forming a "
                                              f"verified position. Passages reviewed: {', '.join(ids) or 'none'}."}}

    def after_guard(state: State) -> str:
        return "done" if state.get("escalation") else "intake"

    def after_intake(state: State) -> str:
        return "done" if state.get("escalation") else "decide"

    def after_decide(state: State) -> str:
        return "done" if state.get("escalation") else "act"

    def after_act(state: State) -> str:
        if state.get("draft") or state.get("escalation"):
            return "done"
        ok, _ = budget_left(state)
        return "decide" if ok else "exhausted"

    g = StateGraph(State)
    g.add_node("guard", guard)
    g.add_node("intake", intake)
    g.add_node("decide", decide)
    g.add_node("act", act)
    g.add_node("exhausted", exhausted)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", after_guard, {"done": END, "intake": "intake"})
    g.add_conditional_edges("intake", after_intake, {"done": END, "decide": "decide"})
    g.add_conditional_edges("decide", after_decide, {"done": END, "act": "act"})
    g.add_conditional_edges("act", after_act, {"done": END, "decide": "decide", "exhausted": "exhausted"})
    g.add_edge("exhausted", END)
    return g.compile()


def run_research(run_id: str, attempt: int = 0) -> None:
    """RQ job: research one run, then hand off to the verifier."""
    from ..queueing import enqueue_verify

    s = settings()
    from ..locks import acquire

    run = db.get_run(run_id)
    if run is None or run["status"] in ("completed", "escalated", "failed"):
        return
    if not acquire("research", run_id, attempt):
        return
    correlation_id.set(run_id)
    current_agent.set(AGENT)
    ctx = extract_context(run.get("trace_carrier"))
    t0 = time.time()
    rec = StepRecorder(run_id, AGENT, attempt)
    with tracer().start_as_current_span("agent:researcher", context=ctx) as span:
        span.set_attribute("run_id", run_id)
        span.set_attribute("attempt", attempt)
        db.update_run(run_id, status="running", stage="research", attempts=attempt)
        feedback = run.get("feedback_for_research") if attempt > 0 else None
        state: State = {"run_id": run_id, "attempt": attempt, "request": run["request"], "started": time.time(),
                        "scratch": [], "retrieved": {}, "steps": 0, "tool_calls": 0, "retrieval_calls": 0,
                        "nudges": 0, "queries": [], "feedback": feedback or {}}
        if feedback:
            prior = db.get_passages(run_id)
            old = (run.get("draft") or {}).get("draft") or {}
            cited = [x.get("chunk_id") for c in old.get("claims", []) for x in c.get("citations", [])]
            order = [c for c in cited if c in prior] + [c for c in prior if c not in cited]
            for cid in order[:8]:
                p = prior[cid]
                state["retrieved"][cid] = {"locator": p["locator"], "superseded": False,
                                           "clause_ref": p.get("clause_ref") or "", "text": p["text"]}
            state["retrieval_calls"] = 2
            state["scratch"].append("PREVIOUS DRAFT (rejected by the verifier): " +
                                    json.dumps({k: old.get(k) for k in ("route", "determined_category", "claims")})[:1500])
        outcome = "draft"
        try:
            final = build_graph(rec, run.get("prompt_versions")).invoke(state, {"recursion_limit": 4 * s.max_steps + 10})
        except Exception as e:  # noqa: BLE001 - a crashed agent must not leave the run hanging
            log(logger, logging.ERROR, "research crashed", run_id=run_id, error=repr(e))
            final = {**state, "escalation": {"reason": "agent_failure", "explanation": f"Research agent error: {type(e).__name__}"}}
            outcome = "error"
        handoff = {
            "attempt": attempt,
            "draft": final.get("draft"),
            "escalation": final.get("escalation"),
            "intake": final.get("intake"),
            "queries": final.get("queries", []),
            "research": {"steps": final.get("steps", 0), "tool_calls": final.get("tool_calls", 0),
                         "retrieval_calls": final.get("retrieval_calls", 0), "llm_calls": rec.llm_calls,
                         "cost_usd": round(rec.cost, 6), "seconds": round(time.time() - t0, 2)},
        }
        if final.get("escalation") and outcome != "error":
            outcome = "escalated"
        AGENT_RUNS.labels(AGENT, outcome).inc()
        AGENT_STEPS.labels(AGENT).observe(rec.step_no)
        AGENT_TOOLS.labels(AGENT).observe(rec.tool_calls)
        AGENT_LAT.labels(AGENT).observe(time.time() - t0)
        db.update_run(run_id, draft=handoff, status="verifying", stage="verify")
        enqueue_verify(run_id)
        log(logger, logging.INFO, "research handed off", run_id=run_id, outcome=outcome, steps=rec.step_no,
            tool_calls=rec.tool_calls, cost_usd=round(rec.cost, 6))
