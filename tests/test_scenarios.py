"""Every evaluation scenario must be a valid request and every supporting anchor must exist in the corpus."""
import os

import pytest
import yaml

from triage.contracts import DisputeRequest
from triage.ingest import build_chunks, load_manifest, parse_pdf, sha256

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCEN = yaml.safe_load(open(os.path.join(ROOT, "eval", "scenarios.yaml"), encoding="utf-8"))["scenarios"]


@pytest.fixture(scope="module")
def chunks():
    out = []
    for doc in load_manifest(os.environ["CORPUS_DIR"]):
        path = os.path.join(os.environ["CORPUS_DIR"], doc["file"])
        out += build_chunks(doc, parse_pdf(path), sha256(path))
    return out


def test_at_least_20_including_41():
    assert len(SCEN) >= 20
    assert any("case41" in s.get("tags", []) for s in SCEN)


@pytest.mark.parametrize("s", SCEN, ids=[s["id"] for s in SCEN])
def test_scenario(s, chunks):
    DisputeRequest.model_validate(s["request"])
    for a in s["support"]:
        hits = [c for c in chunks if c.clause_ref == a["ref"] and not c.superseded
                and " ".join(a["phrase"].lower().split()) in " ".join(c.text.lower().split())]
        assert hits, f"{s['id']}: no chunk {a['ref']} containing {a['phrase']!r}"
