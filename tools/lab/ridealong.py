"""ridealong: rare bits read on maps the common reads already make. Tool Builder, 10 Nov (owner ~20:52Z: "test rare issues combined with
more common ones ... so we don't waste time creating more new maps than necessary"; ~21:10Z: "when we generate random maps for the common
stuff we also see if it fits the rare stuff, that way we don't double generate").

OFF unless /data/USER/st/bq/ridealong_ON exists (the HARVEST part also runs under its own switch bq/rarereuse_ON). Absent: every caller's
hook returns at once and nothing here runs; shipcheck, fixbatch and changedprobe decide exactly as before.

A. HARVEST (changedprobe --wfams, i.e. a rare line with --rare-fams): before a targeted batch generates family maps, harvest() takes maps
   from the CURRENT common fresh sets (dirs with otf.json + .map26a modified < RIDE_HARVEST_H (6) h: /data/USER/st/panel/*,
   /data/USER/st/gate/*, /data/USER/otf_tmp/*, RIDE_HARVEST_DIRS globs) that have the family's property: a map built by that family
   (its otf label 'family') or one whose built map passes genweird.check(FAM, ...) (the family's own _ck_ test, gencruel's CHECKS
   included) after the .map26a is decoded back into a genmaps.Map. Only the shortfall is generated. A family whose check is vacuous on a
   built map (w_dashgolem, w_bushaltar, families with no test) is matched by label only. Never: maps of a changed-map read
   (otf.json with changed_probe), the line's own earlier probe maps (panel/*/changed.json of the same slug, by name and seed), a fresh
   dir whose condab summary names the line's own bot, held-out maps (gen_*, heldout lists), a map already in this probe. A harvested map
   is HARD-LINKED (never copied, never moved: the common read still owns it) as fm_h<seed>.map26a, labels harvested=<dir>, hfam=<fam>.
   Family checks are cached per map seed in WORK/famcache.json. Time budget per batch RIDE_HARVEST_S (90) s.
B. RIDE-ALONG (owner 10 Nov ~20:52Z). A rare line (armq --rare N, lane fix, no --shadow / --base-has) whose slug is in bq/ridealong_pick.txt
   ('*' = all) or whose armq row has "ride": true is taken into the next fixbatch bundle as its own flag value (fixbatch.release: at most
   RIDE_MAX (2), flips that clash with the bundle's are left out, the line is dropped from armq.txt and the bundle's riders go to
   bq/ridealong_bundles.json). The bundle is read as usual, on its lane's bars; the riders never enter its verdict.
   TWIN LEG: shipcheck (main and CONFIRM MODE) calls twin_start(): when the candidate has riders (env RIDEALONG, a marker line
   RIDEALONG=slug:F=V,G=W;slug2:H=1, or the registry by bundle slug, so rebases _r<ver> and requeues keep them), ONE detached process
   (`ridealong.py twin CAND LIVE RTAG TAG LANE`, log bq/ridealong_twin_TAG.log) waits for the check's own fresh maps
   (panel/<RTAG>/otf.json + .map26a), hard-links them away (the fresh read deletes its maps at the end), and per rider X: TWIN = flip.sh
   CAND nova_rt<RTAG>_<slug> 'X's flags at live's values' (code IDENTICAL by wsec; a flag live lacks takes the trunk's value, else 0),
   both libraries from that one wasm, CAND v TWIN both seats on every map via changedprobe.play (pilots, node-side replay hash, prio
   RIDE_PRIO 9). Both games byte-identical <=> X did not touch the game (changedprobe's rule). Changed maps give X's score.
   LEDGER bq/ridealong.json per bit: every changed map (seed key, map, score, check TAG, bundle, base, version, matching rare families of
   watched_fams()) and every read (changed, unchanged, point, z, per-family counts); never maps the bit was picked on (its own changed-map
   probes, by name and seed) or held-out maps; the same seed counts once; reads on different bases pool (base noted per map).
   VERDICT at RIDE_RARE_N (420 = shipcheck's max(N, 1.05 x min of bq/rarebar.txt)) pooled changed maps: point > .50 and LOS >= 95%
   (shipcheck.rare_rows' rule). PASS: a PENDING line (ships inside its bundle if that ships; else arm it alone, the command given). FAIL:
   status FAIL (never rides again) + the failed-positive bank (flagscreen bank add <slug>_ra). DRAG: one twin read with >= 100 changed
   maps, point < .50 and z <= -2 marks drop_next: the bit leaves the NEXT bundle build (never the reverse); so does a twin read with over
   50% of >= 50 maps changed (changedprobe's NOT_RARE: a common change reads on its own lane). Report bq/ridealong_TAG.txt,
   log bq/ridealong.log. RIDEALONG_DRY=1: no bank, no PENDING line.
CLI: python3 -I tools/lab/ridealong.py harvest-test FAMS N [OUTDIR]   (a dry harvest into a scratch dir; nothing else is touched)
     python3 -I tools/lab/ridealong.py status                         (the ledger and the bundle registry)
     python3 -I tools/lab/ridealong.py settle SLUG                    (re-apply the verdict to one bit)
     python3 -I tools/lab/ridealong.py twin CAND LIVE RTAG TAG LANE   (what shipcheck starts)
Env for tests: RIDEALONG_Q (the bq dir), RIDEALONG_WORK, RIDE_PANEL (the fresh-map root), RIDEALONG_DRY=1.
"""
import glob
import json
import math
import os
import re
import shutil
import sys
import threading
import time

