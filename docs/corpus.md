# Corpus confirmation (Evaluation 1)

State: **Karnataka**. Regulator: **Karnataka Electricity Regulatory Commission (KERC)**.

| doc_id | Document | Version | Pages | Text layer |
|---|---|---|---|---|
| `kerc_to_2025` | KERC Combined Tariff Order 2025 (BESCOM, MESCOM, CESC, HESCOM, GESCOM) | Order dated 27.03.2025, control period FY2025-26 to FY2027-28 | 567 | yes, no OCR needed |
| `kerc_cos_2006` | Conditions of Supply of Electricity of Distribution Licensees in the State of Karnataka (the supply code), with I and II amendments | Notified 17.06.2006; amendments 20.03.2008 and 22.07.2010 | 140 | yes, no OCR needed |

Both files, their SHA-256 checksums and their sources are recorded in `corpus/manifest.yaml`. The
ingest pipeline refuses to run if a checksum does not match.

Two things about this corpus matter for the design:

1. In the 2025 order the domestic category is **LT-1**. Older orders split domestic into LT-1
   (Bhagyajyothi) and LT-2(a); the 2025 order merged them. Our project plan said LT-2(a); the
   corpus shows LT-1 is correct.
2. The Conditions of Supply contains amended clauses with the superseded text printed beside them
   under "OLD VERSION". The chunker marks those passages as superseded so they cannot be cited.

## The section 4.1 case

> "I have a domestic connection. I run a small tailoring shop from one room of the house. Which
> tariff category should I be billed under?"

### Passages the case depends on

| # | Where | What it says | Why it matters |
|---|---|---|---|
| P1 | Tariff Order 2025, Annexure-9, Tariff Schedule **LT-1**, PDF p.547 | LT-1 applies to residential houses "and also to such houses where a portion is used by the occupant for ... (e) Tailoring ..." | The domestic category itself allows tailoring, but only by the occupant, in a portion of the house. This sentence is part of the definition, not a note. |
| P2 | Tariff Order 2025, Annexure-9, Tariff Schedule **LT-5**, PDF p.552 | LT-5 (industrial) applies to "... Tailoring shop ..." and "Garment manufacturing units" | The same activity appears under a second category. Neither schedule mentions the other. |
| P3 | Conditions of Supply, **Clause 42.02** (Misuse of electricity), p.79 | Energy supplied under one method of charging and "misused for purpose for which a higher method of charging is in force" is assessed at two times the applicable tariff | What happens if the premises is really a shop on a domestic meter. |
| P4 | Conditions of Supply, **Clause 3.04** (Reclassification), p.15 | The licensee may reclassify a consumer "classified under a particular Tariff category erroneously", after 15 days' notice | How a wrong category is corrected, and that reclassification needs an error. |
| P5 | Tariff Order 2025, Annexure-9, General Terms, **para 29**, PDF p.540 | The Conditions of Supply "will prevail over the extract given in this tariff book in the event of any discrepancy" | Tells the agent which document wins if they disagree. |

Why one search is not enough: on the question alone, dense retrieval with all-MiniLM-L6-v2 over
the full corpus returns CoS 3.03 and public-consultation pages from the tariff order, and neither
LT-1 nor LT-5 appears in its top 5. Keyword search finds the LT-1 note block but not the LT-5
schedule. LT-5 and the misuse clause only turn up when the agent searches again with words it
read, such as "tailoring shop" or "misuse higher tariff". We checked this on the indexed corpus on
4 Nov 2026 (incident log entry 1).

### Test values

| Field | Value |
|---|---|
| escom | BESCOM |
| connection_type | LT |
| billed_category | LT-1 |
| sanctioned_load_kw | 2 |
| connected_load_kw | 1.8 (within the sanctioned load, so load is not an issue) |
| premises_use | residential, commercial |
| description | the sentence in section 4.1, unchanged |

### Reference answer (to be confirmed with the faculty)

**Route: bill-stands-with-reason. Category: LT-1.** The consumer is the occupant and uses one room
of the house for tailoring, which LT-1 explicitly lists (P1). LT-5's "Tailoring shop" (P2) covers a
tailoring business as a shop or unit, not a portion of the occupant's house, so the domestic
billing is correct. The system must cite both P1 and P2.

Variants in the evaluation set test the boundary: S02 (occupant tailoring wrongly moved to LT-5 ->
revision-recommended, citing P1 and P4), S03 (a tailoring shop in a market complex -> LT-5 stands)
and S21 (a garment unit with six employees under the family's flat -> escalate, because the
provisions do not settle it).
