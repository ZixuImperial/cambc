#!/usr/bin/env python3
"""rarebank: family maps for waiting rare lines, banked from the common reads; a rare read starts only when its bank is big enough.
Tool Builder, 11 Nov (owner ~02:4xZ: "Just store maps you find in common reads that fit one of the rare reads and once you have enough do the
rare read with that"). Spec from the Tool Builder 6ad907.

Switch: ON only while /data/zw4424/st/bq/rarebank_ON exists. Absent: no bank scan, no gate, no bank draw; rare lines run as before.
--rare-fams w_any (12 Nov): every family; the slug's class filter in bq/rarebank_class.tsv decides (class-only lines).
Generation: a shipcheck rare line (env RARE) with --wfams never GENERATES family maps unless bq/rare_generate_ON exists, or its slug is a line of
  bq/rare_generate_ok.txt (the owner approves one slug at a time); without it only maps from the common sets are used (changedprobe.draw).
  An approved slug also skips the bank gate (it runs as before: harvest + generated shortfall).

1. BANK (scan): every common fresh set ridealong.fresh_dirs() lists (panel/*, gate/*, gate/*/*, otf_tmp/*: otf.json + .map26a, never a
   changed-map read's dir) is scanned for the families of every WAITING rare line: armq.txt rows with rare + rarefams, and bots/*/SHIPCHECK
   markers with RARE= and RAREFAMS= that shipwatch has not started (their hash is not in shipwatch_state.json) or that wait on their bank.
   A map fits a line when ridealong.fams_of() says it has one of the line's families (its own family label, or genweird.check on the built
   map; cached per seed in st/ridealong/famcache.json, shared with ride-along's harvest). Fitting maps are HARD-LINKED (never copied or moved)
   into /data/zw4424/st/rarebank/<slug>/maps/fm_h<seed>.map26a; <slug>/index.json keeps per seed: family, source dir and name, time.
   Never banked: held-out maps (gen_*, ridealong.HELDOUT_LISTS), maps the line was picked on (ridealong.own_picked: every changed-map probe of
   the slug), a seed already in the line's bank, maps of a read whose condab summary names one of the line's bots, changed-map read dirs.
   Runs (a) as `rarebank.py tick` every RAREBANK_TICK (120) s from shipwatch's loop (its own nice'd process; RAREBANK_S (60) s of work a tick,
   newest dirs first, a dir is re-scanned only when its otf.json or the families wanted change), and (b) as stylepanel's hook just before a
   finished read deletes its maps (RAREBANK_HOOK_S (30) s).
2. GATE (shipwatch.scan): a rare marker with RAREFAMS waits, without a slot or any CPU (no ubaudit prebuild either), with the queue reason
   "rare bank N of M maps", until its bank holds M = ceil((n - k) / s) unused maps: n = max(RARE, 1.05 x rarebar min) (shipcheck's own n),
   k = changed maps kept by an earlier short read of the same CAND on the same live (resume), s = the slug's changed share on bank maps over
   its earlier bank reads (>= 100 maps probed), else RAREBANK_S0 (0.5). Then it starts with CP_RAREBANK=<bank> and SP_CHANGED_TARGETED_ONLY=1:
   changedprobe draws EVERY batch from the bank (rarebank.draw: hard links, the drawn seeds are consumed for that slug), never the pool or
   generation. The changed-map rule, rarebar.txt and shipcheck's rows are unchanged; every bank map counts as 'targeted' (as generated family
   maps did).
3. SHORT READ: a bank read that runs out of bank maps before n changed maps stops (changedprobe st.bank_short), stylepanel saves its probe
   (changed.json, otf.json, the kept changed maps) as the slug's resume and exits 4 with "RARE BANK SHORT"; shipcheck then writes
   "OVERALL: BANKWAIT" (not INCONCLUSIVE: no re-arm, no self-heal count) and appends a comment line to the marker, so shipwatch sees it again
   and it waits on its bank. The next read of the same CAND v the same live resumes from the saved probe (its changed maps' games kept);
   after a rebase (new CAND or live) the read starts whole on new bank maps.
4. REPORT bq/rarebank_report.txt (refreshed hourly): per waiting line slug, families, bank n, target, growth/h, hours waiting; a line whose
   bank grows under 1%/h of its target after RAREBANK_SLOW_H (2) h is marked SLOW (no common set produces its families): the owner may add its
   slug to bq/rare_generate_ok.txt.
5. bq/rare_max still caps running rare reads (shipwatch).
CLI: python3 -I tools/lab/rarebank.py status          (per waiting line: families, bank n, target, growth/h, waiting h)
     python3 -I tools/lab/rarebank.py tick [--dry]    (one scan; --dry: count fitting maps, link nothing, write nothing)
     python3 -I tools/lab/rarebank.py report          (write the report now)
     python3 -I tools/lab/rarebank.py gate BOT        (what shipwatch would decide for bots/BOT/SHIPCHECK)
Env for tests: RAREBANK_Q (bq dir), RAREBANK_ROOT (bank root), RAREBANK_REPO (repo with bots/)."""
import fcntl
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
Q = os.environ.get("RAREBANK_Q", "/data/zw4424/st/bq")
ROOT = os.environ.get("RAREBANK_ROOT", "/data/zw4424/st/rarebank")
REPO = os.environ.get("RAREBANK_REPO", "/homes/zw4424/cambc")
LOG = os.path.join(Q, "rarebank.log")
S0 = float(os.environ.get("RAREBANK_S0", 0.5))


def on():
    return os.path.exists(os.path.join(Q, "rarebank_ON"))


def gen_allowed(slug=None):
    """Generation of family maps for a rare line: bq/rare_generate_ON (all), or the slug listed in bq/rare_generate_ok.txt."""
    if os.path.exists(os.path.join(Q, "rare_generate_ON")):
        return True
    if not slug:
        return False
    try:
        ok = {ln.split("#")[0].strip() for ln in open(os.path.join(Q, "rare_generate_ok.txt"))}
    except OSError:
        return False
    return slug in ok


