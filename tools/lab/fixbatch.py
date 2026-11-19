#!/usr/bin/env python3
"""fixbatch: bug-fix PASSes ship together, not one by one. Tool Builder, 9 Nov (owner ~21:35Z, to the Builder: "yes batch bug fixes"; every ship
moves live and makes every waiting armed line stale, so small fix ships go out as one bundle).

  shipcheck.py: a plain FIX-LANE PASS (marker LANE=fix, with or without BUGBAR=1; not ctrunk, RARE, param, draft or behaviour, not a STACK_ON read,
    not a CONFIRM MODE read, not a fixbatch bundle itself) is NOT submitted: add_entry() appends it to bq/fixbatch.tsv and shipcheck prints 'BATCHED: ...'.
  python3 -I tools/lab/fixbatch.py --tick     one pass (shipwatch spawns it every 60 s; a lock makes overlapping passes exit at once)
  python3 -I tools/lab/fixbatch.py --loop     the same every 60 s, standalone (not needed while shipwatch spawns ticks)
  python3 -I tools/lab/fixbatch.py --drop BOT [BOT ...]   take waiting entries out (they are not shipped or re-armed)
  python3 -I tools/lab/fixbatch.py --status   what waits, the running bundle, and whether a release would go now
  FIXBATCH_DRY=1 ... --tick                   decide and print the armq commands; nothing is armed, no file changes

RELEASE (one bundle at a time): the list holds >= N_MIN (3) fixes OR its oldest entry is >= AGE_MIN (90) min old, AND no behaviour/draft/rare
  (or param) shipcheck near its verdict is running (running for >= NEAR_MIN (3) min; coordinator 9 Nov), unless the oldest entry is >= STARVE_MIN (240) min old. A release takes
  every entry: entries whose flips give a flag another value than an earlier entry (best point first) are armed singly at once; the rest go as ONE
  armq line (armq.py add DONORS FLIPS fix "bundle(fixbatch): ..." fxb<n>z --bugbar --front --confirm-from <best entry's TAG> --confirm-n 1):
  armq's preflight merges every donor onto live (a conflict refuses the line), fastship builds it on live, shipcheck runs CONFIRM MODE (1,200
  fresh maps, point >= BUGBAR_PT .50, CI upper >= .50, faults, capped fuel, death guard) and submits on PASS. One entry alone is armed singly.
FALLBACK: preflight refused (a conflict), or the bundle's chain (its rebases fxb<n>z_r*, requeues fxb<n>z[ir]) ends without shipping (FAIL,
  INCONCLUSIVE twice, arm failure; settled for GRACE 10 min): every fix is re-armed singly, best point first, as shipcheck's reread_requeue
  does (armq.py front DONORS FLIPS fix SUBJECT SLUGf [--bugbar] --confirm-from ITS_TAG --confirm-n 1): its confirm read submits on PASS.
OFF: touch /data/USER/st/bq/fixbatch_OFF: shipcheck submits fix PASSes at once again, and the next tick re-arms whatever waits singly.
Files: bq/fixbatch.tsv (waiting), bq/fixbatch.log (every decision), bq/fixbatch_state.json (the running bundle), bq/fixbatch_dry.tsv (DRY shipchecks).
QUIET (owner 10 Nov ~14:55Z: "shorten the bug wait when there are not many ideas"): when at most QUIET_MAX (2) behaviour/param/draft/rare
  shipchecks run and no such line waits in armq.txt, AGE_MIN becomes AGE_MIN_QUIET (15) and STARVE_MIN becomes STARVE_MIN_QUIET (25): a lone
  fix waits 15 min, not 90, and a near-verdict idea check holds a bundle at most 25 min. Rare FIX-lane probes (bug reads on the rare bar) count
  as neither busy nor a blocker in QUIET (a stale rare PASS gets the usual confirm read). FIXBATCH_QUIET_MAX=-1 turns it off.
Settings (env or bq/fixbatch.conf lines KEY=VALUE): FIXBATCH_N_MIN, FIXBATCH_AGE_MIN, FIXBATCH_NEAR_MIN, FIXBATCH_STARVE_MIN, FIXBATCH_GRACE_MIN,
  FIXBATCH_AGE_MIN_QUIET, FIXBATCH_STARVE_MIN_QUIET, FIXBATCH_QUIET_MAX.
RELEASE TRAIN (10 Nov, Tool Builder for the Builder: a ship every 20 min): OFF unless bq/train_ON exists (absent: every rule above, unchanged).
  On: a PASS of ANY lane goes to bq/train.tsv; every FIXBATCH_TRAIN_MIN (20) min ONE train (all waiting, or a pending half) departs as this file's
  bundle path (one armq line, CONFIRM read on live, bug bar point .50); unshipped: halves, a failed single to the failed-positive bank. See the
  RELEASE TRAIN block below for the rules; --status shows it.
RIDE-ALONG (10 Nov, owner ~20:52Z): OFF unless bq/ridealong_ON exists (and never with the train on). A release also takes up to RIDE_MAX (2)
  armq rare lines picked by bq/ridealong_pick.txt (slugs, '*' = all) or a 'ride' row (tools/lab/ridealong.py eligible_rows) into the bundle
  line as their own flag values (subject 'slug~'), drops them from armq.txt, records them in state run.riders and bq/ridealong_bundles.json;
  a bundle with one fix and a rider is still a bundle. shipcheck's twin legs read each rider; a bundle that does not ship sends its riders
  back to armq as their own rare lines (unless their ledger decided them); a shipped bundle settles their ledger.
PRE-TEST BUNDLING (FIXPRE, 10 Nov, owner ~21:30Z): OFF unless bq/fixbundle_ON exists. On: >= 3 plain fix lines waiting in armq.txt (not
  --rare) leave armq as ONE line 'bundle(fixpre): ...' fxp<n>z --bugbar, read once (full read, bars unchanged); FAIL/arm failure: halves; a
  member alone goes back to armq as its own line. See the PRE-TEST BUNDLING block above tick(); log lines 'FIXPRE ...'."""
import fcntl
import glob
import json
import math
import os
import re
import subprocess
import sys
import time

Q = os.environ.get("FIXBATCH_Q", "/data/USER/st/bq")
REPO = "/homes/USER/cambc"
BOTS = os.environ.get("FIXBATCH_BOTS", os.path.join(REPO, "bots"))  # (tests: a fake bots dir)
ARMQ_PY = os.environ.get("FIXBATCH_ARMQ", os.path.join(REPO, "tools/lab/armq.py"))  # (tests: a fake armq)
TSV = os.path.join(Q, "fixbatch.tsv")
DRYTSV = os.path.join(Q, "fixbatch_dry.tsv")
LOG = os.path.join(Q, "fixbatch.log")
STATE = os.path.join(Q, "fixbatch_state.json")
OFF = os.path.join(Q, "fixbatch_OFF")
CONF = os.path.join(Q, "fixbatch.conf")
SW_STATE = os.path.join(Q, "shipwatch_state.json")
LIVE = os.path.join(Q, "live.txt")
ARMQ_FILE = os.path.join(Q, "armq.txt")
ARMQ_FAILED = os.path.join(Q, "armq.failed")
PENDING = os.path.join(Q, "pending_reads.txt")
COLS = ("t", "bot", "tag", "donors", "flips", "lane", "bugbar", "point", "subject", "fuelx")
DRY = os.environ.get("FIXBATCH_DRY") == "1"


def setting(key, default):
    v = os.environ.get(key)
    if v is None:
        try:
            for ln in open(CONF):
                k, _, x = ln.strip().partition("=")
                if k == key:
                    v = x
        except OSError:
            pass
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default


def utc(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def log(s):
    line = f"{utc()} {'[dry] ' if DRY else ''}{s}"
    print(line, flush=True)
    if not DRY:
        with open(LOG, "a") as f:
            f.write(line + "\n")


class locked:
    def __init__(self, path, block=True):
        self.path, self.block = path, block

    def __enter__(self):
        self.f = open(self.path, "a")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | (0 if self.block else fcntl.LOCK_NB))
        except BlockingIOError:
            self.f.close()
            return False
        return True

    def __exit__(self, *e):
        self.f.close()


def clean(x):
    return re.sub(r"[\t\n\r]", " ", str(x if x is not None else "")).strip()


def add_entry(row, dry=False):
    """shipcheck: one passed fix -> a line of fixbatch.tsv (fixbatch_dry.tsv for a DRY shipcheck)."""
    row = dict(row, t=row.get("t") or utc())
    dst = DRYTSV if dry else TSV
    with locked(TSV + ".lock"):
        with open(dst, "a") as f:
            f.write("\t".join(clean(row.get(c, "")) for c in COLS) + "\n")
    if not dry:
        with open(LOG, "a") as f:
            f.write(f"{utc()} BATCHED {row['bot']} TAG {row['tag']} point {row.get('point')} donors {row.get('donors')} flips {row.get('flips')!r}"
                    f"{' (bug bar)' if str(row.get('bugbar')) == '1' else ''}\n")
    return dst


def entries():
    out = []
    try:
        for ln in open(TSV):
            w = ln.rstrip("\n").split("\t")
            if len(w) >= 8 and w[0] != "t":
                out.append(dict(zip(COLS, w + [""] * (len(COLS) - len(w)))))
    except OSError:
        pass
    return out


