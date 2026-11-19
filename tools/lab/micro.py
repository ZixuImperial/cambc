#!/usr/bin/env python3
"""Micro analysis of fights, turn by turn, from replays (live or local).

For every turn of a champion with an enemy champion within 8 tiles, in execution order with the true positions and HP
of all bodies at that moment, it records what the champion did and flags micro losses:
  no hit       an enemy champion was in its attack range (from where it started or where it ended the turn; a ranged
               champion that walked counts its end tile only with its attack reset ready, since a walk spends its
               attack), it was free to act (not stunned, not channelling) and it hit no champion
  spell idle   a damage, area or stun spell was ready (cooldown 0) with an enemy champion in that spell's range, unused
               (spells that exclude walking count the start tile only: a walk and such a cast cannot share a turn)
  split focus  in a round, 2+ of a team's champions hit 2+ different enemy champions
  target       when it hit a champion with 2+ enemy champions in its attack range: did it hit the lowest-HP one
  range        damage dealt from 4+ tiles; ranged champions (range 3+) ending a turn next to an enemy melee champion
  stun         stuns wasted: landing on an enemy already stunned (in execution order; a second stun before its next turn is
               wasted) or on Marcella (immune); Marcella's enhanced attack (the basic attack after her slot-0 reset) stuns
  dead foes    a body is dead from its killing blow (or the round start for camp kills) on, not from its next turn row
  first strike which team dealt the first champion damage of each fight (replay.fights clusters)
  safe shot    a ranged champion at 50%+ HP with an enemy champion in attack range, on a tile no enemy can hit next turn
               (walk, dash, reset and spell reach from each enemy's cooldowns): did it shoot, or walk off
  kite shot    a ranged champion walked without a shot or any cast (one cast a turn) while its attack reset was ready
               and an enemy champion stood in range of its end tile (walk + reset + shot was there)
  dashes       fight dashes that end closer to an enemy champion; dashes followed by a basic hit in the same turn
  chase        dash ready, 35%+ HP, an enemy champion below 30% HP 2-4 tiles away: did it dash
  finish       an enemy champion below 35% HP within reach (walk, dash, reset, spell) but 3+ tiles away: hit it; died
               within 3 rounds
  low HP       below 35% HP with an enemy champion adjacent: died within 5 rounds; hit, then dashed
"Died within N rounds" counts deaths from the rest of the turn's own round (r .. r + N).
Attack and spell ranges per champion type are inferred from the replays themselves (the farthest attack or cast seen)
and cached in /data/USER/micro_kits.json.

usage: python3 -I tools/lab/micro.py stats GAME... [--us A|B|BOT] [--jobs 8] [--by-champion] [--from R] [--to R]
          [--power LO,HI]
          rates per side (us vs them) across the games, with the number of opportunities behind each rate, and the
          us - them difference with its 95% bootstrap interval (over games; over maps for local runs; * = excludes 0)
          --from/--to: count only turns in rounds [R, R'] (and, for first strike, fights that start in the window)
          --power LO,HI: count only turns whose acting side's spent-gold ratio is in [LO, HI]: gold spent (shop
            actions, as topread contest/respawn) by the acting side's living bodies within 8 of the acting champion
            (itself included) / both sides' within 8; 0.5 when neither side has bought anything. First strike is
            filtered by the window only. Turn filters apply to every per-turn count, stuns, far damage and split focus.
          --by-champion also prints why finishing chances were missed (what it did instead, stance, whether the low
            enemy was in a recall channel or within 2 of a mate at 50%+ HP) and unused ready spells by champion, slot
            and stance with what it did instead; why a basic hit with 2+ enemy champions in range was not on the lowest
            (by absolute HP, the existing target metric, and by HP %); and it splits the chances to hit a champion not
            taken by what it did instead
            (hit a camp, stepped away, moved closer, moved sideways, cast without moving, stood) and, for a nova side,
            by its stance: the last set_priority value set up to and including that turn (40 FLEE, 35 FINISH, else
            BASE; a 'p' action). Nova sides: the live side ("us") of live games; in local runs, bots named nova*.
       python3 -I tools/lab/micro.py walk GAME [--fight N | --worst K] [--us A|B|BOT]
          step-by-step tables of fights: every turn of every champion in the fight, with its action and flags
       python3 -I tools/lab/micro.py kits GAME...      rebuild the range table from these games
GAME: a live match id, a live set dir (e.g. /data/USER/plat/m19eD), RUN:ID, a .repl26a, or an abl run dir with rep/.
"""
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "replay.py")):
    sys.path.insert(0, "/homes/USER/cambc/tools/lab")  # a copy run from elsewhere still uses the lab's replay.py
import replay as RP  # noqa: E402


def real_ch(g, ci, t):
    """replay.real_channel of turn t, computed once per game."""
    if not hasattr(g, "_real_ch"):
        g._real_ch = {(x[0], x[1]): RP.real_channel(ci, x, ts[i - 1] if i else None) for ts in g.by_champ.values() for i, x in enumerate(ts)}
    return g._real_ch.get((t[0], t[1]), 0)

KITS = "/data/USER/micro_kits.json"
DMG_TYPES = {2, 3, 4}  # damage, aoe_damage, cc
AREA_STUNS = {(0, 0), (12, 1)}  # (champion_type, slot): Ryth's area spell, Heart of Ruin's dash landing
WALK_OK = {(3, 1)}  # (champion_type, slot): the one damage/stun spell that can share a turn with a walk (Cassi's stun)
MARCELLA = 7        # champion_type: immune to stuns; her slot-0 reset makes the next basic attack stun
ABIL = RP.ABILITY
BODY = ["ryth", "vesper_vale", "vendetta", "cassi", "issac", "stellar", "prism", "marcella", "willow", "ren", "varg", "tavi",
        "heart_of_ruin"]  # champion_type


def opt(argv, name, default, cast=str):
    if name in argv:
        i = argv.index(name)
        v = cast(argv[i + 1])
        del argv[i:i + 2]
        return v
    return default


# ---------------------------------------------------------------- champion ranges from replays
def _kit_obs(spec):
    try:
        g = RP.load(spec)
    except SystemExit:
        return {}
    obs = collections.defaultdict(lambda: {"attack": 0, "spells": {}})
    for t in g.turns:
        typ = g.bodies[t[1]]["type"]
        x, y = t[2], t[3]
        for a in t[-1]:
            if a[0] == "m":
                x, y = a[1], a[2]
            elif a[0] == "a" and a[1] == 1:
                obs[typ]["attack"] = max(obs[typ]["attack"], RP.cheb(x, y, a[3], a[4]))
            elif a[0] == "c":
                key = str(a[1])
                sp = obs[typ]["spells"].setdefault(key, {"atype": a[2], "range": 0})
                if a[2] == 6:  # a dash lands the caster on its target tile
                    x, y = a[3], a[4]
                else:  # the cast record's from-tile is set for dashes only: range from the tracked position
                    sp["range"] = max(sp["range"], RP.cheb(x, y, a[3], a[4]))
    return {str(k): v for k, v in obs.items()}