LAB = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(LAB))
sys.path.insert(0, LAB)
Q = os.environ.get("RIDEALONG_Q", "/data/USER/st/bq")
WORK = os.environ.get("RIDEALONG_WORK", "/data/USER/st/ridealong")
PANEL = "/data/USER/st/panel"
HARVEST_ROOTS = ["/data/USER/st/panel/*", "/data/USER/st/gate/*", "/data/USER/st/gate/*/*", "/data/USER/otf_tmp/*"]
HELDOUT_LISTS = ["/data/USER/st/fl/fb2/heldout.txt"]
VACUOUS = {"w_dashgolem", "w_bushaltar"}  # genweird CHECK2 lambdas that accept any map: label match only


def on():
    return os.path.exists(os.path.join(Q, "ridealong_ON"))


def harvest_on():
    return on() or os.path.exists(os.path.join(Q, "rarereuse_ON"))


def say(msg):
    print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} ridealong: {msg}", flush=True)


# ---------------------------------------------------------------- A. family checks on built maps
_FC = {}
_HV_LOCK = threading.Lock()  # changedprobe runs up to CP_PAR batches in threads: one harvest at a time, so two never take one map


def _fc_load():
    if "d" not in _FC:
        try:
            _FC["d"] = json.load(open(os.path.join(WORK, "famcache.json")))
        except (OSError, ValueError):
            _FC["d"] = {}
        _FC["new"] = 0
    return _FC["d"]


def _fc_save():
    if not _FC.get("new"):
        return
    os.makedirs(WORK, exist_ok=True)
    p = os.path.join(WORK, f"famcache.json.{os.getpid()}")
    try:  # merge with what another process wrote meanwhile
        cur = json.load(open(os.path.join(WORK, "famcache.json")))
    except (OSError, ValueError):
        cur = {}
    for k, v in _FC["d"].items():
        cur.setdefault(k, {}).update(v)
    if len(cur) > 200000:  # keep it bounded: the newest half
        cur = dict(list(cur.items())[-100000:])
    json.dump(cur, open(p, "w"))
    os.replace(p, os.path.join(WORK, "famcache.json"))
    _FC["d"], _FC["new"] = cur, 0


@__import__("functools").lru_cache(maxsize=None)
def checkable(fam):
    """True when genweird.check has a real test for FAM on a built map."""
    import inspect
    import genweird as W
    import gencruel
    if fam in VACUOUS:
        return False
    if fam in gencruel.CHECKS or fam in W.CHECK2:
        return True
    return f'"{fam}"' in inspect.getsource(W.check)


def map_of(path):
    """A built .map26a -> (genmaps.Map, features) as genweird.build_one has them (groups/protect: none, a built map has no generator notes)."""
    import genmaps as G
    import genfam as NF
    import map26a
    import mapfeat
    d = map26a.load(path)
    m = G.Map(d["W"], d["H"], d["symmetry"], d["champs_per_team"])
    for k, v in (("wall", G.WALL), ("hole", G.HOLE), ("bush", G.BUSH), ("altar", G.ALTAR)):
        for x, y in d[k]:
            m.g[y * m.W + x] = v
    m.camp = dict(d["camps"])
    m.spawn = tuple(d["spawnA_rect"])
    m.altars = sorted(d["altar"])
    f = mapfeat.analyse(d, os.path.basename(path))
    return m, dict(f, **NF.extfeat(d))


def fams_of(path, meta, fams):
    """-> {fam: True/False} for FAMS on the map at PATH (otf entry META): its own family label, else the family's check (cached by seed)."""
    import genweird as W
    key = str(meta.get("seed") or meta.get("name"))
    c = _fc_load().setdefault(key, {})
    out, todo = {}, []
    for fam in fams:
        if meta.get("family") == fam or (meta.get("labels") or {}).get("fam") == fam:
            out[fam] = True
        elif fam in c:
            out[fam] = c[fam]
        elif not checkable(fam):
            out[fam] = False
        else:
            todo.append(fam)
    if todo:
        try:
            m, f = map_of(path)
        except Exception:  # noqa: BLE001  unreadable map: no match
            m = None
        for fam in todo:
            ok = False
            if m is not None:
                try:
                    ok = W.check(fam, m, f, f) is None
                except Exception:  # noqa: BLE001  a check needing generator notes (m.groups kinds): no match
                    ok = False
            out[fam] = c[fam] = ok
        _FC["new"] = _FC.get("new", 0) + 1
    return out


def heldout_names():
    out = set()
    for p in HELDOUT_LISTS:
        try:
            out |= {ln.strip() for ln in open(p) if ln.strip()}
        except OSError:
            pass
    return out


def base_slug(bot):
    """nova_b11600_hlr1s_r712 / ..._hlr1si -> hlr1s (rebases and requeues keep the line's slug as a prefix)"""
    s = bot.split("_", 2)[-1] if bot.startswith("nova_b") else bot
    return re.sub(r"_r\d+.*$", "", s.split("_")[0])


def own_picked(bot):
    """-> (names, seeds) of maps the line BOT was picked on: every changed-map probe of the same slug (panel/*/changed.json, otf.json)."""
    sl = base_slug(bot)
    names, seeds = set(), set()
    if not sl:
        return names, seeds
    for pj in glob.glob(f"{PANEL}/*/changed.json"):
        try:
            st = json.load(open(pj))
        except (OSError, ValueError):
            continue
        if base_slug(str(st.get("cand", ""))) != sl:
            continue
        names |= set(st.get("maps", {}))
        try:
            seeds |= {str(m.get("seed")) for m in json.load(open(os.path.join(os.path.dirname(pj), "otf.json")))["maps"]}
        except (OSError, ValueError, KeyError):
            pass
    seeds |= {n[4:] for n in names if n.startswith("fm_h")}
    return names, seeds


