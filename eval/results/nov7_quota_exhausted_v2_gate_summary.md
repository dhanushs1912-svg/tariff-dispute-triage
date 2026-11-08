# Evaluation: v2_gate

Settings: `{"research": "v2", "modifier_gate": true}`

| metric | value |
|---|---|
| n | 26 |
| errors | 0 |
| route_accuracy | 0.308 |
| route_acceptable | 0.308 |
| category_accuracy | 0.118 |
| escalation_accuracy | 0.5 |
| support_cited | 0.136 |
| support_retrieved | 0.455 |
| groundedness | 0.812 |
| context_relevance | 0.487 |
| faithfulness | 0.5 |
| hallucination_rate | 0.0 |
| case41_route | bill-stands-with-reason |
| case41_support_cited | 1.0 |
| mean_cost_usd | 0.003 |
| cost_per_100_runs_usd | 0.3 |
| mean_tokens | 19169.846 |
| mean_steps | 11.692 |
| mean_tool_calls | 3.462 |
| p50_latency_s | 2.01 |
| p95_latency_s | 211.31 |

| id | expected | got | ok | category | support cited | grounded | halluc. | cost $ | s |
|---|---|---|---|---|---|---|---|---|---|
| S01 | bill-stands-with-reason | bill-stands-with-reason | yes | LT-1 | 1.0 | 1.0 | 0.0 | 0.005784 | 38.5 |
| S02 | revision-recommended | revision-recommended | yes | LT-1 | 0.5 | 1.0 | 0.0 | 0.01351425 | 207.4 |
| S03 | bill-stands-with-reason | escalated-to-officer | no | None | 0.5 | None | None | 0.00482955 | 88.39 |
| S04 | revision-recommended | escalated-to-officer | no | None | 0.0 | 0.5 | 0.0 | 0.01317255 | 209.78 |
| S05 | bill-stands-with-reason | escalated-to-officer | no | None | 1.0 | 0.75 | 0.0 | 0.0160782 | 211.31 |
| S06 | bill-stands-with-reason | escalated-to-officer | no | None | 0.0 | None | None | 0.01411425 | 233.03 |
| S07 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.00630585 | 83.72 |
| S08 | site-inspection-required | escalated-to-officer | no | None | 0.0 | None | None | 0.00844875 | 130.72 |
| S09 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.00585915 | 209.45 |
| S10 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0013662 | 25.44 |
| S11 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0005676 | 2.01 |
| S12 | bill-stands-with-reason | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 23.84 |
| S13 | site-inspection-required | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 21.12 |
| S14 | site-inspection-required | escalated-to-officer | no | None | 0.0 | None | None | 0.00022095 | 1.14 |
| S15 | bill-stands-with-reason | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 1.85 |
| S16 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 0.25 |
| S17 | escalated-to-officer | escalated-to-officer | yes | None | 0.0 | None | None | 0.0 | 0.3 |
| S18 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.38 |
| S19 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.33 |
| S20 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.06 |
| S21 | escalated-to-officer | escalated-to-officer | yes | None | 0.0 | None | None | 0.0 | 0.42 |
| S22 | bill-stands-with-reason | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 0.43 |
| S23 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 0.46 |
| S24 | bill-stands-with-reason | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 0.45 |
| S25 | revision-recommended | escalated-to-officer | no | None | 0.0 | None | None | 0.0 | 0.47 |
| S26 | escalated-to-officer | escalated-to-officer | yes | None | None | None | None | 0.0 | 0.06 |