def remove_entries(gone):
    keys = {(e["bot"], e["tag"]) for e in gone}
    with locked(TSV + ".lock"):
        keep = [e for e in entries() if (e["bot"], e["tag"]) not in keys]
        with open(TSV + ".new", "w") as f:
            for e in keep:
                f.write("\t".join(clean(e.get(c, "")) for c in COLS) + "\n")
        os.replace(TSV + ".new", TSV)


def _epoch(stamp):
    import calendar
    return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))


def age(e):
    try:
        return (time.time() - _epoch(e["t"])) / 60
    except (ValueError, KeyError):
        return 0.0


def point(e):
    try:
        return float(e.get("point"))
    except (TypeError, ValueError):
        return -math.inf


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return dict(n=0, run=None)


def save_state(st):
    if DRY:
        return
    with open(STATE + ".new", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(STATE + ".new", STATE)


def marker(name):
    kv = {}
    try:
        for ln in open(os.path.join(BOTS, name, "SHIPCHECK")):
            k, eq, v = ln.strip().partition("=")
            if eq and not k.startswith("#"):
                kv[k.strip()] = v.strip()
    except OSError:
        pass
    return kv


def lock_held(name):
    with open(os.path.join(Q, f".shipwatch_{name}.lock"), "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def sw_state():
    try:
        return json.load(open(SW_STATE))
    except (OSError, ValueError):
        return {}


def blocker(skip_fix_rare=False):
    """A behaviour/param/draft/rare shipcheck near its verdict: still running and running for >= NEAR_MIN (3) min -> 'NAME (LANE, N min)', else
    None (coordinator 9 Nov: don't overtake it; a check that just started has most of its read ahead, and the stale-pass confirm makes a collision cheap)."""
    near = setting("FIXBATCH_NEAR_MIN", 3.0)
    for name, s in sw_state().items():
        if name.startswith("_") or not isinstance(s, dict) or s.get("status") != "started":
            continue
        mins = (time.time() - float(s.get("at") or 0)) / 60
        if mins < near or not lock_held(name):
            continue
        kv = marker(name)
        lane = kv.get("LANE", "behaviour")
        if skip_fix_rare and lane == "fix" and lane not in ("behaviour", "param", "draft"):  # QUIET: a rare FIX probe is a bug read, not an idea
            continue
        if lane in ("behaviour", "param", "draft") or "RARE" in kv:
            return f"{name} ({'rare' if 'RARE' in kv else lane}, started {mins:.0f} min ago)"
    return None


def behaviour_load():
    """-> (running behaviour/param/draft/rare shipchecks, such lines waiting in armq.txt): how busy the idea lanes are (QUIET)."""
    run = 0
    for name, s in sw_state().items():
        if name.startswith("_") or not isinstance(s, dict) or s.get("status") != "started" or not lock_held(name):
            continue
        kv = marker(name)
        if kv.get("LANE", "behaviour") in ("behaviour", "param", "draft") or ("RARE" in kv and kv.get("LANE") != "fix"):  # rare FIX probes are bug reads
            run += 1
    wait = 0
    try:
        for ln in open(os.path.join(Q, "armq.txt")):
            w = ln.split()
            if ln.strip() and not ln.startswith("#") and ({"behaviour", "draft"} & set(w) or "--rare" in w or "--parambar" in w):
                wait += 1
    except OSError:
        pass
    return run, wait


def flips_of(s):
    return dict(x.split("=", 1) for x in (s or "").split() if "=" in x)


def slug_of(bot):
    return re.sub(r"[^a-z0-9]", "", bot.split("_", 2)[-1].lower())[:20] or "fix"


def armq(args):
    cmd = [sys.executable, "-I", ARMQ_PY] + args
    if DRY:
        log("DRY: would run: armq.py " + " ".join(repr(a) if " " in a else a for a in args))
        return 0, "DRY"
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=900)
    return r.returncode, (r.stdout + r.stderr).strip()


def arm_single(e, why):
    """One fix re-armed as shipcheck's reread_requeue does: at the front, fix lane, its own bug bar, a CONFIRM read from its own full PASS."""
    fl, dn = e.get("flips") or "", e.get("donors") or "-"
    subj = e.get("subject") or f"fix(trunk): {fl}"[:60]
    args = ["front", dn, fl, "fix", subj, slug_of(e["bot"]) + "f"]
    args += ["--bugbar"] if str(e.get("bugbar")) == "1" else []
    args += ["--fuelx", e["fuelx"]] if e.get("fuelx") else []
    args += ["--confirm-from", e["tag"], "--confirm-n", "1"] if re.fullmatch(r"[A-Za-z0-9_]+", e.get("tag") or "") else []
    rc, out = armq(args)
    log(f"single {e['bot']} (TAG {e['tag']}, point {e.get('point')}): {why}: armq front rc {rc}: {out.splitlines()[-1][:200] if out else ''}")
    if rc and not DRY:
        with open(PENDING, "a") as f:
            f.write(f"PENDING: {utc()} {e['bot']} (fix{', bug bar' if str(e.get('bugbar')) == '1' else ''}) PASSED (TAG {e['tag']}), fix batch fallback "
                    f"could not re-arm it (armq rc {rc}); re-arm: armq.py add {dn} \"{fl}\" fix \"{subj}\" --front"
                    f"{' --bugbar' if str(e.get('bugbar')) == '1' else ''}\n")


def is_fallback_single(bot, hours=6):
    """10 Nov (owner: "why haven't we uploaded the passed stuff"): True when bot is a fallback single this file re-armed (its slug = a logged
    'single nova_b..._SLUG' line's slug + 'f', within hours). Its confirm PASS must submit, not come back here: else PASS -> batch -> bundle
    fails -> singles -> confirm PASS -> batch, round and round (voh1f/brs7gf/ckf2/q3/rcb255, 10 Nov 15:39Z)."""
    me = slug_of(bot)
    cut = time.time() - hours * 3600
    try:
        for ln in open(LOG):
            m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) single (nova_\S+)", ln)
            if m and slug_of(m.group(2)) + "f" == me:
                if time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ")) - time.timezone >= cut:
                    return True
    except OSError:
        pass
    return False


def singles(es, why):
    """Best point first at the head of the queue: armq front puts each at the head, so the worst goes in first."""
    for e in sorted(es, key=point):
        arm_single(e, why)


def subject(slugs):
    s, used = f"bundle(fixbatch): {len(slugs)} fixes", 0
    for x in slugs:
        if len(s) - len("bundle(fixbatch): ") + len(x) + 1 > 52:
            break
        s += (" " if used == 0 else ",") + x
        used += 1
    return s + (f" +{len(slugs) - used}" if used < len(slugs) else "")


RIDE_ON = os.path.join(Q, "ridealong_ON")


def ride_pick(seen):
    """10 Nov (owner ~20:52Z, ride-along; OFF unless bq/ridealong_ON, and never with the release train on): armq rare lines picked to ride
    in this bundle (tools/lab/ridealong.py eligible_rows: ridealong_pick.txt or a 'ride' row, ledger not decided, flips not clashing)."""
    if not os.path.exists(RIDE_ON) or train_on():
        return []
    try:
        import ridealong
        return [ridealong.rider_of_row(r) for r in ridealong.eligible_rows(seen, ARMQ_FILE)]
    except Exception as e:  # noqa: BLE001  never break a release
        log(f"ride-along: no riders ({type(e).__name__}: {e})")
        return []


def ride_readd(riders, why):
    """A rider back on the arm queue as its own rare line (the bundle did not take it, or did not ship), unless its ledger decided it."""
    led = {}
    try:
        led = json.load(open(os.path.join(Q, "ridealong.json")))
    except (OSError, ValueError):
        pass
    for r in riders:
        if led.get(r["slug"], {}).get("status") in ("PASS", "FAIL"):
            log(f"ride-along {r['slug']}: not re-armed: ledger {led[r['slug']]['status']} ({why})")
            continue
        args = ["add", r.get("donor") or "-", r["flips"], "fix", r.get("subject") or f"fix(rare): {r['slug']}"[:60], r["slug"], "--rare", str(r.get("rare") or 420)]
        args += ["--rare-fams", r["rarefams"]] if r.get("rarefams") else []
        args += ["--bugbar"] if r.get("bugbar") else []
        rc, out = armq(args)
        log(f"ride-along {r['slug']}: back to armq as its own rare line ({why}): rc {rc}: {out.splitlines()[-1][:160] if out else ''}")


