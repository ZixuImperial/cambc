"""botdirprune (13 Nov, TB; /data at 99%): bot copies in /data/USER/st/new/bots that NO bots/ link points at, untouched > BDP_AGE_H (24) h and
not cited (the same citation scan as botlinkprune: bq ledgers, reports, prereg, CLAUDE.md, tools, RC lists, every bot's BASE/FLIP/PARENT/SHIPCHECK,
running processes; base_/spar_/trunk/anchors never). usage: botdirprune.py OUTLIST   (then: sh tools/lab/rmdata.sh OUTLIST; keeplist refuses in-use bots)"""
import os, re, glob, time, subprocess, sys

BOTS = "/homes/USER/cambc/bots"
NEW = "/data/USER/st/new/bots"
TOK = re.compile(r"nova_[A-Za-z0-9_.+-]*[A-Za-z0-9_+]")
now = time.time()
linked = {os.path.realpath(os.path.join(BOTS, n)) for n in os.listdir(BOTS)}
age_h = float(os.environ.get("BDP_AGE_H", 24))
links = []
for n in os.listdir(NEW):
    p = os.path.join(NEW, n)
    if n.startswith("nova_") and os.path.isdir(p) and not os.path.islink(p) and os.path.realpath(p) not in linked:
        if now - max(os.path.getmtime(p), max((os.path.getmtime(os.path.join(p, f)) for f in os.listdir(p)), default=0)) > age_h * 3600:
            links.append(n)
keep = set()
def scan(path, cap=50 << 20):
    try:
        with open(path, errors="replace") as f:
            keep.update(TOK.findall(f.read(cap)))
    except OSError:
        pass
BQ = "/data/USER/st/bq"
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
R = "/homes/USER/condor-work/reports"
for f in glob.glob(R + "/*.md") + glob.glob(R + "/analysts/*.md") + glob.glob(R + "/parked/*.md") + glob.glob(R + "/live/*.md"):
    scan(f)
for f in glob.glob("/data/USER/st/b*/prereg.md") + glob.glob("/homes/USER/cambc/CLAUDE.md") + glob.glob("/homes/USER/cambc/tools/lab/*.py"):
    scan(f)
for f in glob.glob("/data/USER/rulecheck/p6/*.md"):
    scan(f)
# every bot dir's BASE / FLIP / SHIPCHECK* (parents of anything)
for d in glob.glob("/data/USER/st/new/bots/*"):
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
open(sys.argv[1], "w").write("\n".join(os.path.join(NEW, n) for n in cand) + "\n")
print(f"unlinked bot dirs > {age_h:g} h: {len(links)}; referenced/protected: {len(links) - len(cand)}; candidates: {len(cand)}")