def say(msg, quiet=False):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    if not quiet:
        print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def slug_of(bot):
    import ridealong
    return ridealong.base_slug(bot)


def bank_dir(slug):
    """a slug's bank; an absolute path is a bank dir already (CP_RAREBANK)"""
    return slug if slug.startswith("/") else os.path.join(ROOT, slug)


class Lock:
    def __init__(self, slug):
        os.makedirs(bank_dir(slug), exist_ok=True)
        self.f = open(os.path.join(bank_dir(slug), ".lock"), "a")

    def __enter__(self):
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *e):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def parent_slug(slug):
    """11 Nov (TB 6ad907: rgp1vs drew its bank, ended INCONCLUSIVE, and its re-arm rgp1vsi started a fresh 840-map bank): the nearest
    existing bank found by stripping re-arm suffixes (i inconclusive requeue, u, r rebase, s live-moved requeue) one at a time; None when there is none."""
    if slug.startswith("/"):
        return None
    s0 = slug
    while len(s0) > 3 and s0[-1] in "iurs":  # 12 Nov ~23:3xZ (TB, hplz1 -> hplz1s lost its bank + saved probe): armq's live-moved requeue adds 's' too
        s0 = s0[:-1]
        if os.path.exists(os.path.join(bank_dir(s0), "index.json")):
            return s0
    return None


CLASS_FILE = "/data/zw4424/st/bq/rarebank_class.tsv"  # 11 Nov (Builder: DMW/CXR want only DOM-trigger maps): SLUG_PREFIX<TAB>mapclass condition
_cls = {}


def class_ok(slug, path):
    """True unless bq/rarebank_class.tsv gives this slug (longest matching prefix) a mapclass condition the map fails."""
    try:
        rows = [ln.split("\t") for ln in open(CLASS_FILE).read().splitlines() if ln.strip() and not ln.startswith("#")]
    except OSError:
        return True
    best = max((r for r in rows if len(r) >= 2 and slug.startswith(r[0].strip())), key=lambda r: len(r[0]), default=None)
    if not best:
        return True
    cond = best[1].strip()
    k = (path, cond)
    if k not in _cls:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import mapclass
            conds = mapclass.parse(cond)
            _cls[k] = bool(mapclass.passes(mapclass.values(path, [c[0] for c in conds]), conds))
        except (Exception, SystemExit):  # noqa: BLE001  a map the class can't read is not banked for a class line
            _cls[k] = False
    return _cls[k]


def slug_root(slug):
    """bsh3rr, bsh3s, bsh3ri -> bsh3: a slug minus its re-arm suffixes (i inconclusive requeue, u, r rebase, s rare/bank re-arm)."""
    s0 = slug
    while len(s0) > 3 and s0[-1] in "iurs":
        s0 = s0[:-1]
    return s0


def related_banks(slug):
    """11 Nov (TB 0c2ec6: bsh3rr sat at 199/840 while bsh3r 477, bsh3s 440 and bsh3 124 unused maps of the same idea lay in other banks):
    every existing bank of the same root slug, nearest parent first."""
    if slug.startswith("/"):
        return []
    root, out = slug_root(slug), []
    par = parent_slug(slug)
    if par:
        out.append(par)
    try:
        for d in sorted(os.listdir(ROOT)):
            if d != slug and d not in out and slug_root(d) == root and os.path.exists(os.path.join(bank_dir(d), "index.json")):
                out.append(d)
    except OSError:
        pass
    return out


def _inherit(slug):
    """A new bank of a re-armed slug starts with the maps of every bank of the same idea (same root slug): those never drawn, and those
    drawn by a read that recorded no result (stopped for capacity or time: no decision was made on them). Maps a recorded read played
    stay out (winner's curse). -> idx or None"""
    pars = related_banks(slug)
    if not pars:
        return None
    idx = dict(slug=slug, maps={}, consumed={}, reads=[], hist=[], created=time.time(), inherited=dict(parent=pars[0], parents=pars, t=time.time()))
    md = os.path.join(bank_dir(slug), "maps")
    os.makedirs(md, exist_ok=True)
    played = set()
    for par in pars:  # a seed any related read played with a result stays out, whichever bank holds it
        try:
            pidx = json.load(open(os.path.join(bank_dir(par), "index.json")))
        except (OSError, ValueError):
            continue
        done = {r.get("tag") for r in pidx.get("reads", [])}
        played |= {sd for sd, ct in pidx.get("consumed", {}).items() if isinstance(ct, str) and ct in done}
        # 12 Nov (jkc3s / gbzhs: hand-set exclusions were dict values, this line raised TypeError, and the re-armed banks started without them,
        # 900 of SC12638's maps back in jkc3s): exclusion marks ('excluded: ...', or any non-tag value) carry into the child bank as consumed
        for sd, ct in pidx.get("consumed", {}).items():
            if not isinstance(ct, str) or ct.startswith("excluded"):
                idx["consumed"].setdefault(sd, ct if isinstance(ct, str) else "excluded: " + str(ct)[:120])
                played.add(sd)
    for par in pars:
        try:
            pidx = json.load(open(os.path.join(bank_dir(par), "index.json")))
        except (OSError, ValueError):
            continue
        pmd = os.path.join(bank_dir(par), "maps")
        for sd, e in pidx.get("maps", {}).items():
            if sd in idx["maps"] or sd in played:
                continue
            src = os.path.join(pmd, e["name"] + ".map26a")
            if not class_ok(slug, src):  # 12 Nov: a re-armed line with a narrower class (rarebank_class.tsv) inherits only maps in its class
                continue
            try:
                os.link(src, os.path.join(md, e["name"] + ".map26a"))
            except FileExistsError:
                pass
            except OSError:
                continue
            idx["maps"][sd] = dict(e, pooled_from=par)
    idx["inherited"]["maps"] = len(idx["maps"])
    say(f"rare bank {slug}: inherited {len(idx['maps'])} maps from {', '.join(pars)} (unused, or drawn by a read with no result)")
    return idx


