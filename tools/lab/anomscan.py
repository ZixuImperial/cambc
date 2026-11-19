#!/usr/bin/env python3
"""anomscan: the automatic ANOMALY SCAN of a live version's games, one ranked table. Tool builder, 30 Oct (Builder: the most
productive bug source today was replay review; livepipe runs this on every new live set).

usage: python3 -I tools/lab/anomscan.py SETDIR... [--out FILE.md] [--jobs 12] [--top 3]
  SETDIR: live-set dirs (matches.txt 'ID map seat result opp' + x_ID/replay.repl26a), e.g. /data/zw4424/plat/unr_v306.
First `replay.py warm SETDIR... --jobs N` (decoded replays are cached; a read is then ~0.15 s), then per game, 12 at a time,
every reader below on both sides. Per class: ours per game, opponents per game, z of the per-game difference (ours - theirs,
paired by game), the deaths / gems lost the class carries (where it has them), and the 3 games where ours is worst (id,
map, example rounds). Sorted by z, highest first: ours > theirs at z >= 2 is a CANDIDATE BUG for the analysts to walk first.
Readers (their own rule each, unchanged; the Combat scripts are flat, so their rule is restated here, cited):
  qa2.py (cambc-07, tools/lab; recalls follow replay.chosen_channel since 2 Nov; qa.py counted a captured group's camps alive until respawn): stuck, loop2, idle-with-target, nobank, deadlock rounds, fuel exhaustions, faults
  hidbush.py (07): hits from hidden bushes, episodes of >= 3 rounds suffered, deaths and gems in them
  wronggate2.py (07's wronggate.py + qa2's capture fix for gate camps): >= 5 turns at a closed gate of an altar with an open one, carrying >= 50 gems
  yieldwait (Econ's yieldwait.py rule, ported 3 Nov): idle body-rounds by own Prism's group with no foe within 8, minus turns in a
    channel (a kept recall, replay.kept_recall, or any other channel). Compared per TEAM-GAME WITH A PRISM (Welch z over those
    team-games, >= 5 each side), since a team without a Prism scores 0 by definition (Builder 3 Nov: v458-v461 flagged on that alone)
  nobank (qa2's rule, ported 3 Nov): a bag >= 100 held >= 300 alive rounds with no tribute, NON-PRISM bodies only: Prism keeps her
    bag by the owner's PC_OWNER_BANK rule, so her holds flagged every digest (Builder 3 Nov)
  killgold.py (Econ): DENIABLE deaths with no foe within 8 (a recall started 6-15 rounds before would have completed), bag lost
  rallyflee.py (Combat, /data/zw4424/st/combat_py): a FLEE move (our priority-40 marker, so OURS ONLY: no z) toward react_rally's
    pick that has >= 2 foes within 4, ending closer to the nearest foe; deaths within 6 rounds
  hordash.py (Combat): a Heart of Ruin camp dash (cast hits camps, no champion) with >= 2 foes within 10; dasher deaths <= 10 r
  rundown.py (Combat): a death whose victim moved in each of its last 4 rounds with the killer within 2 each round
  deathclass.py RECALL (Combat): a death while channelling a recall (that round or the one before)
Not included: fleedir2.py (a direction profile, not a per-game anomaly count).
"""
import collections
import importlib.util
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

LAB = "/homes/zw4424/cambc/tools/lab"
sys.path.insert(0, LAB)
SRC = {"qa": LAB + "/qa2.py", "hidbush": "/data/zw4424/st/bugx/hidbush.py",
       "wronggate": "/data/zw4424/st/bugx/wronggate2.py",
       "killgold": "/homes/zw4424/condor-work/reports/econ/killgold.py"}
