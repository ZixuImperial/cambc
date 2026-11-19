#!/usr/bin/env python3
"""draftstock: a stock of never-played maps with each map's labels and base lineups, so a draft-lane probe plays only the maps where a change is possible (owner 8 Nov: finding 1,200
changed maps cost 19,757-35,635 fresh probes for DXS, 12-25 min). Tool Builder, 8 Nov.

  python3 -I tools/lab/draftstock.py fill --n N [--wait 1800]                 take N maps (rounded up to whole 300-map pool sets) from the fresh pool: half weird, half std, as the pool gives
  python3 -I tools/lab/draftstock.py lineups [--bot BOT] [--batch 300] [--par 6] [--max N]    1-round BOT v BOT on stock maps that lack lineups for BOT's draft_key (one game gives both seats)
  python3 -I tools/lab/draftstock.py status [--base-has F] [--bot BOT]        ready maps per half, lineups per key, what a filter would pass, claims outstanding
  python3 -I tools/lab/draftstock.py take DEST --n N [--base-has F] [--bot BOT] --who W    claim N maps (half weird, half std) into DEST for a full-game read: consumed
  python3 -I tools/lab/draftstock.py reclaim [--dry]                          give back maps claimed by a probe whose process is gone

STOCK (DS_ROOT, default /data/zw4424/st/draftstock):
  ready/NAME.map26a     a map still in the stock. A CLAIM is one os.rename out of here: two consumers can never hold the same map.
  sets/SID.json         the pool set's otf.json (per map: file, seed, recipe, labels). Never rewritten; maps leave ready/, their record stays.
  lineups/KEY.json      per draftprobe.draft_key: {bot, maps: {name: {bA, bB}}}. Refresh: a new draft key gets new lineups; the maps stay. Records of consumed maps stay so a filter's pool fraction
                        is measured on the whole stock as filled, not on what earlier reads left behind.
  claims.log / returned.log / consumed.log    who drew what, what came back, what was used up.

SINGLE USE. A 1-round probe is not a read (draftprobe has always kept skipped maps): a map a probe finds unchanged, unread or surplus goes back. A map kept for a read, or played to the end
by changedprobe, is consumed for good. draw() takes the least-probed maps first, so a returned map only comes round again once the unprobed ones are gone (a map that survived earlier
probes is selected: not changed by those candidates).

FILTER (--base-has F, draftprobe / changedprobe / stylepanel / inforead --base-has, marker BASEHAS=F): terms joined by '+', all must hold. A term is KIT[,KIT...] (the stored BASE lineup holds
one of them, in either seat), -KIT[,KIT...] (12 Nov: NEITHER seat's lineup holds any of them), !KIT[,KIT...] (at least ONE seat's lineup holds none) or LABEL=V[/V...] (a stratmaps label: fam team area spawn altar terrain econ pool). e.g. ryth    ryth,prism+team=T5/T4. Draft-time facts only (map labels and BASE's lineup): never an
outcome. A filter claims 'no change is possible elsewhere', so every filtered probe also probes ~DS_OUT_N (300) maps OUTSIDE it; a changed share outside that puts coverage under DS_COV_BAR (.95) makes the probe INCONCLUSIVE.
coverage = in x f / (in x f + out x (1-f)), in/out the changed shares inside and outside, f the filter's share of the stock (halves' mean). Lineups are keyed on BASE's draft_key,
else (a private trunk whose flag-0 draft equals live's) on live's: every probe compares the BASE lineups it measures with the stored ones and a mismatch over DS_MISMATCH (2%) is INCONCLUSIVE too.
Reading: no daemon; fill / lineups are run by hand. As a module: draw, settle, frac, key_for, parse_filter (draftprobe.py, changedprobe.py)."""
import argparse
import fcntl
import json
import subprocess
import math
import os
import random
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, REPO + "/tools/lab")
ROOT = os.environ.get("DS_ROOT", "/data/zw4424/st/draftstock")
BQ = "/data/zw4424/st/bq"
LABELS = ("fam", "team", "area", "spawn", "altar", "terrain", "econ", "pool")
SET_N = 300
OUT_N = int(os.environ.get("DS_OUT_N", 300))
COV_BAR = float(os.environ.get("DS_COV_BAR", 0.95))
MISMATCH_BAR = float(os.environ.get("DS_MISMATCH", 0.02))
_lock = threading.Lock()