def release(es, st, why):
    es = sorted(es, key=point, reverse=True)
    seen, take, clash, keys = {}, [], [], set()
    for e in es:
        k = (e.get("donors"), " ".join(sorted((e.get("flips") or "").split())))
        if k in keys:  # the same fix twice (a rebased copy passed too): once is enough
            log(f"duplicate of an entry already taken: {e['bot']} (TAG {e['tag']}) dropped")
            continue
        f = flips_of(e.get("flips"))
        if any(x in seen and seen[x] != v for x, v in f.items()):
            clash.append(e)
            continue
        keys.add(k)
        seen.update(f)
        take.append(e)
    log(f"RELEASE ({why}): {len(es)} entries: {', '.join(e['bot'] for e in es)}")
    if not DRY:
        remove_entries(es)
    if clash:
        singles(clash, "its flips give a flag another value than a better entry")
    riders = ride_pick(seen) if take else []
    if len(take) == 1 and not riders:
        singles(take, "the only fix in this release")
        return
    if not take:
        return
    st["n"] = int(st.get("n") or 0) + 1
    slug = f"fxb{st['n']}z"
    donors = []
    for e in take:
        for d in (e.get("donors") or "-").split(","):
            if d and d != "-" and d not in donors:
                donors.append(d)
    for r in riders:  # ride-along rare bits: their own flag values in the same line (ridealong_ON only)
        for d in (r.get("donor") or "-").split(","):
            if d and d != "-" and d not in donors:
                donors.append(d)
        seen.update(flips_of(r["flips"]))
    fl = " ".join(f"{k}={v}" for k, v in seen.items())
    fx = [float(e["fuelx"]) for e in take if re.fullmatch(r"\d+(\.\d+)?", e.get("fuelx") or "")]
    args = ["add", ",".join(donors) or "-", fl, "fix", subject([slug_of(e["bot"]) for e in take] + [r["slug"] + "~" for r in riders]).replace(f"{len(take) + len(riders)} fixes", f"{len(take)} fixes", 1), slug, "--bugbar", "--front",
            "--confirm-from", take[0]["tag"], "--confirm-n", "1"]
    args += ["--fuelx", f"{max(fx):g}"] if fx else []
    st["run"] = dict(slug=slug, entries=take, t=time.time(), args=args)
    if riders:
        st["run"]["riders"] = [{k: v for k, v in r.items() if k != "row"} for r in riders]
        log(f"bundle {slug}: ride-along rare bits {', '.join(r['slug'] + ' [' + r['flips'] + ']' for r in riders)}: twin legs in its shipcheck")
        if not DRY:
            import ridealong
            ridealong.register(slug, st["run"]["riders"])
        for r in riders:  # off the queue first, so the armq daemon never arms a rider alone meanwhile
            armq(["drop", r["slug"]])
    save_state(st)  # before the add: a crash after it leaves a tracked run ('never armed' -> singles), never an untracked second bundle
    rc, out = armq(args)
    log(f"bundle {slug}: armq add rc {rc}: {' | '.join(out.splitlines()[-4:])[:600]}")
    if rc:
        st["run"] = None
        save_state(st)
        if riders:
            ride_readd([{k: v for k, v in r.items() if k != "row"} for r in riders], f"bundle {slug} not queued")
        if len(take) == 1:
            return singles(take, f"bundle {slug} not queued (armq preflight: a conflict or a refused flip): the only fix")
        singles(take, f"bundle {slug} not queued (armq preflight: a conflict or a refused flip)")


def chain_state(run):
    """-> ('wait' | 'shipped' | 'ended', detail, fingerprint) for the bundle's chain: bots/nova_b*_SLUG* (rebases, requeues)."""
    slug = run["slug"]
    bots = sorted((os.path.basename(p) for p in glob.glob(os.path.join(BOTS, f"nova_b*_{slug}*")) if os.path.isdir(p)),
                  key=lambda b: os.path.getmtime(os.path.join(BOTS, b)))
    live = set()
    try:
        live = {ln.split()[1] for ln in open(LIVE) if len(ln.split()) > 1}
    except OSError:
        pass
    shipped = [b for b in bots if b in live]
    if shipped:
        return "shipped", shipped[-1], None
    queued = []
    try:
        queued = [json.loads(x).get("slug") for x in open(ARMQ_FILE) if x.strip()]
    except (OSError, ValueError):
        pass
    queued = [s for s in queued if s and str(s).startswith(slug)]
    if queued:
        return "wait", f"queued in armq as {queued[0]}", None
    failed = []
    try:
        for x in open(ARMQ_FAILED):
            try:
                d = json.loads(x)
            except ValueError:
                continue
            if str(d.get("slug") or "").startswith(slug) and float(d.get("t") or 0) >= run["t"] - 60:
                failed.append(d.get("slug"))
    except OSError:
        pass
    sw = sw_state()
    if not bots:
        if failed:
            return "ended", f"arm failed (armq.failed: {failed[-1]})", ("failed", tuple(failed))
        if time.time() - run["t"] > 1800:
            return "ended", "never armed in 30 min (see armq.log / armq.failed)", ("none",)
        return "wait", "being armed", None
    b = bots[-1]
    s = sw.get(b) if isinstance(sw.get(b), dict) else None
    status = (s or {}).get("status")
    if status is None or b in (sw.get("_queue") or {}):
        return "wait", f"{b}: marker waiting for shipwatch", None
    if status == "started":
        return "wait", f"{b}: shipcheck running", None
    if "rebased ->" in status:
        return "wait", f"{b}: {status}", None
    return "ended", f"{b}: {status}" + (f"; arm failed {failed[-1]}" if failed else ""), (b, status, tuple(failed))


def resolve(st):
    run = st["run"]
    state, detail, fp = chain_state(run)
    if state == "shipped":
        log(f"bundle {run['slug']} SHIPPED as {detail}: {', '.join(e['bot'] for e in run['entries'])}")
        for r in run.get("riders") or []:  # ride-along: shipped inside the bundle; its ledger keeps reading out as is
            try:
                import ridealong
                ridealong.settle(r["slug"], shipped_in=detail)
            except Exception as e:  # noqa: BLE001
                log(f"ride-along {r['slug']}: settle failed ({e})")
        st["run"] = None
        return save_state(st)
    if state == "wait":
        run.pop("settled", None)
        if time.time() - run["t"] > 12 * 3600 and not run.get("alarm"):
            run["alarm"] = True
            log(f"ALARM bundle {run['slug']} still not settled after 12 h ({detail}): left to the Builder, entries {', '.join(e['bot'] for e in run['entries'])}")
        return save_state(st)
    grace = setting("FIXBATCH_GRACE_MIN", 10.0) * 60
    if run.get("settled", {}).get("fp") != json.dumps(fp):
        run["settled"] = dict(fp=json.dumps(fp), t=time.time())
        return save_state(st)
    if time.time() - run["settled"]["t"] < grace:
        return None
    if run.get("riders"):
        ride_readd(run["riders"], f"bundle {run['slug']} did not ship ({detail[:80]})")
    if train_on():  # release train (10 Nov): no singles; the bundle's fixes split into train halves
        log(f"bundle {run['slug']} ended without shipping ({detail}): release train on: its fixes go to the train as halves, no singles")
        st["run"] = None
        save_state(st)
        tst = train_load()
        train_split(tst, run["entries"], f"fixbatch bundle {run['slug']} did not ship ({detail[:120]})")
        return train_save(tst)
    log(f"bundle {run['slug']} ended without shipping ({detail}): back to the single fixes, best point first")
    st["run"] = None
    save_state(st)
    singles(run["entries"], f"bundle {run['slug']} did not ship ({detail[:120]})")


def decide(es, st):
    """-> (go, why)."""
    if st.get("run"):
        return False, f"bundle {st['run']['slug']} still running"
    if not es:
        return False, "nothing waits"
    n_min, age_lim, starve = setting("FIXBATCH_N_MIN", 3.0), setting("FIXBATCH_AGE_MIN", 90.0), setting("FIXBATCH_STARVE_MIN", 240.0)
    qmax = setting("FIXBATCH_QUIET_MAX", 2.0)
    quiet = False
    if qmax >= 0:
        brun, bwait = behaviour_load()
        if brun <= qmax and bwait == 0:  # QUIET: few ideas in flight, so a ship costs little; don't hold fixes 90 min
            age_lim = min(age_lim, setting("FIXBATCH_AGE_MIN_QUIET", 15.0))
            starve = min(starve, setting("FIXBATCH_STARVE_MIN_QUIET", 25.0))
            quiet = True
    oldest = max(age(e) for e in es)
    if len(es) < n_min and oldest < age_lim:
        return False, f"{len(es)} fixes (< {n_min:g}), oldest {oldest:.0f} min (< {age_lim:g})"
    why = f"{len(es)} fixes, oldest {oldest:.0f} min"
    b = blocker(skip_fix_rare=quiet)
    if b and oldest < starve:
        return False, f"{why}, but {b} is near its verdict (running >= {setting('FIXBATCH_NEAR_MIN', 3.0):g} min)"
    return True, why + (f"; overrides {b}: oldest >= {starve:g} min" if b else "")