def load(slug):
    try:
        return json.load(open(os.path.join(bank_dir(slug), "index.json")))
    except (OSError, ValueError):
        idx = None
        try:
            idx = _inherit(slug)
        except Exception as e:  # noqa: BLE001  inheritance never blocks a bank
            say(f"rare bank {slug}: no inheritance ({e!r})")
        if idx is not None:
            save(slug, idx)
            return idx
        return dict(slug=slug, maps={}, consumed={}, reads=[], hist=[], created=time.time())


def save(slug, idx):
    p = os.path.join(bank_dir(slug), "index.json")
    os.makedirs(bank_dir(slug), exist_ok=True)
    json.dump(idx, open(p + f".{os.getpid()}", "w"))
    os.replace(p + f".{os.getpid()}", p)


def avail(slug, idx=None):
    """Unused bank maps of SLUG (on disk, not consumed by a read)."""
    idx = idx or load(slug)
    md = os.path.join(bank_dir(slug), "maps")
    return [s for s, e in idx["maps"].items() if s not in idx["consumed"] and os.path.exists(os.path.join(md, e["name"] + ".map26a"))]


def rare_bar_min():
    try:
        w = open(os.path.join(Q, "rarebar.txt")).read().split()
        return float(dict(zip(w[::2], w[1::2]))["min"])
    except (OSError, KeyError, ValueError):
        return 400.0


def n_eff(rare):
    return max(int(rare), math.ceil(1.05 * rare_bar_min()))  # shipcheck: RARE["n"] = max(N, ceil(1.05 x min))


def share(idx):
    """The slug's changed share on bank maps over its earlier bank reads (>= 100 maps probed), else None."""
    c = sum(r.get("changed", 0) for r in idx.get("reads", []))
    p = sum(r.get("probed", 0) for r in idx.get("reads", []))
    return (c / p, c, p) if p >= 100 else (None, c, p)


def live_bot():
    try:
        return open(os.path.join(Q, "live.txt")).readline().split()[1]
    except (OSError, IndexError):
        return None


def resume_of(idx, cand, base):
    r = idx.get("resume") or {}
    if r.get("cand") == cand and r.get("base") == base and os.path.exists(os.path.join(r.get("dir", "/nonexistent"), "changed.json")):
        return r
    return None


S0_FILE = "/data/zw4424/st/bq/rarebank_s0.tsv"  # 12 Nov (Builder, jkc3): SLUG_PREFIX<TAB>share<TAB>source: a measured prior share per line


def s0_of(slug):
    """-> (share, note): the longest matching prefix in bq/rarebank_s0.tsv (a share measured on an earlier read of the same cell), else
    RAREBANK_S0. Only used until the line's own first bank read measures it."""
    try:
        rows = [ln.split("\t") for ln in open(S0_FILE).read().splitlines() if ln.strip() and not ln.startswith("#")]
        best = max((r for r in rows if len(r) >= 2 and slug.startswith(r[0].strip())), key=lambda r: len(r[0]), default=None)
        if best:
            v = float(best[1])
            if 0.05 <= v <= 1.0:
                return v, f"prior share from bq/rarebank_s0.tsv ({best[2].strip()[:80] if len(best) > 2 else best[0]})"
    except (OSError, ValueError):
        pass
    return S0, "RAREBANK_S0"


def target(slug, rare, cand=None, base=None, confirm=False, idx=None):
    """-> (target maps, why): unused bank maps needed for n changed maps at the expected share."""
    idx = idx or load(slug)
    n = n_eff(rare)
    if confirm:
        n = math.ceil(n / 2)
    s, c, p = share(idx)
    rel = ""
    if not s:  # 12 Nov (gbzhsrs asked 504 maps at the default .50 while its parent gbzhs had measured 893 of 893): a related bank's measured share
        try:
            rc = rp = 0
            for b in related_banks(slug):
                bs, bc, bp = share(load(b))
                rc, rp = rc + bc, rp + bp
            if rp >= 100:
                s, c, p, rel = rc / rp, rc, rp, " in related banks"
        except Exception:  # noqa: BLE001
            pass
    r = resume_of(idx, cand, base) if cand else None
    k = int(r.get("kept", 0)) if r else 0
    s0 = s0_of(slug)
    sh = s if s else s0[0]
    t = max(1, math.ceil(max(0, n - k) / max(sh, 0.01) * (1.2 if confirm else 1.0)))
    why = f"n {n}" + (f" - {k} kept (resume)" if k else "") + f" at share {sh:.2f}" + (f" ({c} of {p} earlier bank maps{rel})" if s else f" (no earlier bank read: {s0[1]})")
    return t, why


# ---------------------------------------------------------------- waiting lines
def _sw_state():
    try:
        return json.load(open(os.path.join(Q, "shipwatch_state.json")))
    except (OSError, ValueError):
        return {}


def parse_marker(path):
    kv = {}
    for ln in open(path, errors="replace"):
        x = ln.strip()
        if x and not x.startswith("#") and "=" in x:
            k, v = x.split("=", 1)
            kv[k.strip()] = v.strip()
    return kv


