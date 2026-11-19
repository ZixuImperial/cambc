#!/usr/bin/env python3
"""How games are won and lost: a markdown report from per-game features (tools/lab/gamefeat.py), written for agents.

usage: python3 -I tools/lab/gamerep.py CAND BASE [--set fresh,genpatho,...] [--out FILE]   local games, CAND = "us"
       python3 -I tools/lab/gamerep.py --live SETDIR [SETDIR ...] [--out FILE]              live sets, our team = "us"
  Local mode reads every game between the current sources of CAND and BASE that has features: abl.sh writes them
  for every new run (games_rich.jsonl); older runs need `python3 -I tools/lab/restat.py RUNDIR` first. It adds a
  paired section: CAND and BASE in the same seat on the same map.
  Live mode reads tools/lab/diag.sh set dirs (matches.txt + <matchId>.json) and adds a per-opponent table.
  --out writes the report to FILE (put shared reports in /homes/USER/condor-work/reports/).

Numbers are means per game; "gap" = us minus them; [lo, hi] = 95% CI over maps (local) or games (live); a * marks a
difference beyond noise (|z| >= 3). Loss patterns are tags with fixed thresholds, shown as the share of losses vs the
share of wins that carry them: only a tag much more common in losses points at a cause.
"""
import collections
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abindex  # noqa: E402
import abstat  # noqa: E402
import gamefeat  # noqa: E402
import map26a  # noqa: E402
import mapfeat  # noqa: E402

CP = (150, 300, 500, 800, 1000)
MAPS = "/data/USER/work301/maps"
_mf = {}


META_DIRS = ["/data/USER/genmaps_s", "/data/USER/genmaps_p", "/data/USER/genmaps_c", "/data/USER/genmaps",
             "/data/USER/genmaps_dev"]
FEAT_CACHE = "/data/USER/mapfeat_cache.json"  # {content hash-v<mapfeat.VERSION>: mapfeat.analyse(...)}


def mapfeats(path):
    """mapfeat.analyse of a map: from the generator's meta.json when there is one (genbig/genmaps store exactly this)
    and it describes this very file with the current mapfeat version, else from a cache keyed by content and mapfeat
    version; analysing takes about 0.4 s per map, too slow for hundreds of maps."""
    if path in _mf:
        return _mf[path]
    import hashlib
    import json
    name = os.path.basename(path)[:-7]
    try:
        raw = open(path, "rb").read()
    except OSError:
        _mf[path] = None
        return None
    for d in META_DIRS:
        mp = os.path.join(d, name + ".meta.json")
        if os.path.exists(mp):
            try:
                f = json.load(open(mp))["features"]
                src = os.path.join(d, name + ".map26a")
                if f.get("v") == mapfeat.VERSION and os.path.exists(src) and open(src, "rb").read() == raw:
                    _mf[path] = f
                    return f
            except (ValueError, KeyError):
                pass
            break
    h = hashlib.sha1(raw).hexdigest()[:12] + f"-v{mapfeat.VERSION}"
    if "_disk" not in _mf:
        try:
            _mf["_disk"] = json.load(open(FEAT_CACHE))
        except (OSError, ValueError):
            _mf["_disk"] = {}
    disk = _mf["_disk"]
    if h not in disk:
        try:
            disk[h] = mapfeat.analyse(map26a.load(path), name)
        except Exception:  # noqa: BLE001
            disk[h] = None
        tmp = FEAT_CACHE + f".{os.getpid()}"
        json.dump(disk, open(tmp, "w"))
        os.replace(tmp, FEAT_CACHE)
    _mf[path] = disk[h]
    return _mf[path]


def live_map(name):
    for n in (name, name.replace("_", "-")):
        p = os.path.join(MAPS, n + ".map26a")
        if os.path.exists(p):
            return p
    return None


def dead_share(rich, s):
    """Share of team s's champion-rounds spent dead, from the stored dead_rounds: gamefeat features written before
    2026-10-25 rounded dead_share to 0.1 (0.05 -> 0.1, 0.04 -> 0.0)."""
    n = sum(1 for c in rich.get("champs", []) if c.get("team") == s)
    if not n:
        return rich[s].get("dead_share", 0.0)
    return rich[s].get("dead_rounds", 0) / max(1, n * rich["rounds"])


