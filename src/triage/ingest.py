"""Idempotent corpus pipeline: read -> parse -> chunk -> embed -> index (D2).

    python -m triage.ingest                 # incremental: only new/changed chunks are embedded
    python -m triage.ingest --reembed-doc kerc_cos_2006   # re-embed one document only
    python -m triage.ingest --dry-run       # parse and chunk, print stats, write nothing

Chunk ids are a hash of (document checksum, clause reference, text), so re-running on an
unchanged corpus embeds nothing, and a changed document only re-embeds its changed chunks.
Chunks that no longer exist are deleted. Each run records data freshness in Postgres
(index_meta) and publishes the index version to Redis so workers reload their BM25 view.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time

import yaml

from .chunking import chunk_conditions_of_supply, chunk_tariff_order
from .config import settings
from .embeddings import LocalEmbeddings, model_slug
from .obs import log, setup_logging

logger = logging.getLogger("ingest")
SCHEDULE_START_PAGE = 535


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(corpus_dir: str) -> list[dict]:
    with open(os.path.join(corpus_dir, "manifest.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["documents"]


def parse_pdf(path: str) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def build_chunks(doc: dict, pages: list[str], digest: str):
    if doc["kind"] == "tariff_order":
        chunks = chunk_tariff_order(doc["doc_id"], doc["short"], pages, SCHEDULE_START_PAGE)
    elif doc["kind"] == "supply_code":
        chunks = chunk_conditions_of_supply(doc["doc_id"], doc["short"], pages)
    else:
        raise ValueError(f"unknown document kind {doc['kind']}")
    seen, out = set(), []
    for c in chunks:
        c.finalize(digest)
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        out.append(c)
    return out


def collection_name(base: str, embed_model: str) -> str:
    return f"{base}__{model_slug(embed_model)}"[:60]


def get_collection(create: bool = True):
    import chromadb

    s = settings()
    client = chromadb.HttpClient(host=s.chroma_host, port=s.chroma_port)
    name = collection_name(s.chroma_collection, s.embed_model)
    if create:
        return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine", "embed_model": s.embed_model})
    return client.get_collection(name=name)


def run(reembed_doc: str | None = None, dry_run: bool = False) -> dict:
    s = settings()
    started = time.time()
    manifest = load_manifest(s.corpus_dir)
    embedder = LocalEmbeddings(s.embed_model, s.embed_cache_dir)
    collection = None if dry_run else get_collection()

    totals = {"chunks_total": 0, "chunks_embedded": 0, "chunks_deleted": 0, "pages": 0}
    docs_meta = []
    for doc in manifest:
        path = os.path.join(s.corpus_dir, doc["file"])
        digest = sha256(path)
        if digest != doc["sha256"]:
            raise SystemExit(f"checksum mismatch for {doc['file']}: manifest {doc['sha256']}, file {digest}")
        t0 = time.time()
        pages = parse_pdf(path)
        chunks = build_chunks(doc, pages, digest)
        totals["pages"] += len(pages)
        totals["chunks_total"] += len(chunks)
        log(logger, logging.INFO, "parsed document", doc_id=doc["doc_id"], pages=len(pages), chunks=len(chunks),
            superseded=sum(c.superseded for c in chunks), seconds=round(time.time() - t0, 2))
        docs_meta.append({"doc_id": doc["doc_id"], "version": doc["version"], "sha256": digest,
                          "pages": len(pages), "chunks": len(chunks), "file": doc["file"]})
        if dry_run:
            continue

        existing = set(collection.get(where={"doc_id": doc["doc_id"]}, include=["metadatas"])["ids"])
        wanted = {c.chunk_id: c for c in chunks}
        stale = sorted(existing - wanted.keys())
        to_embed = [c for cid, c in wanted.items() if cid not in existing or doc["doc_id"] == reembed_doc]
        if stale:
            for i in range(0, len(stale), 500):
                collection.delete(ids=stale[i:i + 500])
        for i in range(0, len(to_embed), 64):
            batch = to_embed[i:i + 64]
            vectors = embedder.embed_documents([c.text for c in batch])
            collection.upsert(
                ids=[c.chunk_id for c in batch],
                embeddings=vectors,
                documents=[c.text for c in batch],
                metadatas=[{
                    "doc_id": c.doc_id, "doc_title": doc["title"], "doc_short": doc["short"], "locator": c.locator,
                    "clause_ref": c.clause_ref, "section": c.section[:200], "page": c.page,
                    "superseded": c.superseded, "refs": ",".join(c.refs), "doc_version": doc["version"],
                } for c in batch],
            )
        totals["chunks_embedded"] += len(to_embed)
        totals["chunks_deleted"] += len(stale)
        log(logger, logging.INFO, "indexed document", doc_id=doc["doc_id"], embedded=len(to_embed),
            deleted=len(stale), unchanged=len(wanted) - len(to_embed))

    seconds = max(time.time() - started, 1e-6)
    index_version = hashlib.sha1(json.dumps(sorted(d["sha256"] for d in docs_meta) + [s.embed_model]).encode()).hexdigest()[:12]
    summary = {
        **totals, "seconds": round(seconds, 2), "index_version": index_version,
        "pages_per_second": round(totals["pages"] / seconds, 2),
        "chunks_per_second": round(totals["chunks_total"] / seconds, 2), "docs": docs_meta,
    }
    if not dry_run:
        from . import db
        from .cache import get_redis

        db.init_schema()
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO index_meta (built_at, embed_model, docs, chunks_total, chunks_embedded, chunks_deleted,"
                " seconds, pages_per_second, chunks_per_second, index_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (time.time(), s.embed_model, db.J(docs_meta), totals["chunks_total"], totals["chunks_embedded"],
                 totals["chunks_deleted"], seconds, summary["pages_per_second"], summary["chunks_per_second"], index_version),
            )
        r = get_redis()
        previous = r.get("index:version")
        r.set("index:version", index_version)
        if previous and previous != index_version:
            for key in r.scan_iter("ret:*"):
                r.delete(key)
            for key in r.scan_iter("runcache:*"):
                r.delete(key)
    log(logger, logging.INFO, "ingest complete", **{k: v for k, v in summary.items() if k != "docs"})
    return summary


def main() -> None:
    setup_logging("ingest")
    parser = argparse.ArgumentParser(description="Build or update the KERC corpus index")
    parser.add_argument("--reembed-doc", help="re-embed every chunk of this doc_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = run(args.reembed_doc, args.dry_run)
    json.dump({k: v for k, v in summary.items()}, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
