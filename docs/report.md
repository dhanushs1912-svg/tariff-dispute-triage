# Report — Electricity Tariff and Billing Dispute Triage Service

Mini Project 11, UE24AM342AA5. Dhanush S (PES1UG24AM360), Vidit Soni (PES1UG24AM318).

## 1. Problem and scope

Karnataka's distribution companies receive billing disputes every day, and many turn on the tariff
category the consumer is billed under. The category depends on how the premises is used and on
its load, and the rules are spread across the KERC Tariff Order 2025 and the Conditions of Supply.

We built a service that accepts a dispute, validates it, finds and cites the provisions that
decide the category, and routes the case to one of four outcomes:
- bill stands, with reason
- revision recommended
- site inspection required
- escalated to an officer

It never recomputes a bill. Out of scope: model training, cloud deployment and bill arithmetic.

## 2. Agent design

Two agents run in separate worker containers and hand off through Postgres and a Redis queue (see
[architecture.md](architecture.md)).

**Researcher (LangGraph).** It runs these nodes in order:
1. Input guard.
2. Intake: classification and entity extraction.
3. A decide/act loop in which the model picks tools: hybrid search, clause lookup by identifier,
   follow cross references, read request fields.

The loop has three bounds: 12 steps, 10 tool calls and 90 s. A modifier gate refuses to let the
agent finish after only one retrieval, and tells it to look for provisions that modify what it
found.

**Verifier (LangGraph).** It runs these checks in order:
1. Deterministic checks: every citation must resolve to a passage retrieved in this run, its quote
   must be found in that passage, and no superseded text may be cited. The output filter blocks
   amounts and bill revisions. For category disputes, the route must be consistent with the
   category.
2. A model judge that reads only the cited passages.
3. A decision: finalise; retry once with a keyword and clause-lookup strategy; or escalate.

If the provider is down the run is escalated; an unverified answer is never returned.

## 3. Architecture and deployment boundaries

