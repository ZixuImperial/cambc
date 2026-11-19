#!/usr/bin/env python3
"""specnew: start a spec the checked way (Tool Builder, 12 Nov; Coordinator's evidence checklist, condor-work/reports/evidence_checklist_1112.md).

usage: python3 -I tools/lab/specnew.py NAME [--words "what the idea does"] [--write]
  NAME   the idea prefix (2-5 capitals, e.g. LSO); the spec file is condor-work/reports/analysts/spec_<name>_<MMDD>.md
Prints, before you write anything:
  1. ledger hits: bq/failure_chains.md lines and ask.py's top notes for NAME (+ --words): was it tried, closed, on which numbers
  2. name clashes: NAME as a flag prefix in live's source (NAME_BITS / NAME_TAB / NAME_ON), in the failure ledger, in an existing spec file
  3. a skeleton with the checklist items pre-filled (ranked only, full match ids, outcome-free rows, yardstick acceptance,
     KILL rows a reader can compute, measured fuel, fresh claims), printed, or written to the spec file with --write (never overwrites)."""
import glob
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
REP = "/homes/USER/condor-work/reports"
LEDGER = "/data/USER/st/bq/failure_chains.md"


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    name = a[0].upper()
    words = a[a.index("--words") + 1] if "--words" in a else ""
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", name):
        sys.exit(f"specnew: NAME must be 2-6 capitals/digits starting with a letter, not {name!r}")
    print(f"== 1. ledger hits for {name}")
    try:
        hits = [ln.rstrip() for ln in open(LEDGER, errors="replace") if re.search(rf"\b{name}\d*\b", ln)]
    except OSError:
        hits = []
    for ln in hits[-12:]:
        print("  " + ln[:200])
    print(f"  ({len(hits)} ledger lines)" if hits else "  none in failure_chains.md")
    q = " ".join(x for x in (name, words) if x)
    r = subprocess.run([sys.executable, "-I", f"{REPO}/tools/lab/ask.py", q], capture_output=True, text=True, timeout=300, cwd=REPO)
    print(f"== ask.py {q!r}")
    for ln in r.stdout.splitlines()[:12]:
        print("  " + ln[:200])
    print(f"== 2. name clashes for {name}")
    clash = []
    try:
        live = open("/data/USER/st/bq/live.txt").readline().split()[1]
        src = os.path.realpath(f"{REPO}/bots/{live}/src")
        for f in glob.glob(f"{src}/*"):
            t = open(f, errors="replace").read()
            m = re.search(rf"\b{name}_(BITS|TAB|ON)\b", t)
            if m:
                clash.append(f"live {live}: {os.path.basename(f)} has {m.group(0)}")
                break
    except (OSError, IndexError):
        pass
    for f in glob.glob(f"{REP}/analysts/spec_{name.lower()}*.md") + glob.glob(f"{REP}/spec_{name.lower()}*.md"):
        clash.append(f"spec file exists: {f}")
    for c in clash:
        print("  CLASH " + c)
    if not clash:
        print("  none (prefix free in live's source and in spec files)")
    path = f"{REP}/analysts/spec_{name.lower()}_{time.strftime('%m%d', time.gmtime())}.md"
    skel = f"""# Spec {name}: <one line> ({time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}, <author>)

Checklist (condor-work/reports/evidence_checklist_1112.md): tick each before sending.
- [ ] Ranked games only (gameindex.py drops unranked by default; no --include-unranked).
- [ ] Every match id FULL (36 chars); gameindex lookup exits 2 on a prefix collision.
- [ ] Rows are outcome-free (draft-time / decision-time features; no split by the game's result).
- [ ] Yardstick: the opponent / map set the read uses is named, with its acceptance numbers.
- [ ] Every KILL / GO row names the reader or tool that computes it from the read's own games (prearm WARNs otherwise).
- [ ] Fuel: measured (fuelprof / lineprof / cutprof dir), not estimated.
- [ ] Claims are fresh: each number has its source file and time.
- [ ] Closing needs a played test: name it (Step 0 count / shadow / local read / shipcheck), never argument (item 13; closedby.py).

Ledger: {len(hits)} failure_chains lines for {name}{' (read them: above)' if hits else ''}. Name: {'CLASH (above)' if clash else 'free'}.

## Change (flag {name}_BITS, one bit per idea)
- base file:line, per-bit condition + action

## Firing / Step 0
- count per game, reader:

## Rows (pre-stated)
- GO:
- KILL:
"""
    print(f"== 3. skeleton ({path})")
    if "--write" in a:
        if os.path.exists(path):
            sys.exit(f"specnew: {path} exists; not overwritten")
        open(path, "w").write(skel)
        print(f"  written: {path}")
    else:
        print(skel)


if __name__ == "__main__":
    main()
