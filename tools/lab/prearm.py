#!/usr/bin/env python3
"""prearm: every pre-arm check of a built donor AT ONCE, one verdict line, and the armq line on PASS (Builder 8 Nov, owner goal: 20-minute
iterations from spec to ship decision; the serial base check -> identity -> firecount -> smoke took 20-30 min).

usage: python3 -I tools/lab/prearm.py DONOR:BASE "FLAG=V ..." LANE "SUBJECT" [SLUG] [--fire TAG,TAG] [--no-fire] [--no-fault] [--no-warm] [--n 100]
                                      [--rare N] [--rare-fams F] [--bugbar] [--parambar] [--seqspar] [--front] [--no-queue]
  run in parallel, on the pilots where a step plays games:
    base    shipcheck.base_check_lines(DONOR, BASE): every line DONOR changes sits behind a switch (seconds)
    merge   mergecheck DONOR BASE --no-build --no-play: defines/TABs/magics, conflict markers, the rules-lint ratchet, rulestest (~5 s)
    flips   flip.py check on DONOR's source: data-only flags; WARN NOCODE = a set bit no code tests (a FAIL here)
    ident   cxeident BASE DONOR --maps 20 (40 games): DONOR at flag 0 plays exactly as BASE (identity at unlimited fuel: owner OK 8 Nov,
            identity only)
            when ident fails, a 'logic' line says whether the games still match with fuel_remaining() constant (cost only) or not (decisions); ident stays FAIL
    fire    firecount DONOR FLIPS --n N (default 100 maps x 2 seats, debug build, 100k fuel): every --fire TAG fires in >= 1 game, or, without
            --fire, at least one counter fires (feat_*.cpp function entries or the agent's DG lines). --no-fire skips it (play-identical work)
    fault   faultcheck DONOR FLIPS: the RELEASE build with the flips v live, 100 new maps x 2 seats on the pilots: any bot fault, or a fuel
            runaway (capped cut-offs > 2x live, sign test p < .01) FAILs (~2 min, mostly the flipped build). --no-fault skips it
    trunk   fastship --merge-only: the private trunk armq would build (live's base + this diff: merge, build, identity v live), beside the other steps,
            so arm is flip + marker only (~10 s, not ~110 s; owner 8 Nov: 5-8 min iterations). A FAIL here would have failed at arm. --no-warm or bq/prearm_warm_OFF skips it;
            armq builds as usual if live's base moved meanwhile
  PASS (all steps pass) -> armq.py add DONOR:BASE FLIPS LANE SUBJECT [SLUG] with the bar flags given here (--no-queue: don't).
  No smoke: shipcheck's look 1 holds the disaster rows and stops early.
  DONOR "-" (flips only, on live): base and ident are skipped.
Prints one line per step as it ends, then 'PREARM PASS|FAIL ...'. Exit 0 PASS, 1 FAIL, 2 bad use. Logs: /data/zw4424/st/prearm/<stamp>/."""
import os
import re
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
LAB = f"{REPO}/tools/lab"
ROOT = "/data/zw4424/st/prearm"
sys.path.insert(0, LAB)


def say(s):
    print(f"{time.strftime('%H:%M:%S')} {s}", flush=True)


def src_of(bot):
    return os.path.join(os.path.realpath(os.path.join(REPO, "bots", bot)), "src")



def bits_guard(donor, base, flips):
    """DONOR v BASE: every existing `#define X_BITS v` whose value changed, and every existing X_TAB whose constexpr / volatile state
    changed, that the line's own FLIPS do not name (by flag, or by the table's stem: X_TAB <-> X_*). New defines and tables are fine.
    -> ["FILE: X_BITS 56 -> 0", ...]"""
    names = {kv.split("=", 1)[0] for kv in (flips or "").replace(",", " ").split() if "=" in kv}
    stems = {n.split("_")[0] for n in names}
    def scan(bot):
        d, t = {}, {}
        sd = src_of(bot)
        for f in os.listdir(sd):
            if not f.endswith((".h", ".cpp", ".cc")):
                continue
            txt = open(os.path.join(sd, f), errors="replace").read()
            for m in re.finditer(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*_BITS)\s+(\S+)", txt, re.M):
                d[m.group(1)] = (f, m.group(2))
            for m in re.finditer(r"\b(constexpr|const\s+volatile)\s+\w+\s+([A-Z][A-Z0-9_]*_TAB)\s*\[", txt):
                t[m.group(2)] = (f, "volatile" if "volatile" in m.group(1) else "constexpr")
        return d, t
    (dd, dt), (bd, bt) = scan(donor), scan(base)
    out = []
    for k, (f, v) in sorted(dd.items()):
        if k in bd and bd[k][1] != v and k not in names and k.split("_")[0] not in stems:
            out.append(f"{f}: {k} {bd[k][1]} -> {v}")
    for k, (f, v) in sorted(dt.items()):
        if k in bt and bt[k][1] != v and k[:-4] not in stems and not any(n.startswith(k[:-4] + "_") for n in names):
            out.append(f"{f}: {k} {bt[k][1]} -> {v}")
    return out