class StockError(Exception):
    pass


def d(*p):
    return os.path.join(ROOT, *p)


def say(m):
    print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} draftstock: {m}", flush=True)


def half(m):
    return "weird" if (m.get("labels") or {}).get("pool") == "weird" else "std"


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def logline(fn, rec):
    os.makedirs(ROOT, exist_ok=True)
    with open(d(fn), "a") as f:
        f.write(json.dumps(rec) + "\n")


_M = {}


_SEEN = set()  # set files already in _M (a set record is never rewritten, so a refresh only reads files added since)
_MLOCK = threading.Lock()


def meta(refresh=False):
    """name -> the map's otf record (with 'sid'), over every set ever filled.
    9 Nov (Builder, b1756: a draft-changed probe peaked at 8.1 GB): every draw refreshed by re-reading all ~1,100 set files (~700 MB a copy), and
    12 parallel draws each built their own. Now a refresh reads only new set files, one thread at a time, into a new dict (a shallow copy of the
    old one plus the new records), so readers of the old dict are never disturbed."""
    global _M
    if _M and not refresh:
        return _M
    with _MLOCK:
        try:
            names = [fn for fn in os.listdir(d("sets")) if fn.endswith(".json") and fn not in _SEEN]
        except OSError:
            names = []
        if _M and not names:
            return _M
        out = dict(_M) if _M else {}
        for fn in names:
            try:
                for m in json.load(open(d("sets", fn)))["maps"]:
                    out[m["name"]] = dict(m, sid=fn[:-5])
                _SEEN.add(fn)
            except (OSError, ValueError, KeyError):
                pass
        _M = out  # 8 Nov (10000, 10002): a new dict, never one cleared in place: draftprobe's parallel draws read it while another refreshes
        return out


def ready_names():
    try:
        return [f[:-len(".map26a")] for f in os.listdir(d("ready")) if f.endswith(".map26a")]
    except OSError:
        return []


def probe_counts():
    """name -> times this map came back from a probe (claims the same map again are the least-probed-first order)."""
    out = {}
    try:
        for ln in open(d("returned.log")):
            try:
                for x in json.loads(ln)["names"]:
                    out[x] = out.get(x, 0) + 1
            except (ValueError, KeyError):
                pass
    except OSError:
        pass
    return out


def live_bot():
    return open(f"{BQ}/live.txt").readline().split()[1]


def lineups_path(key):
    return d("lineups", f"{key}.json")


def load_lineups(key):
    """-> {'bot', 'maps': {name: {bA, bB}}} or None."""
    try:
        return json.load(open(lineups_path(key)))
    except (OSError, ValueError):
        return None


def known_kits():
    out = set()
    try:
        for fn in os.listdir(d("lineups")):
            if fn.endswith(".json"):
                for v in json.load(open(d("lineups", fn)))["maps"].values():
                    out.update(v["bA"], v["bB"])
    except (OSError, ValueError, KeyError):
        pass
    return out


