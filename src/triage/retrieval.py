"""Hybrid retrieval over the KERC corpus (L1).

Dense search (MiniLM in Chroma) finds passages that paraphrase the question; BM25 finds exact
terms the dense model blurs ("Tailoring shop", "42.02", "LT-5"). Results are fused with
reciprocal-rank fusion. A clause index supports lookup by identifier and following the
cross references written into the text. Exposed to LangChain through HybridRetriever.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from rank_bm25 import BM25Okapi

from .cache import get_redis, index_version
from .config import settings
from .embeddings import LocalEmbeddings
from .metrics import CACHE

DOC_ALIASES = {
    "tariff_order": "kerc_to_2025", "tariff": "kerc_to_2025", "kerc_to_2025": "kerc_to_2025",
    "conditions_of_supply": "kerc_cos_2006", "supply_code": "kerc_cos_2006", "cos": "kerc_cos_2006",
    "kerc_cos_2006": "kerc_cos_2006",
}
COMMENTARY_WEIGHT = 0.6
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = {"the", "of", "and", "to", "in", "a", "for", "is", "be", "by", "or", "as", "on", "with", "shall", "this",
         "that", "under", "any", "such", "are", "at", "from", "which", "if", "an", "it", "its", "i", "my", "me"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def normalize_clause(ref: str) -> list[str]:
    r = ref.strip().upper().replace("CLAUSE", "").replace("PARA", "").strip()
    r = re.sub(r"\s+", "", r)
    cands = []
    m = re.fullmatch(r"(COS-?)?(\d{1,2}\.\d{2})", r)
    if m:
        cands.append(f"COS-{m.group(2)}")
    m = re.fullmatch(r"(TO-?)?(LT|HT)-?(\d.*)", r)
    if m:
        cands.append(f"TO-{m.group(2)}-{m.group(3)}")
    m = re.fullmatch(r"(TO-)?(GT|LTB)-?(\d{1,2})", r)
    if m:
        cands.append(f"TO-{m.group(2)}-{m.group(3)}")
    if r.startswith(("TO-", "COS-")):
        cands.append(r)
    return [re.sub(r"\(([A-Z]+)\)", lambda m: f"({m.group(1).lower()})", c) for c in cands]


class CorpusStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._version: str | None = None
        self._loaded_at = 0.0
        self.ids: list[str] = []
        self.docs: list[str] = []
        self.metas: list[dict] = []
        self.by_id: dict[str, int] = {}
        self.by_clause: dict[str, list[int]] = {}
        self.bm25: BM25Okapi | None = None
        self.collection = None
        s = settings()
        self.embedder = LocalEmbeddings(s.embed_model, s.embed_cache_dir, redis=get_redis())

    def _ensure(self) -> None:
        version = index_version()
        if self._version == version and self.bm25 is not None and time.time() - self._loaded_at < 600:
            return
        with self._lock:
            if self._version == version and self.bm25 is not None and time.time() - self._loaded_at < 600:
                return
            from .ingest import get_collection

            self.collection = get_collection(create=False)
            data = self.collection.get(include=["documents", "metadatas"])
            self.ids, self.docs, self.metas = data["ids"], data["documents"], data["metadatas"]
            self.by_id = {cid: i for i, cid in enumerate(self.ids)}
            self.by_clause = {}
            for i, m in enumerate(self.metas):
                self.by_clause.setdefault(m["clause_ref"], []).append(i)
            self.bm25 = BM25Okapi([tokenize(d) for d in self.docs])
            self._version = version
            self._loaded_at = time.time()

    def _passage(self, i: int, score: float | None = None) -> dict:
        m = self.metas[i]
        return {
            "chunk_id": self.ids[i], "doc_id": m["doc_id"], "doc_title": m.get("doc_title", m["doc_id"]),
            "locator": m["locator"], "clause_ref": m["clause_ref"], "superseded": bool(m.get("superseded")),
            "refs": [r for r in (m.get("refs") or "").split(",") if r], "text": self.docs[i],
            "score": None if score is None else round(float(score), 4),
        }

    def _allowed(self, i: int, doc_id: str | None, include_superseded: bool) -> bool:
        m = self.metas[i]
        if doc_id and m["doc_id"] != doc_id:
            return False
        if not include_superseded and m.get("superseded"):
            return False
        return True

    def search(self, query: str, k: int = 5, mode: str = "hybrid", doc: str | None = None,
               include_superseded: bool = False) -> list[dict]:
        self._ensure()
        doc_id = DOC_ALIASES.get((doc or "").lower()) if doc else None
        k = max(1, min(int(k), 10))
        cache_key = None
        s = settings()
        if s.retrieval_cache_enabled:
            raw = json.dumps([self._version, query.strip().lower(), k, mode, doc_id, include_superseded])
            cache_key = "ret:" + hashlib.sha1(raw.encode()).hexdigest()
            try:
                hit = get_redis().get(cache_key)
                if hit:
                    CACHE.labels("hit").inc()
                    return json.loads(hit)
                CACHE.labels("miss").inc()
            except Exception:
                pass

        ranks: dict[int, float] = {}
        if mode in ("hybrid", "keyword"):
            scores = self.bm25.get_scores(tokenize(query))
            order = sorted((i for i in range(len(scores)) if self._allowed(i, doc_id, include_superseded)),
                           key=lambda i: -scores[i])[: k * 4]
            for rank, i in enumerate(order):
                if scores[i] > 0:
                    ranks[i] = ranks.get(i, 0.0) + 1.0 / (60 + rank)
        if mode in ("hybrid", "dense"):
            where = {"doc_id": doc_id} if doc_id else None
            res = self.collection.query(query_embeddings=[self.embedder.embed_query(query)], n_results=k * 4,
                                        where=where, include=["distances"])
            rank = 0
            for cid in res["ids"][0]:
                i = self.by_id.get(cid)
                if i is None or not self._allowed(i, doc_id, include_superseded):
                    continue
                ranks[i] = ranks.get(i, 0.0) + 1.0 / (60 + rank)
                rank += 1
        # Chapter text and public-consultation appendices discuss provisions; Annexure-9 and the CoS
        # state them. Down-weight commentary so it does not crowd out the provisions themselves.
        for i in ranks:
            if self.metas[i]["clause_ref"].startswith("TO-P"):
                ranks[i] *= COMMENTARY_WEIGHT
        best = sorted(ranks.items(), key=lambda kv: -kv[1])[:k]
        out = [self._passage(i, score) for i, score in best]
        if cache_key:
            try:
                get_redis().set(cache_key, json.dumps(out), ex=s.retrieval_cache_ttl)
            except Exception:
                pass
        return out

    def get_clause(self, ref: str, limit: int = 4) -> list[dict]:
        """Chunks of one provision; applicability text and notes before rate tables."""
        self._ensure()
        out = []
        for cand in normalize_clause(ref):
            for i in self.by_clause.get(cand, []):
                if not self.metas[i].get("superseded"):
                    out.append(self._passage(i))
            if out:
                break
        is_table = lambda p: p["text"].split("\n", 1)[-1].lstrip().startswith(("Particulars", "LT-6(c): ToD", "DEMAND BASED"))
        out.sort(key=is_table)
        return out[:limit]

    def get_chunk(self, chunk_id: str) -> dict | None:
        self._ensure()
        i = self.by_id.get(chunk_id)
        return None if i is None else self._passage(i)

    def cross_references(self, chunk_id: str) -> list[dict]:
        p = self.get_chunk(chunk_id)
        if not p:
            return []
        out = []
        for ref in p["refs"][:6]:
            hits = self.by_clause.get(ref, [])
            if hits:
                first = self._passage(hits[0])
                out.append({"ref": ref, "chunk_id": first["chunk_id"], "locator": first["locator"],
                            "preview": first["text"][:200]})
            else:
                out.append({"ref": ref, "chunk_id": None, "locator": "not in corpus", "preview": ""})
        return out

    def stats(self) -> dict:
        self._ensure()
        return {"chunks": len(self.ids), "version": self._version}


class HybridRetriever(BaseRetriever):
    """LangChain retriever over CorpusStore; used by the evaluation harness and the baseline pipeline."""

    store: object
    k: int = 5
    mode: str = "hybrid"

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return [Document(page_content=p["text"], metadata={k: v for k, v in p.items() if k != "text"})
                for p in self.store.search(query, k=self.k, mode=self.mode)]


_store: CorpusStore | None = None


def get_store() -> CorpusStore:
    global _store
    if _store is None:
        _store = CorpusStore()
    return _store
