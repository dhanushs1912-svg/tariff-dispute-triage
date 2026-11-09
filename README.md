# Electricity Tariff and Billing Dispute Triage Service

Mini Project 11 — UE24AM342AA5 ML System Design and AgentOps (Jackfruit, Level 3)

| Name | SRN |
|---|---|
| Dhanush S | PES1UG24AM360 |
| Vidit Soni | PES1UG24AM318 |

A consumer says their electricity bill is wrong. This service accepts the dispute over a REST API
and validates it against a published data contract. Two agents then work out the correct tariff
category from the Karnataka (KERC) Tariff Order 2025 and Conditions of Supply. The result is one
route, always with clause-level citations that are checked against the retrieved text:

- **bill-stands-with-reason**
- **revision-recommended**
- **site-inspection-required**
- **escalated-to-officer**, when the provisions do not settle the case

It never revises or recomputes a bill; a grievance officer decides.

Project plan: [docs/project_plan.pdf](docs/project_plan.pdf). Corpus and the section 4.1 passages: [docs/corpus.md](docs/corpus.md).

---

## 1. Run it

**You need:** Docker Desktop (or Docker Engine with Compose v2), about 6 GB free disk space,
8 GB RAM, and internet for the first build.

```bash
git clone <this repository> && cd tariff-dispute-triage
cp .env.example .env
```

Open `.env` and set the one required value:

- `EMBED_MODEL` — the sentence-transformers MiniLM-L6-v2 model id recommended in section 12 of the
  brief (its full Hugging Face id).

Then start everything:

```bash
docker compose up --build
```

The first build downloads the base images and the embedding model (5–10 minutes). The `ingest` job
then indexes the corpus (about 1–2 minutes), and the agent workers start once it has finished. The
system is ready when `http://127.0.0.1:8000/ready` returns `"ready": true`.

By default the agents talk to the **stub model**, so everything runs with no API key and no cost,
but the answers are canned. To get real answers, set these in `.env` and run
`docker compose up -d llm-gateway`:

| Variable | Value |
|---|---|
| `LLM_BASE_URL` | your provider's OpenAI-compatible base URL, from its docs |
| `LLM_API_KEY` | your key |
| `LLM_MODEL` | a model id from the provider's model list |
| `LLM_FALLBACK_*` | optional: a second provider, used when the first is down or rate-limited |

| What | Where |
|---|---|
| Web client | http://127.0.0.1:8000 |
| API docs (OpenAPI) | http://127.0.0.1:8000/docs |
| Grafana dashboard | http://127.0.0.1:3000 (opens on "Tariff Dispute Triage") |
| Jaeger traces | http://127.0.0.1:16686 |
| Prometheus | http://127.0.0.1:9090 |
| Gateway breaker status | http://127.0.0.1:8001/admin/breaker |

Scale the research agent with `docker compose up -d --scale researcher=3`.
Stop with `docker compose down`; add `-v` to also delete the data.

### Without Docker on your machine: GitHub Codespaces

If Docker Desktop will not install on your PC, run the whole stack in the browser instead.

1. On the repository page, click **Code → Codespaces → Create codespace on main**. The Codespace
   asks for a 4-core / 8 GB machine, because the stack runs 14 containers.
2. Wait for setup to finish. It creates `.env` from `.env.example`. If you saved `EMBED_MODEL` as a
   Codespaces secret (GitHub → Settings → Codespaces → Secrets), it is filled in for you;
   otherwise set it in `.env` yourself.
3. In the terminal: `docker compose up --build`.
4. Open the **Ports** tab and click the globe icon next to 8000 (web client), 3000 (Grafana),
   16686 (Jaeger) or 9090 (Prometheus).

Every command in this README works the same inside the Codespace. Stop the Codespace when you are
done (Codespaces → ⋯ → Stop), so it does not use up your free monthly hours.

## 2. Use the API

