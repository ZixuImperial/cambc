#!/usr/bin/env python3
"""gploracle.py (13 Nov, b2396; owner: "tweak how we choose what map type it is"): refit the chooser's map key on b2392's ORACLE table
(per map: every plan's result on both seats v live, same maps), strictly held out.
Input: winners.tsv (map, pick_A, pick_B, then P_A / P_B per plan P incl. p0), map files in --maps; features gplfeat (cache --cache),
gpl_type by mapclass. Per map and plan k: dA_k = k_A - p0_A, dB_k = k_B - p0_B (paired on the same map and seat).
Choosers (leaf rule: the plan with the best mean delta minus 1 SE if > 0, else p0; min --min-n maps per leaf):
  ALWAYS-P0 (0 by definition) | ONE PLAN (best plan everywhere) | SIX TYPES (gpl_type leaves) | TREE d1 / d2 (gplfeat features, quintile cuts)
Held-out scoring, both reported:
  SEAT SPLIT: fit on seat-A deltas, score on seat-B deltas of the same maps (and B -> A; mean of the two)
  MAP FOLDS: 5 folds by map hash, fit on both-seat means of the train maps, score on the test maps' both-seat means
Gain = mean over scored maps of the chosen plan's delta (p0 = 0).
Usage: python3 -I tools/lab/gploracle.py [--winners F] [--maps DIR] [--cache F] [--min-n 30]
"""
import argparse
import glob
import hashlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gplfeat  # noqa: E402


def leaf(maps, key, plans, min_n):
    if len(maps) < min_n:
        return "p0"
    best, bv = "p0", 0.0
    for k in plans:
        v = [m[key][k] for m in maps]
        mu = sum(v) / len(v)
        se = math.sqrt(sum((x - mu) ** 2 for x in v) / max(1, len(v) - 1) / len(v))
        if mu - se > bv:
            best, bv = k, mu - se
    return best


def fit_tree(maps, key, plans, depth, min_n, feats):
    """-> node: ('leaf', plan) | ('split', f, t, l, r); objective = sum over leaves of n x (mean - se)+ of the chosen plan."""
    def score(ms, k):
        if k == "p0" or not ms:
            return 0.0
        v = [m[key][k] for m in ms]
        mu = sum(v) / len(v)
        se = math.sqrt(sum((x - mu) ** 2 for x in v) / max(1, len(v) - 1) / len(v))
        return len(ms) * max(0.0, mu - se)

    def rec(ms, d):
        k = leaf(ms, key, plans, min_n)
        best = (score(ms, k), ("leaf", k))
        if d == 0:
            return best
        for f in feats:
            v = sorted(m["f"][f] for m in ms)
            if len(set(v)) < 2:
                continue
            for q in (0.2, 0.4, 0.6, 0.8):
                t = v[int(len(v) * q)]
                L = [m for m in ms if m["f"][f] <= t]
                R = [m for m in ms if m["f"][f] > t]
                if len(L) < min_n or len(R) < min_n:
                    continue
                oL, nL = rec(L, d - 1)
                oR, nR = rec(R, d - 1)
                if oL + oR > best[0] + 1e-9:
                    best = (oL + oR, ("split", f, t, nL, nR))
        return best
    return rec(maps, depth)[1]


def choose(node, m):
    while node[0] == "split":
        node = node[3] if m["f"][node[1]] <= node[2] else node[4]
    return node[1]


