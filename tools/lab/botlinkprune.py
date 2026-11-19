#!/usr/bin/env python3
"""botlinkprune: guarded prune of old bots/ links (owner OK 12 Nov ~21:3xZ; TB). A link in bots/ -> /data/zw4424/st/new/bots/NAME goes when it is > 3 h old
and NAME is not cited in bq ledgers (armq.txt, pending_reads, failure_chains, fuelbank, hold_submit, bake_keep, ...), reports (condor-work/reports/**.md,
live/), prereg.md files, CLAUDE.md, tools/lab, rulecheck p6, any bot BASE/FLIP/PARENT/SHIPCHECK file, or a running process; protected prefixes
(base_, spar_, trunk, the anchors) never go. keeplist (via rmdata) also refuses bots with a live SHIPCHECK marker (ended/skipped > 3 h is not live).
Only the link goes: the bot dir stays on /data. usage: botlinkprune.py OUTLIST   (then: sh tools/lab/rmdata.sh OUTLIST)"""
import os, re, glob, time, subprocess, sys

BOTS = "/homes/zw4424/cambc/bots"
TOK = re.compile(r"nova_[A-Za-z0-9_.+-]*[A-Za-z0-9_+]")
now = time.time()
links = []
for n in os.listdir(BOTS):
    p = os.path.join(BOTS, n)
    if os.path.islink(p) and n.startswith("nova_"):
        age = now - os.lstat(p).st_mtime
        tgt = os.path.realpath(p)
        if age > 3 * 3600 and tgt.startswith("/data/zw4424/") and os.path.isdir(tgt):
            links.append(n)
keep = set()
def scan(path, cap=50 << 20):
    try:
        with open(path, errors="replace") as f:
            keep.update(TOK.findall(f.read(cap)))
    except OSError:
        pass
BQ = "/data/zw4424/st/bq"
for f in ["armq.txt", "pending_reads.txt", "live.txt", "baseline.txt", "failure_chains.md", "hold_submit.txt", "bake_keep.txt",
          "parked_v826_1112.txt", "pending_nocopy_1112.txt", "tb_open_1112.md", "fuelbank.tsv", "identship.log"]:
    scan(os.path.join(BQ, f))
# armq log + shipwatch log of the last 3 days only (recent activity)
for f in []:  # logs are history, not citations (owner OK 12 Nov ~22:2xZ guarded prune)
    try:
        with open(os.path.join(BQ, f), errors="replace") as fh:
            for ln in fh:
                if ln[:10] >= time.strftime("%Y-%m-%d", time.gmtime(now - 1 * 86400)):
                    keep.update(TOK.findall(ln))
    except OSError:
        pass
R = "/homes/zw4424/condor-work/reports"
for f in glob.glob(R + "/*.md") + glob.glob(R + "/analysts/*.md") + glob.glob(R + "/parked/*.md") + glob.glob(R + "/live/*.md"):
    scan(f)
for f in glob.glob("/data/zw4424/st/b*/prereg.md") + glob.glob("/homes/zw4424/cambc/CLAUDE.md") + glob.glob("/homes/zw4424/cambc/tools/lab/*.py"):
    scan(f)
for f in glob.glob("/data/zw4424/rulecheck/p6/*.md"):
    scan(f)
# every bot dir's BASE / FLIP / SHIPCHECK* (parents of anything)
for d in glob.glob("/data/zw4424/st/new/bots/*"):
    for f in ("BASE", "FLIP", "PARENT"):
        scan(os.path.join(d, f), 1 << 16)
    for f in glob.glob(d + "/SHIPCHECK*"):
        scan(f, 1 << 16)
# running processes
for p in os.listdir("/proc"):
    if p.isdigit():
        try:
            keep.update(TOK.findall(open(f"/proc/{p}/cmdline", "rb").read().decode(errors="replace")))
        except OSError:
            pass
prot = re.compile(r"^nova_(base_|spar_|trunk|b633_rythhp|b2769_ems_glate)")
cand = [n for n in sorted(links) if n not in keep and not prot.match(n)]
open(sys.argv[1], "w").write("\n".join(os.path.join(BOTS, n) for n in cand) + "\n")
print(f"links >24h: {len(links)}; referenced/protected: {len(links) - len(cand)}; candidates: {len(cand)}")