def game(rich, seat, win, cluster, **kw):
    """One analysed game from our side: seat = our team letter in the statistics."""
    them = "B" if seat == "A" else "A"
    us_f, them_f = dict(rich[seat]), dict(rich[them])
    us_f["dead_share"], them_f["dead_share"] = dead_share(rich, seat), dead_share(rich, them)
    g = dict(us=us_f, them=them_f, win=win, rounds=rich["rounds"], ended=rich["ended"], cluster=cluster,
             groups=rich.get("groups", {}), seat=seat, draft_us=rich["draft"][seat], draft_them=rich["draft"][them],
             champs_us=[c for c in rich["champs"] if c["team"] == seat],
             champs_them=[c for c in rich["champs"] if c["team"] == them], check=rich.get("check") or [])
    g.update(kw)
    return g


# ---------------------------------------------------------------- loading
def load_local(cand, base, sets=None):
    (nc, hc), (nb, hb) = abindex.resolve(cand), abindex.resolve(base)
    if not hc or not hb:
        sys.exit(f"cannot resolve {cand if not hc else base}")
    ix = abindex.Index({hc, hb}, screen=False, rich=True)
    names = abindex.map_names()
    games, total = [], 0
    for (ha, hb2, mh), rec in ix.games.items():
        if {ha, hb2} != {hc, hb}:
            continue
        total += 1
        m = names.get(mh, mh)
        fam = abindex.map_set(m) if m in abindex.maps() else "other"
        if sets and fam not in sets:
            continue
        if "rich" not in rec:
            continue
        seat = "A" if ha == hc else "B"
        mp = abindex.maps().get(m, (None, None))[1]
        games.append(game(rec["rich"], seat, rec["win"] == seat, m, map=m, family=fam, map_path=mp, opp=nb))
    return games, total, (nc, hc, nb, hb)


def load_live(dirs):
    games, total = [], 0
    for sd in dirs:
        for line in open(os.path.join(sd, "matches.txt")):
            p = line.split()
            if len(p) < 5:
                continue
            mid, m, side, res, opp = p[:5]
            f = os.path.join(sd, mid + ".json")
            total += 1
            if not os.path.exists(f):
                continue
            mp = live_map(m)
            rich = gamefeat.extract(f, mp)
            games.append(game(rich, side.upper(), res == "win", mid, map=m, family=os.path.basename(sd.rstrip("/")),
                              map_path=mp, opp=opp, mid=mid, t=os.path.getmtime(f)))
    return games, total


# ---------------------------------------------------------------- statistics
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def ci(games, f):
    """mean of f(game) with a 95% CI over clusters (maps for local games, games for live)."""
    by = collections.defaultdict(list)
    for g in games:
        v = f(g)
        if v is not None:
            by[g["cluster"]].append(v)
    xs = [sum(v) / len(v) for v in by.values()]
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    h = 1.96 * sd / math.sqrt(n) if n > 1 else float("nan")
    return m, m - h, m + h, n


def fmt(x, d=0):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:+.{d}f}" if d >= 0 and isinstance(x, float) and x < 0 else f"{x:.{d}f}"


NONE_KEYS = {"first_cap", "first_sub", "first_item", "lead_for_good"}  # undefined when it never happened


def val(team, k):
    """gamefeat stores a count only when it is nonzero: a missing count is 0, a missing first-round is None."""
    return team.get(k, None if k in NONE_KEYS else 0)


def gap(g, k):
    a, b = val(g["us"], k), val(g["them"], k)
    if a is None or b is None:
        return None
    return a - b


def z_of(m, lo, hi):
    h = (hi - lo) / 2
    return m / (h / 1.96) if h and h == h and h > 0 else 0.0


def table(rows, header):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


