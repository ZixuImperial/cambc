#!/usr/bin/env python3
"""triagefill: back-fill critgame's triage table with the losses it never read (Tool Builder, 9 Nov; owner via the Coordinator: "the
analysts receive every loss"; all_losses.md showed ~1,300 'untriaged': climb-lane losses of versions whose live window critgame's auto
pass had already left).

Per pass: the untriaged losses of /data/zw4424/st/crit/all_losses.tsv (losstable's rows, cause 'untriaged'), newest version first,
ranked before unranked, at most --per (40). Each: its replay (plat_fetch into /data/zw4424/plat/crit_auto, the same set critgame uses;
a copy already on disk is reused), then critgame's own triage_metrics, appended to /data/zw4424/st/crit/triage.jsonl with the lane's
version and side and t_fill so the rows are known to come from here. A game that can't be fetched or read is logged and skipped this pass.
losstable then shows it triaged with its cause tags; critgame's LIGHT step can pick it.
usage: python3 -I tools/lab/triagefill.py [--per 40] [--loop [--every 300]] [--dry]
Log: /data/zw4424/st/crit/triagefill.log."""
import csv
import json
import os
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
CRIT = "/data/zw4424/st/crit"
LOG = f"{CRIT}/triagefill.log"
SET = "/data/zw4424/plat/crit_auto"


def say(m):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + m
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def vnum(v):
    try:
        return int(str(v).lstrip("v").split("-")[0])
    except ValueError:
        return 0


def todo():
    done = set()
    try:
        for ln in open(f"{CRIT}/triage.jsonl", errors="replace"):
            try:
                done.add(json.loads(ln).get("id"))
            except ValueError:
                pass
    except OSError:
        pass
    rows = [r for r in csv.DictReader(open(f"{CRIT}/all_losses.tsv"), delimiter="\t") if r.get("cause") == "untriaged" and r["id"] not in done]
    return sorted(rows, key=lambda r: (-vnum(r["version"]), r["lane"] != "ranked", r["id"]))


def one_pass(per, dry):
    import critgame as C
    import replay as R
    rows = todo()
    say(f"pass: {len(rows)} untriaged losses; doing up to {per} (newest version first, ranked first)")
    ok = 0
    for r in rows[:per]:
        mid, side = r["id"], (r.get("side") or "").upper()
        if dry:
            say(f"  DRY {mid} {r['version']} {r['lane']} {r['map']} {side}")
            continue
        if not side:
            say(f"  {mid}: no side in the lane's list; skipped")
            continue
        p = subprocess.run(["sh", os.path.join(REPO, "tools/lab/plat_fetch.sh"), mid, "--dest", SET], capture_output=True, text=True, timeout=1800,
                           env=dict(os.environ, CAMBC_WHO="triagefill"))
        if p.returncode:
            say(f"  {mid}: fetch failed: {(p.stderr or p.stdout).strip()[-150:]}")
            continue
        try:
            g = R.load(mid, side)
            row = dict(id=mid, version=r["version"], result="loss", kind=r["lane"], map=r["map"], foe=r["foe"], t=time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
                       t_fill=1, **C.triage_metrics(g))
        except Exception as e:  # noqa: BLE001  one bad replay must not stop the back-fill
            say(f"  {mid}: triage failed: {e!r}"[:200])
            continue
        with open(f"{CRIT}/triage.jsonl", "a") as fh:
            fh.write(json.dumps(row) + "\n")
        ok += 1
    say(f"pass done: {ok} triaged")
    return ok


def main():
    a = sys.argv[1:]
    per = int(a[a.index("--per") + 1]) if "--per" in a else 40
    dry = "--dry" in a
    if "--loop" not in a:
        one_pass(per, dry)
        return 0
    every = int(a[a.index("--every") + 1]) if "--every" in a else 300
    while True:
        try:
            if not one_pass(per, dry) and not todo():
                say("nothing left; checking again later")
        except Exception as e:  # noqa: BLE001
            say(f"pass failed: {e!r}"[:200])
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
