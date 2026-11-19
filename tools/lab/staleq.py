#!/usr/bin/env python3
"""staleq: Step 0 diag wait and the oldest unfinished reads (Tool Builder, 10 Nov; Coordinator: Step 0 diags at Condor priority 9, under
ship legs, must not starve; "a nightly list of the 10 oldest unfinished Step 0 / pending_reads entries so none rots").
  python3 -I tools/lab/staleq.py wait     pilot queue: per priority and kind, items waiting, median and oldest age (min); ALARM line when
                                          cqbatch --debug items (prio 9) wait median > 45 min or oldest > 120 min
  python3 -I tools/lab/staleq.py oldest   the 10 oldest PENDING lines of bq/pending_reads.txt (by their ISO stamp) and the 10 oldest
                                          prio <= 9 cqbatch runs still queued -> stdout and /data/zw4424/st/bq/staleq_oldest.txt
Unit nova-staleq (timer, daily 06:00Z) writes 'oldest'; healthwatch-style alarm file bq/staleq.alarm while 'wait' alarms."""
import collections
import json
import os
import re
import statistics as S
import sys
import time

Q = "/homes/zw4424/condor-runs/pilotq"
BQ = "/data/zw4424/st/bq"


def items():
    now = time.time()
    for sub in ("queue", "claimed"):
        for n in os.listdir(os.path.join(Q, sub)):
            p = n.split("_", 3)
            try:
                pr, t = 500 - int(p[0]), int(p[1]) / 1000
            except (ValueError, IndexError):
                continue
            yield sub, pr, "diag" if "_stage-" in n else "cq", (now - t) / 60, n


def wait():
    g = collections.defaultdict(list)
    for sub, pr, kind, age, _ in items():
        if sub == "queue":
            g[(pr, kind)].append(age)
    for (pr, kind), v in sorted(g.items(), key=lambda kv: -kv[0][0]):
        print(f"prio {pr:4d} {kind:5s} waiting {len(v):5d}  age med {S.median(v):5.0f} min, oldest {max(v):5.0f} min")
    d = [a for (pr, kind), v in g.items() if kind == "diag" and pr <= 9 for a in v]
    al = os.path.join(BQ, "staleq.alarm")
    if d and (S.median(d) > 45 or max(d) > 120):
        msg = f"Step 0 diags (prio <= 9) starve: {len(d)} waiting, median {S.median(d):.0f} min, oldest {max(d):.0f} min (bar 45 / 120)"
        print("ALARM " + msg)
        open(al, "w").write("ALARM " + msg + "\n")
        promote_small()
    elif os.path.exists(al):
        os.remove(al)


def promote_small(max_items=8):
    """10 Nov (owner: testing must run smoothly): on the alarm, small Step 0 batches (<= max_items queued items at prio 9, key 491) go to
    prio 11 (key 489), still under ship legs (12); big batches stay. Logged to bq/staleq.log."""
    qd = os.path.join(Q, "queue")
    by = collections.defaultdict(list)
    for n in os.listdir(qd):
        if n.startswith("491_") and n.count("_") >= 3:
            by[re.sub(r"_\d+(_g)?$", "", n.split("_", 2)[2])].append(n)
    moved = 0
    for b, ns in by.items():
        if len(ns) > max_items:
            continue
        for n in ns:
            p = os.path.join(qd, n)
            try:
                d = json.load(open(p))
                d["prio"] = 11
                json.dump(d, open(p + ".tmp", "w"))
                os.rename(p + ".tmp", p)
                os.rename(p, os.path.join(qd, "489_" + n[4:]))
                moved += 1
            except (OSError, ValueError):
                pass
    with open(os.path.join(BQ, "staleq.log"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} promoted {moved} items of small Step 0 batches to prio 11\n")
    print(f"promoted {moved} items of small Step 0 batches (<= {max_items} items) to prio 11")


def oldest():
    rows = []
    for ln in open(os.path.join(BQ, "pending_reads.txt"), errors="replace"):
        if ln.startswith("PENDING:"):
            m = re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?Z?", ln)
            rows.append((m.group(0) if m else "9999 (no stamp)", ln.strip()[:220]))
    rows.sort()
    out = [f"staleq {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: 10 oldest PENDING reads of {len(rows)}"] + [f"  {r[1]}" for r in rows[:10]]
    bids = {}
    for sub, pr, kind, age, n in items():
        if kind == "diag" and pr <= 9:
            b = re.sub(r"_\d+(\..*)?$", "", n.split("_", 2)[2])
            bids[b] = max(bids.get(b, 0), age)
    out.append(f"10 oldest queued Step 0 diag batches (prio <= 9) of {len(bids)}:")
    out += [f"  {b}: {a:.0f} min" for b, a in sorted(bids.items(), key=lambda kv: -kv[1])[:10]]
    txt = "\n".join(out) + "\n"
    open(os.path.join(BQ, "staleq_oldest.txt"), "w").write(txt)
    print(txt, end="")


if __name__ == "__main__":
    {"wait": wait, "oldest": oldest}.get((sys.argv[1:] or [""])[0], lambda: sys.exit(__doc__))()
