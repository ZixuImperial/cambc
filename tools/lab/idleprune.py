#!/usr/bin/env python3
"""idleprune: remove old run data from IDLE agent dirs /data/USER/st/bNNN* (Tool builder 2, 4 Nov; owner: 'delete all unnecessary
files', confirmed for run data of closed agent work). An agent dir is idle when nothing in it changed for 24 h, it is not named in
pending_reads.txt and no process uses it. Removes per-game results (fm_*, A__B__seat names, st/ and rep/ dirs), maps, replays,
stdout/logs and dumps over 256 KB; keeps .md .py .sh .csv .tsv, prereg/README, py/ and tools/, and small summaries.
7 Nov (owner: delete all unnecessary files): a pending line counts only while it is open (pending.py state: a finished or marked line no longer
holds a dir for ever); bh*/fx* agent dirs get the same rule; dr* and closeread dirs lose replays only, after 48 h idle. Those and the
bh*/fx* dirs are skipped while a note changed in the last 36 h names their path (autoclean.recent_mentions).
usage: python3 -I tools/lab/idleprune.py [--apply]   (DRY by default)"""
import os, glob, time, re, sys
now = time.time(); APPLY = "--apply" in sys.argv
IDLE_H = float(os.environ.get("IDLEPRUNE_H", "24"))  # 8 Nov (owner: remove all that is not in use): the idle window, hours (dr*/closeread: twice)
KEEP = [k for k in os.environ.get("IDLEPRUNE_KEEP", "").split(",") if k]  # agent dir prefixes never pruned (running agents)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pending as pdg  # noqa: E402
import shutil
sys.path.insert(0, "/homes/USER/cambc/tools/lab")
import keeplist  # noqa: E402  8 Nov: kept paths (condor-work/keep_paths.txt) are never deleted
keeplist.guard(os, shutil)
_mk, _procs = pdg.marked(), pdg.cmdlines()
pend = "\n".join(x for i, x in pdg.lines() if re.search(r"\bHOLD|\bHELD", x) or (i not in _mk and pdg.state(x, _procs)[0] != "DONE"))
busy = set()
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        busy.add(os.readlink(f"/proc/{pid}/cwd"))
        for fd in os.listdir(f"/proc/{pid}/fd"): busy.add(os.readlink(f"/proc/{pid}/fd/{fd}"))
        busy |= set(re.findall(r"/data/USER/st/b\d+\w*", open(f"/proc/{pid}/cmdline").read().replace("\0", " ")))
    except OSError: pass
import inuse  # noqa: E402  10 Nov: an agent whose bots are in use (process, pilot item, stage manifest, nova-* unit) is not idle
INUSE_AG = {m.group(1) for b, k in inuse.in_use_why(IDLE_H, strict=APPLY).items() if k != "recent"
            for m in [re.match(r"nova_(?:dgfc_|dg_|ft_)?(b\d+)", b)] if m}
KEEPX = {".md", ".py", ".sh", ".csv", ".tsv"}
DROPX = {".repl26a", ".map26a", ".stdout", ".stderr", ".bin", ".tgz", ".zip", ".gz", ".wasm", ".obj", ".jsonl", ".json", ".txt", ".log", ".out", ".err"}
tot = nf = nd = 0
ST = "/data/USER/st/"
ment = None
for d in sorted(glob.glob(ST + "b[0-9]*") + glob.glob(ST + "bh[0-9]*") + glob.glob(ST + "fx*") + glob.glob(ST + "dr[0-9]*") + [ST + "closeread"]):
    if not os.path.isdir(d) or os.path.islink(d): continue
    name = os.path.basename(d)
    plain = re.fullmatch(r"b\d+\w*", name) is not None  # the bNNN dirs the owner confirmed on 4 Nov
    light = name.startswith("dr") or name == "closeread"  # analysts' dirs: replays only
    if re.search(rf"\b{re.escape(name)}\b", pend) or any(p == d or p.startswith(d + "/") for p in busy): continue
    if any(name == k or name.startswith(k) for k in KEEP): continue
    if re.match(r"b\d+", name) and re.match(r"b\d+", name).group(0) in INUSE_AG: continue  # 10 Nov: its bots are in use  # 8 Nov: running agents named by the Builder (IDLEPRUNE_KEEP)
    files, newest = [], 0
    for r, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(r, f)
            try: s = os.lstat(p)
            except OSError: continue
            newest = max(newest, s.st_mtime); files.append((p, s.st_size))
    if now - newest < (2 if light else 1) * IDLE_H * 3600: continue
    if not plain:
        if ment is None:
            import autoclean
            ment = autoclean.recent_mentions()
        if f"st/{name}/" in ment: continue
    nd += 1
    for p, sz in files:
        rel = p[len(d) + 1:]; x = os.path.splitext(p)[1].lower()
        if light and x != ".repl26a": continue
        if x in KEEPX or rel.startswith(("py/", "tools/")) or os.path.basename(p).startswith(("prereg", "README")): continue
        if x not in DROPX: continue
        bn = os.path.basename(p)
        pergame = bn.startswith("fm_") or "__" in bn or "/st/" in "/" + rel or "/rep/" in "/" + rel
        if x in (".json", ".txt", ".log", ".out", ".err") and sz <= 256 * 1024 and not pergame: continue
        tot += sz; nf += 1
        if APPLY:
            try: os.remove(p)
            except OSError: pass
print(f"{'removed' if APPLY else 'DRY would remove'} {nf} files, {tot/1e9:.1f} GB from {nd} idle agent dirs")