def waiting_lines():
    """{slug: dict(fams, rare, bots, src, confirm)} of rare lines with families that have not started: armq rows and unstarted markers."""
    out = {}
    st = _sw_state()
    for mk in glob.glob(os.path.join(REPO, "bots", "nova_b*", "SHIPCHECK")):
        name = os.path.basename(os.path.dirname(mk))
        try:
            raw = open(mk, "rb").read()
            kv = parse_marker(mk)
        except OSError:
            continue
        if (kv.get("RARE") and not kv.get("RAREFAMS") and not kv.get("CLASS") and not kv.get("BASEHAS")
                and os.environ.get("ARMQ_RARE_BANK", "1") == "1"):
            # 13 Nov (TB, queue watch: wfc1s/kos1s/mzs1rs/... sat 1-6 h at 'bank 0 of 840', growth 0/h): gate() banks a plain rare line on
            # w_any, but this list (what the harvest fills) skipped markers with no RAREFAMS, so those banks never grew. Same default here.
            kv = dict(kv, RAREFAMS="w_any")
        if not kv.get("RARE") or not kv.get("RAREFAMS"):
            continue
        h = hashlib.sha1(raw).hexdigest()[:12]
        s = st.get(name) or {}
        if s.get("marker") == h:
            continue  # handled: started, ended, skipped, rebased
        sl = slug_of(name)
        e = out.setdefault(sl, dict(fams=set(), rare=kv["RARE"], bots=set(), src=set(), confirm=False))
        e["fams"] |= set(kv["RAREFAMS"].split(","))
        e["bots"].add(name)
        e["src"].add("marker")
        e["confirm"] = e["confirm"] or "CONFIRM_FROM" in kv
    try:
        for ln in open(os.path.join(Q, "armq.txt")):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if not r.get("rare") or not r.get("rarefams") or not r.get("slug"):
                continue
            sl = slug_of(f"nova_b0_{r['slug']}")
            e = out.setdefault(sl, dict(fams=set(), rare=str(r["rare"]), bots=set(), src=set(), confirm=False))
            e["fams"] |= set(str(r["rarefams"]).split(","))
            e["src"].add("armq")
    except OSError:
        pass
    for sl in list(out):
        if gen_allowed(sl):
            out.pop(sl)  # approved for generation: runs as before, no bank
    # 12 Nov (TB; Deep: bank a class BEFORE its line is armed, so the read does not wait): bq/rarebank_standing.tsv lines
    # 'SLUG<TAB>FAMS<TAB>CAP' harvest like a waiting line (class filter from rarebank_class.tsv as usual; FAMS w_any = any family)
    # until the bank holds CAP unused maps; a real waiting line of the same slug takes precedence
    try:
        for ln in open(os.path.join(Q, "rarebank_standing.tsv")):
            p_ = ln.split("#")[0].rstrip("\n").split("\t")
            # 12 Nov 20:4xZ (Aggression: rarebank/tgo stayed empty): a stamped slug (gen_allowed) no longer skips its standing harvest; the
            # Coordinator's order is harvest from stock first, rarefill only when short, and a bank holds both (index src / gen per map)
            if len(p_) < 3 or not p_[0].strip() or p_[0] in out:
                continue
            try:
                cap = int(p_[2])
            except ValueError:
                continue
            if len(avail(p_[0])) >= cap:
                continue
            out[p_[0]] = dict(fams=set(p_[1].split(",")), rare=str(cap), bots=set(), src={"standing"}, confirm=False)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- 1. scan
def _excl_dir(d, slug):
    """A read whose condab summary names one of the line's bots: its maps are the line's own picks."""
    try:
        head = open(os.path.join(Q, f"fp{os.path.basename(d)}.condor.txt")).read(3000)
    except OSError:
        return False
    return bool(re.search(rf"nova_b\d+_{re.escape(slug)}(?![a-z0-9])", head))


