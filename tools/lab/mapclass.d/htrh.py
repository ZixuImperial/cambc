"""htrh (b2199, HTR1 class gate; RC/Builder 12 Nov; installed by Tool Builder from /data/USER/st/b2199/plug/htrh.py, htrh_share added to CLASSES).
Static map fields only, no map identity. htrh_share is the bot's MCL4 bit 1 quantity (the bot sums from its OWN spawn; this from either: mirrored maps agree).
  htrh = number of camp groups (4-connected camp tiles, as the bot's M.groups) that hold a golem (5) or monolith (4) camp and that a
         walk reaches: an 8-way BFS from either team's spawn tiles (walls, holes, altars and camp tiles block) reaches a land tile
         8-adjacent to one of the group's camp tiles (the bot's ACC_WALK && d_home != UNREACH). Class: 'htrh:>=1'.
Camp kinds (map26a): 0 wolf, 1 elk, 2 gem cluster, 3 gold cluster, 4 monolith, 5 golem."""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402

_c = {}


def htrh(path):
    if path in _c:
        return _c[path]
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    reach = {p for p in (set(d["spawnA"]) | set(d.get("spawnB") or ())) if p not in block}
    q = deque(reach)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in reach:
                    reach.add(n)
                    q.append(n)
    seen, k = set(), 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        if any(camps[t] in (4, 5) for t in comp) and any((x + dx, y + dy) in reach for x, y in comp for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            k += 1
    _c[path] = k
    return k


def htrh_share(path):
    """gems of the walk-reached golem/monolith groups / gems of all walk-reached groups (None when no reached group has gems)."""
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    G = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    reach = {p for p in (set(d["spawnA"]) | set(d.get("spawnB") or ())) if p not in block}
    q = deque(reach)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in reach:
                    reach.add(n)
                    q.append(n)
    seen, num, den = set(), 0, 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        if not any((x + dx, y + dy) in reach for x, y in comp for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            continue
        gm = sum(G[camps[t]] for t in comp)
        den += gm
        if any(camps[t] in (4, 5) for t in comp):
            num += gm
    return num / den if den else None


_cs = {}


def _share_from(path, spawn_key):
    """htrh_share with the walk from ONE seat's spawn only (the bot's own classing: M.groups with ACC_WALK && d_home != UNREACH from its spawn)."""
    k = (path, spawn_key)
    if k in _cs:
        return _cs[k]
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    G = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    reach = {p for p in set(d.get(spawn_key) or ()) if p not in block}
    q = deque(reach)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in reach:
                    reach.add(n)
                    q.append(n)
    seen, num, den = set(), 0, 0
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in camps and n not in seen:
                    seen.add(n)
                    st.append(n)
        if not any((x + dx, y + dy) in reach for x, y in comp for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            continue
        gm = sum(G[camps[t]] for t in comp)
        den += gm
        if any(camps[t] in (4, 5) for t in comp):
            num += gm
    _cs[k] = num / den if den else None
    return _cs[k]


def htrh_share_a(path):
    """per seat (12 Nov, Builder / RC C652): htrh_share from seat A's spawn only"""
    return _share_from(path, "spawnA")


def htrh_share_b(path):
    """per seat: htrh_share from seat B's spawn only"""
    return _share_from(path, "spawnB")


def htrh_share_min(path):
    """the smaller seat value (None if either is None): 'htrh_share_min:>=0.75' = BOTH seats in the class, so a map-pair read (both seats
    of each map) holds only class seats"""
    a, b = htrh_share_a(path), htrh_share_b(path)
    return None if a is None or b is None else min(a, b)


CLASSES = {"htrh": htrh, "htrh_share": htrh_share, "htrh_share_a": htrh_share_a, "htrh_share_b": htrh_share_b, "htrh_share_min": htrh_share_min}
