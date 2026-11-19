#!/usr/bin/env python3
"""homequota: the home directory's own quota line. Tool builder, 1 Nov ~22:40Z.

`quota -s` prints one block per NFS server with a home mounted on this machine (other users' automounted homes add
blocks, e.g. erne's for /homes/aj2322 on maple05), and the LAST block is not necessarily ours: on maple05 it was erne's
stale 60,783 files while $HOME on kiwi held 37,936, so quotaguard and condab's preflight read the wrong server. This picks
the block of the server that `df` names for $HOME (the "kiwi.doc.ic.ac.uk." part of kiwi.doc.ic.ac.uk.:/export/...).

usage: python3 -I tools/lab/homequota.py   ->  "FILES FILES_SOFT FILES_HARD MB MB_SOFT" (one line; empty when unreadable)
API:   home_quota() -> dict(files, files_soft, files_hard, mb, mb_soft) or None"""
import os
import re
import subprocess

UNIT_MB = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1048576}


def home_server():
    out = subprocess.run(["df", "-P", os.path.expanduser("~")], capture_output=True, text=True).stdout.splitlines()
    src = out[-1].split()[0] if len(out) > 1 else ""
    return src.split(":")[0] if ":" in src else None


def home_quota():
    """Fields are classified by shape, since a '*' and a grace column appear when a soft limit is passed: sizes end in
    K/M/G/T, file counts are bare integers, grace periods hold letters or ':'."""
    out = subprocess.run(["quota", "-s", "-w"], capture_output=True, text=True).stdout.splitlines()
    srv = home_server()
    rows = [ln.split() for ln in out if ln.strip() and ":" in ln.split()[0]]
    row = next((r for r in rows if srv and r[0].split(":")[0] == srv), None)
    if row is None and len(rows) == 1:
        row = rows[0]
    if row is None:
        return None
    vals = [x.rstrip("*") for x in row[1:]]
    sz = [float(x[:-1]) * UNIT_MB[x[-1]] for x in vals if re.fullmatch(r"[0-9.]+[KMGT]", x)]
    n = [int(x) for x in vals if re.fullmatch(r"[0-9]+", x)]
    if len(sz) < 2 or len(n) < 3:
        return None
    return dict(files=n[0], files_soft=n[1], files_hard=n[2], mb=round(sz[0]), mb_soft=round(sz[1]))


if __name__ == "__main__":
    q = home_quota()
    print(f"{q['files']} {q['files_soft']} {q['files_hard']} {q['mb']} {q['mb_soft']}" if q else "")
