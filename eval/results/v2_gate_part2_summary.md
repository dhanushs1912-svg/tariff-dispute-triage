# Evaluation: v2_gate_part2

Settings: `{"research": "v2", "modifier_gate": true}`

| metric | value |
|---|---|
| n | 17 |
| errors | 0 |
| route_accuracy | 0.529 |
| route_acceptable | 0.706 |
| category_accuracy | 0.333 |
| escalation_accuracy | 1.0 |
| support_cited | 0.615 |
| support_retrieved | 0.962 |
| groundedness | 0.867 |
| context_relevance | 0.555 |
| faithfulness | 0.7 |
| hallucination_rate | 0.013 |
| case41_route | None |
| case41_support_cited | None |
| mean_cost_usd | 0.004 |
| cost_per_100_runs_usd | 0.4 |
| mean_tokens | 23438.471 |
| mean_steps | 15.412 |
| mean_tool_calls | 3.824 |
| p50_latency_s | 15.84 |
| p95_latency_s | 44.84 |

| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |
|---|---|---|---|---|---|---|---|---|---|
| S10 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.00775065 | 28.44 |
| S11 | revision-recommended | escalated-to-officer | no | None | 1.0 | None | 0.14285714285714285 | 0.01119735 | 44.84 |
| S12 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-3(a) | 0.5 | 1.0 | 0.0 | 0.0041904 | 15.84 |
| S13 | site-inspection-required | revision-recommended | ok | LT-1 | 1.0 | 1.0 | 0.0 | 0.0069963 | 26.62 |
| S14 | site-inspection-required | site-inspection-required | yes | LT-1 | 1.0 | 1.0 | 0.0 | 0.0021582 | 8.09 |
| S15 | bill-stands-with-reason | escalated-to-officer | no | None | 0.0 | 0.5 | 0.0 | 0.00583185 | 29.95 |
| S16 | revision-recommended | revision-recommended | yes | LT-1 | 0.0 | 1.0 | 0.0 | 0.0019416 | 6.74 |
| S17 | escalated-to-officer | revision-recommended | ok | LT-1 | 1.0 | 1.0 | 0.0 | 0.00233715 | 9.79 |
| S18 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.11 |
| S19 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.1 |
| S20 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.12 |
| S21 | escalated-to-officer | escalated-to-officer | yes | None | 1.0 | 0.5 | 0.0 | 0.0057633 | 18.95 |
| S22 | bill-stands-with-reason | site-inspection-required | ok | LT-1 | 0.5 | 1.0 | 0.0 | 0.00225645 | 8.1 |
| S23 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0071223 | 24.2 |
| S24 | bill-stands-with-reason | escalated-to-officer | no | None | 1.0 | 0.6666666666666666 | 0.0 | 0.00731955 | 26.09 |
| S25 | revision-recommended | revision-recommended | yes | LT-6(c) | 1.0 | 1.0 | 0.0 | 0.0052485 | 16.91 |
| S26 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.12 |
