#!/usr/bin/env python3
"""gplmix.py (13 Nov, b2396; owner: "beat ourselves more too ... we lose to people worse than us solely because of the wrong strategy"):
the per-map plan chooser on b2392's OPPONENT-MIX oracle (or2/mix_rows.tsv: map, mtype, opp, plan, win_A, win_B; opp in mirror (live) /
sbg / fish / mite / aggro). Per map, plan k, opponent o: d_ko = mean over seats of (k - p0) v o (paired, same map, seat, opponent).
TARGET = mean of d_ko over the opponents present for that map (equal weight). A switch must not lose to ourselves or aggro: the
per-opponent gains of every chooser are printed next to the mean.
Reports: (1) per plan x opponent mean delta; (2) seat repeatability per opponent (pick the best plan on seat A v that opponent, score it
on seat B, and B->A; ties to p0) = the cross-seat ceiling of per-map choosing v that opponent; (3) choosers with empirical-Bayes leaves
(p0 default), depth 0/1/2 on map features, 5-fold CV by map: mean-mix gain +- SE (z) and per-opponent gains of the same choices.
Usage: python3 -I tools/lab/gplmix.py [--rows F] [--cache F] [--min-n 40] [--n0 auto]
"""
import argparse
import collections
import hashlib
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gplfeat  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="/data/zw4424/st/b2392/p3/or2/mix_rows.tsv")
    ap.add_argument("--cache", default="/data/zw4424/st/b2396/or2_feat.tsv")
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--n0", default="auto")
    a = ap.parse_args()
    F = {}
    L = open(a.cache).read().splitlines()
    for l in L[1:]:
        p = l.split("\t")
        F[p[0]] = [float(x) for x in p[1:]]
    W = open(a.rows).read().splitlines()
    wh = W[0].split("\t")
    cell = collections.defaultdict(dict)  # (map, opp) -> {plan: (wA, wB)}
    for l in W[1:]:
        r = dict(zip(wh, l.split("\t")))
        try:
            cell[(r["map"], r["opp"])][r["plan"]] = (float(r["win_A"]), float(r["win_B"]))
        except (ValueError, KeyError):
            continue
    opps = sorted({o for _, o in cell})
    plans = sorted({p for d in cell.values() for p in d if p not in ("p0", "0")}, key=lambda x: (len(x), x))
    p0 = "p0" if any("p0" in d for d in cell.values()) else "0"
    # partial tables (legs still landing): keep the plans present for every opponent somewhere, then the opponents with >= 300 maps
    # complete for those plans, then the maps complete for all kept opponents
    plans = [k for k in plans if all(any(k in cell[(m, o)] for m, oo in cell if oo == o) for o in opps)]
    comp = {o: {m for m, oo in cell if oo == o and m in F and p0 in cell[(m, o)] and all(k in cell[(m, o)] for k in plans)} for o in opps}
    opps = [o for o in opps if len(comp[o]) >= 300]
    maps = sorted(set.intersection(*[comp[o] for o in opps])) if opps else []
    print("complete maps per opponent:", {o: len(v) for o, v in comp.items()})
    n, P, O = len(maps), len(plans), len(opps)
    print(f"# gplmix: {n} complete maps (all {O} opponents x {P + 1} plans), opponents {opps}, plans {plans}")
    if n < 100:
        return 1
    dA = np.zeros((n, O, P))
    dB = np.zeros((n, O, P))
    for i, m in enumerate(maps):
        for j, o in enumerate(opps):
            b = cell[(m, o)][p0]
            for k, pl in enumerate(plans):
                w = cell[(m, o)][pl]
                dA[i, j, k], dB[i, j, k] = w[0] - b[0], w[1] - b[1]
    D = (dA + dB) / 2          # per opponent
    T = D.mean(axis=1)          # target: mean over opponents
    print("\n(1) mean delta v p0 per plan x opponent (paired both seats; +-1.96 SE)")
    print("| plan | " + " | ".join(opps) + " | MIX |")
    print("|---|" + "---|" * (O + 1))
    for k, pl in enumerate(plans):
        cells = [f"{D[:, j, k].mean():+.3f}+-{1.96 * D[:, j, k].std(ddof=1) / math.sqrt(n):.3f}" for j in range(O)]
        print(f"| {pl} | " + " | ".join(cells) + f" | {T[:, k].mean():+.3f}+-{1.96 * T[:, k].std(ddof=1) / math.sqrt(n):.3f} |")
    print("\n(2) seat repeatability per opponent: best plan on seat A (ties -> p0) scored on seat B, and B->A (cross-seat ceiling)")
    for j, o in enumerate(opps):
        def cross(X, Y):
            best = X[:, j, :].argmax(axis=1)
            bv = X[np.arange(n), j, best]
            return np.where(bv > 0, Y[np.arange(n), j, best], 0.0)
        c = np.concatenate([cross(dA, dB), cross(dB, dA)])
        # correlation of seat-A and seat-B deltas over maps x plans
        r = np.corrcoef(dA[:, j, :].ravel(), dB[:, j, :].ravel())[0, 1]
        print(f"  {o:8s}: cross-seat ceiling {c.mean():+.4f} +- {1.96 * c.std(ddof=1) / math.sqrt(len(c)):.4f}; seat A~B corr of deltas {r:+.3f}")
    keep = [i for i, nm in enumerate(gplfeat.NAMES) if nm not in gplfeat.EXCLUDE]
    X = np.array([F[m] for m in maps])[:, keep]
    names = [gplfeat.NAMES[i] for i in keep]
    fold = np.array([int(hashlib.md5(("f" + m).encode()).hexdigest(), 16) % 5 for m in maps])
    s2 = float(np.mean(np.var(T, axis=0, ddof=1)))
    n0 = float(a.n0) if a.n0 != "auto" else max(50.0, s2 / 0.002)

    def leaf(idx):
        if idx.sum() < a.min_n:
            return -1, 0.0
        mu = T[idx].mean(axis=0)
        k = int(np.argmax(mu))
        sh = mu[k] * idx.sum() / (idx.sum() + n0)
        return (k, float(sh)) if sh > 0 else (-1, 0.0)

    def fit(idx, depth):
        k, sh = leaf(idx)
        best = (idx.sum() * sh, ("leaf", k))
        if depth == 0:
            return best
        for j in range(X.shape[1]):
            col = X[idx, j]
            if len(np.unique(col)) < 2:
                continue
            for t in np.unique(np.quantile(col, [0.2, 0.4, 0.6, 0.8])):
                Lm, Rm = idx & (X[:, j] <= t), idx & (X[:, j] > t)
                if Lm.sum() < a.min_n or Rm.sum() < a.min_n:
                    continue
                oL, nL = fit(Lm, depth - 1)
                oR, nR = fit(Rm, depth - 1)
                if oL + oR > best[0] + 1e-9:
                    best = (oL + oR, ("split", j, float(t), nL, nR))
        return best

    def choose(node):
        out = np.full(n, -1)
        def rec(nd, m):
            if nd[0] == "leaf":
                out[m] = nd[1]
                return
            _, j, t, l, r_ = nd
            rec(l, m & (X[:, j] <= t))
            rec(r_, m & (X[:, j] > t))
        rec(node, np.ones(n, dtype=bool))
        return out

    def text(node, ind=""):
        if node[0] == "leaf":
            return [f"{ind}-> {plans[node[1]] if node[1] >= 0 else 'p0'}"]
        _, j, t, l, r_ = node
        return [f"{ind}if {names[j]} <= {t:.4g}:"] + text(l, ind + "    ") + [f"{ind}else:"] + text(r_, ind + "    ")
    print(f"\n(3) 'keep p0 unless' choosers on the MIX target (EB n0 {n0:.0f}, min {a.min_n} maps/leaf), 5-fold CV by map")
    print("| depth | MIX CV gain +- SE (z) | " + " | ".join(f"{o} (same choices)" for o in opps) + " |")
    print("|---|---|" + "---|" * O)
    res = {}
    for depth in (0, 1, 2):
        g, go = [], np.zeros((5, O))
        for i in range(5):
            tr, te = fold != i, fold == i
            ch = choose(fit(tr, depth)[1])
            sel = np.maximum(ch, 0)
            gm = np.where(ch >= 0, T[np.arange(n), sel], 0.0)
            g.append(float(gm[te].mean()))
            for j in range(O):
                go[i, j] = float(np.where(ch >= 0, D[np.arange(n), j, sel], 0.0)[te].mean())
        mu, se = float(np.mean(g)), float(np.std(g, ddof=1) / math.sqrt(5))
        res[depth] = (mu, se)
        print(f"| {depth} | {mu:+.4f} +- {se:.4f} (z {mu / se if se else 0:.2f}) | " + " | ".join(f"{go[:, j].mean():+.4f}" for j in range(O)) + " |")
    best = max(res, key=lambda d: res[d][0] / (res[d][1] or 1))
    mu, se = res[best]
    print(f"\nBest: depth {best} CV {mu:+.4f} +- {se:.4f} (z {mu / se if se else 0:.2f}) -> {'SHIP-RELEVANT (z >= 2): gpt + same-map check' if se and mu / se >= 2 else 'not z >= 2'}")
    print("\n".join(text(fit(np.ones(n, dtype=bool), best)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
