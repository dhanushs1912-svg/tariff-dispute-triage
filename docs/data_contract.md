# Data contracts (D1)

Every external interface has a versioned JSON Schema in `contracts/`, generated from the Pydantic
models in `src/triage/contracts.py`. The API serves the live schema at `GET /v1/contract`.

## `dispute_request.v1`: POST /v1/disputes

| Field | Type | Rules |
|---|---|---|
| `account_number` | string | `^[A-Z0-9][A-Z0-9/-]{3,23}$` |
| `escom` | enum | BESCOM, MESCOM, CESC, HESCOM, GESCOM, HRECS, MSEZ |
| `connection_type` | enum | LT, HT |
| `billed_category` | enum | the 22 KERC categories: LT-1 ... LT-7, HT-1 ... HT-7 |
| `sanctioned_load_kw` | number | > 0, <= 20000 |
| `connected_load_kw` | number or null | >= 0, <= 20000 |
| `premises_use` | list of enum | 1–4 unique values from residential, commercial, industrial, agricultural, institutional, religious, other |
| `claimed_dispute_type` | enum or null | tariff_category, meter_accuracy, load_violation, arrears, disconnection, other |
| `bill_period_start`, `bill_period_end` | date | ISO dates |
| `billed_amount_inr` | number | >= 0, <= 10 crore |
| `description` | string | 20–2000 characters (screened by the guardrails before any model sees it) |

Unknown fields are rejected (`extra = forbid`).

Cross-field rules:
- An LT connection must have an LT category, and an HT connection an HT category (LT-6(c)/HT EV
  charging is allowed on both).
- LT needs a sanctioned load below 150 kW (General Terms para 9 of the tariff order).
- `bill_period_end` must not be before `bill_period_start`.
- The bill period must not exceed 12 months.
- The period must not end in the future.

**On rejection:**
- the API answers 422 with `{"error": "validation_failed", "quarantine_id", "agent_run_started": false, "errors": [{loc, msg, type, input}]}`;
- the payload and its field-level errors are written to the `quarantine` table;
- `quarantined_requests_total{reason}` is incremented;
- no row is created in `runs` and nothing is enqueued.

Bodies that are not valid JSON are quarantined the same way.

## `tariff_position.v1`: result in GET /v1/runs/{id}

`route`, `dispute_type`, `billed_category`, `determined_category`, `position`, `claims[]`
(text, citation ids, verified flag), `citations[]` (chunk id, document, locator, exact quote),
`escalation` (reason, explanation), `verification` (decision, attempts, checks, judge),
`prompt_versions`, `cost_usd`, `latency_ms` and `disclaimer`.

## `feedback.v1`: POST /v1/runs/{id}/feedback

`satisfactory` (bool) and `reason` (3–500 characters). Extra fields are rejected.

## Internal: model gateway

`POST /v1/complete` on `llm-gateway` takes `{messages, run_id, agent, step, json_mode, max_tokens, temperature}`
and returns `{content, prompt_tokens, completion_tokens, cost_usd, provider, retries, degraded, latency_ms}`,
or 503 `{error: "provider_unavailable", attempts, breakers}`.
