#!/usr/bin/env python3
"""activations: when each of our platform versions was really ACTIVE (Tool Builder, 13 Nov).

Why: bq/live.txt stamps a version at UPLOAD, but the platform compiles first; v882 was uploaded 08:52:41Z and v881 stayed active until
08:56:15Z. Games created in that gap ran the OLD version. ladderclimb stamped a whole group with the version live when it was queued, so 3,045
of 23,495 climb games (13%) carried the wrong version (Aggression, 01a1d3c5-...-7fd6: labelled v876, played by v877).

Source: `submissions list --json` (paged with --before). An inactive submission's statusAt is the moment it stopped being active; sorting
those switch moments gives each version's active window [start, end): start = the previous switch, end = its own statusAt (the active one: end
open). A version that never compiled (status not active/inactive) gets no window. A rollback (an older version re-activated) keeps only its last
window (the platform reports one statusAt); such games print '?'-free but may be off: rare.

Cache: /data/USER/st/bq/activations.tsv (version, created, start, end), refreshed when older than ACT_MAX_AGE (600 s) and a lookup is newer than
the cached head. CLI: activations.py refresh [--from V] | at MATCH_ID... | show"""
import calendar
import json
import os
import re
import subprocess
import sys
import time
import uuid

CACHE = "/data/USER/st/bq/activations.tsv"
REPO = "/homes/USER/cambc"
CLI = "/data/USER/cambc400/bin/cambc400"
_T = None


def _ts(s):
    return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) + (float("0" + s[19:23]) if s[19:20] == "." else 0.0)


def _page(before=None):
    args = ["sh", f"{REPO}/tools/lab/platlock.sh", CLI, "submissions", "list", "--json"] + (["--before", str(before)] if before else [])
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=300)
    d = json.loads(r.stdout)
    return d.get("submissions") or [], bool(d.get("more"))


def refresh(stop_at=600):
    """Page back until version stop_at (or the cached oldest is reached and the head is known) and rewrite the cache."""
    subs = {}
    old = load(force_file=True)
    before = None
    while True:
        lst, more = _page(before)
        if not lst:
            break
        for s in lst:
            subs[int(s["version"])] = s
        lo = min(int(s["version"]) for s in lst)
        if not more or lo <= stop_at or (old and lo <= max(old)):
            break
        before = lo
    rows = {v: dict(created=r["created"], start=r["start"], end=r["end"], status=r.get("status", "")) for v, r in (old or {}).items()}
    for v, s in subs.items():
        rows[v] = dict(created=_ts(s["createdAt"]), status=s.get("status", ""), statusAt=_ts(s.get("statusAt") or s["createdAt"]), start=None, end=None)
    # windows from the switch moments
    sw = sorted((r["statusAt"], v) for v, r in rows.items() if r.get("status") == "inactive" and r.get("statusAt"))
    for v, r in rows.items():
        if "statusAt" not in r:
            continue  # an old cached row: keep its window
        if r["status"] == "inactive":
            r["end"] = r["statusAt"]
            prev = [t for t, _ in sw if t < r["statusAt"]]
            r["start"] = max(prev) if prev else r["created"]
            r["start"] = max(r["start"], r["created"])
        elif r["status"] == "active":
            r["start"] = max([t for t, _ in sw] + [r["created"]])
            r["end"] = None
    tmp = CACHE + f".new.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write("# version\tcreated\tstart\tend\tstatus  (UTC epoch s; end '-' = active now) tools/lab/activations.py\n")
        for v in sorted(rows):
            r = rows[v]
            if r.get("start") is None:
                continue
            end = "-" if r["end"] is None else "%.3f" % r["end"]
            f.write(f"{v}\t{r['created']:.3f}\t{r['start']:.3f}\t{end}\t{r.get('status', '')}\n")
    os.replace(tmp, CACHE)
    global _T
    _T = None
    return load()


def load(force_file=False):
    global _T
    if _T is not None and not force_file:
        return _T
    t = {}
    try:
        for ln in open(CACHE):
            if ln.startswith("#"):
                continue
            p = ln.rstrip("\n").split("\t")
            if len(p) >= 4:
                t[int(p[0])] = dict(created=float(p[1]), start=float(p[2]), end=None if p[3] == "-" else float(p[3]), status=p[4] if len(p) > 4 else "")
    except (OSError, ValueError):
        t = {}
    if not force_file:
        _T = t
    return t


def at_time(t, allow_refresh=True):
    """'vNNN' active at epoch t, or None."""
    tab = load()
    head = max((r["start"] for r in tab.values()), default=0)
    stale = not tab or (t > head and time.time() - os.path.getmtime(CACHE) > int(os.environ.get("ACT_MAX_AGE", 600)))
    if stale and allow_refresh:
        try:
            tab = refresh()
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    # 13 Nov: AMBIGUOUS between a version's upload and its switch moment. 01a1d3c5-...-7fd6 was created 07:18:18Z, finished 07:19:21Z, v877's
    # switch is recorded 07:19:13Z, and an exact puppet reproduced v877 (Aggression): the new build can serve before statusAt. None there.
    for v, r in tab.items():
        if r["created"] <= t < r["start"] and r["start"] - r["created"] <= int(os.environ.get("ACT_MAX_LAG", 900)):
            return None  # (a longer lag is a later re-activation: statusAt keeps only the last switch, the first is unknown)
    best = None
    for v, r in tab.items():
        if r["start"] <= t and (r["end"] is None or t < r["end"]):
            if best is None or r["start"] > tab[best]["start"]:
                best = v
    return f"v{best}" if best is not None else None


def at_match(mid, allow_refresh=True):
    try:
        return at_time((uuid.UUID(mid).int >> 80) / 1000.0, allow_refresh)
    except ValueError:
        return None


def main():
    a = sys.argv[1:]
    if a[:1] == ["refresh"]:
        stop = int(a[a.index("--from") + 1].lstrip("v")) if "--from" in a else 600
        t = refresh(stop)
        print(f"activations: {len(t)} versions in {CACHE}")
    elif a[:1] == ["at"]:
        for m in a[1:]:
            print(m, at_match(m))
    elif a[:1] == ["show"]:
        for v, r in sorted(load().items())[-15:]:
            print(v, time.strftime("%m-%dT%H:%M:%S", time.gmtime(r["start"])), "-" if r["end"] is None else time.strftime("%m-%dT%H:%M:%S", time.gmtime(r["end"])),
                  f"lag {r['start'] - r['created']:.0f} s")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