def build_kits(specs, jobs=8):
    import multiprocessing
    with multiprocessing.get_context("fork").Pool(min(jobs, max(1, len(specs)))) as pool:
        parts = pool.map(_kit_obs, specs)
    kits = {}
    for p in parts:
        for typ, v in p.items():
            k = kits.setdefault(typ, {"attack": 0, "spells": {}})
            k["attack"] = max(k["attack"], v["attack"])
            for slot, sp in v["spells"].items():
                ks = k["spells"].setdefault(slot, {"atype": sp["atype"], "range": 0})
                ks["range"] = max(ks["range"], sp["range"])
    with open(KITS, "w") as f:
        json.dump(kits, f, indent=1, sort_keys=True)
    return kits


def load_kits():
    try:
        return json.load(open(KITS))
    except (OSError, ValueError):
        sys.exit(f"no range table {KITS}: run `micro.py kits GAME...` on a set of games first")


# ---------------------------------------------------------------- per-turn records
def next_reach(kit, lt):
    """How far a champion can damage on its next turn (walk + attack, dash, walk + reset + ranged attack, unit or area
    spell), from its cooldowns at its last turn start and the slots it cast then: lt = (cd0, cd1, slots); None = all ready."""
    rng = max(1, kit.get("attack", 1))
    reach = rng + 1 if rng <= 1 else rng
    for s, sp in kit.get("spells", {}).items():
        if s not in ("0", "1") or (lt is not None and (lt[int(s)] > 1 or s in lt[2])):
            continue
        at = sp.get("atype")
        if at == 6:
            reach = max(reach, 4 if rng <= 1 else 5)
        elif at in (2, 4):
            reach = max(reach, 4)
        elif at == 3:
            reach = max(reach, 5)
        elif at == 1 and rng >= 3:
            reach = max(reach, rng + 1)
    return reach


def kill_steps(g):
    """When each body dies, in execution order: {(turn index, action index): [victims]} for champion kills (the last
    damaging effect on the victim in its death round is the killing blow, linked deaths included) and
    {round: [victims]} for camp kills, which happen at round start."""
    dies = {(e[0], e[2]): e[3] for e in g.events if e[1] == "death"}
    last = {}
    for k, t in enumerate(g.turns):
        for j, a in enumerate(t[-1]):
            fx = a[5] if a[0] == "a" else (a[7] if a[0] == "c" else ())
            for kk, i, d in fx:
                if kk == 1 and d < 0 and (t[0], i) in dies:
                    last[(t[0], i)] = (k, j)
    at_step, at_start = collections.defaultdict(list), collections.defaultdict(list)
    for (r, v), kk in dies.items():
        if (r, v) in last:
            at_step[last[(r, v)]].append(v)
        elif kk == 2:
            at_start[r].append(v)
    return at_step, at_start


