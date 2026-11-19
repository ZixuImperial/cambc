#!/usr/bin/env python3
"""partials: interim reads of running shipchecks (owner 13 Nov ~03:4xZ via the Planner: "make sure both [camp logic, aggression] have a slot for
testing and return partial results so we can see promise"). Tool Builder.

Every SW_PARTIAL_EVERY (60) s, for each running shipcheck, reads its fresh leg's per-game records as they arrive (panel/TAGff/fp_games.jsonl for a
FRESH-FIRST look, else panel/TAG/fp_games.jsonl), pairs both seats by map and writes ONE line per crossing of 50% and 80% of the first look to
bq/partials.log:  UTC  partial NAME [family] 50%|80% of look N maps: point P [lo, hi] n MAPS (games G); deaths/g CAND v BASE; fuel cut-offs CAND v BASE
Information only: never a verdict, never read by shipcheck. Families from bq/prio_family.txt (comment after '#', e.g. 'CAMP LOGIC').
usage: partials.py loop | once"""
import glob
import json
import math
import os
import re
import subprocess
import sys
import time

BQ = "/data/zw4424/st/bq"
PANEL = "/data/zw4424/st/panel"
LOG = os.path.join(BQ, "partials.log")
STATE = os.path.join(BQ, "partials_state.json")
MARKS = (0.5, 0.8)


def running():
    """-> [(name, tag)] of running shipcheck.py processes."""
    out = subprocess.run(["pgrep", "-af", "[s]hipcheck.py nova_"], capture_output=True, text=True).stdout
    res = []
    for ln in out.splitlines():
        m = re.search(r"shipcheck\.py (nova_\S+) (\d+)", ln)
        if m:
            res.append((m.group(1), m.group(2)))
    return res


def family(name):
    try:
        sc = open(f"/homes/zw4424/cambc/bots/{name}/SHIPCHECK", errors="replace").read()
    except OSError:
        sc = ""
    text = name + " " + sc
    hit = ""
    try:  # a named family ([CAMP LOGIC], [AGGRESSION]) wins over the plain funnel lines
        for ln in open(os.path.join(BQ, "prio_family.txt")):
            rx, _, com = ln.partition("#")
            rx = rx.strip()
            if rx and re.search(rx, text, re.I):
                m = re.search(r"\[([A-Z ]+)\]", com)
                if m:
                    return m.group(1)
                hit = hit or "funnel"
    except (OSError, re.error):
        pass
    return hit


def look_size(name, tag):
    try:
        out = open(glob.glob(f"{BQ}/shipwatch_{name}_{tag}.out")[0], errors="replace").read(200000)
    except (OSError, IndexError):
        return None, None
    m = re.search(r"FRESH-FIRST[^\n]*?(\d[\d,]*) fresh maps alone first \(tag (\w+)\)", out)
    if m:
        return int(m.group(1).replace(",", "")), m.group(2)
    m = re.search(r"stylepanel\.py \S+ \S+ " + tag + r" --n (\d+)", out)
    if m:
        return int(m.group(1)), tag
    return None, None


def read_games(ptag, cand):
    per = {}
    try:
        f = open(os.path.join(PANEL, ptag, "fp_games.jsonl"), errors="replace")
    except OSError:
        return per
    for ln in f:
        try:
            g = json.loads(ln)
        except ValueError:
            continue
        if cand not in (g.get("a"), g.get("b")):
            continue
        ca = g.get("a") == cand
        w = g.get("win")
        sc = 0.5 if w not in ("A", "B") else (1.0 if (w == "A") == ca else 0.0)
        mine, theirs = (g.get("sa") or {}, g.get("sb") or {}) if ca else (g.get("sb") or {}, g.get("sa") or {})
        x = per.setdefault(g.get("map"), [])
        x.append((sc, int(mine.get("deaths", 0)), int(theirs.get("deaths", 0)), int(mine.get("fuel", 0)), int(theirs.get("fuel", 0))))
    return per


def summary(per):
    ms = [sum(s[0] for s in v) / len(v) for v in per.values() if v]
    n = len(ms)
    if n < 2:
        return None
    mu = sum(ms) / n
    se = math.sqrt(sum((x - mu) ** 2 for x in ms) / (n - 1) / n)
    games = [s for v in per.values() for s in v]
    g = len(games)
    return dict(point=mu, lo=mu - 1.96 * se, hi=mu + 1.96 * se, n=n, g=g, dc=sum(s[1] for s in games) / g, db=sum(s[2] for s in games) / g,
                fc=sum(s[3] for s in games), fb=sum(s[4] for s in games))


def once():
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        st = {}
    for name, tag in running():
        N, ptag = look_size(name, tag)
        if not N:
            continue
        per = read_games(ptag, name)
        games = sum(len(v) for v in per.values())
        frac = games / (2.0 * N)
        done = st.setdefault(f"{tag}:{ptag}", [])
        for mk in MARKS:
            if frac >= mk and mk not in done:
                s = summary(per)
                if not s:
                    continue
                fam = family(name)
                line = (f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} partial {name}{' [' + fam + ']' if fam else ''} {int(mk * 100)}% of look "
                        f"{N} maps: point {s['point']:.4f} [{s['lo']:.3f}, {s['hi']:.3f}] n {s['n']} maps ({s['g']} games); deaths/g {s['dc']:.2f} v "
                        f"{s['db']:.2f}; fuel cut-offs {s['fc']} v {s['fb']}  (information, not a verdict)")
                with open(LOG, "a") as f:
                    f.write(line + "\n")
                print(line, flush=True)
                done.append(mk)
    live = {f"{t}:" for _, t in running()}
    st = {k: v for k, v in st.items() if any(k.startswith(p) for p in live) or len(st) < 400}
    tmp = STATE + f".new.{os.getpid()}"
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, STATE)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("loop", "once"):
        sys.exit(__doc__)
    if sys.argv[1] == "once":
        once()
        return 0
    every = int(os.environ.get("SW_PARTIAL_EVERY", 60))
    while True:
        try:
            once()
        except Exception as e:  # noqa: BLE001  a daemon: log and go on
            print(f"partials: {type(e).__name__}: {e}", flush=True)
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
