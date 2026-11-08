"""llm-stub: an OpenAI-compatible stand-in for the model provider (D6).

Returns fixed, well-formed responses after a realistic delay so that load tests measure our
system (queue, workers, retrieval, database) rather than a free tier's rate limits. It reads
the TASK marker in the system prompt and, for the research agent, walks a fixed script:
search, search again for modifying provisions, then finish citing passages it was shown.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

DELAY_MS = float(os.environ.get("STUB_DELAY_MS", "1500"))
JITTER_MS = float(os.environ.get("STUB_JITTER_MS", "300"))
STUB_CALLS = Counter("stub_calls_total", "Stub completions served", ["task"])

app = FastAPI(title="llm-stub", version="1.0.0")
_PASSAGE = re.compile(r"\[(C[0-9a-f]{16})\][^\n]*\n([^\n]{20,})")


def _task(messages: list[dict]) -> str:
    system = " ".join(m.get("content", "") for m in messages if m.get("role") == "system")
    m = re.search(r"TASK:\s*(\w+)", system)
    return m.group(1).lower() if m else "unknown"


def _intake(messages) -> dict:
    return {"dispute_type": "tariff_category", "premises_use_summary": "residence with part business use",
            "billed_category": None, "candidate_categories": ["LT-1", "LT-5"],
            "key_facts": ["domestic connection", "part of premises used for business"],
            "summary": "Consumer disputes the tariff category of a home with partial business use."}


def _research(messages) -> dict:
    text = "\n".join(m.get("content", "") for m in messages if m.get("role") in ("user", "assistant"))
    searches = text.count('"action": "search_corpus"') + text.count('"action":"search_corpus"')
    passages = _PASSAGE.findall(text)
    if searches == 0:
        return {"thought": "Find the category definition first.", "action": "search_corpus",
                "args": {"query": "domestic installation portion used by occupant tailoring", "k": 5}}
    if searches == 1:
        return {"thought": "Check provisions that modify the definition.", "action": "search_corpus",
                "args": {"query": "misuse of electricity purpose higher tariff reclassification", "k": 5}}
    picked = passages[:2]
    claims = []
    for cid, line in picked:
        words = line.split()
        quote = " ".join(words[: min(10, len(words))])
        claims.append({"text": "The cited provision governs the category for this use.",
                       "citations": [{"chunk_id": cid, "quote": quote}]})
    return {"thought": "Enough evidence.", "action": "finish",
            "args": {"route": "bill-stands-with-reason", "determined_category": "LT-1",
                     "position": "The billed category is consistent with the cited provisions.",
                     "claims": claims, "escalation": None}}


def _judge(messages) -> dict:
    text = messages[-1].get("content", "")
    n = max(1, len(re.findall(r"^CLAIM \d+", text, re.M)))
    return {"claims": [{"index": i, "supported": True, "reason": "stub"} for i in range(n)],
            "conclusion_follows": True, "reason": "stub"}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    task = _task(messages)
    STUB_CALLS.labels(task).inc()
    await asyncio.sleep(max(0.0, DELAY_MS + random.uniform(-JITTER_MS, JITTER_MS)) / 1000)
    payload = {"intake": _intake, "research": _research, "judge": _judge}.get(task, lambda m: {"ok": True})(messages)
    content = json.dumps(payload)
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return {
        "id": "stub", "object": "chat.completion", "model": body.get("model", "stub"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_chars // 4, "completion_tokens": len(content) // 4,
                  "total_tokens": prompt_chars // 4 + len(content) // 4},
    }


@app.get("/health")
def health():
    return {"status": "ok", "delay_ms": DELAY_MS}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
