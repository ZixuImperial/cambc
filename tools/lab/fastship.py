#!/usr/bin/env python3
"""fastship: donor(s) and flips to a bundle ready to arm, in one command. Tool builder, 2 Nov (owner: speed up iteration).

usage: python3 -I tools/lab/fastship.py DONOR:BASE[,DONOR2:BASE2] "FLAG=V ..." LANE [--subject S] [--name SLUG] [--trunk T]
                                        [--set "FLAG=V ..."] [--live BOT] [--carry-pending] [--stack-on A] [--plan] [--arm]
  DONOR:BASE  as for trunkmerge; "-" flips the current trunk with no merge. LANE: fix | behaviour.
  "FLAG=V ..." may be "": ship the trunk's own code (say fuel work) as it is: flip.sh then sets a flag to its trunk value, 0 data bytes.
Runs the existing tools in order and stops at the first failure; every check stays theirs:
  1. trunkmerge.py DONORS TRUNK NEWTRUNK --set ...  (merge, mergecheck, build, identity vs live, registry line)
  2. flip.sh NEWTRUNK BUNDLE "FLIPS"    (code IDENTICAL; FASTSHIP_BUILD=1 also compiles it and checks compiled wasm == predicted: 294 s at a busy hour, and it never differed; the games build from source anyway)
  3. mkmarker.py BUNDLE ... --dry                    (validates the marker)
  4. only with --arm: mkmarker.py BUNDLE ...         (writes SHIPCHECK; shipwatch then gates it and auto-submits on PASS)
After a merge made a new trunk, trunkset.py builds its shared measurement set in the background; that never affects the bundle.
TRUNK is the last nova_trunk* line of trunk_registry.md unless --trunk; NEWTRUNK its next name; BUNDLE nova_b<next number>_<slug>.
A bundle cannot revert a flip:
  - a flag whose live value differs from the trunk's is carried into FLIPS and LIVEVALS;
  - asking for another value of a flag live has flipped is refused;
  - --arm is refused while another bundle's shipcheck runs, unless --carry-pending adds that bundle's flips: if it ships first,
    this one needs them, and if it fails, this one carries them, so read the result before relying on it.
--set: extra trunk values for trunkmerge. Each flag in "FLAG=V ..." that the trunk lacks is set to 0 in the trunk automatically.
--plan prints the commands and stops: nothing is built or written."""
import argparse
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
LAB = REPO + "/tools/lab"
sys.path.insert(0, LAB)
import shipstack  # noqa: E402
BQ = os.environ.get("SHIPWATCH_Q", "/data/USER/st/bq")
REGISTRY = "/homes/USER/condor-work/reports/trunk_registry.md"
LIVE = "/data/USER/st/bq/live.txt"
STATE = "/data/USER/st/bq/shipwatch_state.json"
OLD = "/data/USER/st/new/bots"


def shipstack_bigset():
    import ladderw
    return ladderw.default_bigset()


def die(msg):
    print(f"fastship: {msg}", file=sys.stderr)
    sys.exit(1)


class FastshipError(RuntimeError):
    """A failure library callers (armq's daemon) handle per iteration; the command line turns it into die()."""


def values(bot):
    """{flag: value} of a bot's runtime tables, from flip.py list. Retries for ~1 min: a bot that just shipped is
    copied into a real folder (shipwatch REAL=1) and its files can be missing for a moment (armq died on that,
    4 Nov 14:50Z, v495 nova_b1365_crd3)."""
    for k in range(7):
        r = subprocess.run([sys.executable, "-I", LAB + "/flip.py", "list", f"{REPO}/bots/{bot}/src"], capture_output=True, text=True)
        if not r.returncode:
            break
        time.sleep(10)
    else:
        raise FastshipError(f"flip.py list {bot}: {(r.stdout + r.stderr).strip()[-200:]}")
    return {k: v for ln in r.stdout.splitlines() for k, v in re.findall(r"\b([A-Z][A-Z0-9_]*)=(-?\d+)", ln)}


def parse_flips(s):
    out = {}
    for x in s.split():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*=-?\d+", x):
            die(f"bad flag {x!r}: use FLAG=INT")
        k, v = x.split("=")
        out[k] = v
    return out


