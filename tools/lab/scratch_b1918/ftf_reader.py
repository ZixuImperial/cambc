"""b1918 FTF1 count: foe Tavi off-spawn max-HP rises and our hits on him while he reads 'weak' only through unhealed max HP."""
import bisect
import replay


def onspawn(g, team, x, y):
    s = g.spawn[team]
    return s[0] <= x <= s[2] and s[1] <= y <= s[3]


def read(path, meta):
    g = replay.load(path, us=meta.get("seat", "A").upper())
    ci = g.ci
    us = g.us
    tavis = [b["id"] for b in g.d["bodies"] if b["team"] != us and b["name"] == "tavi"] if "name" in g.d["bodies"][0] else []
    if not tavis:
        tavis = [b["id"] for b in g.d["bodies"] if b["team"] != us and "tavi" in g.who(b["id"])]
    res = {"tavi": len(tavis), "rises": 0, "rise_hp": 0, "turns_mis": 0, "hits": 0, "hits_mis": 0, "hits_mis_full": 0,
           "vv_hits_mis": 0, "hits_by": {}, "max_u": 0, "rounds": g.last_round}
    for tv in tavis:
        team = g.team_of[tv]
        rows = sorted(g.by_champ[tv], key=lambda t: t[0])
        rs, st = [], []
        U, pm = 0, None
        for t in rows:
            hp, mh, al = t[ci["hp"]], t[ci["maxHp"]], t[ci["alive"]]
            if not al:
                U, pm = 0, None
                rs.append(t[0]); st.append((hp, mh, 0, False))
                continue
            sp = onspawn(g, team, t[2], t[3])
            if pm is not None and mh > pm and not sp:
                U += mh - pm
                res["rises"] += 1
                res["rise_hp"] += mh - pm
            if sp:
                U = 0
            U = max(0, min(U, mh - hp))
            pm = mh
            res["max_u"] = max(res["max_u"], U)
            mis = U > 0 and hp < 0.5 * mh and hp >= 0.5 * (mh - U)
            res["turns_mis"] += mis
            rs.append(t[0]); st.append((hp, mh, U, mis))
        for t in g.turns:
            if g.team_of.get(t[1]) != us:
                continue
            hit = False
            for a in t[-1]:
                if a[0] == "a" and a[1] == 1 and a[2] == tv:
                    hit = True
                elif a[0] == "c" and any(k == 1 and i == tv for k, i, d in a[7]):
                    hit = True
            if not hit:
                continue
            res["hits"] += 1
            k = bisect.bisect_right(rs, t[0]) - 1  # Tavi's latest turn at or before this round
            if k < 0:
                continue
            hp, mh, U, mis = st[k]
            if mis:
                res["hits_mis"] += 1
                w = g.who(t[1]).split(":")[1].split("(")[0]
                res["hits_by"][w] = res["hits_by"].get(w, 0) + 1
                if w == "vesper_vale":
                    res["vv_hits_mis"] += 1
                if hp >= mh - U:
                    res["hits_mis_full"] += 1
    return res
