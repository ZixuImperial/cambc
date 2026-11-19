#!/usr/bin/env python3
"""Economy race from the engine's replay of every turn: camp-group cycles, phase economy, the richest mid group.

usage: python3 -I tools/lab/econrace.py COMMAND GAME... [--out FILE] [--jobs 4] [--us A|B|BOT]
  GAME as in `replay.py report`: a live set dir (expands to its games; us = the live side from matches.txt), a local
  run dir with kept replays (RUN/rep: KEEP=1 abl.sh or `restat.py --keep RUN`), RUN:ID, or a match id.
  --us BOT (local runs): our side is wherever that bot played; games without it are skipped.
commands:
  cycles [--min-gems 20]   per camp-group respawn cycle: who damaged it, who was near, who captured (losses vs wins)
  phases                   captures, gems, deaths and time budget per phase (0-75-150-300-600), us vs them
  jackpot                  the richest mid group per game: first presence, hit and capture, captures before r300
  jackpot --pair CAND BASE RUNDIR... [--censor 300]
                           paired CAND - BASE on the same map and seat (opponent: each other in a head-to-head run,
                           or the same third bot): the richest mid group's first capture round and captures before
                           r300, mean difference with a bootstrap 95% CI over maps (both seats of a map resampled together)
Merged from condor-work/reports/econ/{cycles,opening,jackpot}.py (cambc-a3); phases = opening.py.
"""
import collections
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as R  # noqa: E402

PH = [(0, 75), (75, 150), (150, 300), (300, 600)]


def groups_of(e):
    return e[2] if isinstance(e[2], list) else [e[2]]


def cap_gems(g):
    """Largest capture (gems) of every group in this game."""
    gems = collections.Counter()
    for e in g.events:
        if e[1] == "capture" and e[3] in (0, 1):
            for k in groups_of(e):
                gems[k] = max(gems[k], sum(x[2] for x in e[4]))
    return gems


