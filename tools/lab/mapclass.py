#!/usr/bin/env python3
# READ-ONLY (11 Nov, Builder: mid-edits broke reads). New classes: tools/lab/mapclass.d/NAME.py. Tool Builder edits this via FILE.new + mv.
"""mapclass: per-map class values from a .map26a file, for stratmaps --class / --class-tag (Tool Builder, 10 Nov; Planner: a class
filter for heavy-class reads). Pure read of the map file: no caches, no writes (safe on Condor nodes).

usage: python3 -I tools/lab/mapclass.py NAME FILE_OR_GLOB...   -> one line per map: value and file; then the heavyscan-style bins
Classes (definitions: /data/USER/st/deepan/wgolem/heavy_def.txt; port of /data/USER/st/econ_readers_1109/heavyscan.py):
  heavy_ge    gems of groups with a golem or any elk camp and no monolith / gems of all groups (whole groups, no reachability)
  mono_share  the same with monolith groups
  heavy_all   golem, elk or monolith groups
A group is a 4-connected component of camp tiles; gems per camp tile: wolf 4, elk 15, gem 7, gold 0, monolith 200, golem 36.
A map with no group gems has value None and passes no condition.
New classes: add a function FILE -> float|None to CLASSES."""
import glob
import operator
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GEM = {0: 4, 1: 15, 2: 7, 3: 0, 4: 200, 5: 36}  # camp types 0 wolf, 1 elk, 2 gem, 3 gold, 4 mono, 5 golem
OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


def groups(path):
    """-> [(gems, set of camp types)] for each 4-connected camp group."""
    import genmaps as G
    camps = G.map26a.load(path)["camps"]
    seen, out = set(), []
    for c in camps:
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        types = [camps[p] for p in comp]
        out.append((sum(GEM[t] for t in types), set(types)))
    return out


def _share(pred):
    def f(path, _g=None):
        g = _g if _g is not None else groups(path)
        tot = sum(x for x, _ in g)
        return round(sum(x for x, t in g if pred(t)) / tot, 4) if tot else None
    return f