# ---------------------------------------------------------------------------------------------------------------------------------------------
# RELEASE TRAIN (Tool Builder 10 Nov, for the Builder: "a ship every 20 min"). OFF unless bq/train_ON exists; absent, nothing below runs (no train
# file is created or read past an existence check) and every decision above is the old one.
#   shipcheck.py train_take(): a PASS of ANY lane (fix, bug bar, behaviour, rare, param, draft; full read or CONFIRM MODE; also a PASS whose base
#     live left mid-read: the train merges its donors onto the live of the day) is not submitted: one line of bq/train.tsv. Not: ctrunk (armq's
#     own train), STACK_ON reads, a train or fixbatch bundle itself, a PASS with no flips and no recorded donors (submitted as before).
#   Every TRAIN_MIN (20) min after the last departure, with no train or old fixbatch bundle running: ONE train departs. A pending half (below) goes
#     first, alone; else every waiting entry. Same flips twice: once. A flag two entries set differently: the better point rides, the other waits
#     for the next train (not a single). Flips all equal live's values already: dropped as live. The train is ONE armq line, fixbatch's bundle path:
#     armq.py add DONORS FLIPS fix "bundle(train): ..." rtr<n>z --bugbar --front --confirm-from <best TAG> --confirm-n 1: armq's preflight merges
#     every donor onto live (a conflict refuses the line), shipcheck runs CONFIRM MODE (1,200 fresh maps v live, point >= .50, CI upper >= .50,
#     faults, capped fuel, death guard) and submits on PASS. Each member keeps its own lane's PASS; the bars do not change. While the train's
#     check runs, its batches jump the pilot queue: '^cq-[a-z]+<TAG>-' in bq/pilot_top.txt, removed when the train ends.
#   FAIL / INCONCLUSIVE (after shipcheck's own one capacity re-arm) / arm failure: no singles. Its entries split in two halves (best point first,
#     alternating: 1st,3rd,5th.. | 2nd,4th,..), queued as the next trains; a half that fails splits again; a train of ONE that fails goes to the
#     failed-positive bank (flagscreen.py bank add, cause power / other) and is dropped.
#   An old fixbatch bundle that ends unshipped while train_ON exists splits into train halves the same way (no singles).
#   train_ON removed: a running train finishes; whatever waits (train.tsv, halves, a train that ends unshipped) is re-armed singly on its own lane
#     and bars with --confirm-from its own TAG (the reread_requeue form), then the old fixbatch rules run as before.
# Files: bq/train_ON (switch), bq/train.tsv (waiting), bq/train_state.json (n, run, groups = pending halves, last_dep), bq/train_dry.tsv (DRY
#   shipchecks); every decision in bq/fixbatch.log as 'TRAIN ...'. Settings: FIXBATCH_TRAIN_MIN (20), FIXBATCH_GRACE_MIN (as the bundle).
TRAIN_ON = os.path.join(Q, "train_ON")
TRAIN_TSV = os.path.join(Q, "train.tsv")
TRAIN_DRYTSV = os.path.join(Q, "train_dry.tsv")
TRAIN_STATE = os.path.join(Q, "train_state.json")
PILOT_TOP = os.environ.get("FIXBATCH_PILOT_TOP", os.path.join(Q, "pilot_top.txt"))
FLAGSCREEN_PY = os.environ.get("FIXBATCH_FLAGSCREEN", os.path.join(REPO, "tools/lab/flagscreen.py"))  # (tests: a fake bank)
TCOLS = COLS + ("bars",)  # bars: the entry's marker bar keys as JSON (BUGBAR, RARE, PARAMBAR, FUELX, ...), for a single re-arm when train_ON goes


def train_on():
    return os.path.exists(TRAIN_ON)


def train_add(row, dry=False):
    """shipcheck: one PASS of any lane -> a line of train.tsv (train_dry.tsv for a DRY shipcheck)."""
    row = dict(row, t=row.get("t") or utc())
    if not isinstance(row.get("bars"), str):
        row["bars"] = json.dumps(row.get("bars") or {}, sort_keys=True)
    dst = TRAIN_DRYTSV if dry else TRAIN_TSV
    with locked(TRAIN_TSV + ".lock"):
        with open(dst, "a") as f:
            f.write("\t".join(clean(row.get(c, "")) for c in TCOLS) + "\n")
    if not dry:
        with open(LOG, "a") as f:
            f.write(f"{utc()} TRAIN JOIN {row['bot']} TAG {row['tag']} lane {row.get('lane')}{' (bug bar)' if str(row.get('bugbar')) == '1' else ''} "
                    f"point {row.get('point')} donors {row.get('donors')} flips {row.get('flips')!r}\n")
    return dst


def train_entries():
    out = []
    try:
        for ln in open(TRAIN_TSV):
            w = ln.rstrip("\n").split("\t")
            if len(w) >= 8 and w[0] != "t":
                out.append(dict(zip(TCOLS, w + [""] * (len(TCOLS) - len(w)))))
    except OSError:
        pass
    return out


def train_remove(gone):
    keys = {(e["bot"], e["tag"]) for e in gone}
    if DRY or not keys:
        return
    with locked(TRAIN_TSV + ".lock"):
        keep = [e for e in train_entries() if (e["bot"], e["tag"]) not in keys]
        with open(TRAIN_TSV + ".new", "w") as f:
            for e in keep:
                f.write("\t".join(clean(e.get(c, "")) for c in TCOLS) + "\n")
        os.replace(TRAIN_TSV + ".new", TRAIN_TSV)


def train_load():
    try:
        st = json.load(open(TRAIN_STATE))
    except (OSError, ValueError):
        st = {}
    st.setdefault("n", 0)
    st.setdefault("run", None)
    st.setdefault("groups", [])
    st.setdefault("last_dep", 0)
    return st


def train_save(st):
    if DRY:
        return
    with open(TRAIN_STATE + ".new", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(TRAIN_STATE + ".new", TRAIN_STATE)


def train_pending():
    """Anything the train holds (waiting, halves, a running train): True even with train_ON gone, so it is finished or re-armed, never lost."""
    if not (os.path.exists(TRAIN_TSV) or os.path.exists(TRAIN_STATE)):
        return False
    st = train_load()
    return bool(train_entries() or st.get("groups") or st.get("run"))


def bars_of(e):
    try:
        b = json.loads(e.get("bars") or "{}")
        return b if isinstance(b, dict) else {}
    except ValueError:
        return {}


def live_values():
    """{flag: value} of the live bot (live.txt's head), or None when it cannot be read (the 'already live' drop is then skipped).
    FIXBATCH_LIVEVALS='F=V ...' (tests) replaces the read."""
    if os.environ.get("FIXBATCH_LIVEVALS") is not None:
        return flips_of(os.environ["FIXBATCH_LIVEVALS"])
    try:
        bot = open(LIVE).readline().split()[1]
        sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import fastship
        return fastship.values(bot)
    except Exception:  # noqa: BLE001
        return None


def train_pick(es, lv):
    """-> (take, defer, dropped) for a departing train: best point first; the same donors + flips twice once; flips that all equal live's values
    (live already carries them) dropped; a flag set to two values: the better entry rides, the other is deferred to the next train."""
    seen, take, defer, dropped, keys = {}, [], [], [], set()
    for e in sorted(es, key=point, reverse=True):
        f = flips_of(e.get("flips"))
        k = (e.get("donors"), " ".join(sorted((e.get("flips") or "").split())))
        if k in keys:
            dropped.append((e, "the same donors and flips as a better entry in this train"))
            continue
        if lv is not None and f and (e.get("donors") or "-") == "-" and all(lv.get(x) == v for x, v in f.items()):
            dropped.append((e, "its flips are live's values already (live carries it)"))
            continue
        if any(x in seen and seen[x] != v for x, v in f.items()):
            defer.append(e)
            continue
        keys.add(k)
        seen.update(f)
        take.append(e)
    return take, defer, dropped


def pilot_edit(fn):
    """fn(lines) -> lines on bq/pilot_top.txt (FILE.new.<pid>, then mv: pilotd reads it every scan)."""
    if DRY:
        return
    try:
        lines = open(PILOT_TOP).read().splitlines()
    except OSError:
        lines = []
    new = fn(list(lines))
    if new == lines:
        return
    tmp = f"{PILOT_TOP}.new.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write("".join(x + "\n" for x in new))
    os.replace(tmp, PILOT_TOP)


def pilot_clear(run):
    pat = run.get("pilot")
    if pat:
        pilot_edit(lambda ls: [x for x in ls if x.strip() != pat])
        log(f"TRAIN {run['slug']}: pilot priority line {pat!r} removed from {PILOT_TOP}")
        run["pilot"] = None


def pilot_track(run):
    """While the train's check runs: its newest chain bot's marker TAG -> '^cq-[a-z]+TAG-' in pilot_top.txt (its Condor batches jump the queue)."""
    bots = sorted((p for p in glob.glob(os.path.join(BOTS, f"nova_b*_{run['slug']}*")) if os.path.isdir(p)), key=os.path.getmtime)
    if not bots:
        return
    tag = marker(os.path.basename(bots[-1])).get("TAG", "")
    if not re.fullmatch(r"[A-Za-z0-9_]+", tag):
        return
    pat = f"^cq-[a-z]+{re.escape(tag)}-"
    if run.get("pilot") == pat:
        return
    old = run.get("pilot")
    pilot_edit(lambda ls: [x for x in ls if x.strip() != old] + ([pat] if pat not in [y.strip() for y in ls] else []))
    run["pilot"] = pat
    log(f"TRAIN {run['slug']}: pilot priority line {pat!r} in {PILOT_TOP}" + (f" (was {old!r})" if old else ""))


def train_subject(n, slugs):
    s, used = f"bundle(train): {n} ideas", 0
    for x in slugs:
        if len(s) - len("bundle(train): ") + len(x) + 1 > 52:
            break
        s += (" " if used == 0 else ",") + x
        used += 1
    return s + (f" +{len(slugs) - used}" if used < len(slugs) else "")


def bank_entry(e, why):
    """A train of ONE that failed: the failed-positive bank (flagscreen.py bank add), as shipcheck's auto_bank does for a missed positive."""
    lane = e.get("lane") or "fix"
    blane = {"rare": "fix", "bugbar": "fix"}.get(lane, lane)
    donor = next((d for d in (e.get("donors") or "-").split(",") if d and d != "-"), "-")
    ver = "?"
    try:
        ver = open(LIVE).readline().split()[0]
    except (OSError, IndexError):
        pass
    eid = re.sub(r"[^A-Za-z0-9_]", "", re.sub(r"^nova_b\d+_", "", e["bot"])) + "_t"
    cmd = [sys.executable, "-I", FLAGSCREEN_PY, "bank", "add", eid, "--donor", donor, "--flips", e.get("flips") or "", "--point",
           f"{max(0.0, point(e)):.4f}", "--base", ver, "--fail", "release train confirm", "--cause", "power" if blane == "fix" else "other",
           "--lane", blane, "--note", f"train: {why} (own PASS TAG {e['tag']}; {e.get('subject') or ''})"[:120]]
    if DRY:
        return log(f"TRAIN DRY: would bank {e['bot']}: {' '.join(cmd[3:])}")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300)
        out = (p.stdout + p.stderr).strip().replace("\n", " | ")[:200]
        rc = p.returncode
    except (OSError, subprocess.SubprocessError) as x:
        out, rc = f"{type(x).__name__}: {x}", 99
    log(f"TRAIN BANKED {e['bot']} (TAG {e['tag']}, lane {lane}, point {e.get('point')}): {why}: flagscreen rc {rc}: {out}")
    if rc:
        with open(PENDING, "a") as f:
            f.write(f"PENDING: {utc()} {e['bot']} ({lane}) PASSED (TAG {e['tag']}) but failed as a release train of one ({why}); the failed-positive "
                    f"bank add failed (rc {rc}): flagscreen.py bank add {eid} --donor {donor} --flips \"{e.get('flips')}\" --point {e.get('point')}\n")


