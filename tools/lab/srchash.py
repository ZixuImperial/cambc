#!/usr/bin/env python3
"""srchash: a bot's source hash without spawning processes. Tool builder, 3 Nov (owner: reduce /var build-up; every exec on this machine is audited into
/var/log/syslog at ~1.5-2.5 KB, and the shell form below cost ~6 processes per call, for every bot on every leg).
Byte-identical to:  cd BOT && find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12   (the key of the game index). Anything the shell form
would treat specially (no files, a name needing sha1sum's escaping) falls back to that shell form.
usage: python3 -I tools/lab/srchash.py BOTDIR"""
import hashlib
import os
import subprocess
import sys

SHELL = "find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12"


def shell_hash(d):
    return subprocess.run(SHELL, shell=True, cwd=d, capture_output=True, text=True).stdout.strip()


def src_hash(d):
    """12 hex digits, or '' when BOT has no src dir (as the shell form prints a hash of nothing only with an empty src: that case goes to the shell)."""
    top = os.path.join(d, "src")
    if not os.path.isdir(top) or os.path.islink(top):  # find does not descend into a symlink given without a slash
        return shell_hash(d)
    names = []
    for root, dirs, files in os.walk(top):  # followlinks False, like find
        rel = os.path.relpath(root, d)
        for f in files:
            p = os.path.join(root, f)
            if not os.path.islink(p) and os.path.isfile(p):
                names.append(os.path.join(rel, f))
    if not names or any(c in n for n in names for c in "\\\n '\"\t"):
        return shell_hash(d)  # xargs splits on spaces and quotes, sha1sum escapes backslashes and newlines
    names = sorted(names, key=os.fsencode)
    out = hashlib.sha1()
    for n in names:
        h = hashlib.sha1()
        with open(os.path.join(d, n), "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        out.update(f"{h.hexdigest()}  {n}\n".encode())
    return out.hexdigest()[:12]


if __name__ == "__main__":
    print(src_hash(sys.argv[1]))