_M = {}
# class -> (label, reader, ours only?)
CLASSES = [
    ("stuck", "stuck >= 20 turns on one tile (qa)"), ("hold", "spin hold >= 20 turns: full HP, no move, income or hits (qa)"), ("loop2", "2-tile loop >= 20 rounds (qa)"),
    ("idlet", "idle >= 10 turns with a target in reach (qa)"), ("nobank", "non-Prism bag >= 100 held >= 300 rounds"),
    ("dlock", "deadlock rounds, >= 3 bodies idle >= 20 (qa)"), ("fuel", "fuel-exhausted turns (qa)"),
    ("fault", "bot faults (qa)"), ("hidhit", "hidden-bush hit episodes suffered (hidbush)"),
    ("wronggate", "wrong-gate episodes with >= 50 gems (wronggate)"),
    ("yieldwait", "idle unchannelled body-rounds by own Prism's group, safe, per team-game with a Prism (yieldwait)"),
    ("deniable", "deniable deaths, no foe within 8 (killgold)"), ("hordash", "HoR camp dash with >= 2 foes within 10 (hordash)"),
    ("rundown", "run-down deaths (rundown)"), ("recalldeath", "deaths while recalling (deathclass RECALL)"),
    ("rallyflee", "FLEE step toward an endangered rally ally (rallyflee; ours only)"),
]
OURS_ONLY = {"rallyflee"}
PRISM_ONLY = {"yieldwait"}  # compared over team-games that field a Prism (Welch), not paired by game


def mod(name):
    if name not in _M:
        sp = importlib.util.spec_from_file_location("anom_" + name, SRC[name])
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _M[name] = m
    return _M[name]


def cheb(a, b):
    return max(abs(a[2] - b[2]), abs(a[3] - b[3]))