def arm_single_lane(e, why):
    """train_ON gone: one waiting entry back on the queue on its own lane and bars, with a CONFIRM read from its own PASS (reread_requeue form)."""
    b, lane = bars_of(e), e.get("lane") or "fix"
    alane = "fix" if lane in ("fix", "bugbar", "rare") else "behaviour" if lane == "param" else lane
    fl, dn = e.get("flips") or "", e.get("donors") or "-"
    subj = e.get("subject") or f"{'fix' if alane == 'fix' else 'feat'}(trunk): {fl}"[:60]
    args = ["front", dn, fl, alane, subj, slug_of(e["bot"]) + "t"]
    args += ["--bugbar"] if str(e.get("bugbar")) == "1" and alane == "fix" else []
    args += ["--parambar"] if b.get("PARAMBAR") == "1" or lane == "param" else []
    args += ["--fuelx", e["fuelx"]] if e.get("fuelx") else []
    args += ["--rare", str(b["RARE"])] if b.get("RARE") and alane == "fix" else []
    args += ["--rare-fams", b["RAREFAMS"]] if b.get("RARE") and b.get("RAREFAMS") and alane == "fix" else []
    args += ["--shadow", b["SHADOW"]] if b.get("RARE") and b.get("SHADOW") and alane == "fix" else []
    args += ["--revises-live", b["REVISES"]] if b.get("REVISES") else []
    args += ["--base-has", b["BASEHAS"]] if b.get("BASEHAS") else []
    args += ["--class", b["CLASS"]] if b.get("CLASS") else []
    args += ["--confirm-from", e["tag"], "--confirm-n", "1"] if re.fullmatch(r"[A-Za-z0-9_]+", e.get("tag") or "") else []
    rc, out = armq(args)
    log(f"TRAIN single {e['bot']} (TAG {e['tag']}, lane {lane}, point {e.get('point')}): {why}: armq front rc {rc}: {out.splitlines()[-1][:200] if out else ''}")
    if rc and not DRY:
        with open(PENDING, "a") as f:
            f.write(f"PENDING: {utc()} {e['bot']} ({lane}) PASSED (TAG {e['tag']}), waited in the release train, could not be re-armed when train_ON "
                    f"went (armq rc {rc}); re-arm: armq.py add {dn} \"{fl}\" {alane} \"{subj}\" --front\n")


def train_split(st, es, why):
    """A train that did not ship: halves (best point first, alternating) queue as the next trains; a train of one goes to the bank. -> None"""
    if not train_on():
        log(f"TRAIN {why}: train_ON is gone: its {len(es)} entries re-armed singly")
        for e in sorted(es, key=point):
            arm_single_lane(e, f"train did not ship and train_ON is gone ({why[:100]})")
        return
    if len(es) == 1:
        log(f"TRAIN {why}: a train of one: {es[0]['bot']} dropped to the failed-positive bank")
        bank_entry(es[0], why[:100])
        return
    h1, h2 = split_halves(sorted(es, key=point, reverse=True))
    st["groups"] = (st.get("groups") or []) + [h1, h2]
    log(f"TRAIN {why}: split into halves for the next trains: [{', '.join(e['bot'] for e in h1)}] then [{', '.join(e['bot'] for e in h2)}]; "
        f"{len(st['groups'])} halves wait")


def train_depart(st, es, why, from_list):
    """ONE train of es on live (armq add ... --confirm-from best TAG). from_list: the entries come from train.tsv (removed now); else a half."""
    take, defer, dropped = train_pick(es, live_values())
    log(f"TRAIN DEPART ({why}): {len(es)} entries: {', '.join(e['bot'] + ' ' + (e.get('lane') or '?') + ' ' + (e.get('point') or '?') for e in sorted(es, key=point, reverse=True))}")
    for e, w in dropped:
        log(f"TRAIN drop {e['bot']} (TAG {e['tag']}): {w}")
    if from_list:
        train_remove([e for e in es if e not in defer])
    elif defer and not DRY:  # a half cannot clash (its train had none), but if one does it waits in the list for the next train
        for e in defer:
            train_add(e)
    for e in defer:
        log(f"TRAIN defer {e['bot']} (TAG {e['tag']}, point {e.get('point')}): its flips give a flag another value than a better entry; next train")
    st["last_dep"] = time.time()
    if not take:
        return train_save(st)
    st["n"] = int(st.get("n") or 0) + 1
    slug = f"rtr{st['n']}z"
    donors = []
    for e in take:
        for d in (e.get("donors") or "-").split(","):
            if d and d != "-" and d not in donors:
                donors.append(d)
    seen = {}
    for e in take:
        seen.update(flips_of(e.get("flips")))
    fl = " ".join(f"{k}={v}" for k, v in seen.items())
    best = next((e["tag"] for e in take if re.fullmatch(r"[A-Za-z0-9_]+", e.get("tag") or "")), None)
    fx = [float(e["fuelx"]) for e in take if re.fullmatch(r"\d+(\.\d+)?", e.get("fuelx") or "")]
    args = ["add", ",".join(donors) or "-", fl, "fix", train_subject(len(take), [slug_of(e["bot"]) for e in take]), slug, "--bugbar", "--front"]
    args += ["--confirm-from", best, "--confirm-n", "1"] if best else []
    args += ["--fuelx", f"{max(fx):g}"] if fx else []
    st["run"] = dict(slug=slug, entries=take, t=time.time(), args=args, pilot=None)
    train_save(st)  # before the add: a crash after it leaves a tracked run, never an untracked second train
    rc, out = armq(args)
    log(f"TRAIN {slug}: {len(take)} entries [{', '.join(e['bot'] for e in take)}] armq add rc {rc}: {' | '.join(out.splitlines()[-4:])[:600]}")
    if rc:
        run, st["run"] = st["run"], None
        train_split(st, run["entries"], f"{slug} not queued (armq preflight: a conflict or a refused flip)")
        train_save(st)


def train_resolve(st):
    run = st["run"]
    state, detail, fp = chain_state(run)
    if state == "shipped":
        log(f"TRAIN {run['slug']} SHIPPED as {detail}: {', '.join(e['bot'] for e in run['entries'])}")
        pilot_clear(run)
        st["run"] = None
        st["last_end"] = time.time()
        return train_save(st)
    if state == "wait":
        run.pop("settled", None)
        pilot_track(run)
        if time.time() - run["t"] > 12 * 3600 and not run.get("alarm"):
            run["alarm"] = True
            log(f"TRAIN ALARM {run['slug']} still not settled after 12 h ({detail}): left to the Builder")
        return train_save(st)
    grace = setting("FIXBATCH_GRACE_MIN", 10.0) * 60
    if run.get("settled", {}).get("fp") != json.dumps(fp):
        run["settled"] = dict(fp=json.dumps(fp), t=time.time())
        return train_save(st)
    if time.time() - run["settled"]["t"] < grace:
        return None
    pilot_clear(run)
    st["run"] = None
    st["last_end"] = time.time()
    train_split(st, run["entries"], f"{run['slug']} ended without shipping ({detail[:160]})")
    train_save(st)


def train_tick(fbst):
    """One train pass. fbst: fixbatch's own state (an old bundle still running holds the departure)."""
    st = train_load()
    if st.get("run"):
        train_resolve(st)
        st = train_load() if not DRY else st
    if not train_on():  # train_ON gone: whatever waits is re-armed singly (a running train finishes first)
        if st.get("run"):
            return
        es = train_entries() + [e for g in st.get("groups") or [] for e in g]
        if es:
            log(f"TRAIN {TRAIN_ON} gone: {len(es)} waiting entries re-armed singly on their own lanes")
            train_remove(train_entries())
            st["groups"] = []
            train_save(st)
            for e in sorted(es, key=point):
                arm_single_lane(e, "release train switched off")
        return
    old = [dict(e, bars=json.dumps({"BUGBAR": "1"} if str(e.get("bugbar")) == "1" else {}), lane=e.get("lane") or "fix")
           for e in entries()]  # fix PASSes batched before train_ON (or by a shipcheck that started before it): they ride the train
    for e in old:
        if not DRY:
            train_add(e)
        log(f"TRAIN adopt {e['bot']} (TAG {e['tag']}) from {TSV}")
    if old and not DRY:
        remove_entries(old)
    if st.get("run"):
        return
    if fbst.get("run"):
        return  # an old fixbatch bundle is still on its way: one merge onto live at a time
    every = setting("FIXBATCH_TRAIN_MIN", 20.0) * 60
    wait = float(st.get("last_dep") or 0) + every - time.time()
    if wait > 0:
        return
    if st.get("groups"):
        g = st["groups"].pop(0)
        return train_depart(st, g, f"pending half 1 of {len(st['groups']) + 1}", from_list=False)
    es = train_entries() + (old if DRY else [])
    if es:
        return train_depart(st, es, f"{len(es)} waiting, every {every / 60:g} min", from_list=True)