def parse_filter(spec):
    """'ryth,prism+team=T5/T4' -> (kit terms [[kit...]...], label terms [(key, set(values))...], spec); None/'' -> (no filter)."""
    if not spec:
        return ([], [], "")
    if not re.fullmatch(r"[A-Za-z0-9_,=/+<>.!-]+", spec):
        raise StockError(f"bad filter {spec!r}: characters allowed are letters, digits and _ , = / + - < > .")
    kt, lb = [], []
    for term in spec.split("+"):
        cm = re.fullmatch(r"([a-z][a-z0-9_]*)(>=|<=|>|<)(-?[\d.]+)", term)
        if cm:  # 11 Nov (VGN: Vesper drafted AND gold_share < .35): a map class term NAME OP V (tools/lab/mapclass.py), on the map file
            import mapclass
            if cm.group(1) not in mapclass.CLASSES:
                raise StockError(f"bad filter {spec!r}: unknown map class {cm.group(1)!r}")
            lb.append(("cls", (cm.group(1), cm.group(2), float(cm.group(3)))))
            continue
        if "=" in term:
            k, v = term.split("=", 1)
            if k not in LABELS:
                raise StockError(f"bad filter {spec!r}: unknown label {k!r} (labels: {' '.join(LABELS)})")
            lb.append((k, set(v.split("/"))))
        elif term.startswith("-"):  # 12 Nov (Builder NCC: lineup holds NONE of marcella, vendetta, vesper): -kit[,kit...], BOTH seats
            lb.append(("nokit", set(term[1:].split(","))))
        elif term.startswith("!"):  # 12 Nov (b2119 NCC fires per seat): !kit[,kit...] = AT LEAST ONE seat's lineup holds none of them
            lb.append(("nokit1", set(term[1:].split(","))))
        else:
            kt.append(term.split(","))
    return (kt, lb, spec)


def check_kits(flt, key=None):
    """A misspelt kit would pass nothing and read as 'the stock ran out'."""
    kn = known_kits()
    for t in flt[0] + [sorted(v) for k_, v in flt[1] if k_ in ("nokit", "nokit1")]:
        for k in t:
            if kn and k not in kn:
                raise StockError(f"filter {flt[2]!r}: kit {k!r} is in no stored lineup (kits seen: {' '.join(sorted(kn))})")


_CLSV = {}


def cls_ok(name, cond):
    """a map class condition on ready/NAME.map26a (None when the file is gone: a consumed map counts as failing)"""
    k = (name, cond)
    if k not in _CLSV:
        p = os.path.join(ROOT, "ready", name + ".map26a")
        try:
            import mapclass
            v = mapclass.values(p, [cond[0]]).get(cond[0]) if os.path.exists(p) else None
            _CLSV[k] = v is not None and mapclass.OPS[cond[1]](v, cond[2])
        except Exception:  # noqa: BLE001
            _CLSV[k] = False
    return _CLSV[k]


def passes(flt, lu, labels, name=None):
    if lu is None:
        return False
    return (all(any(k in lu["bA"] or k in lu["bB"] for k in t) for t in flt[0])
            and all((not (set(v) & (set(lu["bA"]) | set(lu["bB"])))) if k == "nokit" else
                    (not (set(v) & set(lu["bA"])) or not (set(v) & set(lu["bB"]))) if k == "nokit1" else
                    (cls_ok(name, v) if name else False) if k == "cls" else (labels or {}).get(k) in v for k, v in flt[1]))


def key_for(base):
    """(key, note) of the lineups a probe against BASE uses: BASE's own draft_key if the stock has lineups for it, else live's (a private trunk built on live drafts like live at flag 0;
    every probe still compares the BASE lineups it measures with the stored ones). No lineups for either -> StockError."""
    import draftprobe as P
    k = P.draft_key(base)
    if load_lineups(k):
        return k, None
    lv = live_bot()
    lk = P.draft_key(lv)
    if load_lineups(lk):
        return lk, f"{base} has draft key {k}, not in the stock: using live {lv}'s lineups (key {lk})"
    # 13 Nov (TB: every ship changes the draft key (draft-path files: champ_prism.h, plan_*, ...), and a new key's 60-90k lineups take ~35 min,
    # so --base-has reads started after a ship stalled on 'no lineups' / 'stock empty'): fall back to the NEWEST key's lineups made within
    # DS_KEY_FALLBACK_H (12 h). Its maps are played for real, so a lineup the new draft changes only dilutes the filter; the outside-filter
    # safety row still runs. DS_KEY_FALLBACK_H=0 turns it off.
    lim = float(os.environ.get("DS_KEY_FALLBACK_H", 12)) * 3600
    try:
        d_ = os.path.dirname(lineups_path(k))
        cands = sorted((os.path.getmtime(os.path.join(d_, x)), x[:-5]) for x in os.listdir(d_) if x.endswith(".json"))
    except OSError:
        cands = []
    for mt, kk in reversed(cands):
        if time.time() - mt <= lim and load_lineups(kk):
            return kk, f"{base} (key {k}) and live {lv} (key {lk}) have no lineups yet: using the newest stock lineups (key {kk}, {(time.time() - mt) / 3600:.1f} h old)"
    raise StockError(f"the stock has no lineups for {base} (key {k}) nor live {lv} (key {lk}): run draftstock.py lineups --bot {base}")