def text(node, ind=""):
    if node[0] == "leaf":
        return [f"{ind}-> {node[1]}"]
    return [f"{ind}if {node[1]} <= {node[2]:.4g}:"] + text(node[3], ind + "    ") + [f"{ind}else:"] + text(node[4], ind + "    ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--winners", default="/data/USER/st/b2392/p3/oracle/winners.tsv")
    ap.add_argument("--maps", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--min-n", type=int, default=30)
    a = ap.parse_args()
    mapdir = a.maps or os.path.join(os.path.dirname(a.winners), "maps")
    # --maps may be a glob of dirs (b2392 or2: m1..m4)
    mpath = {os.path.basename(p)[:-7]: p for d in glob.glob(mapdir) for p in glob.glob(os.path.join(d, "*.map26a"))}
    cache = a.cache or os.path.join("/data/USER/st/b2396", "oracle_" + hashlib.md5(a.winners.encode()).hexdigest()[:8] + "_feat.tsv")
    gplfeat.build_cache(cache, [os.path.join(d, "*.map26a") for d in glob.glob(mapdir)])
    F = {}
    L = open(cache).read().splitlines()
    h = L[0].split("\t")
    for l in L[1:]:
        p = l.split("\t")
        F[p[0]] = {k: float(x) for k, x in zip(h[1:], p[1:])}
    import mapclass
    W = open(a.winners).read().splitlines()
    wh = W[0].split("\t")
    plans = sorted({c[:-2] for c in wh if c.endswith("_A") and c != "pick_A" and c[:-2] != "p0"})
    maps = []
    for l in W[1:]:
        r = dict(zip(wh, l.split("\t")))
        if r["map"] not in F:
            continue
        try:
            t = mapclass.values(mpath[r["map"]], ["gpl_type"])["gpl_type"]
        except Exception:  # noqa: BLE001
            t = None
        f = dict(F[r["map"]])
        f["gpl_type"] = float(t or 0)
        dA = {k: float(r[k + "_A"]) - float(r["p0_A"]) for k in plans}
        dB = {k: float(r[k + "_B"]) - float(r["p0_B"]) for k in plans}
        maps.append(dict(m=r["map"], f=f, A=dA, B=dB, AB={k: (dA[k] + dB[k]) / 2 for k in plans}))
    feats = [n for n in gplfeat.NAMES if n not in gplfeat.EXCLUDE]
    print(f"# gploracle: {len(maps)} maps, plans {plans}, min-n {a.min_n}")
    for k in plans:
        v = [m["AB"][k] for m in maps]
        mu = sum(v) / len(v)
        print(f"  {k}: mean paired delta v p0 {mu:+.4f} +- {1.96 * math.sqrt(sum((x - mu) ** 2 for x in v) / (len(v) - 1) / len(v)):.4f}")
    choosers = {
        "ONE PLAN": lambda ms, key: ("leaf", leaf(ms, key, plans, a.min_n)),
        "SIX TYPES": lambda ms, key: fit_tree(ms, key, plans, 1, 1, []) if False else None,
        "TREE d1": lambda ms, key: fit_tree(ms, key, plans, 1, a.min_n, feats),
        "TREE d2": lambda ms, key: fit_tree(ms, key, plans, 2, a.min_n, feats),
    }

    def six(ms, key):
        tab = {t: leaf([m for m in ms if m["f"]["gpl_type"] == t], key, plans, a.min_n) for t in range(1, 7)}
        return ("types", tab)

    def apply(model, m):
        if model[0] == "types":
            return model[1].get(int(m["f"]["gpl_type"]), "p0")
        return choose(model, m)
    fits = {"ONE PLAN": choosers["ONE PLAN"], "SIX TYPES": six, "TREE d1": choosers["TREE d1"], "TREE d2": choosers["TREE d2"]}
    print("| chooser | SEAT SPLIT (fit A score B, fit B score A) | MAP FOLDS (5) mean +- SE |")
    print("|---|---|---|")
    for nm, fit in fits.items():
        mA = fit(maps, "A")
        mB = fit(maps, "B")
        sAB = sum(m["B"][apply(mA, m)] if apply(mA, m) != "p0" else 0.0 for m in maps) / len(maps)
        sBA = sum(m["A"][apply(mB, m)] if apply(mB, m) != "p0" else 0.0 for m in maps) / len(maps)
        g = []
        for i in range(5):
            tr = [m for m in maps if int(hashlib.md5(("f" + m["m"]).encode()).hexdigest(), 16) % 5 != i]
            te = [m for m in maps if int(hashlib.md5(("f" + m["m"]).encode()).hexdigest(), 16) % 5 == i]
            mod = fit(tr, "AB")
            g.append(sum(m["AB"][apply(mod, m)] if apply(mod, m) != "p0" else 0.0 for m in te) / max(1, len(te)))
        mu = sum(g) / len(g)
        se = math.sqrt(sum((x - mu) ** 2 for x in g) / 4 / 5)
        print(f"| {nm} | {sAB:+.4f} / {sBA:+.4f} (mean {(sAB + sBA) / 2:+.4f}) | {mu:+.4f} +- {se:.4f} ({' '.join('%+.3f' % x for x in g)}) |")
    print("| ALWAYS-P0 | +0 | +0 |")
    for d in (1, 2):
        print(f"\nTREE d{d} on all maps (both-seat means):")
        print("\n".join(text(fit_tree(maps, "AB", plans, d, a.min_n, feats))))
    print("\nSIX TYPES on all maps:", six(maps, "AB")[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