def train_status():
    st, es = train_load(), train_entries()
    every = setting("FIXBATCH_TRAIN_MIN", 20.0)
    print(f"release train: {'ON (' + TRAIN_ON + ')' if train_on() else 'off (touch ' + TRAIN_ON + ')'}; every {every:g} min; {len(es)} waiting; "
          f"{len(st.get('groups') or [])} pending halves; trains so far {st.get('n', 0)}")
    for e in sorted(es, key=point, reverse=True):
        print(f"  {e['t']} {e['bot']} TAG {e['tag']} lane {e.get('lane')}{' bugbar' if str(e.get('bugbar')) == '1' else ''} point {e['point']} "
              f"donors {e['donors']} flips {e['flips']!r} ({age(e):.0f} min)")
    for i, g in enumerate(st.get("groups") or [], 1):
        print(f"  half {i}: {', '.join(e['bot'] + ' ' + str(e.get('point')) for e in g)}")
    r = st.get("run")
    if r:
        print(f"running train {r['slug']} since {utc(r['t'])}: {', '.join(e['bot'] for e in r['entries'])}; {chain_state(r)[:2]}; pilot line {r.get('pilot')!r}")
    else:
        nxt = float(st.get("last_dep") or 0) + every * 60
        held = " (held: an old fixbatch bundle is running)" if load_state().get("run") else ""
        what = "a pending half" if st.get("groups") else f"{len(es)} waiting" if es else "nothing (list empty)"
        print(f"next departure: {'now' if nxt <= time.time() else utc(nxt)} with {what}{held}")


# ---------------------------------------------------------------------------------------------------------------------------------------------
# PRE-TEST BUNDLING (FIXPRE; Tool Builder 10 Nov, owner ~21:30Z: "batch bug fixes so you have more space for behavioural changes"). OFF unless
# bq/fixbundle_ON exists; absent (and no fixpre_state.json left from a run), nothing below runs past two existence checks: every decision above
# is the old one.
#   On: when no pre-test bundle runs and >= FIXPRE_N_MIN (3) plain fix lines wait in armq.txt (lane fix, with or without --bugbar; not --rare,
#     --shadow, --base-has, --revises-live, --parambar, not a CONFIRM re-read (confirm_from), not a bundle (subject 'bundle(' or slug fxb/fxp/rtr),
#     with a slug, not being armed now (an 'arming: ... --name SLUG' line in armq.log in the last 20 min), not the line being merged, not
#     tombstoned in armq.dropped.jsonl, not a member this file put back alone in the last 24 h): up to FIXPRE_MAX (8) of them, best evidence
#     first (tools/lab/evid.py z; no z: after every z, oldest first), are taken out of armq.txt (armq's own lock, plus a tombstone so an arm
#     that started meanwhile is withdrawn) and queued as ONE line, fixbatch's bundle form:
#       armq.py add DONORS FLIPS fix "bundle(fixpre): N fixes ..." fxp<n>z --bugbar --front [--fuelx MAX] [--score MAX_Z]
#     It is read once on the fix lane under the bug bar (a full read; the bars are shipcheck's, unchanged); shipcheck submits its PASS at once
#     ('(fixpre)' in SUBJECT: never batched again, like '(fixbatch)').
#   A flag two members set to different values: the better member rides; the other is held (out of armq, in fixpre_state 'held') and goes first
#     in the next bundle; held lines go back to armq as their own lines when no next bundle forms (fewer than N_MIN waiting).
#   armq add refused (preflight): a member the refusal names (its donor after 'refused:', or a flag of its in a flip refusal) goes back to armq
#     alone; the rest are re-queued at once as a new bundle (2+) or alone (1). A refusal naming nobody, an arm failure, FAIL or INCONCLUSIVE twice
#     (the chain fxp<n>z* ends unshipped; settled for FIXBATCH_GRACE_MIN): halves (split_halves, the train's 1st,3rd,..|2nd,4th,.. split, in
#     evidence order) queue as the next bundles; a half of one goes back to armq alone (its own single read, the normal path, never re-bundled).
#   fixbundle_ON removed: a running bundle finishes; held lines and pending halves go back to armq as single lines; a run that then ends
#     unshipped puts its members back singly.
# Files: bq/fixbundle_ON (switch), bq/fixpre_state.json (n, run, groups, held, solo); every decision in bq/fixbatch.log as 'FIXPRE ...'.
# Settings: FIXPRE_N_MIN (3), FIXPRE_MAX (8), FIXBATCH_GRACE_MIN. Tests: FIXBATCH_EVID (an evidence.tsv copy).
FIXPRE_ON = os.path.join(Q, "fixbundle_ON")
FIXPRE_STATE = os.path.join(Q, "fixpre_state.json")
ARMQ_LOG = os.path.join(Q, "armq.log")
ARMQ_DROPPED = os.path.join(Q, "armq.dropped.jsonl")
ARMQ_MERGING = os.path.join(Q, "armq.merging")
FIXPRE_SKIP = ("rare", "rarefams", "shadow", "basehas", "revises", "parambar", "seqspar", "confirm_from", "cls", "nobundle")  # nobundle: armq add --no-bundle (11 Nov)  # cls: a class read (armq --class)


def split_halves(es):
    """An ordered list -> its two halves, alternating (1st,3rd,5th.. | 2nd,4th,..): the release train's split, shared with FIXPRE."""
    return es[0::2], es[1::2]


def fixpre_on():
    return os.path.exists(FIXPRE_ON)


def fp_log(s):
    log("FIXPRE " + s)


def fp_load():
    try:
        st = json.load(open(FIXPRE_STATE))
    except (OSError, ValueError):
        st = {}
    for k, v in (("n", 0), ("run", None), ("groups", []), ("held", []), ("solo", {}), ("out", {})):
        st.setdefault(k, v)
    return st


def fp_save(st):
    if DRY:
        return
    with open(FIXPRE_STATE + ".new", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(FIXPRE_STATE + ".new", FIXPRE_STATE)


def fixpre_pending():
    """Anything FIXPRE holds (a run, halves, held lines): True with fixbundle_ON gone too, so it is finished or put back, never lost."""
    if not os.path.exists(FIXPRE_STATE):
        return False
    st = fp_load()
    return bool(st["run"] or st["groups"] or st["held"])


def fp_evid():
    try:
        if os.path.join(REPO, "tools/lab") not in sys.path:
            sys.path.insert(0, os.path.join(REPO, "tools/lab"))
        import evid
        if os.environ.get("FIXBATCH_EVID"):
            evid.F = os.environ["FIXBATCH_EVID"]
        d = evid.load()
        return lambda slug: evid.get(slug, d)
    except Exception:  # noqa: BLE001  no evidence: oldest first
        return lambda slug: None


def fp_arming(mins=20):
    """{slug: epoch} of armq.py's arms started in the last mins (its 'arming: ... --name SLUG' log line): such a line is in flight, never taken."""
    import calendar
    out, cut = {}, time.time() - mins * 60
    try:
        with open(ARMQ_LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400000))
            tail = f.read().decode(errors="replace").splitlines()
    except OSError:
        return out
    for ln in tail:
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) arming: .* --name (\S+)", ln)
        if m:
            try:
                t = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ"))
                if t >= cut:
                    out[m.group(2)] = max(t, out.get(m.group(2), 0))
            except ValueError:
                pass
    return out


def fp_tombstoned(slug, hours=24):
    last = None
    try:
        for ln in open(ARMQ_DROPPED):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("slug") == slug:
                last = d
    except OSError:
        pass
    return bool(last) and not last.get("revive") and time.time() - float(last.get("t") or 0) < hours * 3600


def fp_armq_rows():
    out = []
    try:
        for ln in open(ARMQ_FILE):
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


NOBUNDLE_FILE = os.path.join(Q, "nobundle_slugs.txt")  # written by armq add --no-bundle


def nobundle_root(slug):
    try:
        import rarebank
        roots = {rarebank.slug_root(x.strip()) for x in open(NOBUNDLE_FILE) if x.strip()}
        return rarebank.slug_root(slug) in roots
    except (OSError, ImportError):
        return False


