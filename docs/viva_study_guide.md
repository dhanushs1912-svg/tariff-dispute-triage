# Viva study guide — Electricity Tariff Dispute Triage

Read this top to bottom once, then use sections 12 (Q&A) and 11 (demo) to rehearse. Every number
here is from the code or from the real evaluation runs. Section 10 lists what is NOT proven, so you
never over-claim.

---

## 0. The 60-second pitch (learn this word for word)

> A consumer says their electricity bill is wrong. Very often the dispute is about the **tariff
> category** they are billed under. The category depends on how the premises is used, and the rules
> for that are spread across two KERC documents: the Tariff Order 2025 and the Conditions of Supply.
> Our service takes the dispute through a REST API, validates it, and uses **two AI agents** to find
> the provisions that decide the case. The first agent searches the documents using tools and drafts
> a position. The second agent **verifies** it: every citation must resolve to text that was really
> retrieved. If it cannot verify, it retries once with a different strategy, and if that fails it
> **escalates to a human officer instead of answering**. It never recomputes a bill. Everything runs
> as 14 containers under one `docker compose up`, with tracing, metrics, caching, rate limiting and
> a load test.

The one idea that makes this project different from a normal chatbot: **a system that always answers
is easy; one that knows when not to answer is hard.** The brief says this itself (F5, F7).

---

## 1. The problem, and why it is hard

### 1.1 The business problem
- A state electricity company gets billing disputes daily.
- A consumer can appeal to the Consumer Grievance Redressal Forum, so the officer's reasoning must
  be **cited**, not just stated.
- The officer must: establish the correct category, check whether a re-categorisation was valid,
  and route the case.
- Our system produces a **tariff position with evidence**. The officer decides. It never revises a
  bill (out of scope in the brief, section 13).

### 1.2 Why it is hard (the "difficult case", brief section 4.1)
> "I have a domestic connection. I run a small tailoring shop from one room of the house. Which
> tariff category should I be billed under?"

- The domestic category is **LT-1**. Its definition says it covers houses "where a portion is used
  by the occupant for ... (e) Tailoring".
