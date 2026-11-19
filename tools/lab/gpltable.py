#!/usr/bin/env python3
"""gpltable.py (13 Nov, b2396; GPL A2, spec_gpl_1113 Amendments 13-22): P3 randomised-plan results -> per map type x plan table and
the chooser's data table (one plan id per map type).

Input: b2392's per-game TSV (default /data/zw4424/st/b2392/p3/chunk_*.tsv; all.tsv is used only when no chunk files exist; rows are
deduped on map+seat). Columns: map, seat (A|B, research bot's seat), plan (0 = live route, in the randomisation), win (1/0/.5 of the
research bot v live), mtype (gpl_type 1..6; blank -> computed with mapclass from --mapdir), then optional numeric key rows (d, phold,
keygem_r200, owngold_r200, centre_first, forced_out, ...: every other column is averaged per cell, blanks skipped).

Method: the opponent is live, so a plan's score v .50 is its edge; plan-0 games are the null arm (reported, and the diff k - 0 too).
Plans are drawn per map + seat, so a cell's games are clustered by MAP (cluster-robust SE of the mean). Per type, the winner is the
plan k >= 1 with the highest point among those whose CI LOWER bound clears .50 (z = --z, default 1.96); none clears -> plan 0 (live).
No plan is judged pooled (owner, A22): only per type. Projected gain = sum over types of share(type) x (winner score - .50);
shares come from the distinct maps per type in the data (or --share-dir maps). A winner's-curse check: the maps are split in two by
a hash; the winner is picked on each half and its edge read on the other half (cross-validated gain).

Out: --out DIR (default /data/zw4424/st/b2396/gpl_out): table.md (human), chooser.h (runtime data table, flip-able #defines),
chooser.tsv (type, plan, n, edge), flips.txt (the flip.sh string). Prints table.md.
Usage: python3 -I tools/lab/gpltable.py [--in GLOB] [--out DIR] [--z 1.96] [--prefix GPC] [--min-maps 30] [--mapdir DIR] [--share-dir DIR]
"""
import argparse
import collections
import glob
import hashlib
import math
import os
import re
import sys

TYPES = {1: "HEAVY-DOM", 2: "SPLIT-SIDES", 3: "CENTRE-DOM", 4: "CENTRE-GEM", 5: "OWN-SUFF", 6: "UNIFORM", 7: "TWO-HALVES"}
CORE = {"map", "seat", "plan", "win", "mtype"}
# Sanity column only, NOT data (Builder 13 Nov): Deep's replay prior /data/zw4424/st/deepan/gpl/plan_table_prior.txt: our 'own gold, no
# forward capture by r150' (OG/-) opening is our worst everywhere; forward (/F) openings win .28-.40; exception: own gems (OM/-) on
# HEAVY-DOM (ours .529). Plan -> label is b2396's reading of b2392's plans: 1 own gold -> centre after first tribute ~ OG/-;
# 2 own gold -> gem-richer of own/centre ~ OG then OM or C; 3 carries to the centre gem region ~ C/F.
KNOB_AUTO = ("trig", "crew", "boost", "gsel", "gwho", "glide")  # b2392 wave 3 (numeric; blank where a knob does not apply); push_r is info, not a knob
ARMS = [(0, ())]  # arm id -> (plan, knob values); arm 0 = plan 0 (live route; knobs ignored)
KNOBS = []


def build_arms(rows, extra, spec):
    """Builder 13 Nov: rows may carry knob columns (push trigger a/b/c/d, push crew 3/4, steal weight 2.5/1.5): the chooser's unit is the
    ARM (plan, knob values). spec 'auto' = columns named in KNOB_AUTO, prefixed k_, or holding non-numeric values; 'none' = plan only;
    else a comma list. Sets r['_p'] = arm id (ints, 0 = plan 0) and returns the knob list (removed from the key rows)."""
    global KNOBS
    if spec == "none":
        kn = []
    elif spec == "auto":
        kn = [c for c in extra if c in KNOB_AUTO or c.startswith("k_") or
              any(r.get(c, "") not in ("", None) and fnum(r.get(c)) is None for r in rows)]
    else:
        kn = [c for c in spec.split(",") if c]
    KNOBS = kn
    keys = sorted({(r["_p"], tuple(str(r.get(c, "")) for c in kn)) for r in rows if r["_p"] > 0})
    ARMS[:] = [(0, ())] + keys
    idx = {k: i for i, k in enumerate(ARMS)}
    for r in rows:
        r["_plan"] = r["_p"]
        r["_p"] = 0 if r["_p"] == 0 else idx[(r["_p"], tuple(str(r.get(c, "")) for c in kn))]
    for c in kn:
        if c in extra:
            extra.remove(c)
    return kn


