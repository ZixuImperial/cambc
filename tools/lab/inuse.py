#!/usr/bin/env python3
"""inuse: bots in use right now; the prune tools never remove one (Tool Builder, 10 Nov: prune3h's closedprune removed an ACTIVE diag bot
of b1834 while its legs sat in the pilot queue). A bot is in use when its name appears in:
  - a running process's command line (any of our processes on this host);
  - a queued or claimed pilot item (condor-runs/pilotq/{queue,claimed}: the item JSON and the files its args name, e.g. parts.txt);
  - a stage dir's manifests or job scripts (condor-runs/stage/*/manifest_*.txt, cf_*/jobs.sh, ...) touched in the last STAGE_H hours;
  - an active nova-* systemd user unit's ExecStart;
  - or its bots/NAME or /data/zw4424/st/new/bots/NAME (the dir or any file in it) changed within age_h hours (mtime or ctime).
usage: python3 -I tools/lab/inuse.py [AGE_H]   (prints each in-use bot and why)"""
import glob
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
BOTS = REPO + "/bots"
STORE = "/data/zw4424/st/new/bots"
PILOTQ = os.environ.get("PILOT_QDIR", "/homes/zw4424/condor-runs/pilotq")
STAGE = "/homes/zw4424/condor-runs/stage"
STAGE_H = float(os.environ.get("INUSE_STAGE_H", "24"))  # a stage dir untouched this long belongs to a finished batch
TOK = re.compile(r"nova_[A-Za-z0-9_.+-]*[A-Za-z0-9_+]")
BOTREF = re.compile(r"(?:^|[/\s=:])bots/([A-Za-z0-9_.+-]+)")
MAXF = 5_000_000


def _names(text):
    return set(TOK.findall(text)) | set(BOTREF.findall(text))


def _read(p):
    try:
        if os.path.isfile(p) and os.path.getsize(p) < MAXF:
            return open(p, errors="ignore").read()
    except OSError:
        pass
    return ""


def from_procs():
    out = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            out |= _names(open(f"/proc/{pid}/cmdline", errors="ignore").read().replace("\0", " "))
        except OSError:
            continue
    return out


def from_pilotq():
    out, seen = set(), set()
    for sub in ("queue", "claimed"):
        for n in os.listdir(os.path.join(PILOTQ, sub)) if os.path.isdir(os.path.join(PILOTQ, sub)) else []:
            t = _read(os.path.join(PILOTQ, sub, n))
            out |= _names(t)
            try:
                it = json.loads(t)
            except ValueError:
                continue
            for a in it.get("args", []) if isinstance(it, dict) else []:
                p = str(a).split(":")[0]
                if p.startswith("/") and p not in seen and os.path.isfile(p):
                    seen.add(p)
                    out |= _names(_read(p))
    return out


def from_stage():
    out, cut = set(), time.time() - STAGE_H * 3600
    for d in glob.glob(STAGE + "/*"):
        try:
            if not os.path.isdir(d) or os.path.getmtime(d) < cut:
                continue
        except OSError:
            continue
        for p in glob.glob(d + "/manifest_*.txt") + glob.glob(d + "/*.sh") + glob.glob(d + "/*.cmds") + glob.glob(d + "/*.txt"):
            out |= _names(_read(p))
    return out


def from_units():
    out = set()
    try:
        r = subprocess.run(["systemctl", "--user", "list-units", "nova-*", "--state=active,activating,reloading", "--no-legend", "--plain"],
                           capture_output=True, text=True, timeout=30)
        units = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
        if units:
            r = subprocess.run(["systemctl", "--user", "show", "-p", "ExecStart"] + units, capture_output=True, text=True, timeout=60)
            out |= _names(r.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def _newest(d):
    st = os.lstat(d)
    t = max(st.st_mtime, st.st_ctime)
    for r, _, fs in os.walk(d):
        for f in fs:
            try:
                s = os.lstat(os.path.join(r, f))
                t = max(t, s.st_mtime, s.st_ctime)
            except OSError:
                pass
    return t


def recent(age_h):
    out, cut = set(), time.time() - age_h * 3600
    for base in (BOTS, STORE):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for b in names:
            p = os.path.join(base, b)
            try:
                if os.lstat(p).st_mtime > cut or os.lstat(p).st_ctime > cut:
                    out.add(b)
                elif os.path.isdir(p) and not os.path.islink(p) and _newest(p) > cut:
                    out.add(b)
            except OSError:
                continue
    return out


def from_records():
    """10 Nov ~23:30Z (Builder + TB 6ad907: bots of running checks and b1834's DKS/VHG flips were deleted at 23:10Z): bots named by any
    SHIPCHECK marker touched in 24 h (and its TRUNK=), any waiting armq line, any prereg.md touched in 24 h, any PENDING read line, and
    any bot whose bots/ link or store dir is on keep_paths.txt."""
    import glob as _g
    names, cut = set(), time.time() - 86400
    for m in _g.glob(os.path.join(BOTS, "*", "SHIPCHECK*")):
        try:
            if os.path.getmtime(m) > cut:
                names.add(os.path.basename(os.path.dirname(m)))
                names |= _names(_read(m))
        except OSError:
            pass
    names |= _names(_read("/data/zw4424/st/bq/armq.txt"))
    for p in _g.glob("/data/zw4424/st/b*/prereg.md"):
        try:
            if os.path.getmtime(p) > cut:
                names |= _names(_read(p))
        except OSError:
            pass
    try:
        names |= _names("".join(ln for ln in open("/data/zw4424/st/bq/pending_reads.txt", errors="ignore") if ln.startswith("PENDING")))
    except OSError:
        pass
    try:
        for ln in open("/homes/zw4424/condor-work/keep_paths.txt", errors="ignore"):
            p = ln.split("#")[0].strip()
            if "/bots/" in p:
                names.add(os.path.basename(p.rstrip("/")))
    except OSError:
        pass
    return names


def in_use_why(age_h=3.0, strict=False):
    """{bot name: first reason}. Names are bot-name tokens; the caller matches them against its own candidates.
    strict: a source that fails raises (a deleting caller stops rather than prune on a partial list)."""
    why = {}
    for k, f in (("process", from_procs), ("pilotq", from_pilotq), ("stage", from_stage), ("unit", from_units), ("record", from_records),
                 ("recent", lambda: recent(age_h))):
        try:
            got = f()
        except Exception:  # noqa: BLE001
            if strict:
                raise
            got = set()
        for b in got:
            why.setdefault(b, k)
    return why


def in_use_bots(age_h=3.0, strict=False):
    return set(in_use_why(age_h, strict))


if __name__ == "__main__":
    a = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    w = in_use_why(a)
    from collections import Counter
    print(len(w), "in use:", dict(Counter(w.values())))
    for b in sorted(w):
        if b.startswith("nova_"):
            print(w[b], b)