def scan(lines=None, budget=None, dirs=None, dry=False, log=say):
    """Link fitting maps of the common fresh sets into each waiting line's bank. -> {slug: new maps} (dry: maps that would be linked)."""
    import ridealong as R
    lines = waiting_lines() if lines is None else lines
    if not lines:
        return {}
    budget = float(os.environ.get("RAREBANK_S", 60)) if budget is None else budget
    t0 = time.time()
    allf = sorted(set().union(*[e["fams"] for e in lines.values()]))
    held = R.heldout_names()
    picked = {sl: R.own_picked(f"nova_b0_{sl}") for sl in lines}
    idxs = {sl: load(sl) for sl in lines}
    have = {sl: set(idxs[sl]["maps"]) | set(idxs[sl]["consumed"]) for sl in lines}
    sst_p = os.path.join(ROOT, "scan_state.json")
    try:
        sst = json.load(open(sst_p))
    except (OSError, ValueError):
        sst = {}
    dirs = R.fresh_dirs() if dirs is None else dirs
    # as ride-along's harvest: a family whose check hits under RIDE_HARVEST_MINRATE (0.5%) of >= RIDE_HARVEST_RATE_N (1000) cached maps, or
    # has no check on a built map, is matched by its family label only (keeps the scan cheap)
    rate = {f: [0, 0] for f in allf}
    for v in R._fc_load().values():
        for f in allf:
            if f in v:
                rate[f][0] += 1
                rate[f][1] += bool(v[f])
    minr, minn = float(os.environ.get("RIDE_HARVEST_MINRATE", 0.005)), int(os.environ.get("RIDE_HARVEST_RATE_N", 1000))
    lab_only = {f for f in allf if not R.checkable(f) or (rate[f][0] >= minn and rate[f][1] < minr * rate[f][0])}
    # 12 Nov (TB: jkc2's w_jackpot2 bank sat at 0 for an hour: every unlabelled map in ~hundreds of panel dirs got the family's full check,
    # 60 s a tick): gencruel families are opt-in and always labelled when made (fresh-mix slices too), so a map without the label can't be one
    try:
        import gencruel
        lab_only |= {f for f in allf if f in gencruel.FAMS}
    except Exception:  # noqa: BLE001
        pass
    new = {sl: [] for sl in lines}
    nd = nm = nchk = 0
    out_of_time = False
    for d in dirs:
        if time.time() - t0 > budget:
            out_of_time = True
            break
        oj = os.path.join(d, "otf.json")
        try:
            mt = os.path.getmtime(oj)
            meta = json.load(open(oj))
        except (OSError, ValueError):
            continue
        rec = sst.get(d) or {}
        if rec.get("mt") == mt and set(allf) <= set(rec.get("fams", [])):
            continue
        excl = {sl for sl in lines if _excl_dir(d, sl)}
        nd += 1
        complete = True
        for m in meta.get("maps", []):
            if time.time() - t0 > budget:
                complete, out_of_time = False, True
                break
            nmn = m.get("name", "")
            sd = str(m.get("seed") or nmn)  # the famcache key
            path = os.path.join(d, nmn + ".map26a")
            if not nmn.startswith("fm_") or nmn in held or not os.path.exists(path):
                continue
            want = [sl for sl in lines if sl not in excl and sd not in have[sl] and f"fm_h{sd}" not in have[sl]
                    and nmn not in picked[sl][0] and sd not in picked[sl][1]]
            if not want:
                continue
            fams = sorted(set().union(*[lines[sl]["fams"] for sl in want]))
            nm += 1
            lab = (m.get("labels") or {}).get("fam")
            res = {f: m.get("family") == f or lab == f for f in fams if f in lab_only}
            res["w_any"] = True  # 12 Nov (b2136 BKY): --rare-fams w_any = every family; the slug's class filter (rarebank_class.tsv) decides
            chk = [f for f in fams if f not in lab_only and f != "w_any"]
            if chk:
                c = R._fc_load().get(str(m.get("seed") or m.get("name")), {})
                nchk += any(f not in c and m.get("family") != f for f in chk)
                res.update(R.fams_of(path, m, chk))
            for sl in want:
                hit = [f for f in sorted(lines[sl]["fams"]) if res.get(f)]
                if not hit or not class_ok(sl, path):
                    continue
                have[sl].add(sd)
                new[sl].append(dict(seed=sd, name=f"fm_h{sd}", fam=(m.get("family") or lab or "normal") if hit[0] == "w_any" else hit[0], src=d, src_name=nmn, t=time.time(), meta=m))
        if complete:
            sst[d] = dict(mt=mt, fams=allf)
    R._fc_save()
    if not dry:
        for sl, lst in new.items():
            with Lock(sl):
                idx = load(sl)
                md = os.path.join(bank_dir(sl), "maps")
                os.makedirs(md, exist_ok=True)
                k = 0
                # 13 Nov (TB: lbb512s/mzs1rs took 106k w_any maps against targets of 11k/1.4k in one tick): link at most
                # RAREBANK_CAP_MULT (2) x the line's target of unused maps; the rest stay in their common read
                try:
                    cap_ = int(float(os.environ.get("RAREBANK_CAP_MULT", "2")) * target(sl, lines[sl]["rare"], sorted(lines[sl]["bots"] or {sl})[0],
                                                                                         live_bot(), confirm=lines[sl].get("confirm", False), idx=idx)[0])
                except Exception:  # noqa: BLE001
                    cap_ = 3000
                room = max(0, cap_ - len(avail(sl, idx)))
                for e in lst:
                    if k >= room:
                        break
                    if e["seed"] in idx["maps"] or e["seed"] in idx["consumed"]:
                        continue
                    dst = os.path.join(md, e["name"] + ".map26a")
                    try:
                        os.link(os.path.join(e["src"], e["src_name"] + ".map26a"), dst)
                    except FileExistsError:
                        pass
                    except OSError:
                        continue  # the common read removed it meanwhile (never copied: hard links only)
                    idx["maps"][e["seed"]] = dict(name=e["name"], fam=e["fam"], src=e["src"], src_name=e["src_name"], t=e["t"],
                                                  meta=dict(e["meta"], name=e["name"], labels=dict(e["meta"].get("labels") or {},
                                                                                                   banked=os.path.basename(e["src"]), hfam=e["fam"])))
                    k += 1
                idx["fams"] = sorted(lines[sl]["fams"])
                idx["rare"] = lines[sl]["rare"]
                idx["bots"] = sorted(set(idx.get("bots", [])) | lines[sl]["bots"])
                idx.setdefault("waiting_since", time.time())
                idx["last_seen_waiting"] = time.time()
                h = idx.get("hist", [])
                if k or not h or time.time() - h[-1][0] > 600:  # growth/h: one point per change, else one per 10 min
                    idx["hist"] = (h + [[time.time(), len(idx["maps"])]])[-500:]
                save(sl, idx)
                new[sl] = k
        os.makedirs(ROOT, exist_ok=True)
        cut = time.time() - 86400
        sst = {d: v for d, v in sst.items() if os.path.exists(d) or v.get("mt", 0) > cut}
        json.dump(sst, open(sst_p + f".{os.getpid()}", "w"))
        os.replace(sst_p + f".{os.getpid()}", sst_p)
    else:
        new = {sl: len(v) for sl, v in new.items()}
    log(f"scan{' (dry)' if dry else ''}: label match only for {','.join(sorted(lab_only)) or 'none'}; {nd} dirs, {nm} candidate maps ({nchk} family-checked), {time.time() - t0:.0f} s"
        f"{' (time budget hit: the rest next tick)' if out_of_time else ''}; new: "
        + (", ".join(f"{sl} +{k}" for sl, k in new.items()) or "none"), quiet=not dry and not any(new.values()))
    return new


def hook_dir(mdir, log=None):
    """stylepanel: a finished read is about to delete its maps: bank what fits now. Never raises."""
    try:
        if not on() or not os.path.exists(os.path.join(mdir, "otf.json")) or os.path.exists(os.path.join(mdir, "changed.json")):
            return
        lines = waiting_lines()
        if lines:
            scan(lines, budget=float(os.environ.get("RAREBANK_HOOK_S", 30)), dirs=[mdir], log=lambda m, quiet=False: say("hook " + m, quiet=True))
    except Exception as e:  # noqa: BLE001
        say(f"hook {mdir}: {type(e).__name__}: {e}", quiet=True)


# ---------------------------------------------------------------- 2. gate (shipwatch) and draw (changedprobe)
def standing_slugs():
    try:
        return {ln.split("\t")[0].strip() for ln in open(os.path.join(Q, "rarebank_standing.tsv")) if ln.strip() and not ln.startswith("#")}
    except OSError:
        return set()