# ---------------------------------------------------------------- per game (runs in a worker)
def cycles_game(g, mg):
    us = g.us
    camp_group = {c: v["group"] for c, v in g.camps.items()}
    bounds, caps, deaths = (collections.defaultdict(list) for _ in range(3))
    for e in g.events:
        if e[1] == "group_respawn":
            bounds[e[2]].append(e[0])
        elif e[1] == "camp_death" and e[2] in camp_group:
            deaths[camp_group[e[2]]].append(e[0])
        elif e[1] == "capture" and e[3] in (0, 1):
            for k in groups_of(e):
                caps[k].append((e[0], e[3], sum(x[2] for x in e[4])))
    dmg = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    pres = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    near = {}
    acts = R.classify_all(g)
    actnear = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))  # group -> round -> our activities
    for t in g.turns:
        tm = g.team_of[t[1]]
        for cid, d in R.camp_hits(g, t):
            k = camp_group.get(cid)
            if k is not None:
                dmg[k][tm][t[0]] += d
        if t[g.ci["alive"]] and t[2] >= 0:
            gl = near.get((t[2], t[3]))
            if gl is None:
                gl = near[(t[2], t[3])] = [k for k, gr in g.groups.items() if any(R.cheb(t[2], t[3], x, y) <= 5 for x, y in gr["pts"])]
            for k in gl:
                pres[k][tm][t[0]] += 1
                if tm == us:
                    actnear[k][t[0]][acts.get((t[0], t[1]), "?")] += 1
    agg = collections.defaultdict(collections.Counter)  # zone -> counters
    rows, nrows, nact = [], [], collections.Counter()
    for k, gr in g.groups.items():
        cg = caps[k]
        if max([c[2] for c in cg], default=0) < mg:
            continue
        zone = g.zone(round(gr["cx"]), round(gr["cy"]), us)
        edges = [0] + sorted(bounds[k]) + [10 ** 6]
        for a, b in zip(edges, edges[1:]):
            du = sum(v for r, v in dmg[k][us].items() if a <= r < b)
            dt = sum(v for r, v in dmg[k][1 - us].items() if a <= r < b)
            pu = sum(v for r, v in pres[k][us].items() if a <= r < b)
            pt = sum(v for r, v in pres[k][1 - us].items() if a <= r < b)
            cap = [c for c in cg if a <= c[0] < b]
            who = cap[0][1] if cap else None
            cgem = cap[0][2] if cap else 0
            c = agg[zone]
            c["cycles"] += 1
            if who == us:
                c["ours"] += 1
                c["ours_gems"] += cgem
                if dt > 0:
                    c["ours_contested"] += 1
            elif who == 1 - us:
                c["theirs"] += 1
                c["theirs_gems"] += cgem
                if du > 0:
                    c["abandoned"] += 1
                    c["abandoned_gems"] += cgem
                    rows.append((cgem, k, a, cap[0][0], int(du), int(dt), pu, pt))
                elif pu >= 10:
                    c["near_nohit"] += 1
                    c["near_nohit_gems"] += cgem
                    c["near_nohit_bt"] += pu
                    if pu >= 30:
                        c["near30"] += 1
                        c["near30_gems"] += cgem
                    an = collections.Counter()
                    for r2, cc in actnear[k].items():
                        if a <= r2 <= cap[0][0]:
                            an.update(cc)
                    nact.update(an)
                    if cgem < 150:
                        # rounds the group was alive (before its last camp death this cycle) with us near and them not
                        dl = max([r2 for r2 in deaths[k] if a <= r2 <= cap[0][0]], default=cap[0][0])
                        fr = sum(1 for r2 in range(a, dl) if pres[k][us][r2] > 0 and pres[k][1 - us][r2] == 0)
                        cr = sum(1 for r2 in range(a, dl) if pres[k][us][r2] > 0 and pres[k][1 - us][r2] > 0)
                        eq = sum(1 for r2 in range(a, dl) if pres[k][us][r2] >= pres[k][1 - us][r2] > 0)
                        c["s_cyc"] += 1
                        c["s_gems"] += cgem
                        c["s_free"] += fr
                        c["s_cont"] += cr
                        c["s_eq"] += eq
                        if fr >= 5:
                            c["s_free5"] += 1
                            c["s_free5_gems"] += cgem
                    nrows.append((cgem, k, a, cap[0][0], pu, pt, " ".join(f"{x}:{v}" for x, v in an.most_common(4))))
                else:
                    c["absent"] += 1
                    c["absent_gems"] += cgem
            else:
                c["uncaptured"] += 1
                if du > 0 or dt > 0:
                    c["hit_uncaptured"] += 1
    return {"agg": dict(agg), "rows": rows, "nrows": nrows, "nact": nact}


def phases_game(g):
    us = g.us

    def side(tm):
        return "us" if tm == us else "them"

    def ph(r):
        return next((i for i, (a, b) in enumerate(PH) if a <= r < b), None)
    agg = collections.defaultdict(collections.Counter)  # (phase, side) -> counters
    for (r, c), a in R.classify_all(g).items():
        p = ph(r)
        if p is not None:
            agg[(p, side(g.team_of[c]))]["t_" + a] += 1
            agg[(p, side(g.team_of[c]))]["turns"] += 1
    first = {}
    for e in g.events:
        p = ph(e[0])
        if e[1] == "capture" and e[3] in (0, 1):
            gm = sum(x[2] for x in e[4])
            if p is not None:
                k = agg[(p, side(e[3]))]
                k["caps"] += 1
                k["gems"] += gm
                if gm >= 30:
                    k["caps30"] += 1
                    k["gems30"] += gm
                gr = g.groups.get(groups_of(e)[0])
                if gr is not None:
                    z = g.zone(round(gr["cx"]), round(gr["cy"]), e[3])  # zone seen from the capturer
                    cls = "s" if gm < 10 else ("m" if gm < 30 else "b")
                    k["z_" + z] += gm
                    k["zc_" + z] += 1
                    k["c_" + cls] += 1
                    k["g_" + cls] += gm
            if e[3] not in first:
                first[e[3]] = (e[0], gm)
        elif e[1] == "death" and p is not None:
            agg[(p, side(g.team_of[e[2]]))]["deaths"] += 1
        elif e[1] == "tribute" and p is not None:
            agg[(p, "us" if g.team_of.get(e[2], -1) == us else "them")]["tribs"] += 1
    return {"agg": dict(agg), "firsts": {side(tm): v for tm, v in first.items()}}