def fresh_dirs(max_h=None, exclude_bot=None):
    """Common fresh sets now on disk: otf.json + .map26a, modified < max_h h; never a changed-map read's dir; never one the line itself played."""
    max_h = float(os.environ.get("RIDE_HARVEST_H", 6)) if max_h is None else max_h
    roots = HARVEST_ROOTS + [x for x in os.environ.get("RIDE_HARVEST_DIRS", "").split(":") if x]
    cut, out, seen = time.time() - 3600 * max_h, [], set()
    sl = base_slug(exclude_bot) if exclude_bot else None
    for r in roots:
        for d in glob.glob(r):
            oj = os.path.join(d, "otf.json")
            try:
                if d in seen or os.path.getmtime(oj) < cut or os.path.exists(os.path.join(d, "changed.json")):
                    continue
            except OSError:
                continue
            seen.add(d)
            if sl:  # the line's own fresh read (an inforead / gate of the same bot): its maps are its own picks
                head = ""
                try:
                    head = open(os.path.join(Q, f"fp{os.path.basename(d)}.condor.txt")).read(3000)
                except OSError:
                    pass
                if re.search(rf"nova_b\d+_{re.escape(sl)}(?![a-z0-9])", head):  # 11 Nov: \b missed a rebased bot (nova_b123_slug_r717)
                    continue
            out.append(d)
    return sorted(out, key=lambda d: -os.path.getmtime(os.path.join(d, "otf.json")))


def harvest(bdir, nn, wfams, tag, own_bot=None, have=(), log=say):
    """Up to NN maps with any of WFAMS' properties from the common fresh sets, hard-linked into BDIR -> list of otf entries (renamed fm_h<seed>).
    HAVE: names already in the probe. Never raises: a failure returns what it has."""
    with _HV_LOCK:
        return _harvest(bdir, nn, wfams, tag, own_bot, have, log)


def _fams_job(args):
    path, meta, fams = args
    _FC["d"] = {}  # a worker: no cache of its own; the parent merges
    try:
        return fams_of(path, meta, fams)
    except Exception:  # noqa: BLE001
        return {f: False for f in fams}


def _harvest(bdir, nn, wfams, tag, own_bot, have, log):
    fams = [f for f in (wfams or "").split(",") if f]
    if not fams or nn <= 0:
        return []
    os.makedirs(bdir, exist_ok=True)
    t0, budget = time.time(), float(os.environ.get("RIDE_HARVEST_S", 90))
    par = max(1, int(os.environ.get("RIDE_HARVEST_PAR", 4)))
    try:  # 11 Nov (TB 6ad907: load 64; rare checks' harvest pools held 4 local workers each): 2 workers above load 30, 1 above 40
        ld = os.getloadavg()[0]
        par = min(par, 1 if ld > float(os.environ.get("RIDE_HARVEST_LOAD1", 40)) else 2 if ld > float(os.environ.get("RIDE_HARVEST_LOAD2", 30)) else par)
    except OSError:
        pass
    names, seeds = own_picked(own_bot) if own_bot else (set(), set())
    held = heldout_names()
    used = _used_load()
    cache = _fc_load()
    rate = {f: [0, 0] for f in fams}  # {fam: [maps checked, hits]} over the cache: a family the common sets almost never hold is matched by label only
    for v in cache.values():
        for f in fams:
            if f in v:
                rate[f][0] += 1
                rate[f][1] += bool(v[f])
    minr, minn = float(os.environ.get("RIDE_HARVEST_MINRATE", 0.005)), int(os.environ.get("RIDE_HARVEST_RATE_N", 1000))
    lab_only = {f for f in fams if not checkable(f) or (rate.get(f, [0, 0])[0] >= minn and rate[f][1] < minr * rate[f][0])}
    if lab_only:
        log(f"harvest: {','.join(sorted(lab_only))}: label match only (no check, or hit rate under {100 * minr:g}% on >= {minn} checked maps)")
    chk = [f for f in fams if f not in lab_only]
    got, scanned, tried, computed = [], 0, 0, 0

    def cands():
        for d in fresh_dirs(exclude_bot=own_bot):
            try:
                meta = json.load(open(os.path.join(d, "otf.json")))
            except (OSError, ValueError):
                continue
            for m in meta.get("maps", []):
                yield d, m

    def take(d, m, res):
        nm, sd = m.get("name", ""), str(m.get("seed"))
        hit = [f for f in fams if res.get(f)]
        if not hit:
            return
        new = f"fm_h{sd}"
        src, dst = os.path.join(d, nm + ".map26a"), os.path.join(bdir, new + ".map26a")
        try:
            os.link(src, dst)
        except FileExistsError:
            return
        except OSError:  # the common read removed it meanwhile, or another file system
            try:
                shutil.copyfile(src, dst)
            except OSError:
                return
        got.append(dict(m, name=new, labels=dict(m.get("labels") or {}, harvested=os.path.basename(d), hfam=hit[0]), harvested_from=f"{d}/{nm}"))
        used[f"{tag}:{sd}"] = time.time()

    pool = None
    try:
        it, taken = cands(), set()
        while len(got) < nn and time.time() - t0 <= budget:
            chunk = []
            for d, m in it:
                nm, sd = m.get("name", ""), str(m.get("seed"))
                scanned += 1
                if (not nm.startswith("fm_") or nm in held or nm in names or sd in seeds or f"fm_h{sd}" in have or nm in have or sd in taken
                        or f"{tag}:{sd}" in used or not os.path.exists(os.path.join(d, nm + ".map26a"))):
                    continue
                taken.add(sd)
                chunk.append((d, m))
                if len(chunk) >= 16 * par:
                    break
            if not chunk:
                break
            tried += len(chunk)
            res = {}
            todo = []
            for d, m in chunk:
                key = str(m.get("seed") or m.get("name"))
                c = cache.get(key, {})
                if m.get("family") in fams or all(f in c for f in chk):
                    res[key] = {f: (m.get("family") == f) or (f in chk and c.get(f, False)) for f in fams}
                else:
                    todo.append((os.path.join(d, m["name"] + ".map26a"), m, chk))
            if todo:
                computed += len(todo)
                if par > 1 and len(todo) > 4:
                    if pool is None:
                        from concurrent.futures import ProcessPoolExecutor
                        pool = ProcessPoolExecutor(par)
                    outs = list(pool.map(_fams_job, todo))
                else:
                    outs = [_fams_job(x) for x in todo]
                for (path, m, _), o in zip(todo, outs):
                    key = str(m.get("seed") or m.get("name"))
                    res[key] = o
                    cache.setdefault(key, {}).update({f: v for f, v in o.items() if m.get("family") != f})

                _FC["new"] = _FC.get("new", 0) + len(todo)
            for d, m in chunk:
                if len(got) < nn:
                    take(d, m, res.get(str(m.get("seed") or m.get("name")), {}))
    except Exception as e:  # noqa: BLE001  never break the probe: generate instead
        log(f"harvest: {type(e).__name__}: {e}")
    finally:
        if pool is not None:
            pool.shutdown(cancel_futures=True)
    _fc_save()
    _used_save(used)
    log(f"harvest {','.join(fams)}: {len(got)} of {nn} maps from common fresh sets ({tried} candidates, {computed} checked, {scanned} seen) "
        f"in {time.time() - t0:.0f} s")
    return got


