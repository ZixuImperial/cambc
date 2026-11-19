#!/usr/bin/env python3
"""hgate: the chokepoint tiles H_GATE(side, altar) of a map (Aggression subagent for Deep Analyser, 11 Nov; definition from
condor-work/reports/analysts/spec_alk_1111.md, "Hot-spot definition"). Map features only; read-only; no other tool is touched.

  H_GATE(side, a) = tiles t that lie on a shortest walk path from that side's spawn to a tribute tile of altar a
                    (dist(spawn, t) + dist(t, ring) == dist(spawn, ring)), within REACH (12, Chebyshev to the nearest tile of a)
                    of the altar, where removing t raises dist(spawn, ring) by >= RAISE (4) or disconnects it.
  Walk = 8-way steps; walls, holes and altar tiles block (the same field as replay.Game.walk_fields). ring = walkable tiles within
  Chebyshev 1 of a tile of the altar. An altar = one 8-connected cluster of altar tiles. Spawn tiles are never gates.

usage: python3 -I tools/lab/hgate.py MAP.map26a [MAP...]     one JSON line per map:
         {"map", "altars": [[tiles]], "A": [{"altar": i, "dist": d, "nearest": 0/1, "gates": [[x, y], ...]}], "B": [...]}
API:   clusters(altar_tiles) -> [sorted tile list]
       gates(W, H, blocked, spawn_tiles, altar_cluster, reach=12, raise_by=4) -> (set of gate tiles, dist spawn->ring or None)
       map_gates(W, H, blocked, spawnA_tiles, spawnB_tiles, altar_tiles) -> {"altars": [...], 0: [per altar dict], 1: [...]}
       (blocked must contain the altar tiles; from a replay: {'#', 'o' tiles of g.rows} | set(g.altars); spawn rect -> its tiles.)
"""
import json
import os
import sys
from collections import deque

N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
INF = 10 ** 9


def clusters(altar_tiles):
    alt, seen, out = set(map(tuple, altar_tiles)), set(), []
    for a in sorted(alt):
        if a in seen:
            continue
        st, cl = [a], []
        seen.add(a)
        while st:
            x, y = st.pop()
            cl.append((x, y))
            for dx, dy in N8:
                q = (x + dx, y + dy)
                if q in alt and q not in seen:
                    seen.add(q)
                    st.append(q)
        out.append(sorted(cl))
    return out


def _bfs(W, H, blocked, src, skip=None, stop=None):
    d = {p: 0 for p in src if p != skip}
    q = deque(d)
    while q:
        x, y = q.popleft()
        if stop is not None and (x, y) in stop:
            return d
        for dx, dy in N8:
            p = (x + dx, y + dy)
            if 0 <= p[0] < W and 0 <= p[1] < H and p not in blocked and p != skip and p not in d:
                d[p] = d[(x, y)] + 1
                q.append(p)
    return d


def ring_of(W, H, blocked, cluster):
    return sorted({(x + dx, y + dy) for x, y in cluster for dx, dy in N8
                   if 0 <= x + dx < W and 0 <= y + dy < H and (x + dx, y + dy) not in blocked})


def gates(W, H, blocked, spawn_tiles, altar_cluster, reach=12, raise_by=4):
    spawn = [tuple(p) for p in spawn_tiles if tuple(p) not in blocked]
    ring = ring_of(W, H, blocked, altar_cluster)
    if not spawn or not ring:
        return set(), None
    ds = _bfs(W, H, blocked, spawn)
    D = min((ds.get(p, INF) for p in ring), default=INF)
    if D >= INF:
        return set(), None
    dr = _bfs(W, H, blocked, ring)
    sp, rs = set(spawn), set(ring)
    out = set()
    for t, a in ds.items():
        if t in sp or a + dr.get(t, INF) != D:
            continue
        if min(max(abs(t[0] - x), abs(t[1] - y)) for x, y in altar_cluster) > reach:
            continue
        d2 = _bfs(W, H, blocked, spawn, skip=t, stop=rs - {t})  # BFS order: the first ring tile reached is the nearest
        nd = min((d2.get(p, INF) for p in ring if p != t), default=INF)
        if nd >= INF or nd - D >= raise_by:
            out.add(t)
    return out, D


def map_gates(W, H, blocked, spawnA, spawnB, altar_tiles, reach=12, raise_by=4):
    cls = clusters(altar_tiles)
    res = {"altars": cls}
    for side, sp in ((0, spawnA), (1, spawnB)):
        rows = []
        for i, cl in enumerate(cls):
            g, D = gates(W, H, blocked, sp, cl, reach, raise_by)
            rows.append({"altar": i, "dist": D, "gates": sorted(g)})
        m = min((r["dist"] for r in rows if r["dist"] is not None), default=None)
        for r in rows:
            r["nearest"] = int(r["dist"] is not None and r["dist"] == m)
        res[side] = rows
    return res


def from_map_file(path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import map26a
    d = map26a.load(path)
    blocked = set(d["wall"]) | set(d["hole"]) | set(d["altar"])
    return map_gates(d["W"], d["H"], blocked, sorted(d["spawnA"]), sorted(d["spawnB"]), d["altar"])


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        r = from_map_file(p)
        print(json.dumps({"map": os.path.basename(p), "altars": r["altars"], "A": r[0], "B": r[1]}))


if __name__ == "__main__":
    main()
