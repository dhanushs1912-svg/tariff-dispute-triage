"""Guardrails (L4): prompt-injection screening on free text, toxicity checks on input and output,
and an output filter that stops the system issuing a determination it is not authorised to make.

The injection screen is deliberately layered: (1) pattern rules here, (2) the consumer text is
always wrapped in <consumer_text> and declared as data in every prompt, (3) each agent has a tool
allow-list and no tool can change a bill or a route, (4) the verifier re-checks the output.
"""
from __future__ import annotations

import re
import unicodedata

_INJECTION_RULES = [
    (r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|system|your)\b.{0,30}\b(instruction|prompt|rule|direction|guideline)s?", 3),
    (r"\b(system prompt|developer message|hidden instructions?)\b", 2),
    (r"\byou are (now|no longer)\b|\bact as\b|\bpretend to be\b|\broleplay\b", 2),
    (r"\b(new|updated) instructions?\b", 2),
    (r"\b(route|mark|classify|set)\b.{0,25}\b(this|the case|status|route)\b.{0,25}\b(as|to)\b.{0,25}\b(revision|approved|bill-stands|refund|waive)", 3),
    (r"\"?(action|tool|route)\"?\s*:\s*\"", 2),
    (r"<\s*/?\s*(system|assistant|consumer_text|instructions?)\s*>|\[\s*/?\s*(INST|SYS)\s*\]|<\|im_(start|end)\|>", 3),
    (r"\b(call|use|invoke|run)\b.{0,20}\b(tool|function|search_corpus|get_clause|finish)\b", 2),
    (r"\b(reveal|print|show|repeat)\b.{0,30}\b(prompt|instructions|api key|secret|password)\b", 3),
    (r"[A-Za-z0-9+/]{120,}={0,2}", 1),
]
_INJ = [(re.compile(p, re.I | re.S), w) for p, w in _INJECTION_RULES]

_TOXIC_TERMS = [
    "idiot", "stupid", "moron", "bastard", "bloody fool", "scoundrel", "rascal", "fuck", "shit", "asshole",
    "bitch", "dumb", "useless fellows", "i will kill", "kill you", "burn your office", "beat you", "thieves",
    "chor", "kamina", "harami", "saala", "bewakoof", "lofer",
]
_TOX = re.compile(r"\b(" + "|".join(re.escape(t) for t in _TOXIC_TERMS) + r")\b", re.I)
_THREAT = re.compile(r"\b(kill|burn|attack|beat|hurt)\b.{0,20}\b(you|officer|staff|office|lineman)\b", re.I)

_AMOUNT = re.compile(r"(₹|\bRs\.?\s*\d|\bINR\s*\d|\brupees?\s+\d|\d[\d,]*\s*(rupees|/-))", re.I)
_BILL_ACTION = re.compile(
    r"\b(revis(e|ed|ing) the bill to|bill (is|has been|shall be|will be) (revised|reduced|waived|cancelled)|"
    r"refund (of|the)|waive[ds]? (the|off)|recomput(e|ed)|recalculat(e|ed)|pay only|amount payable is|"
    r"we (have|will) (revise|refund|waive))", re.I)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
    return text


def injection_score(text: str) -> tuple[int, list[str]]:
    t = normalize(text)
    score, hits = 0, []
    for pat, weight in _INJ:
        if pat.search(t):
            score += weight
            hits.append(pat.pattern[:60])
    return score, hits


def toxicity(text: str) -> tuple[bool, list[str]]:
    t = normalize(text)
    hits = [m.group(0).lower() for m in _TOX.finditer(t)] + [m.group(0).lower() for m in _THREAT.finditer(t)]
    return bool(hits), hits[:5]


def screen_input(text: str) -> dict:
    score, inj_hits = injection_score(text)
    toxic, tox_hits = toxicity(text)
    return {
        "injection_score": score,
        "injection_flagged": score >= 3,
        "injection_rules": inj_hits,
        "toxic": toxic,
        "toxic_terms": tox_hits,
        "threat": bool(_THREAT.search(normalize(text))),
    }


def wrap_consumer_text(text: str) -> str:
    t = normalize(text).replace("<consumer_text>", "").replace("</consumer_text>", "")
    return t.strip()


def output_violations(texts: list[str]) -> list[str]:
    problems = []
    for t in texts:
        if not t:
            continue
        if _AMOUNT.search(t):
            problems.append(f"states an amount: {_AMOUNT.search(t).group(0)!r}")
        if _BILL_ACTION.search(t):
            problems.append(f"issues a bill determination: {_BILL_ACTION.search(t).group(0)!r}")
        toxic, hits = toxicity(t)
        if toxic:
            problems.append(f"toxic output: {hits}")
    return problems
