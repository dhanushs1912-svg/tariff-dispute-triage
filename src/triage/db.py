"""Postgres access: run log, steps, retrieved passages, quarantine, feedback, live scores, index metadata."""
import json
import threading
import time
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'queued',
    request JSONB NOT NULL,
    request_hash TEXT NOT NULL,
    intake JSONB,
    draft JSONB,
    result JSONB,
    route TEXT,
    attempts INT NOT NULL DEFAULT 0,
    resumes INT NOT NULL DEFAULT 0,
    feedback_for_research JSONB,
    prompt_versions JSONB,
    trace_carrier JSONB,
    trace_id TEXT,
    cached BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    finished_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS runs_status_idx ON runs(status, updated_at);
CREATE TABLE IF NOT EXISTS steps (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    attempt INT NOT NULL DEFAULT 0,
    step_no INT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    input JSONB,
    output JSONB,
    status TEXT NOT NULL,
    latency_ms INT NOT NULL DEFAULT 0,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    prompt_version TEXT,
    retries INT NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS steps_run_idx ON steps(run_id, id);
CREATE TABLE IF NOT EXISTS passages (
    run_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    clause_ref TEXT,
    locator TEXT NOT NULL,
    text TEXT NOT NULL,
    score DOUBLE PRECISION,
    query TEXT,
    tool TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, chunk_id)
);
CREATE TABLE IF NOT EXISTS quarantine (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    payload JSONB,
    errors JSONB NOT NULL,
    received_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    satisfactory BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS live_scores (
    run_id TEXT PRIMARY KEY,
    groundedness DOUBLE PRECISION,
    context_relevance DOUBLE PRECISION,
    faithfulness DOUBLE PRECISION,
    hallucination_rate DOUBLE PRECISION,
    scored_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS index_meta (
    id BIGSERIAL PRIMARY KEY,
    built_at DOUBLE PRECISION NOT NULL,
    embed_model TEXT NOT NULL,
    docs JSONB NOT NULL,
    chunks_total INT NOT NULL,
    chunks_embedded INT NOT NULL,
    chunks_deleted INT NOT NULL,
    seconds DOUBLE PRECISION NOT NULL,
    pages_per_second DOUBLE PRECISION NOT NULL,
    chunks_per_second DOUBLE PRECISION NOT NULL,
    index_version TEXT NOT NULL
);
"""

_local = threading.local()


def _conn() -> psycopg.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        conn = psycopg.connect(settings().database_url, autocommit=True, row_factory=dict_row, connect_timeout=5)
        _local.conn = conn
    return conn


@contextmanager
def cursor():
    try:
        conn = _conn()
        with conn.cursor() as cur:
            yield cur
    except psycopg.OperationalError:
        _local.conn = None
        raise


def init_schema(retries: int = 30) -> None:
    for i in range(retries):
        try:
            with cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(424242)")
                try:
                    cur.execute(SCHEMA)
                finally:
                    cur.execute("SELECT pg_advisory_unlock(424242)")
            return
        except psycopg.OperationalError:
            time.sleep(min(2.0, 0.2 * (i + 1)))
    raise RuntimeError("database not reachable")


def J(value):
    return Jsonb(value) if value is not None else None


def create_run(run_id: str, client_id: str, request: dict, request_hash: str, prompt_versions: dict,
               trace_carrier: dict, trace_id: str | None) -> None:
    now = time.time()
    with cursor() as cur:
        cur.execute(
            "INSERT INTO runs (run_id, client_id, status, stage, request, request_hash, prompt_versions, trace_carrier,"
            " trace_id, created_at, updated_at) VALUES (%s,%s,'queued','queued',%s,%s,%s,%s,%s,%s,%s)",
            (run_id, client_id, J(request), request_hash, J(prompt_versions), J(trace_carrier), trace_id, now, now),
        )


def create_cached_run(run_id: str, client_id: str, request: dict, request_hash: str, result: dict) -> None:
    now = time.time()
    with cursor() as cur:
        cur.execute(
            "INSERT INTO runs (run_id, client_id, status, stage, request, request_hash, result, route, cached,"
            " prompt_versions, created_at, updated_at, finished_at) VALUES (%s,%s,%s,'done',%s,%s,%s,%s,TRUE,%s,%s,%s,%s)",
            (run_id, client_id, "escalated" if result["route"] == "escalated-to-officer" else "completed",
             J(request), request_hash, J(result), result["route"], J(result.get("prompt_versions")), now, now, now),
        )


def update_run(run_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k} = %s")
        vals.append(J(v) if isinstance(v, (dict, list)) else v)
    vals.append(run_id)
    with cursor() as cur:
        cur.execute(f"UPDATE runs SET {', '.join(cols)} WHERE run_id = %s", vals)


def get_run(run_id: str) -> dict | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        return cur.fetchone()


def add_step(run_id: str, agent: str, attempt: int, step_no: int, kind: str, name: str, input_, output, status: str,
             latency_ms: int, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0,
             prompt_version: str | None = None, retries: int = 0) -> None:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO steps (run_id, agent, attempt, step_no, kind, name, input, output, status, latency_ms,"
            " prompt_tokens, completion_tokens, cost_usd, prompt_version, retries, created_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_id, agent, attempt, step_no, kind, name, J(_jsonable(input_)), J(_jsonable(output)), status,
             latency_ms, prompt_tokens, completion_tokens, cost_usd, prompt_version, retries, time.time()),
        )
        cur.execute("UPDATE runs SET updated_at = %s WHERE run_id = %s", (time.time(), run_id))


def _jsonable(value):
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


def add_passages(run_id: str, passages: list[dict], query: str, tool: str) -> None:
    if not passages:
        return
    now = time.time()
    with cursor() as cur:
        for p in passages:
            cur.execute(
                "INSERT INTO passages (run_id, chunk_id, doc_id, clause_ref, locator, text, score, query, tool, created_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id, chunk_id) DO NOTHING",
                (run_id, p["chunk_id"], p["doc_id"], p.get("clause_ref"), p["locator"], p["text"], p.get("score"),
                 query, tool, now),
            )


def get_passages(run_id: str) -> dict[str, dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM passages WHERE run_id = %s", (run_id,))
        return {r["chunk_id"]: r for r in cur.fetchall()}


def get_steps(run_id: str) -> list[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM steps WHERE run_id = %s ORDER BY id", (run_id,))
        return cur.fetchall()


def quarantine(client_id: str, payload, errors) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO quarantine (client_id, payload, errors, received_at) VALUES (%s,%s,%s,%s) RETURNING id",
            (client_id, J(_jsonable(payload)), J(_jsonable(errors)), time.time()),
        )
        return cur.fetchone()["id"]


def stale_runs(older_than: float) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT run_id, stage, status, attempts, resumes, created_at FROM runs"
            " WHERE status IN ('running','verifying') AND updated_at < %s",
            (time.time() - older_than,),
        )
        return cur.fetchall()
