#!/usr/bin/env python3
"""mpairs: matched win/loss pairs for a per-game metric, in one call (Tool Builder, 10 Nov; analysts kept hand-rolling it).

Games come from /data/zw4424/st/gameindex.tsv (columns id path our_seat version foe map result lane created dup_key form) and load
through gamesum (stored games, ~15 ms each; a game not stored yet is decoded through replay.load unless --no-decode). A stratum is
one value of --key (default map,foe,seat,lineup: same map, same foe team, same seat of ours, same foe lineup = the foe's drafted
champion types as a sorted tuple). A stratum with at least one win and one loss gives one pair:
  --pair mean (default)  W - L = mean(metric over the stratum's wins) - mean(metric over its losses); one pair per stratum
                         (Econ's 18:00Z rule).
  --pair one             wins and losses each sorted by match id (time), zipped one-to-one; the surplus side is dropped.
Output: matched n, then drops counted per reason (rows: not W/L, seat unknown, byte-identical re-play when deduped, no replay on
disk, not stored with --no-decode, load error; strata: wins only, losses only, a side lost to unloadable replays; per metric: a
metric that returned None or raised), then per metric the mean of W - L over pairs with a 95% CI:
  --ci t (default)  mean +- t(0.975, n-1) * sd/sqrt(n)
  --ci z            mean +- 1.96 * sd/sqrt(n)              (what Econ's 18:00Z read used)
  --ci boot         percentile bootstrap over pairs, 10,000 resamples, seed 1
Dedup (default on, gameindex --dedup semantics): ids sharing a dup_key are one game; the first id is kept. --no-dedup counts
every id (Econ's 18:00Z read did not dedup; the top-3 lane re-plays maps deterministically, so duplicates are common).

Built-in metrics (N = round; 'foe_' prefix = the same quantity for the foe team):
  banked_by_rN    gems tributed by the team in rounds <= N (sum of 'tribute' events' e[4], the score gain)
  captured_by_rN  gems gained from the team's completed captures in rounds <= N (sum of each 'capture' event's gain[i][2])
  earned_by_rN    sum over the team's champions of their 'earned' turn column at their last turn <= N (cumulative gold)
  deaths_by_rN    the team's champion deaths in rounds <= N ('death' events whose victim is on the team)
  score           final score (sum of the team's tribute gems over the whole game)
Custom: --expr 'NAME=lambda g: ...' (or a bare lambda, named exprK). In the lambda: g (replay.Game / gamesum.SumGame, g.us = our
team 0/1, g.row = gameindex row), and helpers banked(g, team, r), captured(g, team, r), earned(g, team, r), deaths(g, team, r),
R (replay module), np. Return a number or None (None = excluded for that metric, counted as a drop).

usage:
  python3 -I tools/lab/mpairs.py METRIC... [--expr 'NAME=lambda g: ...'] [--since vNNN] [--until vNNN] [--lane L[,L]]
         [--foe F[,F]] [--key map,foe,seat,lineup] [--pair mean|one] [--ci t|z|boot] [--before ISO] [--no-dedup] [--no-decode]
         [--asof ISO] [--pairs-out FILE.tsv]
  --foe: comma list, each a case-insensitive substring of gameindex's foe (e.g. Mite,SBG,Fish).
  --pairs-out: one row per pair (stratum key, nW, nL, ids, each metric's W, L and W-L).
example (Econ 18:00Z bank-timing read, reproduced to the decimal):
  python3 -I tools/lab/mpairs.py banked_by_r100 banked_by_r200 captured_by_r100 foe_banked_by_r200 \\
      --since v695 --lane top3 --key map,foe --no-dedup --ci z --asof 2026-11-10T17:59:30Z
  -> 84 pairs, 17 strata dropped (a side had no replay on disk yet); -2.4 [-6.0,+1.1]  +0.9 [-8.4,+10.2]  +2.7 [-2.3,+7.7]  -18.3 [-31.8,-4.9]
"""
import argparse
import collections
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamesum as GS  # noqa: E402
import replay as R  # noqa: E402


# ---------------------------------------------------------------- metric helpers
def banked(g, team, r):
    return sum(e[4] for e in g.events if e[1] == "tribute" and e[3] == team and e[0] <= r)


def captured(g, team, r):
    return sum(sum(x[2] for x in e[4]) for e in g.events if e[1] == "capture" and e[3] == team and e[0] <= r)


def deaths(g, team, r):
    return sum(1 for e in g.events if e[1] == "death" and e[0] <= r and g.team_of.get(e[2]) == team)


def earned(g, team, r):
    tot = 0
    for b, t in g.team_of.items():
        if t != team:
            continue
        if hasattr(g, "series"):
            rr, ee = g.series(b, "r"), g.series(b, "earned")
            m = rr <= r
            if m.any():
                tot += int(ee[m][-1])
        else:
            last = None
            for t_ in g.by_champ.get(b, []):
                if t_[g.ci["r"]] <= r:
                    last = t_[g.ci["earned"]]
            tot += last or 0
    return tot


BASE = {"banked": banked, "captured": captured, "earned": earned, "deaths": deaths}