def cached_flag(bot, flag):
    """11 Nov (b1827): 'file:line' where FLAG's X_ON(...) is read once into a static (static const bool x = X_ON(..)), else ''."""
    stem = flag.rsplit("_", 1)[0] if flag.endswith("_BITS") else flag.split("_")[0]
    pat = re.compile(rf"\bstatic\s+(?:const\s+)?bool\s+\w+\s*=\s*{re.escape(stem)}_ON\s*\(")
    try:
        sd = src_of(bot)
        for f in sorted(os.listdir(sd)):
            if f.endswith((".cc", ".cpp", ".h")):
                for i, ln in enumerate(open(os.path.join(sd, f), errors="replace"), 1):
                    if pat.search(ln):
                        return f"{f}:{i}"
    except OSError:
        pass
    return ""

def draft_only_files(donor, base):
    """11 Nov (TB 6ad907; b1827 CLT1 read 'fire FAIL' though cxeident --where showed its code running): -> the changed source files when
    every one is draft-turn code (src/draft*), else None. Flag tables (*_flags.h, feat_*.h) don't count as changes."""
    try:
        d = os.path.realpath(f"{REPO}/bots/{donor.split(':')[0]}") + "/src"
        b = os.path.realpath(f"{REPO}/bots/{base}") + "/src"
        ch = []
        for f in sorted(os.listdir(d)):
            pd, pb = os.path.join(d, f), os.path.join(b, f)
            if not os.path.isfile(pd) or f.endswith((".orig", ".rej")):
                continue
            if not os.path.exists(pb) or open(pd, "rb").read() != open(pb, "rb").read():
                if f.endswith("_flags.h") or f.startswith("feat_"):
                    continue
                ch.append(f)
        return ch if ch and all(f.startswith("draft") for f in ch) else None
    except OSError:
        return None

def draft_value_flip(donor, base, target, flips):
    """12 Nov (TB; Builder b2185 DTZ arm B): -> a note when the line is a VALUE flip of flag tables that only draft-turn code reads: the donor
    changes nothing but *_flags.h tables (e.g. a constexpr -> const volatile un-bake), and every table holding a flipped macro is read
    (X_TAB[) only in src/draft* files. Then there is no play-turn firing to count; the draft-changed share (draft probe / --draft-changed
    read) is the firing measure. Else None."""
    try:
        d = os.path.realpath(f"{REPO}/bots/{donor.split(':')[0]}") + "/src"
        b = os.path.realpath(f"{REPO}/bots/{base}") + "/src"
        t = src_of(target)
        ch = [f for f in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, f)) and not f.endswith((".orig", ".rej"))
              and (not os.path.exists(os.path.join(b, f)) or open(os.path.join(d, f), "rb").read() != open(os.path.join(b, f), "rb").read())]
        if not ch or not all(f.endswith("_flags.h") for f in ch):
            return None
        macros = [x.split("=", 1)[0] for x in flips.split() if "=" in x]
        tabs = set()
        hdr = {f: open(os.path.join(t, f), errors="replace").read() for f in os.listdir(t) if f.endswith(".h")}
        for mac in macros:
            for txt in hdr.values():
                for m in re.finditer(r"\b([A-Za-z_]\w*_TAB)\s*\[\d*\]\s*=\s*\{([^}]*)\}", txt):
                    if re.search(r"\b" + re.escape(mac) + r"\b", m.group(2)):
                        tabs.add(m.group(1))
        if not tabs or len(tabs) < 1:
            return None
        users = set()
        for f in os.listdir(t):
            if f.endswith((".cc", ".cpp", ".h")) and not f.endswith("_flags.h"):
                txt = open(os.path.join(t, f), errors="replace").read()
                if any(re.search(r"\b" + re.escape(x) + r"\s*\[", txt) for x in tabs):
                    users.add(f)
        if not users or not all(f.startswith("draft") for f in users):
            return None
        return (f"draft-only value flip ({', '.join(sorted(tabs))} read only in {', '.join(sorted(users))}): no play-turn firing to count; "
                "the draft-changed share is the firing measure (draft probe or inforead --draft-changed)")
    except OSError:
        return None


TOOLWORDS = re.compile(r"\.py\b|reader|readmany|replay|dgkit|\bDG\w*\b|diag|inforead|firecount|counter|fc_|shipcheck|fresh|h2h|panel|cap5|heavy turn|"
                       r"death|fuel|step ?0|draftprobe|census|log row|record", re.I)
METRICWORDS = re.compile(r"\b(gold|gems?|stat|share|ownership|own\b|buy|bought|purchase|capture|kill|lock|tribut\w*|r\d{2,4}|round \d+)\b", re.I)


