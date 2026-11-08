# Runbook (D8)

The two most likely failure modes, judged from how the system behaved during development.

## 1. Model provider unavailable or rate-limited

**Symptom**
- Runs end as `escalated-to-officer` with reason `provider_unavailable`.
- On the dashboard, "Circuit breaker state" shows 2 (open) and "Provider calls by outcome" shows
  `rate_limited`, `timeout` or `connect`.
- The gateway logs `provider call failed` and `breaker transition`.

**Confirm**
```
curl http://127.0.0.1:8001/admin/breaker
docker compose logs llm-gateway --since 10m | findstr "provider call failed"
```
- `rate_limited`: the free tier's per-minute or per-day quota is used up.
- `connect` or `timeout`: an outage, or the wrong `LLM_BASE_URL`.
- `http_401`: a wrong key.
- `http_404` / `http_400`: a wrong model id, or the provider does not support JSON mode.

**Recover**
1. Quota: wait for the window to reset (the breaker half-opens after `BREAKER_RESET_SECONDS` and
   closes on the first success). Or set `LLM_FALLBACK_*` to a second provider and run
   `docker compose up -d llm-gateway`.
2. Bad key, URL or model: fix `.env`, then run `docker compose up -d llm-gateway`. Nothing else
   needs restarting, because only the gateway holds provider settings.
3. Unsupported JSON mode: set `LLM_JSON_MODE=false`.
4. Runs that escalated during the outage are not cached. Resubmit them once the breaker is closed.
5. To check the recovery path, inject a fault with
   `curl -X POST http://127.0.0.1:8001/admin/fault -H "Content-Type: application/json" -d "{\"mode\":\"down\",\"seconds\":60}"`.

## 2. Runs stuck in `queued` or `running` (workers down or saturated)

**Symptom**
- The web client keeps showing `queued`.
- "Queue depth" keeps rising.
- p95 run latency climbs above 60 s.
- `runs_by_status{status="running"}` stays flat.

**Confirm**
```
docker compose ps researcher verifier
docker compose logs researcher --since 10m
curl http://127.0.0.1:8000/ready
```
- `researcher` exited: check the logs for an index or import error.
- Health check failing: the worker cannot reach Redis or the gateway.
- `/ready` says `index: not built`: `ingest` failed (`docker compose logs ingest`).
- All workers healthy but the queue is growing: the system is saturated.

**Recover**
1. Restart dead workers with `docker compose up -d researcher verifier`. The API watchdog finds
   runs that made no progress for `RUN_DEADLINE_SECONDS` and re-enqueues them once; a second stall
   escalates them as `agent_failure`, so nothing hangs forever.
2. Index missing: run `docker compose run --rm ingest`, then restart the workers.
3. Saturated: scale the research agent with `docker compose up -d --scale researcher=3`.
   Prometheus discovers the new replicas by DNS. If p95 does not fall, the bottleneck is elsewhere:
   - verifier queue depth: scale the verifier.
   - gateway or provider latency: the provider's rate limit.
   - Postgres CPU: the database.