def group_race(g, k, team, st=None):
    """First presence (within 5), first hit and first capture of group k by `team` and its opponent; captures before r300."""
    st = st or R.group_stats(g)
    camp_group = {c: v["group"] for c, v in g.camps.items()}
    fd = [None, None]
    for t in g.turns:
        for cid, d in R.camp_hits(g, t):
            if camp_group.get(cid) == k and fd[g.team_of[t[1]]] is None:
                fd[g.team_of[t[1]]] = t[0]
    c300 = [0, 0]
    for e in g.events:
        if e[1] == "capture" and e[3] in (0, 1) and e[0] < 300 and k in groups_of(e):
            c300[e[3]] += 1
    s = st[k]
    o = 1 - team
    return {"fp": (s["first_pres"][team], s["first_pres"][o]), "fd": (fd[team], fd[o]),
            "fc": (s["first_cap"][team], s["first_cap"][o]), "c300": (c300[team], c300[o]), "caps": (s["caps"][team], s["caps"][o])}


def jackpot_game(g):
    """The richest mid group of this game by its largest capture (20-149 gems), as jackpot.py chose it."""
    us = g.us
    gems = cap_gems(g)
    mids = [k for k, gr in g.groups.items() if g.zone(round(gr["cx"]), round(gr["cy"]), us) == "mid" and 20 <= gems[k] < 150]
    if not mids:
        return None
    k = max(mids, key=lambda q: gems[q])
    return dict(k=k, gems=gems[k], desc=R.self_desc(g, k)[:30], **group_race(g, k, us))


def richest_mid_static(g, team):
    """The richest mid group seen from `team` by the map's gems per capture (20-149): the same group in every game on
    a map and seat, so paired games compare one group."""
    mids = [k for k, gr in g.groups.items() if g.zone(round(gr["cx"]), round(gr["cy"]), team) == "mid" and 20 <= gr["gems"] < 150]
    return max(sorted(mids), key=lambda q: g.groups[q]["gems"]) if mids else None


def pair_game(g, cand, base):
    """Rows for CAND and BASE in one local game: (bot, map, seat, opponent key, group, gems, race)."""
    m = g.meta
    out = []
    for bot in (cand, base):
        if bot not in (m.get("a"), m.get("b")):
            continue
        seat = 0 if m.get("a") == bot else 1
        opp = m.get("b") if seat == 0 else m.get("a")
        k = richest_mid_static(g, seat)
        if k is None:
            continue
        out.append({"bot": bot, "map": m.get("map", "?"), "seat": "AB"[seat], "opp": "h2h" if opp in (cand, base) else opp,
                    "k": k, "gems": g.groups[k]["gems"], "spec": f"{m.get('run')}:{m.get('game')}", **group_race(g, k, seat)})
    return out


def _job(a):
    cmd, spec, us, opt = a
    try:
        g = R.load(spec, us)
    except SystemExit as e:
        return {"spec": spec, "error": str(e)}
    m = g.meta
    if us and us.upper() not in ("A", "B") and m.get("source") == "local" and us not in (m.get("a"), m.get("b")) \
            and cmd != "pair":
        return {"spec": spec, "error": f"{us} did not play this game"}
    if g.final.get("outcome") not in (1, 2):
        return {"spec": spec, "error": f"no result (outcome {g.final.get('outcome')} at round {g.last_round})"}
    res = "win" if {1: 0, 2: 1}[g.final["outcome"]] == g.us else "loss"
    gid = m.get("match", "")[:8] or f"{m.get('run', '?')}:{m.get('game', '?')}" if m.get("source") != "file" else spec
    info = {"spec": spec, "res": res, "map": m.get("map", "?"), "opp": g.team_name(1 - g.us), "gid": gid}
    if cmd == "cycles":
        info.update(cycles_game(g, opt["min_gems"]))
    elif cmd == "phases":
        info.update(phases_game(g))
    elif cmd == "jackpot":
        info["jp"] = jackpot_game(g)
    elif cmd == "pair":
        info["pair"] = pair_game(g, opt["cand"], opt["base"])
    return info