def prereg_rows(donor):
    """12 Nov (Coordinator, evidence checklist: EMO's KILL rows (gold r600, main stat r300, Vesper ownership) could not be computed from
    shipcheck's fresh games): WARN for each KILL / GO row of the donor agent's prereg.md that names a game metric but no reader or tool
    that computes it. Information only; never blocks."""
    m = re.match(r"nova_b(\d+)_", donor or "")
    if not m:
        return []
    p = f"/data/zw4424/st/b{m.group(1)}/prereg.md"
    try:
        lines = open(p, errors="replace").read().splitlines()
    except OSError:
        return []
    out = []
    for i, ln in enumerate(lines, 1):
        if re.search(r"\b(KILL|GO|NO-GO)\b", ln) and METRICWORDS.search(ln) and not TOOLWORDS.search(ln):
            out.append(f"prearm: WARN {os.path.basename(os.path.dirname(p))}/prereg.md:{i}: a KILL/GO row names a game metric but no reader/tool that "
                       f"computes it from the read's games (shipcheck keeps only end totals): {ln.strip()[:140]}")
    return out


_SLOT = []


def take_slot():
    """13 Nov (owner via the Builder: "Just make sure nothing crashes"; load exception until midnight): at most PREARM_SLOTS (4) prearms run their
    local work at once on this machine; the rest wait here for a free slot (flock, released when the process ends)."""
    import fcntl
    d = "/data/zw4424/st/bq/prearm_slots"
    os.makedirs(d, exist_ok=True)

    def slots():
        # 13 Nov 16:4xZ (Builder: prearm slots were the bottleneck at load ~16, ~40 GB free): bq/prearm_slots/N holds the count (6 tonight);
        # back to 4 while the 1-min load is over 50 or free memory under 15 GB. PREARM_SLOTS in the environment overrides both.
        if os.environ.get("PREARM_SLOTS"):
            return int(os.environ["PREARM_SLOTS"])
        try:
            k = int(open(os.path.join(d, "N")).read().split()[0])
        except (OSError, ValueError, IndexError):
            k = 4
        try:
            ld = float(open("/proc/loadavg").read().split()[0])
            av = next(int(ln.split()[1]) for ln in open("/proc/meminfo") if ln.startswith("MemAvailable:")) / 1048576
            # 13 Nov 19:0xZ (Builder, owner's load exception: up to 75 at nice 19, 4G caps, >= 10 GB free): N slots (8 tonight) below a
            # 1-min load of 75 with >= 12 GB free; 4 above it; none (wait) above 75 + 10 or under 10 GB
            # 19:1xZ (Builder, ~72 prearms waiting): N (12) up to load 65; 8 up to 75; 4 above
            if ld > 85 or av < 10:
                k = 0
            elif ld > 75 or av < 12:
                k = min(k, 4)
            elif ld > 65:
                k = min(k, 8)
        except (OSError, ValueError, StopIteration):
            k = min(k, 4)
        return k
    n = slots()
    if n <= 0 and os.environ.get("PREARM_SLOTS") == "0":
        return
    t0, said = time.time(), False
    while True:
        n = slots()
        # 13 Nov ~19:1xZ (owner: "prioritise the prism upgrades"): a Prism line (bq/prio_first.txt) may take any slot; others leave the top 3 free
        try:
            import re as _re
            _first = any(_re.search(l_.split("#")[0].strip(), " ".join(sys.argv[1:]), _re.I) for l_ in open("/data/zw4424/st/bq/prio_first.txt")
                         if l_.split("#")[0].strip())
        except (OSError, Exception):  # noqa: BLE001
            _first = False
        if not _first and n >= 6:
            n -= 3
        for k in range(n):
            fh = open(os.path.join(d, f"slot{k}"), "a")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _SLOT.append(fh)
                return
            except OSError:
                fh.close()
        if not said:
            print(f"prearm: all {n} local slots busy; waiting (bq/prearm_slots)", flush=True)
            said = True
        if time.time() - t0 > int(os.environ.get("PREARM_SLOT_WAIT", 5400)):
            print("prearm: no slot after the wait; running anyway", flush=True)
            return
        time.sleep(10)


