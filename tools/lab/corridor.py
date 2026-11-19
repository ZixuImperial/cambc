#!/usr/bin/env python3
"""corridor: choke / corridor features of a map from the map file alone (Tool Builder, 12 Nov; Coordinator/Deep cellclass search: half the
repeat-loss variance is a MAP effect none of the 39 draft-time features captures). Draft-time map features only; no names or ids in outputs.

usage: python3 -I tools/lab/corridor.py OUT.tsv MAP.map26a|DIR ...     one row per map, keyed by the map file's sha1 (first 16 hex)
Walk model: 8-way moves; walls, holes and camp tiles block (camps are alive at the draft); targets = the walkable tiles next to an altar.
From spawn A (the maps are mirrored, so B is the same up to symmetry). Columns:
  alt_n           altars
  path_min/mean   exact BFS steps spawn -> nearest tile beside each altar (min, mean over altars; -1 unreachable)
  cut_min/mean    min vertex cut between spawn and each altar = number of vertex-disjoint routes (Menger), capped at CAP (12)
  corr_share      share of the shortest spawn -> nearest-altar path on corridor tiles (blocked on both sides, horizontally or vertically)
  bush_alt        1 when the last 10 tiles of a shortest path to some altar are >= half bush
  open_alt        mean share of walkable tiles within Chebyshev 5 of each altar
  open_mono       mean share of walkable tiles within Chebyshev 5 of each monolith group (-1 when none)
  walk_share      walkable share of the board"""
import hashlib
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402

