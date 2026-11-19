#!/usr/bin/env python3
"""gplvp.py (13 Nov, b2396; Builder: VP trees whose leaves carry (plan, wa, wb, cdamp, switch point), wa per leaf): value-program
chooser on set 3/4 rows. Steps, all cross-validated over held-out MAP folds (5) v the within-type plan-0 null (wins shifted per wave):
 1 tree over draft features (gplfit.fit_tree, depth --depth) choosing a VP plan per leaf (plans = codes present in the chunks given;
   set 3 = 100 + id after gpltable's recode);
 2 per leaf, for the chosen plan, the best quintile bin of each knob in --knobs (wa first): the leaf's plan-k games in that bin v the
   leaf's plan-0 games (>= --min-n games);
 3 test gain (per fold): for each test leaf with plan k, the plan-k test games whose PRIMARY knob (first of --knobs) lies in the chosen
   bin, mean minus their type's plan-0 test mean, weighted by the leaf's map share. 'plan only' (no knob bin) is printed next to it.
Prints the all-data tree, each leaf's plan + knob bins (range, edge, n) and the CV rows; writes OUT/vp_tree.h with GPV_ defines: the
generic GPT node form (gplfit) + per leaf GPV_L<j>_P and GPV_L<j>_<KNOB>_LO / _HI (bin bounds, raw units; the bot draws/uses the bin
midpoint GPV_L<j>_<KNOB>).
Usage: python3 -I tools/lab/gplvp.py [--chunks 131-154,155-200] [--knobs wa,wb,cdamp,tval] [--depth 2] [--min-n 15] [--out DIR]
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
import gplfit  # noqa: E402
from gpltable import load, fnum, TYPES  # noqa: E402


def fold(m, k):
    return int(hashlib.md5(("f" + m).encode()).hexdigest(), 16) % k


def in_chunks(c, spec):
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        if int(lo) <= c <= int(hi or lo):
            return True
    return False


def leaves_of(node, pred=lambda g: True, out=None):
    out = [] if out is None else out
    if node[0] == "leaf":
        out.append((pred, node[1]))
    else:
        _, f, t, l, r = node
        leaves_of(l, lambda g, p=pred: p(g) and g["_f"][f] <= t, out)
        leaves_of(r, lambda g, p=pred: p(g) and g["_f"][f] > t, out)
    return out


def best_bin(games, k, knob, min_n):
    """-> (lo, hi, edge, n) of the best quintile bin of knob for plan k v plan 0 in these games, or None."""
    gk = [g for g in games if g["_p"] == k and g["kn"].get(knob) is not None]
    g0 = [g["_w"] for g in games if g["_p"] == 0]
    if len(gk) < 5 * min_n or len(g0) < min_n:
        return None
    m0 = sum(g0) / len(g0)
    xs = sorted(g["kn"][knob] for g in gk)
    cuts = [xs[0] - 1e-9] + [xs[int(len(xs) * q)] for q in (0.2, 0.4, 0.6, 0.8)] + [xs[-1] + 1e-9]
    best = None
    for i in range(5):
        v = [g["_w"] for g in gk if cuts[i] < g["kn"][knob] <= cuts[i + 1]]
        if len(v) >= min_n:
            e = sum(v) / len(v) - m0
            if best is None or e > best[2]:
                best = (cuts[i], cuts[i + 1], e, len(v))
    return best


def paired_edge(games, k):
    """Builder 13 Nov: set 4/4b are PAIRED (plan k and plan 0 on the same map). -> (mean of per-map (mean plan-k win - mean plan-0
    win) over maps with both, SE, maps) or None."""
    by = collections.defaultdict(lambda: ([], []))
    for g in games:
        if g["_p"] == k:
            by[g["map"]][0].append(g["_w"])
        elif g["_p"] == 0:
            by[g["map"]][1].append(g["_w"])
    d = [sum(a) / len(a) - sum(b) / len(b) for a, b in by.values() if a and b]
    if len(d) < 2:
        return None
    m = sum(d) / len(d)
    return m, math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1) / len(d)), len(d)


def type_m0(games):
    d = collections.defaultdict(list)
    for g in games:
        if g["_p"] == 0:
            d[g["_t"]].append(g["_w"])
    return {t: sum(v) / len(v) for t, v in d.items() if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/data/USER/st/b2392/p3/chunk_*.tsv")
    ap.add_argument("--chunks", default="301-324")
    ap.add_argument("--knobs", default="wa,wb,cdamp,tval,pen,glide")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--min-n", type=int, default=15)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--cache", default="/data/USER/st/b2396/feat_cache.tsv")
    ap.add_argument("--out", default="/data/USER/st/b2396/gpl_vp")
    a = ap.parse_args()
    knobs = [k for k in a.knobs.split(",") if k]
    _, rows, _ = load(a.inp)
    rows = [r for r in rows if in_chunks(r.get("_chunk", 0), a.chunks)]
    gpltable.wave_adjust(rows)
    cache = {}
    with open(a.cache) as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) == len(hdr):
                cache[p[0]] = {h: float(x) for h, x in zip(hdr[1:], p[1:])}
    games = []
    for r in rows:
        pl, t, f = fnum(r.get("plan")), fnum(r.get("mtype")), cache.get(r["map"])
        if pl is None or pl < 0 or t is None or f is None or r.get("_wadj") is None:
            continue
        kn = {k: fnum(r.get(k)) for k in knobs}
        if "tval" in kn and kn["tval"] is not None and str(r.get("trig", "")).strip() not in ("", "0"):
            kn["tval"] = None  # switch point fitted in trig-0 units only (tributed gems); other trigger modes are other scales
        games.append(dict(map=r["map"], _p=int(pl), _w=r["_wadj"], _t=int(t), _f=f, kn=kn))
    plans = sorted({g["_p"] for g in games})
    gpltable.ARMS[:] = [(i, ()) for i in range(max(plans) + 1)] if plans else [(0, ())]  # plan codes are used directly as arm ids here
    gpltable.KNOBS[:] = []
    nmaps = len({g["map"] for g in games}) or 1
    os.makedirs(a.out, exist_ok=True)
    L = [f"# GPL value-program trees (chunks {a.chunks}): {len(games)} games, {nmaps} maps, plans {plans}, knobs {knobs}\n"]
    if 0 not in plans or len(plans) < 2:
        L.append("no plan-0 null or no VP plans in these chunks")
        print("\n".join(L))
        return 1
    K = a.folds
    res = collections.defaultdict(list)
    for i in range(K):
        tr = [g for g in games if fold(g["map"], K) != i]
        te = [g for g in games if fold(g["map"], K) == i]
        nte = len({g["map"] for g in te}) or 1
        _, node = gplfit.fit_tree(tr, plans, a.depth, a.min_n)
        m0 = type_m0(te)
        g_plan, g_knob = 0.0, 0.0
        for pred, k in leaves_of(node):
            if k == 0:
                continue
            bb = best_bin([g for g in tr if pred(g)], k, knobs[0], a.min_n) if knobs else None
            tl = [g for g in te if pred(g)]
            share = len({g["map"] for g in tl}) / nte
            for sel, acc in ((lambda g: True, "plan"), (lambda g: bb is not None and g["kn"].get(knobs[0]) is not None
                                                        and bb[0] < g["kn"][knobs[0]] <= bb[1], "knob")):
                mk = [g["_w"] - m0[g["_t"]] for g in tl if g["_p"] == k and g["_t"] in m0 and sel(g)]
                if mk:
                    if acc == "plan":
                        g_plan += share * sum(mk) / len(mk)
                    else:
                        g_knob += share * sum(mk) / len(mk)
        res["VP tree, plan only"].append(g_plan)
        res[f"VP tree + {knobs[0] if knobs else '-'} bin per leaf"].append(g_knob)
    L.append("| chooser | CV gain v within-type plan 0 | fold SE | folds |")
    L.append("|---|---|---|---|")
    summ = {}
    for k, v in res.items():
        m = sum(v) / len(v)
        se = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1) / len(v))
        summ[k] = (m, se)
        L.append(f"| {k} | {m:+.4f} | {se:.4f} | {' '.join('%+.3f' % x for x in v)} |")
    best_row = max(summ, key=lambda k: summ[k][0])
    rec = summ[best_row][0] - summ[best_row][1] > 0
    L.append(f"\nBest: {best_row} {summ[best_row][0]:+.4f} +- {summ[best_row][1]:.4f} -> {'CV-POSITIVE (send as gpt)' if rec else 'not CV-positive'}\n")
    _, node = gplfit.fit_tree(games, plans, a.depth, a.min_n)
    L.append("### All-data tree\n```")
    L += gplfit.tree_text(node)
    L.append("```\n### Leaf edges, PAIRED (per-map plan k - plan 0 on the same map; only maps with both)\n")
    for j, (pred, k) in enumerate(leaves_of(node)):
        gl = [g for g in games if pred(g)]
        rowsj = []
        for kk in plans:
            if kk == 0:
                continue
            pe = paired_edge(gl, kk)
            if pe:
                rowsj.append((pe[0], kk, pe))
        rowsj.sort(reverse=True)
        L.append(f"- L{j} (chosen {k}): " + "; ".join(f"{kk} {pe[0]:+.3f}+-{1.96 * pe[1]:.3f} ({pe[2]} maps)" for _, kk, pe in rowsj[:4]))
    L.append("\n| leaf | maps | plan | " + " | ".join(f"{k} best bin (edge v leaf plan 0, n)" for k in knobs) + " |")
    L.append("|---|---|---|" + "---|" * len(knobs))
    nodes, leaves = [], []

    def emit(nd):
        if nd[0] == "leaf":
            leaves.append(nd)
            return 100 + len(leaves) - 1
        i = len(nodes)
        nodes.append(None)
        _, f, t, l, r = nd
        nodes[i] = (gplfeat.FID[f], int(round(t * 1000)), emit(l), emit(r))
        return i
    root = emit(node)
    vals = dict(ROOT=root, NN=len(nodes), NL=len(leaves))
    for i, (f, t, l, r) in enumerate(nodes):
        vals.update({f"N{i}_F": f, f"N{i}_T": t, f"N{i}_L": l, f"N{i}_R": r})
    for j, (pred, k) in enumerate(leaves_of(node)):
        gl = [g for g in games if pred(g)]
        cells = []
        vals[f"L{j}_P"] = k
        for kn in knobs:
            bb = best_bin(gl, k, kn, a.min_n) if k else None
            cells.append(f"{bb[0]:.4g}-{bb[1]:.4g} {bb[2]:+.3f} (n {bb[3]})" if bb else "-")
            if bb:
                vals[f"L{j}_{kn.upper()}_LO"] = int(round(bb[0]))
                vals[f"L{j}_{kn.upper()}_HI"] = int(round(bb[1]))
                vals[f"L{j}_{kn.upper()}"] = int(round((bb[0] + bb[1]) / 2))
        L.append(f"| L{j} | {len({g['map'] for g in gl})} | {k} | " + " | ".join(cells) + " |")
    # b2397's donor form (depth <= 2): GPT_F0 T0 F1 T1 F2 T2; leaves PLL PLR PRL PRR: GPT_<L> = bot plan id (set-3 code - 100),
    # GPT_<L>_WB / _WA (x100), _CD (cdamp x100, 0 none), _SW (tributed gems >= SW, trig 0), _PEN (plan 10), _GLIDE (plan 9).
    # Knob value = the leaf's best-bin midpoint; if no bin is fitted, the median drawn value of that plan in the leaf (0 if none).
    NAMEMAP = {"wb": "WB", "wa": "WA", "cdamp": "CD", "tval": "SW", "pen": "PEN", "glide": "GLIDE"}
    legacy = ""
    if a.depth <= 2:
        def leafvals(nd, pred):
            k = nd[1]
            gl = [g for g in games if pred(g)]
            out = {"": (k - 100 if k >= 100 else k)}
            for kn in knobs:
                if kn not in NAMEMAP:
                    continue
                bb = best_bin(gl, k, kn, a.min_n) if k else None
                if bb:
                    v = (bb[0] + bb[1]) / 2
                else:
                    xs = sorted(g["kn"][kn] for g in gl if g["_p"] == k and g["kn"].get(kn) is not None)
                    v = xs[len(xs) // 2] if xs else 0
                out["_" + NAMEMAP[kn]] = int(round(v)) if k else 0
            return out

        def sub(nd, pred):
            if nd[0] == "leaf":
                return 0, 0, (nd, pred), (nd, pred)
            _, f, t, l, r = nd
            return (gplfeat.FID[f], int(round(t * 1000)), (l, lambda g, p=pred: p(g) and g["_f"][f] <= t),
                    (r, lambda g, p=pred: p(g) and g["_f"][f] > t))
        if node[0] == "leaf":
            F0 = T0 = 0
            F1, T1, LL, LR = sub(node, lambda g: True)
            F2, T2, RL, RR = F1, T1, LL, LR
        else:
            _, f, t, l, r = node
            F0, T0 = gplfeat.FID[f], int(round(t * 1000))
            F1, T1, LL, LR = sub(l, lambda g: g["_f"][f] <= t)
            F2, T2, RL, RR = sub(r, lambda g: g["_f"][f] > t)
        lv = dict(F0=F0, T0=T0, F1=F1, T1=T1, F2=F2, T2=T2)
        for nm_, (nd, pred) in (("PLL", LL), ("PLR", LR), ("PRL", RL), ("PRR", RR)):
            if nd[0] != "leaf":
                continue
            for suf, v in leafvals(nd, pred).items():
                lv[nm_ + suf] = v
        if any(v == 7 for k, v in lv.items() if k in ("PLL", "PLR", "PRL", "PRR")):
            lv["P7_FLOOR_OWNGEM"] = 25  # Builder 13 Nov: a plan-7 leaf plays 7 only if own_ratio > 0 and own_gem >= 25, else plan 0
        legacy = " ".join(f"GPT_{k}={v}" for k, v in lv.items())
    flips = " ".join(f"GPV_{k}={v}" for k, v in vals.items())
    h = ["// GPV value-program tree (gplvp.py, b2396): node form as GPT (gplfit; feature ids gplfeat.NAMES order, x1000, LEFT if <=);",
         "// child >= 100 = leaf; leaf plan GPV_L<j>_P (set-3 codes are 100 + b2392's id), knob = bin midpoint GPV_L<j>_<KNOB> (raw units).",
         f"// {best_row}: CV {summ[best_row][0]:+.4f} +- {summ[best_row][1]:.4f}; {'CV-POSITIVE' if rec else 'not CV-positive'}. Flip: {flips}"]
    h += [f"#define GPV_{k} {v}" for k, v in vals.items()]
    if legacy:
        h.append(f"// b2397 donor form: {legacy}")
        h += [f"#define {x.split('=')[0]} {x.split('=')[1]}" for x in legacy.split()]
    L.append("\n```\n" + "\n".join(h) + "\n```")
    md = "\n".join(L) + "\n"
    open(os.path.join(a.out, "vp.md"), "w").write(md)
    open(os.path.join(a.out, "vp_tree.h"), "w").write("\n".join(h) + "\n")
    open(os.path.join(a.out, "vp_flips.txt"), "w").write(f"VP\t{flips}\tcv {summ[best_row][0]:+.4f} +- {summ[best_row][1]:.4f} ({best_row}; {'CV-POSITIVE' if rec else 'no'})\n"
                                                        + (f"GPT\t{legacy}\n" if legacy else ""))
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
