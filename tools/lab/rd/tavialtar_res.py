"""tavi one-altar census (analyst, 11 Nov; spec tavi_one_altar_1111): per game, map altar/gold features from the replay and, per side,
altar presence by 300-round band, kills near the altar, carrier kills, tribute starts and how they end. read(path, meta) for readmany."""
import collections
import replay

GOLD = [40, 90, 0, 20, 300, 160]
GEMS = [4, 15, 7, 0, 200, 36]
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def comps(alt):
    alt = set(alt); seen = set(); n = 0
    for a in alt:
        if a in seen:
            continue
        n += 1; st = [a]; seen.add(a)
        while st:
            x, y = st.pop()
            for dx, dy in N8:
                q = (x + dx, y + dy)
                if q in alt and q not in seen:
                    seen.add(q); st.append(q)
    return n


def read(path, meta):
    g = replay.load(path, us=meta.get("seat", "A").upper())
    ci = g.ci; us = g.us
    alt = set(g.altars)
    W, H = g.W, g.H
    block = {(x, y) for y, row in enumerate(g.rows) for x, ch in enumerate(row) if ch in "#o"} | alt
    src = [(x + dx, y + dy) for x, y in alt for dx, dy in N8 if 0 <= x + dx < W and 0 <= y + dy < H and (x + dx, y + dy) not in block]
    dist = {p: 0 for p in src}; q = collections.deque(src)
    while q:
        x, y = q.popleft()
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in block and p not in dist:
                dist[p] = dist[(x, y)] + 1; q.append(p)
    gold = g6 = g10 = gems = m10 = 0
    for c in g.camps.values():
        go, ge = GOLD[c["type"]], GEMS[c["type"]]
        d = dist.get((c["x"], c["y"]), 999)
        gold += go; gems += ge
        g6 += go * (d <= 6); g10 += go * (d <= 10); m10 += ge * (d <= 10)

    def near(x, y, R=6):
        return any(max(abs(x - a), abs(y - b)) <= R for a, b in alt)

    names = {b["id"]: b.get("name", "?") for b in g.d["bodies"]}
    side = lambda c: "us" if g.team_of[c] == us else "foe"
    res = dict(nalt=comps(alt), W=W, H=H, gold=gold, gems=gems, g6=g6, g10=g10, m10=m10, rounds=g.last_round,
               T=sum(1 for b in g.d["bodies"] if b["team"] == 0),
               lineup={s: sorted(names[c] for c in names if side(c) == s) for s in ("us", "foe")},
               sub=dict(us=g.final.get("submitted", [0, 0])[us], foe=g.final.get("submitted", [0, 0])[1 - us]))
    P = {s: collections.defaultdict(lambda: [0, 0]) for s in ("us", "foe", "us_tavi", "foe_tavi")}  # band -> [near, alive]
    for t in g.turns:
        if not t[ci["alive"]]:
            continue
        c = t[1]; b = min(6, t[0] // 300); n = near(t[2], t[3])
        s = side(c)
        P[s][b][0] += n; P[s][b][1] += 1
        if names[c] == "tavi":
            P[s + "_tavi"][b][0] += n; P[s + "_tavi"][b][1] += 1
    res["pres"] = {s: {str(b): v for b, v in d.items()} for s, d in P.items()}
    K = {s: collections.Counter() for s in ("us", "foe")}  # keyed by the KILLER's side
    for e in g.events:
        if e[1] != "death" or e[3] != 1 or e[4] < 0 or e[4] not in g.team_of:
            continue
        s = side(e[4]); n = near(e[6], e[7]); tv = names[e[4]] == "tavi"; bag = e[5]
        k = K[s]
        k["kills"] += 1; k["kills_near"] += n; k["gems"] += bag; k["gems_near"] += bag * n
        k["carr"] += bag >= 20; k["carr_near"] += (bag >= 20) * n
        if tv:
            k["tv_kills"] += 1; k["tv_kills_near"] += n; k["tv_carr"] += bag >= 20; k["tv_carr_near"] += (bag >= 20) * n
            k["tv_gems"] += bag; k["tv_gems_near"] += bag * n
        if e[0] >= 300:
            k["kills_near300"] += n
    res["kills"] = {s: dict(v) for s, v in K.items()}
    # tribute starts and how they end (keyed by the TRIBUTER's side)
    trib_ev = collections.defaultdict(list); death_ev = collections.defaultdict(list)
    for e in g.events:
        if e[1] == "tribute":
            trib_ev[e[2]].append(e[0])
        elif e[1] == "death":
            death_ev[e[2]].append(e[0])
    T = {s: collections.Counter() for s in ("us", "foe")}
    for c, ts in g.by_champ.items():
        s = side(c); i = 0
        while i < len(ts):
            t = ts[i]
            if not any(a[0] == "t" for a in t[-1]):
                i += 1; continue
            bag = t[ci["gems"]]; stun = False; j = i + 1
            while j < len(ts):
                u = ts[j]
                bag = max(bag, u[ci["gems"]]); stun = stun or bool(u[ci["stunned"]])
                if not u[ci["alive"]] or (u[ci["chType"]] != 2 and not any(a[0] == "t" for a in u[-1])):
                    break
                j += 1
            r1 = ts[j][0] if j < len(ts) else 10 ** 9
            if any(t[0] <= r <= r1 for r in trib_ev[c]):
                out = "land"
            elif any(t[0] <= r <= r1 for r in death_ev[c]):
                out = "killed"
            elif stun:
                out = "stun"
            else:
                out = "abandon"
            nr = near(t[2], t[3], 2)
            T[s]["start"] += 1; T[s][out] += 1
            if bag >= 20:
                T[s]["start20"] += 1; T[s][out + "20"] += 1; T[s]["gems_" + out] += bag
            i = max(j, i + 1)
    for e in g.events:
        if e[1] == "tribute":
            T["us" if e[3] == us else "foe"]["ev"] += 1
            T["us" if e[3] == us else "foe"]["ev_gems"] += e[4]
    res["trib"] = {s: dict(v) for s, v in T.items()}
    return res