- But a different category, **LT-5** (industrial), lists "Tailoring shop".
- Neither definition mentions the other. The answer depends on **which one applies to this
  person** (a portion of the occupant's own house vs. a separate shop or unit), and the system must
  find **both** and say so.
- A normal "embed the question, fetch the top passages, ask the model" pipeline returns neither.
  We measured it: the top-5 dense results for the 4.1 question were CoS 3.03 and
  public-consultation pages, not LT-1 or LT-5 (incident 1 in `docs/incident_log.md`).

### 1.3 What the brief demands, in one table

| Group | What | Our answer in one line |
|---|---|---|
| F1–F8 | Functional (API, validation, classify, retrieve, cite, route, escalate, observe) | REST API, Pydantic contract, intake agent, hybrid retrieval, verifier, 4 routes, escalation reasons, metrics |
| A1–A8 | Agent system | LangGraph, 2 agents, verification, FastAPI async, resilience, per-agent metrics, scaling, web client |
| L1–L6 | LLMOps | LangChain + Chroma, versioned prompts, 26-scenario eval, guardrails, cost per step, feedback + live scoring |
| D1–D8 | Platform | Data contract, ingest CLI, 14 containers, no secrets in repo, observability, SLO + Locust, caching + rate limit, runbook + incidents |

---

## 2. The corpus (the real documents)

| doc_id | Document | Size | Notes |
|---|---|---|---|
| `kerc_to_2025` | KERC Combined Tariff Order 2025 (BESCOM, MESCOM, CESC, HESCOM, GESCOM), order dated 27.03.2025, control period FY2025-26 to FY2027-28 | 567 pages | Text layer, no OCR. The retrieved copy is from the OpenCity mirror of the KERC order. |
| `kerc_cos_2006` | Conditions of Supply of Electricity of Distribution Licensees in Karnataka, with the 1st and 2nd amendments | 140 pages | Text layer, from KERC's own site. |

Both are listed in `corpus/manifest.yaml` with a **SHA-256 checksum**. The ingest pipeline refuses to
run if a file does not match its checksum (so nobody silently swaps a document).

### 2.1 Where the useful law actually is
- The **first ~534 pages** of the tariff order are commentary: the regulator discussing, consultation
  replies from the public, calculations. These talk *about* provisions.
- **Annexure-9** (PDF pages 535–567, "Electricity Tariff 2026") is the real tariff book:
  - General Terms and Conditions (para 1–31). Para 23: uncovered installations are classified by the
    licensee with KERC approval. Para 29: **the Conditions of Supply prevail over the tariff book in
    case of discrepancy.**
  - Conditions applicable to billing of LT installations.
  - Each tariff schedule: **LT-1** (domestic and listed part-uses and institutions), **LT-2**
    (private professional/educational institutions, nursing homes), **LT-3(a)** (commercial),
    **LT-3(b)** (hoardings), **LT-4(a)/(b)/(c)** (irrigation), **LT-5** (industrial incl. "Tailoring
    shop", garment units), **LT-6(a)/(b)/(c)** (water supply, street lights, EV charging), **LT-7**
    (temporary), and the HT-1 to HT-7 equivalents.
  - Notes under each schedule. These carry the exceptions. Example: the LT-1 note says temples are
    LT-1 but power used for a marriage hall is billed LT-3; and the "home stay" definition (owner
    must live there) decides LT-1 vs LT-3(a).
- **Conditions of Supply** key clauses:
  - **3.03 / 3.04** classification and reclassification: a consumer classified under a category
    *erroneously* can be reclassified after 15 clear days' notice and a fresh agreement.
  - **39.00** conversion from one type of use to another (change in tariff category).
  - **42.02** misuse of electricity: using supply for a purpose with a higher tariff. Assessed at
    2x tariff for the period (12 months if unknown). Part (c): use for a purpose with a *lower*
    tariff is not prejudicial and no bill revision is made.
  - **42.01** unauthorised increase in load; **27.01** meter accuracy dispute (third-party testing);
    **29.06** disconnection rules (not on holidays/Sundays); **29.08** erroneous bills (no recovery of
    arrears after 2 years unless continuously shown in bills).
- **Superseded text.** The CoS prints amended clauses with the old wording below, marked
  "OLD VERSION". Citing old law as current would be a serious error, so our chunker marks it
  `[SUPERSEDED]` and the system excludes and rejects it (14 chunks).

### 2.2 The reference answer for 4.1
**bill-stands-with-reason, category LT-1, citing LT-1 and LT-5.** Reason: the consumer is the occupant
using one room of their own house for tailoring, which LT-1 explicitly allows; LT-5's "Tailoring
shop" covers a shop or unit. This is *our* reading, to be confirmed by faculty at Evaluation 1.

---

## 3. Architecture

### 3.1 The picture

```
 browser / Locust / eval ---> api :8000 ---------------------------------+
                               | 1 rate-limit (Redis)                     |
                               | 2 validate against data contract         |
                               |   bad -> Postgres quarantine, 422        |
                               | 3 run cache hit? -> return result        |
                               | 4 else create run row, enqueue, 202      |
                               v                                          |
                     redis queues: research | verify                      |
                         |                       ^                        |
                         v                       |                        |
         researcher (xN) --- hand-off via ----> verifier                  |
         LangGraph agent 1   Postgres + queue   LangGraph agent 2         |
         guard>intake>decide<>act               check>judge>decide        |
           |        |                              |                       |
           v        v                              v                       v
        chroma   llm-gateway --> Groq x3, Gemini   postgres        jaeger, prometheus,
        (dense)  (timeouts, retry, breaker,        (runs, steps,    grafana, exporters
                 fallback, cost)  or llm-stub      passages, ...)
 ingest (one-shot job): PDFs -> chunks -> embeddings -> chroma, freshness -> postgres
```

### 3.2 The 14 containers and why each is separate (D3: "justify the boundaries")

| Container | Job | Why it is its own boundary |
|---|---|---|
| `api` | Public API, validation, quarantine, cache, rate limit, watchdog, metrics, web client | Must answer instantly while workers are busy. Scales on request rate. |
| `researcher` (scalable) | Agent 1 | The heavy, slow part (many model calls). `--scale researcher=3`. One job at a time per container. |
| `verifier` | Agent 2 | Different job and profile (short). Failure isolation: if a researcher dies, verification still works, and vice versa. |
| `llm-gateway` | The only place that talks to model providers | One circuit breaker sees the true failure rate of the provider; keys live in one place; provider switchable by config. |
| `llm-stub` | Fake provider with fixed 1.5 s delay | So load tests measure *our* system, not a free tier's rate limit (D6). |
| `ingest` | One-shot indexing job | Different lifecycle; workers wait for it to finish successfully. |
| `chroma` | Vector index | Stateful; re-indexing does not restart workers. |
| `postgres` | System of record | Stateful. A run can be fully rebuilt from it. |
| `redis` | Queues, caches, rate-limit counters, locks | Shared, fast, different resource profile. |
| `jaeger`, `prometheus`, `grafana`, `redis-exporter`, `postgres-exporter` | Observability | Must keep working when the app fails. |

All the Python services share **one Docker image** (`tariff-triage:local`) and differ only by the
command they run. The embedding model is **baked into the image at build time** (so containers start
identically and offline).

### 3.3 The life of one request (be able to narrate this)

1. **Client** sends `POST /v1/disputes` with an `X-Client-Id` header.
2. **API** checks the **per-client rate limit** (Redis counter, 20 submissions/min).
3. **Validate** against the Pydantic data contract. If it fails: write the payload + field-level
   errors to the **quarantine** table, return **422** with `agent_run_started: false`. No run row, no
   queue entry, nothing starts. (Demo item 4.)
4. Compute a **request hash** (request + prompt versions + index version). If the same verified
   request was answered before, return the cached result immediately (HTTP 200, `cached: true`).
5. Otherwise create a `runs` row (`queued`), store the OpenTelemetry trace context, **enqueue** a
   research job in Redis, and return **202 + run_id** at once.
6. **Researcher** takes the job. It takes a Redis **lock** for (stage, run, attempt) so duplicates
   cannot run twice, and runs its LangGraph (section 5). Every step is written to `steps`; every
   retrieved passage to `passages`.
7. It writes its **draft** (or an escalation) into `runs.draft` and enqueues a **verify** job. This is
   the hand-off between the two agents.
8. **Verifier** runs deterministic checks, then a model judge, then decides: **finalize**,
   **retry** (back to the research queue with feedback, new strategy) or **escalate**.
9. The result is saved, cached (if verified or a deterministic escalation), and a 25% sample is
   scored for live quality.
10. The client **polls** `GET /v1/runs/{id}` until `result` appears.
11. In the background, the API **watchdog** (every 10 s) re-queues runs that have not progressed for
    `RUN_DEADLINE_SECONDS`, once; a second stall escalates them as `agent_failure`.

---

## 4. Retrieval (L1): the core of the "hard case"

### 4.1 What RAG is, and why a single pass fails
- **RAG** (retrieval-augmented generation): fetch relevant text, give it to the model, so the answer
  is grounded in documents instead of the model's memory.
- **Single-pass RAG** embeds the *question* and returns the passages most similar to it. That finds
  passages that **resemble the question**.
- In the 4.1 case the deciding provision (LT-5's "Tailoring shop", CoS 42.02 misuse) **does not
  resemble the question**. The question says "domestic connection" and "which category"; the
  provision says "Tailoring shop ... Garment manufacturing units". So single-pass misses it.
- **Fix = agentic retrieval**: the agent reads what it found, asks "what could modify this?", and
  searches again **using words it read in the passages**. That is the brief's steps 1–5 (section 5).

### 4.2 Embeddings and cosine similarity
- An **embedding** turns text into a vector (a list of numbers) so that similar meaning is
  numerically close. We use **all-MiniLM-L6-v2**: 384 dimensions, 6 transformer layers, small enough
  for CPU. It runs through **fastembed** (ONNX runtime), no GPU, no API cost (brief section 12).
- **Cosine similarity** = angle between two vectors: `cos = (a·b) / (|a||b|)`. 1 = same direction.
  Chroma is configured with the cosine space.
- Query embeddings are **cached in Redis** (D7), keyed by model + text.

### 4.3 Vector database
- **Chroma** stores chunk vectors with metadata (doc, clause_ref, locator, page, superseded flag,
  cross-reference list). It finds nearest neighbours with **HNSW** (a graph index for approximate
  nearest-neighbour search: fast, slightly approximate).
- The collection name includes the embedding model's name, so **changing the model creates a new
  collection beside the old one**. That is how "re-embed without rebuilding everything" works
  (L1). `--reembed-doc <doc_id>` re-embeds one document only.

### 4.4 BM25 (keyword search)
- BM25 scores a chunk by how many query terms it contains, weighted by how **rare** each term is
  (IDF) with saturation on repeated terms (k1) and length normalisation (b). It is the classic
  search-engine ranking.
- Why we need it too: a small dense model **blurs exact terms**. "Tailoring shop", "42.02", "LT-5" are
  exact tokens BM25 nails. Dense is better at paraphrase.
- Implemented with `rank_bm25` (BM25Okapi), built in memory from all chunks, and reloaded when the
  index version changes.

### 4.5 Hybrid fusion (RRF) and the commentary down-weight
- We take the top `4k` from BM25 and top `4k` from dense and fuse them with **reciprocal rank
  fusion**: each result gets `1/(60 + rank)` from each list, and the scores add. A chunk ranked high
  in both wins. RRF needs no score normalisation (BM25 and cosine scores are on different scales).
  The constant 60 is the standard damping value.
- **Commentary down-weight x0.6** for chunks from the commentary part of the order (`TO-P*`), because
  they *discuss* provisions and crowd out the provisions themselves (we saw this in incident 1).
- **Superseded** chunks are excluded by default.
- Exposed to LangChain as a `HybridRetriever(BaseRetriever)` (L1 asks for LangChain or LlamaIndex),
  and to the agent as tools.

### 4.6 Chunking (L1: "document the strategy and how it addresses the difficulty")
We cut on the documents' **own structure**, not at fixed sizes, because the deciding passages are
short clauses and notes that a fixed window would merge with rate tables or cut mid-sentence.

| Part | Rule | clause_ref example |
|---|---|---|
| Conditions of Supply | One chunk per **clause number**, with the clause title and parent heading prepended | `COS-42.02` |
| Tariff order, commentary pages | Page-level chunks | `TO-P397` |
| Annexure-9 general terms / LT billing | One chunk per **numbered paragraph** | `TO-GT-29`, `TO-LTB-14` |
| Annexure-9 schedules | Applicability text and **rate table as separate chunks**; **notes** under a schedule as their own chunk | `TO-LT-1`, `TO-LT-5` |
| Long clauses (> 1800 chars) | Split with LangChain `RecursiveCharacterTextSplitter` (1400 chars, 150 overlap) | same clause_ref |

- Each chunk has a **clause_ref** and the **cross references** found in its text (e.g. the LT-4 note
  points at CoS 42.06). This is what powers the `get_clause` and `follow_references` tools.
- Result: **805 tariff-order chunks + 537 CoS chunks = 1,342**, of which 14 are superseded.
- How this addresses the difficulty: the applicability list of LT-1 and of LT-5 are each **one
  intact chunk**, so a search for "tailoring" returns *both*; the notes that carry exceptions are
  separate chunks; and lookup by identifier lets the agent fetch a provision it knows exists even if
  the search does not surface it.

### 4.7 The ingest pipeline (D2): idempotent, with freshness metrics
`python -m triage.ingest`: **read -> parse -> chunk -> embed -> index**.
- **Idempotent**: a chunk id = hash(document checksum, clause_ref, text). Re-running on an unchanged
  corpus embeds **0** chunks (we saw `chunks_embedded: 0`, 4.8 s). A changed document re-embeds only
  its changed chunks and deletes stale ones.
- **Freshness** (when built, from which versions, how many chunks) is stored in Postgres
  `index_meta` and exposed at `GET /v1/index` and as Prometheus metrics (`index_age_seconds`,
  `index_chunks_total`). **Throughput** (pages/s, chunks/s) too.
- It publishes an **index version** (hash of document checksums + embed model) to Redis. When it
  changes, retrieval and whole-run caches are invalidated, so stale answers cannot survive a corpus
  update.
- First build: 707 pages, 1,342 chunks, ~59 s on CPU.

---

## 5. The agents (A1–A3)

### 5.1 What an "agent" is (versus a pipeline)
- A **pipeline** has fixed stages: retrieve, then answer.
- An **agent** lets the model **decide the next action** (a tool) in a loop, look at the result, and
  decide again. Retrieval is *a tool the agent chooses to call*, not a fixed stage (A1).
- The brief's marks (steps 2 and 4) are for: **(2)** noticing that another provision may modify the
  one found and searching for it, and **(4)** verifying the answer against retrieved text. Those are
  the two things a fixed pipeline cannot do.

### 5.2 Tool calling
- We use the provider's **native function calling**: we send tool definitions (name, description,
  JSON schema for arguments) and the model replies with a tool call. We moved to this after the first
  attempt (listing tools in the prompt and asking for JSON) broke against a reasoning model
  (incident 4).
- Tools of the research agent:

| Tool | What it does |
|---|---|
| `search_corpus(query, doc, k, mode)` | Hybrid / keyword / dense search, optional document filter |
| `get_clause(ref)` | Fetch a provision by identifier (`LT-1`, `LT-3(a)`, `42.02`, `GT-29`); applicability text before rate tables |
| `follow_references(chunk_id)` | List the clauses a passage refers to |
| `get_request_field(name)` | Read one field of the consumer's request |
| `finish(route, category, position, claims[+citations], escalation)` | Submit the draft |

### 5.3 LangGraph (the framework)
LangGraph models the agent as a **state machine**: nodes are functions that read and update a shared
state; edges (including conditional ones) decide what runs next. We chose it because the topology
(loops, gates, early exits) is explicit and testable, and the brief names it (A1).

**Researcher graph** (`agents/researcher.py`):
```
START -> guard -> intake -> decide <-> act -> END
            \         \         \        \-> exhausted -> END
             \-------- escalate early (input flagged / outside corpus / provider down) -> END
```
- **guard**: screens the free text for prompt injection / threats *before any model sees it*.
- **intake**: first checks the manifest for **outside-corpus** licensees (HRECS, MSEZ) and escalates
  with **no model call, no cost** (decided in under 100 ms). Otherwise a model call classifies the
  dispute type (tariff category, meter accuracy, load violation, arrears, disconnection, other) and
  extracts entities (premises use, the activity, loads, billed category, candidate categories) (F3).
- **decide**: a model call that picks the next tool. The prompt shows each retrieved passage **once**
  in a "passages so far" block, plus a short history of actions and the remaining budget.
- **act**: runs the tool **with a timeout**, records query, passages, latency, cost; refuses
  **repeated identical** searches; and enforces the two gates below.
- **exhausted**: budget hit, so escalate `budget_exhausted` with the evidence collected.

**Loop bounds (A1)**: max **12 steps** (decide calls), **10 tool calls**, and a **wall-clock** limit.
Defaults in `.env.example` are 12 / 10 / 90 s. **Our evaluation used 360 s** because free-tier rate
limits made runs wait; say this if asked, don't claim 90 s for the eval.

### 5.4 The two gates (our own design; know why they exist)
1. **Modifier gate.** If the agent tries to `finish` after fewer than 2 retrievals, the finish is
   **refused** (up to twice) with the instruction to search the activity word on its own and check
   notes, part-use lists, misuse 42.02, reclassification 3.04, change of use 39, general terms 23/29.
   *Why*: a prompt line can be ignored; a gate makes "search again for what modifies it" **structural
   and measurable**. This is step 2 of the brief's required approach.
2. **Competing-provision gate.** If the agent retrieved a tariff schedule of **another category** that
   lists the consumer's activity (e.g. LT-5 "Tailoring shop") but did not cite it, `finish` is refused
   and it is told to cite each one and explain which applies. *Why*: it is what forces both LT-1 and
   LT-5 into the 4.1 answer. *Cost*: see the L3 result in section 9 (more complete, but more
   escalations).

### 5.4b Prompt context management (why tokens per run fell from ~55k to ~22k)
Each model call used to re-send every passage retrieved so far. Now each passage appears **once**,
older observations are reduced to ids, repeated searches are refused without calling the tool, and
passages are truncated to 550 characters in the prompt. This mattered because free tiers allow only
8,000 tokens per minute per model.

### 5.5 Two agents, hand-off, and failure (A2)
- "Two prompts in one process are not two agents" (brief). Ours are **separate containers**, with
  separate responsibilities, separate graphs and separate failure domains.
- Hand-off: researcher writes `runs.draft` (draft, escalation, intake, queries, counters) and
  enqueues `verify`. The verifier works **only from what was retrieved**: it reads the `passages`
  table, not the model's memory.
- **If one fails mid-run** (A2: "document what happens"):
  - A Python exception inside a graph is caught and turned into an `agent_failure` escalation.
  - RQ retries a failed job once.
  - If a container is killed, every step touches `runs.updated_at`; the **watchdog** (Redis-locked,
    every 10 s) finds runs with no progress for `RUN_DEADLINE_SECONDS`, releases their locks and
    re-queues the stage **once** (`resumes`); a second stall escalates.
  - **Per-stage Redis locks** (5-minute TTL) stop a re-queued job from running a stage twice.
  - Workers are `SimpleWorker` (no fork) so Prometheus metrics recorded inside a job are not lost.

### 5.6 The verifier (A3): "an unverified answer is never returned"
**Step 1: deterministic checks** (no model):
- Every claim must have a citation.
- **Citation repair**: models often quote a provision correctly but give the id of the *neighbouring
  chunk of the same clause*. If the quote is not in the cited chunk but is in another retrieved chunk
  of the **same clause_ref**, we re-point it. Text that is not in any retrieved chunk is never
  repaired.
- **Resolve every citation**: status is `ok`, `unknown_chunk` (id never retrieved in this run),
  `superseded`, or `quote_not_found`.
- **Quote matching** (`quality.py`): normalise Unicode (e.g. non-breaking hyphens), lower-case;
  exact substring; or an elided quote ("A ... B", each piece found **in order**); or up to 3 verbatim
  pieces with a short omitted stretch between (skipped list items); or a fuzzy match at ratio >= 0.85.
  **A paraphrase or invented text fails.**
- **Output filter**: blocks any amount (₹, Rs, INR, "rupees N"), bill actions ("revised to", "refund",
  "waive", "recalculate"), and toxic text. This is how the system **cannot issue a determination it
  is not authorised to make** (L4).
- For category disputes only: route/category consistency (`revision-recommended` with the determined
  category equal to the billed one is contradictory).

**Step 2: model judge.** A separate prompt (`verifier/v1.yaml`) sees *only the cited passages* and
decides per claim `supported: true/false` and whether the route/category **follows** from the
supported claims. It may read cited passages together (e.g. one covers part of a house, another a
shop).

**Step 3: decision.**
- Everything passes -> **finalize**.
- Problems and this was the first attempt (`MAX_VERIFY_ATTEMPTS` = 2) -> **retry**: the research
  queue gets the **named problems**, the previous draft, the already-retrieved passages, and a hint to
  switch to keyword search and `get_clause`, copying quotes verbatim (a *different strategy*, as A3
  requires).
- Problems after the retry -> **escalate** `verification_failed`.
- The judge cannot run because the provider is down -> **escalate** `provider_unavailable`.
- The draft states an amount or revises a bill on the last attempt -> `unauthorised_determination`.

### 5.7 Escalation reasons (F7)
`mixed_category`, `provisions_conflict`, `insufficient_evidence` (chosen by the research model),
`outside_corpus` (decided from the manifest, not by the model), `input_flagged` (guardrail),
`verification_failed`, `budget_exhausted`, `provider_unavailable`, `agent_failure`,
`unauthorised_determination`.

### 5.8 Routes (F6)
`bill-stands-with-reason`, `revision-recommended`, `site-inspection-required` (the outcome turns on
facts that need checking on site: who runs the activity, actual load, meter accuracy), and
`escalated-to-officer`.

---

## 6. Guardrails (L4)

| Layer | What | Where |
|---|---|---|
| 1. Pattern screen | Weighted regex rules ("ignore previous instructions", "system prompt", "you are now", fake role tags, "mark this case as revision...", etc.). Score >= 3 = flagged. Also a toxicity word list and a threat pattern. | `guardrails.py`, the `guard` node |
| 2. Data fencing | Consumer text is wrapped in `<consumer_text>` and every prompt declares it as **data, never instructions** | prompts |
| 3. Capability limits | No tool can change a bill or a route. The only way to a route is `finish`, and the verifier re-checks it. | tool design |
| 4. Output filter | Amounts, bill actions, toxicity blocked on output | verifier |

- Flagged input **never reaches a model that holds tools** (brief: "agents are more exposed than
  pipelines, because injected text can reach a model holding tools").
- Threat language escalates; plain toxic language is logged and counted but still handled (the
  consumer may be angry for a good reason).
- Honest limit: layer 1 is **regex**, so a creative attacker can evade it; layers 2–4 are what really
  protect the system. A trained classifier would be the upgrade.

---

## 7. The LLM gateway (A5, L5): resilience and cost

All model traffic goes through `llm-gateway`; agents never hold a key or a model id (D4).

### 7.1 Timeouts, retries, backoff
- **Timeout** on every model call (30 s) and every tool call (10 s) so nothing hangs.
- **Bounded retries with exponential backoff and full jitter**: the delay after attempt n is a
  random value between 0 and `min(max, base × 2^(n-1))` (base 0.5 s). *Why jitter*: if many workers
  retry at the same moment they hammer the provider again together (thundering herd); randomising
  spreads them out.
- Retryable: timeouts, connection errors, 5xx, malformed output. Not retryable: other 4xx.

### 7.2 Circuit breaker
Three states per provider:
- **Closed**: normal.
- **Open**: after N consecutive failures (default 5): calls are refused immediately for 30 s, so we
  do not waste time and tokens on a dead provider.
- **Half-open**: after the reset time, **one** probe call is allowed; success closes it, failure
  re-opens it.
- **Rate limits (HTTP 429) deliberately do not count** as breaker failures. A rate limit means "slow
  down", not "I am broken". We learned this the hard way (incident 8): rate limits were opening the
  breakers and then refusing calls that would have worked seconds later.

### 7.3 Fallback chain and graceful degradation
Order tried: `gpt-oss-120b` (primary) -> `gpt-oss-20b` -> `qwen3.8-27b` (all Groq) -> Gemini
`gemini-3.1-flash-lite` (a different company). Each has its **own breaker and quota**. When all are
rate-limited, the gateway **waits for the earliest reset the provider reports** (up to 90 s) and
goes round again. When all fail: HTTP 503 `provider_unavailable` and the caller **escalates**; it
never returns a half-finished answer as confident (A5).

### 7.4 Cost and tokens recorded at call time (L5)
Prompt tokens, completion tokens, and cost (`tokens × price per million`, prices from config) are
recorded **per step**, labelled by agent and step name, in Postgres and Prometheus. Free tiers bill $0,
so cost is reported at **list price**, which is the honest "what would this cost".

### 7.5 Fault injection
`POST /admin/fault {"mode":"down","seconds":60}` makes the primary fail. This is how we **demonstrate
the breaker on request** (A5, demo item 8). It is enabled by `ENABLE_FAULT_INJECTION` (dev only).

### 7.6 The stub
`llm-stub` is an OpenAI-compatible fake that returns fixed JSON after 1.5 s ± 0.3 s and follows a fixed
script (search, search again, finish). Used for the load test (D6) so the test measures **our**
queue/workers/database, not the provider.

---

## 8. Platform concepts

### 8.1 Asynchronous API (A4)
Runs take tens of seconds, so `POST` returns `202 {run_id}` immediately and the client **polls**
`GET /v1/runs/{id}`.
- *Why polling and not a callback*: the officer's browser and our load generator have no public
  callback URL; a poll is idempotent and safe to retry; polling is cheap (a primary-key read,
  rate-limited).
- A **Redis queue (RQ)** sits between submission and execution (**queue-based load levelling**): a
  burst of submissions fills the queue instead of overloading workers.

### 8.2 Data contract (D1, F2)
`contracts.py` (Pydantic) is the single source; JSON Schemas are generated into `contracts/` and
served at `GET /v1/contract`.
- **Schema/type**: `extra = forbid` (unknown fields rejected), types.
- **Range**: load 0 < kW <= 20000, description 20–2000 chars, amount <= 10 crore.
- **Category (enum)**: 22 KERC categories, 7 licensees, 6 dispute types.
- **Cross-field**: LT connection must have an LT category (HT likewise; LT-6(c)/HT EV allowed on both);
  LT only below 150 kW (tariff general term 9); period end not before start; period <= 12 months;
  period not in the future.
- **Quarantine**: rejects are stored with their field-level errors; **no run starts**. Proven by the
  run count not changing (demo item 4).

### 8.3 Caching (D7) and rate limiting
| Cache | Key | Why it is safe/useful |
|---|---|---|
| Query embeddings | model + text | Agents repeat similar queries; saves CPU |
| Retrievals | index version + query + mode + filters | Identical searches across runs; invalidated when the index version changes |
| Whole runs | request + prompt versions + index version | A repeated identical dispute gets the same **verified** answer with zero model cost. Never caches `provider_unavailable`, `budget_exhausted`, or other transient failures. |

**Rate limit**: fixed one-minute window per client (Redis `INCR` + expiry): 20 submissions and 600 reads
per minute, then 429 with `Retry-After`. It is a **cost control**: one client looping against a
multi-step agent could exhaust the model budget in minutes (brief).

### 8.4 Observability (D5, F8, A6)
- **Structured JSON logs** from every service, each line carrying `correlation_id` (the run id once
  one exists), `agent`, `trace_id`.
- **Tracing (OpenTelemetry -> Jaeger)**: the trace context is stored on the run row and **continued by
  both workers**, so one trace spans submit, research, each tool and model call, and verify.
- **Metrics (Prometheus)**: scraped from api, gateway, stub, every researcher/verifier replica (DNS
  discovery so `--scale` is picked up), Redis, Postgres, Jaeger. **Histograms** are used for latency:
  p50/p95 are computed with `histogram_quantile` from bucket counts.
- **Grafana**: 34 panels: p50/p95 run and API latency, error rate, throughput, availability, CPU /
  memory / uptime per container, per-agent success rate, steps and tool calls per run, step latency,
  retry rate, routes and escalations, breaker state, cost by step, tokens, guardrail hits, live
  quality, feedback, index age, caches.
- **Run reconstruction (D5)**: `GET /v1/runs/{id}/trace` returns every step (input, output, latency,
  tokens, cost, prompt version, retries), every passage with the query/tool that found it, the
  verifier outcome and the Jaeger link.

### 8.5 Prompts as versioned artifacts (L2)
Prompts are files `prompts/<id>/<version>.yaml`. The tag stored with every step and every response is
`id@version#contenthash`, so an edited file can never pretend to be the same version.
- `research@v1`: tools listed, "find the provision that applies and answer with citations".
- `research@v2` (default): an explicit procedure: find the definition, look for what **modifies** it,
  search again with words **read in the passages**, search the activity word alone, cite each category
  that lists it, escalate rather than guess.

### 8.6 Feedback and live scoring (L6)
`POST /v1/runs/{id}/feedback {satisfactory, reason}` is stored and aggregated (`/v1/feedback/summary`).
25% of non-escalated runs are **scored automatically** with the same four metrics and charted over time
on the dashboard.

### 8.7 Docker Compose practices (D3, D4)
- **Health checks** on every service except Jaeger (no shell in its image).
- **`depends_on` with conditions**: workers wait for `ingest` to **complete successfully**
  (`service_completed_successfully`) and for the gateway/api to be **healthy**.
- Only `127.0.0.1` ports are published (not exposed to the network).
- **Config via environment** (12-factor): everything environment-specific comes from `.env`
  (documented in `.env.example`); **no keys, endpoints or model ids in the repository**, which is why
  `EMBED_MODEL` is blank in the example.
- Named volumes for Redis, Postgres, Chroma, Prometheus, Grafana.

### 8.8 Postgres tables
`runs` (state machine: queued -> running -> verifying -> completed/escalated, request, draft, result,
prompt versions, trace id), `steps` (every LLM/tool/check step with latency, tokens, cost, prompt
version, retries), `passages` (every retrieved chunk per run, with query and tool), `quarantine`,
`feedback`, `live_scores`, `index_meta` (freshness and ingest throughput).

---

## 9. Evaluation and results (L2, L3) and how to read them

### 9.1 The evaluation set
26 scenarios (`eval/scenarios.yaml`), each with a full request, expected route and category,
acceptable alternative routes, and **the passages that support it** (clause_ref + a phrase that must
appear). `tests/test_scenarios.py` checks every request passes the contract and every anchor exists
in the corpus. Groups: the 4.1 case and its boundary variants; notes/part-use lists that modify a
definition; CoS clauses that modify the tariff book (misuse 42.02, change of use 39); plain
definitions; other dispute types (meter, load, arrears, disconnection); and cases that must escalate
(outside corpus, prompt injection, genuinely mixed, threat).

### 9.2 The four metrics (say how each is computed; the brief asks)
| Metric | How |
|---|---|
| **Groundedness** | Supported claims / all claims, judged by the verifier's model reading only the cited passages |
| **Context relevance** | Mean cosine similarity (MiniLM) between the dispute text and each cited passage, rescaled from [0.1, 0.7] to [0, 1] |
| **Faithfulness** | 1 if the judge says the route/category follows from the supported claims, else 0 |
| **Hallucination rate** | (citations that do not resolve + claims with no citation) / (citations + uncited claims). "Does not resolve" = unknown chunk id, superseded text, or quote not found. This one is **deterministic**, no model involved. |

We used our own implementation instead of TruLens (the brief says "TruLens or equivalent"). Reason:
TruLens' feedback functions would need a second model provider, and our deterministic citation checks
are stricter than an LLM grader on our main failure (an invented or paraphrased quote).

### 9.3 Main pass: 26 scenarios, prompt v2, gate on (8 Nov 2026)
| Metric | Value |
|---|---|
| Route exactly right | **0.54** (14 of 26) |
| Right or an accepted alternative | **0.73** |
| Escalation reason right (outside corpus, injection, threat) | **1.00** |
| Expected passage **retrieved** | **0.95** |
| Expected passage **cited** | 0.66 |
| Groundedness / context relevance / faithfulness | 0.85 / 0.50 / 0.68 |
| **Hallucination rate** | **0.007** |
| p50 / **p95** run time (real model) | 16.9 s / **45.3 s** |
| Mean tokens per run / cost per 100 runs (list price) | 26.6k / **$0.50** |
| Largest cost driver | research `decide` calls = **87%** of cost (almost all prompt tokens, since each turn re-sends context); judge 7%; intake 6% |

**How to explain 54%:** most misses are **escalations, not wrong answers**: 6 were `verification_failed`
and 2 hit the step limit. In the main pass, S01 (the 4.1 case) escalated because the agent wrongly
claimed LT-1's list does not include tailoring; **the judge caught it and the system escalated
instead of answering wrongly**. That is demo item 6 happening on the hardest case. In the 7 Nov run
the same case was answered correctly with both clauses cited, so the *answer* varies between runs
while the *safety net* works.

### 9.4 Prompt v1 vs v2 (L2), 8 hard scenarios, same set
Groundedness 0.69 -> **0.77** (+0.08); faithfulness 0.43 -> **0.50** (+0.07); acceptable route 0.50 ->
0.63; exact route unchanged (0.25); tokens +24%. **v2 is better on groundedness and faithfulness.**

### 9.5 The deliberate change (L3): modifier gate off -> on, same 8 scenarios
| | Gate off | Gate on |
|---|---|---|
| Supporting passages cited | 0.56 | **0.69** |
| 4.1: both provisions cited | 0.0 | **1.0** |
| Groundedness | 0.92 | 0.77 |
| Faithfulness | 0.83 | 0.50 |
| Route exactly right | 0.50 | 0.25 |
| Hallucination rate | 0 | 0 |

**Honest reading**: the gate does what it was built for (more of the deciding provisions are cited, and
only with the gate does the 4.1 answer cite both LT-1 and LT-5), but forcing comparisons produces
comparative claims that the strict judge rejects more often, so more runs end as safe escalations. It
is a **real trade-off between completeness and answer rate**, and we report it as such.

---

## 10. What is NOT proven (know this before they ask)

- **The 8 Nov evaluation ran before the incident-9 fix** (passages cut at 550 characters hid
  "(e) Tailoring" from the research agent). The numbers likely understate the current system; we did not
  re-run the full evaluation, to keep the free quota for the demo. After the fix: 4.1 correct 2/2.
- **Sample size and noise**: comparisons are one run each on 8 scenarios. Differences of 0.07–0.08 are
  **directional, not statistically significant**.
- **Mixed models**: in the main pass **48% of calls were served by Gemini** and the rest by three Groq
  models, because the free tier's per-minute caps kept forcing the fallback. Results describe the
  deployed system with its fallback chain, not one model.
- **Judge = verifier**: groundedness and faithfulness use the same judge that gates answers, so they are
  not independent measurements, and we have no human-labelled gold for them. Hallucination rate (a
  deterministic check) and route accuracy against our expected routes are the more objective ones.
- **Expected routes are our own reading** of the documents (not an expert's), and the 4.1 reference
  answer is "to be confirmed by faculty".
- **Corpus limits**: the CoS is the 2006 text with only the 1st and 2nd amendments; KERC has issued
  later amendments (3rd to 11th) and a draft Electricity Supply Regulations 2026 that may replace it.
  The tariff order is the March 2025 order (a later BESCOM true-up order exists and is not included).
- **Eval config differs from the committed defaults**: the evaluation ran with a 360 s run budget, 4
  retries and a breaker threshold of 8; the committed defaults are 90 s, 3 and 5.
- **Regex guardrail** can be evaded (section 6).
- **No authentication** on the API (local demo scope); admin/fault endpoints are bound to localhost.
- **Single Postgres/Redis**: no high availability (out of scope: local Compose).
- **The load test used the stub model** (as the brief requires), so its latencies are our system's,
  not the real model's. The two comparable real-model figures: p95 45 s for cases run one at a time,
  and a mean of 26.6k tokens per run. The retrieval-cache hit rate from the load test is inflated
  (the stub repeats the same queries).

---

## 11. The demo (all 10 items) and what to say

| # | Item | How | What to say |
|---|---|---|---|
| 1 | Clean clone to working system | `copy .env.example .env`, set EMBED_MODEL, `docker compose up --build`; `/ready` true | "14 containers, health-checked, workers wait for the index." |
| 2 | Valid request with resolving citations | Web client, "Tailoring room (4.1)" | Point at each citation's quote and clause; "every one is checked against retrieved text." |
| 3 | One run traced end to end | "Full run trace" link; Jaeger link inside | Walk steps: guard, intake, decide, tool, passages, prompt version, per-step latency and cost, verifier. |
| 4 | Malformed request quarantined | "Malformed request" preset | "422, field-level errors, `agent_run_started: false`, quarantine id; the run count did not move." |
| 5 | Case the corpus can't answer | "Outside corpus (HRECS)" | "Decided from the manifest in ~100 ms, zero tokens: it does not ask the model whether it is out of scope." |
| 6 | Self-verification catches an unsupported answer | A trace with `attempts: 2`, or show the S01 8 Nov escalation | "The judge rejected a false claim; it retried with keyword search; failing again, it escalated." |
| 7 | Prompt injection | "Prompt injection" preset | "Flagged before any model; no tool-holding model saw it; escalated `input_flagged`." |
| 8 | Circuit breaker + degradation | `curl -X POST http://127.0.0.1:8001/admin/fault -H "Content-Type: application/json" -d "{\"mode\":\"down\",\"seconds\":120}"`, submit two disputes, show `/admin/breaker` | "Breaker opens after repeated failures; fallback model serves; with none left, it escalates rather than guessing." Clear with `{"mode":"none"}`. |
| 9 | Locust vs target, failing concurrency, `--scale` | Show the two tables in `docs/report.md` §6 (and Grafana "Queue depth" / worker panels if the stack ran the test recently) | "SLO p95 ≤ 60 s at 10. One researcher fails at 10 (62.5 s): the worker is the bottleneck. Three researchers: 21.2 s at 10, fails at 30. Throughput ×2.9. The verifier is next." |
| 10 | The 4.1 case | Preset 1 (served from the cache: a verified answer, 0 ms, no quota). For a live run, tick "bypass cache" (≈15–20 s). | "Bill stands, LT-1: LT-1 covers a portion of the occupant's house used for tailoring; LT-5's 'Tailoring shop' covers industrial or commercial units. Both cited, verified first time." If a live run escalates, present it as item 6. |

**Stored runs to open during the demo** (they are in the Postgres volume; open
`http://127.0.0.1:8000/v1/runs/<run_id>/trace`):

| Use | run_id | What it shows |
|---|---|---|
| Item 6, caught then fixed | `run_05b296b139cb49aca9c7` | S02. Attempt 1: the judge rejected two over-reaching claims ("LT-5 excludes residential use", "the reclassification was invalid"). The agent retried with a narrower claim from the LT-1 text, which passed: **revision-recommended, LT-1** (the correct answer). |
| Item 6, caught then escalated | `run_12abe6cb564845dc87cf` | The 4.1 case on 8 Nov: the agent claimed LT-1 "does not include tailoring" (false); the judge rejected it twice, so the run escalated instead of answering wrongly. |
| Item 10 backup | `run_1f6cdd94ead145848d7f`, `run_463bcaa99d4649188ade` | The 4.1 case answered correctly: bill-stands, LT-1, citing both LT-1 and LT-5. |

**Before the demo**: check Groq quota is fresh (daily limit), make sure Docker is running, and never
run `docker compose down -v` (the `-v` deletes these stored runs and the cache).

---

## 12. Likely viva questions, with answers

**Problem and design**

1. *Why agents and not a simple RAG pipeline?* Because the deciding provision does not resemble the
   question. A single retrieval returns passages that look like the question; the agent reads what it
   found, asks what could modify it, and searches again with words from the passages. We measured the
   single pass missing both LT-1 and LT-5.
2. *What is the difference between an agent and a pipeline?* In a pipeline the stages are fixed; in an
   agent the model chooses the next action (a tool) in a loop. Retrieval is a tool it can call
   repeatedly.
3. *Why two agents?* Separate responsibilities (find vs. check), separate containers (failure
   isolation, independent scaling), and the brief requires a defined hand-off. A checker that is the
   same prompt as the writer shares its blind spots; ours uses deterministic checks the model cannot
   argue with.
4. *What happens if the researcher crashes mid-run?* The exception is caught and escalated; RQ retries
   once; if the container is killed, the watchdog re-queues the stage once, and a second stall
   escalates it. Stage locks prevent double processing.
5. *How does the system "know when not to answer"?* Several independent routes to escalate:
   input flagged, outside the corpus, loop budget exhausted, verification failed, provider down. All
   produce `escalated-to-officer` with a stated reason.
6. *Why not let the model decide outside-corpus?* It misused that reason on S03 (it escalated a valid
   case as "outside corpus"). It is a fact about the request, so we decide it from the manifest:
   cheaper, instant, and deterministic.

**Retrieval**

7. *What is an embedding?* A vector representing meaning, so similar texts are close. We use
   MiniLM-L6-v2 (384 dimensions), run locally on CPU.
8. *Why hybrid BM25 + dense?* Dense catches paraphrase; BM25 catches exact terms ("Tailoring shop",
   "42.02") that a small dense model blurs. Together they cover both.
9. *What is RRF?* Reciprocal rank fusion: each list gives `1/(60 + rank)` and scores add, so a chunk
   high in both wins, with no need to normalise two different score scales.
10. *Why clause-aware chunking?* The deciding passages are short clauses and notes. Fixed windows merge
    them with rate tables or cut them in half. Cutting on the document's own structure keeps each
    provision intact and gives each a clause id for lookup.
11. *How do you re-embed without rebuilding?* Chunk ids hash (document checksum, clause, text), so only
    changed chunks re-embed; `--reembed-doc` re-embeds one document; a new embedding model gets its
    own collection.
12. *What is HNSW?* An approximate nearest-neighbour graph index inside Chroma: fast lookups, slightly
    approximate results.
13. *How do you handle superseded clauses?* The CoS prints old versions after "OLD VERSION". The chunker
    marks them `[SUPERSEDED]`, excludes them from search, and the verifier rejects any citation to
    them.

**Verification and quality**

14. *What exactly does the verifier check?* Every claim has a citation; every cited chunk was actually
    retrieved in this run; the quote is found in it (exact, elided, gapped, or fuzzy >= 0.85); no
    superseded text; no amounts or bill actions; route consistent with category; then a model judge
    reads only the cited passages.
15. *Can the model fool the verifier by paraphrasing?* A paraphrase fails the quote check. The checker
    only accepts text that really appears in a retrieved passage.
16. *What is a hallucination in your system?* A citation that does not resolve (unknown id, superseded,
    quote not in the passage) or a claim with no citation. Measured: 0.7%.
17. *Why did the first real-model run fail?* The model's tool call was rejected by the provider
    (incident 4); we moved to native tool definitions and a gateway that recovers malformed calls.
18. *Why is route accuracy only 54%?* Mostly safe escalations: 6 verification failures, 2 step limits,
    versus 5 wrong routes. An escalation costs an officer a few minutes; a confidently wrong answer
    could be used against a consumer at a Forum. We prefer the first error.
19. *How is the evaluation done and is it reliable?* 26 fixed scenarios with expected outcomes and
    supporting passages. Reliable for direction, not for exact size (single runs, mixed models, the
    judge is also the gate). See section 10.
20. *Why not TruLens?* It needs a second model provider for its feedback functions. We implemented the
    four metrics with documented formulas and reuse the verifier's judge plus deterministic checks.
21. *What was the deliberate change and its effect?* Turning the modifier gate off vs on. On: more of
    the deciding provisions cited (+0.13) and both clauses cited in the 4.1 case; but more
    escalations, so exact route accuracy fell. A trade-off between completeness and answer rate.

**Resilience and platform**

22. *Explain the circuit breaker.* Closed (normal) -> open after N consecutive failures (calls refused
    for 30 s) -> half-open (one probe) -> closed on success. It stops us hammering a dead provider.
23. *Why exponential backoff with jitter?* Doubling delays give the provider time to recover; random
    jitter stops many workers retrying simultaneously.
24. *Why don't rate limits trip the breaker?* A 429 means "slow down" not "broken". Counting them
    opened breakers and blocked calls that would have succeeded seconds later (incident 8). Now the
    gateway waits for the reset time the provider reports.
25. *What is graceful degradation here?* Primary -> other models -> a different company's model -> if all
    fail, escalate with `provider_unavailable`. Never a half-finished answer presented as confident.
26. *Why async with polling?* Runs take tens of seconds; blocking the request would tie up the API and
    time out clients. We return a run id and the client polls; no public callback URL is needed.
27. *Why a queue between API and workers?* Load levelling and decoupling: bursts wait in the queue, the
    API stays fast, and workers scale independently.
28. *Why validate at the ingestion boundary?* A malformed request must not start an expensive agent
    run. Bad data is quarantined with field-level errors instead.
29. *How do you prevent prompt injection?* Layers: pattern screen before any model; fencing the
    consumer text as data; tools that cannot change a bill or route; output filter and verifier. No
    single layer is trusted.
30. *What does caching buy you?* Embedding and retrieval caches save CPU and repeated searches; the
    whole-run cache returns a previously verified answer at zero model cost. All keyed by index and
    prompt versions so they cannot go stale after a change. (Effect on p95 and cost is part of Vidit's
    measurements.)
31. *Why rate limit?* A client looping against a multi-step agent could exhaust the model budget in
    minutes; a per-client limit is a cost control.
32. *How can you reconstruct a run?* `GET /v1/runs/{id}/trace`: every step, tool call, query, passage,
    prompt version, per-step latency and cost, and the verification outcome, plus the Jaeger trace.
33. *What is a correlation id?* One identifier carried through every service, log line and trace span of
    a run (our run id), so you can follow one request across containers.
34. *What is an SLO and what did you declare?* A target for a service's behaviour. Ours: p95 of a
    complete run (submit to result) <= 60 s at 10 concurrent runs, error rate < 1%, declared **before**
    measuring, because an officer reads the result with the case open.
35. *Why a stub for the load test?* So the test measures our queue, workers and database, not a free
    tier's rate limits.
36. *What did the load test show, and where is the bottleneck?* With 1 researcher the SLO failed at 10
    concurrent runs (p95 62.5 s): throughput was stuck at 0.17 runs/s, the researcher was 98 % busy,
    the research queue reached 29, and CPU was low. The worker handles one job at a time and waits on
    the model, so the **researcher count** is the bottleneck. With 3 researchers, throughput rose
    to 0.49 runs/s (×2.9), p95 at 10 users fell to 21.2 s (SLO met), and it first fails at 30 users
    (62.9 s). Little's law predicts both: 10 / 0.17 ≈ 59 s and 30 / 0.49 ≈ 61 s. At 3 researchers
    the single **verifier** becomes the next bottleneck (77 % busy, mostly the live quality scoring),
    so the next step is scaling it or moving live scoring off the critical path.
36b. *What did caching do?* A whole-run cache hit returns in 14 ms (p50) instead of 8.1 s, at $0
    model cost instead of about $0.005.
37. *What does Docker Compose give you here?* One command from a clean clone, health checks,
    dependency ordering (workers wait for ingest and the gateway), a private network, volumes.
38. *Why are there no keys in the repo?* D4: all environment-specific config is injected from `.env`
    at runtime; the repo has only `.env.example` with blanks.

**Honesty questions**

39. *What does not work well?* The 4.1 answer varies between runs; the strict judge makes the gate
    escalate more; free-tier quotas limited how much we could evaluate and forced fallback to a second
    provider; guardrail patterns are regex; the corpus lacks later CoS amendments.
40. *What would you do with more time or budget?* Larger evaluation with repeated runs per scenario and
    confidence intervals; a stronger or higher-reasoning model; human-labelled gold set; a trained
    injection classifier; add the later CoS amendments and the latest tariff order to the corpus.

---

## 13. File map: what to open when you explain a part

| Topic | File |
|---|---|
| Data contract, result shape | `src/triage/contracts.py`, `contracts/*.json` |
| API, quarantine, cache, rate limit, watchdog | `src/triage/api.py`, `cache.py`, `locks.py`, `queueing.py` |
| Chunking | `src/triage/chunking.py` |
| Ingest CLI | `src/triage/ingest.py`, `corpus/manifest.yaml` |
| Embeddings / retrieval | `src/triage/embeddings.py`, `retrieval.py` |
| Researcher agent | `src/triage/agents/researcher.py` |
| Verifier agent | `src/triage/agents/verifier.py` |
| Citation and quote logic, metrics | `src/triage/quality.py` |
| Guardrails | `src/triage/guardrails.py` |
| Prompts | `prompts/*/*.yaml`, `src/triage/prompts.py` |
| Model gateway, stub | `src/triage/gateway.py`, `stub.py`, `llm.py` |
| Metrics, logs, traces | `src/triage/metrics.py`, `obs.py`, `ops/` |
| Evaluation | `eval/scenarios.yaml`, `src/triage/evaluate.py`, `eval/results/` |
| Load test | `loadtest/locustfile.py`, `analyze.py` |
| Compose and image | `docker-compose.yml`, `Dockerfile`, `.env.example` |
| Docs | `docs/architecture.md`, `corpus.md`, `evaluation.md`, `slo.md`, `runbook.md`, `incident_log.md`, `report.md` |

**Split for the viva** (each person should still understand the whole picture):
- **You:** sections 2, 4, 5, 6, 9 (corpus, retrieval, agents, guardrails, evaluation).
- **Vidit:** sections 7, 8 and the load test (gateway, API, compose, observability, caching, SLO).

---

## 14. The 8 real incidents (short stories; great for "what went wrong?")

1. **Single-pass dense retrieval missed both 4.1 provisions.** Proved the need for agentic and hybrid
   retrieval.
2. **Lettered schedules (`LT-3(a)`) were unreachable by `get_clause`.** The reference normaliser upper-cased
   the letters while lookups used lower case.
3. **Superseded "OLD VERSION" text was indexed as current law.** The splitter ended the old block at the
   same sub-clause letter. Fixed; test added.
4. **The provider rejected every research call.** Plain-text tool listing vs a reasoning model with native
   tool calling. Moved to native tools and added repair.
5. **Free-tier rate limit became escalations.** 8k tokens/min vs 20k–55k per run. Smaller prompts, waiting
   instead of failing.
6. **DNS outage mid-run.** The run escalated safely; the next run after reconnection completed.
7. **Daily token quota exhausted during evaluation.** 200k/day/model. The eval was split into slices.
8. **Both limits hit in the first full evaluation pass.** Rate limits tripped breakers; fixed: they no
   longer count as failures, the gateway waits for the reset; outside-corpus decided without a model.
9. **The research agent never saw "Tailoring" in LT-1** (found in the 18 Nov rehearsal). To save tokens,
   the research prompt cut passages at 550 characters, and "(e) Tailoring" is at character 586 of the
   LT-1 chunk. That is why the agent kept "misreading" LT-1 and the judge (which sees the full text)
   rejected it. Fixed with focus-aware excerpts; then the 4.1 case passed twice in a row, verified first
   time. **Best viva story**: the verifier did its job, and the trace let us find a bug in *our* code.

---

## 15. Vocabulary cheat sheet

- **RAG**: retrieval-augmented generation. **Agentic RAG**: the model controls retrieval across several
  steps. **Tool calling**: the model returns a structured request to run a function.
- **Embedding / cosine similarity / HNSW**: vector meaning, angle between vectors, approximate neighbour graph.
- **BM25**: rarity-weighted keyword ranking. **RRF**: rank fusion `1/(60+rank)`.
- **Idempotent**: running it again gives the same result without side effects.
- **State machine (LangGraph)**: nodes + edges over shared state.
- **LLM-as-judge**: a model grades another model's output.
- **Circuit breaker**: stop calling a failing dependency for a while. **Backoff + jitter**: growing random delays between retries.
- **SLO / p95**: a service target / the value below which 95% of measurements fall.
- **Little's law**: concurrency = throughput × time in system.
- **Correlation id / trace / span**: the id of a request across services / the whole journey / one step of it.
- **Data contract**: a published, enforced description of what an interface accepts.
- **Quarantine**: where rejected records are kept, with reasons, instead of being processed.
- **12-factor config**: environment-specific settings come from the environment, not the code.
