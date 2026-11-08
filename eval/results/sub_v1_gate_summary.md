# Evaluation: sub_v1_gate

Settings: `{"research": "v1", "modifier_gate": true}`

| metric | value |
|---|---|
| n | 8 |
| errors | 0 |
| route_accuracy | 0.25 |
| route_acceptable | 0.5 |
| category_accuracy | 0.286 |
| escalation_accuracy | None |
| support_cited | 0.625 |
| support_retrieved | 0.875 |
| groundedness | 0.69 |
| context_relevance | 0.429 |
| faithfulness | 0.429 |
| hallucination_rate | 0.0 |
| case41_route | escalated-to-officer |
| case41_support_cited | 1.0 |
| mean_cost_usd | 0.006 |
| cost_per_100_runs_usd | 0.6 |
| mean_tokens | 30714.375 |
| mean_steps | 22.25 |
| mean_tool_calls | 5.625 |
| p50_latency_s | 22.32 |
| p95_latency_s | 32.1 |

| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |
|---|---|---|---|---|---|---|---|---|---|
| S01 | bill-stands-with-reason | escalated-to-officer | ok | None | 1.0 | 0.5 | 0.0 | 0.00597015 | 22.32 |
| S02 | revision-recommended | escalated-to-officer | no | None | 0.0 | 0.5 | 0.0 | 0.0080004 | 32.1 |
| S04 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.00727665 | 31.77 |
| S07 | revision-recommended | escalated-to-officer | no | None | 1.0 | 0.5 | 0.0 | 0.00514305 | 21.26 |
| S12 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 0.5 | 1.0 | 0.0 | 0.00317925 | 10.64 |
| S13 | site-inspection-required | revision-recommended | ok | LT-1 | 1.0 | 1.0 | 0.0 | 0.00200535 | 9.21 |
| S22 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-5 | 0.5 | 1.0 | 0.0 | 0.0040257 | 14.63 |
| S24 | bill-stands-with-reason | escalated-to-officer | no | None | 1.0 | 0.3333333333333333 | 0.0 | 0.00840135 | 28.66 |
