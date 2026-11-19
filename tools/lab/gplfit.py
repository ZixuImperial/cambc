#!/usr/bin/env python3
"""gplfit.py (13 Nov, b2396; owner via Builder: "see on which maps each [plan] is good and their map features"): P3 per-plan map
feature profiles + a small policy tree (depth <= 2 on gplfeat.py features), cross-validated by map against the 6-type chooser.

Input: the P3 TSV (as gpltable.py; plan -1 dropped), map files found under --mapglob (basename + .map26a). Features: gplfeat.py,
cached in --cache. No map names are printed (maps are numbered).
A. Per plan k >= 1: paired maps where seat plans are {k, 0}: 'k beats 0' (k won, 0 lost) v '0 beats k'; mean feature vectors of both
   sets + the per-map rows in OUT/beats_k.tsv. Feature interaction: slope of win on the standardised feature under plan k minus under
   plan 0, with z; top features printed.
B. Policy chooser. Leaf rule (train data): for each plan k >= 1 with >= --min-n games of k and of plan 0 in the leaf, edge = mean_k -
   mean_0, se; choose argmax(edge - se) if > 0, else plan 0. Tree: depth 0 (all live), depth 1, depth 2 over features x quintile cuts,
   maximising sum share x (edge - se)+. Same leaf rule on the 6 gpl types = the type chooser. All evaluated by 5-fold CV by map hash:
   test gain = sum over test leaves of share x (test mean_k - test mean_0). The winner is printed with its CV gain +- fold SE.
Out: OUT/fit.md, OUT/tree.h (GPT_ #defines + GPT_TAB, flip-able), OUT/tree_flips.txt.
Usage: python3 -I tools/lab/gplfit.py [--in GLOB] [--out DIR] [--min-n 20] [--folds 5]
"""
import argparse
import collections
import glob
import hashlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gplfeat  # noqa: E402
import gpltable  # noqa: E402
from gpltable import load, fnum, TYPES, build_arms, lab, kcode  # noqa: E402

NAMES = gplfeat.NAMES
DEPTHS = [1, 2, 3]


def mean_se(v):
    n = len(v)
    if n == 0:
        return None, None, 0
    m = sum(v) / n
    var = sum((x - m) ** 2 for x in v) / (n - 1) if n > 1 else 0.25
    return m, math.sqrt(max(var, 1e-6) / n), n


def leaf_choice(games, plans, min_n):
    by = collections.defaultdict(list)
    for g in games:
        by[g["_p"]].append(g["_w"])
    m0, s0, n0 = mean_se(by.get(0, []))
    best = (0, 0.0, 0.0)
    if n0 < min_n:
        return best
    for k in plans:
        if k == 0:
            continue
        mk, sk, nk = mean_se(by.get(k, []))
        if nk < min_n:
            continue
        e, se = mk - m0, math.sqrt(sk * sk + s0 * s0)
        if e - se > best[1]:
            best = (k, e - se, e)
    return best  # (plan, penalised edge, raw edge)


def test_gain(leaves, games, nmaps, null=None):
    """leaves: list of (predicate, plan); games: test games -> sum share x (mean_k - mean_0)."""
    tot = 0.0
    for pred, k in leaves:
        if k == 0:
            continue
        gl = [g for g in games if pred(g)]
        mk = [g["_w"] for g in gl if g["_p"] == k]
        m0 = [g["_w"] for g in gl if g["_p"] == 0]
        if not mk or (null is None and not m0):
            continue
        share = len({g["map"] for g in gl}) / nmaps
        # null None: v the test fold's plan-0 games; null .5: plan 0 IS live (b2392), so .5 is its exact value (lower variance)
        tot += share * (sum(mk) / len(mk) - (sum(m0) / len(m0) if null is None else null))
    return tot


def test_gain_type(leaves, games, nmaps, only=None):
    """Planner 13 Nov: within-TYPE plan-0 null. For each (leaf, type) with plan k: weight = maps in leaf and type / all maps,
    gain = mean of plan-k games there - mean of ALL plan-0 games of that type (test fold)."""
    m0 = {}
    for t in TYPES:
        v = [g["_w"] for g in games if g["_t"] == t and g["_p"] == 0]
        m0[t] = sum(v) / len(v) if v else None
    tot = 0.0
    for pred, k in leaves:
        if k == 0:
            continue
        for t in TYPES:
            if m0[t] is None or (only is not None and t != only):
                continue
            gl = [g for g in games if g["_t"] == t and pred(g)]
            mk = [g["_w"] for g in gl if g["_p"] == k]
            if mk:
                tot += len({g["map"] for g in gl}) / nmaps * (sum(mk) / len(mk) - m0[t])
    return tot


