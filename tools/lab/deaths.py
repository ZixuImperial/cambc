#!/usr/bin/env python3
"""Death autopsy: why our champions die, one row per death of our champion, from the engine's replay of every turn.

usage: python3 -I tools/lab/deaths.py GAME|SETDIR... --out FILE [--jobs 4] [--us A|B]
       python3 -I tools/lab/deaths.py --from-tsv ALL.tsv --out FILE [--jobs 4]   (10 Nov: gameindex.py lookup --out DIR's all.tsv; each row's
       our_seat (a|b) is used per game, so both seats go in one run; rows with seat '?' are skipped; columns read by header name)
  GAME / SETDIR as in `replay.py report` (a live set dir expands to its games; us = the live side from matches.txt).
  Default (no GAME): the v252 live sets unr_1028_1746 1809 1817 1853 1923 in /data/zw4424/plat.
  Writes FILE (markdown summary) and FILE.csv (one row per death; FILE with .md replaced by .csv if it ends in .md).

Columns (R = death round; "hostile" = damage from enemy champions, from their attacks and casts):
  hp_r10/r5/r3/r1: victim HP % of max at the start of its turn in round R-k (latest turn at or before R-k)
  first_dmg_ago: R minus the first round in [R-10, R] in which the victim took hostile damage (-1: none)
  dmg_1/3/5: hostile damage taken in rounds [R-k+1, R]; attackers_3: distinct enemy champions hitting it in [R-2, R]
  us3/us6/us8, them3/them6/them8: living bodies within 3/6/8 tiles of the victim at R-3 (ours excludes the victim);
  us_hp8/them_hp8: their HP sum within 8 (ours includes the victim)
  v_spent/k_spent, v_items/k_items: gold spent and items bought up to R by victim and killer; v_str/k_str etc. at R-1
  act_1..act_5: classify_all activity of the victim's last 5 living turns before R (act_1 = latest);
  mv_1..mv_5: its own move that turn vs the nearest enemy at that turn's start: T toward (D: by a dash), A away,
  = same distance, - no move
  dealt_5: hostile damage the victim dealt in its last 5 turns
  channel_r1: channel type at R-1 (recall/tribute/capture/teleport/lock or -); ch_enemy6: an enemy within 6 when it began
  dash_2: a dash cast in its last 2 turns; dash_closer: that turn ended nearer the nearest enemy than it began
  mate_dmg3: hostile damage dealt in [R-2, R] by teammates within 8 of the victim
  Stance (nova's set_priority, a 'p' action: 40 = FLEE OR under 50% HP with a foe within 6 (brain.cpp DYN_PRIO; b909 2 Nov: a low-HP
  fighter sets 40 too), 35 = finishing a low focus, other = the slot's base). p40_lowhp: 1 when the last 40 started at under 50% HP, so it may
  be a fight at low HP, not a flee; 0: it started at 50%+ HP, a FLEE for sure.
  last_p40_ago: R minus the round it last set 40 (-1: never); p40_runs_15: 40-episodes active in [R-15, R]
  drop_ago: R minus the round of its latest 40 -> base drop (-1: none); mv_after_drop: its moves (T/A/=/-, oldest
  first, D = a dash that ended closer) from the drop's turn until it set 40 again or died
  dash_ready_unused: of its last 2 living turns, how many began with a dash slot ready (cooldown 0; dash slots from
  micro.py's kit table) and cast no dash ('' = no dash in its kit); dash_escape: in such a turn, a legal dash landing
  (up to 2 steps, over holes not walls; not on a wall, hole, altar, enemy spawn or living body)
  ended farther from every enemy champion within 4 than its start ('' = no enemy within 4 or no ready-unused turn)
  last2_stood_vs_melee: of its last 2 living turns, how many began with a melee enemy within 2 and did not end farther
  from the nearest melee enemy (attacked or stood or closed in); counted for every victim, tagged for ranged ones
Tags (a death may carry several):
  ONE_SHOT  hp >= 70% at R-1, or dead within 2 rounds of the first hostile damage
  BLEED     first hostile damage >= 4 rounds before death
  NO_RETREAT  BLEED and at least half of its moves in the last 5 turns went toward or kept the distance (T or =)
  CHANNEL_DEATH  a CHOSEN channel at R-1 (tribute/capture/teleport/lock, or a recall kept with its timer counting down; not a
                 SPIN_SELF lazy recall restarted every turn: replay.chosen_channel);  DASH_IN  dashed in the last 2 turns and ended closer
  ABANDONED  no teammate within 8 at R-3;  OUTNUMBERED_LOCAL  them6 > us6 + 1 (the victim counts on our side)
  FARM_CAUGHT  farm or capture in its last 3 turns;  OUTSCALED  killer gold spent >= 1.5x the victim's (and >= 100)
  MONSTER  killed by a camp
  REENGAGE  a 40 -> base drop within 8 rounds before death, then a T move or a dash closer
  CAUGHT_RANGED  a ranged victim with last2_stood_vs_melee >= 1
  ESCAPE_DASH_UNUSED  in one of its last 2 living turns its dash was ready and not cast, and a dash landing existed
            that ended farther from every enemy champion within 4 (dash_escape)
Per game (summary): every 40-episode of our bodies; it reverses when it ends with a 40 -> base drop followed by a T move
  within 5 rounds; death-after-reversal = that body dies within 10 rounds of the T move. Shield-absorbed attacks: basic
  attacks on an enemy champion that changed no HP while the target had a shield (decoded effects list HP changes only).
"""
import collections
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as R  # noqa: E402

