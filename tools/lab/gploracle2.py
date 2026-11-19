#!/usr/bin/env python3
"""gploracle2.py (13 Nov, b2396; owner: "improve classifying, our draft also isn't that good at choosing"): the 'keep p0 unless' rule on
b2392's oracle table, with empirical-Bayes leaves, map features +/- OUR lineup features, strictly held out.
Per map and alternative k: d_k = mean over seats of (k_seat - p0_seat) (paired, same map). Leaf rule: for each k, shrunk edge =
mean_k x n / (n + n0) (n0 = within-map variance / between-leaf variance of plan means, estimated on the training maps); the leaf
switches to the k with the largest shrunk edge if it is > 0 (else p0). Trees: depth 0 (one plan), 1, 2 over quintile cuts, objective =
sum over leaves of n x shrunk edge (> 0). Scored by 5-fold MAP CV (fit on train maps, score the chosen plan's d_k on test maps; p0 =
0) and SEAT SPLIT (fit on seat-A deltas, score seat-B deltas of the same maps, and B->A). Feature sets: MAP (gplfeat) and MAP+LINEUP
(extra numeric columns in winners.tsv that are not plan/seat/pick/gplfeat columns: b2392 logs our draft there; categorical text is
one-hot coded). Also prints Table-B style 'best alternative cross-seat edge' per leaf for reference.
Usage: python3 -I tools/lab/gploracle2.py [--winners F] [--maps GLOB] [--cache F] [--min-n 40] [--n0 auto]
"""
import argparse
import glob
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
    ap.add_argument("--winners", default="/data/USER/st/b2392/p3/or2/winners.tsv")
    ap.add_argument("--maps", default="/data/USER/st/b2392/p3/or2/m*")
    ap.add_argument("--cache", default="/data/USER/st/b2396/or2_feat.tsv")
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--n0", default="auto")
    a = ap.parse_args()
    gplfeat.build_cache(a.cache, [os.path.join(d, "*.map26a") for d in glob.glob(a.maps)])
    F = {}
    L = open(a.cache).read().splitlines()
    h = L[0].split("\t")
    for l in L[1:]:
        p = l.split("\t")
        F[p[0]] = [float(x) for x in p[1:]]
    W = open(a.winners).read().splitlines()
    wh = W[0].split("\t")
    import re
    plans = sorted({c[:-2] for c in wh if re.fullmatch(r"p\d+_A", c) and c != "p0_A" and c[:-2] + "_B" in wh})
    skip = {"map", "pick_A", "pick_B", "mtype"} | {p + s for p in plans + ["p0"] for s in ("_A", "_B")} | set(gplfeat.NAMES)
    extra = [c for c in wh if c not in skip]
    rows = [dict(zip(wh, l.split("\t"))) for l in W[1:]]
    rows = [r for r in rows if r["map"] in F and all(r.get(k + s, "") not in ("", None) for k in plans + ["p0"] for s in ("_A", "_B"))]
    # lineup columns: numeric as is; text one-hot
    lcols, lnames = [], []
    for c in extra:
        vals = [r.get(c, "") for r in rows]
        try:
            [float(v) for v in vals if v != ""]
            lcols.append(("num", c, None))
            lnames.append(c)
        except ValueError:
            for v in sorted({v for v in vals if v}):
                lcols.append(("cat", c, v))
                lnames.append(f"{c}={v}")
    seatcols = sorted({c[:-2] for c in wh if c.endswith("_A") and c[:-2] + "_B" in wh and c[:-2] not in plans + ["p0", "pick"]})
    if seatcols:
        # b2392 13 Nov: OUR lineup per seat (lineup_X = our type names joined by '-', carry_X, healer_X, dashers_X, vendetta_X,
        # team_size_X): units become map-seats; lineup -> champion presence one-hot + carry one-hot + numeric columns
        champs = sorted({c for r in rows for s_ in "AB" for c in r.get("lineup_" + s_, "").split("-") if c})
        carries = sorted({r.get("carry_" + s_, "") or "none" for r in rows for s_ in "AB"})
        nums = [c for c in seatcols if c not in ("lineup", "carry")]
        lnames = [f"has_{c}" for c in champs] + [f"carry={c}" for c in carries] + nums
        units = []
        for r in rows:
            for s_ in "AB":
                lu = set(r.get("lineup_" + s_, "").split("-"))
                cv = r.get("carry_" + s_, "") or "none"
                lv = [float(c in lu) for c in champs] + [float(cv == c) for c in carries] + [float(r.get(f"{c}_{s_}") or 0) for c in nums]
                units.append((r, s_, lv))
        print(f"# gploracle2 SEAT UNITS: {len(units)} map-seats from {len(rows)} maps; lineup features {len(lnames)}")
        XMs = np.array([F[r["map"]] for r, _, _ in units])
        keep = [i for i, nm in enumerate(gplfeat.NAMES) if nm not in gplfeat.EXCLUDE]
        XMs, mnames = XMs[:, keep], [gplfeat.NAMES[i] for i in keep]
        XLs = np.array([lv for _, _, lv in units])
        D = np.array([[float(r[f"{k}_{s_}"]) - float(r[f"p0_{s_}"]) for k in plans] for r, s_, _ in units])
        fold = np.array([int(hashlib.md5(("f" + r["map"]).encode()).hexdigest(), 16) % 5 for r, _, _ in units])
        for k_, nm in enumerate(plans):
            print(f"  {nm}: mean delta v p0 {D[:, k_].mean():+.4f}")
        nU = len(units)

        def leafU(idx, n0):
            if idx.sum() < a.min_n:
                return -1, 0.0
            m = D[idx].mean(axis=0)
            k = int(np.argmax(m))
            sh = m[k] * idx.sum() / (idx.sum() + n0)
            return (k, float(sh)) if sh > 0 else (-1, 0.0)

        def fitU(X, idx, depth, n0):
            k, sh = leafU(idx, n0)
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
                    oL, nL = fitU(X, Lm, depth - 1, n0)
                    oR, nR = fitU(X, Rm, depth - 1, n0)
                    if oL + oR > best[0] + 1e-9:
                        best = (oL + oR, ("split", j, float(t), nL, nR))
            return best

        def chooseU(node, X):
            out = np.full(X.shape[0], -1)
            def rec(nd, m):
                if nd[0] == "leaf":
                    out[m] = nd[1]
                    return
                _, j, t, l, r_ = nd
                rec(l, m & (X[:, j] <= t))
                rec(r_, m & (X[:, j] > t))
            rec(node, np.ones(X.shape[0], dtype=bool))
            return out

        def textU(node, names, ind=""):
            if node[0] == "leaf":
                return [f"{ind}-> {plans[node[1]] if node[1] >= 0 else 'p0'}"]
            _, j, t, l, r_ = node
            return [f"{ind}if {names[j]} <= {t:.4g}:"] + textU(l, names, ind + "    ") + [f"{ind}else:"] + textU(r_, names, ind + "    ")
        s2 = float(np.mean(np.var(D, axis=0, ddof=1)))
        n0 = a.n0 if a.n0 != "auto" else None
        n0 = float(n0) if n0 else max(50.0, s2 / 0.002)  # tau ~ .045 between-leaf SD of a plan's edge (prior); n0 ~ s2/tau^2
        sets = {"MAP": (XMs, mnames), "MAP+LINEUP": (np.hstack([XMs, XLs]), mnames + lnames), "LINEUP only": (XLs, lnames)}
        print(f"n0 (shrinkage) = {n0:.0f}")
        print("| features | depth | MAP FOLDS CV gain +- SE (z) |")
        print("|---|---|---|")
        res = {}
        for sname, (X, names) in sets.items():
            for depth in (0, 1, 2):
                g = []
                for i in range(5):
                    tr, te = fold != i, fold == i
                    node = fitU(X, tr, depth, n0)[1]
                    ch = chooseU(node, X)
                    gg = np.where(ch >= 0, D[np.arange(nU), np.maximum(ch, 0)], 0.0)
                    g.append(float(gg[te].mean()))
                mu, se = float(np.mean(g)), float(np.std(g, ddof=1) / math.sqrt(5))
                res[(sname, depth)] = (mu, se)
                print(f"| {sname} | {depth} | {mu:+.4f} +- {se:.4f} (z {mu / se if se else 0:.2f}) | folds {' '.join('%+.3f' % x for x in g)}")
        best = max(res, key=lambda k: res[k][0] / (res[k][1] or 1))
        X, names = sets[best[0]]
        mu, se = res[best]
        print(f"\nBest by z: {best[0]} depth {best[1]}: CV {mu:+.4f} +- {se:.4f} (z {mu / se if se else 0:.2f}) -> "
              f"{'SHIP-RELEVANT (z >= 2)' if se and mu / se >= 2 else 'not z >= 2'}")
        print("\n".join(textU(fitU(X, np.ones(nU, dtype=bool), best[1], n0)[1], names)))
        return 0
    n = len(rows)
    print(f"# gploracle2: {n} complete maps, alternatives {plans}, map features {len(gplfeat.NAMES)}, lineup columns {lnames or 'none yet'}")
    if n < 100 or not plans:
        return 1
    XM = np.array([F[r["map"]] for r in rows])
    keep = [i for i, nm in enumerate(gplfeat.NAMES) if nm not in gplfeat.EXCLUDE]
    XM, mnames = XM[:, keep], [gplfeat.NAMES[i] for i in keep]
    XL = np.array([[(float(r.get(c) or 0) if kind == "num" else float(r.get(c) == v)) for kind, c, v in lcols] for r in rows]) if lcols else np.zeros((n, 0))
    dA = np.array([[float(r[k + "_A"]) - float(r["p0_A"]) for k in plans] for r in rows])
    dB = np.array([[float(r[k + "_B"]) - float(r["p0_B"]) for k in plans] for r in rows])
    dAB = (dA + dB) / 2
    fold = np.array([int(hashlib.md5(("f" + r["map"]).encode()).hexdigest(), 16) % 5 for r in rows])

    def n0_of(D, mask=None):
        Xs = XM if mask is None else XM[mask]
        if a.n0 != "auto":
            return float(a.n0)
        s2 = float(np.mean(np.var(D, axis=0, ddof=1)))  # within-map variance of a plan delta
        # between-'leaf' variance proxy: variance of plan means over quintiles of the first few features
        means = []
        for j in range(min(Xs.shape[1], 10)):
            q = np.quantile(Xs[:, j], [0.2, 0.4, 0.6, 0.8])
            b = np.searchsorted(q, Xs[:, j])
            for bb in range(5):
                m = b == bb
                if m.sum() >= 30:
                    means.extend(D[m].mean(axis=0) - D.mean(axis=0))
        tau2 = max(float(np.var(means)) - s2 / max(1, n / 5), 1e-5)
        return s2 / tau2

    def leaf(D, idx, n0):
        if idx.sum() < a.min_n:
            return -1, 0.0
        m = D[idx].mean(axis=0)
        k = int(np.argmax(m))
        nn = idx.sum()
        sh = m[k] * nn / (nn + n0)
        return (k, float(sh)) if sh > 0 else (-1, 0.0)

    def fit(X, D, idx, depth, n0):
        k, sh = leaf(D, idx, n0)
        best = (idx.sum() * sh, ("leaf", k))
        if depth == 0:
            return best
        for j in range(X.shape[1]):
            col = X[idx, j]
            if len(np.unique(col)) < 2:
                continue
            for t in np.unique(np.quantile(col, [0.2, 0.4, 0.6, 0.8])):
                Lm = idx & (X[:, j] <= t)
                Rm = idx & (X[:, j] > t)
                if Lm.sum() < a.min_n or Rm.sum() < a.min_n:
                    continue
                oL, nL = fit(X, D, Lm, depth - 1, n0)
                oR, nR = fit(X, D, Rm, depth - 1, n0)
                if oL + oR > best[0] + 1e-9:
                    best = (oL + oR, ("split", j, float(t), nL, nR))
        return best

    def choose(node, X):
        out = np.full(X.shape[0], -1)
        def rec(nd, m):
            if nd[0] == "leaf":
                out[m] = nd[1]
                return
            _, j, t, l, r = nd
            rec(l, m & (X[:, j] <= t))
            rec(r, m & (X[:, j] > t))
        rec(node, np.ones(X.shape[0], dtype=bool))
        return out

    def gain(ch, D, m):
        g = np.where(ch >= 0, D[np.arange(len(ch)), np.maximum(ch, 0)], 0.0)
        return float(g[m].mean())

    def text(node, names, ind=""):
        if node[0] == "leaf":
            return [f"{ind}-> {plans[node[1]] if node[1] >= 0 else 'p0'}"]
        _, j, t, l, r = node
        return [f"{ind}if {names[j]} <= {t:.4g}:"] + text(l, names, ind + "    ") + [f"{ind}else:"] + text(r, names, ind + "    ")

    for k_, nm in enumerate(plans):
        se = dAB[:, k_].std(ddof=1) / math.sqrt(n)
        print(f"  {nm}: mean paired delta {dAB[:, k_].mean():+.4f} +- {1.96 * se:.4f}")
    sets = {"MAP": (XM, mnames)}
    if XL.shape[1]:
        sets["MAP+LINEUP"] = (np.hstack([XM, XL]), mnames + lnames)
        sets["LINEUP only"] = (XL, lnames)
    print("| features | depth | MAP FOLDS CV gain +- SE (z) | SEAT SPLIT A->B / B->A |")
    print("|---|---|---|---|")
    results = {}
    for sname, (X, names) in sets.items():
        for depth in (0, 1, 2):
            g = []
            for i in range(5):
                tr, te = fold != i, fold == i
                n0 = n0_of(dAB[tr], tr)
                _, node = fit(X, dAB, tr, depth, n0)
                g.append(gain(choose(node, X), dAB, te))
            mu, se = float(np.mean(g)), float(np.std(g, ddof=1) / math.sqrt(5))
            all_ = np.ones(n, dtype=bool)
            nA = fit(X, dA, all_, depth, n0_of(dA))[1]
            nB = fit(X, dB, all_, depth, n0_of(dB))[1]
            sAB, sBA = gain(choose(nA, X), dB, all_), gain(choose(nB, X), dA, all_)
            results[(sname, depth)] = (mu, se)
            print(f"| {sname} | {depth} | {mu:+.4f} +- {se:.4f} (z {mu / se if se > 0 else 0:.2f}) | {sAB:+.4f} / {sBA:+.4f} |")
    best = max(results, key=lambda k: results[k][0] / (results[k][1] or 1))
    X, names = sets[best[0]]
    node = fit(X, dAB, np.ones(n, dtype=bool), best[1], n0_of(dAB))[1]
    mu, se = results[best]
    print(f"\nBest by z: {best[0]} depth {best[1]}: CV {mu:+.4f} +- {se:.4f} (z {mu / se if se else 0:.2f}) -> "
          f"{'SHIP-RELEVANT (z >= 2): send as gpt + same-map check' if se and mu / se >= 2 else 'not z >= 2'}")
    print("\n".join(text(node, names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