def builtin(name):
    foe = name.startswith("foe_")
    n = name[4:] if foe else name
    if n == "score":
        return lambda g: banked(g, 1 - g.us if foe else g.us, 10 ** 9)
    if "_by_r" in n:
        k, r = n.split("_by_r", 1)
        if k in BASE and r.isdigit():
            f, r = BASE[k], int(r)
            return lambda g: f(g, 1 - g.us if foe else g.us, r)
    raise SystemExit(f"mpairs: unknown metric {name!r} (banked|captured|earned|deaths _by_rN, score; foe_ prefix; or --expr)")


def custom(spec, k):
    name, src = (spec.split("=", 1) if "=" in spec.split("lambda", 1)[0] else (f"expr{k}", spec))
    env = {"banked": banked, "captured": captured, "earned": earned, "deaths": deaths, "R": R, "np": np}
    return name.strip(), eval(src.strip(), env)  # noqa: S307 - analyst-supplied lambda, by design


# ---------------------------------------------------------------- statistics
def t975(df):
    try:
        from scipy.stats import t
        return float(t.ppf(0.975, df))
    except Exception:  # noqa: BLE001
        return 1.96 + 2.4 / df  # close enough above df 10


def ci(v, how):
    v = np.asarray(v, float)
    n = len(v)
    m = float(v.mean()) if n else float("nan")
    if n < 2:
        return m, float("nan"), float("nan")
    if how == "boot":
        rng = np.random.default_rng(1)
        bm = v[rng.integers(0, n, size=(10000, n))].mean(axis=1)
        return m, float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))
    se = float(v.std(ddof=1)) / math.sqrt(n)
    q = 1.96 if how == "z" else t975(n - 1)
    return m, m - q * se, m + q * se


# ---------------------------------------------------------------- main
def _iso_ts(s):
    import datetime
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _first_mtime(r):
    """earliest mtime of the game's replay copies (gameindex path; for an extracted x_<id>/ copy also its sibling <id>.zip)"""
    p = r["path"]
    cand = [p]
    d = os.path.dirname(p)
    if os.path.basename(d).startswith("x_"):
        cand.append(os.path.join(os.path.dirname(d), r["id"] + ".zip"))
    ts = [os.path.getmtime(c) for c in cand if os.path.exists(c)]
    return min(ts) if ts else float("inf")