def current_trunk():
    names = re.findall(r"^- (nova_trunk[0-9]+[a-z])\b", open(REGISTRY, errors="ignore").read(), re.M)
    if not names:
        die("no nova_trunk line in trunk_registry.md: give --trunk")
    if os.path.isdir(os.path.join("/homes/USER/cambc/bots", names[-1], "src")):
        return names[-1]
    # 8 Nov (Builder): the registry's last trunk is gone from bots/ since the purge, so `armq list` previewed every line against nothing and reported a conflict: use live's base
    q = "/data/USER/st/bq"
    live = open(q + "/live.txt").readline().split()[1]
    a = open(q + "/diffbase.txt").readline().split()
    base = a[1] if len(a) > 1 and a[0] == live else live
    return base if os.path.isdir(os.path.join("/homes/USER/cambc/bots", base, "src")) else live


def next_trunk(t):
    m = re.fullmatch(r"nova_trunk(\d+)([a-z])", t)
    if not m:
        die(f"cannot name the next trunk after {t}")
    n, c = int(m.group(1)), m.group(2)
    while True:
        n, c = (n + 1, "a") if c == "z" else (n, chr(ord(c) + 1))
        name = f"nova_trunk{n}{c}"
        if not os.path.lexists(f"{REPO}/bots/{name}") and not os.path.lexists(f"{OLD}/{name}"):
            return name


def next_bundle(slug):
    nums = [1000]  # bundle numbers have 4+ digits (agent bots like nova_b912_x have 3); 3 Nov: was 1\d{3}, which reused nova_b2000 forever
    for d in (REPO + "/bots", OLD):
        for x in os.listdir(d):
            m = re.match(r"nova_b(\d{4,})(?!\d)", x)
            if m:
                nums.append(int(m.group(1)))
    try:  # 2 Nov: bots get pruned, and a reused number would reuse its TAG's files in st/bq
        nums += [int(m.group(1)) for x in json.load(open(STATE)) for m in [re.match(r"nova_b(\d{4,})(?!\d)", x)] if m]
    except (OSError, ValueError):
        pass
    # 7 Nov (armq arms several lines at once): a number is RESERVED atomically (mkdir) the moment it is chosen, so two arms that start
    # together never share a number, and so a TAG (shipwatch refuses a TAG used twice); reservations count like existing bots
    res = "/data/USER/st/bq/bundle_res"
    os.makedirs(res, exist_ok=True)
    nums += [int(x) for x in os.listdir(res) if x.isdigit()]
    # 9 Nov 16:41Z (Builder): shipwatch refused nova_b10171 / nova_b10172 because TAG 10171 / 10172 was used years of bots ago by nova_b1017_bundle33
    # (an old bot's tags are its number plus a suffix, so 1017 + '1' = 10171): skip every number shipwatch's tag table already holds
    try:
        used = set(json.load(open(STATE)).get("_tags", {}))
    except (OSError, ValueError, AttributeError):
        used = set()
    n = max(nums) + 1
    while True:
        if str(n) in used:
            n += 1
            continue
        try:
            os.mkdir(os.path.join(res, str(n)))
            break
        except FileExistsError:
            n += 1
    return f"nova_b{n}_{slug}"


def read_marker(bot):
    try:
        return open(f"{REPO}/bots/{bot}/SHIPCHECK").read()
    except OSError:
        return ""


def pending(me):
    """[(bot, {flips})] of shipchecks running now."""
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        return []
    out = []
    for b, v in st.items():
        if b != me and isinstance(v, dict) and v.get("status") == "started":
            lock = f"/data/USER/st/bq/.shipwatch_{b}.lock"
            try:  # 11 Nov (/var: one `flock` process per check per armq step): the same test in-process
                import fcntl as _f
                with open(lock, "a") as _lf:
                    _f.flock(_lf, _f.LOCK_EX | _f.LOCK_NB)
                    _f.flock(_lf, _f.LOCK_UN)
                continue  # its lock is free: that shipcheck has ended
            except BlockingIOError:
                pass
            except OSError:
                continue
            try:
                m = re.search(r"^FLIPS=(.*)$", open(f"{REPO}/bots/{b}/FLIP").read(), re.M)
            except OSError:
                m = None
            out.append((b, parse_flips(m.group(1)) if m else {}))
    return out