def analyse(g, kits, keep=None):
    """Records of every champion turn with an enemy champion within 8, in execution order, plus per-round hits.
    keep(r, c, team, x, y, pos, alive): count only the turns it accepts (state still advances on every turn)."""
    ci = g.ci
    pos, hp, alive = {}, {}, {}
    mhp, last = {}, {}  # body -> max HP; body -> (cd0, cd1, slots cast) at its last turn
    for c in g.bodies:
        pos[c], hp[c], alive[c] = None, 0, False
    recs = []
    hits_round = collections.defaultdict(lambda: collections.defaultdict(set))  # (round, team) -> hitter -> targets
    dmg_far = [[0.0, 0.0], [0.0, 0.0]]  # team -> [damage from 4+ tiles, all champion damage]
    stun_waste = [[0, 0, 0, 0], [0, 0, 0, 0]]  # team -> [stuns on an already-stunned champion, stuns landing on champions,
                                               #          stuns on Marcella (immune), stuns landing in games where the target team fields her]
    pend = collections.Counter()        # body -> stuns landed since its last turn (a stun is spent on the next turn)
    enhanced = set()                    # Marcella bodies whose next basic attack stuns (after her slot-0 reset)
    kill_at, camp_kills = kill_steps(g)
    camp_hits = collections.defaultdict(list)  # round -> [(champion, damage)] dealt by camps at round start
    for e in g.events:
        if e[1] == "camp_attack" and e[3] >= 0:
            camp_hits[e[0]].append((e[3], e[4]))
    cur_r = None
    recall = {}  # body -> in a recall channel between its latest turn and its next one (its next turn starts channelling)
    gems_of, shield_of, chan_now = {}, {}, {}  # body -> gems and shield at its latest turn start; channelling now
    next_ch, seen = {}, {}  # turn index -> channel type at the start of the same body's next turn
    for k in range(len(g.turns) - 1, -1, -1):
        c = g.turns[k][1]
        next_ch[k] = seen.get(c, 0)
        seen[c] = g.turns[k][ci["chType"]]

    def can_reach(m, o):
        """Can our body m hit body o from where m stands: basic-attack range, or a damage/stun spell ready at m's next
        turn (next_reach's cooldown rule) within that spell's range (micro_kits.json)."""
        kit = kits.get(str(g.bodies[m]["type"]), {"attack": 1, "spells": {}})
        d = RP.cheb(pos[m][0], pos[m][1], pos[o][0], pos[o][1])
        if d <= max(1, kit.get("attack", 1)):
            return True
        lt = last.get(m)
        for sl, sp in kit.get("spells", {}).items():
            if sl in ("0", "1") and sp.get("atype") in DMG_TYPES and d <= sp.get("range", 0) and (
                    lt is None or (lt[int(sl)] <= 1 and sl not in lt[2])):
                return True
        return False

    def pick_why(tg, inr, x, y, me):
        """For a basic hit with 2+ enemy champions in range: per variant (absolute HP, HP %), None when the target was
        the lowest, else what the target had instead of the lowest one and the HP gap."""
        if tg not in inr:  # the target is out of the tracked attack range (range table lag): no comparison
            return {}
        pct = {o: hp.get(o, 0) / mhp.get(o, 1) for o in inr}
        out = {}
        for var, key in (("abs", lambda o: hp.get(o, 0)), ("pct", lambda o: pct[o])):
            lw = min(inr, key=key)
            if key(tg) <= key(lw):
                out[var] = None
                continue
            other = pct[tg] < pct[lw] if var == "abs" else hp.get(tg, 0) < hp.get(lw, 0)
            ehp = lambda o: hp.get(o, 0) + shield_of.get(o, 0)  # noqa: E731
            team = g.team_of[me]
            mates = [m for m in g.bodies if m != me and g.team_of[m] == team and alive.get(m) and pos.get(m) is not None]
            ours = mates + [me]
            def peel(o, who):
                return any((RP.cheb(pos[o][0], pos[o][1], pos[m][0], pos[m][1]) <= 2
                            and (hp.get(m, 0) < 0.5 * mhp.get(m, 1) or gems_of.get(m, 0) >= 30))
                           or (chan_now.get(m) and RP.cheb(pos[o][0], pos[o][1], pos[m][0], pos[m][1]) <= 4) for m in who)
            f = {"mates": sum(can_reach(m, tg) for m in mates) > sum(can_reach(m, lw) for m in mates),
                 "peel_mate": peel(tg, mates) and not peel(lw, mates),
                 "peel": peel(tg, ours),
                 "gems": gems_of.get(tg, 0) > gems_of.get(lw, 0),
                 "cassi_issac": BODY[int(g.bodies[tg]["type"])] in ("cassi", "issac") if int(g.bodies[tg]["type"]) < len(BODY) else False,
                 "channel": chan_now.get(tg, False), "stunned": pend[tg] > 0,
                 "closer": RP.cheb(x, y, pos[tg][0], pos[tg][1]) < RP.cheb(x, y, pos[lw][0], pos[lw][1]),
                 "other": other, "shield": shield_of.get(lw, 0) > 0 and ehp(lw) > ehp(tg)}
            f["none_old"] = not any(v for kk, v in f.items() if kk not in ("mates", "peel", "peel_mate"))
            f["none"] = not any(v for kk, v in f.items() if kk not in ("none_old", "peel"))
            f["gap"] = hp.get(tg, 0) - hp.get(lw, 0) if var == "abs" else 100 * (pct[tg] - pct[lw])
            out[var] = f
        return out

    def land_stuns(team, victims, count=True):
        for i in victims:
            immune = str(g.bodies[i]["type"]) == str(MARCELLA)
            if count:
                stun_waste[team][1] += 1
                stun_waste[team][2] += immune
                stun_waste[team][0] += not immune and pend[i] > 0
            if not immune:
                pend[i] += 1

    for k, t in enumerate(g.turns):
        r, c = t[0], t[1]
        if r != cur_r:  # round start: camp hits and camp kills come before every champion turn of the round
            cur_r = r
            for i, d in camp_hits.get(r, ()):
                hp[i] = hp.get(i, 0) - d
            for i in camp_kills.get(r, ()):
                alive[i] = False
        team = g.team_of[c]
        pend[c] = 0
        pos[c] = (t[2], t[3]) if t[2] >= 0 else None
        hp[c], mhp[c] = t[4], max(1, t[5])
        alive[c] = bool(t[ci["alive"]])
        recall[c] = next_ch[k] == 1  # a recall started each turn and dropped by a walk does not count
        chan_now[c] = next_ch[k] != 0
        gems_of[c], shield_of[c] = t[ci["gems"]], t[ci["shield"]]
        if not alive[c] or pos[c] is None:
            for a in t[-1]:
                if a[0] == "m":
                    pos[c] = (a[1], a[2])
            continue
        typ = str(g.bodies[c]["type"])
        kit = kits.get(typ, {"attack": 1, "spells": {}})
        rng = max(1, kit.get("attack", 1))
        foes = {o: pos[o] for o in g.bodies if g.team_of[o] != team and alive.get(o) and pos.get(o) is not None}
        x0, y0 = pos[c]
        ok = keep is None or keep(r, c, team, x0, y0, pos, alive)
        dmin = min((RP.cheb(x0, y0, p[0], p[1]) for p in foes.values()), default=99)
        # turn-start state: is this tile out of every enemy's reach next turn; low enemies near; my own reach
        safe = all(RP.cheb(x0, y0, p[0], p[1]) > next_reach(kits.get(str(g.bodies[o]["type"]), {}), last.get(o))
                   for o, p in foes.items())
        spells = {s: sp.get("atype") for s, sp in kit.get("spells", {}).items() if s in ("0", "1")}
        ready_at = {at for s, at in spells.items() if t[ci["cd" + s]] == 0}
        my_reach = rng + 1 if rng <= 1 else rng + (1 in ready_at)
        if 6 in ready_at:
            my_reach = max(my_reach, 4 if rng <= 1 else 5)
        if ready_at & DMG_TYPES:
            my_reach = max(my_reach, 4)
        low30_near = any(hp.get(o, 0) < 0.3 * mhp.get(o, 1) and 2 <= RP.cheb(x0, y0, p[0], p[1]) <= 4 for o, p in foes.items())
        low35_far = [o for o, p in foes.items() if hp.get(o, 0) < 0.35 * mhp.get(o, 1) and 3 <= RP.cheb(x0, y0, p[0], p[1]) <= my_reach]
        low_ctx = {}  # low enemy -> (its start position, in a recall channel, within 2 of a mate at 50%+ HP)
        for o in low35_far:
            p = foes[o]
            cover = any(m != o and g.team_of[m] == g.team_of[o] and alive.get(m) and pos.get(m) is not None
                        and hp.get(m, 0) >= 0.5 * mhp.get(m, 1) and RP.cheb(p[0], p[1], pos[m][0], pos[m][1]) <= 2
                        for m in g.bodies)
            low_ctx[o] = (p, recall.get(o, False), cover)
        # walk the actions: position at each attack, champion hits, casts
        x, y = x0, y0
        hit_champ, cast_champ, hit_camp, moved, walked, casts = False, False, False, False, False, set()
        targets, picks, hit_ids, pick_info = [], [], set(), []
        dash_used, dash_closer, dash_hit = False, False, False
        for j, a in enumerate(t[-1]):
            if a[0] == "m":
                x, y = a[1], a[2]
                moved = walked = True
            elif a[0] == "a":
                if a[1] == 1 and g.team_of.get(a[2], team) != team:
                    hit_champ = True
                    hit_ids.add(a[2])
                    dash_hit |= dash_used
                    inr = [o for o, p in foes.items() if RP.cheb(x, y, p[0], p[1]) <= rng and alive.get(o)]
                    if len(inr) >= 2:
                        low = min(inr, key=lambda o: hp.get(o, 0))
                        picks.append(hp.get(a[2], 0) <= hp.get(low, 0))
                        pick_info.append(pick_why(a[2], inr, x, y, c))
                    targets.append(a[2])
                elif a[1] == 2:
                    hit_camp = True
                if int(typ) == MARCELLA and c in enhanced:  # her enhanced attack: the basic attack after the reset
                    enhanced.discard(c)
                    if a[1] == 1 and g.team_of.get(a[2], team) != team:
                        land_stuns(team, [a[2]], ok)
                for kk, i, d in a[5]:
                    if kk != 1:
                        continue
                    if ok and d < 0 and g.team_of.get(i, team) != team:
                        dmg_far[team][1] += -d
                        if i in foes and RP.cheb(x, y, foes[i][0], foes[i][1]) >= 4:
                            dmg_far[team][0] += -d
                    hp[i] = hp.get(i, 0) + d
            elif a[0] == "c":
                casts.add(str(a[1]))
                champ_fx = [(kk, i, d) for kk, i, d in a[7] if kk == 1 and g.team_of.get(i, team) != team]
                if champ_fx or (a[5] == 1 and g.team_of.get(a[6], team) != team):
                    cast_champ = True
                    if a[6] >= 0:
                        targets.append(a[6])
                    hit_ids.update(i for kk, i, d in champ_fx)
                    if a[5] == 1 and g.team_of.get(a[6], team) != team:
                        hit_ids.add(a[6])
                # stuns that land: unit stuns, Ryth's area spell, Heart of Ruin's dash landing (in execution order:
                # a second stun before the target's next turn does not stack, so it is wasted)
                stunned_now = [a[6]] if a[2] == 4 and a[5] == 1 and g.team_of.get(a[6], team) != team else []
                if (int(typ), a[1]) in AREA_STUNS:
                    stunned_now = [i for kk, i, d in champ_fx]
                land_stuns(team, stunned_now, ok)
                if int(typ) == MARCELLA and a[1] == 0:
                    enhanced.add(c)
                for kk, i, d in a[7]:
                    if kk != 1:
                        continue
                    if ok and d < 0 and g.team_of.get(i, team) != team:
                        dmg_far[team][1] += -d
                        if i in foes and RP.cheb(x, y, foes[i][0], foes[i][1]) >= 4:
                            dmg_far[team][0] += -d
                    hp[i] = hp.get(i, 0) + d
                if a[2] == 6:  # a dash lands the caster on its target tile
                    if foes:
                        before = min(RP.cheb(x, y, p[0], p[1]) for p in foes.values())
                        dash_closer = min(RP.cheb(a[3], a[4], p[0], p[1]) for p in foes.values()) < before
                    x, y = a[3], a[4]
                    moved = True
                    dash_used = True
            for v in kill_at.get((k, j), ()):  # the killing blow: the victim is dead from here on
                alive[v] = False
        if ok and (hit_champ or cast_champ):
            for o in set(targets):
                hits_round[(r, team)][c].add(o)
        xe, ye = x, y
        pos[c] = (xe, ye)
        last[c] = (t[ci["cd0"]], t[ci["cd1"]], set(casts))
        if dmin > 8 or not ok:
            continue
        stunned = bool(t[ci["stunned"]])
        chan = real_ch(g, ci, t) != 0  # not the raw chType: a SPIN_SELF lazy recall start is no channel (2 Nov)
        free = not stunned and not chan
        # a walk spends a ranged champion's attack: its end tile counts only if it did not walk or had its reset ready
        end_ok = rng <= 1 or not walked or 1 in ready_at
        in_range = [o for o, p in foes.items() if RP.cheb(x0, y0, p[0], p[1]) <= rng or (end_ok and RP.cheb(xe, ye, p[0], p[1]) <= rng)]
        spell_ready = []
        for slot, sp in kit.get("spells", {}).items():
            if sp.get("atype") in DMG_TYPES and sp.get("range", 0) > 0:
                cd = t[ci["cd" + slot]] if slot in ("0", "1") else None
                # a spell that excludes walking cannot share a turn with a walk: only its start tile counts
                ends = ((x0, y0), (xe, ye)) if (int(typ), int(slot)) in WALK_OK else ((x0, y0),)
                if cd == 0 and any(RP.cheb(ex, ey, p[0], p[1]) <= sp["range"] for p in foes.values() for ex, ey in ends):
                    spell_ready.append((slot, sp["atype"]))
        melee_adj = rng >= 3 and any(RP.cheb(xe, ye, p[0], p[1]) <= 1 and kits.get(str(g.bodies[o]["type"]), {}).get("attack", 1) <= 1
                                     for o, p in foes.items())
        toward = None
        if moved and foes:
            near = min(foes.values(), key=lambda p: RP.cheb(x0, y0, p[0], p[1]))
            toward = RP.cheb(xe, ye, near[0], near[1]) - RP.cheb(x0, y0, near[0], near[1])
        recs.append({"r": r, "c": c, "team": team, "type": typ, "dmin": dmin, "free": free, "stunned": stunned, "chan": chan,
                     "in_range": len(in_range), "hit": hit_champ or cast_champ, "basic": hit_champ, "cast": cast_champ,
                     "camp": hit_camp, "moved": moved,
                     "toward": toward, "spell_ready": spell_ready, "spell_used": [s for s, _ in spell_ready if s in casts],
                     "picks": picks, "melee_adj": melee_adj, "hp": t[4], "maxhp": t[5], "start": (x0, y0), "end": (xe, ye),
                     "rng": rng, "safe": safe,
                     "in_range_start": any(RP.cheb(x0, y0, p[0], p[1]) <= rng for p in foes.values()),
                     "in_range_end": any(RP.cheb(xe, ye, p[0], p[1]) <= rng for p in foes.values()),
                     "reset_ready": 1 in ready_at, "reset_cast": any(spells.get(s) == 1 for s in casts), "cast_any": bool(casts),
                     "walked": walked,
                     "dash_ready": 6 in ready_at, "dash_used": dash_used, "dash_closer": dash_closer, "dash_hit": dash_hit,
                     "low30_near": low30_near, "low35_far": low35_far, "hit_ids": hit_ids,
                     "low_ctx": low_ctx, "casts": set(casts), "camp_any": hit_camp, "pick_info": pick_info})
    split = [[0, 0], [0, 0]]  # team -> [rounds with 2+ hitters on 2+ targets, rounds with 2+ hitters]
    for (r, team), hs in hits_round.items():
        if len(hs) >= 2:
            split[team][1] += 1
            tg = set().union(*hs.values())
            split[team][0] += len(tg) >= 2
    marc = {g.team_of[i] for i in g.bodies if str(g.bodies[i]["type"]) == str(MARCELLA)}
    for team in (0, 1):  # Marcella hits are exposure, not micro: rate them only over games where the target team fields her
        stun_waste[team][3] = stun_waste[team][1] if 1 - team in marc else 0
    return recs, dmg_far, stun_waste, split