# ---------------------------------------------------------------- loss patterns
TAGS = [
    ("outfarmed", "they collected 25%+ more gems", lambda u, t, g: t.get("col_rend", 0) >= 1.25 * max(1, u.get("col_rend", 0))),
    ("mid_lost", "they captured 150+ more gems in the mid zone", lambda u, t, g: t.get("cap_mid", 0) - u.get("cap_mid", 0) >= 150),
    ("own_zone_raided", "they captured 100+ gems in our zone", lambda u, t, g: t.get("cap_enemy", 0) >= 100),
    ("slow_start", "behind by 75+ collected gems at round 300", lambda u, t, g: t.get("col_r300", 0) - u.get("col_r300", 0) >= 75),
    ("late_collapse", "we led by 100+ tributed gems at some point and lost", lambda u, t, g: not g["win"] and u.get("max_lead", 0) >= 100),
    ("lost_fights", "they got 3+ more kills", lambda u, t, g: t.get("kills", 0) - u.get("kills", 0) >= 3),
    ("bags_stolen", "100+ carried gems handed to their champions", lambda u, t, g: u.get("bag_lost_champ", 0) >= 100),
    ("camp_deaths", "3+ of our deaths to monsters", lambda u, t, g: u.get("deaths_camp", 0) >= 3),
    ("dead_time", "10%+ of our champion-rounds spent dead", lambda u, t, g: u.get("dead_share", 0) >= 0.10),
    ("captures_stolen", "2+ groups we cleared were captured by them", lambda u, t, g: u.get("stolen", 0) >= 2),
    ("unbanked", "150+ gems still carried at the end", lambda u, t, g: u.get("carried_end", 0) >= 150),
    ("tiebreak", "went to the round-2000 tiebreak", lambda u, t, g: g["ended"] == "limit"),
    ("fuel_or_faults", "a fuel exhaustion or bot fault on our side", lambda u, t, g: u.get("fuel", 0) + u.get("faults", 0) > 0),
]


def tags_of(g):
    return [k for k, _, f in TAGS if f(g["us"], g["them"], g)]


# ---------------------------------------------------------------- report
METRICS = [  # (section, label, key, decimals)
    ("gems", "captured, own zone", "cap_own", 0), ("gems", "captured, mid zone", "cap_mid", 0),
    ("gems", "captured, enemy zone", "cap_enemy", 0), ("gems", "captured, off-walk (dash/crystal)", "cap_offwalk", 0),
    ("gems", "loot from kills", "loot_gems", 0), ("gems", "collected in total", "col_rend", 0),
    ("gems", "tributed (score)", "score", 0), ("gems", "carried at the end", "carried_end", 0),
    ("loss", "kills", "kills", 1), ("loss", "deaths", "deaths", 1), ("loss", "deaths to monsters", "deaths_camp", 1),
    ("loss", "deaths in own zone", "deaths_own", 1), ("loss", "deaths in mid zone", "deaths_mid", 1),
    ("loss", "deaths in enemy zone", "deaths_enemy", 1), ("loss", "deaths, rounds 1-500", "deaths_early", 1),
    ("loss", "deaths, rounds 501-1000", "deaths_midgame", 1), ("loss", "deaths, after 1000", "deaths_late", 1),
    ("loss", "carried gems handed to enemy champions", "bag_lost_champ", 0),
    ("loss", "carried gems destroyed by monsters", "bag_lost_camp", 0), ("loss", "share of champion-rounds dead", "dead_share", 3),
    ("obj", "camp clears", "clears", 1), ("obj", "captures", "cap_n", 1), ("obj", "distinct groups captured", "groups_capped", 1),
    ("obj", "our clears captured by them", "stolen", 1), ("obj", "tributes", "sub_n", 1), ("obj", "mean tribute size", "sub_mean", 1),
    ("obj", "first capture (round)", "first_cap", 0), ("obj", "first tribute (round)", "first_sub", 0),
    ("obj", "altar locks bought", "locks", 1), ("obj", "wards per 100 rounds", "wards_100", 1),
    ("obj", "first item (round)", "first_item", 0), ("obj", "gold spent", "spent_gold", 0), ("obj", "gold earned", "gold_rend", 0),
]


OUTCOME = {"score", "col_rend", "gold_rend", "sub_n", "spent_gold", "cap_n", "clears"}  # results, not causes


