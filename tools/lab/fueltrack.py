#!/usr/bin/env python3
"""fueltrack: our fuel cut-offs on the platform, per live version, kept as a ledger (owner 8 Nov: "analyse our fuel outs and keep track of it").
Reads the game bundles livepipe and the climbs fetch (/data/zw4424/plat/*/x_ID with team-X.fuel; matches.txt gives the version's set, map
and our side). A turn of exactly 100,000 fuel after the first turns is a cut (the platform logs a cut turn at its budget); 90k+ is near.
For each cut game it decodes the replay once (cached) for the round and the champion. No games are played.
usage: python3 -I tools/lab/fueltrack.py [--quiet]     rebuild the ledger and the report
       python3 -I tools/lab/fueltrack.py show [N]      the report (latest N versions, default 12)
Out: /data/zw4424/st/fueltrack/{ledger.tsv (one row per version), cuts.tsv (one row per cut), report.txt}. healthwatch runs it hourly."""
import collections
import glob
import json
import os
import re
import struct
import sys
import time

PLAT = "/data/zw4424/plat"
OUT = "/data/zw4424/st/fueltrack"
REPO = "/homes/zw4424/cambc"
CUT, NEAR, BUDGET = 100000, 90000, 100000
sys.path.insert(0, os.path.join(REPO, "tools/lab"))


def turns(xdir, side):
    """our per-turn fuel (draft turns first, as vercheck reads it), or None"""
    try:
        d = open(os.path.join(xdir, f"team-{side.lower()}.fuel"), "rb").read()
        v = struct.unpack_from("<%dQ" % ((len(d) - 13) // 8), d, 13)
        return list(v[8:]) if len(v) > 8 else None
    except (OSError, struct.error):
        return None


def where(xdir, side, cache):
    """[(round, champion)] of our turns the replay itself marks fuel-exhausted (turn end flag 1), past round 2; cached per game.
    9 Nov (restart probe): the old mapping from the fuel file's turn index put cuts ~2 rounds late and on the wrong body."""
    key = os.path.basename(xdir)
    if key in cache and isinstance(cache[key], list):
        return cache[key]
    try:
        import replay as R
        g = R.load(os.path.join(xdir, "replay.repl26a"), us=side.upper())
        out = sorted((tt[0], g.who(ch)) for ch, ts in g.by_champ.items() if g.team_of.get(ch) == g.us
                     for tt in ts if tt[g.ci["end"]] == 1 and tt[0] > 2)
    except BaseException:  # noqa: BLE001  a replay that can't be read leaves the place unknown
        out = None
    cache[key] = out
    return out


def scan():
    os.makedirs(OUT, exist_ok=True)
    cp = os.path.join(OUT, "where_cache.json")
    cache = json.load(open(cp)) if os.path.exists(cp) else {}
    per = collections.defaultdict(lambda: dict(games=0, cut_games=0, cuts=0, near=0, turns=0, maps=collections.Counter(), first=None, last=None))
    rows, seen = [], set()
    for sd in sorted(glob.glob(f"{PLAT}/*")):
        mt = os.path.join(sd, "matches.txt")
        if not os.path.isfile(mt):
            continue
        m = re.search(r"_(v\d+)", os.path.basename(sd))
        for ln in open(mt):
            p = ln.split()
            if len(p) < 3 or p[0] in seen:
                continue
            x = os.path.join(sd, "x_" + p[0])
            v = (m.group(1) if m else None)
            if not v or not os.path.isdir(x):
                continue
            t = turns(x, p[2])
            if not t:
                continue
            seen.add(p[0])
            # the first turns (draft 100x, each champion's first play turn 2x) are skipped: at most the first 20 of ours
            body = t[20:]
            cuts = [i + 20 for i, f in enumerate(body) if f == CUT]
            e = per[v]
            e["games"] += 1
            e["turns"] += len(body)
            e["near"] += sum(1 for f in body if NEAR <= f < CUT)
            if cuts:
                e["cut_games"] += 1
                e["cuts"] += len(cuts)
                e["maps"][p[1]] += len(cuts)
                w = where(x, p[2], cache)
                for k, i in enumerate(cuts[:20]):  # the replay's own exhausted turns give round and body; the fuel file only the count
                    rd, ch = w[k] if w and k < len(w) else (None, None)
                    rows.append((v, p[0], p[1], p[2], i, rd, ch, os.path.basename(sd)))
            ts = p[0][:13]
            e["first"] = min(e["first"] or ts, ts)
            e["last"] = max(e["last"] or ts, ts)
    json.dump(cache, open(cp + ".new", "w"))
    os.replace(cp + ".new", cp)
    return per, rows


def vkey(v):
    return int(v[1:])


def write(per, rows):
    with open(os.path.join(OUT, "ledger.tsv.new"), "w") as f:
        f.write("version\tgames\tcut_games\tcuts\tcuts_per_game\tshare_games_cut\tnear90k_per_game\ttop_maps\n")
        for v in sorted(per, key=vkey):
            e = per[v]
            g = max(e["games"], 1)
            f.write(f"{v}\t{e['games']}\t{e['cut_games']}\t{e['cuts']}\t{e['cuts'] / g:.3f}\t{e['cut_games'] / g:.3f}\t{e['near'] / g:.2f}\t"
                    + ",".join(f"{k}:{n}" for k, n in e["maps"].most_common(3)) + "\n")
    os.replace(os.path.join(OUT, "ledger.tsv.new"), os.path.join(OUT, "ledger.tsv"))
    with open(os.path.join(OUT, "cuts.tsv.new"), "w") as f:
        f.write("version\tmatch\tmap\tside\tturn_index\tround\tchampion\tset\n")
        for r in sorted(rows, key=lambda r: (vkey(r[0]), r[1], r[4])):
            f.write("\t".join("" if x is None else str(x) for x in r) + "\n")
    os.replace(os.path.join(OUT, "cuts.tsv.new"), os.path.join(OUT, "cuts.tsv"))


def report(n=12):
    L = [f"# fueltrack {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: our platform fuel cut-offs per live version (first 20 turns skipped)",
         f"{'ver':>5} {'games':>6} {'cut games':>9} {'cuts':>5} {'cuts/g':>7} {'near90k/g':>9}  top maps"]
    lines = open(os.path.join(OUT, "ledger.tsv")).read().splitlines()[1:]
    for ln in lines[-n:]:
        v, g, cg, c, cpg, sh, near, tm = (ln.split("\t") + [""])[:8]
        L.append(f"{v:>5} {g:>6} {cg:>9} {c:>5} {float(cpg):>7.3f} {float(near):>9.2f}  {tm}")
    cuts = [r.split("\t") for r in open(os.path.join(OUT, "cuts.tsv")).read().splitlines()[1:]]
    recent = cuts[-12:]
    if recent:
        L += ["", "latest cuts (version match map side round champion):"]
        L += [f"  {r[0]} {r[1][:13]} {r[2]} {r[3]} r{r[5] or '?'} {r[6] or '?'}" for r in recent]
    by = collections.Counter(r[6] for r in cuts if r[6])
    if by:
        L.append("cuts by champion, all versions: " + ", ".join(f"{k} {n}" for k, n in by.most_common(8)))
    txt = "\n".join(L) + "\n"
    open(os.path.join(OUT, "report.txt"), "w").write(txt)
    return txt


def main():
    a = sys.argv[1:]
    if a[:1] == ["show"]:
        print(report(int(a[1]) if len(a) > 1 else 12), end="")
        return 0
    per, rows = scan()
    write(per, rows)
    txt = report()
    if "--quiet" not in a:
        print(txt, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
