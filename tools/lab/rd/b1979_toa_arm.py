"""b1979 TOA arm reader (one game). Seat from the file name: MAP__a = candidate is team A, MAP__b = team B.
Rows: win, our/their tributes and gems, foe tribute channels cancelled under a stun, deaths (ours, at the altar within 6), our kills of
foe carriers (bag >= 20) and gems taken, Tavi rows (rounds to Strength 60 / 120, gold earned, share of alive rounds within 4 of the altar
after the foe's first tribute)."""
import os
import replay


def read(path, meta):
    sm = str((meta or {}).get("seat", "")).upper()  # readmany passes the seat (a/b); nodes rename the file
    seat = sm if sm in ("A", "B") else ("A" if os.path.basename(path).split("__")[-1].startswith("a") else "B")
    g = replay.load(path, us=seat)
    us, them = g.us, 1 - g.us
    f = g.final or {}
    out = f.get("outcome")
    win = 1 if out == us + 1 else 0
    ci = g.ci
    alt = g.altars
    da = lambda x, y: min((max(abs(x - a[0]), abs(y - a[1])) for a in alt), default=99)
    r = dict(win=win, rounds=g.last_round, sub=f.get("submitted"), us=us)
    trib = [0, 0]
    tgems = [0, 0]
    first_foe_trib = None
    for e in g.events:
        if e[1] == "tribute":
            t = e[3]
            trib[t] += 1
            tgems[t] += e[4]
            if t == them and e[4] >= 20 and first_foe_trib is None:
                first_foe_trib = e[0]
    r.update(trib_us=trib[us], trib_them=trib[them], tg_us=tgems[us], tg_them=tgems[them])
    d_us = d_alt = k_car = k_gems = d_them = 0
    for e in g.events:
        if e[1] != "death":
            continue
        v = e[2]
        if g.team_of.get(v) == us:
            d_us += 1
            if da(e[6], e[7]) <= 6:
                d_alt += 1
        else:
            d_them += 1
            if g.team_of.get(e[4]) == us and e[3] != 2 and e[5] >= 20:
                k_car += 1
                k_gems += e[5]
    r.update(d_us=d_us, d_alt=d_alt, d_them=d_them, k_car=k_car, k_gems=k_gems)
    canc = 0
    for c, ts in g.by_champ.items():
        if g.team_of.get(c) != them:
            continue
        for a, b in zip(ts, ts[1:]):
            if a[ci["chType"]] == 2 and b[ci["stunned"]] and b[ci["chType"]] != 2:
                canc += 1
    r["foe_canc"] = canc
    tv = [b["id"] for b in g.d["bodies"] if b["team"] == us and b["name"] == "tavi"]
    r["tavi"] = 1 if tv else 0
    if tv:
        ts = g.by_champ[tv[0]]
        s60 = next((t[0] for t in ts if t[ci["strength"]] >= 60), -1)
        s120 = next((t[0] for t in ts if t[ci["strength"]] >= 120), -1)
        post = [t for t in ts if first_foe_trib is not None and t[0] >= first_foe_trib and t[ci["alive"]]]
        near = sum(1 for t in post if da(t[2], t[3]) <= 4)
        r.update(t_s60=s60, t_s120=s120, t_earned=ts[-1][ci["earned"]] if ts else 0, t_post_n=len(post), t_post_near=near,
                 t_deaths=sum(1 for e in g.events if e[1] == "death" and e[2] == tv[0]))
    names = sorted(b["name"] for b in g.d["bodies"] if b["team"] == us)
    r["lineup"] = ",".join(names)
    return r