def report(games, title, who, mode, extra=None):
    L = [f"# {title}", ""]
    W = [g for g in games if g["win"]]
    Ls = [g for g in games if not g["win"]]
    n = len(games)
    L.append(f"Generated {time.strftime('%Y-%m-%d %H:%M')} by tools/lab/gamerep.py. \"us\" = {who}. {n} games "
             f"({len(W)} won, {len(Ls)} lost). Means per game; gap = us - them; [lo, hi] = 95% CI over "
             f"{'maps' if mode == 'local' else 'games'}; * = beyond noise (|z| >= 3).")
    if extra:
        L += [""] + extra
    bad = [g for g in games if g.get("check")]
    if bad:
        L += ["", f"!! {len(bad)} games fail gamefeat's self-check against their statistics (first: "
                  f"{bad[0].get('mid', bad[0]['cluster'])}: {'; '.join(bad[0]['check'][:3])}); their features may be wrong."]
    if not games:
        return "\n".join(L + ["", "No games with features."])
    summary_at = len(L)  # the summary (built from the sections below) goes here
    summary = []

    # 1. results
    L += ["", "## 1. Results", ""]
    m, lo, hi, k = ci(games, lambda g: 1.0 if g["win"] else 0.0)
    if mode == "live":  # Wilson score interval: a normal interval leaves [0, 1] at rates like 3 of 50
        z2, w = 1.96 ** 2, sum(g["win"] for g in games)
        c = (w + z2 / 2) / (n + z2)
        h = 1.96 * math.sqrt(w * (n - w) / n + z2 / 4) / (n + z2)
        lo, hi = c - h, c + h
    L.append(f"- Win rate {m:.3f} [{max(0.0, lo):.3f}, {min(1.0, hi):.3f}] over {k} {'maps' if mode == 'local' else 'games'}.")
    for e in ("race", "limit"):
        gs = [g for g in games if g["ended"] == e]
        if gs:
            L.append(f"- Ended by {'a team reaching 1000 tributed gems' if e == 'race' else 'the round-2000 tiebreak'}: "
                     f"{len(gs)} games, {sum(g['win'] for g in gs)} won; median end round {sorted(g['rounds'] for g in gs)[len(gs) // 2]}.")
    for lab, gs in (("losses", Ls), ("wins", W)):
        if gs:
            mg = sorted(abs(g["us"]["score"] - g["them"]["score"]) for g in gs)
            L.append(f"- Margin in {lab}: median {mg[len(mg) // 2]} tributed gems; {sum(x >= 500 for x in mg)} of "
                     f"{len(mg)} by 500 or more; {sum(x < 100 for x in mg)} by under 100.")
    if mode == "live" and len({g["family"] for g in games}) > 1:
        rows = []
        for fam in sorted({g["family"] for g in games}, key=lambda f: min(g.get("t", 0) for g in games if g["family"] == f)):
            gs = [g for g in games if g["family"] == fam]
            rows.append([fam, f"{sum(g['win'] for g in gs)}-{sum(not g['win'] for g in gs)}",
                         f"{mean([g['us']['score'] - g['them']['score'] for g in gs]):+.0f}",
                         f"{mean([gap(g, 'col_rend') for g in gs]):+.0f}", f"{mean([gap(g, 'cap_mid') for g in gs]):+.0f}",
                         f"{mean([val(g['us'], 'dead_share') for g in gs]):.3f}", f"{mean([val(g['us'], 'sub_mean') for g in gs]):.0f}"])
        L += [""] + table(rows, ["set (oldest first)", "W-L", "tributed gap", "collected gap", "mid-capture gap",
                                 "our dead share", "our mean tribute"])
    if mode == "live":
        rows = []
        by = collections.defaultdict(list)
        for g in games:
            by[g["opp"]].append(g)
        for opp, gs in sorted(by.items(), key=lambda kv: -sum(not g["win"] for g in kv[1])):
            rows.append([opp, f"{sum(g['win'] for g in gs)}-{sum(not g['win'] for g in gs)}",
                         f"{mean([g['us']['score'] - g['them']['score'] for g in gs]):+.0f}",
                         f"{mean([gap(g, 'col_rend') for g in gs]):+.0f}", f"{mean([gap(g, 'cap_mid') for g in gs]):+.0f}",
                         f"{mean([gap(g, 'kills') for g in gs]):+.1f}", ", ".join(sorted({g['map'] for g in gs if not g['win']}))])
        L += [""] + table(rows, ["opponent", "W-L", "tributed gap", "collected gap", "mid-capture gap", "kill gap", "maps lost"])
    else:
        rows = []
        for fam in sorted({g["family"] for g in games}):
            gs = [g for g in games if g["family"] == fam]
            rows.append([fam, len(gs), f"{sum(g['win'] for g in gs)}-{sum(not g['win'] for g in gs)}",
                         f"{mean([g['us']['score'] - g['them']['score'] for g in gs]):+.0f}"])
        L += [""] + table(rows, ["map family", "games", "W-L", "tributed gap"])

    # 2. timing
    L += ["", "## 2. When the game is decided", "",
          "Gap at each round (us - them): tributed gems / collected gems."]
    rows = []
    for r in CP:
        row = [f"r{r}"]
        for gs in (Ls, W):
            row.append(f"{mean([gap(g, f'sub_r{r}') for g in gs]):+.0f} / {mean([gap(g, f'col_r{r}') for g in gs]):+.0f}" if gs else "-")
        rows.append(row)
    L += table(rows, ["round", f"losses ({len(Ls)})", f"wins ({len(W)})"])
    lf_l = sorted(g["them"].get("lead_for_good") for g in Ls if g["them"].get("lead_for_good") is not None)
    lf_w = sorted(g["us"].get("lead_for_good") for g in W if g["us"].get("lead_for_good") is not None)
    if lf_l:
        L.append(f"- In losses they led for good from round {lf_l[len(lf_l) // 2]} (median; quartiles {lf_l[len(lf_l) // 4]}-{lf_l[3 * len(lf_l) // 4]}).")
        summary.append(f"- In losses they lead for good from round {lf_l[len(lf_l) // 2]} (median); the "
                       f"collected-gem gap in losses is {mean([gap(g, 'col_r300') for g in Ls]):+.0f} at r300 and "
                       f"{mean([gap(g, 'col_r800') for g in Ls]):+.0f} at r800.")
    if lf_w:
        L.append(f"- In wins we led for good from round {lf_w[len(lf_w) // 2]} (median).")
    cb = [g for g in Ls if g["us"].get("max_lead", 0) >= 150]
    L.append(f"- Thrown leads: {len(cb)} losses where we led by 150+ tributed gems; comebacks: "
             f"{sum(1 for g in W if g['them'].get('max_lead', 0) >= 150)} wins after trailing by 150+.")

    # 3-5. metric tables
    sect = {"gems": "## 3. Where the gems come from (zones from our spawn: own / mid / enemy)",
            "loss": "## 4. What we lose", "obj": "## 5. Camps, banking, vision, shopping"}
    findings = []
    for s, head in sect.items():
        L += ["", head, ""]
        rows = []
        for sec, lab, key, dd in METRICS:
            if sec != s:
                continue
            row = [lab]
            for gs in (Ls, W):
                us_m = mean([val(g["us"], key) for g in gs])
                th_m = mean([val(g["them"], key) for g in gs])
                m, lo, hi, k = ci(gs, lambda g, key=key: gap(g, key))
                star = "*" if abs(z_of(m, lo, hi)) >= 3 else ""
                row += [f"{fmt(us_m, dd)} / {fmt(th_m, dd)}", f"{fmt(m, dd)}{star} [{fmt(lo, dd)}, {fmt(hi, dd)}]"]
                if gs is Ls and k >= 8 and key not in OUTCOME:
                    findings.append((abs(z_of(m, lo, hi)), lab, key, m, lo, hi, dd, us_m, th_m))
            rows.append(row)
        L += table(rows, ["metric", "losses: us / them", "losses: gap [95% CI]", "wins: us / them", "wins: gap [95% CI]"])

    # 6. loss patterns
    L += ["", "## 6. Loss patterns", "", "Share of losses vs share of wins with each tag (a tag common in both is not a cause)."]
    rows = []
    tl = [tags_of(g) for g in Ls]
    tw = [tags_of(g) for g in W]
    for k, desc, _ in TAGS:
        a = sum(k in t for t in tl) / max(1, len(tl))
        b = sum(k in t for t in tw) / max(1, len(tw))
        rows.append((a - b, [k, desc, f"{100 * a:.0f}%", f"{100 * b:.0f}%"]))
    rows.sort(key=lambda r: -r[0])
    L += table([r[1] for r in rows], ["tag", "definition", f"losses ({len(Ls)})", f"wins ({len(W)})"])
    summary.append("- Most loss-specific patterns: " + "; ".join(f"{r[1][0]} ({r[1][2]} of losses vs {r[1][3]} of wins)"
                                                                for r in rows[:3]) + ".")

    # 7. camp groups left to them
    L += ["", "## 7. Camp groups we leave to them", ""]
    left = []
    for g in Ls:
        su, st = g["seat"], ("B" if g["seat"] == "A" else "A")
        for gid, gr in g["groups"].items():
            cu, ct = gr.get(f"cap_{su}", 0), gr.get(f"cap_{st}", 0)
            if ct >= 3 and cu == 0:
                z = gr.get("zone_A", "?")
                if su == "B":
                    z = {"own": "enemy", "enemy": "own"}.get(z, z)
                left.append((gr.get(f"gems_{st}", 0), g["map"], gid, z, ct, gr.get(f"first_{st}"), g.get("opp", "")))
    if left:
        gz = collections.Counter()
        nz = collections.Counter()
        for x in left:
            gz[x[3]] += x[0]
            nz[x[3]] += 1
        L.append(f"Groups captured 3+ times by them and never by us, per lost game ({len(Ls)} losses), by zone seen "
                 f"from our spawn. Their own side is normally theirs; the mid and our zone are the contestable gems.")
        L += [""] + table([[z, f"{nz[z] / max(1, len(Ls)):.1f}", f"{gz[z] / max(1, len(Ls)):.0f}"]
                           for z in ("mid", "own", "enemy", "offwalk", "nomap") if nz[z]],
                          ["zone (ours)", "groups per lost game", "their gems from them per lost game"])
        agg = {}  # (map, group) -> games, their captures, their gems, first captures, opponents (group ids are per map)
        for gem, m, gid, z, ct, fr, op in left:
            if z not in ("mid", "own"):
                continue
            x = agg.setdefault((m, gid), [0, 0, 0.0, [], set(), z])
            x[0] += 1
            x[1] += ct
            x[2] += gem
            x[3].append(fr)
            x[4].add(op)
        if agg:
            lost_on = collections.Counter(g["map"] for g in Ls)
            top = sorted(agg.items(), key=lambda kv: -kv[1][2])[:12]
            summary.append(f"- Contestable groups left to them: {gz['mid'] / max(1, len(Ls)):.0f} mid-zone gems per lost "
                           "game; largest " + ", ".join(f"{m} group {gid} ({gem / n:.0f} gems, {n} lost game{'s' if n > 1 else ''})"
                                                           for (m, gid), (n, ct, gem, fr, ops, z) in top[:3]) + ".")
            L += ["", "Contestable groups (mid or our zone) left to them, by map: the same group id is the same group "
                      "in every game on that map.", ""]
            L += table([[m, gid, z, f"{n}/{lost_on[m]}", f"{ct / n:.1f}", f"{gem / n:.0f}",
                         sorted(fr)[len(fr) // 2], ", ".join(sorted(ops))[:60]]
                        for (m, gid), (n, ct, gem, fr, ops, z) in top],
                       ["map", "group", "zone (ours)", "lost games where it was theirs only / losses on the map",
                        "their captures per game", "their gems per game", "median first capture", "opponents"])
    else:
        L.append("- No group was captured 3+ times by them and never by us in a lost game.")

    # 8. map features
    L += ["", "## 8. Map features", "", "Win rate by tercile of each map feature (low / middle / high)."]
    rows = []
    feats = [("area (W x H)", lambda f: f["W"] * f["H"]), ("champions per team", lambda f: f["T"]),
             ("gems on the map", lambda f: f["gems"]), ("camp groups", lambda f: f["grp"]),
             ("monolith share of gems", lambda f: f["mono"]), ("heavy-group share of gems", lambda f: f["heavy"]),
             ("dash-only share of gems", lambda f: f["dash"]), ("spawn-to-spawn walk", lambda f: f["s2s"] if f["s2s"] is not None else 999),
             ("walk to nearest altar", lambda f: f["alt_d"] if isinstance(f["alt_d"], int) else 999)]
    for lab, fx in feats:
        vals = []
        for g in games:
            mf = mapfeats(g["map_path"]) if g.get("map_path") else None
            if mf:
                vals.append((fx(mf), g["win"]))
        if len(vals) < 15:
            continue
        vals.sort(key=lambda v: v[0])
        k = len(vals)
        parts = [vals[: k // 3], vals[k // 3: 2 * k // 3], vals[2 * k // 3:]]
        rates = [sum(w for _, w in p) / max(1, len(p)) for p in parts]
        hi_i, lo_i = rates.index(max(rates)), rates.index(min(rates))
        pooled = sum(w for _, w in vals) / k
        se = math.sqrt(pooled * (1 - pooled) * (1 / max(1, len(parts[hi_i])) + 1 / max(1, len(parts[lo_i]))))
        zz = (rates[hi_i] - rates[lo_i]) / se if se else 0.0
        rows.append([lab, " / ".join(f"{100 * r:.0f}%" for r in rates),
                     f"{parts[0][-1][0]:g} | {parts[1][-1][0]:g}", f"z {zz:.1f}" + (" *" if zz >= 3 else "")])
    L += table(rows, ["feature", "win rate low / mid / high", "tercile cut points", "best vs worst tercile"])

    # 9. champions
    L += ["", "## 9. Champions (per game)", ""]
    rows = []
    for side, key in (("us", "champs_us"), ("them", "champs_them")):
        by = collections.defaultdict(list)
        for g in games:
            for c in g[key]:
                by[c["name"]].append((c, g["win"]))
        for nm, cs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            if len(cs) < max(3, n // 10):
                continue
            rows.append([side, nm, len(cs), f"{mean([c.get('collected', 0) for c, _ in cs]):.0f}",
                         f"{mean([c.get('deaths', 0) for c, _ in cs]):.1f}", f"{mean([c.get('deaths_camp', 0) for c, _ in cs]):.2f}",
                         f"{mean([c.get('kills', 0) for c, _ in cs]):.1f}", f"{mean([c.get('bag_lost', 0) for c, _ in cs]):.0f}",
                         f"{100 * mean([1.0 if w else 0.0 for _, w in cs]):.0f}%"])
    L += table(rows, ["side", "champion", "games", "collected", "deaths", "monster deaths", "kills", "bags lost", "our win rate"])

    # 10. findings
    L += ["", "## 10. Biggest gaps in our losses (ranked by |z|; outcome totals such as score are left out)", ""]
    findings.sort(key=lambda f: -f[0])
    shown = 0
    for zz, lab, key, m, lo, hi, dd, us_m, th_m in findings:
        if zz < 3 or shown >= 10:
            break
        L.append(f"- {lab}: us {fmt(us_m, dd)} vs them {fmt(th_m, dd)} per lost game (gap {fmt(m, dd)} "
                 f"[{fmt(lo, dd)}, {fmt(hi, dd)}], z {zz:.1f})")
        if shown < 5:
            summary.append(f"- {lab}: us {fmt(us_m, dd)} vs them {fmt(th_m, dd)} per lost game (z {zz:.1f}).")
        shown += 1
    if not shown:
        L.append("- No gap in the losses is beyond noise (|z| >= 3).")

    # summary at the top
    res = [f"- Record {len(W)}-{len(Ls)}; median margin in losses "
           f"{sorted(abs(g['us']['score'] - g['them']['score']) for g in Ls)[len(Ls) // 2] if Ls else 0} tributed gems."]
    if mode == "live" and len({g["family"] for g in games}) > 1:
        fams = sorted({g["family"] for g in games}, key=lambda f: min(g.get("t", 0) for g in games if g["family"] == f))
        res.append("- By set, oldest first: " + ", ".join(
            f"{f} {sum(g['win'] for g in games if g['family'] == f)}-{sum(not g['win'] for g in games if g['family'] == f)}"
            for f in fams) + ".")
    L[summary_at:summary_at] = ["", "## Summary (details in the numbered sections)", ""] + res + summary

    # 11. worst losses
    L += ["", "## 11. Worst losses (inspect these)", ""]
    worst = sorted(Ls, key=lambda g: g["us"]["score"] - g["them"]["score"])[:10]
    L += table([[g["map"], g.get("opp", ""), g["seat"], f"{g['us']['score']}-{g['them']['score']}", g["rounds"],
                 g["them"].get("lead_for_good", "-"), ", ".join(tags_of(g)) or "-", g.get("mid", g["cluster"])]
                for g in worst], ["map", "opponent", "our seat", "score", "end round", "they led for good from", "tags", "game"])
    return "\n".join(L) + "\n"


def paired(games, cand, base):
    """CAND vs BASE in the same seat on the same map (each played the other): what CAND does differently."""
    by = collections.defaultdict(dict)
    for g in games:
        by[g["map"]][g["seat"]] = g
    rows, out = [], []
    keys = ["col_r300", "col_r500", "col_rend", "cap_mid", "cap_own", "loot_gems", "deaths", "deaths_camp",
            "bag_lost_champ", "dead_share", "stolen", "sub_mean", "carried_end", "wards_100", "score"]
    for k in keys:
        diffs = []
        for m, d in by.items():
            if "A" in d and "B" in d:  # CAND in seat A (game 1) vs BASE in seat A (game 2, where CAND is B)
                a1, a2 = val(d["A"]["us"], k), val(d["B"]["them"], k)
                b1, b2 = val(d["B"]["us"], k), val(d["A"]["them"], k)
                if None not in (a1, a2, b1, b2):
                    diffs.append(((a1 - a2) + (b1 - b2)) / 2)
        if len(diffs) < 8:
            continue
        mm = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((x - mm) ** 2 for x in diffs) / (len(diffs) - 1))
        h = 1.96 * sd / math.sqrt(len(diffs))
        star = "*" if h and abs(mm) / (h / 1.96) >= 3 else ""
        rows.append([k, len(diffs), f"{mm:+.2f}{star}", f"[{mm - h:+.2f}, {mm + h:+.2f}]"])
    if rows:
        out = ["", f"## 12. What {cand} does differently from {base} (same map, same seat)", "",
               "Mean over maps of (CAND's value - BASE's value) in the same seat, each playing the other: for close "
               "variants this isolates the behaviour change. * = beyond noise."] + table(
            rows, ["metric", "maps", "CAND - BASE", "95% CI"])
    return out


def main():
    a = sys.argv[1:]
    out = None
    if "--out" in a:
        i = a.index("--out")
        out = a[i + 1]
        del a[i:i + 2]
    sets = None
    if "--set" in a:
        i = a.index("--set")
        sets = set(a[i + 1].split(","))
        del a[i:i + 2]
    if a and a[0] == "--live":
        dirs = a[1:]
        games, total = load_live(dirs)
        title = "Live games: " + ", ".join(os.path.basename(d.rstrip("/")) for d in dirs)
        text = report(games, title, "our live submission", "live",
                      [f"Sets: {', '.join(dirs)}; {len(games)} of {total} matches have statistics."])
    elif len(a) == 2:
        games, total, (nc, hc, nb, hb) = load_local(a[0], a[1], sets)
        rows = [(g["map"], g["family"], (2 if g["win"] else 0)) for g in games]
        pairs = collections.defaultdict(list)
        for g in games:
            pairs[g["map"]].append(g)
        pr = [(m, gs[0]["family"], sum(g["win"] for g in gs) / 2, 0, 0) for m, gs in pairs.items() if len(gs) == 2]
        st = abstat.summarize(pr, boot=200) if pr else None
        extra = [f"Local games between {nc}@{hc} (us) and {nb}@{hb}: {len(games)} of {total} have features"
                 + (f"; map-pair score {st['score']:.3f} [{st['lo']:.3f}, {st['hi']:.3f}] over {st['n']} maps." if st else ".")]
        if len(games) < total:
            extra.append(f"Missing features for {total - len(games)} games: run `python3 -I tools/lab/restat.py` on their run dirs "
                         f"(listed by `python3 -I tools/lab/gamerep.py --runs {a[0]} {a[1]}`).")
        text = report(games, f"Local games: {nc} vs {nb}", nc, "local", extra)
        text += "\n".join(paired(games, nc, nb)) + "\n"
    elif len(a) == 3 and a[0] == "--runs":
        (nc, hc), (nb, hb) = abindex.resolve(a[1]), abindex.resolve(a[2])
        ix = abindex.Index({hc, hb}, screen=False, rich=True)
        need = sorted({rec["src"][4:] for rec in ix.games.values() if "rich" not in rec and rec["src"].startswith("abl:")})
        print("\n".join(os.path.join(abindex.ABL, r) for r in need))
        return
    else:
        print(__doc__)
        sys.exit(1)
    if out:
        open(out, "w").write(text)
        print(f"wrote {out} ({text.count(chr(10))} lines)")
    else:
        print(text)


if __name__ == "__main__":
    main()
