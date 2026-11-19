#!/usr/bin/env python3
"""bankimport (13 Nov, Tool Builder): import a screened map set (stratmaps-format dir: *.map26a + otf.json) into a rare bank, so a RARE line whose
class depends on the draft (b2365 OCF-M: our v898 draft fields Marcella, not Prism/Vesper, both seats) reads only those maps. Maps are hard-linked
into rarebank/SLUG/maps and recorded in its index.json (src = the set dir), skipping any whose bytes the bank already holds or whose name is in
--exclude FILE (held-out maps). A class row 'SLUG<TAB>bankimport_only:>=1' (a class no map passes) keeps harvest from adding random maps.
usage: bankimport.py SLUG SET_DIR [--exclude FILE]"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rarebank as R  # noqa: E402


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    slug, src = a[0], os.path.realpath(a[1])
    excl = set()
    if "--exclude" in a:
        excl = {ln.strip() for ln in open(a[a.index("--exclude") + 1]) if ln.strip()}
    maps = json.load(open(os.path.join(src, "otf.json")))["maps"]
    md = os.path.join(R.bank_dir(slug), "maps")
    os.makedirs(md, exist_ok=True)
    n = skip = 0
    with R.Lock(slug):
        idx = R.load(slug)
        idx.setdefault("slug", slug)
        have = {hashlib.sha1(open(os.path.join(md, f), "rb").read()).hexdigest() for f in os.listdir(md) if f.endswith(".map26a")}
        for m in maps:
            nm = m["name"]
            p = os.path.join(src, nm + ".map26a")
            if nm in excl or not os.path.exists(p):
                skip += 1
                continue
            h = hashlib.sha1(open(p, "rb").read()).hexdigest()
            if h in have:
                skip += 1
                continue
            sd = f"imp_{h[:16]}"
            if sd in idx["maps"] or sd in idx.get("consumed", {}):
                skip += 1
                continue
            dst = os.path.join(md, nm + ".map26a")
            if not os.path.exists(dst):
                os.link(p, dst)
            idx["maps"][sd] = dict(name=nm, fam=m.get("family") or (m.get("labels") or {}).get("fam") or "normal", src=src, src_name=nm, t=time.time(),
                                   meta=dict(m, labels=dict(m.get("labels") or {}, banked=os.path.basename(src))))
            have.add(h)
            n += 1
        idx["fams"] = ["w_any"]
        R.save(slug, idx)
    q = os.path.join(R.Q, "rarebank_class.tsv")
    rows = open(q).read()
    if not any(ln.split("\t")[0] == slug for ln in rows.splitlines()):
        tmp = q + f".new.{os.getpid()}"
        open(tmp, "w").write(rows.rstrip("\n") + f"\n{slug}\tbankimport_only:>=1\n")
        os.replace(tmp, q)
    print(f"bankimport {slug}: +{n} maps from {src} ({skip} skipped: held out, missing or duplicate); bank unused {len(R.avail(slug, R.load(slug)))}")


if __name__ == "__main__":
    main()