def ported(g, R):
    """rallyflee / hordash / rundown / recall deaths -> {class: [per side: (count, deaths, gems, [rounds])]}."""
    ci, tm = g.ci, g.team_of
    out = {k: [[0, 0, 0, []], [0, 0, 0, []]] for k in ("rallyflee", "hordash", "rundown", "recalldeath", "yieldwait", "nobank")}
    S = collections.defaultdict(dict)
    T = {}
    for t in g.turns:
        T[(t[0], t[1])] = t
        if t[ci["alive"]]:
            S[t[0]][t[1]] = t
    deaths = [e for e in g.events if e[1] == "death"]
    dl = {(e[2], e[0]) for e in deaths}
    # rallyflee (ours only: priority markers are ours)
    us = g.us
    cur = {}
    for t in sorted((t for t in g.turns if tm.get(t[1]) == us), key=lambda t: t[0]):
        for x in t[-1]:
            if x[0] == "p":
                cur[t[1]] = x[1]
        r, b = t[0], t[1]
        if cur.get(b) != 40 or not t[ci["alive"]] or not any(x[0] == "m" for x in t[-1]):
            continue
        nx = S[r + 1].get(b)
        foes = [f for o, f in S[r].items() if tm[o] != us]
        if not nx or not foes or min(cheb(t, f) for f in foes) > 6:
            continue
        allies = [(cheb(t, a), a) for o, a in S[r].items() if tm[o] == us and o != b and a[ci["hp"]] > 0.3 * a[ci["maxHp"]]
                  and not R.real_channel(ci, a, S[r - 1].get(o))]
        allies = [x for x in allies if 2 <= x[0] < 13]
        if allies:
            al = min(allies, key=lambda x: x[0])[1]
            if sum(1 for f in foes if cheb(al, f) <= 4) >= 2 and min(cheb(nx, f) for f in foes) < min(cheb(t, f) for f in foes):
                o = out["rallyflee"][us]
                o[0] += 1
                o[1] += any((b, q) in dl for q in range(r, r + 7))
                o[3].append(r)
    # hordash, both sides
    for b in [x for x in tm if "heart_of_ruin" in g.who(x)]:
        s = tm[b]
        for t in g.by_champ.get(b, []):
            if not t[ci["alive"]]:
                continue
            casts = [x for x in t[-1] if x[0] == "c" and len(x) > 7 and x[7]]
            if not casts or R.hostile_hits(g, t) or not any(k == 2 for x in casts for k, c, d in x[7]):
                continue
            r = t[0]
            if sum(1 for o, f in S[r].items() if tm[o] != s and cheb(f, t) <= 10) >= 2:
                o = out["hordash"][s]
                o[0] += 1
                o[1] += any((b, q) in dl for q in range(r, r + 11))
                o[3].append(r)
    # rundown and recall deaths, both sides
    for e in deaths:
        r, v = e[0], e[2]
        if v not in tm:
            continue
        s = tm[v]
        bag = e[5] if len(e) > 5 and isinstance(e[5], (int, float)) else 0
        if len(e) > 4 and e[3] == 1 and e[4] in tm:
            ok = True
            for q in range(r - 4, r):
                a, k = T.get((q, v)), T.get((q, e[4]))
                if not a or not k or not any(x[0] == "m" for x in a[-1]) or cheb(a, k) > 2:
                    ok = False
                    break
            if ok:
                o = out["rundown"][s]
                o[0] += 1
                o[1] += 1
                o[2] += bag
                o[3].append(r)
        tv = g.by_champ.get(v, [])
        if R.chosen_channel(g, tv, r) == 1 or R.chosen_channel(g, tv, r + 1) == 1:  # 1 Nov (Combat): a KEPT recall at r-1 or r;
            # since SPIN_SELF (v383) ~84% of turns end in a lazy recall restarted every turn, which the raw chType test counted
            o = out["recalldeath"][s]
            o[0] += 1
            o[1] += 1
            o[2] += bag
            o[3].append(r)
    prism = {b for b in tm if g.bodies[b]["name"] == "prism"}
    # nobank (qa2's rule) on non-Prism bodies: >= 300 consecutive alive rounds with a bag >= 100 and no tribute channel
    for b, ts in g.by_champ.items():
        if b in prism or b not in tm:
            continue
        run = []
        for t in ts + [None]:
            if t is not None and t[ci["alive"]] and t[ci["gems"]] >= 100 and t[ci["chType"]] != 2:
                run.append(t[0])
                continue
            if len(run) >= 300:
                o = out["nobank"][tm[b]]
                o[0] += 1
                o[3].append(run[0])
            run = []
    # yieldwait (Econ's rule) minus channelled turns: a non-Prism mate idle (no m/a/c/s/t) within 2 of the group whose tile its own Prism
    # stands on, off the group's camp tiles, no foe within 8 of the group
    tiles = {}
    for k, v in g.groups.items():
        for c in v["camps"]:
            if c in g.camps:
                tiles[(g.camps[c]["x"], g.camps[c]["y"])] = k
    gt = collections.defaultdict(list)
    for p, k in tiles.items():
        gt[k].append(p)
    nxt = {(a[0], a[1]): z for ts in g.by_champ.values() for a, z in zip(ts, ts[1:])}
    for r, P in S.items():
        for pb, pt in P.items():
            if pb not in prism or (pt[2], pt[3]) not in tiles:
                continue
            s, k = tm[pb], tiles[(pt[2], pt[3])]
            if any(tm[o] != s and min(max(abs(q[2] - x), abs(q[3] - y)) for x, y in gt[k]) <= 8 for o, q in P.items()):
                continue
            for b, t in P.items():
                if b == pb or tm[b] != s or (t[2], t[3]) in tiles or any(a[0] in ("m", "a", "c", "s", "t") for a in t[-1]):
                    continue
                if t[ci["chType"]] in (2, 3, 4, 5) or R.kept_recall(ci, t, nxt.get((r, b))):
                    continue
                if min(max(abs(t[2] - x), abs(t[3] - y)) for x, y in gt[k]) <= 2:
                    o = out["yieldwait"][s]
                    o[0] += 1
                    if len(o[3]) < 3 and r - 1 not in o[3]:
                        o[3].append(r)
    out["has_prism"] = [any(tm[b] == s for b in prism) for s in (0, 1)]
    return out


