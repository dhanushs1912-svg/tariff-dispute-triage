"""Batch evaluation over eval/scenarios.yaml against the running API (L2, L3).

    docker compose run --rm eval --variant v2_gate --research v2 --gate on
    docker compose run --rm eval --variant v1_gate --research v1 --gate on
    docker compose run --rm eval --compare v1_gate v2_gate

Metrics (definitions in docs/evaluation.md and triage/quality.py):
  route_accuracy        expected route exactly
  route_acceptable      expected or an accepted alternative route
  category_accuracy     determined category matches (scenarios with an expected category)
  support_cited         share of expected supporting passages that the final answer cites
  support_retrieved     share of expected supporting passages the agent retrieved at all
  groundedness, context_relevance, faithfulness, hallucination_rate   per run, averaged over runs with claims
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import yaml

ROOT = os.environ.get("EVAL_DIR", "/app/eval")
API = os.environ.get("EVAL_API_URL", "http://api:8000")


def load_scenarios() -> list[dict]:
    with open(os.path.join(ROOT, "scenarios.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["scenarios"]


def anchor_hit(anchor: dict, passages: list[dict]) -> bool:
    phrase = " ".join(anchor["phrase"].lower().split())
    return any(p.get("clause_ref") == anchor["ref"] and phrase in " ".join(p["text"].lower().split()) for p in passages)


def run_one(client: httpx.Client, sc: dict, variant: str, overrides: dict, timeout: float) -> dict:
    headers = {"X-Client-Id": f"eval-{variant}"[:60], "Cache-Control": "no-cache",
               "X-Eval-Overrides": json.dumps(overrides)}
    t0 = time.time()
    while True:
        r = client.post(f"{API}/v1/disputes", json=sc["request"], headers=headers)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("retry-after", "10")) + 1)
            continue
        break
    if r.status_code not in (200, 202):
        return {"id": sc["id"], "error": f"submit {r.status_code}: {r.text[:200]}"}
    run_id = r.json()["run_id"]
    while time.time() - t0 < timeout:
        st = client.get(f"{API}/v1/runs/{run_id}", headers={"X-Client-Id": headers["X-Client-Id"]})
        if st.status_code == 200 and st.json().get("result"):
            break
        time.sleep(2)
    else:
        return {"id": sc["id"], "run_id": run_id, "error": "timeout"}
    trace = client.get(f"{API}/v1/runs/{run_id}/trace").json()
    return score(sc, run_id, trace, time.time() - t0)


def score(sc: dict, run_id: str, trace: dict, wall: float) -> dict:
    from .quality import context_relevance
    from .retrieval import get_store

    res = trace["result"] or {}
    passages = trace["passages"]
    by_id = {p["chunk_id"]: p for p in passages}
    cited = [by_id[c["chunk_id"]] for c in res.get("citations", []) if c["chunk_id"] in by_id]
    support = sc.get("support") or []
    route = res.get("route")
    out = {
        "id": sc["id"], "run_id": run_id, "tags": sc.get("tags", []),
        "expected_route": sc["expected_route"], "route": route,
        "route_correct": route == sc["expected_route"],
        "route_acceptable": route == sc["expected_route"] or route in (sc.get("acceptable_routes") or []),
        "expected_category": sc.get("expected_category"), "category": res.get("determined_category"),
        "escalation": (res.get("escalation") or {}).get("reason"),
        "support_cited": (sum(anchor_hit(a, cited) for a in support) / len(support)) if support else None,
        "support_retrieved": (sum(anchor_hit(a, passages) for a in support) / len(support)) if support else None,
        "latency_s": round(res.get("latency_ms", 0) / 1000, 2), "wall_s": round(wall, 1),
        "cost_usd": trace["totals"]["cost_usd"],
        "tokens": trace["totals"]["prompt_tokens"] + trace["totals"]["completion_tokens"],
        "steps": sum(a["steps"] for a in trace["totals"]["by_agent"].values()),
        "tool_calls": sum(a["tool_calls"] for a in trace["totals"]["by_agent"].values()),
        "attempts": (res.get("verification") or {}).get("attempts"),
        "prompt_versions": res.get("prompt_versions"),
    }
    if sc.get("expected_category") is not None:
        out["category_correct"] = res.get("determined_category") == sc["expected_category"]
    if sc.get("expected_escalation"):
        out["escalation_correct"] = out["escalation"] == sc["expected_escalation"]
    claims = res.get("claims") or []
    ver = res.get("verification") or {}
    checks = ver.get("checks") or {}
    judge = ver.get("judge") or {}
    handoff = trace.get("handoff_to_verifier") or {}
    if claims:
        sup = [c.get("supported") for c in claims if c.get("supported") is not None]
        out["groundedness"] = (sum(1 for x in sup if x) / len(sup)) if sup else None
        out["faithfulness"] = 1.0 if judge.get("conclusion_follows") else 0.0 if "conclusion_follows" in judge else None
        out["hallucination_rate"] = checks.get("hallucination_rate")
        texts = [p["text"] for p in cited] or [by_id[i]["text"] for c in claims for i in c.get("citation_ids", []) if i in by_id]
        out["context_relevance"] = context_relevance(get_store().embedder, sc["request"]["description"], texts)
    elif (handoff.get("draft") or {}).get("claims"):
        out["hallucination_rate"] = checks.get("hallucination_rate")
    return out


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]

    def mean(key, subset=None):
        vals = [r[key] for r in (subset or ok) if r.get(key) is not None]
        return round(statistics.mean(vals), 3) if vals else None

    cat = [r for r in ok if "category_correct" in r]
    esc = [r for r in ok if "escalation_correct" in r]
    case41 = [r for r in ok if "case41" in r["tags"]]
    lat = sorted(r["latency_s"] for r in ok)
    return {
        "n": len(rows), "errors": len(rows) - len(ok),
        "route_accuracy": mean("route_correct"), "route_acceptable": mean("route_acceptable"),
        "category_accuracy": round(sum(r["category_correct"] for r in cat) / len(cat), 3) if cat else None,
        "escalation_accuracy": round(sum(r["escalation_correct"] for r in esc) / len(esc), 3) if esc else None,
        "support_cited": mean("support_cited"), "support_retrieved": mean("support_retrieved"),
        "groundedness": mean("groundedness"), "context_relevance": mean("context_relevance"),
        "faithfulness": mean("faithfulness"), "hallucination_rate": mean("hallucination_rate"),
        "case41_route": case41[0]["route"] if case41 else None,
        "case41_support_cited": case41[0]["support_cited"] if case41 else None,
        "mean_cost_usd": mean("cost_usd"), "cost_per_100_runs_usd": round((mean("cost_usd") or 0) * 100, 4),
        "mean_tokens": mean("tokens"), "mean_steps": mean("steps"), "mean_tool_calls": mean("tool_calls"),
        "p50_latency_s": lat[len(lat) // 2] if lat else None,
        "p95_latency_s": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
    }


def write_report(variant: str, rows: list[dict], summary: dict, meta: dict) -> None:
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", f"{variant}.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(ROOT, "results", f"{variant}_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"variant": variant, **meta, "summary": summary}, f, indent=2)
    lines = [f"# Evaluation: {variant}", "", f"Settings: `{json.dumps(meta)}`", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary.items()]
    lines += ["", "| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['id']} | | error: {r['error']} | | | | | | | |")
            continue
        lines.append(f"| {r['id']} | {r['expected_route']} | {r['route']} | {'yes' if r['route_correct'] else ('ok' if r['route_acceptable'] else 'no')} "
                     f"| {r.get('category')} | {r.get('support_cited')} | {r.get('groundedness')} | {r.get('hallucination_rate')} "
                     f"| {r['cost_usd']} | {r['latency_s']} |")
    with open(os.path.join(ROOT, "results", f"{variant}_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def compare(a: str, b: str) -> None:
    sa = json.load(open(os.path.join(ROOT, "results", f"{a}_summary.json")))["summary"]
    sb = json.load(open(os.path.join(ROOT, "results", f"{b}_summary.json")))["summary"]
    lines = [f"# {a} vs {b}", "", f"| metric | {a} | {b} | change |", "|---|---|---|---|"]
    for k in sa:
        va, vb = sa[k], sb.get(k)
        delta = round(vb - va, 3) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool) else ""
        lines.append(f"| {k} | {va} | {vb} | {delta} |")
    out = os.path.join(ROOT, "results", f"compare_{a}_vs_{b}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="default")
    ap.add_argument("--research", choices=["v1", "v2"], default="v2")
    ap.add_argument("--gate", choices=["on", "off"], default="on")
    ap.add_argument("--only", default="")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=420)
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--merge", nargs="+", help="combine result files of the same settings into --variant")
    args = ap.parse_args()
    if args.compare:
        compare(*args.compare)
        return
    if args.merge:
        rows, order = {}, [s["id"] for s in load_scenarios()]
        for part in args.merge:
            for line in open(os.path.join(ROOT, "results", f"{part}.jsonl"), encoding="utf-8"):
                r = json.loads(line)
                rows[r["id"]] = r
        keep = set(args.only.split(",")) if args.only else None
        merged = [rows[i] for i in order if i in rows and (keep is None or i in keep)]
        meta = {**json.load(open(os.path.join(ROOT, "results", f"{args.merge[0]}_summary.json"))), "merged_from": args.merge}
        meta.pop("summary", None)
        meta.pop("variant", None)
        summary = summarize(merged)
        write_report(args.variant, merged, summary, meta)
        print(json.dumps(summary, indent=2))
        return
    scenarios = load_scenarios()
    if args.only:
        keep = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in keep]
    overrides = {"research": args.research, "modifier_gate": args.gate == "on"}
    rows: list[dict] = []
    with httpx.Client(timeout=30) as client, ThreadPoolExecutor(args.concurrency) as pool:
        futures = [pool.submit(run_one, client, sc, args.variant, overrides, args.timeout) for sc in scenarios]
        for fut in futures:
            r = fut.result()
            rows.append(r)
            print(json.dumps({k: r.get(k) for k in ("id", "route", "expected_route", "route_correct", "support_cited", "error")}),
                  flush=True)
    summary = summarize(rows)
    write_report(args.variant, rows, summary, overrides)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
