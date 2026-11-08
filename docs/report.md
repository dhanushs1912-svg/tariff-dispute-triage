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

<!-- RESULTS:LOAD -->
Load test results (stub model, 1 vs 3 researcher workers): to be added by Vidit.

Measured on the real model during evaluation (8 Nov 2026):
- p95 complete run of 45.3 s, inside the 60 s SLO, with one researcher and sequential cases.
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
- **Research reasoning on the 4.1 case is not stable from run to run.** In the 7 Nov evaluation
  run it was right, citing both LT-1 and LT-5. In the 8 Nov run the agent misread LT-1, and the
  verifier caught it and escalated. The safety net works, but the answer itself varies. A stronger
  model, or a higher reasoning effort, is the obvious next step and was beyond the free-tier quota.
