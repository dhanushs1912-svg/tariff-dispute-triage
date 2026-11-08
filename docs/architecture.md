# Architecture

```
                         host (127.0.0.1 only)
   browser / Locust / eval ----> api :8000 ---------------------------+
                                  |  validate (data contract)          |
                                  |  bad -> quarantine (Postgres), 422 |
                                  |  ok  -> runs row, enqueue          |
                                  v                                    |
                          +---------------+                            |
                          |  redis        |  queues: research, verify  |
                          |  (queue+cache)|  caches: query embeddings, |
                          +---------------+  retrievals, whole runs,   |
                             |         ^     rate-limit counters        |
                     research job      | verify job                     |
                             v         |                                |
   +----------------------------+   hand-off    +---------------------+ |
   | researcher  x N (scalable) | ------------> | verifier            | |
   | LangGraph agent:           |  draft saved  | LangGraph agent:    | |
   | guard > intake > decide<>act  in Postgres  | check > judge >     | |
   | tools: search_corpus,      | <------------ | decide: finalize /  | |
   |  get_clause, follow_refs,  |  retry with   |  retry / escalate   | |
   |  get_request_field         |  new strategy |                     | |
   +----------------------------+               +---------------------+ |
        |            |                                |                 |
        v            v                                v                 v
   +---------+  +-------------+                 +-------------+   +-----------+
   | chroma  |  | llm-gateway | --> provider     | postgres    |   | jaeger    |
   | (dense  |  | timeouts,   |     (or llm-stub)| runs, steps,|   | prometheus|
   |  index) |  | retry, CB,  |                  | passages,   |   | grafana   |
   +---------+  | fallback,   |                  | feedback... |   | exporters |
                | cost ledger |                  +-------------+   +-----------+
                +-------------+
   ingest (one-shot job): PDFs -> chunks -> embeddings -> chroma; freshness -> postgres
```

## Services and why each is its own container (D3)

| Service | Job | Boundary reason |
|---|---|---|
| `api` | Data contract, quarantine, submit/poll, trace, feedback, rate limiting, run cache, watchdog, metrics | Must stay responsive while workers are saturated; scales on request rate, not on model calls. |
| `researcher` | Agent 1: intake, tool-using research loop | The CPU and latency-heavy part. Scaled independently (`--scale researcher=3`); one job per container. |
| `verifier` | Agent 2: citation checks, model judge, routing | Different responsibility and resource profile (short, one model call); failure isolation, so a crashed researcher does not take verification down and the reverse. |
| `llm-gateway` | Only holder of provider config and keys; timeouts, retry, circuit breaker, fallback, cost | Isolates provider failure. One breaker shared by all workers sees the real failure rate; workers can be released without touching provider settings. |
| `llm-stub` | OpenAI-compatible fake provider with a fixed delay | Load tests measure our system, not a free tier's rate limits (D6). |
| `ingest` | One-shot indexing job | Runs on demand, different lifecycle; workers wait for it to finish successfully. |
| `chroma` | Vector index | Stateful; re-indexing does not restart workers. |
| `postgres` | Runs, steps, passages, quarantine, feedback, live scores, index metadata | Stateful system of record; a run can be rebuilt from it. |
| `redis` | Queues, caches, rate-limit counters, locks | Shared fast state; different resource profile. |
| `jaeger`, `prometheus`, `grafana`, `redis-exporter`, `postgres-exporter` | Traces, metrics, dashboard | Must keep working when the application fails. |

Fourteen containers start with one `docker compose up`. Every service declares a health check
except Jaeger (its image has no shell); the services that depend on Jaeger only need it started.

## Agent topology (A1, A2)

**Researcher** (LangGraph `StateGraph`, `triage/agents/researcher.py`):

1. `guard` screens the free text for prompt injection and threats. If it is flagged, the text never
   reaches a model that holds tools, and the run is escalated.
2. `intake` is a model call that classifies the dispute (tariff category, meter accuracy, load
   violation, arrears, disconnection) and extracts entities. Licensees outside the corpus
   (HRECS, MSEZ) are escalated here.
3. `decide` is a model call that returns `{"action": tool, "args": ...}` or `finish`. Retrieval is a
   tool the model chooses. The tools are `search_corpus` (hybrid, keyword or dense),
   `get_clause` (by identifier), `follow_references` (cross references written in a passage) and
   `get_request_field`.
4. `act` runs the tool under a hard timeout and records the query, passages, latency and cost. It
   also enforces the **modifier gate**: a `finish` after only one retrieval is refused once, with
   an instruction to look for provisions that modify what was found. This is step 2 of the
   required approach, and it is structural, not just a line in the prompt.
5. Loop bounds: 12 steps, 10 tool calls and 90 s wall clock (configurable). When a bound is hit,
   the run escalates with the evidence collected so far.

**Hand-off.** The researcher writes its draft (or its escalation), the queries it ran and its
counters to `runs.draft`, then enqueues a `verify` job. Every retrieved passage is already in the
`passages` table, so the verifier works only from what was actually retrieved.

**Verifier** (`triage/agents/verifier.py`):

