"""Prometheus metrics for the agent workers (A6, L5, L6)."""
from prometheus_client import Counter, Gauge, Histogram

LAT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 45, 60, 90, 120, 180, 300)

AGENT_RUNS = Counter("agent_runs_total", "Agent task outcomes", ["agent", "outcome"])
AGENT_STEPS = Histogram("agent_steps_per_run", "Steps per agent run", ["agent"], buckets=(1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20))
AGENT_TOOLS = Histogram("agent_tool_calls_per_run", "Tool calls per agent run", ["agent"], buckets=(0, 1, 2, 3, 4, 5, 6, 8, 10, 12))
AGENT_LAT = Histogram("agent_run_latency_seconds", "Agent task latency", ["agent"], buckets=LAT_BUCKETS)
STEP_LAT = Histogram("agent_step_latency_seconds", "Latency per step", ["agent", "kind", "name"], buckets=LAT_BUCKETS)
AGENT_RETRIES = Counter("agent_retries_total", "Model-call retries attributed to the agent", ["agent"])
AGENT_LLM_CALLS = Counter("agent_llm_calls_total", "Model calls made by the agent", ["agent"])
TOOL_CALLS = Counter("agent_tool_calls_total", "Tool calls", ["agent", "tool", "outcome"])
RUN_E2E = Histogram("run_e2e_seconds", "Submission to final result", ["route"], buckets=LAT_BUCKETS)
RUN_COST = Histogram("run_cost_usd", "Cost per completed run (USD)", buckets=(0, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1))
STEP_COST = Counter("agent_cost_usd_total", "Model cost by agent and step (USD)", ["agent", "step"])
TOKENS = Counter("agent_tokens_total", "Tokens by agent", ["agent", "kind"])
ROUTES = Counter("run_routes_total", "Final routes", ["route"])
ESCALATIONS = Counter("run_escalations_total", "Escalations by reason", ["reason"])
VERIFY = Counter("verification_outcomes_total", "Verifier decisions", ["outcome"])
GUARD = Counter("guardrail_events_total", "Guardrail hits", ["kind"])
LIVE_SCORE = Histogram("live_quality_score", "Sampled live quality scores", ["metric"],
                       buckets=(0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
LIVE_LAST = Gauge("live_quality_last", "Most recent sampled live score", ["metric"])
WORKER_UP = Gauge("worker_busy", "1 while the worker is processing a job", ["agent"])
CACHE = Counter("retrieval_cache_total", "Retrieval cache lookups", ["result"])