def _used_load():
    try:
        return json.load(open(os.path.join(WORK, "harvest_used.json")))
    except (OSError, ValueError):
        return {}


def _used_save(u):
    os.makedirs(WORK, exist_ok=True)
    cut = time.time() - 7 * 86400
    u = {k: v for k, v in u.items() if v >= cut}
    p = os.path.join(WORK, f"harvest_used.json.{os.getpid()}")
    try:
        cur = json.load(open(os.path.join(WORK, "harvest_used.json")))
    except (OSError, ValueError):
        cur = {}
    cur.update(u)
    json.dump({k: v for k, v in cur.items() if v >= cut}, open(p, "w"))
    os.replace(p, os.path.join(WORK, "harvest_used.json"))


def draw_with_harvest(bdir, nn, tag, wfams, gen, own_bot=None, have=(), log=say):
    """changedprobe.draw's targeted batch with the harvest first: GEN(dir, k) -> (otf meta, err) generates k family maps into dir.
    -> (meta, err) in draw's form: BDIR/otf.json holds harvested + generated maps."""
    os.makedirs(bdir, exist_ok=True)
    hv = harvest(bdir, nn, wfams, tag, own_bot=own_bot, have=have, log=log)
    meta, err = {"maps": []}, None
    if len(hv) < nn:
        gdir = os.path.join(bdir, "gen")
        gm, err = gen(gdir, nn - len(hv))
        if gm:
            meta = dict(gm)
            for m in gm.get("maps", []):
                src = os.path.join(gdir, m["name"] + ".map26a")
                if os.path.exists(src):
                    os.replace(src, os.path.join(bdir, m["name"] + ".map26a"))
        shutil.rmtree(gdir, ignore_errors=True)
        if not gm and not hv:
            return None, err
    meta["maps"] = list(meta.get("maps", [])) + hv
    meta["harvest"] = dict(harvested=len(hv), generated=len(meta["maps"]) - len(hv), fams=wfams)
    json.dump(meta, open(os.path.join(bdir, "otf.json"), "w"))
    return meta, None


# ---------------------------------------------------------------- B. ride-along bits: registry, twin leg, ledger, verdict
if os.environ.get("DRY") == "1":  # a DRY shipcheck's twin legs: their own ledger, no bank, no PENDING line
    os.environ["RIDEALONG_DRY"] = "1"
LEDGER = os.path.join(Q, "ridealong_dry.json" if os.environ.get("DRY") == "1" else "ridealong.json")
REGISTRY = os.path.join(Q, "ridealong_bundles.json")
PICK = os.path.join(Q, "ridealong_pick.txt")  # slugs of armq rare lines allowed to ride ('*' = every eligible rare line)
RLOG = os.path.join(Q, "ridealong.log")
RIDE_MAX = int(os.environ.get("RIDE_MAX", 2))  # riders per bundle: each costs one twin leg (2 games a fresh map)
DRAG_N, DRAG_Z = 100, -2.0  # owner brief 10 Nov: a twin read with >= 100 changed maps, point < .50 and z <= -2 drops the bit from the NEXT build
TWIN_PRIO = os.environ.get("RIDE_PRIO", "10")  # 10 Nov: level with ship legs at 10, above Step 0 (9)
PANEL_DIR = os.environ.get("RIDE_PANEL", PANEL)