def frac(key, flt):
    """{'weird': f, 'std': f, 'mean': f}: the share of the stock (every map with a lineup for KEY, used up or not) that passes FLT."""
    L = load_lineups(key) or {}
    M = meta()
    cnt = {"weird": [0, 0], "std": [0, 0]}
    for x, lu in (L.get("maps") or {}).items():
        if x in M:
            c = cnt[half(M[x])]
            c[1] += 1
            c[0] += passes(flt, lu, M[x].get("labels"), x)
    out = {h: c[0] / c[1] if c[1] else 0.0 for h, c in cnt.items()}
    out["mean"] = (out["weird"] + out["std"]) / 2
    out["n"] = {h: c[1] for h, c in cnt.items()}
    return out


def draw(dest, key, flt, nw, ns, who, outside=False, exclude=(), rng=None):
    """Claim up to nw weird and ns std maps (least-probed first) passing FLT (outside: failing it) into DEST and write DEST/otf.json -> the otf dict, whose 'stock' says how many were asked for and
    what was available. A claim is one os.rename(ready/NAME -> DEST/NAME): a race loses and tries the next map."""
    os.makedirs(dest, exist_ok=True)
    M = meta(refresh=True)  # a fill may have added sets since this process started
    L = (load_lineups(key) or {}).get("maps", {})
    pc = probe_counts()
    exclude = set(exclude)
    rng = rng or random.Random(os.urandom(8))
    groups = {"weird": [], "std": []}
    nolu = 0
    for x in ready_names():
        if x not in M or x in exclude:
            continue
        if x not in L:
            nolu += 1
            continue
        if bool(passes(flt, L[x], M[x].get("labels"), x)) != (not outside):
            continue
        groups[half(M[x])].append(x)
    avail = {h: len(v) for h, v in groups.items()}
    got = []
    for h, want in (("weird", nw), ("std", ns)):
        g = groups[h]
        rng.shuffle(g)
        g.sort(key=lambda x: pc.get(x, 0))  # stable: random within the same probe count
        k = 0
        for x in g:
            if k >= want:
                break
            try:
                os.rename(d("ready", x + ".map26a"), os.path.join(dest, x + ".map26a"))
            except OSError:  # another consumer won this map
                continue
            got.append(x)
            k += 1
    bm = dict(maps=[{k: v for k, v in M[x].items() if k != "sid"} for x in got], tag="stock", made=stamp(),
              stock=dict(asked=dict(weird=nw, std=ns), avail=avail, nolu=nolu, outside=outside, filter=flt[2], key=key))
    json.dump(bm, open(os.path.join(dest, "otf.json.part"), "w"))
    os.replace(os.path.join(dest, "otf.json.part"), os.path.join(dest, "otf.json"))
    if got:
        logline("claims.log", dict(t=stamp(), who=who, pid=os.getpid(), dest=os.path.abspath(dest), outside=outside, names=got))
    return bm


def settle(dest, names, kept, who):
    """A batch is read: maps in KEPT (their copy is in the probe's OUTDIR) are consumed and DEST's copy goes; every other map of NAMES goes back to the stock. Idempotent (a resume repeats it)."""
    kept = set(kept)
    back, used = [], []
    os.makedirs(d("ready"), exist_ok=True)
    for x in names:
        p = os.path.join(dest, x + ".map26a")
        if not os.path.exists(p):
            continue
        if x in kept:
            os.remove(p)
            used.append(x)
        else:
            os.rename(p, d("ready", x + ".map26a"))
            back.append(x)
    if back:
        logline("returned.log", dict(t=stamp(), who=who, names=back))
    if used:
        logline("consumed.log", dict(t=stamp(), who=who, reason="kept for a read", names=used))
    return len(back), len(used)


