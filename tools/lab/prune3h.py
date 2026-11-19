#!/usr/bin/env python3
"""prune3h: the standing 3-hour cleanup (Tool Builder, 10 Nov; owner: "delete all unnecessary files so bots, replays and any unused scratch
that is not used for 3 hours", "make sure you have a hook for deleting files"). One pass, or --loop (hourly, unit nova-prune3h):
  1. closed bots: tools/lab/closedprune.py --apply with CB_AGE_H=AGE (keeps running, recent, current, shipped, parents, tool bots, and
     every bot tools/lab/inuse.py finds in use: command lines, pilot items, stage manifests, nova-* units, dirs changed within AGE)
  2. idle agent run data: tools/lab/idleprune.py --apply with IDLEPRUNE_H=AGE (keeps .md/.py/.sh/.tsv, prereg, summaries)
  3. replays and run dirs in /data/USER/abl untouched for AGE hours, unless named in a report, ledger, pending read or bot_errors, or open
     in a running process
  4. replay decode-cache files (/data/USER/rdec_cache) untouched for AGE hours (rebuilt on demand in 1-6 s)
Every deletion goes through tools/lab/rmdata.sh (its own checks and log). AGE: PRUNE3H_AGE hours (default 3).
Off: touch /data/USER/st/bq/prune3h_OFF. Log: /data/USER/st/tb2/prune3h.log.
usage: python3 -I tools/lab/prune3h.py [--loop] [--dry]"""
import glob
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
LAB = REPO + "/tools/lab"
OFF = "/data/USER/st/bq/prune3h_OFF"
LOG = "/data/USER/st/tb2/prune3h.log"
AGE = float(os.environ.get("PRUNE3H_AGE", "3"))
DRY = "--dry" in sys.argv
CITES = [REPO + "/condor-work/reports/*.md", REPO + "/condor-work/reports/analysts/*.md", REPO + "/docs/bot_errors.md",
         "/data/USER/st/bq/pending_reads.txt", "/data/USER/st/bq/failure_chains.md"]


def log(m):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}{' [DRY]' if DRY else ''} {m}\n")


def run_tool(name, env):
    cmd = ["nice", "-n", "15", sys.executable, "-I", os.path.join(LAB, name)] + ([] if DRY else ["--apply"])
    r = subprocess.run(cmd, cwd=REPO, env=dict(os.environ, **env), capture_output=True, text=True, timeout=3600)
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    log(f"{name}: rc {r.returncode}: {tail[0][:220]}")


def cited_abl():
    names = set()
    for pat in CITES:
        for p in glob.glob(pat):
            try:
                names.update(re.findall(r"abl/([A-Za-z0-9_.+-]+)", open(p, errors="replace").read()))
            except OSError:
                pass
    for p in glob.glob("/proc/[0-9]*"):
        try:
            for fd in os.listdir(p + "/fd"):
                t = os.readlink(f"{p}/fd/{fd}")
                m = re.match(r"/data/USER/abl/([^/]+)", t)
                if m:
                    names.add(m.group(1))
            m = re.match(r"/data/USER/abl/([^/]+)", os.readlink(p + "/cwd"))
            if m:
                names.add(m.group(1))
        except OSError:
            pass
    return names


def rm_list(paths, what):
    if not paths:
        log(f"{what}: nothing to remove")
        return
    lst = f"/data/USER/st/tb2/prune3h_{what}.txt"
    open(lst, "w").write("\n".join(paths) + "\n")
    r = subprocess.run(["sh", os.path.join(LAB, "rmdata.sh")] + (["--dry"] if DRY else []) + [lst], cwd=REPO, capture_output=True, text=True,
                       timeout=7200)
    log(f"{what}: {len(paths)} listed; {((r.stdout + r.stderr).strip().splitlines() or [''])[-1][:200]}")


def one_pass():
    if os.path.exists(OFF):
        log(f"{OFF} present: skipped")
        return
    cut = time.time() - AGE * 3600
    run_tool("closedprune.py", {"CB_AGE_H": str(AGE)})
    run_tool("idleprune.py", {"IDLEPRUNE_H": str(AGE)})
    keep = cited_abl()
    sys.path.insert(0, LAB)
    import inuse  # 10 Nov: an abl run dir named after a bot in use (process, pilot item, stage manifest, nova-* unit, recent dir) stays
    busy = inuse.in_use_bots(AGE, strict=not DRY)
    abl = [d for d in glob.glob("/data/USER/abl/*") if os.path.isdir(d) and os.path.basename(d) not in keep and os.path.getmtime(d) < cut
           and not (set(inuse.TOK.findall(os.path.basename(d))) & busy)]
    rm_list(abl, "abl")
    rdec = []
    for root, _, files in os.walk("/data/USER/rdec_cache"):
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getmtime(p) < cut:
                    rdec.append(p)
            except OSError:
                pass
    rm_list(rdec, "rdec")


def main():
    if "--loop" not in sys.argv:
        return one_pass()
    while True:
        try:
            one_pass()
        except Exception as e:  # noqa: BLE001  a cleanup loop must not die on one bad pass
            log(f"error: {e!r}")
        time.sleep(3600)


if __name__ == "__main__":
    main()
