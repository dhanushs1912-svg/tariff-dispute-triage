"""Citation resolution and the four quality metrics, shared by the verifier, live scoring and the eval harness.

Definitions (also in docs/evaluation.md):
  groundedness       = supported claims / all claims (model judge reads only the cited passages)
  context_relevance  = mean cosine similarity between the dispute text and each cited passage (MiniLM),
                       rescaled from [0.1, 0.7] to [0, 1] and clipped
  faithfulness       = 1 if the judge says the route and category follow from the supported claims, else 0
  hallucination_rate = citations that do not resolve (unknown chunk id, superseded text, or quote not
                       found in the passage) plus claims with no citation, divided by all citations + uncited claims
"""
from __future__ import annotations

import difflib
import math
import re


_UNI = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
                      "‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})
_ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")


def _norm(text: str) -> str:
    text = text.translate(_UNI).lower()
    text = re.sub(r"[^a-z0-9%./() -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_found(quote: str, passage: str, threshold: float = 0.85) -> bool:
    """A quote resolves if it appears in the passage. Elided quotes ("A ... B") resolve if every
    segment of at least 12 characters appears, in order."""
    segments = [s for s in _ELLIPSIS.split(quote.translate(_UNI)) if len(_norm(s)) >= 12]
    if not segments:
        return False
    if len(segments) == 1:
        return _segment_found(segments[0], passage, threshold)
    p = _norm(passage)
    pos = 0
    for seg in segments:
        q = _norm(seg)
        i = p.find(q, pos)
        if i == -1:
            if not _segment_found(seg, passage, threshold):
                return False
            continue
        pos = i + len(q)
    return True


def _gapped_found(q: str, p: str, max_pieces: int = 3, min_piece: int = 8, max_gap: int = 600) -> bool:
    """Quote made of up to three verbatim pieces, in order, with short omitted stretches between them
    (an unmarked elision such as skipping list items). Every piece must be real passage text."""
    pos, rest = 0, q
    for piece_no in range(max_pieces):
        best = 0
        for end in range(len(rest), min_piece - 1, -1):
            i = p.find(rest[:end].strip(), pos)
            if i != -1 and (piece_no == 0 or i - pos <= max_gap):
                best, pos = end, i + len(rest[:end].strip())
                break
        if best == 0:
            return False
        rest = rest[best:].strip()
        if len(rest) < 3:
            return True
    return False


def _segment_found(quote: str, passage: str, threshold: float) -> bool:
    q, p = _norm(quote), _norm(passage)
    if len(q) < 12:
        return False
    if q in p:
        return True
    if _gapped_found(q, p):
        return True
    m = difflib.SequenceMatcher(None, p, q, autojunk=False).find_longest_match(0, len(p), 0, len(q))
    if m.size / len(q) >= threshold:
        return True
    window = p[max(0, m.a - m.b - 20): m.a - m.b + len(q) + 20]
    return difflib.SequenceMatcher(None, window, q, autojunk=False).ratio() >= threshold


def repair_citations(claims: list[dict], passages: dict[str, dict]) -> int:
    """Re-point a citation whose quote is not in the cited chunk to another retrieved chunk of the
    SAME clause that does contain it (models often quote a provision correctly but give the id of its
    neighbouring chunk). Edits claims in place; returns the number of repairs."""
    repaired = 0
    for c in claims:
        for x in c.get("citations") or []:
            p = passages.get(x.get("chunk_id"))
            if p is None or quote_found(x.get("quote", ""), p["text"]):
                continue
            ref = p.get("clause_ref")
            for cid, other in passages.items():
                if cid != x["chunk_id"] and ref and other.get("clause_ref") == ref \
                        and "[SUPERSEDED" not in other["text"] and quote_found(x.get("quote", ""), other["text"]):
                    x["repaired_from"] = x["chunk_id"]
                    x["chunk_id"] = cid
                    repaired += 1
                    break
    return repaired


def resolve_citations(claims: list[dict], passages: dict[str, dict]) -> dict:
    """Check every citation against the run's retrieved set. Returns per-claim results and totals."""
    results, total, bad = [], 0, 0
    for i, c in enumerate(claims):
        cites = c.get("citations") or []
        claim_res = {"index": i, "citations": [], "ok": bool(cites)}
        if not cites:
            bad += 1
            total += 1
            claim_res["problem"] = "claim has no citation"
        for x in cites:
            total += 1
            p = passages.get(x.get("chunk_id"))
            if p is None:
                status = "unknown_chunk"
            elif "[SUPERSEDED" in p["text"]:
                status = "superseded"
            elif not quote_found(x.get("quote", ""), p["text"]):
                status = "quote_not_found"
            else:
                status = "ok"
            if status != "ok":
                bad += 1
                claim_res["ok"] = False
            claim_res["citations"].append({"chunk_id": x.get("chunk_id"), "status": status})
        results.append(claim_res)
    return {"claims": results, "citations_total": total, "citations_bad": bad,
            "all_ok": bad == 0 and total > 0, "hallucination_rate": (bad / total) if total else 1.0}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def context_relevance(embedder, question: str, passages: list[str]) -> float | None:
    if not passages:
        return None
    q = embedder.embed_query(question)
    vecs = embedder.embed_documents(passages)
    sims = [cosine(q, v) for v in vecs]
    mean = sum(sims) / len(sims)
    return max(0.0, min(1.0, (mean - 0.1) / 0.6))