def consumed(names, who, reason):
    """Full games were played on NAMES (changedprobe, take): used up."""
    if names:
        logline("consumed.log", dict(t=stamp(), who=who, reason=reason, names=list(names)))


def coverage(st):
    """The safety row: (coverage or None, in share, out share, f, out_changed, out_probed, reason). The outside sample is the only evidence that the unprobed maps cannot change."""
    o = st.get("outside") or {}
    s = st.get("stock") or {}
    f = (s.get("frac") or {}).get("mean", 0.0)
    in_n, in_c = st.get("probed") or len(st.get("maps") or {}), st.get("changed")
    if in_c is None:  # changedprobe's state keeps no counters
        ms = (st.get("maps") or {}).values()
        in_n, in_c = len(ms), sum(1 for m in ms if m.get("changed"))
    i = in_c / in_n if in_n else 0.0
    if not o.get("done"):
        return dict(cov=None, inside=i, outside=None, f=f, out_changed=0, out_probed=0, out_drawn=0, reason="outside sample not read")
    on, oc = o["probed"], o["changed"]
    ot = oc / on if on else 0.0
    cov = None
    if f >= 0.999:
        cov = 1.0
    elif i or ot:
        cov = i * f / (i * f + ot * (1 - f))
    return dict(cov=cov, inside=i, outside=ot, f=f, out_changed=oc, out_probed=on, out_drawn=o.get("drawn", on), reason="")


def safety_verdict(c):
    """(ok, text) on coverage() output. A full-read's INCONCLUSIVE when coverage is under the bar or the sample was not read."""
    if c["f"] < 0.95 and c["out_probed"] < max(30, 0.8 * c.get("out_drawn", 0)):
        return False, f"the outside sample was not read ({c['out_probed']} of {c.get('out_drawn', 0)} drawn): filter {100 * c['f']:.1f}% of the stock, the rest unmeasured"
    if c["cov"] is not None and c["cov"] < COV_BAR:
        return False, (f"coverage {c['cov']:.2f} < {COV_BAR:.2f}: {c['out_changed']} of {c['out_probed']} maps OUTSIDE the filter changed "
                       f"({100 * c['outside']:.1f}%) v {100 * c['inside']:.1f}% inside, filter {100 * c['f']:.1f}% of the stock")
    return True, ""


def cmd_fill(a):
    import freshpool
    for s in ("ready", "sets", "incoming"):
        os.makedirs(d(s), exist_ok=True)
    want = int(math.ceil(a.n / SET_N))
    got, t0, total = 0, time.time(), 0
    while got < want and time.time() - t0 < a.wait:
        sid = f"s{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}_{os.urandom(3).hex()}"
        inc = d("incoming", sid)
        k = freshpool.take(inc, SET_N, "draftstock:fill")
        if not k:
            time.sleep(20)
            continue
        m = json.load(open(f"{inc}/otf.json"))
        m["maps"] = [x for x in m["maps"] if os.path.exists(f"{inc}/{x['name']}.map26a")]
        json.dump(m, open(d("sets", f"{sid}.part"), "w"))  # the record first: a claim never sees a map without one
        os.replace(d("sets", f"{sid}.part"), d("sets", f"{sid}.json"))
        for x in m["maps"]:
            os.rename(f"{inc}/{x['name']}.map26a", d("ready", x["name"] + ".map26a"))
        shutil.rmtree(inc, ignore_errors=True)
        got += 1
        total += len(m["maps"])
        say(f"set {got}/{want}: {sid} ({len(m['maps'])} maps), {time.time() - t0:.0f} s; ready now {len(ready_names())}")
    say(f"fill: {total} maps from {got} pool sets in {time.time() - t0:.0f} s{'' if got == want else ' (pool short: ' + str(want - got) + ' sets not taken)'}")
    return 0 if got else 1