def lineup(g):
    try:
        return tuple(sorted(g.d["draft"][1 - g.us]))
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("metrics", nargs="*")
    ap.add_argument("--expr", action="append", default=[])
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--lane")
    ap.add_argument("--foe")
    ap.add_argument("--key", default="map,foe,seat,lineup")
    ap.add_argument("--pair", choices=("mean", "one"), default="mean")
    ap.add_argument("--ci", choices=("t", "z", "boot"), default="t")
    ap.add_argument("--before", help="only games created (UUIDv7 time) at or before this UTC ISO stamp")
    ap.add_argument("--asof", help="reproduce a read made at this UTC ISO stamp: --before plus 'no replay' for games whose replay "
                    "file (or its zip) appeared on disk later")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--no-decode", action="store_true")
    ap.add_argument("--pairs-out")
    a = ap.parse_args()
    t0 = time.time()
    M = [(m, builtin(m)) for m in a.metrics] + [custom(s, k) for k, s in enumerate(a.expr, 1)]
    if not M:
        raise SystemExit("mpairs: give at least one metric")
    keyf = [k.strip() for k in a.key.split(",") if k.strip()]
    bad = set(keyf) - {"map", "foe", "seat", "lineup", "version"}
    if bad:
        raise SystemExit(f"mpairs: unknown key part(s) {sorted(bad)}")
    lanes = set(a.lane.split(",")) if a.lane else None
    foes = [f.lower().replace("_", " ") for f in a.foe.split(",")] if a.foe else None
    if a.asof:
        a.before = a.before or a.asof
        asof_ts = _iso_ts(a.asof)
    lo = GS._vnum(a.since) if a.since else -1
    hi = GS._vnum(a.until) if a.until else 10 ** 9

    drop = collections.Counter()
    seen = set()
    sel = []
    for r in GS._index()["rows"]:
        v = GS._vnum(r["version"])
        if v < lo or v > hi or (lanes and r["lane"] not in lanes):
            continue
        if foes and not any(f in r["foe"].lower().replace("_", " ") for f in foes):
            continue
        if a.before and r["created"] > a.before:
            continue
        if r["result"] not in ("win", "loss"):
            drop["row: result not win/loss"] += 1
            continue
        if r["our_seat"] not in ("a", "b"):
            drop["row: our seat unknown"] += 1
            continue
        if not a.no_dedup and r["dup_key"] not in ("", "-"):
            if r["dup_key"] in seen:
                drop["row: byte-identical re-play (dedup)"] += 1
                continue
            seen.add(r["dup_key"])
        sel.append(r)

    # strata by index columns first (lineup needs the game), so 'side lost to missing replays' is countable
    def ikey(r):
        return tuple(r["map"] if k == "map" else r["foe"] if k == "foe" else r["our_seat"] if k == "seat"
                     else r["version"] for k in keyf if k != "lineup")

    pre = collections.defaultdict(list)
    for r in sel:
        pre[ikey(r)].append(r)
    games = []  # (row, key, values)
    for k, rs in pre.items():
        res = {r["result"] for r in rs}
        if res != {"win", "loss"}:
            drop["stratum: wins only" if res == {"win"} else "stratum: losses only"] += 1
            continue
        for r in rs:
            g = None
            if r["form"] not in ("replay", "zip") or r["dup_key"] in ("", "-"):
                drop["game: no replay on disk"] += 1
            elif a.asof and _first_mtime(r) > asof_ts:
                drop["game: replay not on disk at --asof"] += 1
            else:
                p = GS.fname(r["dup_key"])
                try:
                    if os.path.exists(p):
                        g = GS.game_from(GS._read(p), r)
                    elif not a.no_decode:
                        g = R.load(r["path"], us=r["our_seat"].upper())
                        g.gid, g.row = r["id"], r
                    else:
                        drop["game: not stored (--no-decode)"] += 1
                except Exception:  # noqa: BLE001
                    drop["game: load error"] += 1
                    g = None
            if g is None:
                continue
            vals = {}
            for name, f in M:
                try:
                    x = f(g)
                except Exception:  # noqa: BLE001
                    x = None
                vals[name] = None if x is None else float(x)
            key = k + ((lineup(g),) if "lineup" in keyf else ())
            games.append((r, key, vals, k))
            del g

    strata = collections.defaultdict(lambda: {"win": [], "loss": []})
    for r, key, vals, k in games:
        strata[key][r["result"]].append((r["id"], vals))
    # an index stratum that had both results but lost a side entirely to loading
    have = collections.defaultdict(set)
    for r, key, vals, k in games:
        have[k].add(r["result"])
    for k, rs in pre.items():
        if {r["result"] for r in rs} == {"win", "loss"} and have.get(k) != {"win", "loss"}:
            drop["stratum: a side has no loadable replay"] += 1
    pairs = []  # (key, W ids, L ids, {metric: (w, l)})
    for key, s in strata.items():
        W, L = sorted(s["win"]), sorted(s["loss"])
        if not W or not L:
            if "lineup" in keyf and have.get(key[:-1]) == {"win", "loss"}:
                drop["stratum: lineup split left one side"] += 1
            continue
        if a.pair == "one":
            for (wi, wv), (li, lv) in zip(W, L):
                pairs.append((key, [wi], [li], {n: (wv[n], lv[n]) for n, _ in M}))
            if len(W) != len(L):
                drop["game: unpaired surplus (--pair one)"] += abs(len(W) - len(L))
        else:
            d = {}
            for n, _ in M:
                wv = [v[n] for _, v in W if v[n] is not None]
                lv = [v[n] for _, v in L if v[n] is not None]
                d[n] = (sum(wv) / len(wv), sum(lv) / len(lv)) if wv and lv else (None, None)
            pairs.append((key, [i for i, _ in W], [i for i, _ in L], d))

    print(f"mpairs: key {','.join(keyf)}, pair {a.pair}, CI {a.ci}{' (percentile bootstrap, 10k)' if a.ci == 'boot' else ''}, "
          f"dedup {'off' if a.no_dedup else 'on'}; rows selected {len(sel)}, games loaded {len(games)}")
    print(f"matched pairs: {len(pairs)}")
    for why, n in sorted(drop.items()):
        print(f"  dropped {why}: {n}")
    print(f"{'metric':28s} {'n':>4s} {'W mean':>8s} {'L mean':>8s} {'W-L':>8s}  95% CI")
    for n, _ in M:
        dv = [(w, l) for _, _, _, d in pairs for (w, l) in [d[n]] if w is not None and l is not None]
        nd = len(pairs) - len(dv)
        if not dv:
            print(f"{n:28s} {0:4d}")
            continue
        m, lo_, hi_ = ci([w - l for w, l in dv], a.ci)
        wm, lm = np.mean([w for w, _ in dv]), np.mean([l for _, l in dv])
        extra = f"   ({nd} pairs without a value)" if nd else ""
        print(f"{n:28s} {len(dv):4d} {wm:8.1f} {lm:8.1f} {m:+8.1f}  [{lo_:+.1f}, {hi_:+.1f}]{extra}")
    if a.pairs_out:
        with open(a.pairs_out, "w") as f:
            f.write("\t".join(["key", "nW", "nL", "win_ids", "loss_ids"] + [f"{n}_{x}" for n, _ in M for x in ("W", "L", "WmL")]) + "\n")
            for key, wi, li, d in pairs:
                cells = []
                for n, _ in M:
                    w, l = d[n]
                    cells += ["" if w is None else f"{w:g}", "" if l is None else f"{l:g}",
                              "" if w is None or l is None else f"{w - l:g}"]
                f.write("\t".join(["|".join(map(str, key)), str(len(wi)), str(len(li)), ",".join(wi), ",".join(li)] + cells) + "\n")
    print(f"runtime {time.time() - t0:.1f} s", file=sys.stderr)


if __name__ == "__main__":
    main()
