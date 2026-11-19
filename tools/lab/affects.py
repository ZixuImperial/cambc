#!/usr/bin/env python3
"""affects: what share of maps a candidate changes (owner 12 Nov ~20:5xZ: "with updates in the message can you put percentage of maps
each update affects"). Tool Builder.

usage: python3 -I tools/lab/affects.py CAND BASE TAG NAME [--maps 100]
Plays CAND v BASE through tools/cxe/cxeident.py on --maps new fresh maps x 2 seats at UNLIMITED fuel (pilots only, low priority), so
fuel timing cannot reshuffle a game: a game differs only where the change itself acts. Affected share = games that differ / games.
Writes one line to bq/affects.tsv (utc, tag, name, differ, games, pct) and one 'affects NAME' line to bq/shipwatch.log, which
since.py and the ship notes read. shipcheck starts it detached at the start of every check; it never blocks or decides anything."""
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
BQ = "/data/zw4424/st/bq"


def main():
    a = sys.argv[1:]
    if len(a) < 4:
        sys.exit(__doc__)
    cand, base, tag, name = a[:4]
    maps = int(a[a.index("--maps") + 1]) if "--maps" in a else 100
    t0 = time.time()
    r = subprocess.run(["nice", "-n", "15", sys.executable, "-I", os.path.join(REPO, "tools/cxe/cxeident.py"), base, cand, "--maps", str(maps),
                        "--seed", str(int(re.sub(r"\D", "", tag) or 0) % 997 + 23)], capture_output=True, text=True, cwd=REPO,
                       env=dict(os.environ, CXEIDENT_PILOTS_ONLY="1", PILOTCXE_PRIO="25"))
    m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", r.stdout)
    # 13 Nov (owner: "why does it keep saying 0% maps on the ship?"): a fuel-only change plays identically at unlimited fuel (0%) and acts only
    # through cut-offs at the real 100k budget, so the 100k cut-off rate (cxeident's real-budget line) rides along: OLD -> NEW per game
    cm = re.search(r"fuel cut-offs ([\d.]+) -> ([\d.]+) per game", r.stdout)
    cuts = f"{cm.group(1)}->{cm.group(2)}" if cm else ""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not m or int(m.group(2)) == 0:
        line = f"affects {name}: not measured (cxeident: {((r.stdout + r.stderr).strip().splitlines() or ['no output'])[-1][:120]})"
        differ = games = None
    else:
        same, games = int(m.group(1)), int(m.group(2))
        differ = games - same
        line = (f"affects {name}: {100 * differ / games:.1f}% of maps ({differ} of {games} games play differently from its base at "
                f"unlimited fuel, {maps} new maps x 2 seats, {time.time() - t0:.0f} s)"
                + (f"; at the 100k budget fuel cut-offs/game {cuts}" if cuts else ""))
    with open(os.path.join(BQ, "affects.tsv"), "a") as f:
        f.write(f"{stamp}\t{tag}\t{name}\t{'' if differ is None else differ}\t{'' if games is None else games}\t"
                f"{'' if differ is None else round(100 * differ / games, 1)}\t{cuts if differ is not None else ''}\n")
    with open(os.path.join(BQ, "shipwatch.log"), "a") as f:
        f.write(f"{stamp[:10]} {stamp[11:]} {line}\n")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
