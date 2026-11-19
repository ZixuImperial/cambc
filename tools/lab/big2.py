#!/usr/bin/env python3
"""big2.py - the BIG2 map set (Tool Builder, 11 Nov; owner: a new BIG, diverse and deduped, current-ladder mix). Built by
/data/USER/mapbank/big2/select2.py (list.txt = source paths in stratified order, table.md = bands, dedupe and diversity report).

  python3 -I tools/lab/big2.py pack      copy the selected maps to /data/USER/mapbank/big2/maps/b2_NNNNN.map26a (order kept), pack them
                                         100 a tar into condor-work/mapbank/b2_NNN.tar and add "name pack" lines to lw_index.txt (the index
                                         condab_node.sh already reads), names.txt = the b2_ names in order
  python3 -I tools/lab/big2.py status    list size, packed maps
condab: BIG=N BIGSET=big2 (or bq/bigset.txt = big2): the published pool + the first N BIG2 maps, as ladderw_nh."""
import os
import shutil
import sys
import tarfile

D = "/data/USER/mapbank/big2"
SRC = os.path.join(D, "list.txt")
NAMES = os.path.join(D, "names.txt")
MAPS = os.path.join(D, "maps")
MB = "/homes/USER/condor-work/mapbank"
INDEX = os.path.join(MB, "lw_index.txt")
PER_PACK = 100


def names():
    return [ln.strip() for ln in open(NAMES) if ln.strip()]


def bank_list(n):
    """The first n BIG2 maps (every prefix keeps the band mix: select2's stratified order), less zero_gem.txt (owner 12 Nov: tournament
    maps always have gems, so maps with no gem-carrying camp are not played; BIG=2000 now plays the 1,985 others)."""
    zg = os.path.join(os.path.dirname(MAPS), "zero_gem.txt")
    skip = {x.strip() for x in open(zg) if x.strip() and not x.startswith("#")} if os.path.exists(zg) else set()
    return [x for x in names()[:n] if x not in skip]


def pack():
    src = [ln.strip() for ln in open(SRC) if ln.strip()]
    os.makedirs(MAPS, exist_ok=True)
    nm = []
    for i, p in enumerate(src):
        n = f"b2_{i:05d}"
        dst = os.path.join(MAPS, n + ".map26a")
        if not os.path.exists(dst):
            shutil.copyfile(p, dst)
        for wd in ("/data/USER/work301/maps", "/data/USER/ablproj_4.0.0/maps"):  # ladderw.MAPS (CLI, readers) and cxecondab.WS_MAPS (cxe on Condor)
            w = os.path.join(wd, n + ".map26a")
            if not os.path.exists(w):
                os.link(dst, w)
        nm.append(n)
    old = [ln for ln in open(INDEX)] if os.path.exists(INDEX) else []
    keep = [ln for ln in old if not ln.startswith("b2_")]
    idx = []
    for k in range(0, len(nm), PER_PACK):
        pk = f"b2_{k // PER_PACK:03d}"
        tmp = os.path.join(MB, f".{pk}.tar.tmp")
        with tarfile.open(tmp, "w") as tf:
            for n in nm[k:k + PER_PACK]:
                tf.add(os.path.join(MAPS, n + ".map26a"), arcname=n + ".map26a")
        os.replace(tmp, os.path.join(MB, pk + ".tar"))
        idx += [f"{n} {pk}\n" for n in nm[k:k + PER_PACK]]
    with open(INDEX + ".tmp", "w") as f:
        f.writelines(keep + idx)
    os.replace(INDEX + ".tmp", INDEX)
    with open(NAMES + ".tmp", "w") as f:
        f.write("\n".join(nm) + "\n")
    os.replace(NAMES + ".tmp", NAMES)
    print(f"big2: {len(nm)} maps in {MAPS}, {len(idx) // PER_PACK + (1 if len(idx) % PER_PACK else 0)} packs, {len(idx)} index lines")


def status():
    try:
        n = names()
    except OSError:
        print("big2: not packed yet (no names.txt)")
        return
    pk = {ln.split()[0] for ln in open(INDEX) if ln.startswith("b2_")}
    print(f"big2: {len(n)} maps, {sum(x in pk for x in n)} packed")


if __name__ == "__main__":
    a = sys.argv[1:]
    {"pack": pack, "status": status}.get(a[0] if a else "", lambda: sys.exit(__doc__))()
