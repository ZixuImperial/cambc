#!/usr/bin/env python3
"""hetfeat: per-map features for hetero.py, and its Condor node reader. Tool builder, 4 Nov.
extra() and one() are Deep research's dr56/feats.py (mapfeat + mid share / top group / gem half-distance), copied here unchanged in
substance so Condor nodes (which can't read /data) run the same extractor, and dr56's feats.jsonl stays a valid cache.
build(m, work): rebuild one map from an otf.json entry (seed + recipe) without the checks it already passed when the read was made.
read(path, meta): readmany's node entry: path is a JSON list of otf.json map entries -> {name: features or None}."""
import json
import os
import shutil
import sys
import tempfile
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402
import mapfeat  # noqa: E402

N8 = [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
GEMS = mapfeat.GEMS
GOLD = mapfeat.GOLD


def extra(d):
    W, H = d['W'], d['H']; wall, hole, alt, camps = d['wall'], d['hole'], d['altar'], d['camps']
    spA, spB = d['spawnA'], d['spawnB']
    def land(p, esp): return 0 <= p[0] < W and 0 <= p[1] < H and p not in wall and p not in hole and p not in alt and p not in esp
    def bfs(st, esp):
        dist = {s: 0 for s in st}; q = deque(st)
        while q:
            c = q.popleft()
            for dx, dy in N8:
                n = (c[0]+dx, c[1]+dy)
                if n not in dist and land(n, esp): dist[n] = dist[c]+1; q.append(n)
        return dist
    wA, wB = bfs(list(spA), spB), bfs(list(spB), spA)
    gid, groups = {}, []
    for p in sorted(camps):
        if p in gid: continue
        g, st = [p], [p]; gid[p] = len(groups)
        while st:
            c = st.pop()
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                n = (c[0]+dx, c[1]+dy)
                if n in camps and n not in gid: gid[n] = len(groups); g.append(n); st.append(n)
        groups.append(g)
    tot = 0; mid = 0; near = []; big = 0; vals = []
    for g in groups:
        gem = sum(GEMS[camps[p]] for p in g); tot += gem; vals.append(gem)
        nb = [(p[0]+dx, p[1]+dy) for p in g for dx, dy in N8]
        da = min([wA[q] for q in nb if q in wA], default=None); db = min([wB[q] for q in nb if q in wB], default=None)
        if da is None or db is None: continue
        if abs(da - db) <= 0.2 * max(da, db, 1): mid += gem
        near.append((min(da, db), gem))
    Tt = max(1, tot)
    near.sort(); acc = 0; d50 = None
    for dd, gem in near:
        acc += gem
        if acc >= 0.5 * sum(x[1] for x in near) and d50 is None: d50 = dd
    return dict(mid=round(mid / Tt, 3), top1=round(max(vals, default=0) / Tt, 3), d50=d50,
                area=W * H, aspect=round(max(W, H) / max(1, min(W, H)), 2))


def one(p):
    try:
        d = map26a.load(p)
        f = mapfeat.analyse(d, os.path.basename(p)[:-7])
        f.update(extra(d))
        T = f['T']
        f['gpb'] = round(f['gems'] / (2 * T), 1)
        f['apb'] = round(f['area'] / (2 * T))
        f['ggr'] = round(f['gold'] / max(1, f['gems']), 2)
        if not isinstance(f.get('alt_d'), int):
            f['alt_d'] = None
        return p, f
    except Exception:  # noqa: BLE001
        return p, None


def build(m, work):
    """otf.json map entry -> map path in work (its own dir per map: builders write scratch files next to the map)."""
    rec, seed, name = dict(m["recipe"]), m["seed"], m["name"]
    gen = {k: v for k, v in rec.items() if k not in ("fam", "nf", "weird")}
    os.makedirs(work, exist_ok=True)
    if rec.get("nf"):
        import genfam
        _, p, _ = genfam.build_one(rec["nf"], name, seed, dict(gen), work)
        return p
    if rec.get("weird"):
        import genweird
        p, _ = genweird.build_one(rec["weird"], name, seed, dict(gen), work)
        return p
    import genmaps as G
    mm = G.generate(gen, seed)
    sp, mp = os.path.join(work, name + ".json"), os.path.join(work, name + ".map26a")
    json.dump(G.spec_of(mm), open(sp, "w"))
    G.build_and_check(mm, sp, mp)
    return mp


def feats_of(m, kept=None):
    """otf.json map entry -> features or None (kept: a map file the read kept, used as it is)."""
    if kept:
        return one(kept)[1]
    work = tempfile.mkdtemp(prefix="hf_")
    try:
        return one(build(m, work))[1]
    except Exception:  # noqa: BLE001  (a map that won't rebuild is reported missing, never fatal)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def read(path, meta):
    """readmany node entry."""
    out = {}
    for m in json.load(open(path)):
        f = feats_of(m)
        if f:
            f.pop("p", None)
        out[m["name"]] = f
    return out