def cmd_lineups(a):
    import draftprobe as P
    bot = a.bot or live_bot()
    key = P.draft_key(bot)
    os.makedirs(d("lineups"), exist_ok=True)
    os.makedirs(d("work"), exist_ok=True)
    lk = open(d("work", f".lineups_{key}.lock"), "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(f"draftstock lineups: another run holds key {key}")
    M = meta(refresh=True)
    L = load_lineups(key) or dict(key=key, bot=bot, made=stamp(), maps={})
    have = set(L["maps"])
    todo = [x for x in ready_names() if x in M and x not in have]
    if a.max:
        todo = todo[:a.max]
    say(f"lineups for {bot} (draft key {key}): {len(have)} known, {len(todo)} to derive")
    if not todo:
        return 0
    os.environ["OTF_ONE_SEAT"] = "1"  # condab: BOT v BOT, one game a map (one game gives both seats)
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    t0 = time.time()
    root = d("work", f"lu_{key}_{os.getpid()}")
    errors, lost = [], [0]

    def read_batch(bot_, bdir, leg):
        lu = P.probe_dir(bot_, bot_, bdir, leg)  # lineups(): a mirror's seat is 'a', so cA and bB are this game's sides A and B
        return {x: dict(bA=v["cA"], bB=v["bB"]) for x, v in lu.items() if "cA" in v and "bB" in v}

    def one(i, names):
        bdir = f"{root}/b{i}"
        os.makedirs(bdir, exist_ok=True)
        maps = []
        for x in names:
            try:
                shutil.copyfile(d("ready", x + ".map26a"), f"{bdir}/{x}.map26a")
            except OSError:  # a consumer took it meanwhile: it needs no lineup from this run
                continue
            maps.append({k: v for k, v in M[x].items() if k != "sid"})
        json.dump(dict(maps=maps), open(f"{bdir}/otf.json", "w"))
        got = read_batch(bot, bdir, f"dsl{key[:6]}{os.getpid()}b{i}")
        return i, names, got

    with ThreadPoolExecutor(max(1, a.par)) as ex:
        for f in [ex.submit(one, i, n) for i, n in enumerate(batches)]:
            try:
                i, names, got = f.result()
            except Exception as e:  # noqa: BLE001  one batch's trouble must not lose the others
                errors.append(str(e)[:200])
                continue
            with _lock:
                L["maps"].update(got)
                lost[0] += len(names) - len(got)
                L["made"] = stamp()
                json.dump(L, open(lineups_path(key) + ".part", "w"))
                os.replace(lineups_path(key) + ".part", lineups_path(key))
            say(f"batch {i}: {len(got)} of {len(names)} maps read ({len(L['maps'])} known, {time.time() - t0:.0f} s)")
    shutil.rmtree(root, ignore_errors=True)
    say(f"lineups: key {key} now {len(L['maps'])} maps; {lost[0]} unread (a re-run derives them); wall {time.time() - t0:.0f} s" + (f"; {len(errors)} batch errors: {errors[0]}" if errors else ""))
    return 0 if len(L["maps"]) else 1


def cmd_status(a):
    import draftprobe as P
    M = meta(refresh=True)
    rd = ready_names()
    h = {"weird": 0, "std": 0, "?": 0}
    for x in rd:
        h[half(M[x]) if x in M else "?"] += 1
    print(f"root {ROOT}\nready {len(rd)}: weird {h['weird']}, std {h['std']}{', no record ' + str(h['?']) if h['?'] else ''}; {len(M)} maps ever filled")
    try:
        keys = sorted(os.listdir(d("lineups")))
    except OSError:
        keys = []
    for fn in keys:
        if fn.endswith(".json"):
            L = json.load(open(d("lineups", fn)))
            print(f"lineups {fn[:-5]}: bot {L['bot']}, {len(L['maps'])} maps ({sum(1 for x in rd if x in L['maps'])} ready), made {L.get('made')}")
    pc = probe_counts()
    hist = {}
    for x in rd:
        hist[pc.get(x, 0)] = hist.get(pc.get(x, 0), 0) + 1
    if hist:
        print("ready maps by times probed: " + ", ".join(f"{k}x: {v}" for k, v in sorted(hist.items())))
    for fn, label in (("claims.log", "claim records"), ("consumed.log", "consumed records")):
        try:
            print(f"{label}: {sum(1 for _ in open(d(fn)))}")
        except OSError:
            print(f"{label}: 0")
    if a.base_has:
        flt = parse_filter(a.base_has)
        check_kits(flt)
        bot = a.bot or live_bot()
        key = P.draft_key(bot)
        f = frac(key, flt)
        L = (load_lineups(key) or {}).get("maps", {})
        inr = sum(1 for x in rd if x in L and passes(flt, L[x], M[x].get("labels"), x))
        print(f"filter {a.base_has!r} on key {key} ({bot}): {100 * f['mean']:.1f}% of the stock (weird {100 * f['weird']:.1f}%, std {100 * f['std']:.1f}%); {inr} ready maps pass")
    return 0


UNFILTERED_RESERVE = int(os.environ.get("DS_UNFILTERED_RESERVE", "12000"))  # ready maps an unfiltered take may not dig below (kept for filtered reads)


def cmd_take(a):
    import draftprobe as P
    bot = a.bot or live_bot()
    key = P.draft_key(bot) if a.bot else key_for(bot)[0]
    flt = parse_filter(a.base_has)
    check_kits(flt)
    if not (flt[0] or flt[1]) and len(ready_names()) - a.n < UNFILTERED_RESERVE:  # parse_filter -> (kits, labels, text)
        # 9 Nov (Planner: filtered rare reads found 31 of 420 maps; one unfiltered confirm read took 81k stock maps in an hour): an unfiltered take
        # that would leave the stock under its reserve gets the same kind of maps (fresh, half weird) straight from the fresh pool instead
        r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "stratmaps.py"), a.dest, "--n", str(a.n),
                            "--take", "--who", f"{a.who}:via-draftstock"])
        got = len([x for x in os.listdir(a.dest) if x.endswith(".map26a")]) if os.path.isdir(a.dest) else 0
        print(f"draftstock take: unfiltered and the stock is near its reserve ({UNFILTERED_RESERVE}): {got} maps from the fresh pool into {a.dest}")
        return r.returncode
    bm = draw(a.dest, key, flt, a.n - a.n // 2, a.n // 2, a.who)
    consumed([m["name"] for m in bm["maps"]], a.who, "take")
    print(f"draftstock take: {len(bm['maps'])} of {a.n} maps into {a.dest} (available: {bm['stock']['avail']})")
    return 0 if len(bm["maps"]) else 1


def cmd_reclaim(a):
    """Give back maps of claims whose process is gone and that no finished probe kept."""
    try:
        recs = [json.loads(x) for x in open(d("claims.log"))]
    except OSError:
        recs = []
    n = 0
    live = set()
    used = set()
    try:
        for ln in open(d("consumed.log")):
            used.update(json.loads(ln).get("names", []))
    except (OSError, ValueError):
        pass
    for r in recs:
        try:
            os.kill(r["pid"], 0)
            live.add(r["pid"])
        except OSError:
            pass
    for r in recs:
        if r["pid"] in live:
            continue
        here = [x for x in r["names"] if x not in used and os.path.exists(os.path.join(r["dest"], x + ".map26a"))]
        if here:
            n += len(here)
            print(f"{'would give back' if a.dry else 'giving back'} {len(here)} maps from {r['dest']} (who {r.get('who')})")
            if not a.dry:
                settle(r["dest"], here, (), f"reclaim:{r.get('who')}")
    print(f"reclaim: {n} maps{' (dry)' if a.dry else ''}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fill")
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--wait", type=int, default=1800, help="seconds to wait for pool sets")
    p = sub.add_parser("lineups")
    p.add_argument("--bot")
    p.add_argument("--batch", type=int, default=300)
    p.add_argument("--par", type=int, default=6)
    p.add_argument("--max", type=int, default=0)
    p = sub.add_parser("status")
    p.add_argument("--base-has")
    p.add_argument("--bot")
    p = sub.add_parser("take")
    p.add_argument("dest")
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--base-has")
    p.add_argument("--bot")
    p.add_argument("--who", required=True)
    p = sub.add_parser("reclaim")
    p.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    try:
        return dict(fill=cmd_fill, lineups=cmd_lineups, status=cmd_status, take=cmd_take, reclaim=cmd_reclaim)[a.cmd](a)
    except StockError as e:
        print(f"draftstock: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
