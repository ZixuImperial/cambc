#!/usr/bin/env python3
"""poolpack: pack the loose lw3_..lw9_ pool maps (killgate stage sets) into condor-work/mapbank/lwx_NNN.tar, 100 maps each, and list them
in lw_index.txt (Tool Builder, 10 Nov; Coordinator: home at 54.9k of 60k files). Before this, condab synced every one of them as a loose
file into condor-work/proj400/maps on the home (6,000 files in a day; quotaguard removed them and the next batch copied them again).
condab's sync skips every map in lw_index.txt (ladderw.packed()), and condab_node.sh takes them from the pack. Entries of ladderw.py's own
lw_NNN packs are kept. Re-run after new lwN_ maps appear (idempotent: a pack is rewritten only when its member list changes).
usage: python3 -I tools/lab/poolpack.py [--dry]"""
import os
import re
import sys
import tarfile

MAPS = "/data/zw4424/work301/maps"
MB = "/homes/zw4424/condor-work/mapbank"
INDEX = os.path.join(MB, "lw_index.txt")
PER = 100
PAT = re.compile(r"^lw[0-9]_\d+$")


def main():
    names = sorted(f[:-7] for f in os.listdir(MAPS) if f.endswith(".map26a") and PAT.match(f[:-7]))
    old = [ln for ln in open(INDEX)] if os.path.exists(INDEX) else []
    keep = [ln for ln in old if len(ln.split()) >= 2 and not ln.split()[1].startswith("lwx_")]
    cur = {}
    for ln in old:
        s = ln.split()
        if len(s) >= 2 and s[1].startswith("lwx_"):
            cur.setdefault(s[1], []).append(s[0])
    idx, wrote = [], 0
    for k in range(0, len(names), PER):
        p, mem = f"lwx_{k // PER:03d}", names[k:k + PER]
        tar = os.path.join(MB, p + ".tar")
        if cur.get(p) != mem or not os.path.exists(tar):
            if "--dry" not in sys.argv:
                tmp = os.path.join(MB, f".{p}.tar.tmp{os.getpid()}")
                with tarfile.open(tmp, "w") as tf:
                    for m in mem:
                        tf.add(os.path.join(MAPS, m + ".map26a"), m + ".map26a")
                os.replace(tmp, tar)
            wrote += 1
        idx += [f"{m} {p}\n" for m in mem]
    if "--dry" not in sys.argv:
        with open(INDEX + f".tmp{os.getpid()}", "w") as fh:
            fh.write("".join(keep + idx))
        os.replace(INDEX + f".tmp{os.getpid()}", INDEX)
    print(f"poolpack: {len(names)} lwN_ maps in {-(-len(names) // PER)} packs ({wrote} written); index {len(keep)} ladderw + {len(idx)} pool lines"
          + (" [dry]" if "--dry" in sys.argv else ""))


if __name__ == "__main__":
    main()