DEFAULT_SETS = ["unr_1028_1746", "unr_1028_1809", "unr_1028_1817", "unr_1028_1853", "unr_1028_1923"]
CH_NAME = {0: "-", 1: "recall", 2: "tribute", 3: "capture", 4: "teleport", 5: "lock"}
TAGS = ["ONE_SHOT", "BLEED", "NO_RETREAT", "CHANNEL_DEATH", "DASH_IN", "ABANDONED", "OUTNUMBERED_LOCAL", "FARM_CAUGHT",
        "OUTSCALED", "MONSTER", "REENGAGE", "CAUGHT_RANGED", "ESCAPE_DASH_UNUSED"]
RANGED = {"cassi", "vesper_vale", "prism", "stellar", "tavi", "willow"}  # GameRules.md attack types; the rest are melee
KITS = "/data/zw4424/micro_kits.json"  # micro.py's range table: champion type -> spells by slot (atype 6 = dash)
FLEE, FINISH = 40, 35  # nova's set_priority stance markers: 40 = FLEE or low HP with a foe near (see p40_lowhp), 35 = finishing a low focus, other = calm/fight
COLS = ["game", "map", "opponent", "result", "round", "victim", "killer", "kill_kind", "zone", "bag",
        "hp_r10", "hp_r5", "hp_r3", "hp_r1", "first_dmg_ago", "dmg_1", "dmg_3", "dmg_5", "attackers_3",
        "us3", "us6", "us8", "them3", "them6", "them8", "us_hp8", "them_hp8",
        "v_spent", "k_spent", "v_items", "k_items", "v_maxhp", "k_maxhp", "v_str", "k_str", "v_focus", "k_focus",
        "act_1", "act_2", "act_3", "act_4", "act_5", "mv_1", "mv_2", "mv_3", "mv_4", "mv_5", "dealt_5",
        "channel_r1", "channel_kept", "ch_enemy6", "dash_2", "dash_closer", "mate_dmg3",
        "last_p40_ago", "p40_runs_15", "p40_lowhp", "drop_ago", "mv_after_drop", "last2_stood_vs_melee", "dash_ready_unused",
        "dash_escape", "tags", "pair_dup"]


def end_pos(t):
    """Where a turn ended: walks and dash landings (a teleport only starts a 3-turn channel; the body arrives later)."""
    x, y = t[2], t[3]
    for a in t[-1]:
        if a[0] == "m":
            x, y = a[1], a[2]
        elif a[0] == "c" and a[2] == 6:
            x, y = a[3], a[4]
    return x, y


def turn_at(ts, r):
    """Latest turn of a body at or before round r."""
    best = None
    for t in ts:
        if t[0] > r:
            break
        best = t
    return best


