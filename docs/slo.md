# Service level objective (D6)

**Declared on 4 Nov 2026, before any load test was run.** This target is not changed after seeing results.

| Item | Target |
|---|---|
| Measured quantity | Time from `POST /v1/disputes` to the moment `GET /v1/runs/{id}` first returns the final result (a complete run, not the submission call) |
| Objective | **p95 <= 60 s** |
| Load | 10 concurrent runs (10 Locust users, each keeping one dispute in flight) |
| Error budget | < 1 % of runs fail or time out (a correct escalation counts as a completed run) |
| Model | `llm-stub`, 1.5 s +/- 0.3 s per call, so the test measures this system and not a free tier's rate limits |

## Why 60 seconds (section 1 of the brief)

A billing dispute is not a live chat with the consumer. It reaches a grievance officer, who works
through a queue of cases, and the officer opens the case, submits it and reads the cited position
before deciding. So the run has to finish while the officer still has that case open: about a
minute. Longer, and the officer moves on and comes back. Much shorter buys nothing, because the
officer still has to read the citations.

The arithmetic also fits. A run makes about six model calls: intake, three or four research
decisions and the verifier's judge. Free-tier models answer in roughly 1 to 3 s per call, which
gives 10 to 20 s of model time. That leaves headroom for retries, a verifier retry and queueing at
moderate load.

Ten concurrent runs is a busy hour for one sub-division's grievance desk.

## How it is measured

```
docker compose --profile tools run --rm loadtest
python loadtest/analyze.py loadtest/results/runs.csv
```

The locustfile reports each complete run as request type `RUN`. It also appends
`ts, users, e2e_ms, ok` to `loadtest/results/runs.csv`, and `analyze.py` turns that into p50, p95
and throughput per concurrency level. The step load runs 2, 5, 10, 15, 20 and 30 concurrent runs.

Results, the concurrency at which the target fails, the component responsible, and the effect of
`--scale researcher=3` are in `docs/report.md`.
