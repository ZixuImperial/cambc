#!/usr/bin/env python3
"""rarefill: GENERATE new unsaved maps into ONE approved rare line's bank (Tool Builder, 12 Nov; owner via the Coordinator [4b38e1], 12 Nov
~11:4xZ: rare-bank generation "yes but make sure this does not affect normal gameplay if rare"; rules in bq/rare_generate_ok.txt's header).

usage: python3 -I tools/lab/rarefill.py SLUG --wfams F1,F2 [--class COND] --count 500        hit-rate count only: generate, test, keep nothing in the bank
       python3 -I tools/lab/rarefill.py SLUG --wfams F1,F2 [--class COND] --fill N            generate until the bank holds N unused class maps
Isolation (refuses otherwise):
  - SLUG must be a line of bq/rare_generate_ok.txt (the owner approves one slug at a time)
  - every map is generated into /data/zw4424/st/rarebank/SLUG/gen/<stamp>/ (the bank dir; never the fresh pool, BIG/BIG2, draftstock, the
    saved bank, the 5% slices, panel/spar sets or another line's bank: the output path is checked to lie under the bank dir)
  - only --wfams families (the line's class families); --class COND (default the slug's bq/rarebank_class.tsv line) must pass
  - kept maps are hard-linked into SLUG/maps/ and recorded in SLUG/index.json under rarebank's lock (src = the gen dir, gen = true);
    SLUG/gen/manifest.tsv lists each kept map: name, sha1, family, class value
  - runs as you start it (start it as a nice'd, memory-capped transient unit); rarebank's scan never reads rarebank/ dirs
The candidate's flag-0 identity on off-class maps is prearm's 40/40 cxeident (record it in the line's prereg)."""
import hashlib
import json
import os
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
import mapclass  # noqa: E402
import rarebank as rb  # noqa: E402

OK = "/data/zw4424/st/bq/rare_generate_ok.txt"
CLS = "/data/zw4424/st/bq/rarebank_class.tsv"


def approved(slug):
    try:
        return any(ln.split("#")[0].strip() == slug for ln in open(OK))
    except OSError:
        return False


def class_of(slug):
    try:
        for ln in open(CLS):
            p = ln.rstrip("\n").split("\t")
            if len(p) >= 2 and not ln.startswith("#") and slug.startswith(p[0]):
                return p[1]
    except OSError:
        pass
    return None


def passes(path, cond):
    if not cond:
        return True, None
    # 13 Nov (TB: sax's 'siegemono:>=1,ssa:<1' raised ValueError): mapclass's own parser, so ','-joined conditions (all must hold) work
    conds = mapclass.parse(cond)
    vals = mapclass.values(path, sorted({n for n, _, _ in conds}))
    return mapclass.passes(vals, conds), vals.get(conds[0][0])


