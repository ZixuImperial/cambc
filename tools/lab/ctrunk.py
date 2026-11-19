#!/usr/bin/env python3
"""ctrunk: the correctness-trunk lane's decision (owner 6 Nov ~13:50Z via the Builder, "Correctness lane"). For the Builder's correctness
batches only (armq add ... ctrunk ..., marker LANE=ctrunk). The candidate plays exactly the fix lane's legs; then this re-decides the rows:

  GATING (as the fix lane): trunk code / identity, bot faults, ubaudit, capped fuel (FUELX, default 1.5, cumulative 2.0x v the v562 anchor,
          see shipcheck.fuel_row), mergecheck rows, and the death guard re-judged: FAIL on a significant rise, pooled z >= 2 over BIG + fresh
          (each set's z weighted by sqrt(maps): Stouffer).
  INFO ONLY: live h2h, anchor h2h, change size, fresh, panel, fresh decides, pooled BIG + fresh: reported as INFO(was X); they block ONLY
          when the pooled BIG + fresh point is < 0.495 (the 'ctrunk pooled floor' row; owner 7 Nov: bugs use .495, was .48).
The report names it: "CTRUNK: h2h informational (owner 6 Nov)".

usage (re-decide a finished shipcheck's stored rows, no games): python3 -I tools/lab/ctrunk.py TAG [TAG ...]
  prints the ctrunk verdict of bq/shipcheck_TAG.txt; it decides and submits nothing (to ship, re-arm with --lane ctrunk: games are reused)."""
import math
import os
import re
import sys

FLOOR = 0.495
DEATH_Z = 2.0
NOTE = "CTRUNK: h2h informational (owner 6 Nov)"
INFO_ROWS = ("live h2h", "anchor h2h", "fix-lane change size", "fresh maps", "playstyle panel", "fresh decides", "pooled BIG + fresh",
             "nochase2 paired D", "CONFIRM", "BIG h2h", "trigger D", "nochase2")


def _info(name):
    return any(name == r or name.startswith(r + " ") or name.startswith(r + "(") for r in INFO_ROWS)


def pooled_point(rows):
    """pooled BIG + fresh point from the live h2h (BIG/pool maps) and fresh rows, by maps; None when either is missing"""
    pr = next((r for r in rows if r[0].startswith("pooled BIG + fresh")), None)
    if pr:
        m = re.match(r"\s*([\d.]+)", pr[1])
        if m:
            return float(m.group(1)), "pooled row"
    lh = next((r for r in rows if r[0] == "live h2h"), None) or next((r for r in rows if r[0].startswith("live h2h")), None)
    fr = next((r for r in rows if r[0] == "fresh maps"), None)
    a = re.search(r"first ([\d.]+) \[[\d.]+, [\d.]+\] n (\d+)", lh[1]) if lh and "near-miss" in lh[0] else None
    a = a or (re.match(r"\s*([\d.]+) \[[\d.]+, [\d.]+\] n (\d+)", lh[1]) if lh else None)
    b = re.search(r"CAND vs LIVE ([\d.]+) \[[^\]]*\] over (\d+) maps", fr[1]) if fr else None
    parts = [(float(m.group(1)), int(m.group(2))) for m in (a, b) if m]
    if not parts:
        return None, "no live h2h / fresh read"
    n = sum(k for _, k in parts)
    return sum(p * k for p, k in parts) / n, " + ".join(f"{p:.3f} n {k}" for p, k in parts)


def death_z(row):
    """pooled z of the death guard row 'BIG a vs b/g (+d, z Z, N maps); fresh a vs b (+d, z Z, N maps)'"""
    zs = [(float(z), int(n)) for z, n in re.findall(r"z ([+-]?[\d.]+), (\d+) maps", row[1])]
    if not zs:
        return None
    w = sum(math.sqrt(n) for _, n in zs)
    return sum(z * math.sqrt(n) for z, n in zs) / w if w else None


def decide(rows):
    """-> (rows, overall) under the ctrunk rule"""
    out = []
    for name, val, bar, v in rows:
        if _info(name):
            out.append((name, val, bar, f"INFO(was {v})"))
        elif name.startswith("death guard"):
            z = death_z((name, val, bar, v))
            if z is None:
                out.append((name, val, bar, v))
            else:
                out.append((name, val + f"; pooled z {z:+.2f}", f"CTRUNK: not pooled z >= {DEATH_Z:g}", "FAIL" if z >= DEATH_Z else "PASS"))
        else:
            out.append((name, val, bar, v))
    p, how = pooled_point(rows)
    if p is None:
        out.append(("ctrunk pooled floor", how, f"BIG + fresh pooled >= {FLOOR}", "INCONCLUSIVE"))
    else:
        out.append(("ctrunk pooled floor", f"{p:.4f} ({how})", f"BIG + fresh pooled >= {FLOOR}", "PASS" if p >= FLOOR else "FAIL"))
    vs = [r[3] for r in out if not r[3].startswith("INFO")]
    overall = "FAIL" if "FAIL" in vs else "VACUOUS" if "VACUOUS" in vs else "INCONCLUSIVE" if "INCONCLUSIVE" in vs else "PASS"
    return out, overall


def parse_stored(path):
    txt = open(path, errors="replace").read().splitlines()
    rows = []
    for ln in txt[2:]:
        if ln.strip().startswith("OVERALL:"):
            break
        m = re.match(r"^  (.{20}) (.*?)\s(PASS|FAIL|INCONCLUSIVE|VACUOUS|EXT|SKIP)\s*$", ln) or \
            re.match(r"^  (live h2h \(near-miss ext\)) (.*?)\s(PASS|FAIL|INCONCLUSIVE)\s*$", ln)
        if m:
            name, rest = m.group(1).strip(), m.group(2)
            bm = re.search(r"\s{2,}(\S.*)$", rest)
            rows.append((name, rest, bm.group(1) if bm else "", m.group(3)))
    return txt[0] if txt else "", rows


def main():
    tags = sys.argv[1:]
    if not tags:
        sys.exit(__doc__)
    rc = 1
    for t in tags:
        p = f"/data/zw4424/st/bq/shipcheck_{t}.txt"
        if not os.path.exists(p):
            print(f"{t}: no stored verdict")
            continue
        head, rows = parse_stored(p)
        new, overall = decide(rows)
        rc = 0 if overall == "PASS" and rc else rc
        print(f"{head}\n  {NOTE}: re-decided from the stored rows -> {overall}")
        for name, val, bar, v in new:
            if not v.startswith("INFO") or "FAIL" in v:
                print(f"    {name:22s} {v:18s} {val[:110]}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