```bash
curl -s -X POST http://127.0.0.1:8000/v1/disputes -H "Content-Type: application/json" -H "X-Client-Id: demo" -d '{
  "account_number": "BLR-1234567", "escom": "BESCOM", "connection_type": "LT", "billed_category": "LT-1",
  "sanctioned_load_kw": 2, "connected_load_kw": 1.8, "premises_use": ["residential", "commercial"],
  "bill_period_start": "2026-08-01", "bill_period_end": "2026-08-31", "billed_amount_inr": 1840,
  "description": "I have a domestic connection. I run a small tailoring shop from one room of the house. Which tariff category should I be billed under?"}'
# -> 202 {"run_id": "run_...", "status": "queued", "status_url": "/v1/runs/run_..."}
curl -s http://127.0.0.1:8000/v1/runs/<run_id>           # poll until "result" appears
curl -s http://127.0.0.1:8000/v1/runs/<run_id>/trace     # full reconstruction of the run
```

| Endpoint | Purpose |
|---|---|
| `POST /v1/disputes` | Submit (data contract: `GET /v1/contract`, or `contracts/dispute_request.v1.schema.json`) |
| `GET /v1/runs/{id}` | Status and, when done, the tariff position |
| `GET /v1/runs/{id}/trace` | Every step, tool call, query, passage, prompt version, latency and cost, plus the verification outcome |
| `POST /v1/runs/{id}/feedback` | `{"satisfactory": true/false, "reason": "..."}` |
| `GET /v1/feedback/summary` | Aggregated feedback and live quality by hour |
| `GET /v1/quarantine` | Rejected requests with field-level errors |
| `GET /v1/index` | Index version and data freshness |
| `GET /health`, `GET /ready`, `GET /metrics` | Liveness, readiness, Prometheus |

## 3. Demonstration checklist

| # | Item | How |
|---|---|---|
| 1 | Clean clone to a working system | Section 1 above |
| 2 | Routed recommendation with resolving citations | Web client, "Tailoring room (4.1)" preset; each citation shows its quote and clause |
| 3 | A run traced end to end | "Full run trace" link in the result, and the Jaeger link inside it |
| 4 | Malformed request quarantined, no run started | "Malformed request" preset → 422 with field errors and `agent_run_started: false`; `GET /v1/quarantine`; the run count on the dashboard does not change |
| 5 | Case outside the corpus escalates | "Outside corpus (HRECS)" preset → `escalated-to-officer`, reason `outside_corpus` |
| 6 | Self-verification catches an unsupported answer | Trace of any run with `attempts: 2`; or set `RESEARCH_PROMPT_VERSION=v1` and look for a `retry` verification outcome on the dashboard |
| 7 | Prompt injection and the guardrail | "Prompt injection" preset → `input_flagged`; the trace shows the injection rules that fired and no model call |
| 8 | Circuit breaker opens, degradation path | `curl -X POST http://127.0.0.1:8001/admin/fault -H "Content-Type: application/json" -d "{\"mode\":\"down\",\"seconds\":120}"`, then submit two disputes: the breaker opens (dashboard / `/admin/breaker`), the fallback provider is used if configured, otherwise the run escalates with `provider_unavailable`. Clear with `{"mode":"none"}` |
| 9 | Locust against the SLO, failing concurrency, effect of `--scale` | Section 5 |
| 10 | Section 4.1 case handled correctly | Preset 1; expected LT-1, bill stands, citing LT-1 and LT-5 ([docs/corpus.md](docs/corpus.md)) |

## 4. Evaluation

The 26 fixed scenarios are in `eval/scenarios.yaml`. Metrics and how each is computed are in
[docs/evaluation.md](docs/evaluation.md). Running the evaluation needs a real model configured.

```bash
docker compose --profile tools run --rm eval --variant v2_gate --research v2 --gate on
docker compose --profile tools run --rm eval --variant v1_gate --research v1 --gate on
docker compose --profile tools run --rm eval --compare v1_gate v2_gate
```

Unit tests (data contract, guardrails, citation checks, chunking, scenario anchors):

```bash
python -m pip install -r requirements-dev.txt && python -m pytest -q
```

## 5. Load test

The SLO was declared before any test: [docs/slo.md](docs/slo.md). Use the stub model:
`LLM_BASE_URL` must point at `llm-stub`, which is the default.

