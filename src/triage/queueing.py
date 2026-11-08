"""RQ queues between the API and the agents, and between the two agents."""
from __future__ import annotations

import redis
from rq import Queue, Retry

from .config import settings

_conn: redis.Redis | None = None


def conn() -> redis.Redis:
    global _conn
    if _conn is None:
        _conn = redis.Redis.from_url(settings().redis_url)
    return _conn


def research_queue() -> Queue:
    return Queue("research", connection=conn())


def verify_queue() -> Queue:
    return Queue("verify", connection=conn())


def enqueue_research(run_id: str, attempt: int = 0) -> None:
    s = settings()
    research_queue().enqueue("triage.agents.researcher.run_research", run_id, attempt,
                             job_timeout=int(s.max_wall_seconds * 2 + 60), result_ttl=600, failure_ttl=86400,
                             retry=Retry(max=1), job_id=f"research-{run_id}-{attempt}-{_suffix()}")


def enqueue_verify(run_id: str) -> None:
    verify_queue().enqueue("triage.agents.verifier.run_verify", run_id, job_timeout=180, result_ttl=600,
                           failure_ttl=86400, retry=Retry(max=1), job_id=f"verify-{run_id}-{_suffix()}")


def _suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:6]


def depths() -> dict:
    return {"research": research_queue().count, "verify": verify_queue().count}
