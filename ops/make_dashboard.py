"""Generates ops/grafana/dashboards/triage.json. Run: python ops/make_dashboard.py"""
import json
import os

P = {"type": "prometheus", "uid": "prom"}
panels = []
y = 0


def row(title):
    global y
    panels.append({"type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
                   "id": len(panels) + 1, "panels": []})
    y += 1


def ts(title, targets, unit="short", w=8, h=8, x=None, stack=False):
    global y
    used = sum(p["gridPos"]["w"] for p in panels if p["gridPos"]["y"] == y and p["type"] != "row")
    if used + w > 24:
        y += h
        used = 0
    panels.append({
        "type": "timeseries", "title": title, "datasource": P, "id": len(panels) + 1,
        "gridPos": {"x": used if x is None else x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 10,
                                                               "stacking": {"mode": "normal" if stack else "none"}}},
                        "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        "targets": [{"datasource": P, "expr": e, "legendFormat": l, "refId": chr(65 + i)} for i, (e, l) in enumerate(targets)],
    })


def stat(title, expr, unit="short", w=4, h=4, legend=""):
    global y
    used = sum(p["gridPos"]["w"] for p in panels if p["gridPos"]["y"] == y and p["type"] != "row")
    if used + w > 24:
        y += 8 if any(p["gridPos"]["h"] == 8 and p["gridPos"]["y"] == y for p in panels) else h
        used = 0
    panels.append({"type": "stat", "title": title, "datasource": P, "id": len(panels) + 1,
                   "gridPos": {"x": used, "y": y, "w": w, "h": h},
                   "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
                   "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "none", "graphMode": "area"},
                   "targets": [{"datasource": P, "expr": expr, "legendFormat": legend, "refId": "A"}]})


def nl(h=8):
    global y
    y += h


Q = lambda q, m: f"histogram_quantile({q}, sum by (le) (rate({m}_bucket[2m])))"

row("Service level (D5, D6)")
ts("Run end-to-end latency (submission to result)", [(Q(0.5, "run_e2e_seconds"), "p50"), (Q(0.95, "run_e2e_seconds"), "p95"),
                                                     ("60", "SLO p95 target")], "s")
ts("API latency (excluding /metrics)", [
    ('histogram_quantile(0.5, sum by (le) (rate(http_request_duration_seconds_bucket{route!="/metrics"}[2m])))', "p50"),
    ('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route!="/metrics"}[2m])))', "p95")], "s")
ts("Error rate (5xx share of API requests)", [
    ('sum(rate(http_request_duration_seconds_count{status=~"5.."}[2m])) / clamp_min(sum(rate(http_request_duration_seconds_count[2m])), 1e-9)', "5xx share")],
   "percentunit")
nl()
ts("Throughput", [("sum by (outcome) (rate(dispute_submissions_total[1m]))", "submitted {{outcome}}"),
                  ("sum(rate(run_routes_total[2m]))", "runs finished")], "reqps")
ts("Availability (scrape up) by service", [("avg by (job) (up)", "{{job}}")], "percentunit")
ts("Queue depth", [("queue_depth", "{{queue}}")])
nl()
ts("CPU per container", [("rate(process_cpu_seconds_total[1m])", "{{job}} {{instance}}")], "percentunit")
ts("Memory per container", [("process_resident_memory_bytes", "{{job}} {{instance}}")], "bytes")
ts("Container uptime", [("time() - process_start_time_seconds", "{{job}} {{instance}}")], "s")
nl()
row("Agents (A6)")
ts("Task success rate by agent", [
    ('sum by (agent) (rate(agent_runs_total{outcome=~"draft|pass"}[5m])) / clamp_min(sum by (agent) (rate(agent_runs_total[5m])), 1e-9)', "{{agent}}")],
   "percentunit")
ts("Steps and tool calls per run (p50)", [
    ("histogram_quantile(0.5, sum by (le, agent) (rate(agent_steps_per_run_bucket[5m])))", "steps {{agent}}"),
    ("histogram_quantile(0.5, sum by (le, agent) (rate(agent_tool_calls_per_run_bucket[5m])))", "tool calls {{agent}}")])
ts("Retry rate (model-call retries per call)", [
    ("sum by (agent) (rate(agent_retries_total[5m])) / clamp_min(sum by (agent) (rate(agent_llm_calls_total[5m])), 1e-9)", "{{agent}}")],
   "percentunit")
nl()
ts("Agent latency p95 (whole task)", [("histogram_quantile(0.95, sum by (le, agent) (rate(agent_run_latency_seconds_bucket[5m])))", "{{agent}}")], "s")
ts("Per-step latency p95", [("histogram_quantile(0.95, sum by (le, agent, name) (rate(agent_step_latency_seconds_bucket[5m])))", "{{agent}} {{name}}")], "s")
ts("Routes and escalations", [("sum by (route) (increase(run_routes_total[15m]))", "{{route}}"),
                              ("sum by (reason) (increase(run_escalations_total[15m]))", "escalation: {{reason}}")])
nl()
row("Model provider, cost and guardrails (A5, L4, L5)")
ts("Provider calls by outcome", [("sum by (provider, outcome) (rate(llm_requests_total[1m]))", "{{provider}} {{outcome}}")], "reqps")
ts("Circuit breaker state (0 closed, 1 half-open, 2 open)", [("llm_breaker_state", "{{provider}}")])
ts("Cost by agent and step (USD, last hour)", [("sum by (agent, step) (increase(agent_cost_usd_total[1h]))", "{{agent}} {{step}}")], "currencyUSD")
nl()
ts("Tokens per second by agent", [("sum by (agent, kind) (rate(agent_tokens_total[5m]))", "{{agent}} {{kind}}")])
ts("Cost per run (p50, p95)", [(Q(0.5, "run_cost_usd"), "p50"), (Q(0.95, "run_cost_usd"), "p95")], "currencyUSD")
ts("Guardrails and verification", [("sum by (kind) (increase(guardrail_events_total[15m]))", "guard {{kind}}"),
                                   ("sum by (outcome) (increase(verification_outcomes_total[15m]))", "verify {{outcome}}"),
                                   ("sum by (reason) (increase(quarantined_requests_total[15m]))", "quarantined {{reason}}")])
nl()
row("Quality, feedback, data freshness, caching (L6, D2, D7)")
ts("Live quality (sampled runs)", [("avg by (metric) (live_quality_last)", "{{metric}}")], "percentunit")
ts("Feedback satisfaction", [("feedback_satisfaction_ratio", "satisfied share")], "percentunit")
ts("Cache", [("sum by (result) (rate(retrieval_cache_total[5m]))", "retrieval {{result}}"),
             ('sum(rate(dispute_submissions_total{outcome="cached"}[5m]))', "whole-run cache hits")], "reqps")
nl()
stat("Index age", "index_age_seconds", "s")
stat("Chunks indexed", "index_chunks_total")
stat("Ingest pages/s", "ingest_pages_per_second")
stat("Ingest chunks/s", "ingest_chunks_per_second")
stat("Redis up", "redis_up")
stat("Postgres up", "pg_up")

dash = {"title": "Tariff Dispute Triage", "uid": "triage", "schemaVersion": 39, "version": 1, "refresh": "10s",
        "time": {"from": "now-30m", "to": "now"}, "timezone": "browser", "panels": panels, "tags": ["mlops"],
        "templating": {"list": []}, "annotations": {"list": []}}
out = os.path.join(os.path.dirname(__file__), "grafana", "dashboards", "triage.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(dash, f, indent=1)
print(f"wrote {out} with {len(panels)} panels")
