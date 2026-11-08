import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

OUT = sys.argv[1]
K = colors.black

body = ParagraphStyle("b", fontName="Helvetica", fontSize=8.8, leading=11, spaceAfter=2)
small = ParagraphStyle("s", parent=body, fontSize=8.3, leading=10, spaceAfter=0)
bullet = ParagraphStyle("li", parent=body, leftIndent=10, bulletIndent=2, spaceAfter=1)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13.5, leading=16, alignment=1)
sub = ParagraphStyle("sub", parent=body, alignment=1)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10, leading=12, spaceBefore=5, spaceAfter=2, keepWithNext=1)


def P(t, s=body):
    return Paragraph(t, s)


def B(t):
    return Paragraph(t, bullet, bulletText="•")


def table(rows, widths, header=True):
    data = [[P(f"<b>{c}</b>" if header and i == 0 else c, small) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, K),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return t


def box_note(t, width):
    tb = Table([[P(t)]], colWidths=[width])
    tb.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, K),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tb


def arrow(d, x1, y1, x2, y2):
    d.add(Line(x1, y1, x2, y2, strokeColor=K, strokeWidth=0.8))
    if x1 == x2:
        s = 1 if y2 > y1 else -1
        d.add(Polygon([x2, y2, x2 - 2.5, y2 - 5 * s, x2 + 2.5, y2 - 5 * s], fillColor=K, strokeColor=K))
    else:
        s = 1 if x2 > x1 else -1
        d.add(Polygon([x2, y2, x2 - 5 * s, y2 - 2.5, x2 - 5 * s, y2 + 2.5], fillColor=K, strokeColor=K))


def box(d, x, y, w, h, lines, bold=False, size=7.2, dash=None):
    d.add(Rect(x, y, w, h, strokeColor=K, fillColor=None, strokeWidth=0.8, strokeDashArray=dash))
    font = "Helvetica-Bold" if bold else "Helvetica"
    step = size + 1.5
    top = y + h / 2 + (len(lines) - 1) * step / 2 - size / 3
    for i, ln in enumerate(lines):
        d.add(String(x + w / 2, top - i * step, ln, fontName=font, fontSize=size, textAnchor="middle"))


def diagram():
    d = Drawing(505, 128)
    y, h = 74, 40
    box(d, 0, y, 58, h, ["Web client", "(officer)"])
    box(d, 74, y, 78, h, ["API (FastAPI)", "checks format,", "gives run ID"])
    box(d, 168, y, 50, h, ["Queue", "(Redis)"])
    d.add(Rect(234, y - 6, 196, h + 18, strokeColor=K, fillColor=None, strokeWidth=0.8))
    d.add(String(332, y + h + 4, "Agent worker (3 copies)", fontName="Helvetica-Bold", fontSize=7.2, textAnchor="middle"))
    xs = [240, 288, 336, 384]
    for x, name in zip(xs, ["Intake", "Research", "Verifier", "Router"]):
        box(d, x, y + 6, 40, 26, [name], size=6.8)
    arrow(d, 280, y + 19, 288, y + 19)
    arrow(d, 328, y + 23, 336, y + 23)
    arrow(d, 336, y + 15, 328, y + 15)
    arrow(d, 376, y + 19, 384, y + 19)
    box(d, 446, y, 59, h, ["Outcome +", "quoted clauses"])
    arrow(d, 58, y + h / 2, 74, y + h / 2)
    arrow(d, 152, y + h / 2, 168, y + h / 2)
    arrow(d, 218, y + h / 2, 234, y + h / 2)
    arrow(d, 430, y + h / 2, 446, y + h / 2)

    box(d, 74, 8, 78, 30, ["Quarantine", "(bad requests, no AI)"], size=6.8)
    arrow(d, 113, y, 113, 38)
    for x, lines in [(240, ["Chroma", "KERC clauses"]), (305, ["LLM gateway", "(free tier / stub)"]),
                     (370, ["Postgres", "run log"])]:
        box(d, x, 8, 58, 30, lines, size=6.8)
        arrow(d, x + 29, 38, x + 29, y - 6)
    box(d, 446, 8, 59, 30, ["Monitoring", "Grafana, Jaeger"], size=6.8, dash=[2, 2])
    return d