The system runs as 14 containers under one `docker compose up`. The boundary reasons for each
service are in [architecture.md](architecture.md#services-and-why-each-is-its-own-container-d3).

## 4. Design decisions and what we rejected

| Decision | Rejected alternative | Why |
|---|---|---|
| Hybrid BM25 + dense with clause-aware chunks | Dense-only, fixed 500-token chunks | Dense-only missed both deciding provisions of the 4.1 case (incident 1). |
| Modifier gate in the graph | Relying on the prompt alone | A prompt instruction can be skipped; the gate makes "search again" structural and measurable. |
| Verifier as a separate worker with deterministic citation checks | Self-critique prompt in the same process | The brief says two prompts in one process are not two agents, and string-level checks catch invented quotes that an LLM grader may accept. |
| Polling | Webhook callbacks | No public callback URL on an officer's machine; polling is idempotent. |
| Our own metric code with documented formulas | TruLens | TruLens feedback needs a second model provider; our metrics reuse the verifier's judge and the deterministic checks. |
| Gateway service owning keys, breaker and cost | Provider SDK inside each worker | One breaker sees the true failure rate; keys live in one place; the provider changes by config. |
| SimpleWorker (no fork) | RQ's default forking worker | Metrics recorded inside a forked job are lost. |

## 5. Evaluation (before and after)

**Set-up.**
- **Models:** Groq free tier, `gpt-oss-120b` primary, with fallbacks `gpt-oss-20b`, `qwen3.8-27b`
  and Gemini `gemini-3.1-flash-lite` (a second provider, tried last).
- **Run date:** 8 Nov 2026, one code version. The evaluation set has 26 scenarios
  (`eval/scenarios.yaml`); metric definitions are in [evaluation.md](evaluation.md).
- **Batch commands:**
  ```
  docker compose --profile tools run --rm eval --variant <name> --research v1|v2 --gate on|off
  ```
- **Raw results:** `eval/results/*.jsonl`. Summaries: `*_summary.md`. Comparisons: `compare_*.md`.
- **Free-tier limits:** 8k tokens per minute and 200k tokens per day per model. To fit them, the
  main pass ran in two slices (S01–S09 and S10–S26, merged with `--merge`). The two comparisons ran
  on a fixed subset of 8 scenarios where a modifying provision decides the outcome: S01, S02, S04,
  S07, S12, S13, S22, S24.
- **Calls served by each model in the main pass:** primary 27%, Groq fallbacks 24%, Gemini 48%.
  Gemini took over whenever all Groq models were at their per-minute cap. The results therefore
  describe the deployed system with its fallback chain, not one model.

> **Note (18 Nov):** these results were measured before the fix in incident 9. Until then the
> research prompt cut passages at 550 characters, which hid some deciding words (including
> "(e) Tailoring" in LT-1) from the research agent. After the fix the 4.1 case passed in two
> consecutive runs. The full evaluation was not re-run, to keep the free-tier quota for the
> demonstration, so the figures below likely understate the current system.

### Main pass: prompt v2 with modifier gate, 26 scenarios

| Metric | Value |
|---|---|
| Route exactly right | **0.54** (14/26) |
| Route right or an accepted alternative | **0.73** |
| Escalation reason right (outside corpus, injection, threat) | **1.00** |
| Expected supporting passage retrieved | **0.95** |
| Expected supporting passage cited | 0.66 |
| Groundedness | 0.85 |
| Context relevance | 0.50 |
| Faithfulness | 0.68 |
| Hallucination rate | **0.007** |
| p50 / p95 run time on the real model | 16.9 s / **45.3 s** |
| Mean tokens per run | 26.6k |

How the misses break down:
- **Most misses are escalations, not wrong answers.**
  - **Verifier rejected the draft (6):** S01, S02, S04, S11, S15, S24. In S01 (the 4.1 case) the
    research agent claimed that LT-1's list "does not include tailoring", which is false. The judge
    rejected that claim, the retry also failed, and the run escalated instead of giving a wrong
    answer. This is the brief's demonstration item 6 happening on its hardest case.
  - **Step limit reached (2):** S10, S23.
- **Wrong non-escalated routes (5), of which 3 were accepted alternatives:**
  - S08 and S13 recommended a revision where we expected a site inspection.
  - S22 asked for a site inspection where we expected bill-stands.
  - S17 recommended a revision on a disconnection complaint.
- **Hallucination rate:** almost zero. The deterministic checks, plus the repair step for
  same-clause chunk ids, leave very few citations that do not resolve.

### Prompt variants (L2): v1 vs v2, gate on, same 8 scenarios

| Metric | v1 | v2 | Change |
|---|---|---|---|
| Groundedness | 0.69 | 0.77 | **+0.08** |
| Faithfulness | 0.43 | 0.50 | **+0.07** |
| Route acceptable | 0.50 | 0.63 | +0.13 |
| Supporting passages cited | 0.63 | 0.69 | +0.06 |
| Route exactly right | 0.25 | 0.25 | 0 |
| Hallucination rate | 0 | 0 | 0 |
| Mean tokens per run | 30.7k | 38.1k | +24% |

v2 performed better. Its gains are largest on groundedness (+0.08) and faithfulness (+0.07), and it
costs about 24% more tokens per run. The explicit procedure (find the definition, search for what
modifies it, cite each category that lists the activity) produces claims the judge accepts more
often. It does not change how often the final route is exactly right on these hard cases.

### Deliberate change (L3): modifier gate off vs on, prompt v2, same 8 scenarios

| Metric | Gate off (before) | Gate on (after) | Change |
|---|---|---|---|
| Groundedness | 0.92 | 0.77 | −0.15 |
| Context relevance | 0.39 | 0.43 | +0.03 |
| Faithfulness | 0.83 | 0.50 | −0.33 |
| Hallucination rate | 0 | 0 | 0 |
| Supporting passages cited | 0.56 | 0.69 | **+0.13** |
| 4.1 case: both provisions cited | 0.0 | **1.0** | +1.0 |
| Route exactly right | 0.50 | 0.25 | −0.25 |

The gate did what it was built for. The agent cites more of the provisions that decide the case,
and only with the gate does it cite both LT-1 and LT-5 in the 4.1 case. It also had a cost we did
not expect:
- Once forced to deal with competing provisions, the agent writes comparative claims ("LT-5 covers
  a shop, not part of a house"). The strict judge rejects these more often, so 4 of 8 runs ended in
  `verification_failed` escalations, and groundedness and faithfulness fell.
- Without the gate, the agent answered more often. But it never cited LT-5 in the 4.1 case, and two
  of its misses were runs that wandered until the step limit.

Caveats: each variant was run once, on 8 scenarios, and runs vary from one attempt to the next. We
read the direction of each effect (gate means more complete citations and more escalations; v2
means better grounded claims), not the exact size.

## 6. SLO, load test, bottleneck, cost

**SLO, declared before any test** ([slo.md](slo.md)): p95 of a complete run (submission to
final result) <= 60 s at 10 concurrent runs, error rate < 1 %.

**Method**
- Locust, closed loop: each simulated user keeps exactly one dispute in flight. It submits, polls
  every second until the result is ready, and records the end-to-end time. So users = concurrent
  runs.
- Model replaced by `llm-stub` (1.5 s ± 0.3 s per call) through `docker-compose.stub.yml`, so the
  test measures our system, not the provider.
- Step load: 2, 5, 10, 20 and 30 concurrent runs, held 90–150 s each.
- Raw data: `loadtest/results/runs_1worker.csv`, `runs_3workers.csv`. Summary:
  `python loadtest/analyze.py`. Run on 18 Nov 2026.

**1 researcher worker**

| Concurrent runs | Throughput (runs/s) | p50 | p95 | Errors | SLO |
|---|---|---|---|---|---|
| 2 | 0.17 | 11.1 s | 12.1 s | 0 | met |
| 5 | 0.17 | 30.3 s | 31.4 s | 0 | met |
| **10** | 0.17 | 59.7 s | **62.5 s** | 0 | **missed** |
| 20 | 0.17 | 77.0 s | 121.4 s | 0 | missed |
| 30 | 0.17 | 124.4 s | 138.6 s | 0 | missed |

**3 researcher workers** (`docker compose up --scale researcher=3`)

| Concurrent runs | Throughput (runs/s) | p50 | p95 | Errors | SLO |
|---|---|---|---|---|---|
| 2 | 0.25 | 9.1 s | 47.6 s* | 0 | met |
| 5 | 0.48 | 9.1 s | 11.2 s | 0 | met |
| **10** | 0.49 | 19.2 s | **21.2 s** | 0 | **met** |
| 20 | 0.49 | 39.4 s | 41.5 s | 0 | met |
| **30** | 0.49 | 60.7 s | **62.9 s** | 0 | **missed** |

\* Two runs at the start waited behind jobs still queued from the previous test (the queue was not
drained between tests); the other eight took 8–9 s.

**Result against the target.**
- With one worker the SLO is **missed at 10 concurrent runs** (p95 62.5 s).
- With three workers it is **met at 10** (21.2 s) and at 20 (41.5 s), and first fails at **30**
  (62.9 s). No errors in either test.

**Effect of scaling.**
- Throughput rose from 0.17 to 0.49 runs/s (×2.9 for ×3 workers).
- p95 at 10 concurrent runs fell from 62.5 s to 21.2 s.

**Bottleneck** (from Prometheus during each test):
- **1 worker: the research worker.**
  - The research queue reached 29 jobs; the verify queue stayed at 0.
  - The researcher was busy 98 % of the time; the verifier 21 %.
  - CPU was low everywhere (researcher 0.14 cores): the worker is not overloaded. It runs one job
    at a time and spends most of it waiting on the model.
- **Little's law fits.** Time in system = concurrent runs ÷ throughput, so
  10 ÷ 0.17 ≈ 59 s (measured p50 59.7 s) and 30 ÷ 0.49 ≈ 61 s (measured p50 60.7 s). The workers'
  throughput sets the latency.
- **3 workers: still the researchers, with the verifier next.**
  - Each researcher was 95 % busy and the research queue reached 26.
  - The single verifier rose to 77 % busy, with 0.86 CPU cores, and its queue appeared (max 2).
  - Most of the verifier's CPU is the sampled live quality scoring (MiniLM embeddings for context
    relevance), which runs inside the verification job.
- **Next steps:** more researchers would hit the verifier limit soon. The fix is to scale the
  verifier too, or move live scoring off the critical path into its own job.

**Caching (D7)**, measured on the stub with the same dispute:

| | p50 | p95 | Model cost per run |
|---|---|---|---|
| Cache bypassed (`Cache-Control: no-cache`) | 8.1 s | 20.3 s | $0.0012 on the stub; **$0.005** on the real model (main pass mean) |
| Whole-run cache hit | **14 ms** | 35 ms | **$0** |

- A repeated identical dispute is answered about 580× faster and at no model cost.
- Only verified answers and deterministic escalations are cached. Keys include the index and prompt
  versions, so a corpus or prompt change cannot serve a stale answer.
- The retrieval cache showed 867 hits to 2 misses in the load test. That figure is inflated because
  the stub issues the same scripted queries every run, so it is not a real-world hit rate.
- Rate limiting (20 submissions/min per client) did not trigger, because each simulated user has its
  own client id.

Measured on the real model during evaluation (8 Nov 2026):
- p95 complete run of 45.3 s, with one researcher and cases run one at a time (not concurrent).
- **Cost per 100 runs:** $0.50 at the list prices in `.env` ($0.15 / $0.60 per million input /
  output tokens). The free tier actually billed $0.
- **Largest cost driver:** the research agent's `decide` calls, 87% of cost. They are almost all
  prompt tokens (607k input vs 25k output over the main pass), because each turn re-sends the case
  and the retrieved passages. Next are the verifier's judge (7%) and intake (6%).

## 7. What did not work

- **One-shot dense retrieval.** On the 4.1 question, dense search returned neither LT-1 nor LT-5
  (incident 1). Hybrid search, clause-aware chunks and searches built from words in the passages
  fixed it.
- **The first tool protocol.** Listing tools in the prompt and asking for JSON broke against a
  reasoning model with native tool calling (incident 4). The model also named its finish call
  `json`, and sometimes wrote tool calls as plain text. We moved to native tool definitions and a
  gateway that repairs these cases.
- **Exact-string citation checks.** They rejected legitimate quotes that left out list items, with
  or without "...", and quotes that gave the id of the neighbouring chunk of the same clause. We
  added gapped matching and same-clause repair. Invented text is still rejected.
- **Free-tier quotas.** The 8k-per-minute and 200k-per-day limits shaped the project more than any
  design choice (incidents 5, 7, 8):
  - Rate limits first opened the circuit breaker. They now cause waiting instead, and the breaker
    is kept for real outages.
  - The evaluation had to be split into slices.
  - Half the calls fell through to the Gemini fallback.
- **The gate's trade-off.** Forcing the agent to cite competing provisions made answers more
  complete but escalated more often (section 5).
- **Our own token saving hid the answer from the agent** (incident 9). The research prompt cut
  each passage to 550 characters, and in LT-1 "(e) Tailoring" starts at character 586. So the agent
  sometimes "misread" LT-1, and the verifier correctly rejected it. We found this in the 18 Nov
  rehearsal and fixed it with focus-aware excerpts. The 4.1 case then passed twice in a row, verified
  on the first attempt. The 8 Nov evaluation numbers in section 5 were measured before this fix.
