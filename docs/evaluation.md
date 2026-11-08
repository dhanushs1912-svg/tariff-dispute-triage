# Evaluation (L2, L3)

## Evaluation set

`eval/scenarios.yaml` has 26 fixed scenarios. Each has a full request, an expected route and
category, any other routes we would accept, and the passages that support the expected outcome
(clause reference plus a phrase that must appear in that chunk). `tests/test_scenarios.py` checks
that every request passes the data contract and that every anchor exists in the indexed corpus.

| Group | Scenarios |
|---|---|
| Section 4.1 and its boundary | S01 (reference case), S02, S03, S21 |
| A note or a part-use list modifies a definition | S04, S05, S06, S07, S08, S10, S11, S22, S24 |
| A Conditions of Supply clause modifies the tariff book | S12 (misuse 42.02), S13 (change of use 39.01) |
| Plain definitions | S09, S23, S25 |
| Other dispute types | S14 meter, S15 load, S16 arrears, S17 disconnection |
| Must escalate | S18, S19 outside corpus, S20 prompt injection, S21 genuinely mixed, S26 threat |

## Running it

The stack must be up with a real model configured (see the README).

What we ran (free-tier quotas meant the main pass ran in two slices and the comparisons ran on a
fixed subset of 8 scenarios where a modifying provision decides the outcome):

```
# main pass, all 26 scenarios
docker compose --profile tools run --rm eval --variant v2_gate_part1 --research v2 --gate on --only S01,...,S09
docker compose --profile tools run --rm eval --variant v2_gate_part2 --research v2 --gate on --only S10,...,S26
docker compose --profile tools run --rm eval --variant v2_gate_final --merge v2_gate_part1 v2_gate_part2
# comparisons on S01,S02,S04,S07,S12,S13,S22,S24
docker compose --profile tools run --rm eval --variant sub_v2_gate --merge v2_gate_final --only <subset>
docker compose --profile tools run --rm eval --variant sub_v1_gate --research v1 --gate on --only <subset>
docker compose --profile tools run --rm eval --variant sub_v2_nogate --research v2 --gate off --only <subset>
docker compose --profile tools run --rm eval --compare sub_v1_gate sub_v2_gate
docker compose --profile tools run --rm eval --compare sub_v2_nogate sub_v2_gate
```

With a provider that allows more tokens per day, run all 26 scenarios for every variant instead.

The `X-Eval-Overrides` header selects the research prompt version and the modifier gate for each
run, so variants run against the same deployment. Results go to `eval/results/`: one JSONL row per
scenario, plus a summary as JSON and as markdown.

## Metrics and how each is computed

| Metric | Computation |
|---|---|
| Groundedness | Share of the answer's claims that the verifier's judge marks as supported. The judge sees only the passages each claim cites. |
| Context relevance | Mean cosine similarity (all-MiniLM-L6-v2) between the dispute text and each cited passage, rescaled from [0.1, 0.7] to [0, 1] and clipped. |
| Faithfulness | 1 if the judge says the route and category follow from the supported claims, else 0. |
| Hallucination rate | (citations that do not resolve + claims without any citation) / (citations + uncited claims). A citation does not resolve if its chunk id was never retrieved in this run, its text is marked superseded, or its quote is not found in the passage (fuzzy match, threshold 0.85). |
| Route accuracy / acceptable | Exact expected route / expected or accepted alternative. |
| Support cited / retrieved | Share of the expected supporting passages that the final answer cites, or that the agent retrieved at all. |

The four quality metrics are computed in `triage/quality.py`, the same code the live system uses.
We used our own implementation rather than TruLens because TruLens' feedback functions need a
second model provider. Our judge is the verifier itself, and the deterministic citation checks are
stricter than an LLM grader on our main failure mode, an invented or paraphrased quote.

## Prompt variants (L2)

- `research@v1`: tools listed, "find the provision that applies and answer with citations".
- `research@v2`: an explicit procedure. Find the definition, look for modifying provisions (notes,
  part-use lists, the same activity under another category, CoS 42.02, 3.04, 39, general terms
  23 and 29), search again with words read in the passages, never cite superseded text, and
  escalate rather than guess.

The prompt version tag (`id@version#hash`) is stored on every run and every model step.

## Deliberate change (L3)

The modifier gate is switched off (`--gate off`) with the same prompt, which reproduces the
"retrieve once and answer" pipeline the brief warns about. All four metrics, the route accuracy
and the support-cited rate are reported before (gate off) and after (gate on).

Results: `docs/report.md`.