def gen(slug, wfams, n, bank):
    d = os.path.realpath(os.path.join(bank, "gen", time.strftime("%m%d%H%M%S") + f"_{os.getpid()}"))  # 13 Nov (TB): parallel class fills started in the same second shared one gen dir and deleted each other's maps
    if not d.startswith(os.path.realpath(bank) + os.sep):
        sys.exit(f"rarefill: refused: output {d} is outside {bank}")
    # 12 Nov ~23:5xZ (Builder, jkcf: a draft-time class over the default mix): --wfams w_any = the default fresh mix (half weird), no family filter
    mix = [] if wfams == "w_any" else ["--weird", "1", "--wfams", wfams]
    r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/stratmaps.py"), d, "--n", str(n)] + mix +
                       ["--who", f"rarefill_{slug}", "--light"], cwd=REPO, capture_output=True, text=True, timeout=7200)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:], flush=True)
    return d


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    slug = a[0]
    opt = lambda k, dflt=None: a[a.index(k) + 1] if k in a else dflt  # noqa: E731
    wfams = opt("--wfams")
    if not wfams or not all(f.startswith(("w_", "nf_")) for f in wfams.split(",")):
        sys.exit("rarefill: --wfams F1,F2 (generator families) is required")
    if not approved(slug):
        sys.exit(f"rarefill: refused: {slug} is not a line of {OK} (the owner approves one slug at a time)")
    cond = opt("--class", class_of(slug))
    bank = rb.bank_dir(slug)
    os.makedirs(os.path.join(bank, "maps"), exist_ok=True)
    if "--count" in a:
        n = int(opt("--count"))
        d = gen(slug, wfams, n, bank)
        fs = sorted(f for f in os.listdir(d) if f.endswith(".map26a"))
        hit = [f for f in fs if passes(os.path.join(d, f), cond)[0]]
        fam = {m["name"]: m.get("family") for m in json.load(open(os.path.join(d, "otf.json")))["maps"]}
        byf = {}
        for f in fs:
            k = fam.get(f[:-7], "?")
            byf.setdefault(k, [0, 0])[0] += 1
            if f in hit:
                byf[k][1] += 1
        print(f"rarefill {slug}: COUNT {len(hit)} of {len(fs)} generated maps pass {cond} ({100 * len(hit) / max(1, len(fs)):.1f}%): "
              + ", ".join(f"{k} {v[1]}/{v[0]}" for k, v in sorted(byf.items())) + f"  (count only: nothing banked; maps in {d})")
        return
    def draft_screen(d):
        """12 Nov ~23:5xZ (Builder, jkcf): --draftdiag BOT --dg 'TAG:a==0,b==1,c>=0': play every map of d in tools/lab/draftdiag.py (2 rounds, on
        the pilots) and keep the maps where some seat's record TAG meets every condition. -> set of map names"""
        bot_, spec_ = opt("--draftdiag"), opt("--dg", "1:a>=0")
        tag_, conds_ = spec_.split(":", 1)
        out_ = d + "_dg"
        subprocess.run(["nice", "-n", "10", sys.executable, "-I", os.path.join(REPO, "tools/lab/draftdiag.py"), bot_, d, out_, "--rounds", "2"],
                       cwd=REPO, capture_output=True, text=True, timeout=7200)
        keep_ = set()
        try:
            for ln in open(os.path.join(out_, "records.tsv")):
                p_ = ln.rstrip("\n").split("\t")
                if len(p_) < 8 or p_[0] == "map" or p_[3] != tag_:
                    continue
                v_ = dict(a=int(p_[4]), b=int(p_[5]), c=int(p_[6]), d=int(p_[7]))
                if all(eval(c_, {}, v_) for c_ in conds_.split(",")):  # simple comparisons on a/b/c/d only (the --dg spec is ours)
                    keep_.add(p_[0])
        except OSError:
            pass
        import shutil
        shutil.rmtree(out_, ignore_errors=True)
        print(f"rarefill {slug}: draft screen {len(keep_)} of {len([x for x in os.listdir(d) if x.endswith('.map26a')])} maps pass {spec_}", flush=True)
        return keep_

    target = int(opt("--fill"))
    man = os.path.join(bank, "gen", "manifest.tsv")
    rounds = int(os.environ.get("RAREFILL_ROUNDS", 40))  # 13 Nov (TB, cgb: a 0.27% class needs ~125 rounds of 1,260 maps)
    for _ in range(rounds):
        p = os.path.join(bank, "index.json")
        with rb.Lock(slug):
            j = json.load(open(p)) if os.path.exists(p) else {"slug": slug, "maps": {}, "consumed": {}, "created": time.time()}
        unused = sum(1 for k in j["maps"] if k not in j.get("consumed", {}))
        if unused >= target:
            print(f"rarefill {slug}: bank holds {unused} unused maps >= {target}: done")
            return
        need = target - unused
        d = gen(slug, wfams, min(2000, max(300, 3 * need)), bank)
        try:
            otf = {m["name"]: m for m in json.load(open(os.path.join(d, "otf.json")))["maps"]}
        except (OSError, ValueError) as e:  # 12 Nov 21:4xZ (tgo died rc 1 on one batch with no otf.json): skip the batch, keep filling
            print(f"rarefill {slug}: batch {d} gave no map list ({type(e).__name__}); next batch", flush=True)
            import shutil
            shutil.rmtree(d, ignore_errors=True)
            continue
        add = []
        dgs = draft_screen(d) if opt("--draftdiag") else None
        pre = {}
        if dgs is None and os.environ.get("RAREFILL_CLS_PILOTS", "1") == "1":
            # 13 Nov (TB, Builder: maple18 load 60+, pilots ~85% idle; 3 fc_plan8 fills burned ~1.3 cores classifying locally): class values on the
            # pilots (stratmaps._cls_on_pilots); maps whose chunk does not come back are classified here as before
            try:
                import stratmaps as _SM
                conds_ = mapclass.parse(cond)
                fs_ = [os.path.join(d, x) for x in sorted(os.listdir(d)) if x.endswith(".map26a")]
                pre = _SM._cls_on_pilots(fs_, sorted({n for n, _, _ in conds_})) or {}
            except Exception as e:  # noqa: BLE001  the pilots are a speed-up only
                print(f"rarefill {slug}: pilot classification failed ({type(e).__name__}: {e}); classifying here", flush=True)
                pre = {}
        for f in sorted(x for x in os.listdir(d) if x.endswith(".map26a")):
            if dgs is not None:  # the class is the probe bot's draft record (--draftdiag BOT --dg TAG:COND), not a mapclass value
                if f[:-7] in dgs:
                    add.append((f, "dg"))
                continue
            pv = pre.get(os.path.join(d, f))
            if pv is not None:
                conds_ = mapclass.parse(cond)
                ok, v = mapclass.passes(pv, conds_), pv.get(conds_[0][0])
            else:
                ok, v = passes(os.path.join(d, f), cond)
            if ok:
                add.append((f, v))
        with rb.Lock(slug):
            j = json.load(open(p)) if os.path.exists(p) else {"slug": slug, "maps": {}, "consumed": {}, "created": time.time()}
            j.setdefault("consumed", {})
            n0 = 0
            # 12 Nov ~22:4xZ (Coordinator, owner's unique test-set rule): no map whose bytes are already in the bank (harvested or generated)
            have_ = set()
            for fn_ in os.listdir(os.path.join(bank, "maps")) if os.path.isdir(os.path.join(bank, "maps")) else []:
                try:
                    have_.add(hashlib.sha1(open(os.path.join(bank, "maps", fn_), "rb").read()).hexdigest())
                except OSError:
                    pass
            with open(man, "a") as mf:
                for f, v in add:
                    m = otf.get(f[:-7], {})
                    seed = str(m.get("seed", f[:-7]))
                    if seed in j["maps"] and os.path.exists(os.path.join(bank, "maps", f"fm_h{seed}.map26a")):
                        continue  # 13 Nov (TB: jka4b kept +0 for an hour: its index outlived the pruned maps/): only a seed whose map is still here
                    try:  # 13 Nov (TB: jkcf/lce2 died rc 1 on a generated map gone before its link): a missing map is skipped
                        h_ = hashlib.sha1(open(os.path.join(d, f), "rb").read()).hexdigest()
                    except OSError:
                        continue
                    if h_ in have_:
                        continue
                    have_.add(h_)
                    name = f"fm_h{seed}"
                    dst = os.path.join(bank, "maps", name + ".map26a")
                    if not os.path.exists(dst):
                        try:
                            os.link(os.path.join(d, f), dst)
                        except OSError:
                            continue
                    j["maps"][seed] = dict(name=name, fam=m.get("family"), src=d, src_name=f[:-7], t=time.time(), meta=dict(m, name=name), gen=True)
                    mf.write(f"{name}\t{hashlib.sha1(open(dst, 'rb').read()).hexdigest()}\t{m.get('family')}\t{v}\n")
                    n0 += 1
            json.dump(j, open(p + ".tmp", "w"))
            os.replace(p + ".tmp", p)
        print(f"rarefill {slug}: +{n0} class maps from {d} ({len(add)} passed {cond})", flush=True)
        # 13 Nov (TB, /data 98%: gen dirs held 7.9 GB against 3.8 GB of kept maps): kept maps are hard links in maps/, so the batch's generation
        # dir (the maps that failed the class, and the generator's otf.json) goes once the batch is recorded
        if os.environ.get("RAREFILL_KEEP_GEN") != "1":
            import shutil
            shutil.rmtree(d, ignore_errors=True)
    print(f"rarefill {slug}: stopped after {rounds} rounds")


if __name__ == "__main__":
    main()
