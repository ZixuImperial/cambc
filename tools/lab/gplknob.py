#!/usr/bin/env python3
"""gplknob.py (13 Nov, b2396; owner A25 via Builder): continuous per-game plan knobs (switch points drawn over a wide range: gold amount,
power ratio, push trigger ...). For one plan P and one numeric knob K it fits the best K two ways and cross-validates each by map
(5 folds) against the within-type plan-0 null (wins shifted per wave as gpltable.py):
 A BINNED per leaf: K cut into quintiles (of plan-P games); leaves = the 6 gpl types (or --leaf FEATURE:THR for a feature split);
   per leaf the bin with the best mean - leaf plan-0 mean (needs >= --min-n games); test = test games of P in the chosen bin.
 B FUNCTION of draft features: OLS on plan-P games  win ~ 1 + x + x^2 + x*f + f  (x = K standardised, f = one feature from --feats,
   standardised); K*(f) = argmax of the fitted curve on the observed K range; test = test games of P whose K is within h (= range/5)
   of K*(their f). Each feature in --feats is tried; the best by train fit is used per fold.
Gain = share of maps in the evaluated set x (mean win of matched test games - plan-0 mean of their types); 'if plan P were played with
the tuned K on every map', so compare with P's untuned gain (also printed). Features: gplfeat.py (cache shared with gplfit.py).
Usage: python3 -I tools/lab/gplknob.py --plan P --knob K [--feats own_gold,c,cen_gem,...] [--in GLOB] [--min-n 20]
"""
import argparse
import collections
import hashlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gplfeat  # noqa: E402
import gpltable  # noqa: E402
from gpltable import load, fnum, TYPES  # noqa: E402


def fold(m, k):
    return int(hashlib.md5(("f" + m).encode()).hexdigest(), 16) % k


def solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return None
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def ols(X, y, ridge=1e-3):
    k = len(X[0])
    A = [[sum(x[i] * x[j] for x in X) + (ridge if i == j else 0) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)]
    return solve(A, b)


def p0_by_type(games):
    d = collections.defaultdict(list)
    for g in games:
        if g["plan"] == 0:
            d[g["t"]].append(g["w"])
    return {t: sum(v) / len(v) for t, v in d.items() if v}


