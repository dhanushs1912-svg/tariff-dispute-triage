# Evaluation: v2_gate_final

Settings: `{"research": "v2", "modifier_gate": true, "merged_from": ["v2_gate_part1", "v2_gate_part2"]}`

| metric | value |
|---|---|
| n | 26 |
| errors | 0 |
| route_accuracy | 0.538 |
| route_acceptable | 0.731 |
| category_accuracy | 0.471 |
| escalation_accuracy | 1.0 |
| support_cited | 0.659 |
| support_retrieved | 0.955 |
| groundedness | 0.851 |
| context_relevance | 0.501 |
| faithfulness | 0.684 |
| hallucination_rate | 0.007 |
| case41_route | escalated-to-officer |
| case41_support_cited | 1.0 |
| mean_cost_usd | 0.005 |
| cost_per_100_runs_usd | 0.5 |
| mean_tokens | 26631.423 |
| mean_steps | 17.385 |
| mean_tool_calls | 4.385 |
| p50_latency_s | 16.91 |
| p95_latency_s | 45.27 |

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
