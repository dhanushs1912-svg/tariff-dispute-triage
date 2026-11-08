"""Clause-aware chunking for the KERC tariff order and the Conditions of Supply.

Why not fixed-size chunks: the decisive provisions in this corpus are short clauses and notes
(LT-1's list of permitted home uses, LT-5's list of industrial uses, CoS 42.02 on misuse).
Fixed windows merge them with rate tables and split them mid-sentence. We cut on the
document's own structure instead and attach a clause reference to every chunk so the agent
can fetch a clause by identifier and follow cross references.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

MAX_CHARS = 1800
_splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=150, separators=["\n\n", "\n", ". ", " "])
_MARK = re.compile(r"<<P(\d+)>>\n?")


@dataclass
class Chunk:
    doc_id: str
    text: str
    locator: str
    clause_ref: str
    section: str
    page: int
    superseded: bool = False
    refs: list[str] = field(default_factory=list)
    chunk_id: str = ""

    def finalize(self, doc_sha: str) -> "Chunk":
        h = hashlib.sha1(f"{doc_sha[:16]}|{self.clause_ref}|{self.text}".encode()).hexdigest()[:16]
        self.chunk_id = f"C{h}"
        self.refs = sorted(set(find_cross_refs(self.text)) - {self.clause_ref})
        return self


def clean(text: str) -> str:
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"),
                 ("—", "-"), ("‐", "-"), ("‑", "-"), ("‟", "'"), ("„", '"'),
                 ("\u0080", ""), ("�", "-")):
        text = text.replace(a, b)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def flatten(text: str) -> str:
    """Join soft-wrapped PDF lines into paragraphs; keep list markers on their own line."""
    text = _MARK.sub("", text)
    text = re.sub(r"\n(?=\s*(\(?[a-z]{1,4}\)|\d{1,2}\.\s|Note|NOTE|Particulars|TARIFF))", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def page_of(body: str, piece: str, default: int) -> int:
    pos = body.find(piece[:60]) if piece else -1
    pos = max(pos, 0)
    page = default
    for m in _MARK.finditer(body):
        if m.start() <= pos:
            page = int(m.group(1))
        else:
            break
    return page


def ascii_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isascii()) / len(letters)


def norm_ref(ref: str) -> str:
    r = ref.upper().replace(" ", "")
    r = re.sub(r"^(LT|HT)(\d)", r"\1-\2", r)
    return re.sub(r"\(([A-Z]+)\)", lambda m: f"({m.group(1).lower()})", r)


_XREF_PATTERNS = [
    (re.compile(r"Clause\s+(\d{1,2}\.\d{2})", re.I), lambda m: f"COS-{m.group(1)}"),
    (re.compile(r"\b(LT|HT)\s*-?\s*(\d)\s*(\(\s*[a-c]\s*\))?(\s*\(\s*i{1,2}\s*\))?"),
     lambda m: "TO-" + norm_ref(f"{m.group(1)}-{m.group(2)}{(m.group(3) or '').replace(' ', '')}{(m.group(4) or '').replace(' ', '')}")),
]


def find_cross_refs(text: str) -> list[str]:
    out = []
    for pat, fmt in _XREF_PATTERNS:
        for m in pat.finditer(text):
            out.append(fmt(m))
    return out


def _split_long(text: str) -> list[str]:
    if len(_MARK.sub("", text)) <= MAX_CHARS:
        return [text]
    return _splitter.split_text(text)


# ---------------------------------------------------------------- Conditions of Supply

_COS_HEADER = re.compile(r"^Conditions of Supply of Electricity\s+\d+\s+\d+/\d+/\d+\s*$", re.M)
_COS_CLAUSE = re.compile(r"^\s*(\d{1,2}\.\d{2})\b\.?\s*(.*)$")
_OLD = re.compile(r"\bOLD VERSION\b")
_INLINE_OLD = re.compile(r"\s*Old version\s*:[^.]*\.", re.I)
_SUBMARK = re.compile(r"^\s*(?:<<P\d+>>\s*)*\(?([a-z]|[ivx]+)\)\s", re.M)
_RESUME = re.compile(r"^(\(?([a-z]|[ivx]+)\)\s|\d{1,2}\.\d{2}\b|Amended version)", re.I | re.M)


def chunk_conditions_of_supply(doc_id: str, short: str, pages: list[str]) -> list[Chunk]:
    lines: list[tuple[int, str]] = []
    for pno, raw in enumerate(pages, start=1):
        txt = _COS_HEADER.sub("", clean(raw))
        lines.append((pno, f"<<P{pno}>>"))
        for line in txt.split("\n"):
            lines.append((pno, line))

    clauses: list[dict] = []
    current = {"ref": "COS-PREAMBLE", "title": "Preamble", "page": 1, "lines": []}
    parent_titles: dict[str, str] = {}
    for pno, line in lines:
        m = None if line.startswith("<<P") else _COS_CLAUSE.match(line)
        if m and float(m.group(1)) < 50:
            clauses.append(current)
            num, rest = m.group(1), m.group(2).strip()
            title = rest if rest.isupper() and len(rest) > 3 else ""
            if num.endswith(".00") and title:
                parent_titles[num.split(".")[0]] = title
            current = {"ref": f"COS-{num}", "title": title, "page": pno, "lines": [f"<<P{pno}>>", line]}
        else:
            current["lines"].append(line)
    clauses.append(current)

    chunks: list[Chunk] = []
    for cl in clauses:
        body = "\n".join(cl["lines"]).strip()
        if len(_MARK.sub("", body)) < 40:
            continue
        num = cl["ref"].removeprefix("COS-")
        parent = parent_titles.get(num.split(".")[0], "")
        heading = f"{short}, Clause {num}" + (f" ({cl['title'].title()})" if cl["title"] else "")
        if parent and not num.endswith(".00"):
            heading += f" under {num.split('.')[0]}.00 {parent.title()}"
        for piece, superseded in _split_superseded(body):
            for part in _split_long(piece):
                page = page_of(body, _MARK.sub("", part), cl["page"])
                part = flatten(part)
                if ascii_ratio(part) < 0.6 or len(part) < 40:
                    continue
                prefix = "[SUPERSEDED - OLD VERSION, not in force] " if superseded else ""
                chunks.append(Chunk(
                    doc_id=doc_id,
                    text=f"{heading}\n{prefix}{part}",
                    locator=f"{short}, Clause {num}, p.{page}",
                    clause_ref=cl["ref"],
                    section=parent.title() if parent else cl["title"].title(),
                    page=page,
                    superseded=superseded,
                ))
    return chunks


def _split_superseded(body: str) -> list[tuple[str, bool]]:
    """Separate superseded OLD VERSION blocks from text in force; drop inline 'Old version: ...' phrases."""
    parts: list[tuple[str, bool]] = []
    rest = _INLINE_OLD.sub(".", body)
    while True:
        m = _OLD.search(rest)
        if not m:
            parts.append((rest, False))
            break
        before, after = rest[: m.start()], rest[m.end():]
        if before.strip():
            parts.append((before, False))
        first = _SUBMARK.match(after)
        first_mark = first.group(1) if first else None
        resume = None
        for r in _RESUME.finditer(after, first.end() if first else 1):
            if r.group(2) and r.group(2) == first_mark:
                continue
            resume = r
            break
        if resume:
            parts.append((after[: resume.start()], True))
            rest = after[resume.start():]
        else:
            parts.append((after, True))
            break
    return [(t, s) for t, s in parts if _MARK.sub("", t).strip()]


# ---------------------------------------------------------------- Tariff order

_TO_HEADER = re.compile(r"^Karnataka Electricity Regulatory Commission\s+Tariff Order 2025\s*$", re.M)
_ANNEX_LINE = re.compile(r"^ANNEXURE\s*-\s*\d+\s+Page\s+(\d+)\s*$", re.M)
_PAGE_LINE = re.compile(r"^(.*?)\s+Page\s+(\d+)\s*$", re.M)
_SCHEDULE = re.compile(r"TARIFF SCHEDULE\s*-?\s*((?:LT|HT)\s*-?\s*\d\s*(?:\([a-z]\))?\s*(?:\([ivx]+\))?(?:\s*/HT)?)")
_NOTE = re.compile(r"^\s*(?:NOTE|Note)\s*:?\s*(\[[^\]]+\])?")


def chunk_tariff_order(doc_id: str, short: str, pages: list[str], schedule_start: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    schedule_pages: list[tuple[int, str]] = []
    for pno, raw in enumerate(pages, start=1):
        txt = _TO_HEADER.sub("", clean(raw))
        if pno >= schedule_start:
            schedule_pages.append((pno, txt))
            continue
        if ascii_ratio(txt) < 0.6:
            continue
        lines = txt.split("\n")
        org = lines[0].strip() if lines else ""
        pm = _PAGE_LINE.search(txt[:400])
        section = pm.group(1).strip() if pm else ""
        for part in _split_long(txt):
            part = flatten(part)
            if ascii_ratio(part) < 0.6 or len(part) < 80:
                continue
            chunks.append(Chunk(
                doc_id=doc_id,
                text=f"{short} ({org}) {section}\n{part}",
                locator=f"{short}, PDF p.{pno}" + (f", {section}" if section else ""),
                clause_ref=f"TO-P{pno}",
                section=section or org,
                page=pno,
            ))
    chunks.extend(_chunk_schedule(doc_id, short, schedule_pages))
    return chunks


def _chunk_schedule(doc_id: str, short: str, pages: list[tuple[int, str]]) -> list[Chunk]:
    """Annexure-9 (Electricity Tariff 2026): general terms, LT billing conditions and each tariff schedule."""
    stream: list[tuple[int, str]] = []
    for pno, txt in pages:
        txt = re.sub(r"^All ESCOMs\s*$", "", txt, flags=re.M)
        txt = _ANNEX_LINE.sub("", txt)
        stream.append((pno, f"<<P{pno}>>"))
        for line in txt.split("\n"):
            stream.append((pno, line))

    blocks: list[dict] = []
    first = stream[0][0] if stream else 0
    cur = {"kind": "intro", "key": "TO-ANNEX9", "title": "Electricity Tariff 2026", "page": first, "lines": []}
    last_page = first
    for pno, line in stream:
        if line.startswith("<<P"):
            last_page = pno
            cur["lines"].append(line)
            continue
        u = line.strip().upper()
        new = None
        if u.startswith("GENERAL TERMS AND CONDITIONS OF TARIFF"):
            new = {"kind": "general", "key": "TO-GT", "title": "General Terms and Conditions of Tariff (HT and LT)"}
        elif u.startswith("CONDITIONS APPLICABLE TO BILLING OF LT INSTALLATIONS"):
            new = {"kind": "ltbilling", "key": "TO-LTB", "title": "Conditions applicable to billing of LT installations"}
        else:
            sm = _SCHEDULE.search(line)
            if sm:
                cat = norm_ref(re.sub(r"\s+", "", sm.group(1)).replace("/HT", ""))
                if cur["kind"] in ("schedule", "note") and cur["key"].startswith(f"TO-{cat}"):
                    cur["lines"].append(line)
                    continue
                new = {"kind": "schedule", "key": f"TO-{cat}", "title": f"Tariff Schedule {cat}"}
            elif cur["kind"] == "schedule" and line.strip().lower().startswith("note"):
                nm = _NOTE.match(line)
                applies = (nm.group(1) if nm and nm.group(1) else f"[Applicable to {cur['title'].removeprefix('Tariff Schedule ')}]").strip("[]")
                new = {"kind": "note", "key": cur["key"] + "-NOTE", "title": f"Note ({applies})", "parent": cur["title"]}
        if new:
            blocks.append(cur)
            new.update({"page": last_page, "lines": [f"<<P{last_page}>>"] + ([line] if new["kind"] in ("schedule", "note") else [])})
            cur = new
        else:
            cur["lines"].append(line)
    blocks.append(cur)

    chunks: list[Chunk] = []
    for b in blocks:
        body = "\n".join(b["lines"]).strip()
        if len(_MARK.sub("", body)) < 40:
            continue
        if b["kind"] in ("general", "ltbilling"):
            for num, para in _numbered_paragraphs(body):
                page = page_of(body, _MARK.sub("", para), b["page"])
                para = flatten(para)
                if len(para) < 20:
                    continue
                chunks.append(Chunk(
                    doc_id=doc_id,
                    text=f"{short}, Annexure-9, {b['title']}, para {num}\n{para}",
                    locator=f"{short}, Annexure-9, {b['title']}, para {num}, PDF p.{page}",
                    clause_ref=f"{b['key']}-{num}",
                    section=b["title"],
                    page=page,
                ))
            continue
        heading = f"{short}, Annexure-9, {b['title']}"
        if b["kind"] == "note":
            heading += f" (notes to {b.get('parent', '')})"
        pieces = _split_schedule(body) if b["kind"] == "schedule" else _split_long(body)
        for part in pieces:
            page = page_of(body, _MARK.sub("", part), b["page"])
            part = flatten(part)
            if ascii_ratio(part) < 0.6 or len(part) < 30:
                continue
            chunks.append(Chunk(
                doc_id=doc_id,
                text=f"{heading}\n{part}",
                locator=f"{short}, Annexure-9, {b['title']}, PDF p.{page}",
                clause_ref=b["key"].replace("-NOTE", ""),
                section=b["title"],
                page=page,
            ))
    return chunks


def _split_schedule(body: str) -> list[str]:
    """Keep a schedule's applicability text separate from its rate table."""
    idx = body.find("\nParticulars")
    if idx == -1:
        return _split_long(body)
    head, table = body[:idx], body[idx:]
    m = re.search(r"\n\s*TARIFF SCHEDULE", head[20:])
    if m:
        head = head[: 20 + m.start()]
    return list(_split_long(head)) + [p for p in _split_long(table) if len(_MARK.sub("", p)) > 60]


def _numbered_paragraphs(body: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^\s*(\d{1,2})\s*\.\s*(?=\S|$)", body)
    out = []
    if _MARK.sub("", parts[0]).strip():
        out.append(("0", parts[0]))
    for i in range(1, len(parts) - 1, 2):
        num, text = parts[i], parts[i + 1]
        if len(_MARK.sub("", text).strip()) < 20:
            continue
        for piece in _split_long(text):
            out.append((num, piece))
    return out