def first_strikes(g, lo=None, hi=None):
    out = [0, 0]
    for f in RP.fights(g):
        if not (sum(f["deaths"]) or sum(f["dmg"].values()) >= 300):
            continue
        if (lo is not None and f["start"] < lo) or (hi is not None and f["start"] > hi):
            continue
        first = None
        for t in g.turns:
            if t[0] < f["start"]:
                continue
            if t[0] > f["end"]:
                break
            if RP.hostile_hits(g, t) and RP.cheb(t[2], t[3], f["cx"], f["cy"]) <= 12:
                first = g.team_of[t[1]]
                break
        if first is not None:
            out[first] += 1
    return out


STANCE = {40: "FLEE", 35: "FINISH"}  # nova's set_priority markers; any other value is the slot's base (calm/fight)
NOHIT = ["camp", "away", "closer", "sideways", "cast", "stood"]


def nohit_kind(x):
    """What a champion did instead of hitting a champion in range."""
    if x["camp"]:
        return "camp"
    if x["moved"]:
        tw = x["toward"] or 0
        return "away" if tw > 0 else ("closer" if tw < 0 else "sideways")
    return "cast" if x["cast_any"] else "stood"


PICKWHY = ["mates", "peel_mate", "peel", "gems", "cassi_issac", "channel", "stunned", "closer", "other", "shield", "none_old", "none"]
FINMISS = ["hit_other", "camp", "dash", "cast", "away", "toward_it", "closer_other", "sideways", "stood"]
SPELLDID = ["other_spell", "basic", "away", "closer", "sideways", "nothing"]


