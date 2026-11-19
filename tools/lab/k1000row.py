#!/usr/bin/env python3
"""k1000row (Coordinator / b1916, 11 Nov): the '1,000-in-hand to finish' play metric per arm from b1916's k1000.py TSVs (game, first round
the team holds >= 1,000 gems tributed + carried (-1 never), finish round, win 0/1). For WON games: median rounds from first-1,000 to the
finish, share over 40, win count, and arm minus base on paired maps (same map and seat) with a bootstrap 90% range. Information only.
usage: python3 -I tools/lab/k1000row.py BASE.tsv ARM.tsv [ARM2.tsv ...]"""
import random
import statistics as st
import sys


def load(p):
    out = {}
    for ln in open(p):
        x = ln.split()
        if len(x) >= 4:
            out[x[0]] = (int(x[1]), int(x[2]), int(x[3]))
    return out


def summ(d):
    g = [f - k for k, f, w in d.values() if w == 1 and k >= 0]
    return g


def row(name, d, base):
    g = summ(d)
    s = f"{name:10s} wins {sum(w for _, _, w in d.values()):3d}/{len(d)}  won+1000 n {len(g):3d}  median gap {st.median(g) if g else float('nan'):5.1f}  >40 {sum(x > 40 for x in g) / max(1, len(g)):.0%}"
    if base is not None:
        common = [m for m in d if m in base and d[m][2] == 1 and base[m][2] == 1 and d[m][0] >= 0 and base[m][0] >= 0]
        diffs = [(d[m][1] - d[m][0]) - (base[m][1] - base[m][0]) for m in common]
        if len(diffs) >= 5:
            rng = random.Random(1)
            bs = sorted(st.median(rng.choices(diffs, k=len(diffs))) for _ in range(2000))
            s += f"  | v base, paired won-both maps n {len(diffs)}: median gap diff {st.median(diffs):+.1f} [90% {bs[100]:+.1f}, {bs[1899]:+.1f}]"
    return s


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    base = load(sys.argv[1])
    print(row(sys.argv[1].split("/")[-1].replace(".tsv", ""), base, None))
    for p in sys.argv[2:]:
        print(row(p.split("/")[-1].replace(".tsv", ""), load(p), base))