def game_deaths(spec, us=None):
    try:
        g = R.load(spec, us)
    except SystemExit as e:
        return {"spec": spec, "error": str(e)}
    if g.final.get("outcome") not in (1, 2):
        return {"spec": spec, "error": f"no result (outcome {g.final.get('outcome')} at round {g.last_round})"}
    ci = g.ci
    usv = g.us
    win = {1: 0, 2: 1}[g.final["outcome"]] == usv
    acts = R.classify_all(g)
    # hostile damage per (round, victim): [(attacker, dmg, attacker x, y)]
    taken = collections.defaultdict(list)
    spent = collections.defaultdict(list)  # body -> [(round, cumulative gold, cumulative items)]
    for t in g.turns:
        for v, dmg in R.hostile_hits(g, t):
            taken[(t[0], v)].append((t[1], dmg, t[2], t[3]))
        for a in t[-1]:
            if a[0] == "s":
                prev = spent[t[1]][-1] if spent[t[1]] else (0, 0, 0)
                spent[t[1]].append((t[0], prev[1] + a[3], prev[2] + sum(n for _, n in a[1])))

    def spent_at(c, r):
        out = (0, 0)
        for rr, gold, items in spent.get(c, []):
            if rr > r:
                break
            out = (gold, items)
        return out

    try:
        kits = json.load(open(KITS))
    except (OSError, ValueError):
        kits = {}
    blocked = {(x, y) for y, row in enumerate(g.rows) for x, ch in enumerate(row) if ch == "#"}
    holes = {(x, y) for y, row in enumerate(g.rows) for x, ch in enumerate(row) if ch == "o"}
    altars = {tuple(a[:2]) for a in g.altars}

    def dash_slots(c):
        """Dash slots of a body's kit and the dash's steps (GameRules: up to 2; the kit table stores range 0)."""
        sp = kits.get(str(g.bodies[c].get("type")), {}).get("spells", {})
        return [int(s) for s, v in sp.items() if v.get("atype") == 6], 2

    def escape_landing(t, c, steps):
        """A legal dash landing from t's start that ends farther from every enemy champion within 4."""
        team = g.team_of[c]
        pos = alive_pos(t)
        foes = [(u[2], u[3]) for o, u in pos.items() if g.team_of[o] != team and R.cheb(t[2], t[3], u[2], u[3]) <= 4]
        if not foes:
            return None
        occ = {(u[2], u[3]) for o, u in pos.items() if o != c}
        sx0, sy0, sx1, sy1 = g.spawn[1 - team]
        frontier, seen = {(t[2], t[3])}, {(t[2], t[3])}
        for _ in range(steps):
            nxt = set()
            for x, y in frontier:
                for dx, dy in R.DIRS8:
                    p = (x + dx, y + dy)
                    if 0 <= p[0] < g.W and 0 <= p[1] < g.H and p not in blocked and p not in seen:
                        seen.add(p)
                        nxt.add(p)
            frontier = nxt
        for p in seen:
            if p in holes or p in altars or p in occ or (sx0 <= p[0] < sx1 and sy0 <= p[1] < sy1):
                continue
            if all(R.cheb(p[0], p[1], fx, fy) > R.cheb(t[2], t[3], fx, fy) for fx, fy in foes):
                return 1
        return 0

    def alive_pos(t):
        """Living bodies at the moment turn t starts, as turn rows holding where each stands then (replay.positions_before)."""
        return {c: [*u[:2], x, y, *u[4:]] for c, (x, y, u) in g.positions_before(t).items() if u[ci["alive"]] and x >= 0}

    def nearest_enemy_d(team, x, y, pos):
        ds = [R.cheb(x, y, u[2], u[3]) for c, u in pos.items() if g.team_of[c] != team]
        return min(ds) if ds else None

    def mv_of(t, melee=False):
        """This turn's own move vs the nearest (melee) enemy at this turn's start: T, D (a dash that closed in), A, =, -."""
        ex, ey = end_pos(t)
        if (ex, ey) == (t[2], t[3]):
            return "-"
        pos = {c: u for c, u in alive_pos(t).items() if not melee or g.bodies[c]["name"] not in RANGED}
        d0, d1 = nearest_enemy_d(usv, t[2], t[3], pos), nearest_enemy_d(usv, ex, ey, pos)
        if d0 is None:
            return "?"
        if d1 < d0:
            return "D" if any(a[0] == "c" and a[2] < len(R.ABILITY) and R.ABILITY[a[2]] == "dash" for a in t[-1]) else "T"
        return "A" if d1 > d0 else "="

    # nova's FLEE stance episodes of our bodies: {body: [[start, end or None, value it dropped to]]}
    episodes = collections.defaultdict(list)
    for c, ts in g.by_champ.items():
        if g.team_of[c] != usv:
            continue
        cur = None
        for t in ts:
            for a in t[-1]:
                if a[0] != "p":
                    continue
                if a[1] == FLEE and cur != FLEE:
                    episodes[c].append([t[0], None, None, int(t[ci["hp"]] < 0.5 * max(1, t[ci["maxHp"]]))])
                elif cur == FLEE and a[1] != FLEE:
                    episodes[c][-1][1:3] = [t[0], a[1]]
                cur = a[1]
    died = collections.defaultdict(list)
    for e in g.events:
        if e[1] == "death":
            died[e[2]].append(e[0])
    def next_flee(c, en):
        """Round of the body's next FLEE start after a drop at round en (the window for 'moves after the drop')."""
        return next((st for st, *_ in episodes[c] if st > en), 10 ** 9)

    ep_stats = collections.Counter()
    for c, eps in episodes.items():
        for st, en, v, *_ in eps:
            ep_stats["episodes"] += 1
            if en is None or v == FINISH:
                continue
            ep_stats["base_drops"] += 1
            hi = min(en + 5, next_flee(c, en) - 1)
            rev = next((t[0] for t in g.by_champ[c] if en <= t[0] <= hi and t[ci["alive"]] and t[2] >= 0
                        and mv_of(t) in "TD"), None)
            if rev is not None:
                ep_stats["reversals"] += 1
                ep_stats["died_after_reversal"] += any(rev <= d <= rev + 10 for d in died[c])
    # basic attacks on enemy champions, and those that changed no HP while the target had a shield, per side
    shield = {"attacks": [0, 0], "absorbed": [0, 0]}
    for t in g.turns:
        side = int(g.team_of[t[1]] != usv)  # 0 = us, 1 = them
        for a in t[-1]:
            if a[0] != "a" or a[1] != 1 or g.team_of.get(a[2], -1) == g.team_of[t[1]]:
                continue
            shield["attacks"][side] += 1
            if not any(k == 1 and i == a[2] and dd < 0 for k, i, dd in a[5]):
                u = g.positions_at(t[0]).get(a[2])
                shield["absorbed"][side] += bool(u and u[ci["shield"]] > 0)

    rows = []
    gid = g.meta["match"] if g.meta.get("match") else spec  # 9 Nov (Deep, v637 digest): the full live id; an 8-char prefix is shared by games of one group
    for e in g.events:
        if e[1] != "death" or g.team_of.get(e[2]) != usv:
            continue
        r, v, kind, killer, bag, dx, dy = e[0], e[2], e[3], e[4], e[5], e[6], e[7]
        ts = g.by_champ.get(v, [])
        row = {"game": gid, "map": g.meta.get("map", "?"), "opponent": g.team_name(1 - usv), "result": "win" if win else "loss",
               "round": r, "victim": g.who(v), "killer": g.who(killer) if kind == 1 and killer >= 0 else
               ("camp" if kind == 2 else "-"), "kill_kind": {1: "champ", 2: "camp"}.get(kind, str(kind)),
               "zone": g.zone(dx, dy, usv) if dx >= 0 else "-", "bag": bag, "_v": v}
        for k in (10, 5, 3, 1):
            t = turn_at(ts, r - k)
            row[f"hp_r{k}"] = round(100 * t[ci["hp"]] / max(1, t[ci["maxHp"]])) if t and t[ci["alive"]] else ""
        first = next((rr for rr in range(r - 10, r + 1) if taken.get((rr, v))), None)
        row["first_dmg_ago"] = r - first if first is not None else -1
        for k in (1, 3, 5):
            row[f"dmg_{k}"] = round(sum(d for rr in range(r - k + 1, r + 1) for _, d, _, _ in taken.get((rr, v), [])))
        row["attackers_3"] = len({a for rr in range(r - 2, r + 1) for a, _, _, _ in taken.get((rr, v), [])})
        t3 = turn_at(g.by_champ[v], r - 3)
        pos3 = alive_pos(t3) if t3 else {}
        me3 = pos3.get(v)
        cx, cy = (me3[2], me3[3]) if me3 else (dx, dy)
        for rad in (3, 6, 8):
            row[f"us{rad}"] = sum(1 for c, u in pos3.items() if c != v and g.team_of[c] == usv and R.cheb(cx, cy, u[2], u[3]) <= rad)
            row[f"them{rad}"] = sum(1 for c, u in pos3.items() if g.team_of[c] != usv and R.cheb(cx, cy, u[2], u[3]) <= rad)
        row["us_hp8"] = sum(u[ci["hp"]] for c, u in pos3.items() if g.team_of[c] == usv and R.cheb(cx, cy, u[2], u[3]) <= 8)
        row["them_hp8"] = sum(u[ci["hp"]] for c, u in pos3.items() if g.team_of[c] != usv and R.cheb(cx, cy, u[2], u[3]) <= 8)
        vs, vi = spent_at(v, r)
        ks, ki = spent_at(killer, r) if kind == 1 and killer >= 0 else ("", "")
        row.update(v_spent=vs, k_spent=ks, v_items=vi, k_items=ki)
        tv = turn_at(ts, r - 1)
        tk = turn_at(g.by_champ.get(killer, []), r - 1) if kind == 1 and killer >= 0 else None
        for name, col in (("maxhp", "maxHp"), ("str", "strength"), ("focus", "focus")):
            row[f"v_{name}"] = tv[ci[col]] if tv else ""
            row[f"k_{name}"] = tk[ci[col]] if tk else ""
        last = [t for t in ts if t[0] < r and t[ci["alive"]] and t[2] >= 0][-5:][::-1]
        moves = []
        for i in range(5):
            t = last[i] if i < len(last) else None
            row[f"act_{i + 1}"] = acts.get((t[0], v), "") if t else ""
            mv = mv_of(t) if t else ""
            if mv not in ("", "-"):
                moves.append(mv)
            row[f"mv_{i + 1}"] = mv
        row["dealt_5"] = round(sum(d for t in last for _, d in R.hostile_hits(g, t)))
        raw = tv[ci["chType"]] if tv and tv[ci["alive"]] else 0
        row["channel_r1"] = CH_NAME.get(raw, str(raw))
        ch = R.chosen_channel(g, ts, r)  # 1 Nov: a recall counts only when kept (SPIN_SELF restarts a lazy recall every turn)
        row["channel_kept"] = int(bool(ch))
        row["ch_enemy6"] = ""
        if ch:
            st = None  # the turn the channel began: walk back while the same channel was running
            for t in reversed([t for t in ts if t[0] <= r - 1]):
                if t[ci["chType"]] != ch:
                    break
                st = t
            if st is not None:
                nd = nearest_enemy_d(usv, st[2], st[3], alive_pos(st))
                row["ch_enemy6"] = int(nd is not None and nd <= 6)
        dash, closer = 0, 0
        for t in last[:2]:
            if any(a[0] == "c" and a[2] < len(R.ABILITY) and R.ABILITY[a[2]] == "dash" for a in t[-1]):
                dash = 1
                closer |= int(mv_of(t) == "D")
        row["dash_2"], row["dash_closer"] = dash, closer
        eps = [x for x in episodes.get(v, []) if x[0] <= r]
        row["last_p40_ago"] = r - eps[-1][0] if eps else -1
        row["p40_runs_15"] = sum(1 for st, en, *_ in eps if en is None or en >= r - 15)
        row["p40_lowhp"] = eps[-1][3] if eps else ""
        drops = [en for st, en, val, *_ in eps if en is not None and en <= r and val != FINISH]
        row["drop_ago"] = r - drops[-1] if drops else -1
        hi = min(r, next_flee(v, drops[-1])) if drops else r
        row["mv_after_drop"] = "".join(mv_of(t) for t in ts if drops[-1] <= t[0] < hi and t[ci["alive"]]
                                       and t[2] >= 0) if drops else ""
        stood = 0
        for t in last[:2]:
            pos = {c: u for c, u in alive_pos(t).items() if g.bodies[c]["name"] not in RANGED}
            d0 = nearest_enemy_d(usv, t[2], t[3], pos)
            if d0 is not None and d0 <= 2 and mv_of(t, melee=True) != "A":
                stood += 1
        row["last2_stood_vs_melee"] = stood
        slots, steps = dash_slots(v)
        row["dash_ready_unused"], row["dash_escape"] = ("", "") if not slots else (0, "")
        for t in last[:2] if slots else []:
            cast = {a[1] for a in t[-1] if a[0] == "c"}
            if any(t[ci[f"cd{s}"]] == 0 and s not in cast for s in slots):
                row["dash_ready_unused"] += 1
                esc = escape_landing(t, v, steps)
                if esc is not None:
                    row["dash_escape"] = max(esc, row["dash_escape"] or 0)
        md = 0
        for t in g.turns:
            if r - 2 <= t[0] <= r and t[1] != v and g.team_of[t[1]] == usv and R.cheb(t[2], t[3], cx, cy) <= 8:
                md += sum(d for _, d in R.hostile_hits(g, t))
        row["mate_dmg3"] = round(md)
        tags = []
        h1 = row["hp_r1"]
        fd = row["first_dmg_ago"]
        if kind == 1 and ((h1 != "" and h1 >= 70) or 0 <= fd <= 2):
            tags.append("ONE_SHOT")
        if fd >= 4:
            tags.append("BLEED")
            if moves and sum(m in "TD=" for m in moves) * 2 >= len(moves):
                tags.append("NO_RETREAT")
        if ch:
            tags.append("CHANNEL_DEATH")
        if dash and closer:
            tags.append("DASH_IN")
        if row["us8"] == 0:
            tags.append("ABANDONED")
        if row["them6"] > row["us6"] + 1:
            tags.append("OUTNUMBERED_LOCAL")
        if any(row[f"act_{i}"] in ("farm", "capture", "hold") for i in (1, 2, 3)):
            tags.append("FARM_CAUGHT")
        if kind == 1 and ks != "" and ks >= 100 and ks >= 1.5 * vs:
            tags.append("OUTSCALED")
        if kind == 2:
            tags.append("MONSTER")
        if 0 <= row["drop_ago"] <= 8 and any(m in "TD" for m in row["mv_after_drop"]):
            tags.append("REENGAGE")
        if g.bodies[v]["name"] in RANGED and stood:
            tags.append("CAUGHT_RANGED")
        if row["dash_escape"] == 1:
            tags.append("ESCAPE_DASH_UNUSED")
        row["tags"] = " ".join(tags)
        rows.append(row)
    # 9 Nov (owner): a linked C&I pair death counts once (GR :381/:442): one row of the pair is marked pair_dup = 1.
    # 10 Nov (Combat, Fish 01a1c322 r228: Marcella's spell hit Issac, yet Cassi's row was kept with her linked 600 HP as dmg_1): keep the row of
    # the body the foe actually targeted that round (attacks aimed at it, plus casts whose largest effect fell on it); a tie keeps the larger
    # death-round damage, then Cassi (the old rule). Linked HP moves between the two, so damage alone can't tell. One row per pair as before.
    def aimed(body, mate, rr):
        """foe actions in round rr aimed at BODY: attacks with it as target, casts whose target tile is nearer BODY than MATE (<= 1 away).
        The effect list can't tell: the link moves HP to the partner (Cassi -600 linked v Issac -170 hit, 01a1c322 r228)."""
        sc, pos = 0, g.positions_at(rr - 1)  # the death round reads both bodies off the board (-1, -1)
        pb, pm = pos.get(body), pos.get(mate)
        for t in g.turns:
            if t[0] != rr or g.team_of.get(t[1]) == usv:
                continue
            for x in t[-1]:
                if x[0] == "a" and x[1] == 1 and x[2] == body:
                    sc += 1
                elif x[0] == "c" and pb and any(kk == 1 and i in (body, mate) and d < 0 for kk, i, d in x[7]):
                    db = R.cheb(x[3], x[4], pb[2], pb[3])
                    dm = R.cheb(x[3], x[4], pm[2], pm[3]) if pm else 99
                    if db <= 1 and db < dm:
                        sc += 1
        return sc
    for r in rows:
        r["pair_dup"] = 0
    by_round = {}
    for r in rows:
        nm = str(r["victim"]).lower()
        if "cassi" in nm or "issac" in nm:
            by_round.setdefault(r["round"], []).append(r)
    for rr, pr in by_round.items():
        if len(pr) < 2:
            continue
        ids = [x["_v"] for x in pr]
        key = lambda x: (aimed(x["_v"], next((i for i in ids if i != x["_v"]), -1), rr), x.get("dmg_1") or 0, "cassi" in str(x["victim"]).lower())  # noqa: E731
        keep = max(pr, key=key)
        for x in pr:
            x["pair_dup"] = int(x is not keep)
    for r in rows:
        r.pop("_v", None)
    return {"spec": spec, "win": win, "rows": rows, "flee": dict(ep_stats), "shield": shield}