def finish_miss_kind(x):
    """What a champion did instead of hitting a low enemy (below 35% HP, in its reach, 3+ tiles away)."""
    if x["hit"]:
        return "hit_other"
    if x["camp"]:
        return "camp"
    if x["dash_used"]:
        return "dash"
    if x["cast_any"]:
        return "cast"
    if not x["moved"]:
        return "stood"
    lows = [c[0] for c in x["low_ctx"].values()]
    (x0, y0), (x1, y1) = x["start"], x["end"]
    d0 = min(RP.cheb(x0, y0, p[0], p[1]) for p in lows)
    d1 = min(RP.cheb(x1, y1, p[0], p[1]) for p in lows)
    if d1 > d0:
        return "away"
    if d1 < d0:
        return "toward_it"
    return "closer_other" if (x["toward"] or 0) < 0 else "sideways"


def spell_did(x, slot):
    """What a champion did with a ready, in-range damage/stun spell left unused."""
    if x["casts"] - {slot}:
        return "other_spell"
    if x["basic"] or x["camp_any"]:
        return "basic"
    if x["moved"]:
        tw = x["toward"] or 0
        return "away" if tw > 0 else ("closer" if tw < 0 else "sideways")
    return "nothing"


def nova_teams(g):
    m = g.meta
    if m.get("source") == "live":
        return {g.us}
    if m.get("source") == "local" and m.get("a"):
        return {t for t, b in enumerate((m.get("a", ""), m.get("b", ""))) if b.startswith("nova")}
    return set()


def game_stats(args):
    spec, us = args[:2]
    lo, hi, power = (list(args[2:]) + [None, None, None])[:3]
    try:
        g = RP.load(spec, us)
    except SystemExit as e:
        return {"spec": spec, "error": str(e)}
    kits = load_kits()
    keep, zero = None, {}
    if lo is not None or hi is not None or power is not None:
        spent_at = None
        if power is not None:
            sys.path.insert(0, "/data/USER/scout2/py")
            import topread as T  # the same spent-gold code as topread contest/respawn and respawnstance
            spent_at = T.shop_spent(g)

        def keep(r, c, team, x, y, pos, alive):
            if (lo is not None and r < lo) or (hi is not None and r > hi):
                return False
            if power is None:
                return True
            sp = [0, 0]
            for o, p in pos.items():
                if alive.get(o) and p is not None and RP.cheb(x, y, p[0], p[1]) <= 8:
                    sp[g.team_of[o] != team] += spent_at(o, r)[0]
            zero[(r, c)] = sp[0] + sp[1] == 0
            return power[0] <= T.ratio(sp[0], sp[1]) <= power[1]
    recs, far, sw, split = analyse(g, kits, keep)
    stance = {}
    for c, ts in g.by_champ.items():
        cur = None
        for t in ts:
            for a in t[-1]:
                if a[0] == "p":
                    cur = a[1]
            stance[(t[0], c)] = STANCE.get(cur, "BASE")
    novas = nova_teams(g)
    deaths = collections.defaultdict(list)
    for e in g.events:
        if e[1] == "death":
            deaths[e[2]].append(e[0])
    s = {"spec": spec, "us": g.us, "win": {1: 0, 2: 1}.get(g.final.get("outcome")) == g.us, "side": [collections.Counter(), collections.Counter()],
         "unit": g.meta.get("map") if g.meta.get("source") == "local" and g.meta.get("map") else spec}
    for x in recs:
        c = s["side"][x["team"]]
        c["turns"] += 1
        if power is not None:
            c["pw_turns"] += 1
            c["pw_zero"] += zero.get((x["r"], x["c"]), False)
        c["stunned"] += x["stunned"]
        if x["free"] and x["in_range"]:
            c["could_hit"] += 1
            if not x["hit"]:
                c["no_hit"] += 1
                c["no_hit_camp" if x["camp"] else ("no_hit_away" if (x["toward"] or 0) > 0 else ("no_hit_moved" if x["moved"] else "no_hit_still"))] += 1
        if x["free"] and x["spell_ready"]:
            c["spell_ready"] += 1
            c["spell_idle"] += len(x["spell_used"]) == 0
            if x["basic"] or (x["toward"] or 0) < 0:  # engaging: hit a champion or ended closer (a fight-stance proxy)
                c["spell_ready_eng"] += 1
                c["spell_idle_eng"] += len(x["spell_used"]) == 0
            if (x["toward"] or 0) > 0:  # stepped away from the nearest enemy: a flee turn (lean replays carry no stance)
                c["spell_ready_away"] += 1
                c["spell_idle_away"] += len(x["spell_used"]) == 0
                if any(at == 4 for _, at in x["spell_ready"]):
                    c["stun_ready_away"] += 1
                    c["stun_idle_away"] += not any(sl in x["spell_used"] for sl, at in x["spell_ready"] if at == 4)
            st = stance[(x["r"], x["c"])] if x["team"] in novas else "n/a"
            for slot, at in x["spell_ready"]:
                k = f"{BODY[int(x['type'])] if int(x['type']) < len(BODY) else x['type']} s{slot} {ABIL[at]}"
                for kk in (k + "|all", k + "|" + st):
                    c["sp|" + kk] += 1
                    if slot not in x["spell_used"]:
                        c["spu|" + kk] += 1
                        c["spu|" + kk + "|" + spell_did(x, slot)] += 1
                c["sr|" + k] += 1
                c["si|" + k] += slot not in x["spell_used"]
                c[("si_hit|" if x["hit"] else "si_nohit|") + k] += slot not in x["spell_used"]
        if x["free"] and x["in_range"]:
            k = BODY[int(x["type"])] if int(x["type"]) < len(BODY) else x["type"]
            c["ch|" + k] += 1
            c["chn|" + k] += not x["hit"]
            st = stance[(x["r"], x["c"])] if x["team"] in novas else "n/a"
            for kk in (k + "|all", k + "|" + st):
                c["cs|" + kk] += 1
                if not x["hit"]:
                    c["csn|" + kk] += 1
                    c["csn|" + kk + "|" + nohit_kind(x)] += 1
        for p in x["picks"]:
            c["pick_n"] += 1
            c["pick_low"] += p
        for pi in x["pick_info"]:
            for var, f in pi.items():
                c[f"pk|{var}|n"] += 1
                if f is not None:
                    c[f"pk|{var}|miss"] += 1
                    for h in PICKWHY:
                        c[f"pk|{var}|{h}"] += f[h]
                    c[f"pk|{var}|gap"] += f["gap"]
        if x["cast"]:
            c["casts"] += 1
            c["cast_died5"] += any(x["r"] <= d <= x["r"] + 5 for d in deaths.get(x["c"], []))
        if x["cast"] and not x["basic"] and x["dmin"] >= 2:  # a poke: a spell at a champion from 2+ tiles, no basic attack
            c["pokes"] += 1
            c["poke_died5"] += any(x["r"] <= d <= x["r"] + 5 for d in deaths.get(x["c"], []))
        if x["free"] and x["dmin"] >= 2:
            c["calm_turns"] += 1
            c["calm_died5"] += any(x["r"] <= d <= x["r"] + 5 for d in deaths.get(x["c"], []))
        if x["free"]:
            c["free_turns"] += 1
            c["melee_adj"] += x["melee_adj"]
        if not x["free"]:
            continue
        hpf = x["hp"] / max(1, x["maxhp"])
        died5 = any(x["r"] <= d <= x["r"] + 5 for d in deaths.get(x["c"], []))
        if x["rng"] >= 3 and x["in_range_start"] and hpf >= 0.5 and x["safe"]:
            c["safe_n"] += 1  # a free shot: no enemy can hit this tile next turn
            c["safe_shot"] += x["hit"]
            c["safe_walk"] += x["moved"] and not x["hit"]
        if x["rng"] >= 3 and x["moved"] and not x["basic"] and x["reset_ready"] and not x["cast_any"] and x["in_range_end"]:
            c["kite_miss"] += 1  # walked without a shot or any cast (one cast a turn) while walk + reset + shot was there
        if x["dash_used"]:
            c["dash_n"] += 1
            c["dash_closer"] += x["dash_closer"]
            c["dash_hit"] += x["dash_hit"]
        if x["dash_ready"] and hpf >= 0.35 and x["low30_near"]:
            c["chase_n"] += 1
            c["chase_used"] += x["dash_used"]
        if x["low35_far"]:
            st = stance[(x["r"], x["c"])] if x["team"] in novas else "n/a"
            for kk in ("all", st):
                c[f"fn|{kk}"] += 1
                if not x["hit_ids"] & set(x["low35_far"]):
                    c[f"fm|{kk}"] += 1
                    c[f"fm|{kk}|{finish_miss_kind(x)}"] += 1
                    c[f"fm|{kk}|recall"] += any(v[1] for v in x["low_ctx"].values())
                    c[f"fm|{kk}|cover"] += all(v[2] for v in x["low_ctx"].values())
            c["fin_n"] += 1
            c["fin_hit"] += bool(x["hit_ids"] & set(x["low35_far"]))
            c["fin_died3"] += any(x["r"] <= d <= x["r"] + 3 for o in x["low35_far"] for d in deaths.get(o, []))
        if hpf < 0.35 and x["dmin"] == 1:
            c["lowadj_n"] += 1
            c["lowadj_died5"] += died5
            c["lowadj_hitdash"] += x["hit"] and x["dash_used"]
    for team in (0, 1):
        c = s["side"][team]
        c["dmg_far"], c["dmg_all"] = far[team]
        c["stun_waste"], c["stun_casts"], c["stun_marc"], c["stun_casts_marc"] = sw[team]
        c["split"], c["multi"] = split[team]
    fs = first_strikes(g, lo, hi)
    for team in (0, 1):
        s["side"][team]["first_strike"] = fs[team]
        s["side"][team]["fights"] = sum(fs)
    s["side"] = [dict(c) for c in s["side"]]
    s["nova"] = sorted(novas)
    return s


