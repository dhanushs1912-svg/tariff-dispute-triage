# Incident log (D8)

Real failures met while building the system, newest last.

## 1. Single-pass dense retrieval missed both 4.1 provisions (4 Nov 2026)

- **What happened:** we embedded the corpus with all-MiniLM-L6-v2 and ran the section 4.1 question
  as one dense query. The top 5 were CoS 3.03, three public-consultation pages from the tariff
  order and LT billing condition 1. Neither LT-1 (which lists tailoring by the occupant) nor LT-5
  ("Tailoring shop") was returned.
- **Impact:** a one-shot RAG pipeline would have answered the reference case without its deciding
  provisions.
- **Cause:** the question's words ("domestic connection", "which category") match general
  classification text and consultation replies better than the schedule wording ("portion is used
  by the occupant", "Tailoring shop"). Consultation pages also flood the index: 567 pages, most of
  them commentary.
- **Fix:**
  1. Hybrid BM25 plus dense retrieval with reciprocal-rank fusion.
  2. Commentary pages down-weighted (x0.6).
  3. Clause-aware chunks with clause references.
  4. The modifier gate, which makes the agent search again with words from the passages it read.

  With queries the agent derives, "tailoring shop industrial tariff schedule" returns LT-5 first
  and "portion used by the occupant tailoring" returns LT-1 first.
- **Detection:** `ret.py` comparison during development; now covered by scenario S01.

## 2. Clause references for lettered schedules were unreachable (4 Nov 2026)

- **What happened:** `get_clause("LT-3(a)")` returned nothing, and the chunk count by clause
  reference showed no `TO-LT-3(a)` or `TO-LT-6(c)` at all.
- **Cause:** `norm_ref()` upper-cased the whole reference, so chunks were stored as `TO-LT-3(A)`,
  while lookups and cross references used lower case.
- **Impact:** lookup by identifier, the agent's second retrieval strategy and the verifier's retry
  path, was broken for 8 of the 22 tariff categories.
- **Fix:** `norm_ref()` lower-cases the letters in parentheses. The test suite now covers every
  scenario anchor, including LT-3(a) and LT-6(c).

## 3. Superseded "OLD VERSION" text indexed as current law (4 Nov 2026)

- **What happened:** the first chunking of CoS 42.02 produced a chunk that read "(a) ... subject to
  a maximum of 6 months and charge at two times". That is the superseded wording; the clause in
  force says 12 months. It was not marked superseded, because the OLD VERSION block started with
  the same sub-clause letter "(a)" as the current text, and the splitter treated "(a)" as the end
  of the old block.
- **Impact:** the agent could have cited repealed text as the current rule.
- **Fix:** the old block now ends only at a different sub-clause letter, a new clause or an
  "Amended version" marker. Inline "Old version: ..." phrases are removed. Superseded chunks are
  excluded from search, and the verifier rejects citations to them.
  `test_superseded_text_is_marked` covers this case.

## 4. Provider rejected every research call: "Tool choice is none, but model called a tool" (5 Nov 2026)

- **What happened:** the first runs on the real provider escalated as `provider_unavailable`
  straight after intake. The gateway logged HTTP 400 `tool_use_failed` from both the primary and
  the fallback model.
- **Cause:** the research prompt listed the tools in plain text and asked for a JSON reply. The
  model (a reasoning model with native tool calling) tried to make a real tool call, and the
  provider refused it because the request declared no tools. Two related quirks followed. Sometimes
  the model wrote its call as text when a tool call was required (400 again). Sometimes it named the
  finish call `json` instead of `finish`.
- **Fix:**
  - The research agent now sends proper tool definitions (`TOOL_SCHEMAS`, with `finish` as a tool),
    and the gateway normalises tool calls back into the agent's action format.
  - On `tool_use_failed`, the gateway recovers the call from the provider's `failed_generation`
    field.
  - Any call carrying a `route` argument is treated as `finish`.
- **Lesson:** the stub never exercised the provider's tool-calling rules. A real-provider smoke run
  is now part of the setup checklist.

## 5. Free-tier rate limit turned into escalations (5 Nov 2026)

- **What happened:** back-to-back runs escalated as `provider_unavailable`. The gateway showed
  `rate_limited` on both models.
- **Cause:**
  - The provider's free tier allows 8,000 tokens per minute per model, and one research run used
    20k–55k tokens.
  - Every model call re-sent every passage already retrieved.
  - The fallback model was given only one retry.
- **Fix:**
  - On a rate limit, the gateway switches to the fallback model immediately.
  - The fallback model now gets the full retry budget with backoff of up to 30 s.
  - The prompt now shows each retrieved passage once, in one block, and repeated identical
    searches are refused without calling the tool.
  - Tokens per run for the 4.1 case fell from about 55k to about 22k.

## 6. DNS outage mid-run (5 Nov 2026)

- **What happened:** a run sat in `verifying` for several minutes and then escalated. The gateway
  logged `connect: [Errno -2] Name or service not known` for both providers.
- **Cause:** the laptop's internet connection dropped, so containers could not resolve the
  provider's host.
- **Behaviour:** this is the path we designed for. The gateway retried with backoff, the fallback's
  circuit breaker opened, the agent escalated with `provider_unavailable`, and no unverified answer
  was returned. The next run after the connection came back completed normally.
- **Follow-up:** none in code. The runbook's failure mode 1 covers it.

## 7. Daily token quota exhausted during evaluation (5 Nov 2026)

- **What happened:** the first evaluation pass escalated S01–S06 as `provider_unavailable`. The
  breakers opened on all three models.
- **Cause:** the provider's free tier also has a **tokens-per-day** limit of 200,000 per model, on a
  rolling 24-hour window. A day of development runs used 199.8k on both gpt-oss models. One
  evaluation pass needs about 26 x 20k = 520k tokens, which is more than three free models allow
  per day.
- **Behaviour:** correct and safe. Every affected run escalated; none returned an answer.
- **Fix / decision:** the evaluation needs either a provider with a larger free daily quota as the
  primary, or the passes spread over several days. Daily quota is now a check in the runbook.

## 8. Evaluation pass ran into both the per-minute and the per-day limit (7 Nov 2026)

- **What happened:** in the first full pass (prompt v2, gate on), S01–S09 ran slowly. They spent most
  of their time waiting on per-minute limits, and three of them used up their 360 s budget while
  waiting. After S09 the daily quota of all three models was gone, so S10–S25 escalated as
  `provider_unavailable` within seconds.
- **Cause:**
  - Each run used 26k–90k tokens. Runs that went through a verifier retry cost about twice as much.
  - Three free models give about 600k tokens a day.
  - Rate limits also tripped the circuit breakers, which then refused calls that would have
    succeeded a few seconds later.
- **Fix:**
  1. Rate limits no longer count as breaker failures. When every model is rate-limited, the gateway
     waits for the earliest reset the provider reports (up to `LLM_RATE_LIMIT_WAIT_SECONDS`) and
     tries again. Real outages still open the breaker; this was checked with fault injection.
  2. Licensees outside the corpus are decided from the manifest before any model call (S18 and S19
     now escalate in under 100 ms at zero cost). The research model can no longer choose
     `outside_corpus` itself; it had misused it on S03.
  3. Fewer and shorter passages in each prompt.
- **Data:** only the first part of that pass is a valid measurement of the system. The pass is re-run
  in daily slices that fit the quota (`--only`).
