#!/usr/bin/env python3
"""ladderw.py - the LADDER-WEIGHTED BIG map set (31 Oct, Builder; Econ's audit condor-work/reports/econ/oldno_retest_1031.md:
bank v2 has no hoard / gated / island maps and a ninth of the ladder's one-altar share). 2000 maps whose band mix matches
ladder70 (one altar, hoard, gated, islands, dominant group, far40, monolith), drawn from bank v2 decision maps plus the band
generator families (dev halves only). The selection and its band table: /data/zw4424/mapbank/ladderw/ (select.py,
list.txt in a stratified order: every prefix keeps the mix, table.md).

Maps keep their own names. Bank maps (gen_bk*_/gen_bh*_) already reach the Condor nodes as packs; the others are packed here
into condor-work/mapbank/lw_NNN.tar (100 maps each, original names) and found through lw_index.txt ("name pack"), which
condab_node.sh reads, so none of them is copied into proj400/maps on the home quota (condab's sync skips them).

usage: python3 -I tools/lab/ladderw.py pack       (re)build the packs and the index from list.txt
       python3 -I tools/lab/ladderw.py status     list size, packed maps, missing packs
condab: BIG=N BIGSET=ladderw sh tools/lab/condab.sh CAND BASE NAME all   (the 636 pool + the first N ladderw maps)
"""
import os
import sys
import tarfile

LIST = "/data/zw4424/mapbank/ladderw/list.txt"
MB = "/homes/zw4424/condor-work/mapbank"
INDEX = os.path.join(MB, "lw_index.txt")
MAPS = "/data/zw4424/work301/maps"
BANKPFX = ("gen_bk_", "gen_bh_", "gen_bk2_", "gen_bh2_")
PER_PACK = 100


SWITCH = "/data/zw4424/st/bq/bigset.txt"  # the default BIGSET for new runs (3 Nov): "ladderw" or "ladderw_nh"; marker and env values win
NH = "ladderw_nh"  # owner 3 Nov: the ladder-weighted maps plus the published pool, no held-out family (gen_NN, gen_u, gen_ux, gen_s, gen_p)
SETS = ("ladderw", NH, "big2")  # 11 Nov: big2 = tools/lab/big2.py (bq/bigset.txt may name it)


def default_bigset():
    try:
        v = open(SWITCH).read().strip()
        return v if v in SETS else "ladderw"
    except OSError:
        return "ladderw"


def names():
    return [ln.strip() for ln in open(LIST) if ln.strip()]


def bank_list(n):
    """The first n maps of the ladder-weighted set (every prefix keeps the band mix)."""
    return names()[:n]


def packed():
    """{map name: pack name} of the maps packed here (empty when nothing is packed)."""
    try:
        return dict(ln.split()[:2] for ln in open(INDEX) if len(ln.split()) >= 2)
    except OSError:
        return {}


def pack():
    extra = [m for m in names() if not m.startswith(BANKPFX)]
    missing = [m for m in extra if not os.path.exists(os.path.join(MAPS, m + ".map26a"))]
    if missing:
        sys.exit(f"{len(missing)} maps of the list are not in {MAPS}, e.g. {missing[:5]}")
    idx = []
    for k in range(0, len(extra), PER_PACK):
        p = f"lw_{k // PER_PACK:03d}"
        tmp = os.path.join(MB, f".{p}.tar.tmp")
        with tarfile.open(tmp, "w") as tf:
            for m in extra[k:k + PER_PACK]:
                tf.add(os.path.join(MAPS, m + ".map26a"), m + ".map26a")
                idx.append(f"{m} {p}\n")
        os.replace(tmp, os.path.join(MB, p + ".tar"))
    n_packs = -(-len(extra) // PER_PACK)
    for f in os.listdir(MB):  # packs of an older, longer list
        if f.startswith("lw_") and f.endswith(".tar") and f[3:6].isdigit() and int(f[3:6]) >= n_packs:
            os.remove(os.path.join(MB, f))
    try:  # 10 Nov: keep tools/lab/poolpack.py's lwx_ pool-pack lines
        idx += [ln for ln in open(INDEX) if len(ln.split()) >= 2 and ln.split()[1].startswith("lwx_")]
    except OSError:
        pass
    with open(INDEX + ".tmp", "w") as fh:
        fh.write("".join(idx))
    os.replace(INDEX + ".tmp", INDEX)
    print(f"packed {len(extra)} non-bank maps into {n_packs} packs ({MB}/lw_*.tar); index {INDEX}")


def status():
    n, pk = names(), packed()
    extra = [m for m in n if not m.startswith(BANKPFX)]
    print(f"{len(n)} maps in {LIST}: {len(n) - len(extra)} bank maps, {len(extra)} others, {sum(m in pk for m in extra)} packed")
    absent = sorted({p for p in pk.values() if not os.path.exists(os.path.join(MB, p + ".tar"))})
    if absent:
        print("missing packs:", " ".join(absent))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["pack"]:
        pack()
    elif a[:1] == ["status"]:
        status()
    else:
        sys.exit(__doc__)