W = A4[0] - 3.2 * cm
s = []
s.append(P("Electricity Bill Dispute Helper &mdash; Project Plan", h1))
s.append(P("Mini Project 11: Electricity Tariff and Billing Dispute Triage Service &middot; UE24AM342AA5 &middot; Evaluation 1", sub))
s.append(P("<b>Team:</b> Dhanush S (PES1UG24AM360) &nbsp;&middot;&nbsp; Vidit Soni (PES1UG24AM318)", sub))
s.append(Spacer(1, 4))
s.append(box_note(
    "<b>In short.</b> A consumer says <i>&ldquo;my electricity bill is wrong&rdquo;</i>. Our service reads the Karnataka "
    "electricity rules (KERC), works out which tariff category the consumer should be in, and tells the grievance officer "
    "what to do next &mdash; quoting the exact clauses. If the rules do not clearly settle it, the system says so and hands "
    "the case to a person instead of guessing.<br/>"
    "<b>Why it is hard.</b> The rule that decides a case is often printed far away from the rule a search finds first. "
    "So we use AI agents that search, ask &ldquo;does anything change this?&rdquo;, search again and check their own answer.<br/>"
    "<b>What it never does.</b> Change or recalculate a bill. The officer always makes the final decision.", W))

s.append(P("1. The problem", h2))
s.append(B("Electricity companies get billing disputes every day. A common cause is the <b>tariff category</b> the consumer "
           "is billed under (domestic, commercial, industrial ...)."))
s.append(B("The category is fixed by KERC's tariff order and depends on <b>what the premises is used for</b>, the "
           "<b>connected load</b>, and sometimes the time of day. A house partly used for business may be re-categorised."))
s.append(B("The officer must find the right category, check whether any change of category was valid, and give a "
           "<b>cited reason</b>, because the consumer can appeal to the Consumer Grievance Redressal Forum."))

s.append(P("2. Worked example: the test case for our demo", h2))
s.append(P("<i>&ldquo;I have a domestic connection. I run a small tailoring shop from one room of the house. Which tariff "
           "category should I be billed under?&rdquo;</i>"))
s.append(table([
    ["A simple search (one lookup)", "Our agent"],
    ["Finds the domestic category (LT-1) definition, because it matches the words in the question, and answers "
     "&ldquo;domestic&rdquo;. It never sees the rule on premises used partly for business, because that rule uses "
     "different words and sits in another part of the order or in the supply code. <b>Confident but possibly wrong.</b>",
     "1. Finds the domestic definition.<br/>2. Asks: <i>is there a rule that changes this?</i> (mixed use, change of use, "
     "load limits)<br/>3. Searches again with new words taken from what it just read, and finds the mixed-use rule.<br/>"
     "4. Checks that both quoted clauses really appear in the text it found.<br/>5. Gives an outcome citing "
     "<b>both</b> clauses, or escalates if together they still do not settle it."],
], [W * 0.42, W * 0.58]))

s.append(P("3. How the system works", h2))
s.append(diagram())
s.append(B("<b>Front door:</b> every request is checked against a published format (fields, ranges, allowed values). "
           "Bad requests are stored in quarantine with the reason, and no AI runs on them."))
s.append(B("<b>Run ID:</b> a case takes about 30 seconds, so the API replies at once with a run ID and the web page "
           "checks back for the result. A queue sits between the API and the workers."))
s.append(B("<b>Four agent roles:</b> <b>Intake</b> works out the dispute type and pulls out the facts (use of premises, "
           "load, billed category). <b>Research</b> searches the documents using tools (search, fetch clause by number, read "
           "the request's fields). <b>Verifier</b> checks every citation against the text actually found and sends the "
           "case back for one more search, or escalates. <b>Router</b> picks the outcome and blocks anything that looks like "
           "a bill change."))
s.append(B("<b>Safety limits:</b> at most 12 steps, 10 tool calls and 90 seconds per case. If a limit is hit, or the "
           "AI provider is down, the case is escalated, never answered half-done."))
s.append(Spacer(1, 2))
s.append(table([
    ["Outcome", "When the system gives it"],
    ["Bill stands (with reason)", "The cited clauses confirm the category the consumer is billed under"],
    ["Revision recommended", "The cited clauses point to a different category"],
    ["Site inspection required", "The answer depends on facts that must be checked on site (actual use, load)"],
    ["Escalate to officer", "Rules are mixed or conflict, the case is outside our documents, or the answer could not be verified"],
], [4.2 * cm, W - 4.2 * cm]))

