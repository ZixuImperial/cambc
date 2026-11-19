#!/usr/bin/env python3
"""replaypath: where a live game's replay actually is (Tool Builder, 9 Nov; CI and Vendetta analyser: top-3 lane replays live either as
plat/<set>/<id>.zip or, once critgame extracted them, plat/<set>/x_<id>/replay.repl26a; a reader that opened only the zips saw every win
and about a third of the losses).

usage: python3 -I tools/lab/replaypath.py MATCH_ID [MATCH_ID ...]       one line per id: id <TAB> path (or MISSING)
       python3 -I tools/lab/replaypath.py --tsv GAMES.tsv               a climb lane's games.tsv: every row with its replay path appended
       python3 -I tools/lab/replaypath.py --set DIR                      every game in a set dir (matches.txt), extracted or zipped
Lookup order: an extracted replay (any plat/*/x_<id>/replay.repl26a, the set's own first), then a zip (plat/*/<id>.zip). As a module:
replaypath.find(match_id, prefer_dir=None) -> path or None."""
import glob
import os
import sys

PLAT = "/data/zw4424/plat"


def find(mid, prefer_dir=None):
    for d in ([prefer_dir] if prefer_dir else []) + [None]:
        pat = os.path.join(d, f"x_{mid}", "replay.repl26a") if d else os.path.join(PLAT, "*", f"x_{mid}", "replay.repl26a")
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    for d in ([prefer_dir] if prefer_dir else []) + [None]:
        pat = os.path.join(d, f"{mid}.zip") if d else os.path.join(PLAT, "*", f"{mid}.zip")
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "--tsv":
        for ln in open(a[1], errors="replace"):
            p = ln.rstrip("\n").split("\t")
            mid = p[3] if len(p) > 3 else ""
            print(ln.rstrip("\n") + "\t" + ((find(mid) or "MISSING") if mid else ""))
        return 0
    if a[0] == "--set":
        d = a[1]
        for ln in open(os.path.join(d, "matches.txt"), errors="replace"):
            mid = ln.split()[0] if ln.strip() else ""
            if mid:
                print(f"{mid}\t{find(mid, d) or 'MISSING'}")
        return 0
    for mid in a:
        print(f"{mid}\t{find(mid) or 'MISSING'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