def _job(a):
    return game_deaths(*a)


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


def main():
    a = sys.argv[1:]

    def opt(name, default=None, cast=str):
        if name in a:
            i = a.index(name)
            val = cast(a[i + 1])
            del a[i:i + 2]
            return val
        return default
    out, jobs, us, ftsv = opt("--out"), opt("--jobs", 4, int), opt("--us"), opt("--from-tsv")
    if not out or any(x.startswith("--") for x in a):
        print(__doc__)
        sys.exit(1)
    if ftsv:
        with open(ftsv, newline="") as f:
            work = [(r["path"], r["our_seat"].upper()) for r in csv.DictReader(f, delimiter="\t") if r.get("our_seat", "").lower() in ("a", "b") and r.get("path")]
    else:
        specs = a or [os.path.join(R.PLAT, s) for s in DEFAULT_SETS]
        games = R.expand_specs(specs)
        work = [(s, us) for s in games]
    if jobs > 1 and len(work) > 1:
        import multiprocessing
        with multiprocessing.get_context("fork").Pool(min(jobs, len(work))) as pool:
            res = pool.map(_job, work)
    else:
        res = [_job(w) for w in work]
    bad = [x for x in res if "error" in x]
    res = [x for x in res if "error" not in x]
    rows = [r for x in res for r in x["rows"]]
    csv_path = out[:-3] + ".csv" if out.endswith(".md") else out + ".csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    nW = sum(x["win"] for x in res)
    nL = len(res) - nW
    dW = [r for r in rows if r["result"] == "win"]
    dL = [r for r in rows if r["result"] == "loss"]
    L = [f"# Death autopsy: {len(rows)} deaths of our champions in {len(res)} games ({nW}-{nL})", "",
         f"Generated by tools/lab/deaths.py; one row per death in {csv_path}; {len(bad)} games not read. "
         f"Tag definitions are in the script's docstring.", ""]
    for x in bad[:10]:
        L.append(f"- not read: {x['spec']}: {x['error'][:160]}")
    pL, pW = sum(r["pair_dup"] for r in dL), sum(r["pair_dup"] for r in dW)
    L += [f"Deaths per game: losses {len(dL) / max(1, nL):.1f}, wins {len(dW) / max(1, nW):.1f}; pair-adjusted (a C&I pair death once, owner 9 Nov): "
          f"losses {(len(dL) - pL) / max(1, nL):.1f}, wins {(len(dW) - pW) / max(1, nW):.1f} ({pL + pW} Issac rows marked pair_dup).", "",
          "## Tags (share of deaths; a death can carry several)", "",
          "| tag | losses | per loss | wins | per win |", "|---|---|---|---|---|"]
    for tg in TAGS:
        cl = sum(tg in r["tags"].split() for r in dL)
        cw = sum(tg in r["tags"].split() for r in dW)
        L.append(f"| {tg} | {cl} ({pct(cl, len(dL))}) | {cl / max(1, nL):.2f} | {cw} ({pct(cw, len(dW))}) | {cw / max(1, nW):.2f} |")
    untag = [sum(not r["tags"] for r in rs) for rs in (dL, dW)]
    L.append(f"| (none) | {untag[0]} ({pct(untag[0], len(dL))}) | | {untag[1]} ({pct(untag[1], len(dW))}) | |")

    def name(who):
        return who.split(":", 1)[1].rsplit("(", 1)[0] if ":" in who else who
    L += ["", "## FLEE stance episodes (all our 40-episodes, not only deaths)", "",
          "| | games | episodes/game | 40->base drops | reversal % of drops | died within 10 after reversal % |",
          "|---|---|---|---|---|---|"]
    for lab, wn in (("losses", False), ("wins", True)):
        gs = [x for x in res if x["win"] == wn]
        f = collections.Counter()
        for x in gs:
            f.update(x["flee"])
        L.append(f"| {lab} | {len(gs)} | {f['episodes'] / max(1, len(gs)):.1f} | {f['base_drops']} | "
                 f"{pct(f['reversals'], f['base_drops'])} | {pct(f['died_after_reversal'], f['reversals'])} |")
    L += ["", "## Basic attacks on champions fully absorbed by a shield", "",
          "| | side | attacks/game | absorbed/game | absorbed % |", "|---|---|---|---|---|"]
    for lab, wn in (("losses", False), ("wins", True)):
        gs = [x for x in res if x["win"] == wn]
        for side, sn in ((0, "us"), (1, "them")):
            at = sum(x["shield"]["attacks"][side] for x in gs)
            ab = sum(x["shield"]["absorbed"][side] for x in gs)
            L.append(f"| {lab} | {sn} | {at / max(1, len(gs)):.1f} | {ab / max(1, len(gs)):.1f} | {pct(ab, at)} |")
    L += ["", "## Medians by result", "", "| | losses | wins |", "|---|---|---|"]
    for col in ("hp_r3", "hp_r1", "first_dmg_ago", "dmg_3", "attackers_3", "us6", "them6", "dealt_5", "bag", "mate_dmg3"):
        def med(rs):
            v = sorted(r[col] for r in rs if r[col] != "")
            return v[len(v) // 2] if v else "-"
        L.append(f"| {col} | {med(dL)} | {med(dW)} |")
    for title, key in (("Top killers (enemy champions)", "killer"), ("Our champions dying", "victim")):
        L += ["", f"## {title}", "", "| champion | deaths in losses | in wins | games with a death (L/W) | per such game (L/W) |",
              "|---|---|---|---|---|"]
        cnt = [collections.Counter(name(r[key]) for r in rs if r["kill_kind"] == "champ" or key == "victim") for rs in (dL, dW)]
        allk = (cnt[0] + cnt[1]).most_common(15)
        for k, _ in allk:
            if key == "victim":
                gp = [sum(1 for x in res if x["win"] == wn and any(name(rr["victim"]) == k for rr in x["rows"])) for wn in (False, True)]
                L.append(f"| {k} | {cnt[0][k]} | {cnt[1][k]} | {gp[0]}/{gp[1]} | "
                         f"{cnt[0][k] / max(1, gp[0]):.1f}/{cnt[1][k] / max(1, gp[1]):.1f} |")
            else:
                L.append(f"| {k} | {cnt[0][k]} | {cnt[1][k]} | | |")
    L += ["", "## Examples per tag (losses first; open with `replay.py track GAME --champ LABEL --from R-10 --to R`)", ""]
    for tg in TAGS:
        ex = [r for r in dL + dW if tg in r["tags"].split()][:10]
        if ex:
            L.append(f"- **{tg}**: " + ", ".join(f"{r['game']} r{r['round']} {r['victim'].split(':')[0]}:{name(r['victim'])}"
                                              f"{'' if r['result'] == 'loss' else ' (W)'}" for r in ex))
    open(out, "w").write("\n".join(L) + "\n")
    print(f"{len(rows)} deaths in {len(res)} games -> {out}, {csv_path}")


if __name__ == "__main__":
    main()