def lab(a):
    pl, kv = ARMS[a]
    return str(pl) + "".join(f"|{c}={v}" for c, v in zip(KNOBS, kv)) if pl else "0"


def kcode(v):
    """knob value -> int for the data table: integer as is, decimal x10, letter a=1, b=2 ..., blank 0."""
    if v in ("", None):
        return 0
    if v == "all":  # wave-1 crew: the whole team pushes
        return 9
    f = fnum(v)
    if f is None:
        return ord(v.strip().lower()[0]) - ord("a") + 1
    return int(f) if f == int(f) else int(round(f * 10))


def prior(t, p):
    p = ARMS[p][0] if 0 <= p < len(ARMS) else p
    if p == 0:
        return "-"
    if p == 20:
        return "n/a (plan 0 + split/flex, wave B)"
    if p >= 300:
        return "n/a (VP v2)"
    if p >= 100:
        return "n/a (VP v1 value program)"
    if p not in (1, 2, 3, 5, 6, 7, 8):
        return "n/a (no prior label)"
    if p == 8:
        return "n/a (carry area denial; prior has no label)"
    if p in (5, 6):
        return "n/a (steal option; prior has no label)"
    if p == 7:
        return "AGREES (gem-richer from the start: no OG/- opening)" if t != 1 else "AGREES (own gems if richer)"
    if p == 1:
        return "AGAINST (OG/- worst)"
    if p == 3:
        return "AGAINST (HEAVY-DOM: own gems OM/- best)" if t == 1 else "AGREES (forward /F)"
    return "AGREES (own gems on HEAVY-DOM)" if t == 1 else "NEUTRAL (OG then OM or C)"



def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load(pattern):
    files = sorted(glob.glob(pattern))
    if not files and pattern.endswith("chunk_*.tsv"):
        files = sorted(glob.glob(os.path.join(os.path.dirname(pattern), "all.tsv")))
    rows, seen, extra = [], set(), []
    for f in files:
        with open(f) as fh:
            hdr = None
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if not parts or not parts[0]:
                    continue
                if parts[0] == "map":
                    hdr = parts
                    for c in parts:
                        if c not in CORE and c not in extra:
                            extra.append(c)
                    continue
                if hdr is None:
                    continue
                r = dict(zip(hdr, parts))
                mm = re.search(r"chunk_(\d+)", os.path.basename(f))
                r["_chunk"] = int(mm.group(1)) if mm else 0
                pl = fnum(r.get("plan"))
                # b2392 wave B (chunks 71-82): plan 0 with split > 0 or flex 1 is NOT live -> arm plan 10 ('plan 0 + split/flex');
                # only plan 0 with split 0 and flex 0 stays the null
                if 71 <= r["_chunk"] <= 82 and pl == 0 and (str(r.get("split", "")).strip() not in ("", "0") or str(r.get("flex", "")).strip() == "1"):
                    r["plan"] = "20"  # (was 10; set 3 uses 10 = PURE FARM)
                    pl = 20.0
                # b2392 SET 3 (chunks 131-154): plans are VALUE PROGRAMS reusing ids 1,2,3,5,7,9 (+10 pure farm, 11 top-3 route):
                # recoded to 100 + id so they never pool with the earlier families; plan 0 stays the null
                # b2392: 201-224 = set 3 again (VP v1, same bot family); 162-172 = plan 12 batch on the VP v1 base -> 100 + id;
                # 301-324 = VP v2 (factors on live's schedule) -> 300 + id
                c_ = r["_chunk"]
                if pl is not None and pl > 0 and (131 <= c_ <= 154 or 162 <= c_ <= 172 or 201 <= c_ <= 224):
                    pl = 100.0 + pl
                    r["plan"] = str(int(pl))
                elif pl is not None and pl > 0 and 301 <= c_ <= 324:
                    pl = 300.0 + pl
                    r["plan"] = str(int(pl))
                # b2392 13 Nov: wave-1 files (no crew/trig columns) pushed with the WHOLE team at the first tribute: crew 'all', trig 0
                # (chunks 04-08 carry the later columns BLANK; wave-3 plans 1-3 always fill crew 3/4, so blank = wave 1)
                if pl in (1, 2, 3) and r.get("crew", "") == "":
                    r["crew"] = "9"  # wave 1 whole team = the 12k wave's crew 9
                if pl in (1, 2, 3) and r.get("trig", "") == "":  # plan 3 before the 12k wave pushed from the start = trig 0
                    r["trig"] = "0"
                if pl == 8:  # b2392 wave 4: push_r means nothing for plan 8 (its trig is its own: 0 power >= 1.2x, 1 >= 1.5x, 2 foe trib >= 650)
                    r["push_r"] = ""
                key = (r.get("map"), r.get("seat"))
                if key in seen or fnum(r.get("win")) is None or fnum(r.get("plan")) is None:
                    continue
                seen.add(key)
                rows.append(r)
    return files, rows, extra