def gate(name, kv):
    """shipwatch: -> (start?, queue reason or None, extra env). Only rare markers with RAREFAMS, while the bank is on."""
    if kv.get("RARE") and not kv.get("RAREFAMS") and kv.get("CLASS"):
        # 13 Nov (TB, ssa1is: a 1% class drew 257 of 300 maps live in 24,000 tries -> harness): a class line whose slug (or a related slug)
        # has a bank with enough unused maps reads that bank; otherwise it draws class maps live (below)
        try:
            sl_ = slug_of(name)
            # 13 Nov (TB, chbf3s drew live: a re-arm suffix 's'/'r' has an empty bank of its own while its root's bank is full): the slug's
            # own bank or a related one (same root), whichever holds the most unused maps
            best_ = (-1, sl_)
            # 13 Nov (TB, swgfm 15100 drew live: variant slug 'swgfm' has root swgfm, so the full 'swg' bank (960) was not related): also any
            # bank whose name prefixes the slug and whose rarebank_class.tsv row is exactly this line's CLASS (same class maps, same filter)
            try:
                rows_ = [ln.split("\t") for ln in open(CLASS_FILE).read().splitlines() if ln.strip() and not ln.startswith("#")]
                same_ = [r[0].strip() for r in rows_ if len(r) >= 2 and r[1].strip() == kv["CLASS"].strip()
                         and len(r[0].strip()) >= 3 and sl_.startswith(r[0].strip()) and r[0].strip() != sl_]
            except OSError:
                same_ = []
            for c_ in [sl_] + related_banks(sl_) + same_:
                if os.path.isdir(bank_dir(c_)):
                    try:
                        best_ = max(best_, (len(avail(c_, load(c_))), c_))
                    except Exception:  # noqa: BLE001
                        pass
            sl_ = best_[1]
            idx_ = load(sl_)
            # 13 Nov 17:3xZ (TB, cgb898rsiis 15297 kept 407 of 420 changed maps under its TRUNK, then waited for 435 NEW maps): a TRUNK-mode
            # read resumes under its trunk, as on the plain path below
            b_ = kv["TRUNK"] if kv.get("TRUNK") and resume_of(idx_, name, kv["TRUNK"]) else live_bot()
            t_, _ = target(sl_, kv["RARE"], name, b_, confirm="CONFIRM_FROM" in kv, idx=idx_)
            n_ = len(avail(sl_, idx_))
            if n_ >= t_:
                return True, None, {"CP_RAREBANK": bank_dir(sl_), "SP_CHANGED_TARGETED_ONLY": "1", "SP_CHANGED_WFAMS": "w_any"}
            # 13 Nov (TB, kvm1 14929: a ~0.5% class drew live, 36 of 300 maps in 7,500 tries, and ended INCONCLUSIVE while its bank was being
            # generated): a class line whose bank is being FILLED (stamped for generation, or a standing harvest) waits for it instead
            if os.path.isdir(bank_dir(sl_)) and (gen_allowed(sl_) or sl_ in standing_slugs() or gen_allowed(slug_root(sl_))):
                return False, f"class bank {n_} of {t_} maps (being filled: classfill/harvest)", {}
        except Exception:  # noqa: BLE001  the bank is a shortcut: any trouble -> the live class draw
            pass
    if kv.get("RARE") and not kv.get("RAREFAMS") and (kv.get("CLASS") or kv.get("BASEHAS")):
        # 13 Nov (TB, Builder: pgr58 --class altgrp1 sat at 'rare bank 0 of 840'): a class or base-has line with no families draws its maps
        # live (stylepanel --class / draftstock), as before 13 Nov; only a plain rare line defaults to a w_any bank
        return True, None, {}
    if kv.get("RARE") and not kv.get("RAREFAMS") and os.environ.get("ARMQ_RARE_BANK", "1") == "1":
        # 13 Nov (TB, 14013 jka1bsi 'bank re-read' probed the POOL 45+ min: re-armed copies (trunk merges, void re-queues) carry no RAREFAMS,
        # so armq's 12 Nov default (a rare line with no families banks w_any) never reached them): the same default here, for every path
        kv = dict(kv, RAREFAMS="w_any")
    if not on() or not kv.get("RARE") or not kv.get("RAREFAMS"):
        return True, None, {}
    sl = slug_of(name)
    if gen_allowed(sl):
        return True, None, {}
    idx = load(sl)
    base = live_bot()  # 11 Nov (TB 6ad907: hmx1ps kept 397 changed maps but the gate asked for a fresh 6,354): a TRUNK-mode read saves its
    if kv.get("TRUNK") and resume_of(idx, name, kv["TRUNK"]):  # resume under its trunk (CAND v TRUNK), not under live
        base = kv["TRUNK"]
    t, why = target(sl, kv["RARE"], name, base, confirm="CONFIRM_FROM" in kv, idx=idx)
    a = len(avail(sl, idx))
    if not idx.get("waiting_since") or idx.get("last_seen_waiting", 0) < time.time() - 3600:
        with Lock(sl):
            idx = load(sl)
            idx.setdefault("waiting_since", time.time())
            idx["last_seen_waiting"] = time.time()
            idx["fams"] = sorted(set(kv["RAREFAMS"].split(",")))
            idx["rare"] = kv["RARE"]
            save(sl, idx)
    if a < t:
        return False, f"rare bank {a} of {t} maps ({why}; bq/rarebank_ON)", {}
    # 13 Nov (TB, 14342 jka1bs probed the POOL with a full 2,079-map bank: changedprobe uses the bank only when SP_CHANGED_WFAMS is set, which
    # shipcheck takes from a RAREFAMS marker; the w_any default above had none): pass the families with the bank
    return True, None, {"CP_RAREBANK": bank_dir(sl), "SP_CHANGED_TARGETED_ONLY": "1", "SP_CHANGED_WFAMS": kv["RAREFAMS"]}


def draw(bank, bdir, nn, tag, have=()):
    """changedprobe.draw in bank mode: up to NN unused bank maps hard-linked into BDIR (consumed for the slug) -> (meta, err)."""
    sl = bank.rstrip("/")
    os.makedirs(bdir, exist_ok=True)
    with Lock(sl):
        idx = load(sl)
        av = sorted(avail(sl, idx), key=lambda s: hashlib.sha1(s.encode()).hexdigest())  # order fixed, not by time banked
        got = []
        for s in av:
            if len(got) >= nn:
                break
            e = idx["maps"][s]
            if e["name"] in have:
                continue
            try:
                os.link(os.path.join(bank, "maps", e["name"] + ".map26a"), os.path.join(bdir, e["name"] + ".map26a"))
            except FileExistsError:
                pass
            except OSError:
                continue
            idx["consumed"][s] = tag
            got.append(e.get("meta") or dict(name=e["name"], seed=s, labels=dict(hfam=e["fam"])))
        save(sl, idx)
    if not got:
        return None, f"rare bank exhausted: no unused maps left in {bank} (BANK SHORT)"
    meta = dict(maps=got, rarebank=dict(bank=bank, drawn=len(got), left=len(av) - len(got)))
    json.dump(meta, open(os.path.join(bdir, "otf.json"), "w"))
    return meta, None


