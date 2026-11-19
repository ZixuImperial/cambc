#!/usr/bin/env python3
"""closedprune: remove CLOSED bots (store dir /data/zw4424/st/new/bots/NAME and its bots/NAME link). Tool builder 2, 4 Nov (owner:
'delete all unnecessary files which includes bots we have closed'). DRY unless --apply; the list goes to /data/zw4424/st/tb2/closedbots.json.
usage: [CB_AGE_H=8] python3 -I tools/lab/closedprune.py [--apply]
A bot is KEPT when any holds: not nova_*; a spar or the anchor; named in the shipped records (live, best_model, baseline, version_history,
submissions_log), in tools/, in CLAUDE.md, idea_queue, failure_chains, the primer, armq.txt, pending_reads, flagmap, .claude/ or memory, or in
the last 400 lines of builder_queue.md / board.md; a SHIPCHECK shipwatch has not finished; named on a running command line or open by a
process; in use per tools/lab/inuse.py (pilot items, stage manifests, nova-* units, bots/ or store dir changed within CB_AGE_H); any file touched in the last CB_AGE_H hours (default 8); or a TRUNK= parent (FLIP or SHIPCHECK) of a kept bot. All else is closed.
Read-only (frozen) closed bots are made writable just before removal."""
import subprocess, glob, os, re, sys, time, shutil, json
sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
import botprune as BP
sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
import keeplist  # noqa: E402  8 Nov: kept paths (condor-work/keep_paths.txt) are never deleted
keeplist.guard(os, shutil)
REPO, BOTS, STORE = BP.REPO, BP.BOTS, "/data/zw4424/st/new/bots"
R, BQ = BP.REPORTS, "/data/zw4424/st/bq"
AGE = float(os.environ.get("CB_AGE_H", 24))
src = {
 "shipped": [BQ + "/live.txt", BQ + "/best_model.txt", BQ + "/baseline.txt", R + "/submissions_log.md"],
 "tools": [f for f in glob.glob(REPO + "/tools/**", recursive=True) if os.path.isfile(f) and "__pycache__" not in f],
 "current": [REPO + "/CLAUDE.md", R + "/idea_queue.md", BQ + "/failure_chains.md", R + "/subagent_primer.md",
             BQ + "/armq.txt", BQ + "/pending_reads.txt", BQ + "/armq.flagmap.json"] + glob.glob(REPO + "/.claude/**/*", recursive=True)
            + glob.glob("/homes/zw4424/.claude/projects/-homes-zw4424-cambc/memory/*.md"),
}
named = {k: BP.named(v) for k, v in src.items()}
tails = set()
for f in (R + "/builder_queue.md", R + "/analysts/board.md"):
    try: tails |= set(BP.TOK.findall("".join(open(f, errors="ignore").readlines()[-400:])))
    except OSError: pass
named["latest"] = tails
import hashlib
swst = json.load(open(BQ + "/shipwatch_state.json"))
def pending_marker(b, d):
    m = d + "/SHIPCHECK"
    if not os.path.exists(m): return False
    h = hashlib.sha1(open(m, "rb").read()).hexdigest()[:12]
    s = swst.get(b, {})
    return s.get("marker") != h or str(s.get("status", "")).startswith("started")
pnames, ppaths = BP.in_use()
import inuse  # noqa: E402  10 Nov (prune3h removed b1834's active diag bot): command lines, pilot items, stage manifests, nova-* units, recent dirs
INUSE = inuse.in_use_why(AGE, strict="--apply" in sys.argv)  # a source that fails stops an --apply run (no prune on a partial list)
ppaths = {os.path.realpath(p) for p in ppaths if p.startswith("/")}
names = set(os.listdir(STORE)) | {b for b in os.listdir(BOTS) if os.path.isdir(os.path.join(BOTS, b))}
def where(b):
    h = os.path.join(BOTS, b)
    if os.path.islink(h) or not os.path.exists(h): return os.path.realpath(h) if os.path.exists(h) else os.path.join(STORE, b)
    return h
def parents(b):
    out = set()
    for f in ("/FLIP", "/SHIPCHECK"):
        try: out |= set(re.findall(r"TRUNK[=: ]+(\S+)", open(where(b) + f, errors="ignore").read()))
        except OSError: pass
    return out
REPO_BOTS, STORE_BOTS = "/homes/zw4424/cambc/bots", "/data/zw4424/st/new/bots"


def _named_active():
    """bot names written in an agent's prereg.md touched in the last 24 h, or in a PENDING line of pending_reads.txt"""
    import glob as _g, re as _re
    txt = []
    for p in _g.glob("/data/zw4424/st/b*/prereg.md"):
        try:
            if time.time() - os.path.getmtime(p) < 86400:
                txt.append(open(p, errors="replace").read())
        except OSError:
            pass
    try:
        txt += [ln for ln in open("/data/zw4424/st/bq/pending_reads.txt", errors="replace") if ln.startswith("PENDING")]
    except OSError:
        pass
    return set(_re.findall(r"\bnova_[A-Za-z0-9_]+", "\n".join(txt)))


NAMED_ACTIVE = _named_active()
now = time.time(); keep = {}
for b in sorted(names):
    d = where(b); why = None
    if not b.startswith("nova_"): why = "not nova"
    elif b.startswith("nova_spar_") or b == "nova_b633_rythhp": why = "prefix"
    else:
        for k in ("shipped", "tools", "current", "latest"):
            if b in named[k]: why = k; break
    if not why and b in pnames: why = "running"
    if not why and b in INUSE: why = "inuse-" + INUSE[b]
    if not why and pending_marker(b, d): why = "marker"
    if not why:  # 10 Nov 23:10Z (Builder, b1834: 7 DKS flip bots and the VHG links went): keep_paths on the store dir OR the bots/ link
        for p in (d, os.path.realpath(d), os.path.join(REPO_BOTS, b), os.path.join(STORE_BOTS, b)):
            try:
                if keeplist.why(p): why = "keep_paths"; break
            except Exception: pass
    if not why and b in NAMED_ACTIVE: why = "named in a prereg or PENDING read"
    if not why and any(p == os.path.realpath(d) or p.startswith(os.path.realpath(d) + "/") for p in ppaths): why = "open"
    if not why:
        try:
            if now - BP.newest(d) < AGE * 3600: why = "recent"
        except OSError: pass
    if why: keep[b] = why
ch = True
while ch:  # flip parents of kept bots, transitively
    ch = False
    for b in list(keep):
        for p in parents(b):
            if p in names and p not in keep: keep[p] = "parent of " + b; ch = True
closed = sorted(names - set(keep))
from collections import Counter
print("bots", len(names), "keep", len(keep), Counter(v.split()[0] for v in keep.values()), "closed", len(closed))
out = "/data/zw4424/st/tb2/"; os.makedirs(out, exist_ok=True)
json.dump(dict(keep=keep, closed=closed), open(out + "closedbots.json", "w"), indent=0)
if "--apply" in sys.argv:
    nh = ns = 0
    for b in closed:
        h = os.path.join(BOTS, b); s = os.path.join(STORE, b)
        if os.path.islink(h): os.remove(h)
        elif os.path.isdir(h) and os.path.dirname(os.path.realpath(h)) == BOTS: shutil.rmtree(h); nh += 1
        if os.path.isdir(s) and not os.path.islink(s):
            subprocess.run(['chmod', '-R', 'u+w', s]); shutil.rmtree(s); ns += 1
    print("removed home dirs", nh, "store dirs", ns)