def boot_diff(rs, a, b, n=1000, seed=7):
    """us - them rate difference in points and its 95% bootstrap interval, resampling games (live) or maps (local A/B
    runs: both seats of a map are one trial). Mirror games of one bot differ by up to 5-15 points on 44 maps."""
    units = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in rs:
        u = units[r.get("unit", r["spec"])]
        us, them = r["side"][r["us"]], r["side"][1 - r["us"]]
        u[0] += us.get(a, 0)
        u[1] += us.get(b, 0)
        u[2] += them.get(a, 0)
        u[3] += them.get(b, 0)
    vals = list(units.values())
    tot = [sum(c) for c in zip(*vals)] if vals else [0, 0, 0, 0]
    if not tot[1] or not tot[3]:
        return None
    d0 = 100 * (tot[0] / tot[1] - tot[2] / tot[3])
    if len(vals) < 2:
        return d0, float("nan"), float("nan")
    rnd = random.Random(seed)
    ds = []
    for _ in range(n):
        x = [sum(c) for c in zip(*rnd.choices(vals, k=len(vals)))]
        if x[1] and x[3]:
            ds.append(100 * (x[0] / x[1] - x[2] / x[3]))
    ds.sort()
    return d0, ds[int(0.025 * len(ds))], ds[max(0, int(0.975 * len(ds)) - 1)]