def run(cmd, env=None):
    print("$ " + " ".join(cmd), flush=True)
    t = time.time()
    r = subprocess.run(cmd, cwd=REPO, env=dict(os.environ, **(env or {})))
    print(f"  ({time.time() - t:.0f} s, exit {r.returncode})", flush=True)
    if r.returncode:
        die(f"stopped: {os.path.basename(cmd[3] if cmd[0] == 'nice' else cmd[2] if len(cmd) > 2 else cmd[0])} failed; nothing further ran")


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("donors")
    ap.add_argument("flips")
    ap.add_argument("lane", choices=["fix", "behaviour", "draft", "ctrunk"])  # ctrunk (owner 6 Nov): tools/lab/ctrunk.py  # draft (4 Nov): drafter-only changes, shipcheck's LANE=draft
    ap.add_argument("--subject")
    ap.add_argument("--name")
    ap.add_argument("--trunk")
    ap.add_argument("--private-trunk", help="7 Nov (armq private trunks): name the merged trunk NAME (not the next nova_trunkNNx), so the rolling trunk line is untouched")
    ap.add_argument("--set", default="")
    ap.add_argument("--live")
    ap.add_argument("--carry-pending", action="store_true")
    ap.add_argument("--parambar", action="store_true", help="marker PARAMBAR=1, behaviour or draft lane: also needs the deciding read (fresh, or draft-changed maps) at n >= 1,140, point >= 0.5025, LOS >= 90%%")
    ap.add_argument("--seqspar", action="store_true", help="marker SEQ_SPAR=1, behaviour lane (owner 3 Nov, MH only): a lone spar second-read FAIL with 0 in its CI still extends")
    ap.add_argument("--fuelx", help="marker FUELX=X (owner 6 Nov): the capped-fuel row passes at cap5 ratio <= X; logged as fuel debt")
    ap.add_argument("--rare", help="marker RARE=N (owner 7 Nov), fix lane: the read on N maps where the games differ decides; shipcheck needs bq/rarebar.txt")
    ap.add_argument("--shadow", help="marker SHADOW='FLAG=V ...', with --rare: shipcheck's base becomes the SHADOW twin (the same donor computing, not acting), so "
                    "the rare changed-map leg reads CAND v SHADOW (maps change only where the rule acts) and the trunk-code row reads SHADOW v live (CI Analyser 10 Nov)")
    ap.add_argument("--revises-live", help="marker REVISES='FILE:TEXT[;FILE:TEXT]': live lines this candidate changes on purpose (a fix or revert of a "
                    "just-shipped line); shipcheck's base check waives exactly those (Builder 10 Nov)")
    ap.add_argument("--rare-fams", help="marker RAREFAMS=w_a,w_b, with --rare: every second batch of generated maps comes from these families")
    ap.add_argument("--wfams", help="marker WFAMS=f1,f2 (11 Nov): shipcheck's fresh / stylepanel legs draw only these generator families (SP_WFAMS)")
    ap.add_argument("--class", dest="cls", help="marker CLASS=NAME:OPvalue (10 Nov, Planner; e.g. heavy_ge:>=0.5, tools/lab/mapclass.py): shipcheck's "
                    "fresh / stylepanel legs draw only maps of that class (SP_CLASS), so its fresh rows mean class maps; BIG is unchanged")
    ap.add_argument("--base-has", help="marker BASEHAS=F (draft lane or --rare): the probe draws from tools/lab/draftstock.py's stock, only maps passing the filter F")
    ap.add_argument("--confirm-from", help="marker CONFIRM_FROM=TAG (owner 9 Nov; shipcheck reread_requeue only): a full PASS (TAG) refused for base: CONFIRM MODE")
    ap.add_argument("--confirm-n", help="marker CONFIRM_N=k with --confirm-from: live moves since that full PASS (shipwatch/shipcheck cap 2)")
    ap.add_argument("--q1bar", action="store_true", help="marker Q1BAR=1, fix lane: owner Q1 no-harm bar (fresh >= .495, CI upper >= .50) for play-identical cuts with a real fuel effect")
    ap.add_argument("--bugbar", action="store_true", help="marker BUGBAR=1, fix lane: the Builder only, for verified bug fixes or play-identical changes")
    ap.add_argument("--parallel", action="store_true", help="arm now beside running shipchecks, each read against the CURRENT live (armq parallel "
                    "mode, Builder 3 Nov); a PASS that a sibling's ship overtakes is re-read once against the new live (shipcheck reread_requeue)")
    ap.add_argument("--stack-on", help="run now beside bundle A, reading against A's values; no submit unless A ships (shipstack.py); needs the switch")
    ap.add_argument("--requeue-of", help="shipcheck's own: this bot's check is ending, so it does not count as pending")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--merge-only", action="store_true", help="8 Nov (owner: 5-8 min iterations): only the private trunk (merge, build, identity); prearm runs this beside its checks")
    ap.add_argument("--prebuilt", help="NAME: the private trunk is built already (prearm --merge-only): flip and marker only")
    ap.add_argument("--arm", action="store_true")
    a = ap.parse_args()
    if a.plan and a.arm:
        die("--plan and --arm together make no sense")
    want = parse_flips(a.flips)
    live = a.live or open(LIVE).readline().split()[1]
    trunk = a.trunk or current_trunk()
    stack_flips = {}
    if a.stack_on:
        if a.donors != "-":
            die("--stack-on: flips only; both bundles must be flips of one trunk")
        if not shipstack.enabled(BQ):
            die(f"--stack-on: stacking is off ({shipstack.SWITCH} is not in {BQ})")
        if live == a.stack_on:
            die(f"--stack-on: {a.stack_on} is live already: arm without it")
        try:
            fa = open(f"{REPO}/bots/{a.stack_on}/FLIP").read()
        except OSError:
            die(f"--stack-on: {a.stack_on} has no FLIP file")
        if shipstack.depth(a.stack_on, REPO, BQ) >= shipstack.MAX_STACK:
            die(f"--stack-on: {a.stack_on} already stands on {shipstack.MAX_STACK} running: at most {shipstack.MAX_STACK} stacked")
        stack_flips = parse_flips(re.search(r"^FLIPS=(.*)$", fa, re.M).group(1))
        clash = [k for k in want if k in stack_flips]
        if clash:
            die(f"--stack-on: both bundles set {', '.join(clash)}: not independent")
    import donorbase  # 10 Nov (b1823): NEW:LIVE where newbot.sh copied the baked base -> NEW:nova_base_vNNN
    a.donors = donorbase.fix(a.donors)
    donors = [] if a.donors == "-" else a.donors.split(",")
    tv, lv = values(trunk), values(live)
    carried = {k: v for k, v in lv.items() if k in tv and tv[k] != v}
    bad = {k: (want[k], carried[k]) for k in want if k in carried and want[k] != carried[k]}
    if bad:
        die("would revert live flips: " + ", ".join(f"{k}={w} but live has {v}" for k, (w, v) in bad.items()))
    if a.prebuilt and not os.path.isdir(f"{REPO}/bots/{a.prebuilt}/src"):
        die(f"--prebuilt: no bot {a.prebuilt}")
    new_trunk = a.prebuilt or ((a.private_trunk or next_trunk(trunk)) if donors else trunk)
    slug = a.name or re.sub(r"[^a-z0-9]", "", next(iter(want), "trunkship").lower())[:16]
    bundle = next_bundle(slug)
    skip = {a.requeue_of, a.stack_on, *(shipstack.chain(a.stack_on, REPO) if a.stack_on else [])}
    pend = [x for x in pending(bundle) if x[0] not in skip]
    extra = dict(stack_flips)
    for b, fl in pend:
        print(f"pending: {b} is in shipcheck, flips {fl or '(unknown)'}")
        if a.carry_pending:
            for k, v in fl.items():
                if k in want and want[k] != v:
                    die(f"{k}={want[k]} conflicts with pending {b}'s {k}={v}")
                extra[k] = v
    if a.arm and pend and not a.carry_pending and not a.parallel:
        die("another bundle's shipcheck is running: wait for it, or use --carry-pending / --parallel")
    flips = {**carried, **extra, **want}
    if not flips:  # flip.sh needs a flag: one at the trunk's value changes no byte, and shipcheck's TRUNK mode gets its FLIP file
        src = f"{REPO}/bots/{trunk}/src"
        ok = (k for k, v in tv.items() if subprocess.run([sys.executable, "-I", LAB + "/flip.py", "check", src, f"{k}={v}"], capture_output=True).returncode == 0)
        k = next(ok, None)
        if not k:
            die(f"no flag of {trunk} passes flip.py check")
        flips = {k: tv[k]}
    # 10 Nov (Builder: 8 lines, sgk2b sgk4b sgn0b sgn2b fcr7b fcr6b gof0 gof1, failed trunkmerge IDENTITY at arm): a flag the trunk lacks was
    # set to 0, but a VALUE flag's live-equivalent setting is its donor's own default (nova_b1776_gof: #define SG_K 3, so SG_K=0 changed
    # play). The trunk now takes each missing flag's value from the donor that defines it; 0 only when no donor defines it.
    def donor_default(k):
        for dn in donors:
            src = f"{REPO}/bots/{dn.split(':', 1)[0]}/src"
            try:
                for fn in os.listdir(src):
                    if fn.endswith((".h", ".hpp", ".cc", ".cpp")):
                        m = re.search(r"^\s*#\s*define\s+" + re.escape(k) + r"\s+(-?(?:0[xX][0-9a-fA-F]+|\d+))\b", open(os.path.join(src, fn), errors="replace").read(), re.M)
                        if m:
                            return str(int(m.group(1), 0))
            except OSError:
                pass
        return "0"
    trunk_set = {k: donor_default(k) for k in want if k not in tv}  # bits too: GRT_BITS defaults to 1 in its donor (live behaviour on)
    if any(v != "0" for v in trunk_set.values()):
        print("trunk values from the donors' defaults: " + " ".join(f"{k}={v}" for k, v in trunk_set.items() if v != "0"), flush=True)
    trunk_set.update(parse_flips(a.set))
    subject = a.subject or f"{'fix' if a.lane == 'fix' else 'feat'}(trunk): " + (" ".join(f"{k}={v}" for k, v in want.items())[:60] or f"{new_trunk} as it is")
    py = [sys.executable, "-I"]
    fs = " ".join(f"{k}={v}" for k, v in flips.items())
    steps = []
    if donors and not a.prebuilt:
        steps.append((["nice", "-n", "10", *py, LAB + "/trunkmerge.py", *donors, trunk, new_trunk] + (["--union-auto"] if a.private_trunk else []) + ["--set",
                       " ".join(f"{k}={v}" for k, v in trunk_set.items())], None))
        if a.private_trunk and os.environ.get("FASTSHIP_FLAGORPHAN", "1") != "0":  # 7 Nov (diff model): advisory, never stops the arm
            fo = f"/data/USER/st/bq/flagorphan/{new_trunk}.txt"  # in the background: 74 s measured, and it never stops the arm
            steps.append((["sh", "-c", f"mkdir -p /data/USER/st/bq/flagorphan && (nice -n 10 {sys.executable} -I {LAB}/flagorphan.py {live} {new_trunk} > {fo} 2>&1 "
                           f"|| echo 'FLAGORPHAN (advisory): live + this diff orphans or bakes flags' >> {fo}) > /dev/null 2>&1 & echo 'flagorphan in the background: {fo}'"], None))
    if a.merge_only:
        if not donors:
            die("--merge-only needs donors")
        t0 = time.time()
        for c, e in steps:
            run(c, e)
        if not new_trunk.startswith("nova_ptk_"):  # 9 Nov 20:45Z: no measurement set for a per-line private trunk (see below)
            subprocess.Popen(["nice", "-n", "10", sys.executable, "-I", LAB + "/trunkset.py", new_trunk], cwd=REPO, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        print(f"PREBUILT {new_trunk} on {trunk} ({time.time() - t0:.0f} s)")
        return 0
    steps.append((["nice", "-n", "10", "sh", LAB + "/flip.sh", new_trunk, bundle, fs], {"FLIP_BUILD": "1"} if os.environ.get("FASTSHIP_BUILD") == "1" else None))
    mk = [*py, LAB + "/mkmarker.py", bundle, f"LANE={a.lane}", "BIG=2000", f"BIGSET={shipstack_bigset()}", f"TRUNK={new_trunk}"]
    if carried or stack_flips:
        mk.append("LIVEVALS=" + " ".join(f"{k}={v}" for k, v in {**carried, **stack_flips}.items()))
    if a.stack_on:
        mk.append("STACK_ON=" + a.stack_on)
    if a.parambar:
        if a.lane not in ("behaviour", "draft"):  # 12 Nov (Builder, RC C634): a draft parameter (DTZ DTM_PP) reads its draft-changed maps
            die("--parambar needs the behaviour or draft lane")
        mk.append("PARAMBAR=1")
    if a.seqspar:
        if a.lane != "behaviour":
            die("--seqspar needs the behaviour lane")
        mk.append("SEQ_SPAR=1")
    if a.bugbar:
        if a.lane != "fix":
            die("--bugbar needs the fix lane")
        mk.append("BUGBAR=1")
    if getattr(a, "q1bar", False):
        if a.lane != "fix":
            die("--q1bar needs the fix lane")
        mk.append("Q1BAR=1")
    if getattr(a, "fuelx", None):
        mk.append(f"FUELX={a.fuelx}")
    if getattr(a, "rare", None):
        mk.append(f"RARE={a.rare}")
    if getattr(a, "shadow", None):
        if not getattr(a, "rare", None) or not re.fullmatch(r"[A-Z][A-Z0-9_]*=-?\d+( [A-Z][A-Z0-9_]*=-?\d+)*", a.shadow):
            die(f"--shadow needs --rare and flips like X_BITS=19, not {a.shadow!r}")
        mk.append(f"SHADOW={a.shadow}")
    if getattr(a, "revises_live", None):
        if not all(":" in w and w.split(":", 1)[1].strip() for w in a.revises_live.split(";")) or "\n" in a.revises_live:
            die(f"--revises-live needs 'FILE:TEXT[;FILE:TEXT]', not {a.revises_live!r}")
        mk.append(f"REVISES={a.revises_live}")
    if getattr(a, "rare_fams", None):
        mk.append(f"RAREFAMS={a.rare_fams}")
    if getattr(a, "base_has", None):
        mk.append(f"BASEHAS={a.base_has}")
    if getattr(a, "cls", None):
        sys.path.insert(0, LAB)
        import mapclass
        mapclass.parse(a.cls)
        mk.append(f"CLASS={a.cls}")
    if getattr(a, "wfams", None):
        mk.append(f"WFAMS={a.wfams}")
    if getattr(a, "confirm_from", None):  # owner 9 Nov: a full PASS refused for base, re-armed on the new live: a short CONFIRM read (shipcheck)
        if not re.fullmatch(r"[A-Za-z0-9_]+", a.confirm_from) or not re.fullmatch(r"[12]", a.confirm_n or "1"):
            die(f"--confirm-from needs a TAG and --confirm-n 1 or 2, not {a.confirm_from!r} {a.confirm_n!r}")
        mk += [f"CONFIRM_FROM={a.confirm_from}", f"CONFIRM_N={a.confirm_n or '1'}"]
    mk.append("SUBJECT=" + subject)
    steps.append(([*mk, "--dry"], None))
    print(f"live {live}; trunk {trunk} -> {new_trunk}; bundle {bundle}; lane {a.lane}")
    print(f"flips: {fs}" + (f"  (carried from live: {carried})" if carried else "  (nothing to carry)"))
    if a.plan:
        for c, e in steps:
            print("  " + "".join(f"{k}={v} " for k, v in (e or {}).items()) + " ".join(repr(x) if " " in x else x for x in c))
        print("--plan: nothing was run")
        return 0
    t0 = time.time()
    for c, e in steps:
        run(c, e)
    # 9 Nov 20:45Z (owner: jobs wait forever): trunkset's shared measurement set made sense for ONE shared trunk; in diff mode every armed line
    # gets its own private trunk (nova_ptk_*), so each arm launched a 600-game set nobody reads: 63 ran at once (~38k games), most of the pilot
    # backlog. Only a real shared trunk still gets one.
    if donors and not a.prebuilt and not new_trunk.startswith("nova_ptk_"):
        subprocess.Popen(["nice", "-n", "10", sys.executable, "-I", LAB + "/trunkset.py", new_trunk], cwd=REPO, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    if a.arm:
        if [x for x in pending(bundle) if x[0] not in skip] and not a.carry_pending and not a.parallel:
            die("another bundle's shipcheck started meanwhile: not armed")
        run(mk)
        print(f"ARMED {bundle} ({time.time() - t0:.0f} s): shipwatch gates it and auto-submits on PASS")
    else:
        print(f"READY {bundle} ({time.time() - t0:.0f} s), not armed. To arm:\n  " + " ".join(repr(x) if " " in x else x for x in mk))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FastshipError as e:
        die(str(e))
