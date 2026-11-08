"""Load test (D6). Measures a COMPLETE run: submission until the final result is available.

Run against the stub model (LLM_BASE_URL pointing at llm-stub) so the test measures this system,
not a free tier's rate limits:

    docker compose --profile tools run --rm loadtest            # step load 2 -> 30 users
    docker compose --profile tools run --rm -e USERS=10 -e RUN_TIME=3m loadtest

Each simulated user keeps exactly one dispute in flight: submit, poll every second until the
result is ready, report the end-to-end time as request type RUN, think briefly, repeat. So the
number of users equals the number of concurrent runs.
"""
import os
import random
import time
import uuid

from locust import HttpUser, LoadTestShape, between, events, task

SLO_P95_SECONDS = 60.0
RESULTS = os.environ.get("RESULTS_DIR", "/mnt/locust/results")
_log = None


def record(env, elapsed_ms: float, ok: bool) -> None:
    global _log
    if _log is None:
        os.makedirs(RESULTS, exist_ok=True)
        _log = open(os.path.join(RESULTS, os.environ.get("RUN_LOG", "runs.csv")), "a", buffering=1)
        if _log.tell() == 0:
            _log.write("ts,users,e2e_ms,ok\n")
    users = env.runner.user_count if env.runner else 0
    _log.write(f"{time.time():.3f},{users},{elapsed_ms:.0f},{int(ok)}\n")


DESCRIPTIONS = [
    "I have a domestic connection. I run a small tailoring shop from one room of the house. Which tariff category applies?",
    "We let out two rooms of our own house to tourists as a home stay and live here. The bill was changed to commercial.",
    "I run a small beauty parlour in the front room of the house I live in. It was reclassified to commercial.",
    "My irrigation pump water is also used for my own dairy cattle. The inspector billed it as industrial.",
    "Our residential apartment has a separate connection for the lift and water pump. It is billed as commercial.",
]


class Officer(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.client_id = "lt-" + uuid.uuid4().hex[:10]

    @task
    def submit_and_wait(self):
        body = {
            "account_number": f"LT-{random.randint(100000, 999999)}", "escom": "BESCOM", "connection_type": "LT",
            "billed_category": "LT-1", "sanctioned_load_kw": round(random.uniform(1, 9), 2), "connected_load_kw": 2.0,
            "premises_use": ["residential", "commercial"], "bill_period_start": "2026-08-01",
            "bill_period_end": "2026-08-31", "billed_amount_inr": random.randint(400, 5000),
            "description": random.choice(DESCRIPTIONS) + f" Ref {uuid.uuid4().hex[:6]}.",
        }
        headers = {"X-Client-Id": self.client_id, "Cache-Control": "no-cache"}
        t0 = time.perf_counter()
        with self.client.post("/v1/disputes", json=body, headers=headers, name="POST /v1/disputes", catch_response=True) as r:
            if r.status_code not in (200, 202):
                r.failure(f"submit {r.status_code}")
                return
            run_id = r.json()["run_id"]
        deadline = t0 + 300
        while time.perf_counter() < deadline:
            time.sleep(1.0)
            with self.client.get(f"/v1/runs/{run_id}", headers=headers, name="GET /v1/runs/{id}", catch_response=True) as r:
                if r.status_code != 200:
                    r.failure(f"poll {r.status_code}")
                    continue
                data = r.json()
            if data.get("result"):
                elapsed_ms = (time.perf_counter() - t0) * 1000
                ok = data["status"] in ("completed", "escalated")
                events.request.fire(request_type="RUN", name="complete run (submit to result)", response_time=elapsed_ms,
                                    response_length=0, exception=None if ok else Exception(data["status"]), context={})
                record(self.environment, elapsed_ms, ok)
                return
        events.request.fire(request_type="RUN", name="complete run (submit to result)", response_time=300000,
                            response_length=0, exception=Exception("timeout"), context={})
        record(self.environment, 300000, False)


if not os.environ.get("USERS"):
    class StepLoad(LoadTestShape):
        """Concurrency steps used to find where the p95 target breaks (set USERS to run a fixed load instead)."""

        stages = [(int(u), int(d)) for u, d in (x.split(":") for x in
                  os.environ.get("STAGES", "2:120,5:120,10:150,15:150,20:150,30:150").split(","))]

        def tick(self):
            t = self.get_run_time()
            elapsed = 0
            for users, dur in self.stages:
                elapsed += dur
                if t < elapsed:
                    return users, users
            return None
