# Evaluation: sub_v2_gate

Settings: `{"research": "v2", "modifier_gate": true, "merged_from": ["v2_gate_final"]}`

| metric | value |
|---|---|
| n | 8 |
| errors | 0 |
| route_accuracy | 0.25 |
| route_acceptable | 0.625 |
| category_accuracy | 0.286 |
| escalation_accuracy | None |
| support_cited | 0.688 |
| support_retrieved | 0.875 |
| groundedness | 0.771 |
| context_relevance | 0.425 |
| faithfulness | 0.5 |
| hallucination_rate | 0.0 |
| case41_route | escalated-to-officer |
| case41_support_cited | 1.0 |
| mean_cost_usd | 0.007 |
| cost_per_100_runs_usd | 0.7 |
| mean_tokens | 38063.375 |
| mean_steps | 23.5 |
| mean_tool_calls | 5.875 |
| p50_latency_s | 26.62 |
| p95_latency_s | 50.39 |

| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |
|---|---|---|---|---|---|---|---|---|---|
| S01 | bill-stands-with-reason | escalated-to-officer | ok | None | 1.0 | 0.5 | 0.0 | 0.00764655 | 50.39 |
| S02 | revision-recommended | escalated-to-officer | no | None | 0.5 | 0.5 | 0.0 | 0.00788205 | 29.11 |
| S04 | revision-recommended | escalated-to-officer | no | None | 0.0 | 0.5 | 0.0 | 0.00564765 | 24.07 |
| S07 | revision-recommended | revision-recommended | yes | LT-1 | 1.0 | 1.0 | 0.0 | 0.0118992 | 45.27 |
| S12 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 0.5 | 1.0 | 0.0 | 0.0041904 | 15.84 |
| S13 | site-inspection-required | revision-recommended | ok | LT-1 | 1.0 | 1.0 | 0.0 | 0.0069963 | 26.62 |
| S22 | bill-stands-with-reason | site-inspection-required | ok | LT-1 | 0.5 | 1.0 | 0.0 | 0.00225645 | 8.1 |
| S24 | bill-stands-with-reason | escalated-to-officer | no | None | 1.0 | 0.6666666666666666 | 0.0 | 0.00731955 | 26.09 |