def cmd_stats(argv):
    by_champ = "--by-champion" in argv
    argv = [a for a in argv if a != "--by-champion"]
    us = opt(argv, "--us", None)
    jobs = opt(argv, "--jobs", 8, int)
    lo, hi = opt(argv, "--from", None, int), opt(argv, "--to", None, int)
    power = opt(argv, "--power", None, lambda v: tuple(float(z) for z in v.split(",")))
    specs = RP.expand_specs(argv)
    if not specs:
        sys.exit(__doc__)
    import multiprocessing
    extra = (lo, hi, power) if (lo, hi, power) != (None, None, None) else ()
    with multiprocessing.get_context("fork").Pool(min(jobs, max(1, len(specs)))) as pool:
        rows = pool.map(game_stats, [(s, us) + extra for s in specs])
    bad = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    print(f"{len(rows)} games ({len(bad)} unreadable); fight turns = champion turns with an enemy champion within 8 tiles")
    if lo is not None or hi is not None:
        print(f"window: turns in rounds {lo if lo is not None else 1}-{hi if hi is not None else 'end'} only; first strike: "
              f"fights starting in the window")
    if power is not None:
        print(f"power filter: turns whose acting side's spent-gold ratio within 8 (gold spent by its living bodies within 8 of "
              f"the acting champion, itself included, / both sides') is in [{power[0]}, {power[1]}]. Caveat: the ratio is "
              f"0.5 when neither side has bought anything yet, so an interval holding 0.5 keeps every pre-shop turn "
              f"(first strike is not power-filtered)")
    for label, sel in (("all games", lambda r: True), ("our losses", lambda r: not r["win"]), ("our wins", lambda r: r["win"])):
        rs = [r for r in rows if sel(r)]
        if not rs:
            continue
        tot = [collections.Counter(), collections.Counter()]
        for r in rs:
            tot[0].update(r["side"][r["us"]])
            tot[1].update(r["side"][1 - r["us"]])

        def rate(c, a, b):
            return f"{100 * c[a] / c[b]:5.1f}% of {c[b]:6d}" if c[b] else "      -        "
        nu = len({r.get("unit", r["spec"]) for r in rs})
        print(f"\n{label} ({len(rs)} games)                                     {'us':>17}  {'them':>17}  "
              f"us-them [95% CI over {nu} {'maps' if nu < len(rs) else 'games'}]")
        lines = [
            ("could hit a champion and did not", "no_hit", "could_hit"),
            ("  ... hit a camp instead", "no_hit_camp", "could_hit"),
            ("  ... stepped away without hitting", "no_hit_away", "could_hit"),
            ("  ... moved (not away) without hitting", "no_hit_moved", "could_hit"),
            ("  ... stood without hitting", "no_hit_still", "could_hit"),
            ("damage or stun spell ready and in range, unused", "spell_idle", "spell_ready"),
            ("  ... on engaging turns (hit a champion or ended closer)", "spell_idle_eng", "spell_ready_eng"),
            ("  ... on turns stepping away from the nearest enemy", "spell_idle_away", "spell_ready_away"),
            ("  ... stun ready on turns stepping away", "stun_idle_away", "stun_ready_away"),
            ("hit the lowest-HP champion in range (2+ in range)", "pick_low", "pick_n"),
            ("rounds with 2+ hitters splitting over 2+ targets", "split", "multi"),
            ("ranged champion ending a turn next to an enemy melee", "melee_adj", "free_turns"),
            ("fight turns spent stunned", "stunned", "turns"),
            ("stuns on an already-stunned champion", "stun_waste", "stun_casts"),
            ("stuns on Marcella (immune), when the target fields her", "stun_marc", "stun_casts_marc"),
            ("fights where this side struck first", "first_strike", "fights"),
            ("any spell cast at a champion: caster died within 5 rounds", "cast_died5", "casts"),
            ("pokes (spell at a champion from 2+ tiles, no basic hit): caster died within 5 rounds", "poke_died5", "pokes"),
            ("  baseline: free fight turns 2+ tiles from every foe, died within 5", "calm_died5", "calm_turns"),
            ("ranged, HP 50%+, enemy in range, no enemy can hit the tile next turn: shot", "safe_shot", "safe_n"),
            ("  ... walked off without a shot", "safe_walk", "safe_n"),
            ("fight dashes ending closer to an enemy champion", "dash_closer", "dash_n"),
            ("fight dashes followed by a hit in the same turn", "dash_hit", "dash_n"),
            ("dash ready, HP 35%+, an enemy below 30% 2-4 tiles away: dashed", "chase_used", "chase_n"),
            ("enemy below 35% in my reach but 3+ tiles away: hit it", "fin_hit", "fin_n"),
            ("  ... it died within 3 rounds", "fin_died3", "fin_n"),
            ("below 35% HP next to an enemy: died within 5 rounds", "lowadj_died5", "lowadj_n"),
            ("  ... hit, then dashed", "lowadj_hitdash", "lowadj_n"),
        ]
        for name, a, b in lines:
            bd = boot_diff(rs, a, b)
            ci = f"  {bd[0]:+6.1f} [{bd[1]:+6.1f}, {bd[2]:+6.1f}]{'*' if bd[1] > 0 or bd[2] < 0 else ''}" if bd else ""
            print(f"  {name:52s} {rate(tot[0], a, b)}  {rate(tot[1], a, b)}{ci}")
        for name, a in (("  pokes a game", "pokes"), ("ranged walks with walk + reset + shot open, a game", "kite_miss")):
            print(f"  {name:52s} {tot[0][a] / len(rs):15.1f}  {tot[1][a] / len(rs):17.1f}")
        if power is not None:
            print(f"  {'kept fight turns where nobody within 8 had bought (ratio 0.5)':52s} {rate(tot[0], 'pw_zero', 'pw_turns')}  "
                  f"{rate(tot[1], 'pw_zero', 'pw_turns')}")
        if by_champ:
            print("  by champion and spell: ready-and-in-range turns, share left unused (of which the champion basic-attacked instead)")
            keys = sorted({k[3:] for side in tot for k in side if k.startswith("sr|")})
            for k in keys:
                cells = []
                for side in tot:
                    n = side["sr|" + k]
                    cells.append(f"{100 * side['si|' + k] / n:5.1f}% of {n:5d} ({100 * side['si_hit|' + k] / n:4.1f}%)" if n else f"{'-':>27s}")
                print(f"    {k:34s} {cells[0]:>27s}  {cells[1]:>27s}")
            print("  by champion: chances to hit a champion in range, share not taken")
            keys = sorted({k[3:] for side in tot for k in side if k.startswith("ch|")})
            for k in keys:
                cells = []
                for side in tot:
                    n = side["ch|" + k]
                    cells.append(f"{100 * side['chn|' + k] / n:5.1f}% of {n:5d}" if n else f"{'-':>15s}")
                print(f"    {k:34s} {cells[0]:>15s}  {cells[1]:>15s}")
            print("  finishing chances (an enemy below 35% HP in my reach, 3+ tiles away; free turns) by stance: hit it, and "
                  "for the misses what it did instead (% of misses) and the low enemy's state")
            print(f"    {'side':4s} {'stance':6s} {'chances':>7s} {'missed':>7s}  " + " ".join(f"{h:>12s}" for h in FINMISS)
                  + f" {'recalling':>9s} {'covered':>8s}")
            for sn, side in (("us", tot[0]), ("them", tot[1])):
                for st in ("all", "FLEE", "FINISH", "BASE"):
                    n, m = side[f"fn|{st}"], side[f"fm|{st}"]
                    if not n:
                        continue
                    parts = " ".join(f"{100 * side[f'fm|{st}|{h}'] / m:11.1f}%" if m else f"{'-':>12s}" for h in FINMISS)
                    rec_c = f"{100 * side[f'fm|{st}|recall'] / m:8.1f}% {100 * side[f'fm|{st}|cover'] / m:7.1f}%" if m else ""
                    print(f"    {sn:4s} {st if side.get('fn|n/a') is None or st != 'all' else 'all n/a':6s} {n:7d} "
                          f"{100 * m / n:6.1f}%  {parts} {rec_c}")
            print("    (hit_other: hit another champion; toward_it: moved closer to the low enemy without hitting it; "
                  "closer_other: same distance to it, closer to another enemy; recalling: a low enemy was in a recall "
                  "channel through this turn (still channelling a recall at its next turn start); covered: every low enemy was within 2 "
                  "of a mate at 50%+ HP)")
            print("  spells ready (cooldown 0 at turn start) with an enemy champion in the spell's range (micro_kits.json), "
                  "by champion, slot and stance: share unused, and what it did instead (% of unused)")
            print(f"    {'side':4s} {'champion and spell':30s} {'stance':6s} {'ready':>6s} {'unused':>7s}  "
                  + " ".join(f"{h:>11s}" for h in SPELLDID))
            for sn, side in (("us", tot[0]), ("them", tot[1])):
                keys = sorted({k[3:] for k in side if k.startswith("sp|")},
                              key=lambda k: (k.split("|")[0], ["all", "FLEE", "FINISH", "BASE", "n/a"].index(k.split("|")[1])))
                for k in keys:
                    sk, st = k.split("|")
                    if st == "n/a":
                        continue
                    n, u = side["sp|" + k], side["spu|" + k]
                    parts = " ".join(f"{100 * side['spu|' + k + '|' + h] / u:10.1f}%" if u else f"{'-':>11s}" for h in SPELLDID)
                    stl = st if st != "all" or side.get(f"sp|{sk}|n/a") is None else "all n/a"
                    print(f"    {sn:4s} {sk:30s} {stl:6s} {n:6d} {100 * u / n:6.1f}%  {parts}")
            print("  basic hits with 2+ enemy champions in range, not on the lowest one: what the target hit had instead "
                  "(% of those hits; a hit can have several; team focus is not in the replay)")
            print(f"    {'side':4s} {'lowest by':9s} {'hits':>6s} {'not low':>7s}  " + " ".join(f"{h:>11s}" for h in PICKWHY)
                  + f" {'mean gap':>9s}")
            for sn, side in (("us", tot[0]), ("them", tot[1])):
                for var, vn in (("abs", "HP"), ("pct", "HP %")):
                    n, m = side[f"pk|{var}|n"], side[f"pk|{var}|miss"]
                    if not n:
                        continue
                    parts = " ".join(f"{100 * side[f'pk|{var}|{h}'] / m:10.1f}%" if m else f"{'-':>11s}" for h in PICKWHY)
                    gap = f"{side[f'pk|{var}|gap'] / m:9.1f}" if m else ""
                    print(f"    {sn:4s} {vn:9s} {n:6d} {100 * m / n:6.1f}%  {parts} {gap}")
            print("    (mates: more of our other living bodies could hit the target than the lowest (basic range, or a damage "
                  "or stun spell ready at their next turn within its range); peel: the target stood within 2 of one of our "
                  "bodies below 50% HP or carrying 30+ gems, or within 4 of our channelling body (the attacker included, as "
                  "specified; broad: a melee attacker carrying 30+ gems always counts); peel_mate: the same for the "
                  "attacker's mates only, and true for the target but not for the lowest; none_old: none of the columns "
                  "before mates and peel; none: none of mates, peel_mate and the older columns (the broad peel left out)")
            print("    (gems: target carried more gems; cassi_issac: target was Cassi or Issac; channel: target channelling "
                  "through this turn; stunned: a stun on it since its last turn; closer: target nearer than the lowest; "
                  "other: target lower on the other measure (HP % for the HP row, absolute HP for the HP % row); shield: "
                  "the lowest had a shield and more HP + shield than the target; none: none of these; mean gap: target "
                  "minus lowest, in HP or HP points)")
            print("  by champion and stance: chances to hit a champion in range, share not taken, and what it did instead "
                  "(% of the not-taken chances; stance n/a = not a nova side)")
            print(f"    {'side':4s} {'champion':13s} {'stance':6s} {'chances':>7s} {'not taken':>9s}  "
                  + " ".join(f"{h:>8s}" for h in NOHIT))
            for sn, side in (("us", tot[0]), ("them", tot[1])):
                keys = sorted({k[3:] for k in side if k.startswith("cs|")},
                              key=lambda k: (k.split("|")[0], ["all", "FLEE", "FINISH", "BASE", "n/a"].index(k.split("|")[1])))
                for k in keys:
                    n, nn = side["cs|" + k], side["csn|" + k]
                    ch, st = k.split("|")
                    if st == "n/a":
                        continue  # the same chances as the 'all' row
                    parts = " ".join(f"{100 * side['csn|' + k + '|' + h] / nn:7.1f}%" if nn else f"{'-':>8s}" for h in NOHIT)
                    stl = st if st != "all" else ("all" if any(side.get(f"cs|{ch}|{z}") for z in ("FLEE", "FINISH", "BASE")) else "all n/a")
                    print(f"    {sn:4s} {ch:13s} {stl:6s} {n:7d} {100 * nn / n:8.1f}%  {parts}")
        far0 = 100 * tot[0]["dmg_far"] / max(1, tot[0]["dmg_all"])
        far1 = 100 * tot[1]["dmg_far"] / max(1, tot[1]["dmg_all"])
        print(f"  {'champion damage dealt from 4+ tiles':52s} {far0:5.1f}% of {tot[0]['dmg_all']:8.0f}  {far1:5.1f}% of {tot[1]['dmg_all']:8.0f}")