# (lo, hi, stratum): chunks 101-124 are the second 12k set (same bot as 48-64, b2392) -> same stratum as 41-70
WAVES = [(1, 8, 0), (9, 24, 1), (25, 40, 2), (41, 70, 3), (71, 82, 4), (83, 100, 5), (101, 124, 3), (125, 130, 5), (131, 154, 6),
         (155, 160, 7), (161, 172, 8), (173, 200, 9), (201, 224, 6), (225, 300, 9), (301, 324, 10), (325, 10 ** 6, 11)]  # wave B = chunks 71-82, its own stratum  # b2392: wave 1 = chunks 1-8, wave 3 = 9-14, wave 4 = 25-28, extra wave 41+


def wave_of(c):
    return next((w for lo, hi, w in WAVES if lo <= c <= hi), -1)


def wave_adjust(rows):
    """b2392 13 Nov: plan 0 read .495 in wave 4 v .468 in wave 1 (z ~1.7). Each game's win is shifted by its wave's plan-0 offset
    (wave plan-0 mean - all plan-0 mean), so a plan is compared with plan 0 net of wave-level drift; the per-type plan-0 comparison
    then runs on the shifted values. Returns {wave: (plan-0 mean, n)}."""
    by = collections.defaultdict(list)
    for r in rows:
        if fnum(r.get("plan")) == 0 and fnum(r.get("win")) is not None:
            by[wave_of(r.get("_chunk", 0))].append(fnum(r["win"]))
    allv = [x for v in by.values() for x in v]
    if not allv:
        return {}
    m_all = sum(allv) / len(allv)
    off = {w: sum(v) / len(v) - m_all for w, v in by.items()}
    for r in rows:
        w = fnum(r.get("win"))
        if w is not None:
            r["_wadj"] = w - off.get(wave_of(r.get("_chunk", 0)), 0.0)
            r["_w"] = r["_wadj"]
    return {w: (sum(v) / len(v), len(v)) for w, v in by.items()}


def mtype_of(rows, mapdir):
    need = [r for r in rows if fnum(r.get("mtype")) is None]
    if need:
        if not mapdir:
            raise SystemExit(f"gpltable: {len(need)} rows lack mtype; pass --mapdir")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import mapclass
        cache = {}
        for r in need:
            m = r["map"]
            if m not in cache:
                p = m if os.path.isabs(m) else os.path.join(mapdir, m)
                try:
                    cache[m] = mapclass.values(p, ["gpl_type"])["gpl_type"]
                except Exception:  # noqa: BLE001
                    cache[m] = None
            r["mtype"] = cache[m]
    for r in rows:
        v = fnum(r.get("mtype"))
        r["_t"] = int(v) if v is not None else None
        r["_p"] = int(fnum(r["plan"]))
        r["_w"] = r.get("_wadj", fnum(r["win"]))


