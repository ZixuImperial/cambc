#!/usr/bin/env python3
"""keeplist: paths no cleanup may delete (8 Nov: the plat prunes removed the live replays the Rule Checker's index of games v Fish,
Mite and SBG points at). One registry, honoured by tools/lab/rmdata.sh, quotaguard, idleprune and closedprune:
  /homes/zw4424/condor-work/keep_paths.txt (shared by every machine), one entry per line ('#' starts a comment; say who and why):
    /abs/path                 the path and everything under it
    index: /abs/file.json     the file itself and every /data/zw4424/... path written in it (an analyst's index of games)
A delete is refused when the target is kept, OR when a kept path lies under it (deleting its folder).
usage: python3 -I tools/lab/keeplist.py check PATH...      prints KEPT/free per path
       python3 -I tools/lab/keeplist.py --filter LISTFILE   free paths to stdout, refusals to stderr (rmdata.sh uses it)
       python3 -I tools/lab/keeplist.py list                every kept path"""
import os
import re
import sys

KEEP = os.environ.get("KEEP_PATHS", "/homes/zw4424/condor-work/keep_paths.txt")  # on /homes: rmdata --host on any machine reads it
PATH_RE = re.compile(r"/data/zw4424/[^\s\"'<>,;)\]}]+")
_cache = {"mt": None, "keys": []}


def keys():
    """sorted kept paths (absolute, no trailing /)"""
    try:
        mt = os.path.getmtime(KEEP)
    except OSError:
        return []
    if _cache["mt"] == mt:
        return _cache["keys"]
    out = set()
    import socket
    me = socket.gethostname().split(".")[0]
    for ln in open(KEEP, errors="replace"):
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        # 9 Nov: optional per-line host scope, `PATH hosts=maple14,maple18`: the path is kept only on those machines (old copies on other
        # hosts can go; Combat agreed for st/combat_py). No hosts= field: kept on every machine, as before.
        parts = ln.split()
        hs = [x[6:].split(",") for x in parts if x.startswith("hosts=")]
        if hs and me not in hs[0]:
            continue
        ln = " ".join(x for x in parts if not x.startswith("hosts="))
        if ln.startswith("index:"):
            f = ln[6:].strip()
            out.add(os.path.normpath(f))
            try:
                for m in PATH_RE.findall(open(f, errors="replace").read()):
                    out.add(os.path.normpath(m))
            except OSError:
                pass
        else:
            out.add(os.path.normpath(ln))
    _cache.update(mt=mt, keys=sorted(out))
    return _cache["keys"]


def why(p):
    """the kept path that protects P (P under it, or it under P), or None"""
    p = os.path.normpath(os.path.abspath(str(p)))
    for k in keys():
        if p == k or p.startswith(k + "/") or k.startswith(p + "/"):
            return k
    return None


def is_kept(p):
    return why(p) is not None


def guard(module_os, module_shutil):
    """route a cleanup tool's os.remove / os.unlink / shutil.rmtree through the keep-list (a kept path is skipped, with a note)"""
    rm, ul, rt = module_os.remove, module_os.unlink, module_shutil.rmtree

    def _skip(p, fn, *a, **k):
        w = why(p)
        if w:
            print(f"keeplist: kept, not deleted: {p} (keep_paths.txt: {w})", file=sys.stderr)
            return None
        return fn(p, *a, **k)
    module_os.remove = lambda p, *a, **k: _skip(p, rm, *a, **k)
    module_os.unlink = lambda p, *a, **k: _skip(p, ul, *a, **k)
    module_shutil.rmtree = lambda p, *a, **k: _skip(p, rt, *a, **k)


BOT_RE = re.compile(r"^(?:/data/zw4424/st/new/bots|/homes/zw4424/cambc/bots)/(nova_[A-Za-z0-9_.+-]+)/?$")
INUSE_AGE_H = float(os.environ.get("RMDATA_BOT_MIN_AGE_H", "3"))