```bash
docker compose up -d --scale researcher=1
docker compose --profile tools run --rm -e RUN_LOG=runs_1worker.csv loadtest
docker compose up -d --scale researcher=3
docker compose --profile tools run --rm -e RUN_LOG=runs_3workers.csv loadtest
python loadtest/analyze.py loadtest/results/runs_1worker.csv loadtest/results/runs_3workers.csv
```

Fixed load instead of the step load:

```bash
docker compose --profile tools run --rm -e USERS=10 -e LOCUST_ARGS="-u 10 -r 10 -t 3m" loadtest
```

## 6. Repository layout

```
src/triage/          all services (one image, different commands)
  api.py             public API, data-contract boundary, quarantine, watchdog
  agents/            researcher.py and verifier.py (LangGraph), common.py
  gateway.py         llm-gateway: timeouts, retry, circuit breaker, fallback, cost
  stub.py            OpenAI-compatible stub provider for load tests
  ingest.py          idempotent corpus pipeline (CLI)
  chunking.py        clause-aware chunking
  retrieval.py       hybrid BM25 + dense retrieval, clause index, LangChain retriever
  guardrails.py      injection, toxicity and output filter
  quality.py         citation resolution and the four quality metrics
  evaluate.py        batch evaluation CLI
  web/               the web client
prompts/             versioned prompts (intake, research v1/v2, verifier)
corpus/              KERC PDFs + manifest with checksums
contracts/           JSON Schemas of the external interfaces
eval/                scenarios.yaml and results/
loadtest/            locustfile.py, analyze.py, results/
ops/                 prometheus.yml, Grafana provisioning and dashboard
docs/                plan, corpus, architecture, data contract, SLO, evaluation, runbook, incident log, report
tests/               pytest suite
```

## 7. Where each requirement is met

| Req | Where |
|---|---|
| F1 / D1 | `contracts.py`, `contracts/*.json`, [docs/data_contract.md](docs/data_contract.md), `POST /v1/disputes` |
| F2 | Pydantic schema, range, enum and cross-field rules; `quarantine` table |
| F3 | Intake agent (`prompts/intake/v1.yaml`) |
| F4–F5 | Research agent tools + hybrid retrieval; citations with quotes |
| F6 | Four routes; verifier `decide` |
| F7 | Escalation reasons: mixed, conflict, outside corpus, insufficient evidence, verification failed, provider unavailable, input flagged |
| F8 / D5 / A6 | `/health`, `/ready`, `/metrics`, JSON logs with correlation id, Jaeger traces, Grafana dashboard |
| A1 | LangGraph; 4 tools chosen by the model; loop bounds in `.env` |
| A2 | Two worker services and a queue hand-off ([docs/architecture.md](docs/architecture.md)) |
| A3 | Verifier: citations must resolve to retrieved text, model judge, retry or escalate |
| A4 | Async submit/poll with a Redis queue |
| A5 | `gateway.py`; fault injection endpoint |
| A7 | `--scale researcher=3`; [docs/report.md](docs/report.md) |
| A8 | `src/triage/web/index.html` |
| L1 | `chunking.py`, `retrieval.py`, `ingest.py --reembed-doc` |
| L2 | `prompts/`, version tag on every step and run, v1 vs v2 comparison |
| L3 | `eval/`, [docs/evaluation.md](docs/evaluation.md) |
| L4 | `guardrails.py`, verifier output filter |
| L5 | Tokens and cost per step in `steps`; cost per 100 runs in the report |
| L6 | Feedback endpoints, sampled live scoring, quality panel |
| D2 | `python -m triage.ingest`; freshness in `index_meta`, `/v1/index`, dashboard |
| D3 | `docker-compose.yml` (14 containers, health checks) |
| D4 | `.env.example`; no keys, provider endpoints or model ids in the repo |
| D6 | [docs/slo.md](docs/slo.md), `loadtest/` |
| D7 | Embedding, retrieval and whole-run caches; per-client rate limits |
| D8 | [docs/runbook.md](docs/runbook.md), [docs/incident_log.md](docs/incident_log.md) |