def cuts(games, f):
    v = sorted({g["_f"][f] for g in games})
    if len(v) < 5:
        return v[:-1]
    return sorted({v[int(len(v) * q)] for q in (0.2, 0.4, 0.6, 0.8)})


def fit_tree(games, plans, depth, min_n):
    """-> (objective, node); node = ('leaf', plan, raw edge, n) or ('split', f, t, left, right). numpy form (13 Nov: 9k games made
    the list form take minutes per fit); same objective: sum over leaves of map share x (edge - se)+, quintile cuts per subset."""
    import numpy as np
    n = len(games)
    if n == 0:
        return 0.0, ("leaf", 0, 0.0, 0)
    P = np.array([g["_p"] for g in games], dtype=np.int64)
    W = np.array([g["_w"] for g in games], dtype=float)
    F = np.array([[g["_f"][nm] for nm in NAMES] for g in games], dtype=float)
    mid = {}
    M = np.array([mid.setdefault(g["map"], len(mid)) for g in games], dtype=np.int64)
    A = int(P.max()) + 1
    nm_all = len(mid) or 1

    def leaf(mask):
        p, w = P[mask], W[mask]
        cnt = np.bincount(p, minlength=A).astype(float)
        sm = np.bincount(p, weights=w, minlength=A)
        s2 = np.bincount(p, weights=w * w, minlength=A)
        best = (0, 0.0, 0.0)
        if cnt[0] < min_n:
            return best
        mean = sm / np.maximum(cnt, 1)
        var = np.where(cnt > 1, (s2 - sm * sm / np.maximum(cnt, 1)) / np.maximum(cnt - 1, 1), 0.25)
        se = np.sqrt(np.maximum(var, 1e-6) / np.maximum(cnt, 1))
        for k in plans:
            if k == 0 or k >= A or cnt[k] < min_n:
                continue
            e = mean[k] - mean[0]
            sk = math.sqrt(se[k] ** 2 + se[0] ** 2)
            if e - sk > best[1]:
                best = (int(k), float(e - sk), float(e))
        return best

    def rec(mask, d):
        k, pen, raw = leaf(mask)
        best = (pen, ("leaf", k, raw, int(mask.sum())))
        if d == 0:
            return best
        nm = len(np.unique(M[mask])) or 1
        for fi, fname in enumerate(NAMES):
            if fname in gplfeat.EXCLUDE:  # equal to own_* by symmetry (Planner 13 Nov)
                continue
            col = F[mask, fi]
            v = np.unique(col)
            if len(v) < 2:
                continue
            cs = v[:-1] if len(v) < 5 else np.unique(v[(np.array([.2, .4, .6, .8]) * len(v)).astype(int)])
            for t in cs:
                L = mask & (F[:, fi] <= t)
                R = mask & (F[:, fi] > t)
                if L.sum() < 2 * min_n or R.sum() < 2 * min_n:
                    continue
                if d >= 3:  # depth >= 3: choose the split by depth-1 lookahead (exhaustive is ~(F x C x 2)^3 leaf fits)
                    oL, nL = rec(L, 1)
                    oR, nR = rec(R, 1)
                else:
                    oL, nL = rec(L, d - 1)
                    oR, nR = rec(R, d - 1)
                o = (len(np.unique(M[L])) * oL + len(np.unique(M[R])) * oR) / nm
                if o > best[0] + 1e-12:
                    best = (o, ("split", fname, float(t), nL, nR), L, R)
        if len(best) == 4:
            o, nd, L, R = best
            if d >= 3:  # grow the chosen children to depth d - 1
                oL, nL = rec(L, d - 1)
                oR, nR = rec(R, d - 1)
                o2 = (len(np.unique(M[L])) * oL + len(np.unique(M[R])) * oR) / nm
                return (o2, ("split", nd[1], nd[2], nL, nR)) if o2 >= best[0] else (o, nd)
            return o, nd
        return best
    return rec(np.ones(n, dtype=bool), depth)


def tree_leaves(node, pred=lambda g: True):
    if node[0] == "leaf":
        return [(pred, node[1])]
    _, f, t, l, r = node
    return (tree_leaves(l, lambda g, p=pred: p(g) and g["_f"][f] <= t) +
            tree_leaves(r, lambda g, p=pred: p(g) and g["_f"][f] > t))