def cell_stats(games):
    """games -> (mean, se, n games, n maps); SE clustered by map (ratio estimator)."""
    by = collections.defaultdict(list)
    for g in games:
        by[g["map"]].append(g["_w"])
    n = sum(len(v) for v in by.values())
    if n == 0:
        return None
    mean = sum(sum(v) for v in by.values()) / n
    k = len(by)
    if k < 2:
        return mean, float("nan"), n, k
    nbar = n / k
    var = sum((sum(v) - mean * len(v)) ** 2 for v in by.values()) * k / (k - 1) / (k * nbar) ** 2
    return mean, math.sqrt(max(var, 0.0)), n, k


NULL = ["plan0"]


def rel_cells(sel, plans, t, h=None):
    """chooser cells. NULL plan0 (default, 13 Nov: plan 0 read .475 +-.013 v live over chunks 1-6 although it should play as live; the
    diag research build is not exactly live, so each plan is judged v the plan-0 games of the same type/half): plan k -> (.5 + diff v
    plan 0, SE of the diff, games, maps); plan 0 -> (.5, 0, ..). NULL half: raw scores v .50."""
    raw = {p: cell_stats(sel(t, p, h)) for p in plans}
    if NULL[0] != "plan0":
        return raw
    s0 = raw.get(0)
    out = {}
    for p, s in raw.items():
        if s is None or s0 is None:
            out[p] = None if p else s0
            continue
        out[p] = (0.5, 0.0, s[2], s[3]) if p == 0 else (0.5 + s[0] - s0[0], math.sqrt(s[1] ** 2 + s0[1] ** 2), s[2], s[3])
    return out


def diff_stats(ga, gb):
    a, b = cell_stats(ga), cell_stats(gb)
    if not a or not b:
        return None
    return a[0] - b[0], math.sqrt(a[1] ** 2 + b[1] ** 2)


def pick_point(cells, min_maps, span):
    """POINT-ESTIMATE chooser (Planner 13 Nov): best mean among plans 1-3 if it beats .50 and plan 0's point, has >= min_maps maps and
    its CI (z 1.96) does not reach more than `span` below .50; else plan 0."""
    best = (0, None)
    p0 = cells.get(0)
    for p, s in sorted(cells.items()):
        if p == 0 or s is None or s[3] < min_maps or math.isnan(s[1]):
            continue
        if s[0] <= 0.5 or (p0 and s[0] <= p0[0]) or s[0] - 1.96 * s[1] < 0.5 - span:
            continue
        if best[1] is None or s[0] > best[1][0]:
            best = (p, s)
    return best


def pick(cells, z, min_maps):
    """cells {plan: stats} -> (plan, stats) winner or (0, None)."""
    best = (0, None)
    for p, s in sorted(cells.items()):
        if p == 0 or s is None or s[3] < min_maps or math.isnan(s[1]):
            continue
        if s[0] - z * s[1] > 0.5 and (best[1] is None or s[0] > best[1][0]):
            best = (p, s)
    return best


def half(m):
    return int(hashlib.md5(m.encode()).hexdigest(), 16) & 1