def gain_of(matched, games, nmaps):
    m0 = p0_by_type(games)
    by = collections.defaultdict(list)
    for g in matched:
        if g["t"] in m0:
            by[g["t"]].append(g)
    tot = 0.0
    for t, gs in by.items():
        maps_t = len({g["map"] for g in games if g["t"] == t})
        tot += maps_t / nmaps * (sum(g["w"] for g in gs) / len(gs) - m0[t])
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=int, required=True)
    ap.add_argument("--knob", required=True)
    ap.add_argument("--feats", default="own_gold,own_gem,c,cen_gem,cen_gold,con20,h,walk_c")
    ap.add_argument("--in", dest="inp", default="/data/zw4424/st/b2392/p3/chunk_*.tsv")
    ap.add_argument("--mapglob", default="/data/zw4424/st/b2392/p3/maps_c*/")
    ap.add_argument("--cache", default="/data/zw4424/st/b2396/feat_cache.tsv")
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--where", default="", help="COL=VAL[,COL=VAL]: keep only plan-P games matching (e.g. trig=1 for tval's meaning)")
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()

    where = [tuple(x.split("=", 1)) for x in a.where.split(",") if "=" in x]
    _, rows, _ = load(a.inp)
    gpltable.wave_adjust(rows)
    cache = {}
    if os.path.exists(a.cache):
        with open(a.cache) as fh:
            hdr = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) == len(hdr):
                    cache[p[0]] = {h: float(x) for h, x in zip(hdr[1:], p[1:])}
    import glob
    paths = {f[:-7]: os.path.join(d, f) for d in glob.glob(a.mapglob) for f in os.listdir(d) if f.endswith(".map26a")}
    games = []
    for r in rows:
        pl, w, t = fnum(r.get("plan")), r.get("_wadj"), fnum(r.get("mtype"))
        if pl is None or pl < 0 or w is None or t is None:
            continue
        m = r["map"]
        if m not in cache and m in paths:
            try:
                cache[m] = gplfeat.feats(paths[m])
            except Exception:  # noqa: BLE001
                cache[m] = None
        f = cache.get(m)
        if f is None:
            continue
        x = fnum(r.get(a.knob))
        if int(pl) == a.plan and any(str(r.get(c, "")).strip() != v for c, v in where):
            x = None  # other trigger modes of this plan: not part of this fit (also kept out of the plan-0 null: they are not plan 0)
        games.append(dict(map=m, plan=int(pl), w=w, t=int(t), f=f, x=x))
    pg = [g for g in games if g["plan"] == a.plan and g["x"] is not None]
    nmaps = len({g["map"] for g in games}) or 1
    print(f"# gplknob plan {a.plan} knob {a.knob} {a.where}: {len(pg)} plan games with the knob, {len(games)} games, {nmaps} maps")
    if len(pg) < 5 * a.min_n:
        print("too few games")
        return 1
    feats = [x for x in a.feats.split(",") if x in gplfeat.NAMES]
    K = a.folds
    res = collections.defaultdict(list)
    for i in range(K):
        tr = [g for g in games if fold(g["map"], K) != i]
        te = [g for g in games if fold(g["map"], K) == i]
        ptr = [g for g in tr if g["plan"] == a.plan and g["x"] is not None]
        pte = [g for g in te if g["plan"] == a.plan and g["x"] is not None]
        nte = len({g["map"] for g in te}) or 1
        res["untuned"].append(gain_of(pte, te, nte))
        # A binned per type
        xs = sorted(g["x"] for g in ptr)
        cuts = [xs[int(len(xs) * q)] for q in (0.2, 0.4, 0.6, 0.8)]

        def b(x):
            return sum(x > c for c in cuts)
        m0 = p0_by_type(tr)
        choice = {}
        for t in TYPES:
            best = None
            for bi in range(5):
                v = [g["w"] for g in ptr if g["t"] == t and b(g["x"]) == bi]
                if len(v) >= a.min_n and t in m0:
                    e = sum(v) / len(v) - m0[t]
                    if best is None or e > best[0]:
                        best = (e, bi)
            choice[t] = best[1] if best else None
        res["A binned/type"].append(gain_of([g for g in pte if choice.get(g["t"]) is not None and b(g["x"]) == choice[g["t"]]], te, nte))
        # B function of one draft feature
        mx = sum(g["x"] for g in ptr) / len(ptr)
        sx = math.sqrt(sum((g["x"] - mx) ** 2 for g in ptr) / len(ptr)) or 1.0
        lo, hi = min(g["x"] for g in ptr), max(g["x"] for g in ptr)
        h = (hi - lo) / 5 or 1.0
        bestfit = None
        for fn in feats:
            mf = sum(g["f"][fn] for g in ptr) / len(ptr)
            sf = math.sqrt(sum((g["f"][fn] - mf) ** 2 for g in ptr) / len(ptr)) or 1.0
            X, y = [], []
            for g in ptr:
                xz, fz = (g["x"] - mx) / sx, (g["f"][fn] - mf) / sf
                X.append([1.0, xz, xz * xz, xz * fz, fz])
                y.append(g["w"])
            beta = ols(X, y)
            if beta is None:
                continue
            sse = sum((yy - sum(bb * xx for bb, xx in zip(beta, x))) ** 2 for x, yy in zip(X, y))
            if bestfit is None or sse < bestfit[0]:
                bestfit = (sse, fn, beta, mf, sf)
        if bestfit:
            _, fn, beta, mf, sf = bestfit
            grid = [lo + (hi - lo) * j / 20 for j in range(21)]

            def xstar(fv):
                fz = (fv - mf) / sf
                return max(grid, key=lambda x: beta[1] * (x - mx) / sx + beta[2] * ((x - mx) / sx) ** 2 + beta[3] * (x - mx) / sx * fz)
            res["B f(feature)"].append(gain_of([g for g in pte if abs(g["x"] - xstar(g["f"][fn])) <= h], te, nte))
            res["B feature"].append(fn)
    print("| fit | CV gain v within-type plan 0 (if plan everywhere) | fold SE | folds |")
    print("|---|---|---|---|")
    for k, v in res.items():
        if k == "B feature":
            continue
        m = sum(v) / len(v)
        se = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1) / len(v))
        print(f"| {k} | {m:+.4f} | {se:.4f} | {' '.join('%+.3f' % x for x in v)} |")
    print(f"B features chosen per fold: {', '.join(res['B feature'])}")
    # all-data fits for the bot
    xs = sorted(g["x"] for g in pg)
    cuts = [xs[int(len(xs) * q)] for q in (0.2, 0.4, 0.6, 0.8)]
    m0 = p0_by_type(games)
    print(f"\nAll data, binned (quintile cuts {', '.join('%.4g' % c for c in cuts)}): per type best bin (mean K) and edge v type plan 0")
    for t in TYPES:
        rowz = []
        for bi in range(5):
            gs = [g for g in pg if g["t"] == t and sum(g["x"] > c for c in cuts) == bi]
            if len(gs) >= a.min_n and t in m0:
                rowz.append((sum(g["w"] for g in gs) / len(gs) - m0[t], sum(g["x"] for g in gs) / len(gs), len(gs)))
        print(f"  {t} {TYPES[t]}: " + "  ".join(f"K~{xk:.3g} {e:+.3f} (n {n})" for e, xk, n in rowz))
    # all-data function fit: K* at feature quintiles (for a data table: piecewise K* by feature bin)
    lo, hi = min(g["x"] for g in pg), max(g["x"] for g in pg)
    mx = sum(g["x"] for g in pg) / len(pg)
    sx = math.sqrt(sum((g["x"] - mx) ** 2 for g in pg) / len(pg)) or 1.0
    best = None
    for fn in feats:
        mf = sum(g["f"][fn] for g in pg) / len(pg)
        sf = math.sqrt(sum((g["f"][fn] - mf) ** 2 for g in pg) / len(pg)) or 1.0
        X = [[1.0, (g["x"] - mx) / sx, ((g["x"] - mx) / sx) ** 2, (g["x"] - mx) / sx * (g["f"][fn] - mf) / sf, (g["f"][fn] - mf) / sf] for g in pg]
        y = [g["w"] for g in pg]
        beta = ols(X, y)
        if beta is None:
            continue
        sse = sum((yy - sum(bb * xx for bb, xx in zip(beta, x))) ** 2 for x, yy in zip(X, y))
        if best is None or sse < best[0]:
            best = (sse, fn, beta, mf, sf)
    if best:
        _, fn, beta, mf, sf = best
        fv = sorted(g["f"][fn] for g in pg)
        grid = [lo + (hi - lo) * j / 20 for j in range(21)]
        print(f"\nAll data, function fit on {fn}: K* by {fn} quintile (bin upper edge -> K*)")
        for q in (0.2, 0.4, 0.6, 0.8, 1.0):
            v = fv[min(len(fv) - 1, int(len(fv) * q) - 1)]
            fz = (v - mf) / sf
            ks = max(grid, key=lambda x: beta[1] * (x - mx) / sx + beta[2] * ((x - mx) / sx) ** 2 + beta[3] * (x - mx) / sx * fz)
            print(f"  {fn} <= {v:.4g}: K* = {ks:.4g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
