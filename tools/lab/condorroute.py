"""condorroute: the Condor environment for tools on a machine with no scheduler of its own (5 Nov, maple02: cqbatch and dgkit failed with
CEDAR:6001 because condor_q asked maple02, which has no schedd; pilotd worked because its unit carries the ash09 route).
env(base) -> base + Condor's bin on PATH, plus _CONDOR_SCHEDD_HOST/NAME from /data/zw4424/st/bq/pilotd.env when this machine runs no
condor_schedd and the caller set no route. On a machine with its own schedd, or with a route already set, nothing is added.
This stays per tool (CLAUDE.md §1: the route lives in tools' environments, never in ~/.condor/user_config)."""
import os

ROUTE = "/data/zw4424/st/bq/pilotd.env"


NO_LOCAL = "/data/zw4424/st/bq/no_local_schedd"  # 10 Nov (maple20): its own condor_schedd takes jobs that never run (ubaudit idle 2 x 300 s,
# cluster ids 4-7); with this file the route (bq/pilotd.env's schedd) is used even when a local schedd runs. Remove it on a host whose schedd works.


def local_schedd():
    if os.path.exists(NO_LOCAL):
        return False
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open(f"/proc/{p}/comm").read().strip() == "condor_schedd":
                    return True
            except OSError:
                pass
    return False


def env(base=None):
    e = dict(os.environ if base is None else base)
    if "/usr/local/condor/release/bin" not in e.get("PATH", ""):
        e["PATH"] = "/usr/local/condor/release/bin:" + e.get("PATH", "")
    if "_CONDOR_SCHEDD_HOST" not in e and not local_schedd():
        try:
            for ln in open(ROUTE):
                k, _, v = ln.strip().partition("=")
                if k in ("_CONDOR_SCHEDD_HOST", "_CONDOR_SCHEDD_NAME") and v:
                    e[k] = v
        except OSError:
            pass
    return e
