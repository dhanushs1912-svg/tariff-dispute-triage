# Evaluation: sub_v2_nogate

Settings: `{"research": "v2", "modifier_gate": false}`

| metric | value |
|---|---|
| n | 8 |
| errors | 0 |
| route_accuracy | 0.5 |
| route_acceptable | 0.75 |
| category_accuracy | 0.571 |
| escalation_accuracy | None |
| support_cited | 0.562 |
| support_retrieved | 0.875 |
| groundedness | 0.917 |
| context_relevance | 0.392 |
| faithfulness | 0.833 |
| hallucination_rate | 0.0 |
| case41_route | escalated-to-officer |
| case41_support_cited | 0.0 |
| mean_cost_usd | 0.006 |
| cost_per_100_runs_usd | 0.6 |
| mean_tokens | 33608.125 |
| mean_steps | 20.625 |
| mean_tool_calls | 6.25 |
| p50_latency_s | 19.01 |
| p95_latency_s | 62.89 |

| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |
|---|---|---|---|---|---|---|---|---|---|
| S01 | bill-stands-with-reason | escalated-to-officer | ok | None | 0.0 | None | None | 0.00624465 | 21.2 |
| S02 | revision-recommended | site-inspection-required | ok | LT-1 | 0.5 | 1.0 | 0.0 | 0.00593895 | 19.01 |
| S04 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0156519 | 62.89 |
| S07 | revision-recommended | escalated-to-officer | no | None | 1.0 | 0.5 | 0.0 | 0.00405 | 17.28 |
| S12 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 0.5 | 1.0 | 0.0 | 0.0032469 | 9.79 |
| S13 | site-inspection-required | site-inspection-required | yes | LT-1 | 1.0 | 1.0 | 0.0 | 0.00503805 | 45.34 |
| S22 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-5 | 0.5 | 1.0 | 0.0 | 0.0018969 | 6.98 |
| S24 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 1.0 | 1.0 | 0.0 | 0.0031773 | 11.58 |