CAP = 12
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def feats(path):
    m = map26a.load(path)
    W, H = m["W"], m["H"]
    blocked = set(m["wall"]) | set(m["hole"]) | set(m["camps"])
    alt = sorted(m["altar"])
    walk = lambda p: 0 <= p[0] < W and 0 <= p[1] < H and p not in blocked and p not in m["altar"]  # noqa: E731
    src = [p for p in m["spawnA"] if walk(p)]

    def bfs(starts):
        dist, par = {p: 0 for p in starts}, {p: None for p in starts}
        q = deque(starts)
        while q:
            c = q.popleft()
            for dx, dy in N8:
                n = (c[0] + dx, c[1] + dy)
                if n not in dist and walk(n):
                    dist[n], par[n] = dist[c] + 1, c
                    q.append(n)
        return dist, par

    dist, par = bfs(src)
    ring = {a: [(a[0] + dx, a[1] + dy) for dx, dy in N8 if walk((a[0] + dx, a[1] + dy))] for a in alt}
    plen, paths = [], []
    for a in alt:
        r = [p for p in ring[a] if p in dist]
        if not r:
            plen.append(-1)
            paths.append([])
            continue
        e = min(r, key=lambda p: dist[p])
        plen.append(dist[e])
        pt, c = [], e
        while c is not None:
            pt.append(c)
            c = par[c]
        paths.append(pt[::-1])

    def corridor(p):
        h = not walk((p[0] - 1, p[1])) and not walk((p[0] + 1, p[1]))
        v = not walk((p[0], p[1] - 1)) and not walk((p[0], p[1] + 1))
        return h or v

    def mincut(targets):
        """vertex-disjoint routes spawn -> targets: Edmonds-Karp on the node-split graph (tile in -> out cap 1; spawn and target tiles
        uncapped; tile out -> neighbour in uncapped; S -> spawn in, target out -> T), capped at CAP"""
        tgt, srcs = set(targets), set(src)
        if not tgt or not srcs:
            return 0
        INF = 10 ** 6
        res = {}  # residual capacity per (u, v)

        def cap(u, v):
            if (u, v) in res:
                return res[(u, v)]
            if u == "S":
                c = INF if v[1] == 0 and v[0] in srcs else 0
            elif v == "T":
                c = INF if u[1] == 1 and u[0] in tgt else 0
            elif u in ("S", "T") or v in ("S", "T"):
                c = 0  # reverse edges into S / out of T start empty
            elif u[0] == v[0] and u[1] == 0 and v[1] == 1:
                c = INF if (u[0] in srcs or u[0] in tgt) else 1
            elif u[1] == 1 and v[1] == 0 and max(abs(u[0][0] - v[0][0]), abs(u[0][1] - v[0][1])) == 1:
                c = INF
            else:
                c = 0
            return c

        def nbrs(u):
            if u == "S":
                return [(p, 0) for p in srcs]
            if u == "T":
                return [(p, 1) for p in tgt]
            p, side = u
            out = [(p, 1 - side)]
            for dx, dy in N8:
                q2 = (p[0] + dx, p[1] + dy)
                if walk(q2):
                    out.append((q2, 0 if side == 1 else 1))
            if side == 1 and p in tgt:
                out.append("T")
            if side == 0 and p in srcs:
                out.append("S")
            return out

        flow = 0
        while flow < CAP:
            prev = {"S": None}
            q = deque(["S"])
            while q and "T" not in prev:
                u = q.popleft()
                for v in nbrs(u):
                    if v not in prev and cap(u, v) > 0:
                        prev[v] = u
                        q.append(v)
            if "T" not in prev:
                break
            v = "T"
            while prev[v] is not None:
                u = prev[v]
                res[(u, v)] = cap(u, v) - 1
                res[(v, u)] = cap(v, u) + 1
                v = u
            flow += 1
        return flow

    cuts = [mincut(ring[a]) for a in alt]
    near = min((i for i in range(len(alt)) if plen[i] >= 0), key=lambda i: plen[i], default=None)
    corr = round(sum(corridor(p) for p in paths[near]) / max(1, len(paths[near])), 3) if near is not None else -1
    bush = set(m["bush"])
    bush_alt = int(any(pt and sum(p in bush for p in pt[-10:]) >= 5 for pt in paths))

    def openness(c):
        cells = [(c[0] + dx, c[1] + dy) for dx in range(-5, 6) for dy in range(-5, 6)]
        cells = [p for p in cells if 0 <= p[0] < W and 0 <= p[1] < H]
        return sum(walk(p) for p in cells) / max(1, len(cells))

    monos = [p for p, k in m["camps"].items() if k == 4]
    reach = [x for x in plen if x >= 0]
    return dict(alt_n=len(alt), path_min=min(reach) if reach else -1, path_mean=round(sum(reach) / len(reach), 1) if reach else -1,
                cut_min=min(cuts) if cuts else 0, cut_mean=round(sum(cuts) / len(cuts), 2) if cuts else 0, corr_share=corr,
                bush_alt=bush_alt, open_alt=round(sum(openness(a) for a in alt) / max(1, len(alt)), 3),
                open_mono=round(sum(openness(p) for p in monos) / len(monos), 3) if monos else -1,
                walk_share=round(sum(walk((x, y)) for x in range(W) for y in range(H)) / (W * H), 3))


COLS = ["alt_n", "path_min", "path_mean", "cut_min", "cut_mean", "corr_share", "bush_alt", "open_alt", "open_mono", "walk_share"]


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    out, srcs = a[0], a[1:]
    files = []
    for s in srcs:
        files += sorted(os.path.join(s, f) for f in os.listdir(s) if f.endswith(".map26a")) if os.path.isdir(s) else [s]
    with open(out + ".tmp", "w") as f:
        f.write("maphash\t" + "\t".join(COLS) + "\n")
        for p in files:
            try:
                r = feats(p)
            except Exception as e:  # noqa: BLE001  one bad map must not stop the table
                print(f"corridor: skipped a map ({e!r})", file=sys.stderr)
                continue
            h = hashlib.sha1(open(p, "rb").read()).hexdigest()[:16]
            f.write(h + "\t" + "\t".join(str(r[c]) for c in COLS) + "\n")
    os.replace(out + ".tmp", out)
    print(f"corridor: {len(files)} maps -> {out}")


if __name__ == "__main__":
    main()