def leaf_report(node, games, plans, min_n, path="root"):
    """Builder 13 Nov: per leaf, its best arm and the top arms with gain v that leaf's OWN plan-0 arm."""
    if node[0] == "split":
        _, f, t, l, r = node
        return (leaf_report(l, [g for g in games if g["_f"][f] <= t], plans, min_n, f"{path} & {f}<={t:.4g}") +
                leaf_report(r, [g for g in games if g["_f"][f] > t], plans, min_n, f"{path} & {f}>{t:.4g}"))
    by = collections.defaultdict(list)
    for g in games:
        by[g["_p"]].append(g["_w"])
    m0, s0, n0 = mean_se(by.get(0, []))
    rows = []
    for k in plans:
        if k == 0 or len(by.get(k, [])) < min_n or n0 == 0:
            continue
        mk, sk, nk = mean_se(by[k])
        rows.append((mk - m0, math.sqrt(sk * sk + s0 * s0), nk, k))
    rows.sort(reverse=True)
    nm = len({g["map"] for g in games})
    top = "; ".join(f"{lab(k)} {e:+.3f}+-{1.96 * se:.3f} (n {n})" for e, se, n, k in rows[:4])
    return [f"| {path} | {nm} | {n0} | {lab(node[1])} | {top} |"]


def tree_text(node, ind=""):
    if node[0] == "leaf":
        return [f"{ind}-> arm {lab(node[1])} (train edge {node[2]:+.3f}, {node[3]} games)"]
    _, f, t, l, r = node
    return [f"{ind}if {f} <= {t:.4g}:"] + tree_text(l, ind + "    ") + [f"{ind}else:"] + tree_text(r, ind + "    ")


def type_fit(games, plans, min_n):
    return {t: leaf_choice([g for g in games if g["_t"] == t], plans, min_n)[0] for t in TYPES}