def inuse_bots():
    """10 Nov 23:2xZ (owner: "make sure these mistakes don't happen again"): prune3h's closedprune deleted bots of RUNNING shipchecks
    (chf227, sta7). Every bot delete through rmdata now refuses a bot that is in use: named in any process's command line or cwd, has a live
    SHIPCHECK marker, is a marker's TRUNK=, is named in armq.txt / fixbatch / pilot queue items, or was touched (dir or src) in the last
    RMDATA_BOT_MIN_AGE_H (3) hours. -> {bot name: reason}"""
    use = {}
    names = re.compile(r"nova_[A-Za-z0-9_.+-]+")
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            c = open(f"/proc/{p}/cmdline", "rb").read().decode("utf-8", "replace").replace("\0", " ")
            c += " " + os.readlink(f"/proc/{p}/cwd")
        except OSError:
            continue
        for n in names.findall(c):
            use.setdefault(n, "running process")
    bd = "/homes/zw4424/cambc/bots"
    try:  # 12 Nov ~22:2xZ (TB, owner-OK'd guarded bots/ link prune): a marker shipwatch ended or skipped > 6 h ago is no longer live
        import json as _json
        _sw = _json.load(open("/data/zw4424/st/bq/shipwatch_state.json"))
    except (OSError, ValueError):
        _sw = {}
    _old = lambda n: (isinstance(_sw.get(n), dict) and str(_sw[n].get("status", "")).startswith(("ended", "skipped"))  # noqa: E731
                      and __import__("time").time() - float(_sw[n].get("at", 0)) > 3 * 3600)
    try:
        for n in os.listdir(bd):
            mk = os.path.join(bd, n, "SHIPCHECK")
            if os.path.exists(mk) and not _old(n):
                use.setdefault(n, "live SHIPCHECK marker")
                try:
                    for ln in open(mk, errors="replace"):
                        if ln.startswith("TRUNK="):
                            use.setdefault(ln.split("=", 1)[1].strip(), "TRUNK of a marker")
                except OSError:
                    pass
    except OSError:
        pass
    # 11 Nov (bk754: 23 of 32 arms were deleted at 16:18 while queued, so they 'ended rc 0' with no games): every bot of a flagscreen
    # whose run has not finished (no "all arms ended" in its log) -- its arms, trunk and idea bots from design.json -- is in use
    import glob as _g
    for dj in _g.glob("/data/zw4424/st/fs/*/design.json"):
        try:
            lg = os.path.join(os.path.dirname(dj), "log")
            if os.path.exists(lg) and "all arms ended" in open(lg, errors="replace").read()[-4000:]:
                continue
            import time as _t
            if _t.time() - max(os.path.getmtime(p) for p in (dj, lg) if os.path.exists(p)) > 24 * 3600:
                continue  # an abandoned screen (no progress for a day) keeps nothing
            for n in names.findall(open(dj, errors="replace").read()):
                use.setdefault(n, "running flagscreen " + os.path.basename(os.path.dirname(dj)))
        except OSError:
            pass
    for fn in ("/data/zw4424/st/bq/armq.txt", "/data/zw4424/st/bq/fixbatch.tsv", "/data/zw4424/st/bq/train.tsv"):
        try:
            for n in names.findall(open(fn, errors="replace").read()):
                use.setdefault(n, os.path.basename(fn))
        except OSError:
            pass
    return use


def bot_young(n):
    import time
    for d in (f"/data/zw4424/st/new/bots/{n}", f"/data/zw4424/st/new/bots/{n}/src", f"/homes/zw4424/cambc/bots/{n}"):
        try:
            # 11 Nov (Builder/b1827: nova_b1827_geh deleted 3 min after newbot.sh): a copy made with preserved times keeps its base's old
            # mtime, so the newest of mtime and ctime (dir and link) counts; ctime is the copy's own creation
            ss = [os.stat(d)] + ([os.lstat(d)] if os.path.islink(d) else [])
            if time.time() - max(max(x.st_mtime, x.st_ctime) for x in ss) < INUSE_AGE_H * 3600:
                return True
        except OSError:
            pass
    return False


def main():
    a = sys.argv[1:]
    if a[:1] == ["--filter"] and len(a) == 2:
        use = None
        for ln in open(a[1], errors="replace"):
            p = ln.strip()
            if not p:
                continue
            q = p if p.startswith("/") else "/data/zw4424/" + p
            w = why(q)
            if w:
                print(f"rmdata: refused (keep-list: {w}): {p}", file=sys.stderr)
                continue
            m = BOT_RE.match(q.rstrip("/") + "/") or BOT_RE.match(q)
            if m and os.environ.get("RMDATA_BOT_FORCE") != "1":
                if use is None:
                    use = inuse_bots()
                n = m.group(1)
                if n in use:
                    print(f"rmdata: refused (bot in use: {use[n]}): {p}", file=sys.stderr)
                    continue
                if bot_young(n):
                    print(f"rmdata: refused (bot touched < {INUSE_AGE_H:g} h ago): {p}", file=sys.stderr)
                    continue
            print(p)
        return 0
    if a[:1] == ["check"]:
        for p in a[1:]:
            w = why(p)
            print(f"{'KEPT' if w else 'free'} {p}" + (f" ({w})" if w else ""))
        return 0
    if a[:1] == ["list"]:
        print("\n".join(keys()))
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