# ---------------------------------------------------------------- step-by-step fight tables
def cmd_walk(argv):
    us = opt(argv, "--us", None)
    fight_n = opt(argv, "--fight", None, int)
    worst = opt(argv, "--worst", 3, int)
    if not argv:
        sys.exit(__doc__)
    g = RP.load(argv[0], us)
    kits = load_kits()
    recs, _, _, _ = analyse(g, kits)
    by_rt = {(x["r"], x["c"]): x for x in recs}
    fs = [f for f in RP.fights(g) if sum(f["deaths"]) or sum(f["dmg"].values()) >= 300]
    usv = g.us
    if fight_n is not None:
        pick = [fs[fight_n]] if 0 <= fight_n < len(fs) else []
    else:
        pick = sorted(fs, key=lambda f: (f["deaths"][1 - usv] - f["deaths"][usv], f["dmg"][usv] - f["dmg"][1 - usv]))[:worst]
        pick.sort(key=lambda f: f["start"])
    print(f"{g.meta.get('map', '?')} vs {g.team_name(1 - usv)}; us = team {'AB'[usv]}; {len(fs)} fights with a death or 300+ damage")
    for f in pick:
        k = fs.index(f)
        parts = f["part"][0] | f["part"][1]
        print(f"\n== fight {k}: rounds {f['start']}-{f['end']} at ({f['cx']:.0f},{f['cy']:.0f}), bodies near {f['near'][usv]} vs "
              f"{f['near'][1 - usv]}, damage {f['dmg'][usv]:.0f} vs {f['dmg'][1 - usv]:.0f}, deaths {f['deaths'][usv]} vs "
              f"{f['deaths'][1 - usv]} ({RP.fight_result(f, usv)})")
        print(f"   {'rnd':>4} {'champion':22s} {'hp':>11} {'pos':>15} {'foe':>4} {'cd':>5}  action / flags")
        for t in g.turns:
            if t[0] < f["start"] - 1 or t[0] > f["end"] + 1 or t[1] not in parts:
                continue
            x = by_rt.get((t[0], t[1]))
            side = "us  " if g.team_of[t[1]] == usv else "them"
            if not t[g.ci["alive"]]:
                continue
            flags = []
            if x:
                if x["stunned"]:
                    flags.append("STUNNED")
                if x["free"] and x["in_range"] and not x["hit"]:
                    flags.append("NO HIT (" + ("hit camp" if x["camp"] else ("stepped away" if (x["toward"] or 0) > 0 else ("moved" if x["moved"] else "stood"))) + ")")
                if x["free"] and x["spell_ready"] and not x["spell_used"]:
                    flags.append("SPELL IDLE " + ",".join(f"s{s} {ABIL[a]}" for s, a in x["spell_ready"]))
                if any(not p for p in x["picks"]):
                    flags.append("NOT THE LOWEST")
                if x["melee_adj"]:
                    flags.append("RANGED NEXT TO MELEE")
            e = RP.turn_end_pos(t)
            cd = f"{t[g.ci['cd0']]}/{t[g.ci['cd1']]}"
            print(f"   {t[0]:4d} {side} {g.who(t[1]):17s} {t[4]:5d}/{t[5]:<5d} ({t[2]:2d},{t[3]:2d})>({e[0]:2d},{e[1]:2d}) "
                  f"{x['dmin'] if x else '-':>4} {cd:>5}  {RP.fmt_acts(g, t)[:80]}" + (f"  [{'; '.join(flags)}]" if flags else ""))


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a.pop(0)
    if cmd == "kits":
        kits = build_kits(RP.expand_specs(a))
        for typ in sorted(kits, key=int):
            k = kits[typ]
            print(f"{BODY[int(typ)] if int(typ) < len(BODY) else typ:13s} attack {k['attack']}  " + "  ".join(
                f"s{s}:{ABIL[v['atype']] if v['atype'] < len(ABIL) else v['atype']}({v['range']})" for s, v in sorted(k["spells"].items())))
    elif cmd == "stats":
        cmd_stats(a)
    elif cmd == "walk":
        cmd_walk(a)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
