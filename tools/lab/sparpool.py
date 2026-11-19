"""sparpool: pool one spar's paired D over several independent stylepanel reads (owner 4 Nov ~19:00Z: a single-spar second
read within noise but below 0 gets ONE more 1,200-map read, then all three reads pooled decide: point >= 0 and CI upper >= 0).
Each read is that spar's line in /data/USER/st/bq/sp<TAG>.txt ("  nova_spar_X  n N ... D d [lo, hi]"); the reads are on
different new maps, so they pool map-weighted: D = sum(n D) / sum(n), se = sqrt(sum((n se)^2)) / sum(n), se = (hi - lo) / 3.92.
usage: python3 -I tools/lab/sparpool.py SPAR TAG [TAG ...]     e.g. sparpool.py heavy 1378 1378s irdltg3_04184947
Exit 0 = pooled point >= 0 and CI upper >= 0, 1 = not, 2 = a read has no line for that spar."""
import math
import os
import re
import sys

BQ = "/data/USER/st/bq"


def spar_read(spar, tag):
    """(D, se, n) of SPAR's line in BQ/sp<TAG>.txt, or None."""
    try:
        txt = open(os.path.join(BQ, f"sp{tag}.txt")).read()
    except OSError:
        return None
    m = re.search(r"^\s+" + re.escape(spar) + r"\s+n\s+(\d+)\s.*?D ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\]", txt, re.M)
    if not m:
        return None
    return float(m.group(2)), (float(m.group(4)) - float(m.group(3))) / 3.92, int(m.group(1))


def pool(reads):
    """Map-weighted pooling of independent (D, se, n) reads -> (D, se, n)."""
    n = sum(r[2] for r in reads)
    return sum(r[0] * r[2] for r in reads) / n, math.sqrt(sum((r[2] * r[1]) ** 2 for r in reads)) / n, n


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    spar = a[0] if a[0].startswith("nova_spar_") else "nova_spar_" + a[0]
    reads = []
    for t in a[1:]:
        r = spar_read(spar, t)
        if r is None:
            print(f"sp{t}.txt: no {spar} line")
            return 2
        reads.append(r)
        print(f"  sp{t}.txt  D {r[0]:+.4f} [{r[0] - 1.96 * r[1]:+.4f}, {r[0] + 1.96 * r[1]:+.4f}] n {r[2]}")
    d, se, n = pool(reads)
    ok = d >= 0 and d + 1.96 * se >= 0
    print(f"{spar} pooled over {len(reads)} reads: D {d:+.4f} [{d - 1.96 * se:+.4f}, {d + 1.96 * se:+.4f}] n {n}  z {d / max(se, 1e-9):+.2f}"
          f" -> {'PASS' if ok else 'FAIL'} (point >= 0 and CI upper >= 0)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