def one(job):
    """One game -> dict(id, map, us, res: {class: [ours, theirs]} with (count, deaths, gems, rounds)) or dict(id, err)."""
    sd, gid, mp, seat = job
    import replay as R
    rep = os.path.join(sd, "x_" + gid, "replay.repl26a")
    us = 0 if seat == "a" else 1
    side = "AB"[us]  # replay.load wants 'A' / 'B' (an int 0 falls through to its default, 1 raises)
    res = {k: [[0, 0, 0, []], [0, 0, 0, []]] for k, _ in CLASSES}
    errs = []
    has_prism = [False, False]
    try:
        g = R.load(rep, us=side)
    except Exception as e:  # noqa: BLE001
        return dict(id=gid, err=f"load: {e!r}"[:120])
    try:
        pr = ported(g, R)
        has_prism = pr.pop("has_prism")
        for k, v in pr.items():
            res[k] = v
    except Exception as e:  # noqa: BLE001
        errs.append(f"ported {e!r}"[:80])
    row = dict(mid=gid, set=os.path.basename(sd), seat=side, v="", win=True, map=mp)
    try:
        for x in mod("qa").scan(rep, side, row):
            s = us if x["cand"] else 1 - us
            m, ex = x["m"], x.get("ex", {})
            for k in ("stuck", "hold", "loop2", "idlet"):
                res[k][s][0] = m.get(k + "_ep", 0)
                res[k][s][3] = [e[0] for e in ex.get(k, [])]
            res["dlock"][s][0] = m.get("dlock_r", 0)
            res["fuel"][s][0] = m.get("fuel", 0)
            res["fault"][s][0] = m.get("fault", 0)
    except Exception as e:  # noqa: BLE001
        errs.append(f"qa {e!r}"[:80])
    for name, key in (("hidbush", "hidhit"), ("wronggate", "wronggate")):
        try:
            R.PREFER[gid] = sd
            for x in mod(name).scan(row):
                s = us if x["us"] else 1 - us
                m = x.get("m", {})
                if key == "hidhit":
                    res[key][s][:3] = [m.get("hid_ep", 0), m.get("hid_ep_died", 0), m.get("hid_ep_died_gems", 0)]
                else:
                    res[key][s][0] = m.get("wg_ep", 0)
                res[key][s][3] = [e[0] if isinstance(e, (list, tuple)) else e for e in (x.get("ex") or [])][:3]
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name} {e!r}"[:80])
    try:
        r = mod("killgold").one((rep, mp, "live", side))
        if r:
            for s in (0, 1):
                c = r[3][s]
                res["deniable"][s][:3] = [c.get("den_clear", 0), c.get("den_clear", 0), 0]
    except Exception as e:  # noqa: BLE001
        errs.append(f"killgold {e!r}"[:80])
    return dict(id=gid, map=mp, us=us, res=res, errs=errs, prism=has_prism)


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    out, jobs, top = opt("--out", None), int(opt("--jobs", 12)), int(opt("--top", 3))
    sets = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in ("--out", "--jobs", "--top"))]
    t0 = time.time()
    subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(LAB, "replay.py"), "warm", *sets, "--jobs", str(jobs)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tw = time.time() - t0
    games, seen = [], set()
    for sd in sets:
        for ln in open(os.path.join(sd, "matches.txt")):
            p = ln.split()
            if len(p) >= 4 and p[2] in "ab" and p[0] not in seen and os.path.exists(os.path.join(sd, "x_" + p[0], "replay.repl26a")):
                seen.add(p[0])
                games.append((sd, p[0], p[1], p[2]))
    with ProcessPoolExecutor(jobs) as ex:
        rows = list(ex.map(one, games, chunksize=2))
    ok = [r for r in rows if "res" in r]
    n = len(ok)
    T = []
    for k, label in CLASSES:
        ours = [r["res"][k][r["us"]] for r in ok]
        theirs = [r["res"][k][1 - r["us"]] for r in ok]
        mo = sum(x[0] for x in ours) / max(1, n)
        mt = sum(x[0] for x in theirs) / max(1, n)
        z = None
        if k in PRISM_ONLY:  # per team-game with a Prism, Welch: a Prism-less team scores 0 by definition
            xo = [r["res"][k][r["us"]][0] for r in ok if r["prism"][r["us"]]]
            xt = [r["res"][k][1 - r["us"]][0] for r in ok if r["prism"][1 - r["us"]]]
            mo, mt = sum(xo) / max(1, len(xo)), sum(xt) / max(1, len(xt))
            label = f"{label} [n {len(xo)} v {len(xt)}]"
            if len(xo) >= 5 and len(xt) >= 5:
                # each side's variance floored at the pooled mean (a Poisson count): a side of all zeros otherwise has se 0 and any
                # small count on the other side reads as z >= 2 (v460: 0.70 v 0.00 over 23 v 11 team-games read +2.2)
                pm = (sum(xo) + sum(xt)) / (len(xo) + len(xt))
                vo = max(pm, sum((v - mo) ** 2 for v in xo) / (len(xo) - 1))
                vt = max(pm, sum((v - mt) ** 2 for v in xt) / (len(xt) - 1))
                se = (vo / len(xo) + vt / len(xt)) ** 0.5
                z = (mo - mt) / se if se > 0 else 0.0
        elif k not in OURS_ONLY and n > 2:
            d = [x[0] - y[0] for x, y in zip(ours, theirs)]
            mu = sum(d) / n
            sd = (sum((v - mu) ** 2 for v in d) / (n - 1)) ** 0.5
            z = mu / (sd / n ** 0.5) if sd > 0 else (0.0 if mu == 0 else math.copysign(99.0, mu))
        dths = (sum(x[1] for x in ours) / max(1, n), sum(y[1] for y in theirs) / max(1, n))
        gems = (sum(x[2] for x in ours) / max(1, n), sum(y[2] for y in theirs) / max(1, n))
        worst = sorted(((x[0], r) for x, r in zip(ours, ok) if x[0] > 0), key=lambda q: -q[0])[:top]
        T.append(dict(k=k, label=label, ours=mo, theirs=mt, z=z, deaths=dths, gems=gems,
                      worst=[(c, r["id"], r["map"], r["res"][k][r["us"]][3][:3]) for c, r in worst]))
    T.sort(key=lambda x: (x["z"] is None, -(x["z"] if x["z"] is not None else 0), -x["ours"]))
    # 12 Nov (Combat): recalldeath flagged single versions at z +2.5 (v768/777/804/824/828) while pooled v800-824 .158/g, v825+ .140/g
    # v the foe .168/.185 (same kept-recall rule): bin noise. Classes in ANOM_MUTE stay in the table as information, never a CANDIDATE.
    mute = set(filter(None, os.environ.get("ANOM_MUTE", "recalldeath").split(",")))
    cand = [x for x in T if x["z"] is not None and x["z"] >= 2 and x["k"] not in mute]
    errs = collections.Counter(e.split()[0] for r in ok for e in r["errs"])
    L = [f"# Anomaly scan: {', '.join(os.path.basename(s) for s in sets)}", "",
         f"{n} games ({len(rows) - n} unreadable), {time.time() - t0:.0f} s (warm {tw:.0f} s). Generated by tools/lab/anomscan.py "
         f"({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}).",
         f"CANDIDATE BUGS (ours > opponents at z >= 2): {len(cand)}" + (": " + ", ".join(x["k"] for x in cand) if cand else ""),
         "" if not errs else f"reader errors (games): {dict(errs)}", "",
         "| class | ours/g | opp/g | z | deaths/g ours-opp | gems lost/g ours-opp | worst games (count, id, map, rounds) |",
         "|---|---|---|---|---|---|---|"]
    for x in T:
        zs = ("ours only" if x["k"] in OURS_ONLY else "too few Prism team-games") if x["z"] is None else f"{x['z']:+.1f}" + ((" (muted: information)" if x["k"] in mute else " **CANDIDATE**") if x["z"] >= 2 else "")
        w = "; ".join(f"{c} {gid[:8]} {mp} r{','.join(str(q) for q in rr) or '?'}" for c, gid, mp, rr in x["worst"]) or "-"
        dd = f"{x['deaths'][0]:.2f} - {x['deaths'][1]:.2f}" if any(x["deaths"]) else "-"
        gg = f"{x['gems'][0]:.1f} - {x['gems'][1]:.1f}" if any(x["gems"]) else "-"
        L.append(f"| {x['label']} | {x['ours']:.2f} | {x['theirs']:.2f} | {zs} | {dd} | {gg} | {w} |")
    L += ["", f"Multiple classes: with {sum(1 for x in T if x['z'] is not None)} classes tested at one-sided z >= 2, about "
          f"{0.023 * sum(1 for x in T if x['z'] is not None):.1f} false candidate(s) per scan are expected by chance: walk the replays first.",
          "z: mean per-game difference (ours - opponents) / its standard error over the games. Ours-only classes rank last. yieldwait: Welch z over team-games that field a Prism, variances floored at the pooled mean (ours/g and opp/g are per such team-game).",
          "Rounds are the class's example rounds in that game (episode starts / event rounds)."]
    txt = "\n".join(L) + "\n"
    if out:
        open(out + ".part", "w").write(txt)
        os.replace(out + ".part", out)
    print(f"ANOMALY {n} games: {len(cand)} candidate(s) at z >= 2" + (": " + ", ".join(f"{x['k']} {x['z']:+.1f}" for x in cand) if cand else ""))
    if not out:
        print(txt)


if __name__ == "__main__":
    main()
