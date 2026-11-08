"""Public API (F1, A4, D1, D7, L6, F8).

Runs take tens of seconds, so submission is asynchronous: POST /v1/disputes validates the request
against the data contract, enqueues it and returns a run id at once (202); the caller polls
GET /v1/runs/{id}. Polling was chosen over callbacks because the web client and Locust run on the
officer's machine with no public callback URL, and polling is retry-safe. A Redis queue sits
between submission and execution.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import ValidationError

from . import db, locks
from .cache import get_redis, index_version, rate_limited, request_hash, run_cache_get
from .config import settings
from .contracts import CONTRACT_VERSION, DisputeRequest, FeedbackRequest
from .obs import correlation_id, current_trace_id, inject_context, log, setup_logging, setup_tracing, tracer
from .prompts import active_versions
from .queueing import depths, enqueue_research, enqueue_verify

logger = setup_logging("api")
setup_tracing("api")
s = settings()

HTTP_LAT = Histogram("http_request_duration_seconds", "API latency", ["route", "method", "status"],
                     buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
SUBMIT = Counter("dispute_submissions_total", "Submissions by outcome", ["outcome"])
QUARANTINED = Counter("quarantined_requests_total", "Requests rejected at the ingestion boundary", ["reason"])
QUEUE_DEPTH = Gauge("queue_depth", "Jobs waiting", ["queue"])
RUNS_BY_STATUS = Gauge("runs_by_status", "Runs in the database by status", ["status"])
INDEX_AGE = Gauge("index_age_seconds", "Seconds since the index was last built")
INDEX_CHUNKS = Gauge("index_chunks_total", "Chunks in the index")
INDEX_PAGES_PS = Gauge("ingest_pages_per_second", "Ingest throughput, pages per second (last build)")
INDEX_CHUNKS_PS = Gauge("ingest_chunks_per_second", "Ingest throughput, chunks per second (last build)")
FEEDBACK_RATE = Gauge("feedback_satisfaction_ratio", "Share of feedback marked satisfactory")
WATCHDOG = Counter("watchdog_actions_total", "Stalled runs handled", ["action"])

app = FastAPI(title="Electricity Tariff Dispute Triage API", version="1.0.0",
              description="Submit a billing dispute; poll for a cited tariff position. Never revises a bill.")
FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics,health")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")
_CLIENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def client_id(request: Request) -> str:
    cid = request.headers.get("x-client-id", "")
    if _CLIENT_RE.match(cid):
        return cid
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def observe(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex[:16]
    correlation_id.set(cid)
    t0 = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    HTTP_LAT.labels(path, request.method, str(response.status_code)).observe(time.perf_counter() - t0)
    response.headers["x-correlation-id"] = cid
    return response


@app.on_event("startup")
def startup() -> None:
    db.init_schema()
    threading.Thread(target=_background, daemon=True).start()
    log(logger, logging.INFO, "api started", contract=CONTRACT_VERSION)


def _limited(request: Request, bucket: str, limit: int):
    limited, reset = rate_limited(client_id(request), bucket, limit)
    if limited:
        SUBMIT.labels("rate_limited").inc() if bucket == "submit" else None
        return JSONResponse(status_code=429, headers={"Retry-After": str(reset)},
                            content={"error": "rate_limited", "bucket": bucket, "limit_per_minute": limit,
                                     "retry_after_seconds": reset})
    return None


@app.post("/v1/disputes", status_code=202)
async def submit(request: Request):
    raw = await request.body()
    return await run_in_threadpool(_submit, request, raw)


def _submit(request: Request, raw: bytes):
    if (resp := _limited(request, "submit", s.rate_limit_submit_per_min)) is not None:
        return resp
    cid = client_id(request)
    try:
        payload = json.loads(raw or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        qid = db.quarantine(cid, {"raw": raw[:4000].decode("utf-8", "replace")},
                            [{"loc": ["body"], "msg": f"invalid JSON: {e}", "type": "json_invalid"}])
        QUARANTINED.labels("invalid_json").inc()
        SUBMIT.labels("rejected").inc()
        return JSONResponse(status_code=422, content={"error": "validation_failed", "quarantine_id": qid,
                                                      "agent_run_started": False, "errors": [{"loc": ["body"], "msg": "invalid JSON"}]})
    try:
        req = DisputeRequest.model_validate(payload)
    except ValidationError as e:
        errors = [{"loc": list(x["loc"]), "msg": x["msg"], "type": x["type"],
                   "input": x.get("input") if not isinstance(x.get("input"), (dict, list)) else None}
                  for x in e.errors(include_url=False)]
        qid = db.quarantine(cid, payload, errors)
        QUARANTINED.labels(errors[0]["type"] if errors else "unknown").inc()
        SUBMIT.labels("rejected").inc()
        log(logger, logging.INFO, "request quarantined", quarantine_id=qid, errors=len(errors))
        return JSONResponse(status_code=422, content={"error": "validation_failed", "contract": CONTRACT_VERSION,
                                                      "quarantine_id": qid, "agent_run_started": False, "errors": errors})

    data = req.model_dump(mode="json")
    overrides = None
    if os.environ.get("ALLOW_EVAL_OVERRIDES", "false").lower() == "true" and request.headers.get("x-eval-overrides"):
        try:
            overrides = json.loads(request.headers["x-eval-overrides"])
        except json.JSONDecodeError:
            overrides = None
    versions = active_versions(overrides)
    rhash = request_hash(data, versions, index_version())
    run_id = "run_" + uuid.uuid4().hex[:20]
    correlation_id.set(run_id)
    no_cache = "no-cache" in request.headers.get("cache-control", "").lower()
    if s.run_cache_enabled and not no_cache:
        hit = run_cache_get(rhash)
        if hit:
            result = {**hit, "run_id": run_id, "cached_from": hit.get("run_id"), "latency_ms": 0}
            db.create_cached_run(run_id, cid, data, rhash, result)
            SUBMIT.labels("cached").inc()
            return JSONResponse(status_code=200, content={"run_id": run_id, "status": "completed", "cached": True,
                                                          "status_url": f"/v1/runs/{run_id}", "result": result})
    with tracer().start_as_current_span("submit") as span:
        span.set_attribute("run_id", run_id)
        db.create_run(run_id, cid, data, rhash, versions, inject_context(), current_trace_id())
        enqueue_research(run_id, 0)
    SUBMIT.labels("accepted").inc()
    log(logger, logging.INFO, "run accepted", run_id=run_id, client=cid)
    return {"run_id": run_id, "status": "queued", "status_url": f"/v1/runs/{run_id}", "cached": False}


def _public(run: dict) -> dict:
    out = {"run_id": run["run_id"], "status": run["status"], "stage": run["stage"], "attempts": run["attempts"],
           "cached": run["cached"], "created_at": run["created_at"], "finished_at": run["finished_at"]}
    if run["status"] in ("completed", "escalated", "failed"):
        out["result"] = run["result"]
    return out


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str, request: Request):
    if (resp := _limited(request, "read", s.rate_limit_read_per_min)) is not None:
        return resp
    run = db.get_run(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": "unknown run"})
    return _public(run)


@app.get("/v1/runs/{run_id}/trace")
def run_trace(run_id: str):
    """Reconstruct a run end to end: every tool call, query, passage, prompt version, per-step latency and cost."""
    run = db.get_run(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": "unknown run"})
    steps = db.get_steps(run_id)
    passages = db.get_passages(run_id)
    by_agent: dict = {}
    for st in steps:
        a = by_agent.setdefault(st["agent"], {"steps": 0, "tool_calls": 0, "llm_calls": 0, "latency_ms": 0,
                                              "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "retries": 0})
        a["steps"] += 1
        a["tool_calls"] += st["kind"] == "tool"
        a["llm_calls"] += st["kind"] == "llm"
        a["latency_ms"] += st["latency_ms"]
        a["cost_usd"] = round(a["cost_usd"] + st["cost_usd"], 8)
        a["prompt_tokens"] += st["prompt_tokens"]
        a["completion_tokens"] += st["completion_tokens"]
        a["retries"] += st["retries"]
    return {
        "run_id": run_id, "status": run["status"], "trace_id": run["trace_id"],
        "jaeger_url": f"{os.environ.get('JAEGER_UI_URL', '').rstrip('/')}/trace/{run['trace_id']}" if run["trace_id"] else None,
        "request": run["request"], "prompt_versions": run["prompt_versions"], "intake": run["intake"],
        "handoff_to_verifier": run["draft"], "result": run["result"],
        "totals": {"cost_usd": round(sum(st["cost_usd"] for st in steps), 8),
                   "prompt_tokens": sum(st["prompt_tokens"] for st in steps),
                   "completion_tokens": sum(st["completion_tokens"] for st in steps),
                   "e2e_ms": int(((run["finished_at"] or time.time()) - run["created_at"]) * 1000), "by_agent": by_agent},
        "steps": [{k: st[k] for k in ("agent", "attempt", "step_no", "kind", "name", "status", "latency_ms",
                                      "prompt_tokens", "completion_tokens", "cost_usd", "prompt_version", "retries",
                                      "input", "output")} for st in steps],
        "passages": [{k: p[k] for k in ("chunk_id", "doc_id", "clause_ref", "locator", "query", "tool", "score", "text")}
                     for p in passages.values()],
    }


@app.post("/v1/runs/{run_id}/feedback")
def feedback(run_id: str, body: FeedbackRequest, request: Request):
    if db.get_run(run_id) is None:
        return JSONResponse(status_code=404, content={"error": "unknown run"})
    with db.cursor() as cur:
        cur.execute("INSERT INTO feedback (run_id, client_id, satisfactory, reason, created_at) VALUES (%s,%s,%s,%s,%s)"
                    " RETURNING id", (run_id, client_id(request), body.satisfactory, body.reason, time.time()))
        fid = cur.fetchone()["id"]
    return {"feedback_id": fid, "run_id": run_id}


@app.get("/v1/feedback/summary")
def feedback_summary():
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, COALESCE(AVG(CASE WHEN satisfactory THEN 1.0 ELSE 0.0 END), 0) AS rate FROM feedback")
        total = cur.fetchone()
        cur.execute("SELECT r.route, COUNT(*) AS n, AVG(CASE WHEN f.satisfactory THEN 1.0 ELSE 0.0 END) AS rate"
                    " FROM feedback f JOIN runs r ON r.run_id = f.run_id GROUP BY r.route")
        by_route = cur.fetchall()
        cur.execute("SELECT reason, COUNT(*) AS n FROM feedback WHERE NOT satisfactory GROUP BY reason ORDER BY n DESC LIMIT 10")
        reasons = cur.fetchall()
        cur.execute("SELECT date_trunc('hour', to_timestamp(scored_at)) AS hour, AVG(groundedness) AS groundedness,"
                    " AVG(context_relevance) AS context_relevance, AVG(faithfulness) AS faithfulness,"
                    " AVG(hallucination_rate) AS hallucination_rate, COUNT(*) AS n FROM live_scores"
                    " GROUP BY 1 ORDER BY 1 DESC LIMIT 48")
        live = cur.fetchall()
    return {"total": total["n"], "satisfactory_rate": float(total["rate"]), "by_route": by_route,
            "top_unsatisfactory_reasons": reasons, "live_quality_by_hour": live}


@app.get("/v1/quarantine")
def quarantine_list(limit: int = 20):
    with db.cursor() as cur:
        cur.execute("SELECT id, client_id, errors, payload, received_at FROM quarantine ORDER BY id DESC LIMIT %s",
                    (max(1, min(limit, 200)),))
        return {"items": cur.fetchall()}


@app.get("/v1/contract")
def contract():
    return {"version": CONTRACT_VERSION, "schema": DisputeRequest.model_json_schema()}


@app.get("/v1/index")
def index_info():
    with db.cursor() as cur:
        cur.execute("SELECT * FROM index_meta ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return {"index_version": index_version(), "last_build": row}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    checks = {}
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {e}"
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = f"error: {e}"
    checks["index"] = "ok" if index_version() != "none" else "not built"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "checks": checks})


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root():
    return RedirectResponse("/ui/")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(os.path.join(WEB_DIR, "favicon.svg"), media_type="image/svg+xml")


def _escalate_stalled(run: dict) -> None:
    full = db.get_run(run["run_id"])
    result = {
        "run_id": full["run_id"], "route": "escalated-to-officer", "dispute_type": None,
        "billed_category": full["request"]["billed_category"], "determined_category": None,
        "position": "Escalated to a grievance officer: the agent workers stopped responding during this run, so no "
                    "verified position was formed.",
        "claims": [], "citations": [],
        "escalation": {"reason": "agent_failure", "explanation": f"run stalled at stage {full['stage']} after a resume"},
        "verification": {"decision": "escalate"}, "prompt_versions": full["prompt_versions"] or {},
        "cost_usd": 0.0, "latency_ms": int((time.time() - full["created_at"]) * 1000),
        "disclaimer": "Recommendation only. This service never revises or recomputes a bill; the grievance officer makes the decision.",
    }
    db.update_run(full["run_id"], status="escalated", stage="done", result=result, route="escalated-to-officer",
                  finished_at=time.time(), error="stalled")


def _watchdog() -> None:
    r = get_redis()
    if not r.set("watchdog:lock", "1", nx=True, ex=14):
        return
    for run in db.stale_runs(s.run_deadline_seconds):
        if run["resumes"] < 1:
            locks.release_all(run["run_id"])
            db.update_run(run["run_id"], resumes=run["resumes"] + 1)
            if run["stage"] == "verify":
                enqueue_verify(run["run_id"])
            else:
                enqueue_research(run["run_id"], run["attempts"])
            WATCHDOG.labels("resumed").inc()
            log(logger, logging.WARNING, "stalled run resumed", run_id=run["run_id"], stage=run["stage"])
        else:
            _escalate_stalled(run)
            WATCHDOG.labels("escalated").inc()
            log(logger, logging.WARNING, "stalled run escalated", run_id=run["run_id"], stage=run["stage"])


def _gauges() -> None:
    for q, n in depths().items():
        QUEUE_DEPTH.labels(q).set(n)
    with db.cursor() as cur:
        cur.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status")
        for row in cur.fetchall():
            RUNS_BY_STATUS.labels(row["status"]).set(row["n"])
        cur.execute("SELECT * FROM index_meta ORDER BY id DESC LIMIT 1")
        meta = cur.fetchone()
        cur.execute("SELECT COALESCE(AVG(CASE WHEN satisfactory THEN 1.0 ELSE 0.0 END), 0) AS rate FROM feedback")
        FEEDBACK_RATE.set(float(cur.fetchone()["rate"]))
    if meta:
        INDEX_AGE.set(time.time() - meta["built_at"])
        INDEX_CHUNKS.set(meta["chunks_total"])
        INDEX_PAGES_PS.set(meta["pages_per_second"])
        INDEX_CHUNKS_PS.set(meta["chunks_per_second"])


def _background() -> None:
    while True:
        try:
            _gauges()
            _watchdog()
        except Exception as e:  # noqa: BLE001 - background upkeep must keep running
            log(logger, logging.WARNING, "background task error", error=repr(e))
        time.sleep(10)
