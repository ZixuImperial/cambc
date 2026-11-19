#!/usr/bin/env python3
"""donorbase.py - normalise DONOR:BASE specs (Tool Builder, 10 Nov, b1823).

newbot.sh copies the baked base (bq/diffbase.txt, e.g. nova_base_v716) when told to copy the live bot, and records it in bots/NEW/BASE.
Agents then still declare NEW:LIVE, so the donor's diff is taken against the wrong tree and shipwatch's base check fails.
fix(spec) rewrites each DONOR:B in a comma list to DONOR:X when bots/DONOR/BASE says BASE=X, B != X, and B is the bot X was baked from
(diffbase.txt "B X ... identity ok", or bots/X/STRIPPED SOURCE=B), and the reverse: DONOR:nova_base_vN where the donor was
copied from the unbaked bot that base was baked from -> DONOR:<that bot>. Anything else is left as given.
usage: python3 -I tools/lab/donorbase.py DONOR:BASE[,DONOR2:BASE2]   (prints the normalised spec)
"""
import os
import re
import sys

REPO = "/homes/USER/cambc"
DIFFBASE = "/data/USER/st/bq/diffbase.txt"


def _kv(path, key):
    try:
        with open(path) as f:
            m = re.search(rf"^{key}=(\S+)", f.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def baked_from(x):
    """-> the set of bots base X was baked from."""
    src = set()
    s = _kv(os.path.join(REPO, "bots", x, "STRIPPED"), "SOURCE")
    if s:
        src.add(s)
    try:
        w = open(DIFFBASE).readline().split()
        if len(w) >= 2 and w[1] == x and "identity ok" in " ".join(w):
            src.add(w[0])
    except OSError:
        pass
    return src


def fix_one(spec, say=print):
    dn, sep, bn = spec.partition(":")
    if not sep or not dn or not bn or dn == "-":
        return spec
    x = _kv(os.path.join(REPO, "bots", dn, "BASE"), "BASE")
    if not x or x == bn or not os.path.isdir(os.path.join(REPO, "bots", x, "src")):
        return spec
    if x in baked_from(bn):  # 11 Nov (lsg13: copied from awr1, declared on nova_base_v755): the diff v the baked base un-baked AWR
        say(f"donor {dn} was copied from {x}, the unbaked bot {bn} was baked from (bots/{dn}/BASE): using {dn}:{x}, not {dn}:{bn}")
        return f"{dn}:{x}"
    if bn not in baked_from(x):
        return spec
    say(f"donor {dn} was copied from {x} (bots/{dn}/BASE): using {dn}:{x}, not {dn}:{bn}")
    return f"{dn}:{x}"


def fix(specs, say=print):
    """Comma list of DONOR:BASE (or '-') -> the same list with each base normalised."""
    if not specs or specs == "-":
        return specs
    return ",".join(fix_one(s, say) for s in specs.split(","))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(fix(sys.argv[1], say=lambda m: print(m, file=sys.stderr)))