s.append(P("4. Documents we use (Karnataka, KERC)", h2))
s.append(B("<b>KERC tariff order</b> currently in force for BESCOM &mdash; definitions of each category (LT-1 domestic, "
           "LT-3 commercial, LT-5 industrial) and the notes under them."))
s.append(B("<b>KERC Conditions of Supply</b> (Karnataka's supply code) &mdash; rules on change of use, re-categorisation "
           "and inspection."))
s.append(B("Both are free PDFs. We split them clause by clause and keep the notes under each category as separate pieces, "
           "since that is where mixed-use rules usually sit. Embeddings are computed locally, so indexing costs nothing. "
           "At Evaluation 1 we will show the exact passages the tailoring case depends on."))

s.append(P("5. Tools", h2))
s.append(table([
    ["Need", "Tool", "Need", "Tool"],
    ["Agents", "LangGraph", "API", "FastAPI"],
    ["Document search", "LangChain + Chroma, all-MiniLM-L6-v2", "Queue and cache", "Redis"],
    ["Run log, feedback", "PostgreSQL", "Run everything", "Docker Compose (one command)"],
    ["Monitoring", "Prometheus, Grafana, Jaeger", "Testing", "TruLens (quality), Locust (load)"],
    ["Language model", "Free-tier provider behind our own gateway, switchable by config", "Load-test model",
     "Stub that replies after a fixed delay"],
], [3.0 * cm, W / 2 - 3.0 * cm, 3.0 * cm, W / 2 - 3.0 * cm]))

s.append(P("6. How we will show it works", h2))
s.append(B("<b>Answer quality:</b> 20+ test cases, each with the expected outcome and the clause that supports it "
           "(including the tailoring case). We measure groundedness, context relevance, faithfulness and hallucination rate, "
           "and compare simple search vs our agent, and two prompt versions."))
s.append(B("<b>Speed target (fixed now, before testing):</b> 95% of cases finish within <b>60 seconds</b> with 10 cases "
           "running at once. The officer reads the result while the case file is open, so about a minute is the useful "
           "limit. Load tests use the stub model so we measure our system, not the provider's limits."))
s.append(B("<b>Safety:</b> checks for prompt injection and toxic text, no unverified answer is ever returned, and a "
           "circuit breaker switches to a fallback when the provider fails."))
s.append(B("<b>Traceability:</b> from a run ID we can replay every search, passage, prompt version, step time and cost."))

s.append(P("7. Timeline and roles", h2))
s.append(table([
    ["Week", "Goal"],
    ["1", "Download documents, locate the tailoring-case passages, define request format, set up repo and containers"],
    ["2", "<b>First full working path:</b> request &rarr; one agent &rarr; answer with citations, shown in the web page"],
    ["3", "Research and Verifier agents, the four outcomes, escalation, safety checks"],
    ["4", "Timeouts, retries and circuit breaker; monitoring dashboards; 20+ test cases"],
    ["5", "Prompt comparison, load test and scaling to 3 workers, caching, cost per 100 cases"],
    ["6", "Runbook, incident log, README tested from a clean clone, report, demo practice"],
], [1.3 * cm, W - 1.3 * cm]))
s.append(Spacer(1, 2))
s.append(table([
    ["Member", "Responsible for"],
    ["Dhanush S", "Documents and indexing, the agents and their tools, test cases and quality metrics, safety checks"],
    ["Vidit Soni", "API and request format, Docker setup and model gateway, monitoring, load testing, caching, cost tracking"],
    ["Both", "Web page, runbook and incident log, report, demo"],
], [2.2 * cm, W - 2.2 * cm]))
s.append(Spacer(1, 3))
s.append(P("<b>Main risks:</b> the mixed-use rule may be unclear (then escalation is the correct answer); free-tier rate "
           "limits (handled by caching, per-user limits and the stub); scanned PDF pages (OCR fallback)."))

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.2 * cm,
                        bottomMargin=1.2 * cm, title="Project Plan - Mini Project 11",
                        author="Dhanush S, Vidit Soni")
doc.build(s)