def rlog(s):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {s}"
    print(line, flush=True)
    try:
        with open(RLOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


class _Lock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        import fcntl
        self.f = open(self.path, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *e):
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _jload(p, default):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return default


def _jsave(p, d):
    t = f"{p}.{os.getpid()}"
    json.dump(d, open(t, "w"), indent=1)
    os.replace(t, p)


def parse_spec(s):
    """'slug:F=V,G=W;slug2:H=1' (marker RIDEALONG=) -> [{slug, flips}] with flips as 'F=V G=W'"""
    out = []
    for part in (s or "").split(";"):
        if ":" in part:
            sl, fl = part.split(":", 1)
            fl = " ".join(x for x in re.split(r"[,\s]+", fl) if "=" in x)
            if sl.strip() and fl:
                out.append(dict(slug=sl.strip(), flips=fl))
    return out


def riders_of(cand):
    """The ride-along bits of CAND: env RIDEALONG, else its marker's RIDEALONG= line, else the bundle registry (fixbatch: by bundle slug, so
    rebases _r<ver> and requeues keep them)."""
    if os.environ.get("RIDEALONG"):
        return parse_spec(os.environ["RIDEALONG"])
    try:
        for ln in open(os.path.join(REPO, "bots", cand, "SHIPCHECK")):
            if ln.startswith("RIDEALONG="):
                return parse_spec(ln.strip().split("=", 1)[1])
    except OSError:
        pass
    reg = _jload(REGISTRY, {})
    sl = cand.split("_", 2)[-1] if cand.startswith("nova_b") else cand
    for k in sorted(reg, key=len, reverse=True):
        if sl == k or sl.startswith(k + "_") or re.fullmatch(re.escape(k) + r"[a-z]?(_.*)?", sl):
            return list(reg[k].get("riders", []))
    return []


def register(bundle_slug, riders):
    with _Lock(REGISTRY + ".lock"):
        reg = _jload(REGISTRY, {})
        reg[bundle_slug] = dict(riders=riders, t=time.time())
        cut = time.time() - 7 * 86400
        _jsave(REGISTRY, {k: v for k, v in reg.items() if v.get("t", 0) >= cut})


def flips_of(s):
    return dict(x.split("=", 1) for x in (s or "").split() if "=" in x)


def define_value(bot, flag):
    """#define FLAG <int> in bots/BOT/src (flip.sh's rule: once), else None."""
    pat = re.compile(rf"^\s*#\s*define\s+{re.escape(flag)}\s+(-?(?:0[xX][0-9a-fA-F]+|\d+))\b", re.M)
    hits = []
    for p in glob.glob(os.path.join(REPO, "bots", bot, "src", "*")):
        if p.endswith((".h", ".cpp", ".cc")):
            try:
                hits += pat.findall(open(p, errors="replace").read())
            except OSError:
                pass
    return str(int(hits[0], 0)) if len(hits) == 1 else None


def revert_values(cand, live, flips):
    """X's flips back at live's values: live's #define, else (a flag live lacks: new donor code) the cand's trunk's, else 0."""
    trunk = (_flipinfo(cand) or {}).get("TRUNK")
    out = {}
    for f in flips_of(flips):
        v = define_value(live, f) if live else None
        if v is None and trunk:
            v = define_value(trunk, f)
        out[f] = v if v is not None else "0"
    return out


def _flipinfo(bot):
    try:
        return dict(ln.split("=", 1) for ln in open(os.path.join(REPO, "bots", bot, "FLIP")).read().splitlines() if "=" in ln)
    except OSError:
        return {}


def eligible_rows(taken_flips, armq_file=None):
    """fixbatch: armq rare lines that may ride the next bundle: lane fix, --rare, no --shadow / --base-has, slug in ridealong_pick.txt (or '*')
    or the row's own 'ride' key, not FAILED / dropped-from-next in the ledger, flips not clashing with TAKEN_FLIPS. -> rows (best first: oldest)."""
    pick = set()
    try:
        pick = {ln.strip() for ln in open(PICK) if ln.strip() and not ln.startswith("#")}
    except OSError:
        pass
    led = _jload(LEDGER, {})
    out, seen = [], dict(taken_flips)
    try:
        rows = [json.loads(x) for x in open(armq_file or os.path.join(Q, "armq.txt")) if x.strip()]
    except (OSError, ValueError):
        rows = []
    for r in rows:
        sl = r.get("slug") or ""
        if not (r.get("rare") and r.get("lane") == "fix" and sl and not r.get("shadow") and not r.get("basehas") and not r.get("cls")):
            continue
        if not (r.get("ride") or sl in pick or "*" in pick):
            continue
        e = led.get(sl, {})
        if e.get("status") in ("FAIL", "PASS") or e.get("drop_next"):
            continue
        f = flips_of(r.get("flips"))
        if not f or any(k in seen and seen[k] != v for k, v in f.items()):
            continue
        seen.update(f)
        out.append(r)
        if len(out) >= RIDE_MAX:
            break
    return out


def rider_of_row(r):
    return dict(slug=r["slug"], flips=r["flips"], donor=r.get("donors") or "-", rare=r.get("rare"), rarefams=r.get("rarefams") or "",
                subject=r.get("subject") or "", bugbar=bool(r.get("bugbar")), row=r)


# ---- the twin leg
def twin_start(cand, live, rtag, tag, lane, log=say):
    """shipcheck hook (ridealong_ON only): one detached process per check plays every rider's twin leg; it never holds the verdict."""
    if not on():
        return None
    rs = riders_of(cand)
    if not rs:
        return None
    import subprocess
    out = os.path.join(Q, f"ridealong_twin_{tag}.log")
    cmd = ["nice", "-n", "10", sys.executable, "-I", os.path.abspath(__file__), "twin", cand, live or "-", rtag, tag, lane]
    p = subprocess.Popen(cmd, cwd=REPO, stdout=open(out, "a"), stderr=subprocess.STDOUT, start_new_session=True)
    log(f"ride-along: {len(rs)} bit(s) ride in {cand} ({', '.join(r['slug'] for r in rs)}): twin legs pid {p.pid}, log {out} (not part of the verdict)")
    return p.pid


def wait_maps(rtag, timeout):
    """panel/<rtag>/otf.json with every listed map on disk -> (dir, meta) or (None, why)."""
    d = os.path.join(PANEL_DIR, rtag)
    t0 = time.time()
    while time.time() - t0 < timeout:
        meta = _jload(os.path.join(d, "otf.json"), None)
        if meta and meta.get("maps"):
            miss = [m["name"] for m in meta["maps"] if not os.path.exists(os.path.join(d, m["name"] + ".map26a"))]
            if not miss:
                return d, meta
            if time.time() - os.path.getmtime(os.path.join(d, "otf.json")) > 120:  # maps gone: the read finished first (or a reused read)
                return None, f"{len(miss)} of {len(meta['maps'])} maps missing in {d}"
        time.sleep(10)
    return None, f"no maps in {d} after {timeout // 60} min"


def link_maps(src, meta, dst):
    os.makedirs(dst, exist_ok=True)
    keep = []
    for m in meta["maps"]:
        a, b = os.path.join(src, m["name"] + ".map26a"), os.path.join(dst, m["name"] + ".map26a")
        try:
            if not os.path.exists(b):
                os.link(a, b)
            keep.append(m)
        except OSError:
            try:
                shutil.copyfile(a, b)
                keep.append(m)
            except OSError:
                pass
    json.dump(dict(meta, maps=keep), open(os.path.join(dst, "otf.json"), "w"))
    return keep


def make_twin(cand, live, rider, rtag, log=rlog):
    """flip.sh CAND TWIN 'X=live ...': data only, code IDENTICAL to CAND (wsec). -> (twin name, revert flips) or (None, why)."""
    import subprocess
    cv = {f: define_value(cand, f) for f in flips_of(rider["flips"])}
    want = flips_of(rider["flips"])
    off = [f"{f}={cv[f]} (rider {want[f]})" for f in want if cv[f] is None or str(int(want[f], 0)) != cv[f]]
    if off:
        return None, f"CAND does not carry the rider's values: {', '.join(off)}"
    rv = revert_values(cand, live, rider["flips"])
    same = [f for f in rv if rv[f] == cv[f]]
    if same:
        return None, f"rider flags already at live values in CAND: {same}"
    name = re.sub(r"[^A-Za-z0-9_]", "", f"nova_rt{rtag}_{rider['slug']}")[:80]
    if os.path.lexists(os.path.join(REPO, "bots", name)):
        if (_flipinfo(name) or {}).get("FLIPS") == " ".join(f"{k}={v}" for k, v in rv.items()):
            return name, rv
        name += f"_{os.getpid()}"
    fl = " ".join(f"{k}={v}" for k, v in rv.items())
    r = subprocess.run(["sh", os.path.join(LAB, "flip.sh"), cand, name, fl], cwd=REPO, capture_output=True, text=True, timeout=3600)
    if r.returncode or not _flipinfo(name).get("WASM"):
        return None, f"flip.sh rc {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}"
    log(f"twin {name} = {cand} + [{fl}]: {(r.stdout.strip().splitlines() or [''])[-1][:200]}")
    return name, rv


def libs(cand, twin):
    """(cand .so, twin .so) from ONE wasm: the twin's FLIP trunk build of CAND and its data-patched copy (code identical by construction)."""
    sys.path.insert(0, os.path.join(REPO, "tools", "cxe"))
    import cxebuild
    import smokefarm as SF
    fi = _flipinfo(twin)
    tw = f"/data/USER/trunkproj/wasm/{fi['TRUNK']}-{fi['TRUNK_HASH']}.wasm"
    cso = cxebuild.build_bot(cand, wasm=tw)
    tso = SF.patch_so(twin) or cxebuild.build_bot(twin)
    return cso, tso


def play_twin(cso, tso, mdir, names, log=rlog):
    """CAND v TWIN, both seats, on the pilots (changedprobe.play: node-side replay hash) -> {map: (ga, gb)}; per 300 maps."""
    import changedprobe
    os.environ["CXEFARM"] = "1"
    os.environ["PILOTCXE_PRIO"] = TWIN_PRIO
    os.environ.setdefault("PILOTCXE_PER", "8")
    got = {}
    for i in range(0, len(names), 300):
        part = names[i:i + 300]
        got.update(changedprobe.play(cso, tso, mdir, part, log))
        shutil.rmtree(os.path.join(mdir, "g"), ignore_errors=True)
        log(f"twin games: {len(got)} of {i + len(part)} maps back")
    return got


def ci_of(v):
    n = len(v)
    if n < 2:
        return (v[0] if v else 0.5), float("inf"), n
    m = sum(v) / n
    se = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1) / n)
    return m, se, n


