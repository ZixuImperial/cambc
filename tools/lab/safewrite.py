"""Shared guard for lab tools that write output files: refuse to write over a map.

usage (in a tool):  import safewrite; safewrite.check_out(path)   # exits with a message if path is unsafe
On 29 Oct 22:02 a mistyped `mapfeat.py --json MAP` wrote "[]" over work301/maps/00ambush.map26a, which ~45 project dirs
reach through symlinks, and broke every test using that map for 18 minutes. check_out refuses an output path that
  - ends in .map26a,
  - resolves (through symlinks) into a directory named maps,
  - or already exists and starts like a map26a file.
"""
import os
import sys


def unsafe_reason(path):
    """Why writing to path would be unsafe, or None."""
    p = str(path)
    if p.endswith(".map26a"):
        return "it ends in .map26a"
    real = os.path.realpath(p)
    parts = os.path.normpath(os.path.dirname(real)).split(os.sep)
    if "maps" in parts:
        return f"it resolves into a maps/ directory ({os.path.dirname(real)})"
    if os.path.isfile(real):
        try:
            with open(real, "rb") as f:
                head = f.read(8)
        except OSError:
            head = b""
        if head[:6] == b"w62pam":  # map26a.py's magic
            return "it is an existing map file"
    return None


def check_out(path, tool=None):
    """Exit with a message if path is an unsafe output target; return path otherwise."""
    why = unsafe_reason(path)
    if why:
        sys.exit(f"{tool or os.path.basename(sys.argv[0])}: refusing to write {path}: {why} (output paths must not be maps)")
    return path