def fold(m, k):
    return int(hashlib.md5(("f" + m).encode()).hexdigest(), 16) % k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/data/zw4424/st/b2392/p3/chunk_*.tsv")
    ap.add_argument("--mapglob", default="/data/zw4424/st/b2392/p3/maps_c*/")
    ap.add_argument("--out", default="/data/zw4424/st/b2396/gpl_fit")
    ap.add_argument("--cache", default="/data/zw4424/st/b2396/feat_cache.tsv")
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--depths", default="1,2,3", help="tree depths to fit and cross-validate (3 uses depth-1 lookahead)")
    ap.add_argument("--knobs", default="auto", help="knob columns forming the arm with the plan (as gpltable.py): auto | none | list")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    global DEPTHS
    DEPTHS = [int(x) for x in a.depths.split(",") if x.strip()]
    _, rows, extra = load(a.inp)
    for r in rows:
        r["_p"] = int(fnum(r["plan"]))
    rows = [r for r in rows if r["_p"] >= 0]
    gpltable.wave_adjust(rows)  # per-wave plan-0 shift (as gpltable.py)
    build_arms(rows, extra, a.knobs)
    cache = {}
    if os.path.exists(a.cache):
        with open(a.cache) as fh:
            hdr = fh.readline().rstrip("\n").split("\t")
            if hdr[1:] != NAMES:  # feature set changed (13 Nov: cmarg, team added): rebuild the cache
                hdr = None
            for line in (fh if hdr else []):
                p = line.rstrip("\n").split("\t")
                cache[p[0]] = {h: float(x) for h, x in zip(hdr[1:], p[1:])} if len(p) == len(hdr) else None
    paths = {}
    for d in glob.glob(a.mapglob):
        for f in os.listdir(d):
            if f.endswith(".map26a"):
                paths[f[:-7]] = os.path.join(d, f)
    new = 0
    for r in rows:
        m = r["map"]
        if m not in cache and m in paths:
            try:
                cache[m] = gplfeat.feats(paths[m])
            except Exception:  # noqa: BLE001
                cache[m] = None
            new += 1
    if new:
        with open(a.cache + ".new", "w") as fh:
            fh.write("map\t" + "\t".join(NAMES) + "\n")
            for m, f in cache.items():
                if f:
                    fh.write(m + "\t" + "\t".join(repr(f[n]) for n in NAMES) + "\n")
        os.replace(a.cache + ".new", a.cache)
    games = []
    for r in rows:
        p, w, t = r["_p"], r.get("_wadj", fnum(r["win"])), fnum(r.get("mtype"))
        f = cache.get(r["map"])
        if p is None or p < 0 or w is None or f is None or t is None:
            continue
        games.append(dict(map=r["map"], seat=r["seat"], _p=int(p), _w=w, _t=int(t), _f=f))
    plans = sorted({g["_p"] for g in games})
    maps = sorted({g["map"] for g in games})
    mid = {m: i for i, m in enumerate(maps)}
    L = [f"# GPL P3 per-plan map features + policy tree ({len(games)} games, {len(maps)} maps; features gplfeat.py; no map names)\n"]

    # A. paired 'beats' sets and interactions
    bymap = collections.defaultdict(dict)
    for g in games:
        bymap[g["map"]][g["seat"]] = g
    sd = {}
    for n in NAMES:
        v = [g["_f"][n] for g in games]
        mu = sum(v) / len(v)
        sd[n] = (mu, math.sqrt(sum((x - mu) ** 2 for x in v) / max(1, len(v) - 1)) or 1.0)

    def slope(gs, n):
        if len(gs) < 10:
            return None, None
        x = [(g["_f"][n] - sd[n][0]) / sd[n][1] for g in gs]
        y = [g["_w"] for g in gs]
        mx, my = sum(x) / len(x), sum(y) / len(y)
        sxx = sum((xi - mx) ** 2 for xi in x)
        if sxx <= 0:
            return None, None
        b = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sxx
        res = sum((yi - my - b * (xi - mx)) ** 2 for xi, yi in zip(x, y)) / max(1, len(x) - 2)
        return b, math.sqrt(res / sxx)
    g0 = [g for g in games if g["_p"] == 0]
    for k in plans:
        if k == 0:
            continue
        gk = [g for g in games if g["_p"] == k]
        win, lose = [], []
        for m, s in bymap.items():
            if len(s) == 2 and sorted(x["_p"] for x in s.values()) == [0, k]:  # with knobs, k is an arm (plan + knob values)
                a0 = next(x for x in s.values() if x["_p"] == 0)
                ak = next(x for x in s.values() if x["_p"] == k)
                if ak["_w"] > a0["_w"]:
                    win.append(m)
                elif ak["_w"] < a0["_w"]:
                    lose.append(m)
        with open(os.path.join(a.out, f"beats_{k}.tsv"), "w") as fh:
            fh.write("map_no\tresult\t" + "\t".join(NAMES) + "\n")
            for tag, ms in (("k_beats_0", win), ("0_beats_k", lose)):
                for m in ms:
                    fh.write(f"{mid[m]}\t{tag}\t" + "\t".join(f"{cache[m][n]:.4g}" for n in NAMES) + "\n")
        L.append(f"## Arm {lab(k)}\n")
        L.append(f"Paired maps (one seat plan {k}, the other plan 0): plan {k} beats 0 on {len(win)}, 0 beats {k} on {len(lose)} "
                 f"(rows: {os.path.join(a.out, f'beats_{k}.tsv')}).\n")
        inter = []
        for n in NAMES:
            bk, sk = slope(gk, n)
            b0, s0 = slope(g0, n)
            if bk is None or b0 is None:
                continue
            z = (bk - b0) / math.sqrt(sk * sk + s0 * s0)
            mw = sum(cache[m][n] for m in win) / len(win) if win else float("nan")
            ml = sum(cache[m][n] for m in lose) / len(lose) if lose else float("nan")
            inter.append((abs(z), n, bk - b0, z, mw, ml))
        inter.sort(reverse=True)
        L.append(f"| feature | slope diff (win per SD, plan {k} - plan 0) | z | mean where {k} beats 0 | mean where 0 beats {k} | all maps |")
        L.append("|---|---|---|---|---|---|")
        for _, n, d, z, mw, ml in inter:
            L.append(f"| {n} | {d:+.3f} | {z:+.2f} | {mw:.4g} | {ml:.4g} | {sd[n][0]:.4g} |")
        L.append("")

    # B. policy choosers, CV by map
    K = a.folds
    res = collections.defaultdict(list)
    pert = collections.defaultdict(list)
    for i in range(K):
        tr = [g for g in games if fold(g["map"], K) != i]
        te = [g for g in games if fold(g["map"], K) == i]
        nte = len({g["map"] for g in te}) or 1
        tc = type_fit(tr, plans, a.min_n)
        tl = [(lambda g, t=t: g["_t"] == t, tc[t]) for t in TYPES]
        res["type"].append(test_gain(tl, te, nte))
        res["type v.5"].append(test_gain(tl, te, nte, 0.5))
        res["type vT0"].append(test_gain_type(tl, te, nte))
        for dep in DEPTHS:
            _, node = fit_tree(tr, plans, dep, a.min_n)
            res[f"tree d{dep}"].append(test_gain(tree_leaves(node), te, nte))
            res[f"tree d{dep} v.5"].append(test_gain(tree_leaves(node), te, nte, 0.5))
            res[f"tree d{dep} vT0"].append(test_gain_type(tree_leaves(node), te, nte))
            for t in TYPES:  # Builder 13 Nov: the tree may override live's route on a type only where it cross-validates above it
                pert[(dep, t)].append(test_gain_type(tree_leaves(node), te, nte, only=t))
    L.append("## Chooser comparison (5-fold CV by map; gain = share x (plan k - plan 0) on held-out maps. 'vT0' rows (DECIDING, Planner 13 Nov): plan k v ALL plan-0 games of the same map type in the test fold; 'v.5' rows score plan k v .50, "
             "valid only if plan 0 reads .50 v live; it read .475 +-.013 by chunk 6, so use the plan-0 rows)\n")
    L.append("| chooser | CV gain | fold SE | folds |")
    L.append("|---|---|---|---|")
    summ = {}
    for nm_, v in res.items():
        m = sum(v) / len(v)
        se = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1) / len(v))
        summ[nm_] = (m, se)
        L.append(f"| {nm_} | {m:+.4f} | {se:.4f} | {' '.join('%+.3f' % x for x in v)} |")
    tc = type_fit(games, plans, a.min_n)
    trees = {d: fit_tree(games, plans, d, a.min_n)[1] for d in DEPTHS}
    best = max((k for k in summ if k.endswith("vT0")), key=lambda k: summ[k][0])
    tb = max((f"tree d{d} vT0" for d in DEPTHS), key=lambda k: summ[k][0])
    tbest = tb[:-4]
    rec = summ[tb][0] > summ["type vT0"][0] and summ[tb][0] - summ[tb][1] > 0  # judged on the within-type plan-0 null
    summ[tbest] = summ[tb]
    summ["type"] = summ["type vT0"]  # needs CV gain > 1 fold SE above 0
    L.append(f"\nBest CV chooser: {best} ({summ[best][0]:+.4f} +- {summ[best][1]:.4f}). Type chooser on all data (same leaf rule): "
             + " ".join(f"T{t}={lab(tc[t])}" for t in TYPES) + "\n")
    L.append(f"Feature tree {'RECOMMENDED over the type chooser' if rec else 'NOT recommended (CV not above the type chooser and 1 SE above 0)'}: "
             f"{tbest} CV {summ[tbest][0]:+.4f} v type {summ['type'][0]:+.4f}.\n")
    for d in DEPTHS:
        L.append(f"### Tree depth {d} (all data)\n```")
        L += tree_text(trees[d])
        L.append("```")
        L.append(f"\n| leaf (depth {d}) | maps | plan-0 games | chosen arm | top arms: gain v this leaf's plan 0 +- 1.96 SE (games) |")
        L.append("|---|---|---|---|---|")
        L += leaf_report(trees[d], games, plans, a.min_n)
        L.append("")
    dsel = int(tbest.split("d")[-1])
    node = trees[dsel]
    mask = 0
    L.append(f"\n## Per-type CV of the {tbest} tree (v within-type plan 0); types at or below 0 are forced to live's route (GPT_LIVEMASK bit t)\n")
    L.append("| type | CV gain contribution | fold SE | forced live |")
    L.append("|---|---|---|---|")
    for t in TYPES:
        v = pert[(dsel, t)]
        m = sum(v) / len(v) if v else 0.0
        se = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1) / max(1, len(v))) if v else 0.0
        forced = m <= 0
        mask |= (1 << t) if forced else 0
        L.append(f"| {t} {TYPES[t]} | {m:+.4f} | {se:.4f} | {'yes' if forced else 'no'} |")
    # GENERIC node table (any depth): nodes in BFS order: GPT_N<i>_F (feature id), _T (thr x1000), _L, _R (child: < 100 = node index,
    # >= 100 = leaf 100 + j); leaves GPT_L<j>_P (plan) + GPT_L<j>_<KNOB> codes. Go LEFT if feat*1000 <= T.
    nodes, leaves = [], []

    def emit(nd):
        if nd[0] == "leaf":
            leaves.append(nd[1])
            return 100 + len(leaves) - 1
        i = len(nodes)
        nodes.append(None)
        _, f, t, l, r = nd
        nodes[i] = (gplfeat.FID[f], int(round(t * 1000)), emit(l), emit(r))
        return i
    root = emit(node)
    vals = dict(LIVEMASK=mask, ROOT=root, NN=len(nodes), NL=len(leaves))
    for i, (f, t, l, r) in enumerate(nodes):
        vals.update({f"N{i}_F": f, f"N{i}_T": t, f"N{i}_L": l, f"N{i}_R": r})
    for j, arm in enumerate(leaves):
        pl, kv = gpltable.ARMS[arm]
        vals[f"L{j}_P"] = pl
        for c, v in zip(gpltable.KNOBS, kv or [""] * len(gpltable.KNOBS)):
            vals[f"L{j}_{c.upper()}"] = kcode(v) if pl else 0
    flips = " ".join(f"GPT_{k}={v}" for k, v in vals.items())
    # legacy depth <= 2 form (gpt7 donor: F0 T0 F1 T1 F2 T2 PLL PLR PRL PRR)
    legacy = ""
    if dsel <= 2:
        def child(nd):
            if nd[0] == "leaf":
                return 0, 0, nd[1], nd[1]
            _, f, t, l, r = nd
            return gplfeat.FID[f], int(round(t * 1000)), (l[1] if l[0] == "leaf" else 0), (r[1] if r[0] == "leaf" else 0)
        if node[0] == "leaf":
            lv = dict(F0=0, T0=0, F1=0, T1=0, F2=0, T2=0, PLL=node[1], PLR=node[1], PRL=node[1], PRR=node[1])
        else:
            _, f, t, l, r = node
            F1, T1, PLL, PLR = child(l)
            F2, T2, PRL, PRR = child(r)
            lv = dict(F0=gplfeat.FID[f], T0=int(round(t * 1000)), F1=F1, T1=T1, F2=F2, T2=T2, PLL=PLL, PLR=PLR, PRL=PRL, PRR=PRR)
        lv = {k: (gpltable.ARMS[v][0] if k.startswith("P") else v) for k, v in lv.items()}
        legacy = " ".join(f"GPT_{k}={v}" for k, v in lv.items()) + f" GPT_LIVEMASK={mask}"
    h = [f"// GPT policy tree (gplfit.py, b2396). Feature ids = gplfeat.py NAMES order (1 c .. 16 walk_ab, 17 cmarg, 18 team); value x1000.",
         "// Generic form: start at node ROOT; at node i go LEFT if feat[N<i>_F]*1000 <= N<i>_T; a child >= 100 is leaf (child-100): plan",
         "// L<j>_P plus knob codes L<j>_<KNOB> (integer as is, decimal x10, 'all'/whole team = 9). Plan 0 = live route.",
         "// LIVEMASK: bit t set -> gpl_type t plays live's route whatever the tree says (the tree did not cross-validate above live there).",
         f"// {tbest}: CV gain {summ[tbest][0]:+.4f} +- {summ[tbest][1]:.4f}; type chooser CV {summ['type'][0]:+.4f}; "
         f"{'RECOMMENDED' if rec else 'NOT RECOMMENDED'}.",
         f"// Flip (generic): {flips}"]
    if legacy:
        h.append(f"// Flip (legacy depth<=2, gpt7 donor form): {legacy}")
    h += [f"#define GPT_{k} {v}" for k, v in vals.items()]
    h.append(f"inline const volatile int GPT_TAB[{len(vals) + 2}] = {{ 0x47505432, " + ", ".join(f"GPT_{k}" for k in vals) + ", 0 };")
    L.append("\n## Tree data table\n```\n" + "\n".join(h) + "\n```")
    md = "\n".join(L) + "\n"
    open(os.path.join(a.out, "fit.md"), "w").write(md)
    open(os.path.join(a.out, "tree.h"), "w").write("\n".join(h) + "\n")
    open(os.path.join(a.out, "tree_flips.txt"), "w").write(f"TREE\t{flips}\tcv {summ[tbest][0]:+.4f} +- {summ[tbest][1]:.4f} ({tbest}; {'RECOMMENDED' if rec else 'NOT RECOMMENDED'})\n"
                                                          + (f"LEGACY\t{legacy}\n" if legacy else "") + f"TYPE_CV\t{summ['type'][0]:+.4f}\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
