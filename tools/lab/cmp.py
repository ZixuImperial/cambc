"""Compare platform test sets made by tools/lab/diag.sh on the same opponents and maps.
usage: python3 tools/lab/cmp.py DIR_A DIR_B [DIR_C ...]
Per game (first two dirs): result, tributed us-them, collected us-them, our deaths, rounds.
Per dir: wins, tributed us/them (the ratio is the most stable signal; W/L flips easily), gems lost on
death, gems still carried at the end, deaths."""
import json
import os
import sys


def load(D):
    # keyed (opponent, map, our side, k): k numbers repeats of the same opponent, map and side (ranked and watched
    # unranked sets have them); keyed by (opponent, map) alone, repeats overwrote each other and the per-dir totals
    # dropped games (unr_v201a: 93 of 100)
    out, seen = {}, {}
    for line in open(os.path.join(D, "matches.txt")):
        f = line.split()
        if len(f) < 5:
            continue
        mid, mp, side, res, opp = f[:5]
        p = os.path.join(D, mid + ".json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        us = "team" + side.upper()
        them = "teamB" if us == "teamA" else "teamA"
        g = {t["team"]: int(t["submittedGems"]) for t in d["teams"]}
        x = dict(res=res, r=d["match"]["roundsStarted"], gu=g[us], gt=g[them], cu=0, ct=0, du=0, lost=0, carry=0)
        for c in d["champions"]:
            m = c["metrics"]
            if c["team"] == us:
                x["cu"] += int(m["collectedGems"]); x["du"] += int(m["deaths"]); x["carry"] += int(m["gems"])
            else:
                x["ct"] += int(m["collectedGems"])
        for e in d["events"]:
            if e["kind"] == "gemLoss" and e["owner"].get("team") == us:
                for y in e["entries"]:
                    x["lost"] += int(float(y.get("value", 0)))
        k = (opp, mp, side)
        seen[k] = seen.get(k, -1) + 1
        out[k + (seen[k],)] = x
    return out


sets = [(D, load(D)) for D in sys.argv[1:]]
if len(sets) >= 2:
    A, B = sets[0][1], sets[1][1]
    def f(x):
        return (f"{x['res'][:1].upper()} {x['gu']:4d}-{x['gt']:<4d} col {x['cu']:4d}-{x['ct']:<4d} d {x['du']:3d} r{x['r']:4d}"
                if x else "-" * 34)
    for key in sorted(set(A) | set(B)):
        print(f"{key[0][:12]:12s} {key[1]:11s} | {f(A.get(key))} | {f(B.get(key))}")
for D, S in sets:
    t = dict(n=len(S), wins=sum(x["res"] == "win" for x in S.values()), sub=sum(x["gu"] for x in S.values()),
             their=sum(x["gt"] for x in S.values()), lost=sum(x["lost"] for x in S.values()),
             carry=sum(x["carry"] for x in S.values()), deaths=sum(x["du"] for x in S.values()))
    print(f"{os.path.basename(D.rstrip('/')):14s} games {t['n']:2d} wins {t['wins']:2d}  tributed {t['sub']}-{t['their']} "
          f"(ratio {t['sub'] / max(1, t['their']):.3f})  lost-on-death {t['lost']}  carried-at-end {t['carry']}  deaths {t['deaths']}")