def los_of(p, se):
    """shipcheck.rare_rows' LOS: P(true point > .50) under the normal approximation"""
    se = max(se, 1e-9)
    return 0.5 * (1 + math.erf((p - 0.5) / se / math.sqrt(2)))


def rare_bar():
    """bq/rarebar.txt as shipcheck reads it -> {point, los, min, n}; n = RIDE_RARE_N or shipcheck's max(N, 1.05 x min) (420)"""
    bar = dict(point=0.5, los=0.95, min=400.0)
    try:
        w = open(os.environ.get("SC_RARE_BAR", os.path.join(Q, "rarebar.txt"))).read().split()
        bar.update({k: float(v) for k, v in zip(w[::2], w[1::2]) if k in ("point", "los", "min")})
    except (OSError, ValueError):
        pass
    bar["n"] = int(os.environ.get("RIDE_RARE_N", max(420, math.ceil(1.05 * bar["min"]))))
    return bar


def live_version():
    try:
        return open(os.path.join(Q, "live.txt")).readline().split()[0]
    except (OSError, IndexError):
        return "?"


def watched_fams(rider):
    fams = {f for f in (rider.get("rarefams") or "").split(",") if f}
    for e in _jload(LEDGER, {}).values():
        fams |= {f for f in (e.get("rarefams") or "").split(",") if f}
    return sorted(fams)