def run(cmd, specs, us, jobs, opt):
    work = [(cmd, s, us, opt) for s in R.expand_specs(specs)]
    if jobs > 1 and len(work) > 1:
        import multiprocessing
        with multiprocessing.get_context("fork").Pool(min(jobs, len(work))) as pool:
            res = pool.map(_job, work)
    else:
        res = [_job(w) for w in work]
    bad = [x for x in res if "error" in x]
    for x in bad[:10]:
        print(f"skip {x['spec']}: {x['error'][:160]}", file=sys.stderr)
    return [x for x in res if "error" not in x], bad


# ---------------------------------------------------------------- reports
def report_cycles(res, nbad, mg):
    ng = collections.Counter(x["res"] for x in res)
    agg = collections.defaultdict(collections.Counter)
    nact = collections.defaultdict(collections.Counter)
    rows, nrows = [], []
    for x in res:
        for z, c in x["agg"].items():
            agg[(x["res"], z)].update(c)
        nact[x["res"]].update(x["nact"])
        rows += [(r[0], x["res"], x["map"], x["opp"], x["gid"]) + r[1:] for r in x["rows"]]
        nrows += [(r[0], x["res"], x["map"], x["opp"], x["gid"]) + r[1:] for r in x["nrows"]]
    L = [f"# Group cycles (groups with {mg}+ gems per capture): {len(res)} games, {ng['win']} wins, {ng['loss']} losses"
         + (f" ({nbad} not read)" if nbad else ""), "",
         "Terms: a cycle is one respawn period of a camp group (from a group_respawn to the next). zone = own/mid/enemy by "
         "walk distance from the two spawns (mid = 0.4-0.6), seen from us. ours/theirs = the cycle's first capture was ours/"
         "theirs (gems). abandoned = we damaged it this cycle, they captured; near, no hit = we had 10+ body-turns within 5 "
         "tiles, no damage, they captured; absent = they captured, we were not there; ours with their damage = we captured "
         "after they damaged it. Values are per game (cycles, gems in brackets).", "",
         "| result | zone | cycles | ours (gems) | theirs (gems) | abandoned (gems) | near, no hit (gems) | absent (gems) | ours with their damage |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r_ in ("loss", "win"):
        for z in ("own", "mid", "enemy"):
            c = agg[(r_, z)]
            n = max(ng[r_], 1)

            def f(a, b):
                return f"{c[a] / n:.1f} ({c[b] / n:.0f})"
            L.append(f"| {r_} | {z} | {c['cycles'] / n:.1f} | {f('ours', 'ours_gems')} | {f('theirs', 'theirs_gems')} | "
                     f"{f('abandoned', 'abandoned_gems')} | {f('near_nohit', 'near_nohit_gems')} | {f('absent', 'absent_gems')} | "
                     f"{c['ours_contested'] / n:.1f} |")
    L += ["", "## Biggest abandoned cycles", "", "| gems | result | map | opponent | game | group | cycle start | their capture | "
          "our dmg | their dmg | our/their body-turns near |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, reverse=True)[:30]:
        L.append("| " + " | ".join(str(x) for x in r[:10]) + f" | {r[10]}/{r[11]} |")
    L += ["", "## Our activity near the group in near-no-hit cycles (body-turns, from cycle start to their capture)", ""]
    for r_ in ("loss", "win"):
        tot = sum(nact[r_].values()) or 1
        L.append(f"- {r_}: " + ", ".join(f"{x} {100 * v / tot:.0f}%" for x, v in nact[r_].most_common()))
    for r_ in ("loss", "win"):
        c = agg[(r_, "mid")]
        n = max(ng[r_], 1)
        L.append(f"- {r_}, mid, 30+ body-turns near: {c['near30'] / n:.1f} cycles ({c['near30_gems'] / n:.0f} gems) per game")
    L += ["", "## Near-no-hit cycles of groups under 150 gems (no monoliths): rounds the group was ALIVE with our body within 5", ""]
    for r_ in ("loss", "win"):
        for z in ("own", "mid", "enemy"):
            c = agg[(r_, z)]
            n = max(ng[r_], 1)
            if c["s_cyc"]:
                L.append(f"- {r_} {z}: {c['s_cyc'] / n:.1f} cycles ({c['s_gems'] / n:.0f} gems)/game; per cycle: rounds near with no "
                         f"enemy near {c['s_free'] / c['s_cyc']:.1f}, with enemies near {c['s_cont'] / c['s_cyc']:.1f} (of which we had "
                         f">= their bodies {c['s_eq'] / c['s_cyc']:.1f}); cycles with 5+ free rounds {c['s_free5'] / n:.1f} "
                         f"({c['s_free5_gems'] / n:.0f} gems)/game")
    L += ["", "## Biggest near-no-hit cycles", "", "| gems | result | map | opponent | game | group | cycle start | their capture | "
          "our/their body-turns | our activity near |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(nrows, reverse=True)[:30]:
        L.append("| " + " | ".join(str(x) for x in r[:8]) + f" | {r[8]}/{r[9]} | {r[10]} |")
    return L


def report_phases(res, nbad):
    ng = collections.Counter(x["res"] for x in res)
    agg = collections.defaultdict(collections.Counter)
    firsts = collections.defaultdict(list)
    for x in res:
        for (p, sd), c in x["agg"].items():
            agg[(x["res"], p, sd)].update(c)
        for sd, v in x["firsts"].items():
            firsts[(x["res"], sd)].append(tuple(v))
    L = [f"# Phase economy: {sum(ng.values())} games ({ng['loss']} losses, {ng['win']} wins); per game"
         + (f" ({nbad} not read)" if nbad else ""), "",
         "Terms: rounds = phase [from, to). captures/gems = camp-group captures and their gems in the phase; 30+ = captures "
         "of 30+ gems. deaths = champion deaths. dead% ... capture% = share of the side's champion turns in that activity "
         "(replay.py activity labels: farm = hit a camp, fight = hit a champion, capture = idle beside our capturing group). "
         "Zones are seen from the capturer; capture size small < 10, medium 10-29, big 30+ gems.", "",
         "| result | rounds | side | captures | gems | gems/capture | 30+ gem captures (gems) | deaths | dead% | farm% | walk% | idle% | fight% | recall% | capture% |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r_ in ("loss", "win"):
        n = max(ng[r_], 1)
        for p, (a, b) in enumerate(PH):
            for sd in ("us", "them"):
                k = agg[(r_, p, sd)]
                T = k["turns"] or 1

                def sh(x):
                    return f"{100 * k['t_' + x] / T:.1f}"
                L.append(f"| {r_} | {a}-{b} | {sd} | {k['caps'] / n:.1f} | {k['gems'] / n:.0f} | {k['gems'] / max(k['caps'], 1):.1f} | "
                         f"{k['caps30'] / n:.1f} ({k['gems30'] / n:.0f}) | {k['deaths'] / n:.2f} | {sh('dead')} | {sh('farm')} | "
                         f"{sh('walk')} | {sh('idle')} | {sh('fight')} | {sh('recall')} | {sh('capture')} |")
    L += ["", "Captures by zone seen from the capturer (gems, captures) and by capture size (<10 / 10-29 / 30+ gems: captures, gems)", "",
          "| result | rounds | side | own | mid | enemy | small | medium | big |", "|---|---|---|---|---|---|---|---|---|"]
    for r_ in ("loss", "win"):
        n = max(ng[r_], 1)
        for p, (a, b) in enumerate(PH):
            for sd in ("us", "them"):
                k = agg[(r_, p, sd)]
                zz = " | ".join(f"{k['z_' + z] / n:.0f} ({k['zc_' + z] / n:.1f})" for z in ("own", "mid", "enemy"))
                cc = " | ".join(f"{k['c_' + c] / n:.1f} ({k['g_' + c] / n:.0f})" for c in "smb")
                L.append(f"| {r_} | {a}-{b} | {sd} | {zz} | {cc} |")
    L += ["", "First capture: median round, median gems"]
    for key, v in sorted(firsts.items()):
        rs = sorted(x[0] for x in v)
        gs = sorted(x[1] for x in v)
        L.append(f"- {key[0]} {key[1]}: round {rs[len(rs) // 2]}, gems {gs[len(gs) // 2]} (n {len(v)})")
    return L


def fmt_pair(p):
    return "/".join("-" if v is None else str(v) for v in p)


def med(v):
    v = sorted(x for x in v if x is not None)
    return v[len(v) // 2] if v else None


def report_jackpot(res, nbad):
    rows = [dict(x["jp"], res=x["res"], mp=x["map"], opp=x["opp"], gid=x["gid"]) for x in res if x["jp"]]
    L = ["# Richest mid group per game (20-149 gems per capture)" + (f" ({nbad} games not read)" if nbad else ""), "",
         f"Terms: per game, the mid-zone group (walk-distance ratio 0.4-0.6 from our spawn) with the largest capture of 20-149 "
         f"gems ({len(rows)} of {len(res)} games have one). first near = first round a body was within 5 tiles of one of its "
         f"camps; first hit = first damage to one of its camps; first capture = first capture of it; caps <r300 = its "
         f"captures before round 300; caps = all its captures. us/them; '-' = never. Medians skip games where it never "
         f"happened.", ""]
    for r_ in ("loss", "win"):
        R_ = [r for r in rows if r["res"] == r_]
        n = len(R_) or 1
        ufc = sum(1 for r in R_ if r["fc"][0] is not None and (r["fc"][1] is None or r["fc"][0] < r["fc"][1]))
        ufd = sum(1 for r in R_ if r["fd"][0] is not None and (r["fd"][1] is None or r["fd"][0] < r["fd"][1]))
        ufp = sum(1 for r in R_ if r["fp"][0] is not None and (r["fp"][1] is None or r["fp"][0] <= r["fp"][1]))
        L.append(f"- {r_} ({len(R_)} games): we arrive first {100 * ufp / n:.0f}%, hit first {100 * ufd / n:.0f}%, capture first "
                 f"{100 * ufc / n:.0f}%; median first presence us {med(r['fp'][0] for r in R_)} / them {med(r['fp'][1] for r in R_)}, "
                 f"first hit {med(r['fd'][0] for r in R_)} / {med(r['fd'][1] for r in R_)}, first capture {med(r['fc'][0] for r in R_)} / "
                 f"{med(r['fc'][1] for r in R_)}; captures before r300 us {sum(r['c300'][0] for r in R_) / n:.2f} / them "
                 f"{sum(r['c300'][1] for r in R_) / n:.2f}; all captures {sum(r['caps'][0] for r in R_) / n:.1f} / "
                 f"{sum(r['caps'][1] for r in R_) / n:.1f}")
    L += ["", "| res | map | opponent | game | group | gems | what | first near us/them | first hit us/them | first capture us/them | "
          "caps <r300 us/them | caps us/them |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["res"], r["mp"])):
        if r["res"] == "loss":
            L.append(f"| {r['res']} | {r['mp']} | {r['opp']} | {r['gid']} | {r['k']} | {r['gems']} | {r['desc']} | {fmt_pair(r['fp'])} | "
                     f"{fmt_pair(r['fd'])} | {fmt_pair(r['fc'])} | {fmt_pair(r['c300'])} | {fmt_pair(r['caps'])} |")
    return L


def boot_ci(per_map, B=4000, seed=1):
    """Mean of per-map values and a percentile bootstrap 95% CI resampling maps."""
    v = list(per_map)
    if not v:
        return None, None, None
    m = sum(v) / len(v)
    rng = random.Random(seed)
    ms = sorted(sum(rng.choice(v) for _ in v) / len(v) for _ in range(B))
    return m, ms[int(0.025 * B)], ms[int(0.975 * B) - 1]


def report_pair(res, nbad, cand, base, censor):
    rows = {}
    for x in res:
        for p in x["pair"]:
            rows.setdefault((p["bot"], p["map"], p["seat"], p["opp"]), p)  # replays of one game are identical: keep one
    keys = sorted({k[1:] for k in rows if (cand,) + k[1:] in rows and (base,) + k[1:] in rows})
    unpaired = sorted({k[1:] for k in rows} - set(keys))

    def fc(p):
        return min(p["fc"][0], censor) if p["fc"][0] is not None else censor
    metrics = [("first capture (censored)", lambda p: fc(p)), ("captures before r300", lambda p: p["c300"][0]),
               ("captured before r300 (0/1)", lambda p: int(p["c300"][0] > 0)), ("all captures", lambda p: p["caps"][0]),
               ("opponent captures before r300", lambda p: p["c300"][1])]
    L = [f"# Richest mid group, paired: {cand} - {base}", "",
         f"Terms: for each map and seat, the subject bot's game with {cand} in that seat is paired with the game with {base} "
         f"in the same seat against the same opponent ('h2h' = they played each other). The group is the mid-zone group "
         f"(walk-distance ratio 0.4-0.6 from the subject's spawn) with the most gems per capture by the map (20-149, the "
         f"same group in both games). first capture = the subject's first capture round of it, censored at r{censor} (never "
         f"captured by then counts as {censor}); captures before r300 = the subject's captures of it before round 300; "
         f"opponent captures = the other side's. diff = {cand} - {base}; mean over maps (a map's value = the mean of its "
         f"seats), 95% CI by bootstrap over maps (4000 resamples). Negative first-capture diff = {cand} captures earlier.",
         "", f"{len(keys)} map-seats paired on {len({k[0] for k in keys})} maps; {len(unpaired)} map-seats unpaired; "
         f"{nbad} games not read.", "", f"| metric | {cand} mean | {base} mean | diff | 95% CI | maps |", "|---|---|---|---|---|---|"]
    for name, fn in metrics:
        per_map = collections.defaultdict(list)
        for k in keys:
            per_map[k[0]].append(fn(rows[(cand,) + k]) - fn(rows[(base,) + k]))
        m, lo, hi = boot_ci([sum(v) / len(v) for v in per_map.values()])
        mc = sum(fn(rows[(cand,) + k]) for k in keys) / max(1, len(keys))
        mb = sum(fn(rows[(base,) + k]) for k in keys) / max(1, len(keys))
        L.append(f"| {name} | {mc:.2f} | {mb:.2f} | {m:+.2f} | [{lo:+.2f}, {hi:+.2f}] | {len(per_map)} |" if m is not None
                 else f"| {name} | - | - | - | - | 0 |")
    nc = sum(1 for k in keys if rows[(cand,) + k]["fc"][0] is None or rows[(cand,) + k]["fc"][0] >= censor)
    nb = sum(1 for k in keys if rows[(base,) + k]["fc"][0] is None or rows[(base,) + k]["fc"][0] >= censor)
    L += ["", f"Censored (no capture before r{censor}): {cand} {nc}, {base} {nb} of {len(keys)} map-seats.", "",
          f"| map | seat | opp | group | gems | first capture {cand}/{base} | caps <r300 {cand}/{base} | games |",
          "|---|---|---|---|---|---|---|---|"]
    for k in keys:
        c, b = rows[(cand,) + k], rows[(base,) + k]
        L.append(f"| {k[0]} | {k[1]} | {k[2]} | {c['k']} | {c['gems']} | {fmt_pair((c['fc'][0], b['fc'][0]))} | "
                 f"{c['c300'][0]}/{b['c300'][0]} | {c['spec']} {b['spec']} |")
    return L


def main():
    a = sys.argv[1:]

    def opt(name, default=None, cast=str):
        if name in a:
            i = a.index(name)
            v = cast(a[i + 1])
            del a[i:i + 2]
            return v
        return default
    out, jobs, us = opt("--out"), opt("--jobs", 4, int), opt("--us")
    mg, censor = opt("--min-gems", 20, int), opt("--censor", 300, int)
    pair = None
    if "--pair" in a:
        i = a.index("--pair")
        pair = a[i + 1:i + 3]
        del a[i:i + 3]
    if len(a) < 2 or a[0] not in ("cycles", "phases", "jackpot") or any(x.startswith("--") for x in a) or (pair and a[0] != "jackpot"):
        print(__doc__)
        sys.exit(1)
    cmd, specs = a[0], a[1:]
    if pair:
        res, bad = run("pair", specs, None, jobs, {"cand": pair[0], "base": pair[1]})
        L = report_pair(res, len(bad), pair[0], pair[1], censor)
    else:
        res, bad = run(cmd, specs, us, jobs, {"min_gems": mg})
        L = {"cycles": lambda: report_cycles(res, len(bad), mg), "phases": lambda: report_phases(res, len(bad)),
             "jackpot": lambda: report_jackpot(res, len(bad))}[cmd]()
    txt = "\n".join(L) + "\n"
    if out:
        open(out, "w").write(txt)
        print(f"{len(res)} games -> {out}")
    else:
        print(txt)


if __name__ == "__main__":
    main()