def seed_resume(bank, outdir, cand, base, log=say):
    """changedprobe.build, bank mode, before anything: a saved short read of the same CAND v the same BASE fills OUTDIR (kept changed maps
    hard-linked), so the probe goes on from it."""
    sl = bank.rstrip("/")
    if os.path.exists(os.path.join(outdir, "changed.json")):
        return False
    idx = load(sl)
    r = resume_of(idx, cand, base)
    if not r:
        return False
    st = json.load(open(os.path.join(r["dir"], "changed.json")))
    meta = json.load(open(os.path.join(r["dir"], "otf.json")))
    for m in meta.get("maps", []):
        try:
            os.link(os.path.join(r["dir"], m["name"] + ".map26a"), os.path.join(outdir, m["name"] + ".map26a"))
        except FileExistsError:
            pass
    for k in ("done", "stopped", "bank_short"):
        st.pop(k, None)
    json.dump(st, open(os.path.join(outdir, "changed.json"), "w"))
    json.dump(meta, open(os.path.join(outdir, "otf.json"), "w"))
    log(f"rare bank: resumed {r['kept']} kept changed maps ({len(st.get('maps', {}))} probed) of the short read {r.get('tag')}")
    return True


def record_read(bank, tag, cand, base, st, meta):
    """changedprobe.build end, bank mode: the read's changed share on bank maps (targeted maps) for the slug's next target."""
    sl = bank.rstrip("/")
    tg = [m for m in st.get("maps", {}).values() if m.get("targeted")]
    with Lock(sl):
        idx = load(sl)
        res = resume_of(idx, cand, base)  # a resumed read holds the short read's maps: that read is replaced, not counted twice
        reads = [r for r in idx.get("reads", []) if (r.get("tag") != tag or r.get("cand") != cand) and not (res and r.get("tag") == res.get("tag"))]
        if res and not st.get("bank_short"):
            idx["resume"] = None  # the read reached its n: nothing to resume
        reads.append(dict(tag=tag, cand=cand, base=base, probed=len(tg), changed=sum(bool(m["changed"]) for m in tg),
                          kept=len(meta["maps"]) if meta else 0, short=bool(st.get("bank_short")), t=time.time()))
        idx["reads"] = reads
        # 11 Nov (TB 6ad907: rgp1vs drew 901 bank maps, probed 301, and the other 600 were lost): maps this read drew but never played
        # (not in st["maps"]: not reached before the stop, or came back unread) go back to the bank
        played = set(st.get("maps", {}))
        back = [sd for sd, t in list(idx.get("consumed", {}).items()) if t == tag and idx["maps"].get(sd, {}).get("name") not in played]
        for sd in back:
            idx["consumed"].pop(sd, None)
        if back:
            say(f"rare bank {sl}: {len(back)} drawn but unplayed map(s) of read {tag} returned to the bank")
        save(sl, idx)


def save_resume(mdir, tag, cand, base):
    """stylepanel on a bank-short read: keep its probe as the slug's resume (hard links to the kept maps). -> (kept, probed, share)"""
    st = json.load(open(os.path.join(mdir, "changed.json")))
    meta = json.load(open(os.path.join(mdir, "otf.json"))) if os.path.exists(os.path.join(mdir, "otf.json")) else dict(maps=[])
    bank = os.environ.get("CP_RAREBANK", "")
    sl = bank.rstrip("/")
    rd = os.path.join(bank, "resume", f"{tag}_{int(time.time())}")
    os.makedirs(rd, exist_ok=True)
    for m in meta.get("maps", []):
        try:
            os.link(os.path.join(mdir, m["name"] + ".map26a"), os.path.join(rd, m["name"] + ".map26a"))
        except FileExistsError:
            pass
    st2 = {k: v for k, v in st.items() if k not in ("done", "stopped", "bank_short")}
    json.dump(st2, open(os.path.join(rd, "changed.json"), "w"))
    json.dump(meta, open(os.path.join(rd, "otf.json"), "w"))
    json.dump(st2, open(os.path.join(mdir, "changed.json"), "w"))  # the same run tag on the next start resumes in place (stylepanel probes again)
    tg = [m for m in st.get("maps", {}).values() if m.get("targeted")]
    kept, probed, ch = len(meta.get("maps", [])), len(tg), sum(bool(m["changed"]) for m in tg)
    with Lock(sl):
        idx = load(sl)
        idx["resume"] = dict(dir=rd, cand=cand, base=base, tag=tag, kept=kept, probed=probed, t=time.time())
        save(sl, idx)
    return kept, probed, (ch / probed if probed else 0.0)


def bank_wait(cand, tag, live, sp_log, dry=False):
    """shipcheck: the rare read ran out of bank maps. -> the shipcheck text (OVERALL: BANKWAIT); the marker gets a comment line so shipwatch
    sees it again and it waits on its bank."""
    m = re.search(r"RARE BANK SHORT: (.*)", open(sp_log, errors="replace").read()) if os.path.exists(sp_log) else None
    detail = m.group(1).strip() if m else "bank exhausted"
    text = (f"SHIPCHECK {tag}: {cand} vs live {live}, lane rare (bank)\n"
            f"  rare bank            {detail}\n"
            f"  -> back to waiting on its bank (tools/lab/rarebank.py; not INCONCLUSIVE: no re-arm)\n"
            f"  OVERALL: BANKWAIT")
    if not dry:
        mk = os.path.join(REPO, "bots", cand, "SHIPCHECK")
        try:
            with open(mk, "a") as f:
                f.write(f"# rarebank wait {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} tag {tag}: {detail[:120]}\n")
        except OSError as e:
            text += f"\n  !! marker not touched ({e}): re-arm by hand"
        say(f"bank wait {cand} ({tag}): {detail}")
    return text


