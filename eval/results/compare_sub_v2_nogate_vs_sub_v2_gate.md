# sub_v2_nogate vs sub_v2_gate

| metric | sub_v2_nogate | sub_v2_gate | change |
|---|---|---|---|
| n | 8 | 8 | 0 |
| errors | 0 | 0 | 0 |
| route_accuracy | 0.5 | 0.25 | -0.25 |
| route_acceptable | 0.75 | 0.625 | -0.125 |
| category_accuracy | 0.571 | 0.286 | -0.285 |
| escalation_accuracy | None | None |  |
| support_cited | 0.562 | 0.688 | 0.126 |
| support_retrieved | 0.875 | 0.875 | 0.0 |
| groundedness | 0.917 | 0.771 | -0.146 |
| context_relevance | 0.392 | 0.425 | 0.033 |
| faithfulness | 0.833 | 0.5 | -0.333 |
| hallucination_rate | 0.0 | 0.0 | 0.0 |
| case41_route | escalated-to-officer | escalated-to-officer |  |
| case41_support_cited | 0.0 | 1.0 | 1.0 |
| mean_cost_usd | 0.006 | 0.007 | 0.001 |
| cost_per_100_runs_usd | 0.6 | 0.7 | 0.1 |
| mean_tokens | 33608.125 | 38063.375 | 4455.25 |
| mean_steps | 20.625 | 23.5 | 2.875 |
| mean_tool_calls | 6.25 | 5.875 | -0.375 |
| p50_latency_s | 19.01 | 26.62 | 7.61 |
| p95_latency_s | 62.89 | 50.39 | -12.5 |
