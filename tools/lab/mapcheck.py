#!/usr/bin/env python3
"""Self-checks of the map tooling (toolrev 25 Oct): run after any change to map26a.py, mapfeat.py or a generator.

usage: python3 -I tools/lab/mapcheck.py audit [DIR ...]
         every .map26a in the dirs (default /data/zw4424/work301/maps):
         decode + encode byte for byte, mirror symmetry of terrain and camps, spawns on free tiles with 9..16 tiles
         (else the game fails to load: engine error 7), and for maps with a generator meta.json (recipe + seed) the
         25 Oct checks (genmaps.strict_checks: split halves never meet, no camp-gated altar on normal/long maps)
       python3 -I tools/lab/mapcheck.py rebuild [--k 3] [--tmp DIR] FAMILYDIR ...   rebuild k maps of each family dir
         (first, last and middle by name; --k 0 = all) from their meta.json recipe and seed into DIR (default
         /data/zw4424/tmp_mapcheck) and compare the bytes with the family's map: the same seed must give the same map.
         Pure Python + node MapBuilder, about 1-4 s per map; no game is played and nothing is installed.
Prints one line per problem and a summary; exit status 1 when any check fails.
"""
import glob
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genmaps as G  # noqa: E402
import map26a  # noqa: E402

FAMILY_DIRS = sorted(glob.glob("/data/zw4424/genmaps*"))


class _Mirror:
    def __init__(self, d):
        self.d = d

    def mir(self, x, y):
        return map26a.mirror(self.d["symmetry"], self.d["W"], self.d["H"], x, y)


def _meta(name):
    for d in FAMILY_DIRS:
        p = os.path.join(d, name + ".meta.json")
        if os.path.exists(p):
            return p
    return None


def audit(dirs):
    bad = n = 0
    for f in sorted(p for d in dirs for p in glob.glob(os.path.join(d, "*.map26a"))):
        n += 1
        name, why = os.path.basename(f)[:-7], []
        try:
            d = map26a.load(f)
        except (ValueError, IndexError) as e:
            print(f"{name}: does not decode ({e})")
            bad += 1
            continue
        if not map26a.roundtrip(f):
            why.append("decode + encode differs")
        mir = _Mirror(d).mir
        why += [f"{k} not mirror-symmetric" for k in ("wall", "hole", "bush", "altar")
                if {mir(*p) for p in d[k]} != d[k]]
        if any(d["camps"].get(mir(*p)) != t for p, t in d["camps"].items()):
            why.append("camps not mirror-symmetric")
        x0, y0, x1, y1 = d["spawnA_rect"]
        if not 9 <= (x1 - x0) * (y1 - y0) <= 16:
            why.append(f"spawn area {x1 - x0}x{y1 - y0} outside 9..16 tiles (engine error 7)")
        blocked = d["wall"] | d["hole"] | d["altar"] | set(d["camps"])
        if (d["spawnA"] | d["spawnB"]) & blocked or d["spawnA"] & d["spawnB"]:
            why.append("spawn on an obstacle, a camp or the other spawn")
        mp = _meta(name)
        rec = json.load(open(mp)).get("recipe") if mp else None
        if rec and rec.get("kind") in ("normal", "long", "split") and hasattr(G, "strict_checks"):  # fix.patch
            w = G.strict_checks(_Mirror(d), rec, d)
            if w:
                why.append(w)
        if why:
            bad += 1
            print(f"{name}: {'; '.join(why)}")
    print(f"audit: {n - bad} of {n} maps pass")
    return bad == 0


def rebuild(fdirs, k, tmp):
    os.makedirs(tmp, exist_ok=True)
    bad = n = 0
    for fd in fdirs:
        metas = sorted(glob.glob(os.path.join(fd, "*.meta.json")))
        if k and len(metas) > k:
            metas = [metas[0], metas[-1]] + metas[len(metas) // 2:len(metas) // 2 + max(0, k - 2)]
        for mp in metas:
            j = json.load(open(mp))
            rec, seed, name = j.get("recipe"), j["seed"], j["name"]
            try:
                if rec and rec.get("kind") in G.GATE_KINDS:
                    m = G.generate_gate(rec, seed)
                elif rec and rec.get("kind") in ("normal", "long") + tuple(G.PATHO):
                    m = G.generate(rec, seed)
                elif "kind" in j and name.startswith("gen_i_"):
                    import genideo
                    m = genideo.KINDS[j["kind"]](random.Random(seed))
                else:
                    print(f"{name}: no rebuild rule for this family; skipped")
                    continue
                sp, out = os.path.join(tmp, name + ".json"), os.path.join(tmp, name + ".map26a")
                json.dump(G.spec_of(m), open(sp, "w"))
                G.build_and_check(m, sp, out)
                same = open(out, "rb").read() == open(mp[:-10] + ".map26a", "rb").read()
            except (RuntimeError, AssertionError) as e:
                same = False
                print(f"{name}: rebuild failed ({e})")
            n += 1
            if not same:
                bad += 1
                print(f"{name}: seed {seed} no longer builds the same map")
    print(f"rebuild: {n - bad} of {n} maps identical")
    return bad == 0


def main():
    a = sys.argv[1:]
    if a and a[0] == "audit":
        ok = audit(a[1:] or ["/data/zw4424/work301/maps"])
    elif a and a[0] == "rebuild":
        k, tmp, rest = 3, "/data/zw4424/tmp_mapcheck", a[1:]
        while rest and rest[0].startswith("--"):
            if rest[0] == "--k":
                k, rest = int(rest[1]), rest[2:]
            elif rest[0] == "--tmp":
                tmp, rest = rest[1], rest[2:]
            else:
                sys.exit(__doc__)
        ok = rebuild(rest or FAMILY_DIRS, k, tmp)
    else:
        sys.exit(__doc__)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