def share_from_dir(d):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mapclass
    c = collections.Counter()
    for f in glob.glob(os.path.join(d, "*")):
        try:
            t = mapclass.values(f, ["gpl_type"])["gpl_type"]
        except Exception:  # noqa: BLE001
            continue
        if t is not None:
            c[int(t)] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/data/zw4424/st/b2392/p3/chunk_*.tsv")
    ap.add_argument("--out", default="/data/zw4424/st/b2396/gpl_out")
    ap.add_argument("--z", type=float, default=1.96)
    ap.add_argument("--prefix", default="GPC")
    ap.add_argument("--min-maps", type=int, default=30)
    ap.add_argument("--mapdir", default="")
    ap.add_argument("--share-dir", default="")
    ap.add_argument("--no-wave-adjust", dest="wave_adjust", action="store_false", help="skip the per-wave plan-0 shift")
    ap.add_argument("--null", default="plan0", choices=["plan0", "half"], help="judge plans v the plan-0 games (default) or v .50")
    ap.add_argument("--knobs", default="auto", help="knob columns forming the arm with the plan: auto | none | comma list")
    ap.add_argument("--pt-min-maps", type=int, default=40)
    ap.add_argument("--pt-span", type=float, default=0.10, help="point chooser: CI lower may sit at most this far below .50")
    a = ap.parse_args()

    NULL[0] = a.null
    files, rows, extra = load(a.inp)
    if not rows:
        raise SystemExit(f"gpltable: no rows under {a.inp}")
    wav = wave_adjust(rows) if a.wave_adjust else {}
    mtype_of(rows, a.mapdir)
    untyped = sum(1 for r in rows if r["_t"] is None)
    noplan = sum(1 for r in rows if r["_p"] < 0)  # b2392 writes plan -1 when no plan was drawn (e.g. a fault/early end): dropped, counted
    rows = [r for r in rows if r["_t"] is not None and r["_p"] >= 0]
    build_arms(rows, extra, a.knobs)
    plans = sorted({r["_p"] for r in rows})
    maps_by_t = collections.defaultdict(set)
    for r in rows:
        maps_by_t[r["_t"]].add(r["map"])
    if a.share_dir:
        c = share_from_dir(a.share_dir)
        tot = sum(c.values()) or 1
        share = {t: c.get(t, 0) / tot for t in TYPES}
        share_src = f"{tot} maps in {a.share_dir}"
    else:
        tot = sum(len(v) for v in maps_by_t.values()) or 1
        share = {t: len(maps_by_t.get(t, ())) / tot for t in TYPES}
        share_src = f"{tot} distinct maps in the data"

    def gsel(t=None, p=None, h=None):
        return [r for r in rows if (t is None or r["_t"] == t) and (p is None or r["_p"] == p) and (h is None or half(r["map"]) == h)]

    def keyrow(games):
        out = []
        for c in extra:
            v = [fnum(g.get(c)) for g in games]
            v = [x for x in v if x is not None]
            out.append(f"{sum(v) / len(v):.1f} ({len(v)})" if v else "-")
        return out

    L = []
    L.append(f"# GPL P3 chooser table ({len(rows)} games, {len(files)} files; untyped dropped {untyped}, plan<0 dropped {noplan})\n")
    L.append(f"Score = research bot v live (plan 0 = live route, null arm). Chooser edges are judged v {NULL[0]} ('plan0': diff v the plan-0 games of the type). Wave plan-0 means (chunks {WAVES}): {', '.join(f'w{w}: {m:.3f} n {n}' for w, (m, n) in sorted(wav.items()))}; wins shifted by wave offset: {bool(wav)}. CI z {a.z}, clustered by map; winner needs CI lower > .50 and >= {a.min_maps} maps; else plan 0. Shares: {share_src}.\n")
    hdr = ["type", "share", "plan", "games", "maps", "score", "CI", "k - plan0"] + extra
    L.append("| " + " | ".join(hdr) + " |")
    L.append("|" + "---|" * len(hdr))
    winners, gain, gain_cv = {}, 0.0, 0.0
    ptw, gain_pt, gain_pt_cv = {}, 0.0, 0.0
    for t in sorted(TYPES):
        rawc = {p: cell_stats(gsel(t, p)) for p in plans}
        cells = rel_cells(gsel, plans, t)
        for p in plans:
            s = rawc[p]
            if s is None:
                continue
            d = diff_stats(gsel(t, p), gsel(t, 0)) if p != 0 else None
            ci = f"[{s[0] - a.z * s[1]:.3f}, {s[0] + a.z * s[1]:.3f}]" if not math.isnan(s[1]) else "-"
            ds = f"{d[0]:+.3f} +-{a.z * d[1]:.3f}" if d and not math.isnan(d[1]) else "-"
            L.append("| " + " | ".join([f"{t} {TYPES[t]}", f"{share[t]:.3f}", lab(p), str(s[2]), str(s[3]), f"{s[0]:.4f}", ci, ds] + keyrow(gsel(t, p))) + " |")
        w, ws = pick(cells, a.z, a.min_maps)
        winners[t] = (w, ws)
        ptw[t] = pick_point(cells, a.pt_min_maps, a.pt_span)
        if ptw[t][1]:
            gain_pt += share[t] * (ptw[t][1][0] - 0.5)
        for h in (0, 1):
            ph, _ = pick_point(rel_cells(gsel, plans, t, h), a.pt_min_maps // 2, a.pt_span)
            if ph:
                so = rel_cells(gsel, plans, t, 1 - h).get(ph)
                if so:
                    gain_pt_cv += 0.5 * share[t] * (so[0] - 0.5)
        if ws:
            gain += share[t] * (ws[0] - 0.5)
        # cross-validated: pick on one half, read on the other
        for h in (0, 1):
            ph, _ = pick(rel_cells(gsel, plans, t, h), a.z, a.min_maps // 2)
            if ph:
                so = rel_cells(gsel, plans, t, 1 - h).get(ph)
                if so:
                    gain_cv += 0.5 * share[t] * (so[0] - 0.5)
    L.append("")
    L.append("## Chooser (one plan per map type)\n")
    nt = len(TYPES) * max(1, len([p for p in plans if p]))
    zb = {6: 2.394, 9: 2.539, 12: 2.638, 18: 2.773, 24: 2.865}.get(nt, 2.773)  # two-sided .05 / nt
    L.append(f"| type | share | plan | edge v live | clears Bonferroni z {zb} ({nt} tests) | Deep prior |")
    L.append("|---|---|---|---|---|---|")
    for t in sorted(TYPES):
        w, ws = winners[t]
        L.append(f"| {t} {TYPES[t]} | {share[t]:.3f} | {lab(w)} | {('%+.4f' % (ws[0] - 0.5)) if ws else '0 (live route)'} | {('yes' if ws[0] - zb * ws[1] > 0.5 else 'no') if ws else '-'} | {prior(t, w)} |")
    L.append("")
    L.append(f"## Chooser B: POINT-ESTIMATE (best mean plan per type, > .50 and > plan 0; live where maps < {a.pt_min_maps} or CI lower < {0.5 - a.pt_span:.2f})\n")
    L.append("| type | share | plan | edge v live | maps | CI | Deep prior |")
    L.append("|---|---|---|---|---|---|---|")
    for t in sorted(TYPES):
        w, ws = ptw[t]
        L.append(f"| {t} {TYPES[t]} | {share[t]:.3f} | {lab(w)} | {('%+.4f' % (ws[0] - 0.5)) if ws else '0 (live route)'} | {ws[3] if ws else '-'} | {('[%.3f, %.3f]' % (ws[0] - 1.96 * ws[1], ws[0] + 1.96 * ws[1])) if ws else '-'} | {prior(t, w)} |")
    L.append("")
    L.append(f"POINT chooser: REALISTIC (cross-validated) gain {gain_pt_cv:+.4f}; in-sample {gain_pt:+.4f}.")
    pooled = cell_stats(rows)
    L.append("")
    L.append(f"REALISTIC projected chooser gain (cross-validated: pick on one map half, read on the other): {gain_cv:+.4f}; in-sample sum share x winner edge (optimistic): {gain:+.4f}. Picks marked 'no' in the Bonferroni column are weaker candidates; the played short read decides.")
    L.append(f"Context only (owner A22: no plan is judged pooled): all games {pooled[0]:.4f} n {pooled[2]}; per plan (plan 0 = null arm) " +
             ", ".join(f"{lab(p)}: {cell_stats(gsel(p=p))[0]:.4f} n {cell_stats(gsel(p=p))[2]}" for p in plans if cell_stats(gsel(p=p))) + ".")
    if KNOBS:  # marginal knob table: per type x plan x one knob value (pools the other knobs; valid under randomisation)
        L.append("\n## Knob marginals (type x plan x knob value; score v live; context for the arm picks)\n")
        L.append("| type | plan | knob | value | games | maps | score | CI |")
        L.append("|---|---|---|---|---|---|---|---|")
        for t in sorted(TYPES):
            for pl in sorted({r["_plan"] for r in rows if r["_plan"] > 0}):
                for ci_, c in enumerate(KNOBS):
                    for v in sorted({ARMS[r["_p"]][1][ci_] for r in rows if r["_plan"] == pl}):
                        gs = [r for r in rows if r["_t"] == t and r["_plan"] == pl and ARMS[r["_p"]][1][ci_] == v]
                        st = cell_stats(gs)
                        if st:
                            ci = f"[{st[0] - a.z * st[1]:.3f}, {st[0] + a.z * st[1]:.3f}]" if not math.isnan(st[1]) else "-"
                            L.append(f"| {t} {TYPES[t]} | {pl} | {c} | {v} | {st[2]} | {st[3]} | {st[0]:.4f} | {ci} |")
    md = "\n".join(L) + "\n"

    os.makedirs(a.out, exist_ok=True)
    P = a.prefix
    def fl(win):
        out = []
        for t in sorted(TYPES):
            pl, kv = ARMS[win[t][0]]
            out.append(f"{P}_T{t}={pl}")
            out += [f"{P}_K{t}_{c.upper()}={kcode(v) if pl else 0}" for c, v in zip(KNOBS, kv or [""] * len(KNOBS))]
        return " ".join(out)
    flips, flips_pt = fl(winners), fl(ptw)
    h = [f"// {P} chooser table (gpltable.py, b2396): plan id per gpl_type (slot t = type t, 1 HEAVY-DOM .. 6 UNIFORM); 0 = live route.",
         f"// Projected gain {gain:+.4f} (cv {gain_cv:+.4f}) from {len(rows)} P3 games. Flip: {flips}"]
    names = [x.split("=")[0] for x in flips.split()]
    if KNOBS:
        h.append(f"// knobs per type: {', '.join(KNOBS)}; codes: integer as is, decimal x10, letter a=1 b=2 ..; crew 'all' (whole team) = 9; 0 = unused")
    for x in flips.split():
        k, v = x.split("=")
        h.append(f"#define {k} {v}")
    if KNOBS:
        h.append(f"inline const volatile int {P}_TAB[{len(names) + 2}] = {{ 0x{int.from_bytes(P[:3].ljust(3, '_').encode(), 'big'):06X}4B, "
                 + ", ".join(names) + ", 0 }; // slot 0 magic; per type: plan then each knob; last slot spare")
    else:
        h.append(f"inline const volatile int {P}_TAB[8] = {{ 0x{int.from_bytes(P[:3].ljust(3, '_').encode(), 'big'):06X}43, "
                 + ", ".join(names) + ", 0 }; // slot 0 magic; slot 7 spare")
    with open(os.path.join(a.out, "table.md"), "w") as f:
        f.write(md)
    with open(os.path.join(a.out, "chooser.h"), "w") as f:
        f.write("\n".join(h) + "\n")
    with open(os.path.join(a.out, "chooser.tsv"), "w") as f:
        f.write("type\tname\tplan\tshare\tedge\tmaps\n")
        for t in sorted(TYPES):
            w, ws = winners[t]
            f.write(f"{t}\t{TYPES[t]}\t{lab(w)}\t{share[t]:.4f}\t{(ws[0] - 0.5) if ws else 0:.4f}\t{ws[3] if ws else 0}\n")
    with open(os.path.join(a.out, "flips.txt"), "w") as f:
        f.write(f"STRICT\t{flips}\tcv {gain_cv:+.4f}\nPOINT\t{flips_pt}\tcv {gain_pt_cv:+.4f}\n")
    for nm, fl in (("flips_strict.txt", flips), ("flips_point.txt", flips_pt)):
        with open(os.path.join(a.out, nm), "w") as f:
            f.write(fl + "\n")
    print(md)
    print("\n".join(h))
    print(f"STRICT flips: {flips}\nPOINT  flips: {flips_pt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
