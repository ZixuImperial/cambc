"""b2120 RWB Step 0 node reader (readmany): v1 facts + our deaths (gems/gold carried), first-emblem rounds, alive body-rounds, result."""
import collections
import replay
import b2120_rwbread


def read(path, meta):
    out = b2120_rwbread.read(path, meta)
    g = replay.load(path, us=replay.reader_seat(path, meta))
    us = g.us
    ci = g.ci
    last = {}
    deaths = []
    emb = {}
    cnt = collections.defaultdict(lambda: collections.Counter())
    alive_rounds = 0
    shops = []
    for t in g.turns:
        b = t[1]
        if g.team_of.get(b) != us:
            continue
        if t[ci["alive"]]:
            alive_rounds += 1
        for a in t[-1]:
            if a[0] == "s":
                shops.append([t[0], b, sum(n for it, n in a[1]), a[3] if len(a) > 3 else 0])
                for it, n in a[1]:
                    cnt[b][it] += n
                    need = 25 if 72 <= it <= 77 else 5
                    if it % 2 == 0 and cnt[b][it] >= need and b not in emb:
                        emb[b] = t[0]
        last[b] = t
    prev = {}
    for t in g.turns:
        b = t[1]
        if g.team_of.get(b) != us:
            continue
        p = prev.get(b)
        if p is not None and p[ci["alive"]] and not t[ci["alive"]]:
            deaths.append([t[0], b, p[ci["gems"]], p[ci["gold"]]])
        prev[b] = t
    sub = (g.final or {}).get("submitted") or [0, 0]
    out.update(shops=shops, deaths=deaths, emblem=emb, alive_rounds=alive_rounds, sub=sub,
               win=1 if sub[us] > sub[1 - us] else (0 if sub[us] < sub[1 - us] else 0.5))
    return out
