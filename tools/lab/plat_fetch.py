#!/usr/bin/env python3
"""Fetch live match replays once for every analyser: reuse any copy already on disk, else download it under platlock.

usage: sh tools/lab/plat_fetch.sh ID|IDFILE... [--dest DIR] [--summary]
  ID      a match id (a unique prefix of 8+ characters is enough to find an existing copy; a download needs the full id)
  IDFILE  a file of ids (first token of each line; blank lines and # comments skipped)
  --dest DIR  where downloads go (default /data/zw4424/plat/shared): DIR/<id>.zip and DIR/x_<id>/ (replay.repl26a and the
              team-[ab] logs; no other zip member is extracted: downloads are untrusted)
  --summary   also make sure the match's statistics JSON (`matches summary ID --json`) sits next to the replay's set
              dir as <id>.json, the plat layout replay.py reads
Prints one replay path per id on stdout, in input order; problems go to stderr and the exit code is 1 if any id failed.
An existing copy is looked up, with no platform call, in: the register /data/zw4424/plat/downloads.tsv (matchId, path,
downloaded_by, utc), /data/zw4424/plat/*/x_<id>*/replay.repl26a and /data/zw4424/scout2 (two levels). Each download is
appended to the register under a lock, by $CAMBC_WHO (else $USER). Platform calls go through tools/lab/platlock.sh, one
at a time machine-wide; 429 waits as long as the server asks, 409/5xx and timeouts retry with a growing pause.
"""
import fcntl
import glob
import json
import os
import re
import subprocess
import sys
import time
import zipfile

PLAT = "/data/zw4424/plat"
SCOUT = "/data/zw4424/scout2"
REG = os.path.join(PLAT, "downloads.tsv")
CLI = "/data/zw4424/cambc400/bin/cambc400"
PLATLOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platlock.sh")
MEMBER = re.compile(r"^(replay\.repl26a|team-[ab]\.(stdout|debug|fuel))$")
FULL_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def err(msg):
    print(f"plat_fetch: {msg}", file=sys.stderr, flush=True)


def register_rows():
    try:
        with open(REG) as f:
            return [line.rstrip("\n").split("\t") for line in f if line.strip() and not line.startswith("matchId")]
    except OSError:
        return []


def find_local(mid):
    """An existing replay of match mid (a full id or a prefix of 8+ characters), or None."""
    for row in register_rows():
        if len(row) >= 2 and row[0].startswith(mid) and os.path.isfile(row[1]):
            return row[1]
    pats = [os.path.join(PLAT, "*", f"x_{mid}*", "replay.repl26a"), os.path.join(SCOUT, "*", f"x_{mid}*", "replay.repl26a"),
            os.path.join(SCOUT, "*", "*", f"x_{mid}*", "replay.repl26a")]
    hits = sorted(p for pat in pats for p in glob.glob(pat))
    return hits[0] if hits else None


def platform(args, out, tries=8):
    """One CLI call writing `out` (via a .part file and the caller's check); True when the call succeeded."""
    for i in range(1, tries + 1):
        tmp = out + ".part"
        if os.path.exists(tmp):
            os.remove(tmp)
        r = subprocess.run(["sh", PLATLOCK, "timeout", "300", CLI] + args + ["-o", tmp], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            return tmp
        msg = (r.stderr + r.stdout).strip().replace("\n", " ")[:300]
        err(f"{' '.join(args)}: try {i} failed (exit {r.returncode}): {msg}")
        m = re.search(r"retry after (\d+)", msg, re.I)
        if m or re.search(r"\b429\b|rate", msg, re.I):
            wait = int(m.group(1)) + 1 if m else 60
        elif re.search(r"\b404\b|not found", msg, re.I):
            return None
        else:
            wait = 5 * i
        time.sleep(max(wait, 3 * i))
    return None


def extract(zpath, xdir):
    """Unpack the whitelisted members of a match bundle into xdir; True when a replay came out."""
    with zipfile.ZipFile(zpath) as z:
        if z.testzip() is not None:
            return False
        names = [n for n in z.namelist() if MEMBER.match(n)]
        if "replay.repl26a" not in names:
            return False
        os.makedirs(xdir, exist_ok=True)
        for n in names:
            dst = os.path.join(xdir, n)
            with open(dst + ".part", "wb") as f:
                f.write(z.read(n))
            os.replace(dst + ".part", dst)
    return True


def register(mid, path):
    who = os.environ.get("CAMBC_WHO") or os.environ.get("USER", "?")
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(REG, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if f.tell() == 0:
            f.write("matchId\tpath\tdownloaded_by\tutc\n")
        f.write(f"{mid}\t{path}\t{who}\t{utc}\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def download(mid, dest):
    os.makedirs(dest, exist_ok=True)
    zpath = os.path.join(dest, mid + ".zip")
    if not (os.path.isfile(zpath) and zipfile.is_zipfile(zpath)):
        tmp = platform(["matches", "download", mid], zpath)
        if not tmp:
            return None
        if not zipfile.is_zipfile(tmp):
            err(f"{mid}: the download is not a zip bundle")
            os.remove(tmp)
            return None
        os.replace(tmp, zpath)
    xdir = os.path.join(dest, "x_" + mid)
    if not extract(zpath, xdir):
        err(f"{mid}: the bundle has no readable replay.repl26a")
        return None
    path = os.path.join(xdir, "replay.repl26a")
    register(mid, path)
    return path


def ensure_summary(mid, replay):
    full = os.path.basename(os.path.dirname(replay))[2:]
    out = os.path.join(os.path.dirname(os.path.dirname(replay)), full + ".json")
    if os.path.isfile(out):
        return
    tmp = platform(["matches", "summary", full, "--json"], out)
    if not tmp:
        err(f"{full}: no summary")
        return
    try:
        json.load(open(tmp))
        os.replace(tmp, out)
    except ValueError:
        err(f"{full}: the summary is not JSON")
        os.remove(tmp)


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if a else 1)
    dest, want_summary, ids = os.path.join(PLAT, "shared"), False, []
    i = 0
    while i < len(a):
        if a[i] == "--dest" and i + 1 < len(a):
            dest = os.path.abspath(a[i + 1])
            i += 2
            continue
        if a[i] == "--summary":
            want_summary = True
        elif os.path.isfile(a[i]):
            ids += [ln.split()[0] for ln in open(a[i]) if ln.strip() and not ln.lstrip().startswith("#")]
        else:
            ids.append(a[i])
        i += 1
    bad = 0
    for mid in ids:
        mid = mid.strip().lower()
        if mid.startswith("x_"):
            mid = mid[2:]
        if len(mid) < 8 or not re.fullmatch(r"[0-9a-f-]+", mid):
            err(f"{mid!r}: not a match id")
            bad += 1
            continue
        path = find_local(mid)
        if path is None:
            if not FULL_ID.match(mid):
                err(f"{mid}: no copy on disk, and a download needs the full match id")
                bad += 1
                continue
            path = download(mid, dest)
            if float(os.environ.get("PLAT_FETCH_GAP", "0") or 0) > 0:  # 10 Nov (Coordinator: bulk back-fill, a gap between platform downloads)
                time.sleep(float(os.environ["PLAT_FETCH_GAP"]))
        if path is None:
            bad += 1
            continue
        if want_summary:
            ensure_summary(mid, path)
        print(path, flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
