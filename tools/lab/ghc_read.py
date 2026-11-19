"""ghc_read: heavy camps (golem / monolith) our team damaged by >= 30% and then left alive (Deep subagent, 10 Nov, golem half-clear).
readmany reader: read(path, meta) -> {"eps": [...], "lives": n, "end": r}. One episode per leave: our damage stops for >= GAP rounds
while the heavy camp is alive and >= 30% of its health is gone. Fields: group, type, life start, last hit round, frac gone, return
round (our next hit on it, same life; None), presence return (our next body within 5 tiles), foe damage in between, killer team,
capture team and round (that life; None)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay  # noqa: E402

GAP = 10
HEAVY = (4, 5)  # monolith, golem


def cheb(a, b, c, d):
    return max(abs(a - c), abs(b - d))


def read(path, meta):
    g = replay.load(path, us=meta.get("seat", "A").upper())
    us = g.us
    end = g.rounds[-1][0] if g.rounds else 0
    heavy = {c: v for c, v in g.camps.items() if v["type"] in HEAVY}
    if not heavy:
        return {"eps": [], "lives": 0, "end": end}
    maxhp = {c: float(v["hp"]) for c, v in heavy.items()}
    # events by round
    deaths, respawns, caps = {}, {}, {}
    for e in g.events:
        if e[1] == "camp_death" and e[2] in heavy:
            deaths[e[2]] = deaths.get(e[2], []) + [(e[0], (0 if g.team_of[e[4]] == us else 1) if (e[3] == 1 and e[4] >= 0) else -1)]
        elif e[1] == "group_respawn":
            respawns.setdefault(e[2], []).append(e[0])
        elif e[1] == "capture" and e[3] in (0, 1):
            for gid in (e[2] if isinstance(e[2], list) else [e[2]]):
                caps.setdefault(gid, []).append((e[0], 0 if e[3] == us else 1))
    # per heavy camp: hits per round per team, our presence rounds
    hits = {c: {} for c in heavy}
    pres = {c: set() for c in heavy}
    for t in g.turns:
        if t[g.ci["alive"]] and t[2] >= 0 and g.team_of[t[1]] == us:
            for c, v in heavy.items():
                if cheb(t[2], t[3], v["x"], v["y"]) <= 5:
                    pres[c].add(t[0])
        for cid, dmg in replay.camp_hits(g, t):
            if cid in heavy:
                side = 0 if g.team_of[t[1]] == us else 1
                d = hits[cid].setdefault(t[0], [0.0, 0.0])
                d[side] += dmg
    eps = []
    lives = 0
    for c, v in heavy.items():
        gid = v["group"]
        starts = [0] + sorted(r for r in respawns.get(gid, []))
        for li, s in enumerate(starts):
            e_end = starts[li + 1] if li + 1 < len(starts) else end + 1
            dr = [(r, k) for r, k in deaths.get(c, []) if s <= r < e_end]
            death_r, killer = (dr[0] if dr else (None, None))
            cp = [(r, k) for r, k in caps.get(gid, []) if s <= r < e_end]
            cap_r, cap_t = (cp[0] if cp else (None, None))
            alive_to = death_r if death_r is not None else e_end
            rs = sorted(r for r in hits[c] if s <= r < alive_to)
            if not rs:
                continue
            lives += 1
            hp = maxhp[c]
            ours = [r for r in rs if hits[c][r][0] > 0]
            if not ours:
                continue
            # walk rounds; a leave = our last hit followed by >= GAP rounds without our hit while alive
            cum = 0.0
            cum_at = {}
            for r in rs:
                cum += hits[c][r][0] + hits[c][r][1]
                cum_at[r] = cum
            def gone_by(r):
                x = 0.0
                for q in rs:
                    if q > r:
                        break
                    x = cum_at[q]
                return x / hp
            for i, r in enumerate(ours):
                nxt = ours[i + 1] if i + 1 < len(ours) else None
                stop = nxt if nxt is not None else alive_to
                if stop - r < GAP or r + GAP >= alive_to:
                    continue
                fg = gone_by(r)
                if fg < 0.30 or fg >= 1.0:
                    continue
                pr = [q for q in sorted(pres[c]) if r + 3 < q < alive_to]
                # presence return: first presence after a stretch away (>= 3 rounds out of reach after r)
                pret = None
                last = r
                for q in sorted(pres[c]):
                    if q <= r:
                        continue
                    if q >= alive_to:
                        break
                    if q - last > 3:
                        pret = q
                        break
                    last = q
                foe_between = sum(hits[c][q][1] for q in rs if r < q < (nxt if nxt is not None else alive_to))
                eps.append({"g": gid, "type": v["type"], "life": s, "last_hit": r, "gone": round(fg, 3), "ret_hit": nxt,
                            "ret_pres": pret, "foe_dmg_between": round(foe_between), "death": death_r, "killer": killer,
                            "cap": cap_r, "cap_team": cap_t, "first_of_life": not any(e["g"] == gid and e["life"] == s and e["type"] == v["type"]
                                                                                     for e in eps)})
    return {"eps": eps, "lives": lives, "end": end}


if __name__ == "__main__":
    import json
    print(json.dumps(read(sys.argv[1], {"seat": sys.argv[2] if len(sys.argv) > 2 else "A"}), indent=None))
