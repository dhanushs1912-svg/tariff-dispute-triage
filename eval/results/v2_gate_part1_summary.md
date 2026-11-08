# Evaluation: v2_gate_part1

Settings: `{"research": "v2", "modifier_gate": true}`

| metric | value |
|---|---|
| n | 9 |
| errors | 0 |
| route_accuracy | 0.556 |
| route_acceptable | 0.778 |
| category_accuracy | 0.625 |
| escalation_accuracy | None |
| support_cited | 0.722 |
| support_retrieved | 0.944 |
| groundedness | 0.833 |
| context_relevance | 0.435 |
| faithfulness | 0.667 |
| hallucination_rate | 0.0 |
| case41_route | escalated-to-officer |
| case41_support_cited | 1.0 |
| mean_cost_usd | 0.006 |
| cost_per_100_runs_usd | 0.6 |
| mean_tokens | 32662.556 |
| mean_steps | 21.111 |
| mean_tool_calls | 5.444 |
| p50_latency_s | 18.4 |
| p95_latency_s | 50.39 |

| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |
|---|---|---|---|---|---|---|---|---|---|
| S01 | bill-stands-with-reason | escalated-to-officer | ok | None | 1.0 | 0.5 | 0.0 | 0.00764655 | 50.39 |
| S02 | revision-recommended | escalated-to-officer | no | None | 0.5 | 0.5 | 0.0 | 0.00788205 | 29.11 |
| S03 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-5 | 1.0 | 1.0 | 0.0 | 0.0026043 | 7.11 |
| S04 | revision-recommended | escalated-to-officer | no | None | 0.0 | 0.5 | 0.0 | 0.00564765 | 24.07 |
| S05 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 0.0 | 1.0 | 0.0 | 0.00336495 | 9.34 |
| S06 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 1.0 | 1.0 | 0.0 | 0.00379815 | 14.18 |
| S07 | revision-recommended | revision-recommended | yes | LT-1 | 1.0 | 1.0 | 0.0 | 0.0118992 | 45.27 |
| S08 | site-inspection-required | revision-recommended | ok | LT-1 | 1.0 | 1.0 | 0.0 | 0.00493545 | 14.15 |
| S09 | revision-recommended | revision-recommended | yes | LT-2 | 1.0 | 1.0 | 0.0 | 0.00426495 | 18.4 |
