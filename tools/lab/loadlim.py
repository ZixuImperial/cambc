#!/usr/bin/env python3
"""loadlim: one place for the machine's load limits (Tool Builder, 10 Nov; owner: "allow the load to go up and make sure to keep the load safe").

Limits live in /data/USER/st/bq/load_limits, one `key value` per line (# comments allowed), read on every call, so a change
needs no restart. An environment variable of the same name in upper case still wins (e.g. LOAD_MAX=40 for one run).
Keys and defaults (16-core HOST; the 4 Nov crash was at load 48 with no CPU weights, see loadguard.py for what protects VS Code now):
  load_max            48   shipwatch: no new shipcheck above this local 1-min load (was 2 x nproc = 32)
  load_max_remote     64   shipwatch, while >= 4 Condor pilots run the games (was 48)
  cxe_build_load      40   tools/cxe/cxebuild.py: no new local build above this (was 32)
  cxe_build_load_hi   34   cxebuild: build slots past 8 only below this (was 28)
  pause_load          64   loadguard: pause the deferrable units (climbs, freshpool, triage, critgame...) above this AND cpu pressure
  hold_load           96   loadguard: also pause the build-agent units (nova-b1*) above this AND cpu pressure
  pause_psi           60   loadguard: cpu pressure (/proc/pressure/cpu some avg10, %) that must hold too: load alone overstates use here
  resume_load         44   loadguard: resume once the load is under this and the pressure under half pause_psi for 60 s
usage: python3 -I tools/lab/loadlim.py            (prints the limits in force)"""
import os
import sys

FILE = "/data/USER/st/bq/load_limits"
DEFAULTS = {"load_max": 48, "load_max_remote": 64, "cxe_build_load": 40, "cxe_build_load_hi": 34,
            "pause_load": 64, "hold_load": 96, "pause_psi": 60, "resume_load": 44, "resume_psi": 50}


def _file():
    out = {}
    try:
        for ln in open(FILE):
            p = ln.split("#", 1)[0].split()
            if len(p) >= 2:
                try:
                    out[p[0]] = float(p[1])
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def get(key, default=None):
    e = os.environ.get(key.upper())
    if e:
        try:
            return float(e)
        except ValueError:
            pass
    v = _file().get(key)
    if v is not None:
        return v
    return float(DEFAULTS.get(key, default if default is not None else 0))


if __name__ == "__main__":
    f = _file()
    for k in DEFAULTS:
        src = "env" if os.environ.get(k.upper()) else "file" if k in f else "default"
        print(f"{k:18} {get(k):g}  ({src})")
    sys.exit(0)