1. Deterministic checks. Every claim has a citation, every cited chunk id is in the run's
   retrieved set, every quote is found in its passage (fuzzy, threshold 0.85) and no cited text is
   superseded. The output filter blocks amounts and bill revisions. For category disputes, the
   route must be consistent with the determined category.
2. Judge (a model call). It reads only the cited passages and decides whether each claim is
   supported and whether the route follows.
3. Decision.
   - If everything passes, the run is finalised.
   - If not, and this was the first attempt, it is sent back to the research queue with feedback
     and a different strategy: keyword search, lookup by identifier, verbatim quotes.
   - If not, and it has already been retried, it is escalated (`verification_failed`).
   - If the judge cannot run because the provider is down, it is escalated (`provider_unavailable`).

   An unverified answer is never returned.

**If an agent fails mid-run.**
- Job failures: each RQ job retries once, and a crashed graph is caught and turned into an
  `agent_failure` escalation.
- A killed container: every step updates `runs.updated_at`. The API watchdog (Redis-locked, every
  10 s) finds runs with no progress for `RUN_DEADLINE_SECONDS`. It releases their stage locks and
  re-enqueues the stage once (`resumes`); a second stall escalates the run.
- Duplicates: per-stage Redis locks stop a re-queued job from running a stage twice.

## Asynchronous execution (A4)

`POST /v1/disputes` returns `202 {run_id, status_url}` straight away; clients poll `GET /v1/runs/{id}`.
We chose polling over callbacks:
- The officer's browser and our load generator have no public callback URL.
- A poll is idempotent and safe to retry.
- Polling is cheap here: a primary-key read, rate-limited per client.

The Redis queue between submission and execution absorbs bursts. Queue depth is on the dashboard.

## Retrieval (L1)

See `docs/corpus.md` for the documents and `triage/chunking.py` for the chunker.

- **Chunking follows the documents' own structure.**
  - Tariff schedules: each schedule's applicability text and its rate table become separate chunks.
  - Notes under each schedule are kept together as their own chunk.
  - General terms and LT billing conditions: one chunk per numbered paragraph.
  - Conditions of Supply: one chunk per clause (`42.02`), with the parent heading prepended.
  - Long clauses are split with LangChain's `RecursiveCharacterTextSplitter`.
  - Each chunk carries a `clause_ref` (`TO-LT-1`, `COS-42.02`, `TO-GT-29`) and the cross references
    found in its text.
- **Superseded text** printed under "OLD VERSION" is marked and excluded from search.
- **Hybrid search.**
  - Dense: all-MiniLM-L6-v2, embedded locally and stored in Chroma.
  - BM25 (`rank_bm25`): catches exact terms ("Tailoring shop", "42.02") that the small dense model
    blurs.
  - The two are fused with reciprocal-rank fusion. Public-consultation and chapter pages are
    down-weighted (x0.6), because they discuss provisions rather than state them.
  - Exposed to LangChain as `HybridRetriever(BaseRetriever)`, and to the agent as tools.
- **Re-embedding without a rebuild.**
  - Chunk ids hash the document checksum, clause reference and text, so re-running
    `python -m triage.ingest` embeds only new or changed chunks and deletes stale ones.
  - `--reembed-doc <doc_id>` re-embeds a single document.
  - A different embedding model creates a new collection beside the old one.

## Caching and rate limiting (D7)

| Cache | Key | Why |
|---|---|---|
| Query embeddings | model + text | Agents repeat similar queries; saves CPU. |
| Retrievals | index version + query + mode + filters | Identical searches across runs; invalidated when the index version changes. |
| Whole runs | request + prompt versions + index version | A resubmitted identical dispute gets the same verified answer at zero model cost. Only verified routes and deterministic escalations are cached, never `provider_unavailable`. |

Rate limits are per client (`X-Client-Id`, else IP), counted per minute: 20 submissions and
600 reads. A looping client gets 429 with `Retry-After` before it can exhaust the model budget.

## Observability (D5, A6, L5)

- **Logs:** JSON on stdout from every service. Each line carries `correlation_id` (the run id once
  a run exists), `agent` and `trace_id`.
- **Traces:** OpenTelemetry to Jaeger. The trace context is stored on the run and continued by both
  workers, so one trace covers submit, research, each tool and model call, and verify.
- **Metrics:** Prometheus scrapes the api, gateway, stub, every researcher and verifier replica (DNS
  discovery), and the Redis, Postgres and Jaeger exporters. The Grafana dashboard "Tariff Dispute
  Triage" shows:
  - p50/p95 run and API latency, error rate, throughput and availability
  - CPU, memory and uptime per container
  - per-agent success rate, steps and tool calls per run, step latency and retry rate
  - breaker state, cost per agent and step, tokens
  - guardrail hits, live quality, feedback, index freshness and cache hits
- **Reconstruction:** `GET /v1/runs/{id}/trace` returns every step, with input, output, latency,
  tokens, cost, prompt version and retries. It also returns every passage, with the query and tool
  that found it, the verifier decision and the Jaeger link.