# ---------------------------------------------------------------- 4. report, status, tick
def rows():
    lines = waiting_lines()
    live = live_bot()
    out = []
    for sl in sorted(set(lines) | {os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(ROOT, "*", "index.json"))}):
        idx = load(sl)
        e = lines.get(sl)
        if not e and idx.get("last_seen_waiting", 0) < time.time() - 6 * 3600:
            continue
        rare = (e or {}).get("rare") or idx.get("rare") or 420
        cand = sorted((e or {}).get("bots") or [None])[-1]
        t, why = target(sl, rare, cand, live, confirm=bool((e or {}).get("confirm")), idx=idx)
        a = len(avail(sl, idx))
        h = idx.get("hist", [])
        cut = time.time() - 6 * 3600
        w = [x for x in h if x[0] >= cut] or h[-1:]
        g = (w[-1][1] - w[0][1]) / max((w[-1][0] - w[0][0]) / 3600, 0.25) if len(w) >= 2 else 0.0
        wh = (time.time() - idx["waiting_since"]) / 3600 if idx.get("waiting_since") else 0.0
        slow = bool(e) and a < t and wh >= float(os.environ.get("RAREBANK_SLOW_H", 2)) and g < 0.01 * t
        out.append(dict(slug=sl, fams=sorted((e or {}).get("fams") or idx.get("fams", [])), n=a, target=t, why=why, growth=g, waiting_h=wh,
                        slow=slow, waiting=bool(e), bots=sorted((e or {}).get("bots") or []), reads=len(idx.get("reads", []))))
    return out


def status():
    print(f"rarebank: {'ON' if on() else 'OFF'} ({Q}/rarebank_ON); generation for rare lines: "
          f"{'ON (rare_generate_ON)' if gen_allowed() else 'off'}; approved slugs: {Q}/rare_generate_ok.txt; root {ROOT}")
    rs = rows()
    if not rs:
        print("no waiting rare line with families")
    for r in rs:
        print(f"{r['slug']:16s} {'WAITING' if r['waiting'] else 'idle   '} bank {r['n']:5d} / target {r['target']:5d}  growth {r['growth']:7.1f}/h  "
              f"waiting {r['waiting_h']:5.1f} h{'  SLOW' if r['slow'] else ''}  fams {','.join(r['fams'])}  [{r['why']}; {r['reads']} earlier bank reads]")


def report():
    rs = rows()
    L = [f"rarebank report {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} (tools/lab/rarebank.py; refreshed hourly while lines wait)",
         "SLOW = bank grows under 1%/h of its target: no common set produces these families. Approve generation for one slug: add the slug to "
         f"{Q}/rare_generate_ok.txt", "slug\tfamilies\tbank_n\ttarget\tgrowth_per_h\thours_waiting\tslow"]
    for r in rs:
        if r["waiting"]:
            L.append(f"{r['slug']}\t{','.join(r['fams'])}\t{r['n']}\t{r['target']}\t{r['growth']:.1f}\t{r['waiting_h']:.1f}\t{'SLOW' if r['slow'] else '-'}")
    p = os.path.join(Q, "rarebank_report.txt")
    open(p + ".part", "w").write("\n".join(L) + "\n")
    os.replace(p + ".part", p)
    return L


def prune():
    """Banks of lines gone > RAREBANK_KEEP_H (48) h, and resume dirs of older reads: removed via rmdata.sh (hard links: our copies only)."""
    keep_h = float(os.environ.get("RAREBANK_KEEP_H", 48))
    lines = waiting_lines()
    paths = []
    for p in glob.glob(os.path.join(ROOT, "*", "index.json")):
        sl = os.path.basename(os.path.dirname(p))
        idx = load(sl)
        # 13 Nov (TB: at 01:46Z this deleted jkcf, zgs32, elong8, lce2 and jka4b: rarefill's banks carry no 'created' / 'last_seen_waiting',
        # so they read as age 0 and went at the first prune before any line was armed): the bank's age is its NEWEST sign of life (index,
        # fill log, those fields), and a slug stamped in rare_generate_ok.txt (being filled for a line) is never pruned
        seen = max([idx.get("last_seen_waiting", 0), idx.get("created", 0)]
                   + [os.path.getmtime(x) for x in (p, os.path.join(ROOT, sl + ".fill.log")) if os.path.exists(x)])
        if sl not in lines and not gen_allowed(sl) and seen < time.time() - keep_h * 3600:
            paths.append(bank_dir(sl))
            continue
        cur = (idx.get("resume") or {}).get("dir")
        for d in glob.glob(os.path.join(bank_dir(sl), "resume", "*")):
            if d != cur and os.path.getmtime(d) < time.time() - keep_h * 3600:
                paths.append(d)
    if not paths:
        return 0
    lf = os.path.join(ROOT, f"prune_{os.getpid()}.txt")
    open(lf, "w").write("\n".join(paths) + "\n")
    r = subprocess.run(["sh", os.path.join(LAB, "rmdata.sh"), lf], capture_output=True, text=True)
    say(f"prune: {len(paths)} paths via rmdata.sh rc {r.returncode}")
    try:
        os.remove(lf)
    except OSError:
        pass
    return len(paths)


def tick(dry=False):
    if not on() and not dry:
        return
    os.makedirs(ROOT, exist_ok=True)
    lk = open(os.path.join(ROOT, ".tick.lock"), "a")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # a tick is still running
    lines = waiting_lines()
    if lines:
        scan(lines, dry=dry)
    if dry:
        return
    stamp = os.path.join(ROOT, ".report_at")
    try:
        last = os.path.getmtime(stamp)
    except OSError:
        last = 0
    if time.time() - last > 3600:
        open(stamp, "w").close()
        report()
        prune()


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else "status"
    if cmd == "status":
        return status()
    if cmd == "tick":
        return tick(dry="--dry" in a)
    if cmd == "report":
        print("\n".join(report()))
        return
    if cmd == "gate":
        kv = parse_marker(os.path.join(REPO, "bots", a[1], "SHIPCHECK"))
        print(gate(a[1], kv))
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