def fp_eligible(q, st, arming, merging):
    """-> None when q may ride a pre-test bundle, else the reason it may not."""
    slug = q.get("slug") or ""
    if q.get("lane") != "fix" or q.get("flips") is None:
        return "not a fix line"
    for k in FIXPRE_SKIP:
        if q.get(k):
            return f"has {k}"
    if not slug:
        return "no slug"
    if nobundle_root(slug):  # 11 Nov: --no-bundle survives shipwatch/armq re-queues (aws1b3 -> aws1b3s) by slug root
        return "no-bundle line"
    if str(q.get("subject") or "").startswith("bundle(") or re.match(r"(fxb|fxp|rtr)\d", slug):
        return "a bundle"
    if slug in arming:
        return "being armed"
    if merging and (slug in merging):
        return "being merged"
    if slug in st["solo"]:
        return "put back alone by FIXPRE"
    if fp_tombstoned(slug):
        return "tombstoned"
    return None


def fp_order(qs):
    z = fp_evid()
    return sorted(qs, key=lambda q: (z(q["slug"]) is None, -(z(q["slug"]) or 0.0), float(q.get("t") or 0)))


def fp_pick(qs):
    """qs in evidence order -> (take, held, dups): up to FIXPRE_MAX with no flag set two ways; a clash is held; the same fix twice: once."""
    mx = int(setting("FIXPRE_MAX", 8.0))
    seen, keys, take, held, dups = {}, set(), [], [], []
    for q in qs:
        k = (q.get("donors"), " ".join(sorted((q.get("flips") or "").split())))
        if k in keys:
            dups.append(q)
            continue
        f = flips_of(q.get("flips"))
        if any(x in seen and seen[x] != v for x, v in f.items()):
            held.append(q)
            continue
        if len(take) >= mx:
            continue
        keys.add(k)
        seen.update(f)
        take.append(q)
    return take, held, dups


