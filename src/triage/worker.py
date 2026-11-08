"""Agent worker entrypoint:  python -m triage.worker research|verify

SimpleWorker runs jobs in-process (no fork) so Prometheus metrics recorded during a job are
kept and served on :9100. Each container runs one job at a time; scale with
`docker compose up --scale researcher=3`.
"""
from __future__ import annotations

import logging
import sys

from prometheus_client import start_http_server
from rq import SimpleWorker

from . import db
from .metrics import WORKER_UP
from .obs import log, setup_logging, setup_tracing
from .queueing import conn


class MeteredWorker(SimpleWorker):
    agent = "-"

    def execute_job(self, job, queue):
        WORKER_UP.labels(self.agent).set(1)
        try:
            return super().execute_job(job, queue)
        finally:
            WORKER_UP.labels(self.agent).set(0)


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else "research"
    agent = {"research": "researcher", "verify": "verifier"}[role]
    logger = setup_logging(agent)
    setup_tracing(agent)
    start_http_server(9100)
    db.init_schema()
    if role == "research":
        from .retrieval import get_store

        try:
            log(logger, logging.INFO, "warming corpus store", **get_store().stats())
        except Exception as e:  # noqa: BLE001 - index may still be building; the store loads lazily
            log(logger, logging.WARNING, "corpus store not ready yet", error=repr(e))
    WORKER_UP.labels(agent).set(0)
    MeteredWorker.agent = agent
    worker = MeteredWorker([role], connection=conn())
    log(logger, logging.INFO, "worker started", queue=role)
    worker.work(with_scheduler=False, logging_level="WARNING")


if __name__ == "__main__":
    main()
