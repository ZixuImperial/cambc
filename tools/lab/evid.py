#!/usr/bin/env python3
"""evid: prior-evidence scores for the shipcheck queue order (Tool Builder, 10 Nov; owner via Builder: "sort it based on results first";
when slots are scarce, waiting lines start by prior evidence, not arrival time).
  python3 -I tools/lab/evid.py set SLUG Z [--why TEXT]   record a line's evidence as a z score (latest wins), e.g. Step 0 strength, a smoke
                                                          point as (p - .5) * 2 * sqrt(n), a near-miss pooled point the same way
  python3 -I tools/lab/evid.py get NAME|SLUG               the z shipwatch would use (none: no evidence)
  python3 -I tools/lab/evid.py list
armq.py add ... --score Z writes it too. shipwatch's queue sort (after its fixed rules: priority, confirm re-reads first, fix lane before
behaviour) orders by -z; a line with no evidence counts as z 0 on the fix lane and goes LAST on the other lanes.
Lookup: a bot nova_bNNNN_SLUG matches SLUG, then SLUG without a re-read suffix (r, r2, i, f, s, t, x ...), then the longest recorded slug
that starts SLUG's stem. File: /data/zw4424/st/bq/evidence.tsv (slug, z, UTC, why)."""
import os
import re
import sys
import time

F = "/data/zw4424/st/bq/evidence.tsv"


def load():
    d = {}
    try:
        for ln in open(F):
            p = ln.rstrip("\n").split("\t")
            if len(p) >= 2:
                try:
                    d[p[0]] = float(p[1])
                except ValueError:
                    pass
    except OSError:
        pass
    return d


def slug_of(name):
    m = re.match(r"nova_b\d+_(.+)$", name)
    return m.group(1) if m else name


def get(name, d=None):
    d = load() if d is None else d
    s = slug_of(name)
    if s in d:
        return d[s]
    t = re.sub(r"(r\d*|i|f|s|t|x)+$", "", s)
    if t in d:
        return d[t]
    c = [k for k in d if len(k) >= 3 and (s.startswith(k) or t.startswith(k))]
    return d[max(c, key=len)] if c else None


def put(slug, z, why=""):
    with open(F, "a") as f:
        f.write(f"{slug}\t{float(z):.3f}\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{why[:160]}\n")


def main():
    a = sys.argv[1:]
    if a[:1] == ["set"] and len(a) >= 3:
        put(a[1], a[2], a[a.index("--why") + 1] if "--why" in a else "")
        print(f"evid: {a[1]} z {float(a[2]):.3f}")
    elif a[:1] == ["get"] and len(a) == 2:
        print(get(a[1]))
    elif a[:1] == ["list"]:
        for k, v in sorted(load().items(), key=lambda kv: -kv[1]):
            print(f"{v:7.3f}  {k}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
