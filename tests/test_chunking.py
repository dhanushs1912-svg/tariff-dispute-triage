"""The section 4.1 case depends on these passages being chunked cleanly (Evaluation 1 evidence)."""
import os

import pytest

from triage.chunking import chunk_conditions_of_supply, chunk_tariff_order
from triage.ingest import SCHEDULE_START_PAGE, build_chunks, load_manifest, parse_pdf, sha256

CORPUS = os.environ["CORPUS_DIR"]


@pytest.fixture(scope="module")
def chunks():
    out = {}
    for doc in load_manifest(CORPUS):
        path = os.path.join(CORPUS, doc["file"])
        out[doc["doc_id"]] = build_chunks(doc, parse_pdf(path), sha256(path))
    return out


def find(chunks, doc, ref, phrase):
    return [c for c in chunks[doc] if c.clause_ref == ref and phrase.lower() in c.text.lower()]


def test_lt1_lists_tailoring_as_permitted_home_use(chunks):
    hits = find(chunks, "kerc_to_2025", "TO-LT-1", "a portion is used by the occupant")
    assert hits and "(e) Tailoring" in hits[0].text


def test_lt5_lists_tailoring_shop(chunks):
    assert find(chunks, "kerc_to_2025", "TO-LT-5", "Tailoring shop")


def test_cos_misuse_and_reclassification(chunks):
    assert find(chunks, "kerc_cos_2006", "COS-42.02", "higher method of charging")
    assert find(chunks, "kerc_cos_2006", "COS-3.04", "reclassify")
    assert find(chunks, "kerc_to_2025", "TO-GT-29", "will prevail over the extract")


def test_superseded_text_is_marked(chunks):
    old = [c for c in chunks["kerc_cos_2006"] if c.superseded]
    assert old and all("SUPERSEDED" in c.text for c in old)
    current = find(chunks, "kerc_cos_2006", "COS-42.02", "12 months immediately preceding")
    assert current and not current[0].superseded


def test_chunk_ids_are_stable(chunks):
    doc = load_manifest(CORPUS)[1]
    path = os.path.join(CORPUS, doc["file"])
    again = build_chunks(doc, parse_pdf(path), sha256(path))
    assert [c.chunk_id for c in again] == [c.chunk_id for c in chunks[doc["doc_id"]]]


def test_cross_references_extracted(chunks):
    lt4 = [c for c in chunks["kerc_to_2025"] if c.clause_ref.startswith("TO-LT-4") and "42.06" in c.text]
    assert lt4 and "COS-42.06" in lt4[0].refs