def fp_edit_armq(fn):
    """fn(lines) -> new lines, under armq.py's own lock (armq.txt.lock), as armq.edit does."""
    with open(ARMQ_FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        lines = open(ARMQ_FILE).read().splitlines() if os.path.exists(ARMQ_FILE) else []
        new = fn(lines)
        with open(ARMQ_FILE + ".new", "w") as f:
            f.write("".join(x + "\n" for x in new))
        os.replace(ARMQ_FILE + ".new", ARMQ_FILE)


def fp_key(q):
    return (q.get("slug"), q.get("t"))


def fp_take_out(qs, slug):
    """Remove qs from armq.txt (and tombstone their slugs, so an arm that started meanwhile is withdrawn) -> the ones really removed."""
    if DRY:
        fp_log(f"DRY: would take {', '.join(q['slug'] for q in qs)} out of {ARMQ_FILE} for {slug}")
        return list(qs)
    want, got = {fp_key(q) for q in qs}, []

    def rm(lines):
        keep = []
        for x in lines:
            try:
                q = json.loads(x)
            except ValueError:
                keep.append(x)
                continue
            if fp_key(q) in want and fp_key(q) not in {fp_key(g) for g in got}:
                got.append(q)
            else:
                keep.append(x)
        return keep
    fp_edit_armq(rm)
    with open(ARMQ_DROPPED, "a") as f:
        for q in got:
            f.write(json.dumps(dict(slug=q["slug"], t=time.time(), by=f"fixpre {slug}")) + "\n")
    return got


def fp_note_out(st, qs):
    """The take-out time of each member (a put-back skips a member armq began arming at or after it)."""
    for q in qs:
        st["out"][q["slug"]] = time.time()


def fp_put_back(qs, why, st, solo=False):
    """Members back on armq.txt as their own lines (front; the row as it was queued, no new preflight); solo: never bundled again (24 h)."""
    if not qs:
        return
    arming = fp_arming(24 * 60)
    back = []
    for q in qs:
        if arming.get(q["slug"], 0) >= float(st["out"].get(q["slug"]) or 9e18) - 5:  # an arm started at the take-out or after: its single path
            fp_log(f"{q['slug']}: not put back ({why}): armq started arming it meanwhile")
            continue
        back.append(q)
        if solo:
            st["solo"][q["slug"]] = time.time()
    if DRY:
        fp_log(f"DRY: would put back {', '.join(q['slug'] for q in back)} on {ARMQ_FILE}{' alone' if solo else ''}: {why}")
        return
    have = set()

    def add(lines):
        for x in lines:
            try:
                have.add(json.loads(x).get("slug"))
            except ValueError:
                pass
        return [json.dumps(q) for q in back if q["slug"] not in have] + lines
    fp_edit_armq(add)
    with open(ARMQ_DROPPED, "a") as f:  # clears fp_take_out's tombstone, as armq add of the same slug does
        for q in back:
            f.write(json.dumps(dict(slug=q["slug"], t=time.time(), revive=True, by="fixpre")) + "\n")
    for q in back:
        fp_log(f"{q['slug']}: back on armq as its own line{' (alone: its own read, never re-bundled)' if solo else ''}"
               f"{' (already queued: skipped)' if q['slug'] in have else ''}: {why}")


def fp_subject(slugs):
    return subject(slugs).replace("bundle(fixbatch)", "bundle(fixpre)", 1)


def fp_blame(members, out):
    """Members a preflight refusal names: a donor right after 'refused: ', or one of the member's flags in a flip refusal."""
    txt = out[out.find("refused:"):] if "refused:" in out else ""
    if not txt:
        return []
    bad = []
    for q in members:
        dn = [d for d in (q.get("donors") or "-").split(",") if d and d != "-"]
        if any(f"refused: {d} " in txt or f"refused: {d}:" in txt for d in dn):
            bad.append(q)
        elif "flip.sh would refuse" in txt and any(re.search(r"\b" + re.escape(k) + r"\b", txt) for k in flips_of(q.get("flips"))):
            bad.append(q)
    return bad


def fp_split(st, members, why):
    if len(members) == 1:
        return fp_put_back(members, why, st, solo=True)
    h1, h2 = split_halves(members)
    for h in (h1, h2):
        if len(h) == 1:
            fp_put_back(h, f"{why}: a half of one", st, solo=True)
        else:
            st["groups"].append(h)
    fp_log(f"{why}: split [{', '.join(q['slug'] for q in h1)}] | [{', '.join(q['slug'] for q in h2)}]; {len(st['groups'])} halves wait")


def fp_bundle(st, members, why):
    """ONE armq line of members (already out of armq.txt). A refusal: blamed members back alone, the rest again at once; nobody blamed: halves."""
    st["n"] = int(st.get("n") or 0) + 1
    slug = f"fxp{st['n']}z"
    donors, seen = [], {}
    for q in members:
        for d in (q.get("donors") or "-").split(","):
            if d and d != "-" and d not in donors:
                donors.append(d)
        seen.update(flips_of(q.get("flips")))
    fl = " ".join(f"{k}={v}" for k, v in seen.items())
    fx = [float(q["fuelx"]) for q in members if re.fullmatch(r"\d+(\.\d+)?", str(q.get("fuelx") or ""))]
    z = fp_evid()
    zs = [z(q["slug"]) for q in members if z(q["slug"]) is not None]
    args = ["add", ",".join(donors) or "-", fl, "fix", fp_subject([q["slug"] for q in members]), slug, "--bugbar", "--front"]
    args += ["--fuelx", f"{max(fx):g}"] if fx else []
    args += ["--score", f"{max(zs):.3f}"] if zs else []
    st["run"] = dict(slug=slug, members=members, t=time.time(), args=args, why=why)
    fp_save(st)  # before the add: a crash after it leaves a tracked run (never armed -> halves), never lost members
    rc, out = armq(args)
    fp_log(f"bundle {slug} ({why}): {len(members)} fixes [{', '.join(q['slug'] + ' ' + (q.get('flips') or '') for q in members)}]: armq add rc {rc}: "
           f"{' | '.join((out or '').splitlines()[-4:])[:600]}")
    if not rc:
        return fp_save(st)
    st["run"] = None
    bad = fp_blame(members, out or "")
    rest = [q for q in members if q not in bad]
    if bad and rest:
        fp_put_back(bad, f"bundle {slug} refused by armq preflight, naming it", st, solo=True)
        if len(rest) == 1:
            fp_put_back(rest, f"bundle {slug} refused for another member: the only one left", st, solo=True)
            return fp_save(st)
        return fp_bundle(st, rest, f"{slug} refused for {', '.join(q['slug'] for q in bad)}: the rest")
    fp_split(st, members, f"bundle {slug} not queued (armq preflight refused, no member named)")
    fp_save(st)


def fp_resolve(st):
    run = st["run"]
    state, detail, fp = chain_state(run)
    if state == "shipped":
        fp_log(f"bundle {run['slug']} SHIPPED as {detail}: {', '.join(q['slug'] for q in run['members'])}")
        st["run"] = None
        return fp_save(st)
    if state == "wait":
        run.pop("settled", None)
        if time.time() - run["t"] > 12 * 3600 and not run.get("alarm"):
            run["alarm"] = True
            fp_log(f"ALARM bundle {run['slug']} still not settled after 12 h ({detail}): left to the Builder")
        return fp_save(st)
    grace = setting("FIXBATCH_GRACE_MIN", 10.0) * 60
    if run.get("settled", {}).get("fp") != json.dumps(fp):
        run["settled"] = dict(fp=json.dumps(fp), t=time.time())
        return fp_save(st)
    if time.time() - run["settled"]["t"] < grace:
        return None
    # 12 Nov (Builder: fxp7zs PASSED but was HELD by hand (its pre-stated rule needed fxp6's near-miss read too, which failed); FIXPRE took
    # 'ended without shipping' as a miss and re-armed tmr7s + shd1s singly, a third chance): a bundle whose chain ended PASS (only a hold stops
    # a PASS from shipping) or whose slug is on bq/hold_submit.txt is a hand decision: its members are NOT re-armed; the Builder decides
    held = "ended: PASS" in detail
    try:
        held = held or any(ln.split("#", 1)[0].strip() and ln.split("#", 1)[0].strip() in run["slug"]
                           for ln in open("/data/USER/st/bq/hold_submit.txt"))
    except OSError:
        pass
    if held:
        st["run"] = None
        fp_log(f"bundle {run['slug']} PASSED but was held by hand ({detail[:160]}): members NOT re-armed ({', '.join(q['slug'] for q in run['members'])}); the Builder decides")
        return fp_save(st)
    st["run"] = None
    why = f"bundle {run['slug']} ended without shipping ({detail[:160]})"
    if fixpre_on():
        fp_split(st, run["members"], why)
    else:
        fp_put_back(run["members"], why + f"; {FIXPRE_ON} is gone", st)
    fp_save(st)


def fixpre_tick():
    st = fp_load()
    now = time.time()
    st["solo"] = {k: v for k, v in st["solo"].items() if now - float(v) < 24 * 3600}
    live_slugs = {q["slug"] for q in ([q for q in (st["run"] or {}).get("members") or []] + [q for g in st["groups"] for q in g] + st["held"])}
    st["out"] = {k: v for k, v in st["out"].items() if k in live_slugs}
    if st["run"]:
        fp_resolve(st)
    if not fixpre_on():  # switched off: a running bundle finishes; whatever else waits goes back on armq
        if st["groups"] or st["held"]:
            fp_log(f"{FIXPRE_ON} gone: {sum(len(g) for g in st['groups']) + len(st['held'])} held/half members back on armq as their own lines")
            fp_put_back([q for g in st["groups"] for q in g] + st["held"], "pre-test bundling switched off", st)
            st["groups"], st["held"] = [], []
        return fp_save(st)
    if st["run"]:
        return fp_save(st)
    if st["groups"]:
        g = st["groups"].pop(0)
        if len(g) == 1:
            fp_put_back(g, "a half of one", st, solo=True)
            return fp_save(st)
        return fp_bundle(st, g, f"pending half 1 of {len(st['groups']) + 1}")
    arming = fp_arming()
    merging = open(ARMQ_MERGING).read() if os.path.exists(ARMQ_MERGING) else ""
    rows, skip = fp_armq_rows(), {}
    ok = []
    for q in rows:
        why = fp_eligible(q, st, arming, merging)
        if why is None:
            ok.append(q)
        elif q.get("lane") == "fix" and q.get("flips") is not None:
            skip[q.get("slug") or q.get("flips")] = why
    held = st["held"]
    n_min = setting("FIXPRE_N_MIN", 3.0)
    if len(ok) + len(held) < n_min:
        if held:
            fp_put_back(held, f"no next bundle: {len(ok) + len(held)} fix lines wait (< {n_min:g})", st)
            st["held"] = []
            fp_save(st)
        return None
    order = held + fp_order(ok)  # held lines first: they waited for this bundle
    take, defer, dups = fp_pick(order)
    fp_log(f"{len(ok)} fix lines wait in armq (+{len(held)} held): "
           f"{', '.join(q['slug'] + ' z ' + str(fp_evid()(q['slug'])) for q in order)}"
           + (f"; not taken: {', '.join(f'{k} ({v})' for k, v in skip.items())}" if skip else ""))
    for q in dups:
        fp_log(f"{q['slug']}: the same donors and flips as a line taken: left on armq")
    if len(take) < 2:
        fp_log(f"only {len(take)} line(s) without a flag clash: no bundle; lines left as they are")
        if held:
            fp_put_back(held, "no bundle formed", st)
            st["held"] = []
        return fp_save(st)
    slug_next = f"fxp{int(st.get('n') or 0) + 1}z"
    newly_held = [q for q in defer if q not in held]
    got = fp_take_out([q for q in take + newly_held if q not in held], slug_next)
    fp_note_out(st, got)
    gk = {fp_key(q) for q in got} | {fp_key(q) for q in held}
    lost = [q for q in take + newly_held if fp_key(q) not in gk]
    for q in lost:
        fp_log(f"{q['slug']}: left armq before the take-out (armed meanwhile): not in the bundle")
    take = [q for q in take if fp_key(q) in gk]
    st["held"] = [q for q in defer if fp_key(q) in gk]
    for q in st["held"]:
        fp_log(f"{q['slug']} [{q.get('flips')}]: a flag another member sets otherwise: held for the next bundle")
    if len(take) < 2:
        fp_put_back(take + st["held"], "fewer than 2 members left after the take-out", st)
        st["held"] = []
        return fp_save(st)
    return fp_bundle(st, take, f"{len(ok) + len(held)} fix lines waited")


def fixpre_status():
    st = fp_load()
    print(f"pre-test bundling (FIXPRE): {'ON (' + FIXPRE_ON + ')' if fixpre_on() else 'off (touch ' + FIXPRE_ON + ')'}; bundles so far {st['n']}; "
          f"{len(st['groups'])} halves; {len(st['held'])} held; {len(st['solo'])} put back alone (24 h)")
    r = st["run"]
    if r:
        print(f"  running {r['slug']} since {utc(r['t'])}: {', '.join(q['slug'] for q in r['members'])}; {chain_state(r)[:2]}")
    for i, g in enumerate(st["groups"], 1):
        print(f"  half {i}: {', '.join(q['slug'] for q in g)}")


def tick():
    with locked(os.path.join(Q, "fixbatch.tick.lock"), block=False) as ok:
        if not ok:
            return
        if not DRY:  # heartbeat: the time of the last pass (shipwatch spawns one every 60 s)
            with open(os.path.join(Q, "fixbatch.beat"), "w") as f:
                f.write(utc() + "\n")
        st = load_state()
        if st.get("run"):
            resolve(st)
            st = load_state() if not DRY else st
        if fixpre_on() or fixpre_pending():  # pre-test bundling (bq/fixbundle_ON; absent: not run)
            try:
                fixpre_tick()
            except Exception as e:  # noqa: BLE001  a FIXPRE bug never stops the rest of the pass
                log(f"FIXPRE !! {type(e).__name__}: {e}")
        if train_on() or train_pending():  # release train: on, it owns every waiting PASS; just switched off, it re-arms what it held
            train_tick(st)
            if train_on():
                return
        es = entries()
        if os.path.exists(OFF):
            if es and not st.get("run"):
                log(f"{OFF} present: {len(es)} waiting fixes re-armed singly")
                if not DRY:
                    remove_entries(es)
                singles(es, "fix batching switched off")
            return
        fb = [e for e in es if is_fallback_single(e["bot"])]  # a fallback single that was batched anyway (before shipcheck knew): out now, alone
        if fb:
            if not DRY:
                remove_entries(fb)
            singles(fb, "fallback single PASSED on live: re-armed alone so its confirm PASS submits (no bundle again)")
            es = [e for e in es if e not in fb]
        go, why = decide(es, st)
        if go:
            release(es, st, why)


def status():
    st, es = load_state(), entries()
    print(f"fixbatch: {'OFF (' + OFF + ')' if os.path.exists(OFF) else 'on'}; {len(es)} waiting")
    for e in es:
        print(f"  {e['t']} {e['bot']} TAG {e['tag']} point {e['point']} bugbar {e['bugbar']} donors {e['donors']} flips {e['flips']!r} ({age(e):.0f} min)")
    if st.get("run"):
        r = st["run"]
        print(f"running bundle {r['slug']} since {utc(r['t'])}: {', '.join(e['bot'] for e in r['entries'])}; {chain_state(r)[:2]}")
    print("release now: %s (%s)" % decide(es, st))
    if train_on() or train_pending():
        train_status()
    if fixpre_on() or fixpre_pending():
        fixpre_status()


def main():
    a = sys.argv[1:]
    if a[:1] == ["--tick"]:
        return tick()
    if a[:1] == ["--loop"]:
        log(f"fixbatch loop up (pid {os.getpid()})")
        while True:
            try:
                tick()
            except Exception as e:  # noqa: BLE001  one bad pass never stops the loop
                log(f"!! tick: {type(e).__name__}: {e}")
            time.sleep(60)
    if a[:1] == ["--drop"] and len(a) >= 2:  # 10 Nov (Builder: rcea, a behaviour change under a bug-bar label): take waiting entries out by bot name
        gone = [e for e in entries() if e["bot"] in a[1:]]
        remove_entries(gone)
        if os.path.exists(TRAIN_TSV) or os.path.exists(TRAIN_STATE):  # release train: its list and pending halves too
            tg = [e for e in train_entries() if e["bot"] in a[1:]]
            train_remove(tg)
            tst = train_load()
            hg = [e for g in tst.get("groups") or [] for e in g if e["bot"] in a[1:]]
            if hg and not DRY:
                tst["groups"] = [x for x in ([e for e in g if e["bot"] not in a[1:]] for g in tst["groups"]) if x]
                train_save(tst)
            gone += tg + hg
        log(f"DROPPED {', '.join(e['bot'] + ' TAG ' + e['tag'] for e in gone) or 'nothing'} (fixbatch.py --drop {' '.join(a[1:])})")
        print(f"dropped {len(gone)} of the waiting entries")
        return 0
    if a[:1] == ["--status"] or not a:
        return status()
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