def ledger_add(rider, cand, live, tag, rows, unchanged, fams):
    """ROWS: [(map key, map name, score, fams matched)] changed maps of one twin read -> the entry after pooling. Maps the bit was picked on
    and held-out maps are dropped here; a map already in the entry (same seed) is not counted twice."""
    names, seeds = own_picked(f"nova_b0_{rider['slug']}")
    held = heldout_names()
    with _Lock(LEDGER + ".lock"):
        led = _jload(LEDGER, {})
        e = led.setdefault(rider["slug"], dict(slug=rider["slug"], flips=rider["flips"], donor=rider.get("donor", "-"), rare=rider.get("rare"),
                                                rarefams=rider.get("rarefams", ""), subject=rider.get("subject", ""), maps={}, reads=[], status="open"))
        e["flips"], e["donor"] = rider["flips"], rider.get("donor", e.get("donor", "-"))
        ver, dropped, added = live_version(), 0, 0
        for key, nm, sc, fm in rows:
            if nm in held or nm in names or key in seeds:
                dropped += 1
                continue
            if key in e["maps"]:
                continue
            e["maps"][key] = dict(map=nm, score=sc, tag=tag, bundle=cand, base=live, version=ver, fams=fm)
            added += 1
        sc = [r[2] for r in rows]
        p, se, n = ci_of(sc)
        e["reads"].append(dict(t=time.time(), tag=tag, bundle=cand, base=live, version=ver, changed=len(rows), unchanged=unchanged, added=added,
                               dropped_picked=dropped, point=round(p, 4) if n else None, z=round((p - 0.5) / se, 2) if n > 1 and se > 0 else None,
                               fams={f: sum(1 for r in rows if f in r[3]) for f in fams}))
        led[rider["slug"]] = e
        _jsave(LEDGER, led)
    return e


def verdict(e):
    """-> (state, text). state: 'open' (< n changed maps), 'PASS' or 'FAIL' on the rare bar (point > P, LOS >= L) over the pooled ledger."""
    bar = rare_bar()
    sc = [m["score"] for m in e["maps"].values()]
    p, se, n = ci_of(sc)
    los = los_of(p, se) if n > 1 else 0.0
    bases = {}
    for m in e["maps"].values():
        k = f"{m.get('version') or '?'}/{m.get('base') or '?'}"
        bases[k] = bases.get(k, 0) + 1
    txt = (f"{e['slug']} [{e['flips']}]: {n} changed maps pooled, point {p:.4f} [{p - 1.96 * se:.3f}, {p + 1.96 * se:.3f}] LOS {100 * los:.0f}% "
           f"(bar point > {bar['point']:g}, LOS >= {bar['los']:.0%}, at >= {bar['n']} maps); by base {bases}")
    if n < bar["n"]:
        return "open", txt
    return ("PASS" if p > bar["point"] and los >= bar["los"] else "FAIL"), txt


def drag_check(rows):
    """this twin read alone: does X drag the bundle? (>= DRAG_N changed maps, point < .50, z <= DRAG_Z)"""
    p, se, n = ci_of([r[2] for r in rows])
    z = (p - 0.5) / se if n > 1 and se > 0 else 0.0
    return n >= DRAG_N and p < 0.5 and z <= DRAG_Z, f"twin read: {n} changed maps, point {p:.4f}, z {z:+.2f}"


def bank_fail(e, txt):
    """A rare bit that missed the bar on its pooled ride-along maps: the failed-positive bank (flagscreen bank add), as fixbatch.bank_entry."""
    import subprocess
    if os.environ.get("RIDEALONG_DRY") == "1":
        return rlog(f"DRY: would bank {e['slug']}: {txt}")
    p = ci_of([m["score"] for m in e["maps"].values()])[0]
    donor = next((d for d in (e.get("donor") or "-").split(",") if d and d != "-"), "-")
    cmd = [sys.executable, "-I", os.path.join(LAB, "flagscreen.py"), "bank", "add", re.sub(r"[^A-Za-z0-9_]", "", e["slug"]) + "_ra", "--donor", donor,
           "--flips", e["flips"], "--point", f"{max(0.0, p):.4f}", "--base", live_version(), "--fail", "ride-along rare bar",
           "--cause", "power" if p > 0.5 else "other", "--lane", "fix", "--note", f"ride-along: {txt}"[:120]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300)
        rlog(f"BANKED {e['slug']}: flagscreen rc {r.returncode}: {(r.stdout + r.stderr).strip()[-160:]}")
    except (OSError, subprocess.SubprocessError) as x:
        rlog(f"bank {e['slug']} failed: {x}")


def settle(slug, shipped_in=None):
    """Apply the verdict to the ledger entry once (status PASS / FAIL); PASS: a PENDING line saying how it ships."""
    with _Lock(LEDGER + ".lock"):
        led = _jload(LEDGER, {})
        e = led.get(slug)
        if not e:
            return None
        st, txt = verdict(e)
        if shipped_in:
            e["shipped_in"] = shipped_in
        if st == "open" or e.get("status") == st:
            _jsave(LEDGER, led)
            return st
        e["status"], e["verdict"], e["decided"] = st, txt, time.time()
        _jsave(LEDGER, led)
    rlog(f"VERDICT {st} {txt}")
    if st == "FAIL":
        bank_fail(e, txt)
    elif st == "PASS" and os.environ.get("RIDEALONG_DRY") != "1":
        try:
            with open(os.path.join(Q, "pending_reads.txt"), "a") as f:
                f.write(f"PENDING: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ride-along rare PASS {slug} [{e['flips']}] donor {e['donor']}: "
                        f"ships inside its bundle if the bundle ships ({e.get('shipped_in') or 'not yet'}); else arm alone as a data flip: armq.py add "
                        f"{e['donor']} \"{e['flips']}\" fix \"{(e.get('subject') or 'rare: ' + slug)[:60]}\" {slug}ra --front ({txt[:160]})\n")
        except OSError:
            pass
    return st


