"""forcedchoke (b2390, 13 Nov; chooser plan 8, owner via the Planner: "The chokepoint value is better if forced there and also it could be
gold in the centre for example and we are competing for that"). Draft-time map features from a MAP FILE only, no map identity. Seat A = us.
Walk: 8-way steps over tiles that are not wall, hole, altar or camp (bodies walk round living camps); a resource is reached at a passable
tile next to it. Zones as gpl.py: rho = walk_A / (walk_A + walk_B), OWN < .40, CENTRE .40-.60, THEIR > .60.
CONTESTED RESOURCES (value per 100 rounds, gold at the bot's exchange rate PG_GOLD_PER_GEM = 20 gold a gem): centre camp groups (gems +
gold / 20, over the group's respawn, gpl.py's tables), and centre altars (each worth the map's gem rate / number of altars).
FOE ROUTES to a resource: from B's spawn and from each of B's farm-loop groups (THEIR zone). A CHOKE tile c (tried along B's shortest
spawn route to the resource): block every tile within Chebyshev 2 of c; a route PASSES c when its walk to the resource grows; share = the
passing routes' fraction (a choke whose disc touches B's spawn or the resource's approach tiles is not tried; an origin
inside the disc is skipped); detour = the smallest growth among them (99 when a route is cut off). Per resource the choke with the highest
share (then the larger detour) is kept.
PLAN 8 (forced-choke hold): a kept choke with detour >= FC_DETOUR (10) whose tile is within FC_NEAR (8) walk of our farm loop (A's spawn or
an OWN-zone group); its guarded value = the contested value of every resource whose kept choke qualifies and lies within 2 of it; the hold
target = the qualifying choke guarding the most value; fc_plan8 = 1 when that value is >= FC_SHARE (.25) of the map's contested value.
Classes: fc_plan8 (0/1), fc_share (guarded share of contested value, 0 if none), fc_detour (the hold choke's detour), fc_route (its route
share), fc_hold (x * 1000 + y, -1 none), fc_cval (contested value per 100 rounds). --class 'fc_plan8:>=1'."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

GEMS = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
GOLD = {0: 40, 1: 90, 2: 0, 3: 20, 4: 300, 5: 160}
RESP = {0: 40, 1: 60, 2: 50, 3: 50, 4: 150, 5: 80}
EXR = 20.0
FC_DETOUR, FC_NEAR, FC_SHARE, FC_R = 10, 8, 0.25, 2
INF = 1 << 30
_c = {}


def _feat(path):
    if path in _c:
        return _c[path]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    camps = m["camps"]
    N = W * H
    blk = bytearray(N)
    for (x, y) in set(m["wall"]) | set(m["hole"]) | set(m["altar"]) | set(camps):
        if 0 <= x < W and 0 <= y < H:
            blk[y * W + x] = 1
    nb = []
    for i in range(N):
        x, y = i % W, i // W
        nb.append([(y + dy) * W + x + dx for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   if (dx or dy) and 0 <= x + dx < W and 0 <= y + dy < H])

    def bfs(src, extra=None):
        d = [INF] * N
        q = collections.deque()
        for s in src:
            if not blk[s] and (extra is None or s not in extra) and d[s] == INF:
                d[s] = 0
                q.append(s)
        while q:
            t = q.popleft()
            dn = d[t] + 1
            for u in nb[t]:
                if d[u] == INF and not blk[u] and (extra is None or u not in extra):
                    d[u] = dn
                    q.append(u)
        return d

    def around(tiles):  # passable tiles next to a set of (x, y)
        out = set()
        for (x, y) in tiles:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if 0 <= x + dx < W and 0 <= y + dy < H and not blk[(y + dy) * W + x + dx]:
                        out.add((y + dy) * W + x + dx)
        return out

    sA = [y * W + x for (x, y) in m["spawnA"]]
    sB = [y * W + x for (x, y) in m["spawnB"]]
    dA, dB = bfs(sA), bfs(sB)
    # camp groups (4-connected), as gpl.py
    seen, groups = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        st, pts = [c], []
        seen.add(c)
        while st:
            x, y = st.pop()
            pts.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        ty = [camps[p] for p in pts]
        resp = max(RESP.get(t, 50) for t in ty)
        groups.append(dict(pts=pts, gr=sum(GEMS.get(t, 0) for t in ty) * 100.0 / resp,
                           orr=sum(GOLD.get(t, 0) for t in ty) * 100.0 / resp, adj=around(pts)))
    total_gr = sum(g["gr"] for g in groups)

    def rho(adj):
        a = min((dA[i] for i in adj), default=INF)
        b = min((dB[i] for i in adj), default=INF)
        if a >= INF or b >= INF:
            return None
        return a / max(1e-9, a + b)

    res, own, theirs = [], [], []
    for g in groups:
        r = rho(g["adj"])
        if r is None:
            continue
        if r < 0.40:
            own.append(g)
        elif r > 0.60:
            theirs.append(g)
        elif g["gr"] + g["orr"] / EXR > 0:
            res.append(dict(adj=g["adj"], val=g["gr"] + g["orr"] / EXR))
    alts = list(m["altar"])
    for a in alts:
        adj = around([a])
        r = rho(adj)
        if r is not None and 0.40 <= r <= 0.60 and total_gr > 0:
            res.append(dict(adj=adj, val=total_gr / len(alts)))
    cval = sum(r["val"] for r in res)
    if not res or cval <= 0:
        _c[path] = (0, 0.0, 0, 0.0, -1, cval)
        return _c[path]
    dF = bfs(sA + [i for g in own for i in g["adj"]])  # our farm loop
    origins = [sB] + [list(g["adj"]) for g in theirs]
    kept = []
    for r in res:
        dR = bfs(list(r["adj"]))
        base = [min((dR[i] for i in o), default=INF) for o in origins]
        b0 = base[0]
        if b0 >= INF:
            continue
        # candidates: tiles on a shortest B-spawn route, one level in two
        cand = [i for i in range(N) if not blk[i] and dB[i] < INF and dR[i] < INF and dB[i] + dR[i] == b0 and dR[i] >= FC_R + 2 and dB[i] >= FC_R + 2]  # the disc touches neither B's spawn nor the resource's approach
        cand.sort(key=lambda i: dR[i])
        lv, pick = -1, []
        for i in cand:
            if dR[i] % 2 == 0 and len(pick) < 60:
                pick.append(i)
        best = None
        for c in pick:
            cx, cy = c % W, c // W
            disc = {(cy + dy) * W + cx + dx for dx in range(-FC_R, FC_R + 1) for dy in range(-FC_R, FC_R + 1)
                    if 0 <= cx + dx < W and 0 <= cy + dy < H}
            d2 = bfs([i for i in r["adj"] if i not in disc], disc)
            npass, det = 0, INF
            for o, b in zip(origins, base):
                if b >= INF:
                    continue
                if all(i in disc for i in o):
                    continue  # the disc covers this origin itself: not a route through a choke
                nb2 = min((d2[i] for i in o if i not in disc), default=INF)
                g = 99 if nb2 >= INF else nb2 - b
                if g > 0:
                    npass += 1
                    det = min(det, g)
            nvalid = sum(1 for b in base if b < INF)
            sh = npass / max(1, nvalid)
            key = (sh, det if det < INF else 0)
            if npass and (best is None or key > best[0]):
                best = (key, c, det, sh)
        if best:
            kept.append(dict(c=best[1], det=best[2], share=best[3], val=r["val"]))
    q = [k for k in kept if k["det"] >= FC_DETOUR and dF[k["c"]] <= FC_NEAR]
    top = None
    for k in q:
        kx, ky = k["c"] % W, k["c"] // W
        gv = sum(j["val"] for j in q if max(abs(j["c"] % W - kx), abs(j["c"] // W - ky)) <= 2)
        if top is None or gv > top[0]:
            top = (gv, k)
    if top is None:
        _c[path] = (0, 0.0, 0, 0.0, -1, cval)
    else:
        gv, k = top
        shv = gv / cval
        _c[path] = (1 if shv >= FC_SHARE else 0, shv, k["det"], k["share"], (k["c"] % W) * 1000 + k["c"] // W, cval)
    return _c[path]


def _f(i):
    return lambda p, _m=None: _feat(p)[i]


CLASSES = {"fc_plan8": _f(0), "fc_share": _f(1), "fc_detour": _f(2), "fc_route": _f(3), "fc_hold": _f(4), "fc_cval": _f(5)}


# ---- HOLD+FARM (owner via the Planner, 13 Nov: "it is better to hold a choke if it lets us farm a lot more") ----
# Our FARM = camp groups with rho < .50 (our half, centre edge included) and value > 0 (gem rate + gold rate / 20 per 100 rounds).
# FOE origins = B's spawn and B's farm (THEIR-zone groups' approach tiles). A choke c (tried along the foe's shortest routes to each of our
# farm groups, one level in two, never touching the foe's origins): block Chebyshev 2 around c and re-walk from the foe's origins; a farm
# group is PROTECTED when the foe's walk to it grows by >= FC_DETOUR (99 = cut off) and the disc does not cover its approach. The holder
# stands at c, within FC_NEAR walk of a protected group. Value per 100 rounds = protected income - the holder's lost farm (our farm income /
# team size); safe rounds proxy = the smallest protected detour. hf_plan8 = 1 when that value > 0.
# Classes: hf_plan8, hf_value (per 100 rounds), hf_income (protected income per 100 rounds), hf_detour, hf_share (protected / our farm
# income), hf_hold (x * 1000 + y, -1 none).
_h = {}


def _hold_farm(path):
    if path in _h:
        return _h[path]
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    camps = m["camps"]
    N = W * H
    blk = bytearray(N)
    for (x, y) in set(m["wall"]) | set(m["hole"]) | set(m["altar"]) | set(camps):
        if 0 <= x < W and 0 <= y < H:
            blk[y * W + x] = 1
    nb = [None] * N

    def nbr(i):
        if nb[i] is None:
            x, y = i % W, i // W
            nb[i] = [(y + dy) * W + x + dx for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                     if (dx or dy) and 0 <= x + dx < W and 0 <= y + dy < H]
        return nb[i]

    def bfs(src, extra=None):
        d = [INF] * N
        q = collections.deque()
        for s in src:
            if not blk[s] and (extra is None or s not in extra) and d[s] == INF:
                d[s] = 0
                q.append(s)
        while q:
            t = q.popleft()
            dn = d[t] + 1
            for u in nbr(t):
                if d[u] == INF and not blk[u] and (extra is None or u not in extra):
                    d[u] = dn
                    q.append(u)
        return d

    def around(tiles):
        out = set()
        for (x, y) in tiles:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if 0 <= x + dx < W and 0 <= y + dy < H and not blk[(y + dy) * W + x + dx]:
                        out.add((y + dy) * W + x + dx)
        return out

    sA = [y * W + x for (x, y) in m["spawnA"]]
    sB = [y * W + x for (x, y) in m["spawnB"]]
    dA, dB = bfs(sA), bfs(sB)
    seen, farm, theirs = set(), [], []
    for c in sorted(camps):
        if c in seen:
            continue
        st, pts = [c], []
        seen.add(c)
        while st:
            x, y = st.pop()
            pts.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        ty = [camps[p] for p in pts]
        resp = max(RESP.get(t, 50) for t in ty)
        val = (sum(GEMS.get(t, 0) for t in ty) + sum(GOLD.get(t, 0) for t in ty) / EXR) * 100.0 / resp
        adj = around(pts)
        a = min((dA[i] for i in adj), default=INF)
        b = min((dB[i] for i in adj), default=INF)
        if a >= INF or b >= INF or val <= 0:
            continue
        r = a / max(1e-9, a + b)
        if r < 0.50:
            farm.append(dict(adj=adj, val=val))
        elif r > 0.60:
            theirs.append(adj)
    team = max(1, int(m.get("champs_per_team") or 3))
    tot = sum(g["val"] for g in farm)
    res = (0, 0.0, 0.0, 0, 0.0, -1)
    if not farm or tot <= 0:
        _h[path] = res
        return res
    origins = list(sB) + [i for adj in theirs for i in adj]
    oset = set(origins)
    dF = bfs(origins)
    for g in farm:
        g["b"] = min((dF[i] for i in g["adj"]), default=INF)
    cand = set()
    for g in farm:
        if g["b"] >= INF:
            continue
        dG = bfs(list(g["adj"]))
        lv = [i for i in range(N) if not blk[i] and dF[i] < INF and dG[i] < INF and dF[i] + dG[i] == g["b"]
              and dF[i] >= FC_R + 2 and dG[i] >= 1 and dF[i] % 2 == 0]
        lv.sort(key=lambda i: dF[i])
        cand.update(lv[:20])
    cand = sorted(cand)[:120]
    best = None
    for c in cand:
        cx, cy = c % W, c // W
        disc = {(cy + dy) * W + cx + dx for dx in range(-FC_R, FC_R + 1) for dy in range(-FC_R, FC_R + 1)
                if 0 <= cx + dx < W and 0 <= cy + dy < H}
        if disc & oset:
            continue
        d2 = bfs(origins, disc)
        inc, det = 0.0, INF
        for g in farm:
            if g["b"] >= INF or all(i in disc for i in g["adj"]):
                continue
            nb2 = min((d2[i] for i in g["adj"] if i not in disc), default=INF)
            gd = 99 if nb2 >= INF else nb2 - g["b"]
            if gd >= FC_DETOUR and min((dA[i] for i in g["adj"]), default=INF) < INF:
                inc += g["val"]
                det = min(det, gd)
        if inc <= 0:
            continue
        dH = bfs([c])  # the holder's walk to the protected region
        ok_near = any(min((dH[i] for i in g["adj"]), default=INF) <= FC_NEAR for g in farm
                      if g["b"] < INF and not all(i in disc for i in g["adj"]))
        if not ok_near:
            continue
        value = inc - tot / team
        key = (value, det)
        if best is None or key > best[0]:
            best = (key, c, inc, det)
    if best:
        (value, det), c, inc, _ = best
        res = (1 if value > 0 else 0, value, inc, det, inc / tot, (c % W) * 1000 + c // W)
    _h[path] = res
    return res


def _g(i):
    return lambda p, _m=None: _hold_farm(p)[i]


CLASSES.update({"hf_plan8": _g(0), "hf_value": _g(1), "hf_income": _g(2), "hf_detour": _g(3), "hf_share": _g(4), "hf_hold": _g(5)})