def main():
    take_slot()
    a = sys.argv[1:]
    flags = {}
    for k in ("--fire", "--n", "--rare", "--rare-fams"):
        if k in a:
            i = a.index(k)
            flags[k] = a[i + 1]
            a = a[:i] + a[i + 2:]
    switches = {k for k in ("--no-warm", "--no-fire", "--no-fault", "--bugbar", "--parambar", "--seqspar", "--front", "--no-queue") if k in a}
    a = [x for x in a if x not in switches]
    if len(a) < 4:
        sys.exit(__doc__)
    spec, fl, lane, subject = a[:4]
    slug = a[4] if len(a) > 4 else None
    import donorbase  # 10 Nov (b1823): NEW:LIVE where newbot.sh copied the baked base -> NEW:nova_base_vNNN
    spec = donorbase.fix(spec)
    donor, base = (spec.split(":", 1) + [None])[:2] if spec != "-" else ("-", None)
    for w in prereg_rows(donor):
        print(w, flush=True)
    run = os.path.join(ROOT, time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"_{os.getpid()}")
    os.makedirs(run, exist_ok=True)
    t0 = time.time()
    if donor != "-" and (not base or not os.path.isdir(src_of(donor)) or not os.path.isdir(src_of(base))):
        sys.exit(f"prearm: DONOR:BASE must name two bots in bots/ ({spec})")
    target = donor if donor != "-" else open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    if donor == "-":  # 12 Nov (Builder, b2145 "- HSK_BITS=33": flip.sh copies via newbot.sh, which gives the BAKED base, then diffed it against
        # the unbaked live: "30 source lines changed for 1 flags"): a flip-only line runs on live's baked base nova_base_vNNN, as armq builds it
        _v = open("/data/zw4424/st/bq/live.txt").readline().split()[0]
        if os.path.isdir(src_of(f"nova_base_{_v}")):
            target = f"nova_base_{_v}"
    procs = {}
    capped_note = [""]  # 10 Nov: the capped-fuel identity line (information)
    bulk_note = [""]  # 10 Nov: bulkscan --diff live on the private trunk (information)
    # which feature file defines each flipped flag: its firecount counters are fc_<feature[:12]>.* (newfeat.py layout)
    feat_of = {}
    for kv in fl.replace(",", " ").split():
        nm = kv.split("=", 1)[0]
        for f in sorted(os.listdir(src_of(target))):
            if f.endswith((".h", ".cpp", ".cc")) and re.search(rf"^\s*#\s*define\s+{re.escape(nm)}\b", open(os.path.join(src_of(target), f), errors="replace").read(), re.M):
                m = re.fullmatch(r"feat_(\w+)\.(h|cpp)", f)
                feat_of[nm] = ("fc_" + m.group(1)[:12] + ".") if m else ("fc_" if os.path.exists(os.path.join(src_of(target), "brain_turn.cc")) else f)  # new layout: any new function
                break

    def start(name, cmd, env=None):
        log = open(os.path.join(run, name + ".log"), "w")
        procs[name] = (subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, **(env or {}))), log)

    # games first (they take longest); the quick checks run meanwhile
    if donor != "-":
        start("ident", ["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", base, donor, "--maps", "20", "--seed", "1"],
              {"PILOTCXE_PRIO": "20"})
    aff_bot = None
    if donor != "-" and flags.get("--rare") and os.environ.get("PREARM_RARE_AFFECTS", "1") == "1":
        # 12 Nov ~23:4xZ (Coordinator: tgos 86%, hsq1s 82%, rstl3s 63% were armed --rare and stopped 'not rare'): a --rare line's FLIPPED form
        # v its base on 30 maps x 2 seats at unlimited fuel; over PREARM_RARE_MAX (30%) of games differing = not rare: refused before it queues
        aff_bot = f"nova_praff_{os.getpid()}"
        r_ = subprocess.run(["sh", f"{LAB}/flip.sh", donor, aff_bot, fl], cwd=REPO, capture_output=True, text=True)
        if r_.returncode == 0 and os.path.isdir(src_of(aff_bot)):
            start("affects", ["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", base, aff_bot, "--maps", "30", "--seed", "3"],
                  {"PILOTCXE_PRIO": "20"})
        else:
            say(f"affects: flip.sh failed ({(r_.stdout + r_.stderr).strip()[-120:]}): not measured")
            aff_bot = None
    if donor != "-" and os.environ.get("PREARM_CAPPED", "1") == "1":
        # 10 Nov (Rule Checker: v700's q3 'play-identical' bundle changed play only when fuel splits a scan; unlimited-fuel identity never runs
        # that path): the same 40 games at the real 100k budget. INFORMATION, not a gate: any fuel change shifts the bot's own fuel readings
        start("capped", ["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", base, donor, "--maps", "20", "--seed", "1", "--budget"],
              {"PILOTCXE_PRIO": "20"})
    if donor != "-":  # 8 Nov (Builder): sections a-d, the rules-lint ratchet and rulestest; identity is the ident step (seconds, not after the arm)
        start("merge", ["nice", "-n", "10", sys.executable, "-I", f"{LAB}/mergecheck.py", donor, base, "--no-build", "--no-play", "--quiet"])
    prebuilt = None
    warm = donor != "-" and "--no-warm" not in switches and not os.path.exists("/data/zw4424/st/bq/prearm_warm_OFF") and ("--no-queue" not in switches or os.environ.get("PREARM_WARM") == "1")
    if warm:
        try:
            import armq
            own, pb_base = armq.private_plan(dict(donors=spec), always=True)[:2]
            if own != "-":
                pb_name = armq.ptk_name(dict(slug=slug))
                start("trunk", ["nice", "-n", "10", sys.executable, "-I", f"{LAB}/fastship.py", own, fl, lane, "--subject", subject, "--trunk", pb_base,
                                "--private-trunk", pb_name, "--merge-only"] + (["--name", slug] if slug else []))
        except (Exception, SystemExit) as e:  # noqa: BLE001  armq builds it as usual
            say(f"trunk  not prebuilt: {str(e)[:120]}")
    ftag = "pa" + time.strftime("%m%d%H%M%S", time.gmtime()) + f"_{os.getpid()}"  # two prearms in one second collided
    if "--no-fire" not in switches:
        start("fire", ["nice", "-n", "10", sys.executable, "-I", f"{LAB}/firecount.py", target, fl, "--n", flags.get("--n", "100"), "--tag", ftag] + (["--base", spec.split(":", 1)[1]] if donor != "-" and ":" in spec and os.path.exists(os.path.join(src_of(target), "brain_turn.cc")) else []),
              {"FIRECOUNT_PRIO": "20"})
    if "--no-fault" not in switches:  # 8 Nov (Builder: sfx2 passed prearm, then 276 faults and 42k fuel cut-offs at shipcheck): flags ON, release
        start("fault", ["nice", "-n", "10", sys.executable, "-I", f"{LAB}/faultcheck.py", target, fl], {"FAULTCHECK_PRIO": "20"})
    res = {}
    if donor != "-":
        try:
            sys.argv = ["shipcheck.py"]
            import shipcheck
            ok, why = shipcheck.base_check_lines(donor, base, None)
            if not ok:  # 12 Nov ~22:5xZ (Builder, ES_TSBL on v843's baked ES_TAB): the same unbake rule as shipcheck's base check: the donor's
                # only missing base lines are baked flag tables it turns back into runtime tables (constexpr -> const volatile, same initializer)
                try:
                    par_ = None  # the baked base's own lines are judged against the live it was baked from (its BASE file's BASE=)
                    try:
                        par_ = next((ln.split("=", 1)[1].strip() for ln in open(os.path.join(REPO, "bots", base, "BASE")) if ln.startswith("BASE=")), None)
                    except OSError:
                        par_ = None
                    if not par_ or not os.path.isdir(os.path.join(REPO, "bots", par_, "src")):
                        raise RuntimeError(f"no unbaked parent for {base}")
                    miss = shipcheck.live_own_missing(donor, base, par_)
                    if miss and len(miss) <= 4:
                        C = shipcheck.src_files(donor)
                        back = []
                        for fn, ln in miss:
                            mm = shipcheck.UNBAKE_RE.match(ln.split("//", 1)[0].strip())
                            hit = next((x for x in C.get(fn, []) if mm and "volatile" in x and shipcheck.UNBAKE_RE.match(x.split("//", 1)[0].strip())
                                        and shipcheck.UNBAKE_RE.match(x.split("//", 1)[0].strip()).group(1) == mm.group(1)), None)
                            back.append(hit or "")
                        if all(back) and shipcheck.unbake_only([ln for _, ln in miss], back):
                            ok, why = True, "built on the base; its only missing lines are baked tables it turns back into runtime tables (unbake)"
                except Exception as e:  # noqa: BLE001
                    why += f" (unbake check: {str(e)[:60]})"
            if not ok and "changed without a new switch" in why:  # 12 Nov ~22:5xZ (Builder, ES_TSBL): a MULTI-LINE baked table turned back
                # into a runtime table: every reported changed line is `inline constexpr int X_TAB[n] = {` whose donor twin is `inline const
                # volatile int X_TAB[n] = {` with the same body to `};` (same values as the base, so flag 0 plays as the base; ident proves it)
                try:
                    reps = re.findall(r"(\S+?):\d+: (\d+) live line\(s\) changed without a new switch: '(inline constexpr int (\w+_TAB)\[\d*\] = \{)'", why)
                    tot = sum(int(x) for x in re.findall(r"(\d+) live line\(s\) changed without a new switch", why))
                    def block(path, name, kind):
                        L = open(path).read().splitlines()
                        for i, x in enumerate(L):
                            if re.match(rf"\s*inline\s+{kind}\s+int\s+{name}\s*\[", x):
                                j = i
                                while j < len(L) and "};" not in L[j]:
                                    j += 1
                                return [y.split("//", 1)[0].strip() for y in L[i + 1:j + 1]]
                        return None
                    good = 0
                    for fn, n_, _decl, name in reps:
                        bb = block(os.path.join(REPO, "bots", base, "src", fn), name, "constexpr")
                        dd = block(os.path.join(REPO, "bots", donor, "src", fn), name, r"const\s+volatile")
                        if bb is not None and dd is not None and bb == dd:
                            good += int(n_)
                    if reps and good == tot:
                        ok, why = True, f"built on the base; its only changed lines turn baked tables back into runtime tables ({', '.join(r[3] for r in reps)}; unbake)"
                except Exception as e:  # noqa: BLE001
                    why += f" (multi-line unbake check: {str(e)[:60]})"
            res["base"] = (ok, why[:160])
        except (Exception, SystemExit) as e:  # noqa: BLE001
            res["base"] = (False, f"base check failed to run: {str(e)[:120]}")
        say(f"base   {'ok' if res['base'][0] else 'FAIL'}: {res['base'][1]}")
    if donor != "-":  # 8 Nov: a hook between an unbraced if/else and its body (b1554 ESC: .26 at flag 0)
        import bracecheck
        hb = [h for h in bracecheck.hits(donor, base) if not h[5]]
        res["brace"] = (not hb, "; ".join(f"{f}:{ln} '{new[:50]}' after unbraced '{ctl[:50]}'" for f, ln, ctl, new, _b, _w in hb[:3])
                        or "no hook in an unbraced body")
        say(f"brace  {'ok' if res['brace'][0] else 'FAIL'}: {res['brace'][1]}")
    if donor != "-":  # 11 Nov (RC: stored bank patches set live's FB6_BITS 56 -> 0 and un-baked R2B in cprs and fpb3)
        bad = bits_guard(donor, base, fl)
        res["bits"] = (not bad, "; ".join(bad[:4]) if bad else "no *_BITS value or *_TAB bake state changed outside the line's own flips")
        say(f"bits   {'ok' if res['bits'][0] else 'FAIL'}: {res['bits'][1]}")
    r = subprocess.run([sys.executable, "-I", f"{LAB}/flip.py", "check", src_of(target), fl], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    nocode = [x for x in out.splitlines() if "NOCODE" in x]
    res["flips"] = (r.returncode == 0 and not nocode, ("; ".join(x for x in out.splitlines() if x.startswith(("REFUSE", "WARN NOCODE"))) or "data-only")[:200])
    say(f"flips  {'ok' if res['flips'][0] else 'FAIL'}: {res['flips'][1]}")
    # wait for the game steps (one waiter, bounded)
    deadline = time.time() + int(os.environ.get("PREARM_TIMEOUT", 1800))
    while procs and time.time() < deadline:
        for name, (p, log) in list(procs.items()):
            if p.poll() is None:
                continue
            log.close()
            txt = open(os.path.join(run, name + ".log"), errors="replace").read()
            if name == "fault":
                m = re.search(r"^FAULTCHECK (PASS|FAIL|ERROR)[^:]*:? ?(.*?)(?:  \[logs|$)", txt, re.M)
                res["fault"] = (p.returncode == 0 and bool(m) and m.group(1) == "PASS",
                                (m.group(2)[:200] if m else (txt.strip().splitlines()[-1:] or ["no output"])[0][:160]))
                say(f"fault  {'ok' if res['fault'][0] else 'FAIL'}: {res['fault'][1]} ({time.time() - t0:.0f} s)")
                del procs[name]
                continue
            if name == "merge":
                fl_ = [x.strip()[5:] for x in txt.splitlines() if x.startswith("  FAIL ")]
                m = re.search(r"== MERGECHECK (PASS|FAIL)", txt)
                res["merge"] = (p.returncode == 0 and bool(m) and m.group(1) == "PASS",
                                ("; ".join(fl_[:2])[:200] if fl_ else "sections a-d, lint ratchet, rules test" if m else
                                 (txt.strip().splitlines()[-1:] or ["no output"])[0][:160]))
                say(f"merge  {'ok' if res['merge'][0] else 'FAIL'}: {res['merge'][1]} ({time.time() - t0:.0f} s)")
                del procs[name]
                continue
            if name == "trunk":
                m = re.search(r"^PREBUILT (\S+) on (\S+) \((\d+) s\)", txt, re.M)
                why = [x.strip() for x in txt.splitlines() if re.search(r"trunkmerge:|conflict|IDENTITY|FAIL", x)] or txt.strip().splitlines()[-1:] or ["no output"]
                res["trunk"] = (bool(m), f"{m.group(1)} on {m.group(2)} in {m.group(3)} s" if m else why[-1][:200])
                prebuilt = f"{m.group(1)}@{m.group(2)}" if m else None
                say(f"trunk  {'ok' if m else 'FAIL'}: {res['trunk'][1]} ({time.time() - t0:.0f} s)")
                if m:  # 10 Nov (Rule Checker X139): the byte-charged memory.fill/copy sites (>= 128 B) this trunk ADDS v live; information
                    try:
                        lv = open("/data/zw4424/st/bq/live.txt").readline().split()[1]
                        bs = subprocess.run([sys.executable, "-I", f"{REPO}/tools/cxe/bulkscan.py", m.group(1), "--diff", lv, "--top", "5"],
                                            capture_output=True, text=True, timeout=120).stdout.strip().splitlines()
                        hd = re.search(r"(\d+) sites in (\d+) functions", bs[0]) if bs else None
                        if hd:
                            bulk_note[0] = f"bulk +{hd.group(1)} site(s) >= 128 B v live"
                            say("bulk   " + bulk_note[0] + (": " + " | ".join(x.strip()[:110] for x in bs[1:4]) if hd.group(1) != "0" else "") + " (information)")
                    except (OSError, IndexError, subprocess.SubprocessError):
                        pass
                del procs[name]
                continue
            if name == "capped":
                m = re.search(r"CHANGED (\d+)/(\d+)", txt)
                capped_note[0] = (f"capped {m.group(1)}/{m.group(2)} games changed at 100k (fuel-cut games excluded)" if m else "capped: no result")
                say("capped " + capped_note[0] + (": NOT play-identical at the real budget" if m and m.group(1) != "0" else "") + " (information)")
                del procs[name]
                continue
            if name == "logic":
                m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", txt)
                say("logic  " + (f"{m.group(1)}/{m.group(2)} games identical with fuel_remaining() constant: "
                                 + ("only the bot's fuel readings differ (a cost change)" if m.group(1) == m.group(2) else "the flag-0 code changes decisions, not just cost") if m else "no result"))
                del procs[name]
                continue
            if name == "affects":
                m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", txt)
                if m and int(m.group(2)) > 0:
                    pct = 100.0 * (int(m.group(2)) - int(m.group(1))) / int(m.group(2))
                    lim = float(os.environ.get("PREARM_RARE_MAX", "30"))
                    res["rare"] = (pct <= lim, f"flipped form changes {pct:.1f}% of games (30 maps x 2, unlimited fuel)" +
                                   ("" if pct <= lim else f" > {lim:g}%: NOT RARE, arm it on the behaviour (or fix) lane without --rare"))
                    say(f"rare   {'ok' if res['rare'][0] else 'FAIL'}: {res['rare'][1]}")
                else:
                    say("rare   affects not read (information): " + (txt.strip().splitlines()[-1:] or ["no output"])[0][:120])
                if aff_bot:
                    try:
                        os.remove(os.path.join(REPO, "bots", aff_bot))  # the link only; its dir under /data/zw4424/st/new/bots stays (newbot layout)
                    except OSError:
                        pass
                del procs[name]
                continue
            if name == "ident":
                m = re.search(r"identity at unlimited fuel : (\d+)/(\d+)", txt)
                res["ident"] = (p.returncode == 0 and bool(m), (f"{m.group(1)}/{m.group(2)} games identical" if m else txt.strip().splitlines()[-1:][0][:120] if txt.strip() else "no output"))
                say(f"ident  {'ok' if res['ident'][0] else 'FAIL'}: {res['ident'][1]} ({time.time() - t0:.0f} s)")
                if not res["ident"][0] and m:  # 8 Nov: why it differs, the check agents ran by hand: same decisions with fuel_remaining constant = cost only. Information; ident stays FAIL
                    start("logic", ["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", base, donor, "--maps", "20", "--seed", "1", "--logic"], {"PILOTCXE_PRIO": "20"})
            else:
                rows = re.findall(r"^  (\S+)\s+(\d+)\s+([\d.]+)\s+(\d+) \(\s*([\d.]+)%\)", txt, re.M)
                read = re.search(r"(\d+) of (\d+) games read", txt)
                fired = {t: (int(f), int(g), pct) for t, f, _, g, pct in rows}
                want = [x for x in flags.get("--fire", "").split(",") if x]
                if not read or int(read.group(1)) == 0:
                    res["fire"] = (False, "no games read" if read else (txt.strip().splitlines()[-1:] or ["no output"])[0][:160])
                elif want:
                    miss = [t for t in want if fired.get(t, (0, 0, 0))[0] == 0]
                    res["fire"] = (not miss, ("never fired: " + ", ".join(miss)) if miss else ", ".join(f"{t} in {fired[t][2]}% of games" for t in want))
                elif "own DG lines" in txt:  # the agent's DG lines are the counters
                    hot = {t: v for t, v in fired.items() if v[0] > 0}
                    res["fire"] = (bool(hot), (", ".join(f"{t} {v[2]}%" for t, v in sorted(hot.items(), key=lambda x: -x[1][0])[:4]) or "no DG tag fired")
                                   + f" ({read.group(1)} games)")
                else:  # each flipped flag's own feature must fire (other features' counters fire anyway)
                    parts, good = [], True
                    for nm, where in feat_of.items():
                        if not where.startswith("fc_"):
                            good = False
                            parts.append(f"no counter for {nm} (defined in {where}): put it in its own file (newfeat.py), or --fire TAG with DG lines, or --no-fire")
                            continue
                        mine = {t: v for t, v in fired.items() if t.startswith(where)}
                        stem = nm.split("_")[0]
                        if where == "fc_" and any(t.startswith(f"fc_{stem}.") for t in fired):  # 11 Nov (b1827): new layout: a flag's own counters
                            mine = {t: v for t, v in fired.items() if t.startswith(f"fc_{stem}.")}  # are fc_<STEM>.*, not every fc_ counter
                        elif where == "fc_":
                            mine = {}
                        hot = {t: v for t, v in mine.items() if v[0] > 0}
                        cached = cached_flag(target, nm)
                        if not hot and (not mine or all(".draft" in t for t in mine) or cached):
                            # 11 Nov (b1827): no counter can see it: a flag read once into a static (PSM: `static const bool psm_on = PSM_ON(1)`),
                            # or counters only on draft-turn code (DFK draft_turn_394: the DG buffer never drains on the draft turn)
                            why = (f"read once into a static at {cached}" if cached else "its counters sit in draft-turn code" if mine
                                   else "no counter placed")
                            parts.append(f"{nm}: NOT counted ({why}); count it with tools/lab/dgkit.py DG lines or draftdiag.py")
                            continue
                        good &= bool(hot)
                        parts.append(f"{nm}: " + (", ".join(f"{t} {v[2]}%" for t, v in sorted(hot.items(), key=lambda x: -x[1][0])[:3]) if hot
                                                  else f"none of {len(mine)} {where}{stem if where == 'fc_' else ''}* counters fired"))
                    if not feat_of:
                        good, parts = False, ["no flipped flag found in the source"]
                    dfiles = draft_only_files(donor, base) if not good and feat_of else None
                    if dfiles:  # 11 Nov (b1827 CLT1): dgkit's DG buffer never drains on the draft turn, so draft-only code reads as "never fired"
                        good = True
                        parts = [f"draft-only change ({', '.join(dfiles)}): dgkit cannot see draft-turn records, fire row NOT counted; "
                                 "check firing with tools/lab/draftdiag.py or cxeident --where"]
                    res["fire"] = (good, "; ".join(parts) + f" ({read.group(1)} games; ENTERED counts: entry to the flag's functions, not play "
                                         "changes. A rare line's play change is read by its bank probe, which stops at 0 changed of 100)")
                if not res["fire"][0] and ("nothing to count" in res["fire"][1] or "no counter for" in res["fire"][1]
                                           or "no flipped flag found" in res["fire"][1]):
                    # 12 Nov (owner via the Coordinator, CLAUDE.md §2 'No arbitrary Step 0 bars': only a bit that fires 0 times stops a line):
                    # 'nothing countable' is not '0 firings': information, the played read decides
                    res["fire"] = (True, "firing NOT COUNTED (information, not a stop: owner 12 Nov, only 0 firing stops a line): " + res["fire"][1][:200])
                if not res["fire"][0] and donor != "-":
                    dv = draft_value_flip(donor, base, target, fl)
                    if dv:  # 12 Nov (TB; Builder b2185 DTZ arm B): a value flip read only by draft-turn code has no play-turn firing to count
                        res["fire"] = (True, dv)
                say(f"fire   {'ok' if res['fire'][0] else 'FAIL'}: {res['fire'][1]} ({time.time() - t0:.0f} s)")
            del procs[name]
        time.sleep(3)
    for name, (p, log) in procs.items():  # timed out
        p.terminate()
        res[name] = (False, "timed out")
    ok = all(v[0] for v in res.values())
    line = " | ".join(f"{k} {'ok' if v[0] else 'FAIL'}" for k, v in res.items()) + (f" | {capped_note[0]}" if capped_note[0] else "") + (f" | {bulk_note[0]}" if bulk_note[0] else "")
    queued = ""
    if ok and "--no-queue" not in switches:
        cmd = [sys.executable, "-I", f"{LAB}/armq.py", "add", spec, fl, lane, subject] + ([slug] if slug else [])
        cmd += ["--prebuilt", prebuilt] if prebuilt else []
        cmd += ["--rare", flags["--rare"]] if "--rare" in flags else []
        cmd += ["--rare-fams", flags["--rare-fams"]] if "--rare-fams" in flags else []
        cmd += [s for s in ("--bugbar", "--parambar", "--seqspar", "--front") if s in switches]
        q = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        queued = f"; armq add rc {q.returncode}: {((q.stdout + q.stderr).strip().splitlines() or [''])[-1][:160]}"
        ok = q.returncode == 0
    print(f"PREARM {'PASS' if ok else 'FAIL'} {spec} {fl}: {line} ({time.time() - t0:.0f} s){queued}  [logs {run}]", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
