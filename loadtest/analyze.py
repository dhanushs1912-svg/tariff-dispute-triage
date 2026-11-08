"""Summarise loadtest/results/<runs.csv> per concurrency level against the declared SLO.

    python loadtest/analyze.py loadtest/results/runs_1worker.csv loadtest/results/runs_3workers.csv
"""
import csv
import statistics
import sys

SLO = 60.0


def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    k = max(0, min(len(values) - 1, int(round(q * (len(values) - 1)))))
    return values[k]


def analyze(path):
    rows = list(csv.DictReader(open(path)))
    by_users = {}
    for r in rows:
        by_users.setdefault(int(r["users"]), []).append(r)
    out = [f"### {path}", "", "| concurrent runs | completed | runs/s | p50 s | p95 s | errors | SLO p95 <= 60 s |",
           "|---|---|---|---|---|---|---|"]
    first_fail = None
    for users in sorted(by_users):
        rs = by_users[users]
        ok = [float(r["e2e_ms"]) / 1000 for r in rs if r["ok"] == "1"]
        ts = [float(r["ts"]) for r in rs]
        span = max(ts) - min(ts) if len(ts) > 1 else 0
        rps = len(rs) / span if span else 0
        p95 = pct(ok, 0.95)
        met = p95 is not None and p95 <= SLO and len(ok) == len(rs)
        if not met and first_fail is None:
            first_fail = users
        out.append(f"| {users} | {len(rs)} | {rps:.3f} | {pct(ok, 0.5):.1f} | {p95:.1f} | {len(rs) - len(ok)} | {'met' if met else 'MISSED'} |"
                   if ok else f"| {users} | {len(rs)} | {rps:.3f} | - | - | {len(rs)} | MISSED |")
    out.append("")
    out.append(f"First concurrency level where the target fails: {first_fail if first_fail else 'not reached'}")
    return "\n".join(out)


if __name__ == "__main__":
    print("\n\n".join(analyze(p) for p in sys.argv[1:]))
