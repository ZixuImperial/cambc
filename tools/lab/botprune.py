#!/usr/bin/env python3
"""botprune: list (and with --apply remove) old test bots in bots/ when the home file quota gets close. Tool builder, 1 Nov.

Owner 1 Nov: bots/ holds real dirs on /homes (60k files), about 59 files a bot, and old bots go when space runs short.
usage: python3 -I tools/lab/botprune.py [--high 50000] [--low 45000] [--apply]
Below --high it does nothing. At or above it, lists the oldest removable bots until home would reach --low; DRY unless --apply.
--apply needs the owner's OK: a bot not committed to git and not on maple04 cannot be restored.
Never removes: a symlink, a name outside nova_*, nova_trunk*, nova_spar_*, the anchor nova_b633_rythhp, a bot with a SHIPCHECK*
marker or a read-only src/, a FLIP parent of any kept bot, any bot changed in the last --age hours (default 24) or in use (a running
process names it or holds a path inside it), or a name found in tools/lab, CLAUDE.md, live.txt, best_model.txt, the
reports (trunk_registry, version_history, builder_queue, subagent_primer, submissions_log, board) or a prereg.md under /data/zw4424/st.
"""
import argparse
import glob
import os
import re
import shutil
import sys
import time

REPO = "/homes/zw4424/cambc"
BOTS = REPO + "/bots"
REPORTS = "/homes/zw4424/condor-work/reports"
TOK = re.compile(r"nova_[A-Za-z0-9_.+-]*[A-Za-z0-9_+]")
sys.path.insert(0, REPO + "/tools/lab")


def named(paths):
    """Bot names mentioned in these files."""
    out = set()
    for p in paths:
        try:
            if os.path.isfile(p) and os.path.getsize(p) < 20_000_000:
                out |= set(TOK.findall(open(p, errors="ignore").read()))
        except OSError:
            pass
    return out


def in_use():
    """(names on running command lines, real paths processes hold as cwd or open files)"""
    names, paths = set(), set()
    uid = os.getuid()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        d = "/proc/" + pid
        try:
            if os.stat(d).st_uid != uid:
                continue
            names |= set(TOK.findall(open(d + "/cmdline").read().replace("\0", " ")))
            paths.add(os.readlink(d + "/cwd"))
            for fd in os.listdir(d + "/fd"):
                paths.add(os.readlink(f"{d}/fd/{fd}"))
        except OSError:
            continue
    # our dirs only (7 Nov: two stray `find /` held 128k files open on /vol/bitbucket; closedprune's realpath of each, ~50 ms on NFS, outran autoclean's 1 h limit for 9 h)
    return names, {p for p in paths if p.startswith(("/homes/zw4424", "/data/zw4424"))}


def newest(d):
    """Newest file time under d, build caches included: a build means the bot is in use. 9 Nov (Builder, b1766): mtime OR ctime. newbot.sh's copy
    keeps the source's mtimes, so a bot made seconds ago read as hours old and the idea sweep retired it (08:48Z); a copy can't keep ctime."""
    st = os.lstat(d)
    t = max(st.st_mtime, st.st_ctime)
    for r, _, fs in os.walk(d):
        for f in fs:
            try:
                st = os.lstat(os.path.join(r, f))
                t = max(t, st.st_mtime, st.st_ctime)
            except OSError:
                pass
    return t


def nfiles(d):
    return 1 + sum(len(ds) + len(fs) for _, ds, fs in os.walk(d))


def candidates(age_h):
    keep = named([f for f in glob.glob(REPO + "/tools/lab/**", recursive=True) if "__pycache__" not in f]
                 + [REPO + "/CLAUDE.md", "/data/zw4424/st/bq/live.txt",
                    "/data/zw4424/st/bq/best_model.txt", REPORTS + "/trunk_registry.md", REPORTS + "/builder_queue.md",
                    REPORTS + "/subagent_primer.md", REPORTS + "/submissions_log.md", REPORTS + "/analysts/board.md"]
                 + glob.glob("/data/zw4424/st/*/prereg.md"))
    names, paths = in_use()
    entries = sorted(os.listdir(BOTS))
    for b in entries:  # FLIP parents of every bot: a flip is meaningless without its trunk
        try:
            keep |= set(re.findall(r"TRUNK[=: ]+(\S+)", open(f"{BOTS}/{b}/FLIP", errors="ignore").read()))
        except OSError:
            pass
    now, out = time.time(), []
    for b in entries:
        d = os.path.join(BOTS, b)
        if (not b.startswith("nova_") or os.path.islink(d) or not os.path.isdir(d) or b in keep or b in names
                or b.startswith(("nova_trunk", "nova_spar_")) or b == "nova_b633_rythhp"
                or glob.glob(d + "/SHIPCHECK*") or not os.access(d + "/src", os.W_OK)
                or any(p == d or p.startswith(d + "/") for p in paths)):
            continue
        t = newest(d)
        if now - t >= age_h * 3600:
            out.append((t, b, nfiles(d)))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--high", type=int, default=50000)
    ap.add_argument("--low", type=int, default=45000)
    ap.add_argument("--age", type=float, default=24)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    import homequota
    q = homequota.home_quota()
    if not q:
        sys.exit("botprune: cannot read the home quota")
    if q["files"] < a.high:
        print(f"home {q['files']} files < {a.high}: nothing to do")
        return
    cands, used, chosen = candidates(a.age), q["files"], []
    for c in cands:
        if used <= a.low:
            break
        chosen.append(c)
        used -= c[2]
    tag = "removing" if a.apply else "DRY, would remove"
    print(f"home {q['files']} files >= {a.high}; {len(cands)} removable; {tag} {len(chosen)} -> ~{used} files")
    for t, b, n in chosen:
        print(f"  {time.strftime('%m-%dT%H:%M', time.gmtime(t))} {n:5d} {b}")
    if used > a.low:
        print(f"ALARM: even so home stays above {a.low}: tell the owner")
    if a.apply:
        for t, b, n in chosen:
            d = os.path.join(BOTS, b)
            if os.path.dirname(os.path.realpath(d)) == BOTS and not os.path.islink(d):
                shutil.rmtree(d)
        print(f"removed {len(chosen)} bots")


if __name__ == "__main__":
    main()