def _d50(path, _g=None):
    """b1802 (TCM amendment, Tavi tempo class): median over 4-connected camp groups of the 8-way walk from spawn A to the nearest
    land tile next to the group (walls, holes, altars and camp tiles blocked)."""
    import genmaps as G
    from collections import deque
    d = G.map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    dist = {s: 0 for s in d["spawnA"]}
    q = deque(dist)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and 0 <= n[0] < W and 0 <= n[1] < H and n not in block and n not in dist:
                    dist[n] = dist[(x, y)] + 1
                    q.append(n)
    seen, ds = set(), []
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
        best = min((dist[(x + dx, y + dy)] for x, y in comp for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (x + dx, y + dy) in dist), default=None)
        if best is not None:
            ds.append(best)
    ds.sort()
    return ds[len(ds) // 2] if ds else None


def _area(path, _g=None):
    import genmaps as G
    d = G.map26a.load(path)
    return d["W"] * d["H"]


def _tavi_tempo(path, _g=None):
    """1 when d50 >= 26 or area >= 3040 (spec_mod_1110 amendment 1, the top thirds of b1832's pool), else 0 (b1802)."""
    v, a = _d50(path), _area(path)
    return 1 if (v is not None and v >= 26) or a >= 3040 else 0


def _s2s(path, _g=None):
    """Chebyshev distance between the two spawn-rect centres (topdraft.py's s2s; b1830)."""
    import genmaps as G
    d = G.map26a.load(path)
    x0, y0, x1, y1 = d["spawnA_rect"]
    ax, ay = (x0 + x1 - 1) / 2.0, (y0 + y1 - 1) / 2.0
    bx, by = G.map26a.mirror(d["symmetry"], d["W"], d["H"], round(ax), round(ay))
    return max(abs(ax - bx), abs(ay - by))


def _ren_big(path, _g=None):
    """1 when area >= 2600 and s2s >= 42 (CI Planner topdraft_tsr_1110: SBG drafts Ren on big, far maps), else 0 (b1830)."""
    return 1 if _area(path) >= 2600 and _s2s(path) >= 42 else 0


def _tavi_a(path, _g=None):
    """1 when area >= 2400, s2s >= 38 and a 5-pick (6-body) team (CI Planner topdraft_tsr_1110: Mite's Tavi maps, TEMPO), else 0 (b1802)."""
    import genmaps as G
    d = G.map26a.load(path)
    v = _s2s(path)
    return 1 if d["W"] * d["H"] >= 2400 and v is not None and v >= 38 and d["champs_per_team"] >= 5 else 0


def _tavi_b(path, _g=None):
    """1 when cluster camps (gem/gold cluster tiles) >= .80 of camps and no elk, golem or monolith (CI Planner: SBG's Tavi maps, PURE
    CLUSTER), else 0 (b1802)."""
    import genmaps as G
    t = list(G.map26a.load(path)["camps"].values())
    if not t:
        return 0
    return 1 if sum(1 for v in t if v in (2, 3)) / len(t) >= 0.80 and not any(v in (1, 4, 5) for v in t) else 0


def _goldrace(path, _g=None):
    """1 when area W x H < 3250 or >= 3 gem-only groups (only gem-cluster camps), else 0 (Econ spec_gpg_1110 GOLDRACE; b1830)."""
    g = _g if _g is not None else groups(path)
    return 1 if _area(path) < 3250 or sum(1 for _, t in g if t == {2}) >= 3 else 0


CLASSES = {
    "heavy_ge": _share(lambda t: (1 in t or 5 in t) and 4 not in t),
    "mono_share": _share(lambda t: 4 in t),
    "heavy_all": _share(lambda t: 1 in t or 5 in t or 4 in t),
    "d50": _d50,
    "area": _area,
    "tavi_tempo": _tavi_tempo,
    "s2s": _s2s,
    "ren_big": _ren_big,
    "tavi_a": _tavi_a,
    "tavi_b": _tavi_b,
    "goldrace": _goldrace,
}

# 11 Nov (Builder: three agents edited this file at once and lost an insert): NEW classes go in their own file,
# tools/lab/mapclass.d/NAME.py, which defines CLASSES = {"name": fn(path) -> value}. They load here, in name order; a broken file is
# skipped with a note on stderr, and a name already defined above is never overwritten. No more edits to this dict.
def _load_plugins():
    import glob as _g
    import importlib.util as _u
    for p in sorted(_g.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapclass.d", "*.py"))):
        try:
            spec = _u.spec_from_file_location("mapclass_d_" + os.path.basename(p)[:-3], p)
            mod = _u.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for k, fn in getattr(mod, "CLASSES", {}).items():
                try:  # 11 Nov: values() calls fn(path, groups); a plugin may take the path alone (gsc and heavy_ge2 read nothing before)
                    import inspect as _i
                    one = len([q for q in _i.signature(fn).parameters.values() if q.default is q.empty]) == 1 and len(_i.signature(fn).parameters) == 1
                except (TypeError, ValueError):
                    one = False
                CLASSES.setdefault(k, (lambda path, _g=None, _f=fn: _f(path)) if one else fn)
        except Exception as e:  # noqa: BLE001
            print(f"mapclass: plugin {p} skipped ({str(e)[:120]})", file=sys.stderr)


_load_plugins()


def parse(spec):
    """'heavy_ge:>=0.5[,name:<0.2...]' -> [(name, op, value)] (all must hold)."""
    out = []
    for part in spec.split(","):
        name, _, cond = part.strip().partition(":")
        if name not in CLASSES:  # 11 Nov (hxb1: shipwatch, a daemon, loaded the plugins before holexb existed): reload them once
            _load_plugins()
        if name not in CLASSES:
            raise SystemExit(f"mapclass: unknown class {name!r} (have {', '.join(CLASSES)})")
        op = next((o for o in (">=", "<=", ">", "<") if cond.startswith(o)), None)
        if op is None:
            raise SystemExit(f"mapclass: bad condition {part!r}: use NAME:OPvalue with OP one of >= > <= <")
        out.append((name, op, float(cond[len(op):])))
    return out


import threading as _th
_VLOCK = _th.Lock()
_ORIG = {}


def values(path, names):
    """-> {name: value} (one map read for all share classes). 11 Nov: map26a.load is memoised for this call, so the plugins (each loads
    the map itself) read the file once: ~350 -> ~60 ms a map for 12 classes (stylepanel's per-class tags)."""
    import map26a as _m
    with _VLOCK:  # 11 Nov: two threads (draw-time tags + the background tag thread) nested the patch, and the leftover memoising loader
        # kept every map loaded afterwards (5 GB stylepanels, OOM-killed checks). One caller at a time; always restore the TRUE original.
        orig = _ORIG.setdefault("load", _m.load)
        memo = {}

        def load(p, *a, **k):
            key = (p, a, tuple(sorted(k.items())))
            if key not in memo:
                memo[key] = orig(p, *a, **k)
            return memo[key]
        _m.load = load
        try:
            g = groups(path)
            return {n: CLASSES[n](path, g) for n in names}
        finally:
            _m.load = orig


def passes(vals, conds):
    return all(vals.get(n) is not None and OPS[op](vals[n], v) for n, op, v in conds)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in CLASSES:
        print(__doc__)
        return 2
    name = sys.argv[1]
    bins, n = {">=.5": 0, ".2-.5": 0, "<.2": 0}, 0
    for f in (f for g in sys.argv[2:] for f in sorted(glob.glob(g))):
        try:
            s = values(f, [name])[name]
        except Exception:  # noqa: BLE001  (unreadable map: skipped, as heavyscan)
            continue
        print(f"{s}\t{f}")
        if s is None:
            continue
        n += 1
        bins[">=.5" if s >= .5 else ".2-.5" if s >= .2 else "<.2"] += 1
    print("maps %d | %s >= .5: %d (%.3f) | .2-.5: %d | < .2: %d" % (n, name, bins[">=.5"], bins[">=.5"] / max(1, n), bins[".2-.5"], bins["<.2"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
