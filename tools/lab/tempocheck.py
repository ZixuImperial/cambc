#!/usr/bin/env python3
"""tempocheck: the self-play tempo lines of a behaviour-lane shipcheck (Tool Builder, 10 Nov; Planner + Deep, selfplay_tempo_1110.md: self-play
inflates early fighting ~1.8x for most kits, 5.7-6.1 fight turns per champion to r150 in self-play v 3.3 for us on the ladder; deaths
unchanged, so the extra pokes cost farm turns).

shipcheck keeps the CONFIRM leg's replays (OTF_KEEP=/data/USER/st/bq/tempo/TAG: rep/*.repl26a + condab's set.json with map, our seat and
the winner per game) for behaviour/draft checks. After the verdict this reads them with tools/lab/tempo.py (Deep's reader) and prints, for
fight turns per champion to r150 (cand = the candidate's champions, live = live's, on the SAME maps, so CONFIRM's map mix needs no calibration):
  (a) TEMPO SHIFT (Planner): cand v live, paired by map, % change with a bootstrap 95% CI over maps. FLAG when it is >= +15%, the CI excludes
      0 and the h2h point > .50: the cell made play pokier, which self-play rewards.
  (b) WHERE THE GAIN SITS (Planner): maps split into terciles by live's own fight turns; the cand's win share per tercile. FLAG when the top
      tercile is > .50 and the bottom two are <= .50: the gain lives only in high-tempo games.
  plus the absolute means and the by-kit table as information. TEMPO_HIGH=X (env) also flags the old absolute form (mean > X, gain).
Information only, never part of the verdict. Deletes the kept replays when done (--keep keeps them).
usage: python3 -I tools/lab/tempocheck.py TAG [--keep]   -> stdout (shipcheck writes it to bq/sc_TAG_tempo.txt)"""
import collections
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys

Q = "/data/USER/st/bq"
REPO = "/homes/USER/cambc"
SHIFT, BOOT = 0.15, 2000


def h2h_point(tag):
    try:
        txt = open(os.path.join(Q, f"shipcheck_{tag}.txt")).read()
    except OSError:
        return None
    m = re.search(r"pooled BIG \+ fresh\s+([\d.]+)", txt) or re.search(r"live h2h[^\n]*?\s([0-5]\.\d{3,4}) \[", txt)
    return float(m.group(1)) if m else None


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    tag = a[0]
    d = os.path.join(Q, "tempo", tag)
    try:
        games = json.load(open(os.path.join(d, "set.json")))
        games = games.get("games", games) if isinstance(games, dict) else games
    except (OSError, ValueError):
        games = []
    games = [g for g in games if os.path.exists(os.path.join(d, g["replay"]))]
    if not games:
        print(f"self-play tempo {tag}: no kept CONFIRM replays with set.json in {d}")
        return
    lst, out = os.path.join(d, "list.txt"), os.path.join(d, "tempo.jsonl")
    # tempo.py labels team 0 / team 1 with LABEL_A / LABEL_B; seat a = team A = team 0
    open(lst, "w").write("".join(f"{os.path.join(d, g['replay'])} {'cand live' if g['seat'] == 'a' else 'live cand'}\n" for g in games))
    subprocess.run(["nice", "-n", "15", sys.executable, "-I", os.path.join(REPO, "tools/lab/tempo.py"), lst, out, "2"], check=False)
    rows = [json.loads(x) for x in open(out) if x.strip()] if os.path.exists(out) else []
    if not rows:
        print(f"self-play tempo {tag}: tempo.py returned nothing for {len(games)} replays")
        return
    by_path = {os.path.join(d, g["replay"]): g for g in games}
    per_map = collections.defaultdict(lambda: {"cand": [], "live": [], "win": []})
    kit = collections.defaultdict(list)
    for r in rows:
        g = by_path.get(r["mid"])
        if not g or "150" not in r:
            continue
        per_map[g["map"]][r["side"]].append(r["150"]["fight"])
        kit[(r["side"], r["kit"])].append(r["150"]["fight"])
    for g in games:
        if g.get("win") in ("A", "B"):
            per_map[g["map"]]["win"].append(1.0 if g["win"].lower() == g["seat"] else 0.0)
    maps = [m for m, v in per_map.items() if v["cand"] and v["live"]]
    if len(maps) < 10:
        print(f"self-play tempo {tag}: only {len(maps)} maps with both sides read")
        return
    mc = {m: sum(per_map[m]["cand"]) / len(per_map[m]["cand"]) for m in maps}
    ml = {m: sum(per_map[m]["live"]) / len(per_map[m]["live"]) for m in maps}
    sc, sl = sum(mc.values()), sum(ml.values())
    shift = sc / sl - 1 if sl else 0.0
    rng = random.Random(1)
    bs = []
    for _ in range(BOOT):
        s = [rng.choice(maps) for _ in maps]
        c, l_ = sum(mc[m] for m in s), sum(ml[m] for m in s)
        bs.append(c / l_ - 1 if l_ else 0.0)
    bs.sort()
    lo, hi = bs[int(0.025 * BOOT)], bs[int(0.975 * BOOT) - 1]
    pt = h2h_point(tag)
    gain = pt is not None and pt > 0.5
    print(f"self-play tempo {tag} (information; CONFIRM {len(games)} games on {len(maps)} maps"
          + (f", h2h point {pt:.4f}" if pt is not None else "") + "):")
    print(f"  fight turns per champion to r150: cand {sc / len(maps):.2f}, live {sl / len(maps):.2f} "
          f"(ladder ~3.3 for us, 3.5-4.6 top 3; self-play 5.7-6.1, Deep; this map mix differs, so compare cand v live only)")
    fa = shift >= SHIFT and lo > 0 and gain
    print(f"  (a) tempo shift cand v live: {100 * shift:+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%] (paired by map, bootstrap over maps)"
          + ("  FLAG: pokier play, which self-play rewards" if fa else ""))
    order = sorted(maps, key=lambda m: ml[m])
    k = len(order) // 3
    terc = [order[:k], order[k:2 * k], order[2 * k:]]
    share = []
    for t in terc:
        w = [x for m in t for x in per_map[m]["win"]]
        share.append((sum(w) / len(w) if w else float("nan"), len(w), (ml[t[0]], ml[t[-1]]) if t else (0, 0)))
    fb = share[2][0] > 0.5 and share[0][0] <= 0.5 and share[1][0] <= 0.5
    print("  (b) cand win share by live-tempo tercile: " + ", ".join(
        f"{nm} {s:.3f} (n {n}, live tempo {r[0]:.1f}-{r[1]:.1f})" for nm, (s, n, r) in zip(("low", "mid", "high"), share))
        + ("  FLAG: the gain lives only in high-tempo games" if fb else ""))
    hi_abs = os.environ.get("TEMPO_HIGH")
    if hi_abs and gain and sc / len(maps) > float(hi_abs):
        print(f"  (TEMPO_HIGH {hi_abs}) FLAG: cand mean {sc / len(maps):.2f} > {hi_abs}")
    kits = collections.defaultdict(dict)
    for (side, kt), v in kit.items():
        kits[kt][side] = sum(v) / len(v)
    print("  by kit (cand / live): " + ", ".join(f"{kt} {v.get('cand', float('nan')):.1f}/{v.get('live', float('nan')):.1f}"
                                                for kt, v in sorted(kits.items(), key=lambda kv: -kv[1].get('live', 0))))
    if "--keep" not in a:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