def twin_main(cand, live, rtag, tag, lane):
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # a stop runs the finally blocks: cxefarm cancels its queued pilot items
    live = None if live == "-" else live
    rs = riders_of(cand)
    rlog(f"twin legs for {cand} (check {tag}, run {rtag}, lane {lane}, live {live}): riders {[r['slug'] for r in rs]}")
    src, meta = wait_maps(rtag, int(os.environ.get("RIDE_MAP_WAIT", 7200)))
    if not src:
        return rlog(f"{tag}: no twin legs: {meta}")
    mdir = os.path.join(WORK, "runs", f"{rtag}_{os.getpid()}")
    keep = link_maps(src, meta, mdir)
    rlog(f"{tag}: {len(keep)} fresh maps of {src} linked into {mdir}")
    report = []
    try:
        for rd in rs:
            twin, rv = make_twin(cand, live, rd, rtag)
            if not twin:
                rlog(f"{tag}: rider {rd['slug']}: no twin: {rv}")
                continue
            cso, tso = libs(cand, twin)
            if cso == tso:
                rlog(f"{tag}: rider {rd['slug']}: CAND and TWIN are the same library: nothing to read")
                continue
            t0 = time.time()
            got = play_twin(cso, tso, mdir, [m["name"] for m in keep])
            fams = watched_fams(rd)
            byname = {m["name"]: m for m in keep}
            rows, unchanged = [], 0
            import changedprobe
            for nm, (ga, gb) in got.items():
                if ga["h"] == gb["h"]:
                    unchanged += 1
                    continue
                m = byname[nm]
                fm = [f for f, ok in fams_of(os.path.join(mdir, nm + ".map26a"), m, fams).items() if ok] if fams else []
                rows.append((str(m.get("seed") or nm), nm, changedprobe.pair_score(ga, gb), fm))
            _fc_save()
            e = ledger_add(rd, cand, live, tag, rows, unchanged, fams)
            drag, dtxt = drag_check(rows)
            if len(got) >= 50 and len(rows) > 0.5 * len(got):  # changedprobe's NOT_RARE: a common change does not ride; it reads on its lane
                drag, dtxt = True, f"not a rare change: {len(rows)} of {len(got)} maps changed in its twin read (read it the normal way)"
            sc = [r[2] for r in rows]
            p, se, n = ci_of(sc)
            line = (f"{tag} rider {rd['slug']} [{rd['flips']}] twin {twin} (reverted {rv}): {len(got)} of {len(keep)} maps read, {len(rows)} changed "
                    f"({100 * len(rows) / max(1, len(got)):.1f}%), {unchanged} byte-identical; X = CAND v TWIN on changed maps {p:.4f} "
                    f"[{p - 1.96 * se:.3f}, {p + 1.96 * se:.3f}]; fams {e['reads'][-1]['fams']}; ledger {len(e['maps'])} maps; {time.time() - t0:.0f} s")
            rlog(line)
            report.append(line)
            if drag:
                with _Lock(LEDGER + ".lock"):
                    led = _jload(LEDGER, {})
                    led[rd["slug"]]["drop_next"] = dict(tag=tag, bundle=cand, why=dtxt, t=time.time())
                    _jsave(LEDGER, led)
                rlog(f"DRAG {rd['slug']}: {dtxt}: dropped from the next bundle build (this bundle's read stands)")
                report.append(f"  DRAG: {dtxt}: not in the next bundle")
            st = settle(rd["slug"])
            report.append(f"  ledger: {verdict(_jload(LEDGER, {})[rd['slug']])[1]} -> {st}")
    finally:
        shutil.rmtree(mdir, ignore_errors=True)  # hard links only: the fresh read's own maps stay with it
    if report:
        open(os.path.join(Q, f"ridealong_{tag}.txt"), "w").write("\n".join(report) + "\n")


def status():
    led = _jload(LEDGER, {})
    print(f"ride-along ledger {LEDGER}: {len(led)} bits; switch {'ON' if on() else 'off'}")
    for sl, e in sorted(led.items()):
        st, txt = verdict(e)
        print(f"  [{e.get('status')}{' DROP-NEXT' if e.get('drop_next') else ''}] {txt}; {len(e.get('reads', []))} reads")
    reg = _jload(REGISTRY, {})
    for k, v in reg.items():
        print(f"  bundle {k}: riders {[r['slug'] for r in v.get('riders', [])]}")


def harvest_test(a):
    fams, n = a[0], int(a[1])
    out = a[2] if len(a) > 2 else os.path.join(WORK, f"htest_{os.getpid()}")
    t = time.time()
    hv = harvest(out, n, fams, f"htest{os.getpid()}")
    by = {}
    for m in hv:
        by.setdefault((m["labels"]["hfam"], "label" if m.get("family") == m["labels"]["hfam"] else "check"), []).append(m["name"])
    print(f"harvest-test {fams} n {n}: {len(hv)} maps in {time.time() - t:.0f} s into {out}")
    for k, v in sorted(by.items()):
        print(f"  {k[0]:16s} by {k[1]:5s}: {len(v)}")
    return hv


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["harvest-test"]:
        harvest_test(a[1:])
    elif a[:1] == ["twin"] and len(a) >= 6:
        twin_main(*a[1:6])
    elif a[:1] == ["status"]:
        status()
    elif a[:1] == ["settle"] and len(a) >= 2:
        print(settle(a[1]))
    else:
        print(__doc__)
