#!/usr/bin/env python3
"""armq: the arm queue, so a candidate never waits for the Builder's next tick. Tool builder, 2 Nov.

  python3 -I tools/lab/armq.py add DONOR:BASE|- "FLAG=V ..." fix|behaviour|draft "SUBJECT" [SLUG] [--bugbar] [--no-preflight] [--front]    append a line (--front: at the head, next to arm) (the Builder only: this leads to a submit on PASS)
      --class 'heavy_ge:>=0.5' (10 Nov, Planner; tools/lab/mapclass.py): marker CLASS: shipcheck's fresh / stylepanel legs draw only maps of
      that class (SP_CLASS), so the fresh rows (and pooled BIG+fresh) mean class maps; BIG is unchanged. Never pre-bundled (FIXPRE) or a ride-along
  python3 -I tools/lab/armq.py list                                                            what waits
  python3 -I tools/lab/armq.py promote SLUG                                                    move the waiting line with that slug to the head
  python3 -I tools/lab/armq.py drop SLUG                                                       remove the waiting line with that slug (not one mid-merge)
  python3 -I tools/lab/armq.py fuelbank [arm TAG [--front] | done TAG]                         the fuel change bank: lines that failed only on fuel; arm re-queues one
  python3 -I tools/lab/armq.py --loop                                                          the daemon: pid in armq.pid, log armq.log
A line with a donor is merged at once, ahead of its turn, into the next trunk at live's values (trunkmerge: identity vs live), so its arm is a 5-second data flip: a rolling trunk.
When no shipcheck runs the daemon takes the oldest ready line and runs fastship.py ... --arm. With the stacking switch on and a shipcheck running, it stacks the line on the last one
if the flips don't overlap and the chain is under shipstack.MAX_STACK. `armq.py donor DONOR:BASE` merges with nothing to arm. Shipcheck still decides, shipwatch still starts it, and every check of
fastship and mkmarker still applies. `add` runs a preflight first (Builder 3 Nov: an hour of arms lost to avoidable fails): the SUBJECT must pass
shipwatch's format (type(area): summary, <= 60 chars); a donor whose change live already holds is dropped from the line with a note; a dry 3-way merge
of each donor onto the current trunk, after every donor queued ahead of it, must have no conflict. --no-preflight skips it (the Builder's call).
A merge and a rebuild from live never run at once (one lock, armq.trunk.lock). A line that fails to arm goes to armq.failed with its reason and is not retried; a second failure running pauses arming (file armq.paused) and keeps the line. ARMQ_DRY=1 prints the command and arms nothing."""
import collections
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import time

Q = os.environ.get("ARMQ_DIR", "/data/USER/st/bq")
FILE, FAILED, LOG, PID, LAST = (os.path.join(Q, x) for x in ("armq.txt", "armq.failed", "armq.log", "armq.pid", "armq.last"))
ARMED_DONORS = os.path.join(Q, "armed_donors.jsonl")  # {bot, donors}: what each armed bot carried (shipcheck re-arms read it)
GATE_QUEUE = 100
KNOWN = {"donors", "flips", "lane", "subject", "slug", "bugbar", "q1bar", "parambar", "seqspar", "fuelx", "rare", "rarefams", "shadow", "revises", "basehas", "merged", "t", "prebuilt",
         "confirm_from", "confirm_n", "cls", "wfams", "nobundle"}  # nobundle: 11 Nov (--no-bundle); cls: 10 Nov (Planner) class read, fastship --class (marker CLASS); confirm_*: owner 9 Nov, a full PASS refused for base re-armed for a short CONFIRM read (shipcheck reread_requeue)
PAUSED = os.path.join(Q, "armq.paused")
DIFF_SWITCH = os.path.join(Q, "armq_diff")  # 7 Nov (owner): present = DIFF MODEL: every line arms on live + its own diffs only; no rolling trunk
PRIVATE_SWITCH = os.path.join(Q, "armq_private")  # 7 Nov (Builder): rolling-trunk mode only: a parallel line arms on live + its own donors when the shared trunk carries others'


def diff_mode():
    return os.path.exists(DIFF_SWITCH) and os.environ.get("ARMQ_DIFF", "1") != "0"
DROPPED = os.path.join(Q, "armq.dropped.jsonl")  # 6 Nov: slugs dropped by hand; arm() skips them even when the line was already being built
MERGING = os.path.join(Q, "armq.merging")
FLAGMAP = os.path.join(Q, "armq.flagmap.json")  # flag -> the donor whose merge brought it  # the line being merged now: hands off
FAILS = [0]
WAITING = [None]
REPO = "/homes/USER/cambc"
sys.path.insert(0, REPO + "/tools/lab")
import fastship  # noqa: E402
import shipstack  # noqa: E402
import mergecheck as M  # noqa: E402
TRUNK_LOCK = os.path.join(Q, "armq.trunk.lock")
BATCH_SWITCH = os.path.join(Q, "armq_batch")  # 5 Nov (owner: speed parallel iterations): present = batch merges + void requeue; rm = the old path, at once
VOIDQ = os.path.join(Q, "armq.voidq.jsonl")  # markers shipwatch voided that went back on the queue
BATCH_FAILED = set()  # donor sets whose batch merge failed: they merge one at a time, which names the donor at fault
T_START = time.time()


class trunk_lock:
    """One merge or rebuild at a time (3 Nov: a merge onto 11c ran while 11d was rebuilt from live). flock per open file, so it holds between this
    daemon's threads and against an `armq.py rebuild` by hand."""
    def __init__(self, wait=True):
        self.wait = wait

    def __enter__(self):
        self.f = open(TRUNK_LOCK, "a")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | (0 if self.wait else fcntl.LOCK_NB))
        except OSError:
            self.f.close()
            return False
        return True

    def __exit__(self, *e):
        self.f.close()


def log(s):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {s}\n")


def edit(fn):
    """fn(lines) -> new lines, under the file's lock."""
    with open(FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        lines = open(FILE).read().splitlines() if os.path.exists(FILE) else []
        new = fn(lines)
        open(FILE + ".new", "w").write("".join(x + "\n" for x in new))
        os.replace(FILE + ".new", FILE)


def src_of(bot):
    """{file: bytes} of a bot's src (realpath: links to /data)."""
    d = os.path.realpath(f"{REPO}/bots/{bot}") + "/src"
    # 6 Nov (Builder): a patch run's *.orig / *.rej leftovers are never source (trunkmerge skips them too; preflight warns)
    return {f: open(os.path.join(d, f), "rb").read() for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)) and not f.endswith(STRAY)}


STRAY = (".orig", ".rej")


def strays(bot):
    d = os.path.realpath(f"{REPO}/bots/{bot}") + "/src"
    try:
        return sorted(f for f in os.listdir(d) if f.endswith(STRAY))
    except OSError:
        return []


FLAGVAL = re.compile(rb"^(\s*(?:#define [A-Z][A-Z0-9_]* |inline const volatile int [A-Z][A-Z0-9_]*\[\d+\] = \{ ?[0-9a-fA-Fx]+, ))-?\d+", re.M)


def merge3(cur, base, donor, mask=False):
    """git merge-file -p CUR BASE DONOR on bytes -> (result, conflicts). mask: flag values read as N on all three (a donor's flag at 0 v live's at 1)."""
    if mask:
        cur, base, donor = (FLAGVAL.sub(rb"\1N", x) for x in (cur, base, donor))
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as t:
        ps = []
        for n, x in (("c", cur), ("b", base), ("d", donor)):
            open(os.path.join(t, n), "wb").write(x)
            ps.append(os.path.join(t, n))
        m = subprocess.run(["git", "merge-file", "-p", *ps], capture_output=True)
        if m.returncode > 0 and not mask:  # trunkmerge --union-auto: every conflict block a pure addition on both sides -> keep both
            d3 = subprocess.run(["git", "merge-file", "-p", "--diff3", *ps], capture_output=True).stdout.decode("utf-8", "surrogateescape")
            bl = re.findall(r"^\|{7}[^\n]*\n(.*?)^={7}$", d3, re.M | re.S)
            if bl and all(not x.strip() for x in bl):
                return subprocess.run(["git", "merge-file", "-p", "--union", *ps], capture_output=True).stdout, 0
        if m.returncode > 0 and not mask:  # 6 Nov: the structured merge (tools/lab/smerge.py) before calling it a conflict
            try:
                import smerge
                sm, _note = smerge.merge_bytes(cur, base, donor, getattr(merge3, "name", "x.cpp"))
                if sm is not None:
                    return sm, 0
            except Exception:  # noqa: BLE001  the plain result stands
                pass
        return m.stdout, max(0, m.returncode)


def apply_donor(cur, donor):
    """trunkmerge's step 2 on {file: bytes}: -> (new files, [conflicted files], [changed files])."""
    dn, _, bn = donor.partition(":")
    d = src_of(dn)
    b = src_of(bn) if bn else src_of(os.path.basename(M.infer_base(M.botdir(dn), M.botdir(fastship.current_trunk()))))
    out, conf, changed = dict(cur), [], []
    for f, x in sorted(d.items()):
        if b.get(f) == x:
            continue
        changed.append(f)
        if f not in b:
            if f in cur and cur[f] != x:
                conf.append(f + " (new in the donor, the trunk has its own)")
            out[f] = x if f not in cur else cur[f]
            continue
        if cur.get(f) == b[f]:
            out[f] = x
            continue
        merge3.name = f  # smerge picks the C++ / FLIP rules by name
        r, n = merge3(cur.get(f, b""), b[f], x)
        if n:
            conf.append(f"{f} ({n} conflicts)")
        else:
            out[f] = r
    return out, conf, changed


def in_live(donor, live):
    """Every file the donor changed already holds its change in live (a 3-way of live with the donor changes nothing, flag values aside)."""
    dn, _, bn = donor.partition(":")
    if not bn:
        return False
    d, b = src_of(dn), src_of(bn)
    changed = [f for f in d if b.get(f) != d[f]]
    if not changed:
        return False
    for f in changed:
        if f not in live:
            return False
        if f not in b:
            if FLAGVAL.sub(rb"\1N", live[f]) != FLAGVAL.sub(rb"\1N", d[f]):
                return False
            continue
        r, n = merge3(live[f], b[f], d[f], mask=True)
        if n or r != FLAGVAL.sub(rb"\1N", live[f]):
            return False
    return True


def contained(donor, files):
    """6 Nov (owner: merging too slow; armq re-applied donors the trunk already held: m32t, bh67): every non-trivial line the donor adds over its BASE is
    in FILES and the lines it deleted are gone (flag values masked, multiset per file). A contained donor is not merged again; its flips stay."""
    dn, _, bn = donor.partition(":")
    if not bn:
        return False
    try:
        d, b = src_of(dn), src_of(bn)
    except OSError:
        return False
    changed = [f for f in d if b.get(f) != d[f] and not f.endswith(("nova_all.cpp",))]
    if not changed:
        return False
    cnt = lambda x: collections.Counter(ln.strip() for ln in FLAGVAL.sub(rb"\1N", x).split(b"\n"))  # noqa: E731
    trivial = lambda ln: len(ln) <= 3 or not re.search(rb"[A-Za-z0-9_]{3}", ln)  # noqa: E731
    for f in changed:
        if f not in files:
            return False
        T, D, B = cnt(files[f]), cnt(d[f]), cnt(b.get(f, b""))
        if any(not trivial(ln) and T[ln] < D[ln] for ln in D - B):
            return False
        if any(not trivial(ln) and T[ln] >= B[ln] for ln in B - D):
            return False
    return True


CONT = {}  # (donor, trunk) -> contained(): a queue pass every 10 s reads no source twice


def strip_contained():
    """Queue lines lose the donors the current trunk already holds; a line left with none becomes flip-only (merged= keeps what it carried)."""
    rows = open(FILE).read().splitlines() if os.path.exists(FILE) else []
    trunk = fastship.current_trunk()
    files, hit = None, set()
    for x in rows:
        ds = json.loads(x)["donors"]
        for d in ds.split(",") if ds != "-" else []:
            if (d, trunk) not in CONT:
                files = files or src_of(trunk)
                CONT[(d, trunk)] = contained(d, files)
            if CONT[(d, trunk)]:
                hit.add(d)
    if not hit:
        return

    def upd(ls):
        out = []
        for y in ls:
            q = json.loads(y)
            ds = q["donors"].split(",") if q["donors"] != "-" else []
            keep = [d for d in ds if d not in hit]
            if len(keep) == len(ds):
                out.append(y)
            elif q.get("flips") is not None or keep:
                out.append(json.dumps(dict(q, donors=",".join(keep) or "-", merged=",".join(x for x in [q.get("merged")] + [d for d in ds if d in hit] if x))))
        return out
    edit(upd)
    log(f"contained in {trunk}, not merged again: {', '.join(sorted(hit))}")


def batch_chain(trunk, donors):
    """Queue order, in memory, with armq's own merge (git merge-file, then smerge): the donors that go in together, and {donor: conflicts} for the rest.
    6 Nov: ideastore.batchable's plain tree merge left out donors smerge merges (nwkr, m32t)."""
    cur, good, bad = src_of(trunk), [], {}
    for d in donors:
        new, conf, _ = apply_donor(cur, d)
        if conf:
            bad[d] = conf
        else:
            cur = new
            good.append(d)
    return good, bad


TABDECL = re.compile(rb"^inline const volatile int ([A-Z][A-Z0-9_]*_TAB)\[", re.M)
DEFINE = re.compile(rb"^#define ([A-Z][A-Z0-9_]*)[ \t]+(\S[^\n]*?)[ \t]*$", re.M)


def merge_problems(donor, trunk, merged):
    """4 Nov (Builder, eoj16/eoj481 lost to a stale DONOR:BASE): -> reasons a clean-looking merge will still fail.
    A flag table that the donor and the trunk both have but the BASE lacks means the donor was built on a newer bot than BASE,
    so the merge re-adds that code (--union keeps both copies); and a #define or table declared twice in one merged file."""
    dn, _, bn = donor.partition(":")
    d, t = src_of(dn), trunk
    b = src_of(bn) if bn else None
    out = []
    if b is not None:
        tabs = lambda fs: {m for x in fs.values() for m in TABDECL.findall(x)}
        stale = sorted((tabs(d) & tabs(t)) - tabs(b))
        if stale:
            out.append(f"BASE {bn} lacks {', '.join(x.decode() for x in stale[:4])} that {dn} and the trunk both have: the donor was "
                       f"built on a newer bot, so the merge re-adds that code. Use {dn}:<the bot it was copied from>, "
                       "with the donor's flags set to the trunk's values (flip.sh) if they differ")
    for f, x in sorted(merged.items()):
        if not f.endswith((".h", ".cpp", ".cc")):
            continue
        defs = {}
        for nm, v in DEFINE.findall(x):
            defs.setdefault(nm, set()).add(v)
        flagnames = set(re.findall(rb"[A-Z][A-Z0-9_]*", b"\n".join(re.findall(rb"^inline const volatile int [^\n]*", x, re.M))))
        dup = sorted(nm.decode() for nm, vs in defs.items() if len(vs) > 1 and nm in flagnames)  # flag values only: #if/#else pairs are fine
        dt = [nm.decode() for nm in set(TABDECL.findall(x)) if len(re.findall(rb"^inline const volatile int " + nm + rb"\[", x, re.M)) > 1]
        if dup or dt:
            out.append(f"merged {f}: " + ", ".join([f"#define {n} twice with different values" for n in dup[:4]] + [f"{n} declared twice" for n in dt[:4]]))
        if b"\n<<<<<<< " in x or x.startswith(b"<<<<<<< "):
            out.append(f"merged {f}: conflict markers left")
    return out


def flipcheck(files, flips, only_defined=False):
    """6 Nov (Builder: fxdr507's #ifndef guard and ccl's constexpr HUNT_TAB passed preflight, then flip.sh refused them at arm time: ~15 min stalled
    plus a trunk rebuild): flip.py check of a line's flips on the src the arm will see ({file: bytes}). -> REFUSE lines, [] when fine.
    only_defined: skip flags this src lacks (a flip-only line whose donor is queued; bring_donors handles those)."""
    fs = flipset(flips)
    if not fs:
        return []
    import tempfile
    with tempfile.TemporaryDirectory(prefix="armq_fc_") as d:
        for f, x in files.items():
            open(os.path.join(d, f), "wb").write(x)
        if only_defined:
            src = b"".join(files.values()).decode(errors="replace")
            fs = {k: v for k, v in fs.items() if re.search(r"^\s*#define " + re.escape(k) + r"\b", src, re.M)}
            if not fs:
                return []
        r = subprocess.run([sys.executable, "-I", f"{REPO}/tools/lab/flip.py", "check", d, " ".join(f"{k}={v}" for k, v in fs.items())],
                           capture_output=True, text=True)
    return [] if r.returncode == 0 else [x for x in (r.stdout + r.stderr).splitlines() if x.strip()] or [f"flip.py check rc {r.returncode}"]


def refuse_flips(bad, where):
    sys.exit(f"armq add: refused: flip.sh would refuse these flips on {where}: " + "; ".join(bad)[:900] +
             ". Make each flag `#define FLAG <int>` once, read only inside table initializers (no #ifndef guard, no constexpr copy), then add again")


def pre_trunk():
    """what a new line is checked against: the diff model's recorded base (else live, while a bake is pending); the rolling trunk otherwise"""
    if diff_mode():
        live = open(fastship.LIVE).readline().split()[1]
        return diff_base(live) or live
    return fastship.current_trunk()


def preflight(row):
    """-> (row to queue, notes) or exits with the reason. Read-only: temp files only."""
    ensure_bots(row["donors"].split(",") if row.get("donors") else [])
    import shipwatch
    notes = []
    if not re.fullmatch(shipwatch.SUBJECT_RE, row["subject"]):
        sys.exit(f"armq add: refused: SUBJECT {row['subject']!r} fails shipwatch's format: type(area): summary, type in "
                 "fix/feat/perf/tune/revert/refactor/bundle, area [a-z0-9_,-], summary 4-60 printable chars "
                 f"(this one is {len(row['subject'].split(': ', 1)[-1])})")
    for dd in (row["donors"].split(",") if row["donors"] != "-" else []):  # 8 Nov: a hook that steals an unbraced if's body (b1554 ESC)
        if ":" in dd:
            import bracecheck
            hb = [h for h in bracecheck.hits(*dd.split(":", 1)) if not h[5]]
            if hb:
                sys.exit("armq add: refused: " + "; ".join(f"{f}:{ln} '{new[:60]}' inserted after unbraced '{ctl[:60]}' (its body was "
                                                           f"'{body[:40]}')" for f, ln, ctl, new, body, _w in hb[:3])
                         + ". Brace the block; a false positive goes in /data/USER/st/bq/bracecheck_waive.txt (FILE:TEXT # why)")
    if row["donors"] == "-":
        t = pre_trunk()
        bad = flipcheck(src_of(t), row.get("flips"), only_defined=True)
        if bad:
            refuse_flips(bad, t)
        return row, notes
    live_bot = open(fastship.LIVE).readline().split()[1]
    live = src_of(live_bot)
    keep = []
    tfiles = src_of(pre_trunk())
    for dd in row["donors"].split(","):
        # 9 Nov (Builder, bb8h): with a baked base (diff model) the submitted live dir still has the shipped table volatile, so a donor that
        # UN-bakes it to flip it again read as "already in live" and was dropped. It counts as shipped only if the trunk holds it too.
        if in_live(dd, live) and (pre_trunk() == live_bot or contained(dd, tfiles)):
            notes.append(f"{dd}: its change is already in live {live_bot}: not merged again (dropped from the line)")
        elif contained(dd, tfiles):
            notes.append(f"{dd}: the trunk already holds it: not merged again (dropped from the line)")
        else:
            keep.append(dd)
    if not keep:
        if row.get("flips") is None:
            sys.exit("armq add: refused: " + "; ".join(notes) + "; nothing left to merge")
        bad = flipcheck(src_of(pre_trunk()), row.get("flips"), only_defined=True)
        if bad:
            refuse_flips(bad, pre_trunk())
        return dict(row, donors="-"), notes
    trunk = pre_trunk()
    base = src_of(trunk)
    for dd in keep:
        try:  # 6 Nov: rules lint on the donor's added lines (WARN; primer RULE SINGLE-SOURCE)
            import ruleslint
            dn_, _, bn_ = dd.partition(":")
            if bn_:
                rl = ruleslint.diff(bn_, dn_)
                if rl:
                    notes.append(f"{dd}: rules lint: {len(rl)} added line(s) with a hand-written rule number, e.g. "
                                 + "; ".join(f"{f}:{k} {r} -> {h}" for f, k, r, h, _ in rl[:3]))
        except Exception:  # noqa: BLE001  a lint never refuses a line
            pass
        st = strays(dd.partition(":")[0])
        if st:
            notes.append(f"{dd}: warning: patch leftovers in src ({' '.join(st)}): skipped by the merge; delete them from the donor folder")
        _, conf, _ = apply_donor(base, dd)
        if conf:
            sys.exit(f"armq add: refused: {dd} conflicts with the current trunk {trunk}: {', '.join(conf)}. Rebase the donor on {trunk} "
                     "(newbot.sh the trunk, port the change), then add DONOR:" + trunk)
    cur, ahead = base, []
    for x in (open(FILE).read().splitlines() if os.path.exists(FILE) and not diff_mode() else []):  # diff model: diffs never stack, each is checked alone
        for qd in json.loads(x)["donors"].split(","):
            if qd != "-" and qd not in keep:
                nxt, conf, _ = apply_donor(cur, qd)
                if not conf:  # a queued donor that conflicts fails on its own turn; the check goes on without it
                    cur = nxt
                    ahead.append(qd)
    for dd in keep:
        cur2, conf, _ = apply_donor(cur, dd)
        if conf:
            who = next((qd for qd in ahead if apply_donor(apply_donor(base, qd)[0], dd)[1]), "the donors queued ahead together")
            sys.exit(f"armq add: refused: {dd} conflicts with {who} (queued ahead, merged first): {', '.join(conf)}. Rebase one on the other, or queue "
                     "them as one line after the first ships")
        bad = merge_problems(dd, base, cur2)
        if any(x.startswith("merged ") for x in bad):  # a stale BASE alone can still merge right (identical blocks fold)
            sys.exit(f"armq add: refused: {dd}: " + "; ".join(bad))
        notes += [f"{dd}: note: {x}" for x in bad]
        cur = cur2
    bad = flipcheck(cur, row.get("flips"))
    if bad:
        refuse_flips(bad, f"{trunk} + {', '.join(ahead + keep)} merged")
    notes.append(f"preflight: {', '.join(keep)} merge cleanly onto {trunk}" + (f" after {len(ahead)} queued donor(s)" if ahead else ""))
    return dict(row, donors=",".join(keep)), notes


def save_idea(r):
    """Every donor line also becomes an idea (owner 5 Nov): its patch on the home and its trees in the store, so a failed one keeps its code after its folder goes."""
    try:
        import ideastore
        ideastore.init()
        for d in (r["donors"] or "-").split(","):
            if ":" in d and not d.startswith("nova_idea_"):
                dn, bn = d.split(":")
                nm = re.sub(r"[^a-z0-9_]", "", dn.replace("nova_", "", 1).lower())
                ideastore.idea_add(nm, dn, bn, r.get("flips") or "", lane=r.get("lane") or "", subject=r.get("subject") or "")
    except (Exception, SystemExit) as e:  # noqa: BLE001  never lose a queue line over this
        log(f"idea not saved for {r.get('donors')}: {str(e)[:120]}")


def fuelbank(a):
    """armq.py fuelbank [list] | fuelbank arm TAG [--front]: the fuel change bank (owner 7 Nov): lines that failed only on fuel, not closed. arm re-queues one as it was armed; the row stays until
    `fuelbank done TAG`. Code lines keep their code as ideas (save_idea), so a donor that was retired comes back through ideastore restore."""
    p = os.path.join(Q, "fuelbank.tsv")
    rows = [ln.rstrip("\n").split("\t") for ln in open(p)] if os.path.exists(p) else []
    if not rows:
        return print(f"fuel change bank: empty ({p})")
    head, rows = rows[0], [dict(zip(rows[0], x)) for x in rows[1:]]
    sub = a[0] if a else "list"
    if sub == "list":
        print(f"fuel change bank: {len(rows)} lines ({p})")
        for r in rows:
            print(f"  {r['tag']:10s} {r['version']:5s} {r['lane'][:5]:5s} point {r['point'][:6]:6s} n {r['n']:6s} cap5 {r['cap5']:10s} heavy {r['heavy']:10s} {r['donor'][:30]:30s} {r['flips'][:40]:40s} {r['subject'][:40]}")
        return
    hit = [r for r in rows if r["tag"] == (a[1] if len(a) > 1 else None)]
    if not hit:
        sys.exit(f"armq fuelbank: no tag {a[1:2]}")
    if sub == "done":
        keep = [r for r in rows if r not in hit]
        with open(p + ".new", "w") as o:
            o.write("\t".join(head) + "\n" + "".join("\t".join(r[c] for c in head) + "\n" for r in keep))
        os.replace(p + ".new", p)
        return print(f"fuel change bank: {a[1]} removed")
    if sub == "arm":
        r = hit[-1]
        return add([r["donor"], r["flips"], r["lane"], r["subject"] or f"fuel bank {r['tag']}"] + a[2:])
    sys.exit(fuelbank.__doc__)


def mcl3_clash(donors):
    """11 Nov (Shared Mem via Builder): until the MCL3 skeleton (b1822 mcl3sk) is live, each MCL3 donor carries its own mcl3_compute() /
    extra_put(MCL3_XID ...) / map_class3() copy and a 3-way merge of two can drop a class bit silently. -> the MCL3 donors of a csv when
    two or more carry it and live does not (else [])."""
    try:
        live = open(fastship.LIVE).readline().split()[1]
        if any(b"mcl3_compute" in v for v in src_of(live).values()):
            return []
    except (OSError, IndexError):
        pass
    hit = []
    for d in (donors or "-").split(","):
        name = d.split(":", 1)[0].strip()
        if not name or name == "-":
            continue
        try:
            if any(b"mcl3_compute" in v or b"extra_put(MCL3_XID" in v for v in src_of(name).values()):
                hit.append(name)
        except (OSError, ValueError):
            continue
    return hit if len(hit) > 1 else []


def add(a, front=False):
    # 12 Nov (Builder, RC C446b: nrf1c died at trunkmerge, identity 17/20, because its donor was a shipcheck bot whose header had
    # NRF_BITS 1 baked in): a donor must be the agent's own build (nova_bNNNN_*), never a shipcheck candidate (nova_b<5-digit tag>_*)
    # or a private trunk (nova_ptk_*). ARMQ_ALLOW_SC_DONOR=1 overrides.
    if a and ":" in a[0] and os.environ.get("ARMQ_ALLOW_SC_DONOR") != "1":
        bad = [d.split(":")[0] for d in a[0].split(",") if re.match(r"^nova_(b\d{5}_|ptk_)", d.split(":")[0])]
        if bad:
            sys.exit(f"armq add: refused: donor {', '.join(bad)} is a shipcheck candidate or private trunk (its flags are baked into a "
                     f"header, so trunkmerge's identity fails); use the agent's own build (nova_bNNNN_NAME) as the donor")
    _cl = mcl3_clash(a[0]) if a and ":" in a[0] else []
    if _cl:
        sys.exit(f"armq add: refused: MCL3 donors {', '.join(_cl)} in one line (each has its own mcl3_compute copy; a merge can drop a class "
                 f"bit) until the MCL3 skeleton (b1822 mcl3sk) is live: add them as separate lines")
    if a and a[0] not in ("-", "") and ":" in a[0] and os.environ.get("ARMQ_PREFLIGHT", "1") != "0":
        # 11 Nov (Builder, owner check-in): (a) a donor whose code live already holds makes a "flip-only" line that still names a donor
        # (jns6r armed with --trunk nova_base_v717): refused, add it as '-' with the same flips
        try:
            live = open(fastship.LIVE).readline().split()[1]
            lsrc = src_of(live)
            bb = diff_base(live)
            bsrc = src_of(bb) if bb and bb != live else None
            def _m(src):
                return {f: FLAGVAL.sub(rb"\1N", v) for f, v in src.items()}
            refs = [_m(lsrc)] + ([_m(bsrc)] if bsrc else [])
            held_ = []
            for d in a[0].split(","):
                dn, _, bn = d.partition(":")
                if not bn:
                    continue
                dm = _m(src_of(dn))
                if dm == _m(src_of(bn)) or any(dm == r for r in refs):  # no change of its own, or exactly live's / live's base's code
                    held_.append(d)
        except (Exception, SystemExit) as e:  # noqa: BLE001  the check never blocks an add on its own failure
            held_ = []
            print(f"armq add: live-code check not run ({str(e)[:100]})", file=sys.stderr)
        if held_:
            sys.exit(f"armq add: refused: live {live} already holds the code of {', '.join(held_)}: add the line as '-' (flip-only) with the "
                     f"same flips (ARMQ_PREFLIGHT=0 skips this check)")
        # (b) hunks shared with a queued / in-flight / running line (lfb127 v x3i31c, caught only by the RC): a warning, never a refusal
        try:
            hp = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/hunkdup.py"), a[0], "--quiet"], capture_output=True,
                                text=True, timeout=60)
            if hp.returncode == 1:
                print("armq add: WARNING: this line's code overlaps a queued/armed/running line (tools/lab/hunkdup.py):\n"
                      + "\n".join(x for x in hp.stdout.splitlines() if not x.startswith("{"))[:1500], file=sys.stderr)
                log(f"preflight: hunk overlap warning for {a[0]}: " + " | ".join(x for x in hp.stdout.splitlines() if not x.startswith("{"))[:300])
        except (OSError, subprocess.SubprocessError) as e:
            print(f"armq add: hunk overlap check not run ({str(e)[:100]})", file=sys.stderr)
    bugbar = "--bugbar" in a  # the Builder's call only, fix lane: fastship --bugbar
    q1bar = "--q1bar" in a  # 12 Nov owner Q1: play-identical cut with a real fuel effect, fix lane: fresh >= .495 + CI upper >= .50
    fuelx = None
    if "--fuelx" in a:  # owner 6 Nov ("Fuel later"): marker FUELX=X, the capped-fuel row passes at cap5 ratio <= X (fuel debt)
        i = a.index("--fuelx"); fuelx = a[i + 1]; a = a[:i] + a[i + 2:]
    rare = None
    if "--rare" in a:  # owner 7 Nov: marker RARE=N, fix lane: the read on N maps where the games differ decides
        i = a.index("--rare"); rare = a[i + 1]; a = a[:i] + a[i + 2:]
    revises = None
    if "--revises-live" in a:  # 10 Nov (Builder): live lines this line changes on purpose; shipcheck's base check waives exactly those
        i = a.index("--revises-live"); revises = a[i + 1]; a = a[:i] + a[i + 2:]
        if not all(":" in w and w.split(":", 1)[1].strip() for w in revises.split(";")):
            sys.exit(f"armq add: --revises-live needs 'FILE:TEXT[;FILE:TEXT]', not {revises!r}")
    shadow = None
    if "--shadow" in a:  # CI Analyser 10 Nov (spec_akx_1110 A4): with --rare, the compute-only twin's flips; shipcheck reads CAND v that twin
        i = a.index("--shadow"); shadow = a[i + 1]; a = a[:i] + a[i + 2:]
    rarefams = None
    if "--rare-fams" in a:  # with --rare: aim the generated maps at the families the change fires on
        i = a.index("--rare-fams"); rarefams = a[i + 1]; a = a[:i] + a[i + 2:]
    if "--rare" in a and not rarefams and os.environ.get("ARMQ_RARE_BANK", "1") == "1":
        # 12 Nov (owner via the Builder: "also limit rare as they take long"; wcs1s held a slot 70+ min probing the pool): a rare line with no
        # families banks ANY family (w_any; the slug's bq/rarebank_class.tsv line filters), so rarebank fills its bank outside a slot and the
        # read starts only when the bank holds its count (a short read waits on the bank again). ARMQ_RARE_BANK=0 keeps the old pool probe
        rarefams = "w_any"
    cls = None
    if "--class" in a:  # 10 Nov (Planner): marker CLASS=COND: a class read (fresh / panel maps of that class only)
        i = a.index("--class"); cls = a[i + 1]; a = a[:i] + a[i + 2:]
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import mapclass
        mapclass.parse(cls)  # exits on a bad condition
    wfams = None
    if "--wfams" in a:  # 11 Nov (TB 06b512, Econ GRC): marker WFAMS=f1,f2: every fresh / look / confirm / panel leg draws only these generator families
        i = a.index("--wfams"); wfams = a[i + 1]; a = a[:i] + a[i + 2:]
        if not re.fullmatch(r"w_[a-z0-9_]+(,w_[a-z0-9_]+)*", wfams):
            sys.exit(f"armq add: --wfams needs family names like w_goldrace1[,w_other], not {wfams!r}")
    basehas = None
    if "--base-has" in a:  # 8 Nov: the draft / rare probe draws from draftstock.py's stock, only maps passing this filter (marker BASEHAS=F)
        i = a.index("--base-has"); basehas = a[i + 1]; a = a[:i] + a[i + 2:]
    confirm = {}
    for opt, key in (("--confirm-from", "confirm_from"), ("--confirm-n", "confirm_n")):  # owner 9 Nov: shipcheck's reread_requeue of a full PASS refused for base only
        if opt in a:
            i = a.index(opt); confirm[key] = a[i + 1]; a = a[:i] + a[i + 2:]
    if confirm and (not re.fullmatch(r"[A-Za-z0-9_]+", confirm.get("confirm_from", "")) or not re.fullmatch(r"[12]", confirm.setdefault("confirm_n", "1"))):
        sys.exit(f"armq add: --confirm-from needs a TAG and --confirm-n 1 or 2, not {confirm}")
    if confirm and os.environ.get("ARMQ_CONFIRM_DUP_OK") != "1":
        # 13 Nov (Builder: SC14947 pjm256 got TWO confirms, shipwatch's auto 14963 FAIL .4992 and a hand arm 14969 PASS .5008 that shipped:
        # best-of-two is a winner's-curse leak): refuse a --confirm-from TAG when a confirm of that TAG already exists (a marker in bots/,
        # a shipwatch start line or an armq line). ARMQ_CONFIRM_DUP_OK=1 overrides on the owner's word only.
        ct = confirm["confirm_from"]
        hit = None
        for mk in glob.glob(os.path.join(REPO, "bots", "nova_b*", "SHIPCHECK")):
            try:
                if re.search(rf"^CONFIRM_FROM={re.escape(ct)}\s*$", open(mk, errors="replace").read(), re.M):
                    hit = os.path.basename(os.path.dirname(mk))
                    break
            except OSError:
                pass
        if not hit:
            try:
                for ln in open(os.path.join(Q, "shipwatch.log"), errors="replace"):
                    if f"CONFIRM_FROM={ct} " in ln or f"CONFIRM_FROM={ct}\n" in ln:
                        hit = (re.search(r"start (\S+):", ln) or re.search(r"(nova_\S+)", ln)).group(1)
            except (OSError, AttributeError):
                pass
        if hit:
            sys.exit(f"armq add: REFUSED: a confirm of TAG {ct} already exists ({hit}); a second confirm would be best-of-two "
                     f"(winner's curse). Read that confirm's verdict instead (owner's word only: ARMQ_CONFIRM_DUP_OK=1)")
    prebuilt = None
    if "--prebuilt" in a:  # 8 Nov: NAME@BASE, the private trunk prearm built beside its checks; arm() uses it only while BASE is still the base
        i = a.index("--prebuilt"); prebuilt = a[i + 1]; a = a[:i] + a[i + 2:]
    parambar = "--parambar" in a  # behaviour lane: fastship --parambar
    if "--score" in a:  # 10 Nov (owner via Builder): prior evidence (z) for shipwatch's queue order, kept in bq/evidence.tsv (tools/lab/evid.py)
        i = a.index("--score"); score_z = a[i + 1]; a = a[:i] + a[i + 2:]
    else:
        score_z = None
    seqspar = "--seqspar" in a  # behaviour lane, owner 3 Nov (MH only): fastship --seqspar
    skip = "--no-preflight" in a
    requeue = front  # the `front` command: a void stacked bundle's requeue (shipcheck), never refused
    front = front or "--front" in a  # 3 Nov (Builder): a gain candidate re-armed after an INCONCLUSIVE should not wait behind fix lines
    nobundle = "--no-bundle" in a  # 11 Nov (Builder: owner's one BIG2 re-read EACH; fixbatch's pre-test bundler must not group the line)
    a = [x for x in a if x not in ("--bugbar", "--q1bar", "--parambar", "--seqspar", "--no-preflight", "--front", "--no-bundle")]
    if a and a[0].startswith("idea:"):  # owner 5 Nov: an idea is a patch + flips (ideastore.py add); the line carries names the store can restore
        import ideastore
        ideastore.init()
        dn, fl, ln, sj = ideastore.resolve(a[0][5:])
        a = [dn, a[1] if len(a) > 1 and a[1] else fl, a[2] if len(a) > 2 else ln, a[3] if len(a) > 3 else sj] + a[4:] + ([] if len(a) > 4 else [a[0][5:]])
    if a:  # 10 Nov (Tool Builder, b1823): NEW:LIVE where newbot.sh copied the baked base -> NEW:nova_base_vNNN (donorbase.py)
        import donorbase
        a = [donorbase.fix(a[0])] + a[1:]
    if len(a) < 4 or a[2] not in ("fix", "behaviour", "draft", "ctrunk") or ((bugbar or q1bar) and a[2] != "fix"):  # ctrunk: owner 6 Nov (correctness batches)
        sys.exit(__doc__)
    if score_z is not None:
        try:
            import evid as _ev
            _sl = a[4] if len(a) > 4 and not a[4].startswith("-") else re.sub(r"[^a-z0-9]", "", a[3].lower())[:12]
            _ev.put(_sl, float(score_z), f"armq add --score: {a[3]}")
        except (ValueError, OSError, ImportError) as e:
            print(f"armq add: --score {score_z!r} not recorded ({e})")
    if rare and a[2] == "behaviour":
        # 13 Nov (Builder: play-changing rare lines were labelled 'fix' and RC kept flagging it): 'behaviour' is accepted with --rare. A RARE
        # line runs shipcheck's rare legs on the fix lane internally (no BIG, the changed-map read decides; bars unchanged), so it is stored as fix
        # with play=1; shipcheck's fix-lane submit hold (bq/hold_fix_lane) does not hold RARE lines without --bugbar/--q1bar
        a[2] = "fix"
        print("armq add: --rare with lane behaviour: armed as the rare lane (stored lane fix, play-changing; same rare bar)")
    if rare and (a[2] != "fix" or not re.fullmatch(r"\d+", rare) or not 50 <= int(rare) <= 1200):  # 7 Nov: vvh6 (behaviour + --rare) reached mkmarker and failed there
        sys.exit(f"armq add: --rare needs lane fix and 50-1200 changed maps, not lane {a[2]}, {rare}")
    if shadow and (not rare or not re.fullmatch(r"[A-Z][A-Z0-9_]*=-?\d+( [A-Z][A-Z0-9_]*=-?\d+)*", shadow)):
        sys.exit(f"armq add: --shadow needs --rare and flips like X_BITS=19 (the donor computing, not acting), not {shadow!r}")
    if rarefams and (not rare or not re.fullmatch(r"w_[a-z0-9_]+(,w_[a-z0-9_]+)*", rarefams)):
        sys.exit(f"armq add: --rare-fams needs --rare and families as w_a,w_b, not {rarefams}")
    if basehas and not (rare or a[2] == "draft") or (basehas and not re.fullmatch(r"[A-Za-z0-9_,=/+<>.!-]+", basehas)):
        sys.exit(f"armq add: --base-has needs the draft lane or --rare, and a draftstock filter (ryth / ryth,prism+team=T4/T5 / !kit,kit = a seat fields none / -kit,kit = neither seat / class>=V), not {basehas}")
    r = dict(donors=a[0], flips=a[1], lane=a[2], subject=a[3], slug=a[4] if len(a) > 4 else None, bugbar=bugbar, **({"q1bar": True} if q1bar else {}), parambar=parambar, seqspar=seqspar, fuelx=fuelx, rare=rare, rarefams=rarefams, shadow=shadow, revises=revises, basehas=basehas, t=time.time())
    if cls:
        r["cls"] = cls
    if nobundle:
        r["nobundle"] = True
        if r.get("slug"):
            with open(os.path.join(Q, "nobundle_slugs.txt"), "a") as _f:  # fixbatch matches re-queues by slug root
                _f.write(r["slug"] + "\n")
    if wfams:
        r["wfams"] = wfams
    if not (skip or requeue):  # a void stacked bundle's requeue (shipcheck) must never be refused; add --front still runs the preflight
        r, notes = preflight(r)
        for n in notes:
            print(n)
            log("add: " + n)
    if prebuilt:
        r["prebuilt"] = prebuilt
    r.update(confirm)  # only when given: a line without them is the same row as before
    row = json.dumps(r)
    # 12 Nov (TB: jkc2 was added twice 2 s apart and both copies armed in parallel, sharing one rare bank): an identical line (donors, flips,
    # lane) already waiting in the queue is not added again
    try:
        for ln in open(FILE):
            q = json.loads(ln)
            # 12 Nov (Builder: lsoc / lsor share donor + flips but read different rare families): every read-selecting field must match too
            sel = ("rare", "rarefams", "cls", "wfams", "basehas", "slug", "bugbar", "q1bar", "parambar")
            if ((q.get("donors"), q.get("lane")) == (r.get("donors"), r.get("lane")) and flipset(q.get("flips") or "") == flipset(r.get("flips") or "")
                    and all(str(q.get(k) or "") == str(r.get(k) or "") for k in sel)):
                log(f"add: skipped, the same donors/flips/lane/read is already queued as {q.get('slug')}")
                return print(f"skipped: already queued as {q.get('slug')}")
    except (OSError, ValueError):
        pass
    save_idea(r)
    if r.get("slug") and dropped_recently(r["slug"]):  # 6 Nov: a re-add of a dropped slug revives it (else arm() skipped it for 24 h)
        with open(DROPPED, "a") as f:
            f.write(json.dumps(dict(slug=r["slug"], t=time.time(), revive=True)) + "\n")
    edit(lambda ls: [row] + ls if front else ls + [row])
    print(f"queued{' first' if front else ''}: {r['donors']} {a[1]} {a[2]}")
    print("  note: a passed screen does not decide; shipcheck's read does (primer RULE CONFIRM-READ). One verdict over every read: tools/lab/verdict.py idea FLAG=V")


def fail(r, why):
    with open(FAILED, "a") as f:
        f.write(json.dumps(dict(r, why=why[-2000:])) + "\n")
    key = [x.strip() for x in why.splitlines() if re.search(r"FAIL|Error|error:|refused|conflict", x)]  # 4 Nov: the reason, not the tail
    log("FAILED: " + (" | ".join(key[:4])[:400] if key else why[-200:]))
    try:  # 11 Nov (Planner: acc1s/ace4s/ace8s/sce3rs sat in armq.failed for 6 h unnoticed): every drop is a PENDING read owed, shown by since.py
        reason = (" | ".join(key[:2]) if key else why.strip().splitlines()[-1:][0] if why.strip() else "?")[:220]
        with open("/data/USER/st/bq/pending_reads.txt", "a") as f:
            f.write(f"PENDING: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} armq FAILED, never read: {r.get('slug') or '-'} "
                    f"({r.get('donors') or '-'} {r.get('flips') or '-'} {r.get('lane') or '-'}): {reason}; rebuild/rebase and re-arm, or DROP with a reason\n")
    except OSError:
        pass


def ensure_bots(donors):
    """A retired bot comes back from the store (5 Nov: old bots are deleted, ideastore keeps them)."""
    for b in {x for d in donors for x in d.split(":") if x and x != "-"}:
        if not os.path.lexists(f"{REPO}/bots/{b}"):
            r = subprocess.run([sys.executable, "-I", REPO + "/tools/lab/ideastore.py", "restore", b], capture_output=True, text=True)
            log(f"{b}: {(r.stdout + r.stderr).strip()[-120:]}")


def merge(donor):
    """donor (or several, comma-free list) into the next trunk at live's values, one build and one identity check. -> "" or why not."""
    donors = donor if isinstance(donor, list) else [donor]
    donor = ", ".join(donors)
    ensure_bots(donors)
    trunk = fastship.current_trunk()
    live = open(fastship.LIVE).readline().split()[1]
    lv, tv = fastship.values(live), fastship.values(trunk)
    new = fastship.next_trunk(trunk)
    fs = " ".join(f"{k}={v}" for k, v in lv.items() if k in tv and tv[k] != v)
    log(f"merging {donor} onto {trunk} -> {new} (live {live})")
    t0 = time.time()
    p = subprocess.run(["nice", "-n", "10", sys.executable, "-I", REPO + "/tools/lab/trunkmerge.py", *donors, trunk, new, "--union-auto", "--set", fs], capture_output=True, text=True, cwd=REPO)
    log(f"rc {p.returncode} in {time.time() - t0:.0f} s: {(p.stdout + p.stderr).strip().splitlines()[-1:]}"
        + "".join(f" [{x.strip()}]" for x in p.stdout.splitlines() if x.startswith("timings:"))[:200])  # 3 Nov: where a merge's ~225 s go
    if p.returncode == 0:
        try:  # which flags this donor brought: a rebuild re-merges a donor only while a queued line still flips one of them
            new_flags = set(fastship.values(new)) - set(tv)
            fm = json.load(open(FLAGMAP)) if os.path.exists(FLAGMAP) else {}
            if len(donors) == 1:
                fm.update({k: donors[0] for k in new_flags})
            else:  # a batch: a flag belongs to the donor that defines it (the last one if two do, as the old one-at-a-time map)
                for d in donors:
                    fm.update({k: d for k in new_flags & set(fastship.values(d.split(":")[0]))})
            json.dump(fm, open(FLAGMAP + ".new", "w"))
            os.replace(FLAGMAP + ".new", FLAGMAP)
        except Exception as e:  # noqa: BLE001
            log(f"!! flag map not updated: {str(e)[:120]}")
        return ""
    # a failed merge leaves a half-made bot with conflict markers, never registered: next_trunk skips a name that exists, but nobody should find this one
    link = f"{REPO}/bots/{new}"
    real = os.path.realpath(link)
    if os.path.lexists(link) and new not in open(fastship.REGISTRY, errors="ignore").read():
        if real != link and real.startswith("/data/USER/st/new/bots/"):
            shutil.rmtree(real, ignore_errors=True)
            os.unlink(link)
        elif real == link:
            shutil.rmtree(link, ignore_errors=True)
    try:  # 5 Nov (Builder: cpb1, bk3, ssu3 dropped): a ship mid-merge makes trunkmerge's identity check run against the NEW live and fail
        now = open(fastship.LIVE).readline().split()[1]
    except (OSError, IndexError):
        now = live
    if now != live:
        log(f"live moved {live} -> {now} during the merge: not a failure; the line stays queued and merges onto a trunk built on {now}")
        return LIVE_MOVED
    return p.stdout + p.stderr


LIVE_MOVED = "LIVE_MOVED"


def merged_already(donor):
    """The donor bot (DONOR:BASE) appears as merged in a registry line of the current trunk or one before it on the line."""
    name = donor.split(":")[0]
    reg = open(fastship.REGISTRY, errors="ignore").read()
    cut = [m.end() for m in re.finditer(r"^- nova_trunk\w+ REBUILT .*$", reg, re.M)]
    reg = reg[cut[-1]:] if cut else reg  # only merges since the last rebuild from live count
    return any(a == name for a, _ in line_donors(reg))


def line_donors(reg):
    """(donor, base) of every merge line in this registry text: one line may carry several (a batch merge: "T + A (base B): took ...; C (base D): ...")."""
    out = []
    for ln in re.findall(r"^- nova_trunk\w+ \(trunkmerge [^)]*\): nova_trunk\w+ \+ (.*)$", reg, re.M):
        out += re.findall(r"(?:^|; )(\S+) \(base (\S+)\)", ln.split(". --set ")[0])
    return out


def prepare():
    """The oldest line with a donor: merge it now, whoever is in shipcheck. Under the trunk lock: a rebuild waits for the merge and its queue edit."""
    with trunk_lock():
        prepare1()


def prepare_batch(rows):
    """Every queued donor into ONE new trunk: one build instead of one per donor (5 Nov: after each ship 7-8 donors merged in turn, ~21 min with
    every arm waiting; a real 5-donor chain took 1,129 s, the batch 173 s, source hash identical). trunkmerge applies them in queue order, so the
    source is what the chain would reach, with the same checks. A failed batch falls back to one at a time, which names the donor at fault.
    -> True when it handled this round."""
    lines = [(x, json.loads(x)) for x in rows]
    with_d = [(x, r) for x, r in lines if r["donors"] != "-"]
    donors = list(dict.fromkeys(d for _, r in with_d for d in r["donors"].split(",") if not merged_already(d)))
    if len(donors) < 2 or tuple(donors) in BATCH_FAILED:
        return False
    if tidy(locked=True):
        return True
    try:  # in memory: a donor that conflicts stays queued (the one-at-a-time path names it) and does not cost the others their batch (5 Nov: one planner.cpp conflict sent 6 donors one at a time)
        donors, bad = batch_chain(fastship.current_trunk(), donors)
        for d, cf in bad.items():
            log(f"batch: leaving out {d}: conflict in {', '.join(cf)}")
    except (Exception, SystemExit) as e:  # noqa: BLE001  the check is an optimisation: without it trunkmerge still decides
        log(f"batch: conflict check not run: {str(e)[:120]}")
    if len(donors) < 2:
        return False
    open(MERGING, "w").write(json.dumps(dict(donors=",".join(donors), slugs=[r.get("slug") for _, r in with_d if r.get("slug")])) + "\n")
    log(f"batch: {len(donors)} donors into one trunk")
    try:
        why = merge(donors)
        if why == LIVE_MOVED:  # every line stays queued; the next round batches them onto a trunk built on the new live
            return True
        if why:
            BATCH_FAILED.add(tuple(donors))
            log(f"batch failed, merging one at a time: {why.strip()[-200:]}")
            return False

        def done(ls):
            out = []
            for y in ls:
                q = json.loads(y)
                ds = q["donors"].split(",") if q["donors"] != "-" else []
                if not ds or not set(ds) <= set(donors):  # a flip-only line, or one queued after the batch began
                    out.append(y)
                elif q.get("flips") is not None:
                    out.append(json.dumps(dict(q, donors="-", merged=q["donors"])))
            return out
        edit(done)
        return True
    finally:
        try:
            os.remove(MERGING)
        except OSError:
            pass


def requeue_voided():
    """A marker shipwatch voided because live moved and its merge conflicts (19 on 5 Nov, always the FLIP file, usually adjacent #define lines): the idea is
    its flips + donors, so it goes back on the queue and is applied to the new live. At most 3 times per idea, then pending_reads.txt."""
    try:
        state = json.load(open(fastship.STATE))
    except (OSError, ValueError):
        return
    seen = [json.loads(x) for x in open(VOIDQ)] if os.path.exists(VOIDQ) else []
    done = {x["bot"] for x in seen}
    for name, st in state.items():
        if name.startswith("_") or name in done or not isinstance(st, dict) or st.get("at", 0) < T_START:
            continue
        if not str(st.get("status", "")).startswith("skipped: merge onto"):
            continue
        try:
            kv = dict(ln.strip().split("=", 1) for ln in open(f"{REPO}/bots/{name}/SHIPCHECK") if "=" in ln)
            fi = dict(ln.strip().split("=", 1) for ln in open(f"{REPO}/bots/{name}/FLIP") if "=" in ln)
        except OSError:  # not a flip candidate: the Builder's
            continue
        own = shipstack.own_flips(shipstack.parse_flips(fi.get("FLIPS", "")), shipstack.parse_flips(kv.get("LIVEVALS", "")))
        fl = " ".join(f"{k}={v}" for k, v in sorted(own.items()))
        dn = "-"
        if os.path.exists(ARMED_DONORS):
            for ln in open(ARMED_DONORS):
                d = json.loads(ln)
                if d.get("bot") == name:
                    dn = d.get("donors") or "-"
        key = f"{kv.get('LANE')} {fl} {dn}"
        rec = dict(bot=name, key=key, t=time.time())
        rows = [json.loads(x) for x in open(FILE)] if os.path.exists(FILE) else []
        busy = {k for y in rows for k in flipset(y.get("flips") or "")} | {k for _, f in fastship.pending("") for k in (f or {})}
        why = ("no own flips or donors" if not fl and dn == "-" else
               "a queued or running line already sets one of its flags" if busy & set(own) else
               "voided 3 times" if sum(x["key"] == key for x in seen) >= 3 else "")
        with open(VOIDQ, "a") as f:
            f.write(json.dumps(dict(rec, why=why)) + "\n")
        seen.append(rec)
        if why:
            log(f"void {name}: not requeued: {why}")
            if why.startswith("voided"):
                with open(os.path.join(Q, "pending_reads.txt"), "a") as f:
                    f.write(f"PENDING: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {name} voided 3 times by ships; re-arm: armq.py add {dn} \"{fl}\" {kv.get('LANE')} \"{kv.get('SUBJECT')}\" --front\n")
            continue
        slug = re.sub(r"[^a-z0-9]", "", name.split("_", 2)[-1]) + "q"
        row = dict(donors=dn, flips=fl, lane=kv.get("LANE"), subject=kv.get("SUBJECT"), slug=slug, bugbar=kv.get("BUGBAR") == "1", **({"q1bar": True} if kv.get("Q1BAR") == "1" else {}),
                   parambar=kv.get("PARAMBAR") == "1", seqspar=kv.get("SEQSPAR") == "1", rare=kv.get("RARE"), rarefams=kv.get("RAREFAMS"), shadow=kv.get("SHADOW"), revises=kv.get("REVISES"), basehas=kv.get("BASEHAS"), t=time.time(),
                   **({"cls": kv["CLASS"]} if kv.get("CLASS") else {}), **({"wfams": kv["WFAMS"]} if kv.get("WFAMS") else {}))
        edit(lambda ls: [json.dumps(row)] + ls)
        log(f"void {name}: requeued first as {slug}: {dn} {fl}")


def prepare1():
    strip_contained()
    rows = open(FILE).read().splitlines() if os.path.exists(FILE) else []
    if train_hold():  # owner 6 Nov: no merge between trains; ctrunk donors wait for the next train's ONE merge
        rows = [x for x in rows if not held_line(json.loads(x))]
    if os.path.exists(BATCH_SWITCH) and prepare_batch(rows):
        return
    for x in rows:
        r = json.loads(x)
        if r["donors"] == "-":
            continue
        if tidy(locked=True):  # never merge onto a failed or dead line: the rebuild requeues this line's donor onto a clean trunk
            return
        open(MERGING, "w").write(x + "\n")  # 2 Nov: an edit removed a line mid-merge; edits should leave this line alone
        for d in r["donors"].split(","):
            if merged_already(d):  # a re-queued donor that a merge took in meanwhile: no second merge
                log(f"{d}: already merged into the trunk line; not merged again")
                continue
            why = merge(d)
            if why == LIVE_MOVED:  # keep the line; tidy() rebuilds the trunk from the new live on the next round
                try:
                    os.remove(MERGING)
                except OSError:
                    pass
                return
            if why:
                fail(r, why)
                edit(lambda ls: [y for y in ls if y != x])
                try:  # 5 Nov: a failed merge left armq.merging behind
                    os.remove(MERGING)
                except OSError:
                    pass
                return
        if r.get("flips") is None:
            edit(lambda ls: [y for y in ls if y != x])
        else:
            edit(lambda ls: [json.dumps(dict(r, donors="-", merged=r["donors"])) if y == x else y for y in ls])
        try:
            os.remove(MERGING)
        except OSError:
            pass
        return


def needed_donors(rows, live_vals):
    """Donors whose flags some flip-only queued line sets and live lacks (from FLAGMAP)."""
    fm = json.load(open(FLAGMAP)) if os.path.exists(FLAGMAP) else {}
    out = []
    for y in rows:
        if y.get("flips") and y["donors"] == "-":
            for k in shipstack.parse_flips(y["flips"]):
                d = fm.get(k)
                if k not in live_vals and d and d not in out:
                    out.append(d)
    return out


def dead_donors(trunk):
    """Donors merged on the trunk line since its last rebuild that no queued line still needs (the donor's lines all failed or closed)."""
    reg = open(fastship.REGISTRY, errors="ignore").read()
    cut = [m.end() for m in re.finditer(r"^- nova_trunk\w+ REBUILT .*$", reg, re.M)]
    reg = reg[cut[-1]:] if cut else reg
    on = line_donors(reg)
    rows = [json.loads(x) for x in open(FILE).read().splitlines()] if os.path.exists(FILE) else []
    live = open(fastship.LIVE).readline().split()[1]
    need = set(needed_donors(rows, fastship.values(live))) | {d for y in rows for d in (y.get("merged") or y["donors"]).split(",") if d != "-"}
    return [f"{a}:{b}" for a, b in on if f"{a}:{b}" not in need]


def rebuild(keep, why):
    """A new trunk = an exact copy of the live bot (newbot.sh), registered as REBUILT; then only the donors in keep (DONOR:BASE, in order) are queued
    to merge onto it, at the queue head, so dead flag-0 code from failed or closed donors goes (Builder 3 Nov: trunk8h failed its code row on it).
    Bundles in shipcheck on the old trunk run on; a line already merged and queued gets its donor back so it merges onto the new trunk."""
    with trunk_lock():
        return rebuild1(keep, why)


def rebuild1(keep, why):
    live = open(fastship.LIVE).readline().split()[1]
    new = fastship.next_trunk(fastship.current_trunk())
    r = subprocess.run(["sh", REPO + "/tools/lab/newbot.sh", live, new], capture_output=True, text=True, cwd=REPO)
    if r.returncode:
        log(f"rebuild failed: newbot {live} {new}: {(r.stdout + r.stderr).strip()[-200:]}")
        return False
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(fastship.REGISTRY, "a") as f:
        f.write(f"- {new} REBUILT {stamp} (armq): exact copy of live {live}; the trunk line restarts here. {why}. Donors queued again: "
                f"{', '.join(keep) or 'none'}.\n")
    def requeue(ls):
        rows = [json.loads(x) for x in ls]
        for y in rows:
            if y.get("merged") and y["donors"] == "-":
                y["donors"] = y.pop("merged")  # merged onto the old trunk: merge again
        for d in needed_donors(rows, fastship.values(live)):  # a flip-only line (a void bundle's requeue) whose flags live lacks
            if d not in keep:
                keep.append(d)
        have = {d for y in rows for d in y["donors"].split(",") if d != "-"}
        head = [dict(donors=d, flips=None, t=time.time()) for d in keep if d not in have]
        return [json.dumps(y) for y in head + rows]
    edit(requeue)
    log(f"REBUILT {new} from live {live} ({why}); donors queued: {keep}")
    return True


def flipset(flips):
    """{flag: value} of a line's flips; '-' (a code-only line: the trunk's own code read at live values) is none. 3 Nov: undefined() and the
    parallel check parsed '-' and the step crashed for 14 min on bake25."""
    return {} if not flips or flips.strip() == "-" else shipstack.parse_flips(flips)


def undefined(flips, trunk):
    """Flags of a line that the trunk does not define (no '#define FLAG' in its src): flip.sh would refuse the arm."""
    d = os.path.realpath(f"{REPO}/bots/{trunk}") + "/src"
    src = "".join(open(os.path.join(d, f), errors="replace").read() for f in os.listdir(d) if f.endswith((".h", ".cpp", ".cc")))
    return [k for k in flipset(flips) if not re.search(r"^\s*#define " + re.escape(k) + r"\b", src, re.M)]


def bring_donors(missing, rows):
    """A flip-only line whose flags the trunk lacks (3 Nov: a VOID requeue armed on a fresh REBUILT trunk before its donor merged back, b971x16,
    b971x1): queue the donors that brought those flags (FLAGMAP) at the head, unless queued or merging. -> what it waits for."""
    fm = json.load(open(FLAGMAP)) if os.path.exists(FLAGMAP) else {}
    queued = {d for y in rows for d in (json.loads(y)["donors"].split(",") if json.loads(y)["donors"] != "-" else [])}
    try:
        queued |= set(json.loads(open(MERGING).read())["donors"].split(","))
    except (OSError, ValueError, KeyError):
        pass
    need = [fm[k] for k in missing if k in fm]
    new = [d for d in dict.fromkeys(need) if d not in queued]
    if new:
        edit(lambda ls: [json.dumps(dict(donors=d, flips=None, t=time.time())) for d in new] + ls)
        log(f"queued donor(s) {new} first: the next flip-only line sets {missing}, which the trunk lacks")
    return need, [k for k in missing if k not in fm]


PAR_FILE = os.path.join(Q, "parallel_max")  # PARALLEL mode (Builder 3 Nov): this many shipchecks side by side, each v live; 0 = stacking


def par_max():
    """How many lines may run side by side against live (PARALLEL mode, the default: 3); 0 in BQ/parallel_max falls back to stacking."""
    try:
        return max(0, int(open(PAR_FILE).read().split()[0]))
    except (OSError, ValueError, IndexError):
        return 3


def stack_target(flips, pend):
    """The running bundle to stack on, or None when this line must wait."""
    if not shipstack.enabled(Q):
        return None
    if len(pend) > shipstack.MAX_STACK:  # the stack is full, or two run side by side: wait
        return None
    tail = max((b for b, _ in pend), key=lambda b: (shipstack.depth(b, REPO, Q), b))
    if shipstack.depth(tail, REPO, Q) >= shipstack.MAX_STACK:
        return None
    try:
        have = shipstack.parse_flips(next(x[6:].strip() for x in open(f"{REPO}/bots/{tail}/FLIP") if x.startswith("FLIPS=")))
    except (OSError, StopIteration):
        return None
    return None if set(flipset(flips)) & set(have) else tail


def built_on_live(trunk):
    try:
        sys.path.insert(0, REPO + "/tools/lab")
        import shipcheck
        live, _, parent = shipcheck.live_bot()
        return shipcheck.base_check(trunk, live, parent)[0]
    except Exception:  # noqa: BLE001  can't tell: don't rebuild on a guess
        return True


def failed_trunks():
    """Trunks with a FAIL in a finished 'trunk code vs live' gate (at live's values or not)."""
    out = set()
    for f in glob.glob("/data/USER/st/gate/tc*/verdict.txt"):
        try:
            t = open(f, errors="replace").read()
        except OSError:
            continue
        m = re.search(r"^GATE tc\w+: (\S+) vs ", t, re.M)
        if m and re.search(r"OVERALL: FAIL", t):
            out.add(re.sub(r"_live\w*$", "", m.group(1)))
    return out


def trunk_failed(trunk):
    """A FAIL in any finished 'trunk code vs live' gate of this trunk, at live's values or not."""
    return trunk in failed_trunks()


def line_trunks():
    """Trunks on the current line: the last REBUILT trunk and every trunk registered after it. Merges only add code, so a later trunk carries
    every earlier one's code."""
    reg = open(fastship.REGISTRY, errors="ignore").read()
    cut = [m.start() for m in re.finditer(r"^- nova_trunk\w+ REBUILT .*$", reg, re.M)]
    return re.findall(r"^- (nova_trunk[0-9]+[a-z])\b", reg[cut[-1]:] if cut else reg, re.M)


TIDIED = set()
TIDY_LOCK = threading.Lock()
ON_LIVE = {}


def off_live(trunk):
    """-> the live bot when the trunk is not built on it, else "". Checked once per (live.txt head, trunk): 4 Nov (Builder, v489 hand-submit) the
    built_on_live check ran only with a flip line at the queue head, so the next donor merged onto the v488 trunk and conflicted."""
    try:
        head = open(fastship.LIVE).readline().split()[:2]
    except OSError:
        return ""
    key = (tuple(head), trunk)
    if key not in ON_LIVE:
        ON_LIVE[key] = built_on_live(trunk)
    return "" if ON_LIVE[key] else " ".join(head)


def dirty(trunk):
    """Why the trunk line must restart from live before its next merge or arm, or "". 4 Nov (Builder, mfd2 1345): after mfd1's trunk code row
    FAILED on 18g, the next donor merged onto 18g at once (18h, the same code: the failed donor's code was still there), shipcheck reused the
    FAIL and refused mfd2 unplayed. The old checks ran only in step() with a flip line queued and looked only at the current trunk's own gate."""
    lv = off_live(trunk)
    if lv:  # live moved on (a ship or a hand submit): merges and arms need a trunk built on it
        return f"{trunk} is not built on live {lv}"
    bad = [t for t in line_trunks() + [trunk] if t in failed_trunks()]
    if bad:
        return f"the trunk line carries {bad[0]}'s code, whose trunk code row FAILED"
    if not fastship.pending(""):  # nothing runs on the trunk now: drop dead donors' flag-0 code (Builder 3 Nov)
        dead = dead_donors(trunk)
        if dead:
            return f"{trunk} carries donors no queued line needs: {', '.join(dead)}"
    return ""


def tidy(locked):
    """Rebuild the trunk from live (queued donors only) when dirty(); once per trunk. -> True when it rebuilt or tried to."""
    with TIDY_LOCK:  # the preparer and the arm loop both come here: 5 Nov two threads rebuilt the same trunk (27h, 27i)
        trunk = fastship.current_trunk()
        if trunk in TIDIED:
            return False
        if train_hold() and all(held_line(json.loads(x)) for x in (open(FILE).read().splitlines() if os.path.exists(FILE) else [])):
            return False  # owner 6 Nov: the trunk stays put between trains, so agents' base is stable; another lane's line still gets its rebuild
        why = dirty(trunk)
        if not why:
            return False
        TIDIED.add(trunk)
    log(f"{why}: rebuilding from live")
    (rebuild1 if locked else rebuild)([], why)
    return True


def not_started():
    """The bundle armed last, if shipwatch has not started it yet (at most 3 min): pending() can't see it, and on 2 Nov 21:21Z that let two bundles start unstacked side by side."""
    try:
        d = json.load(open(LAST))
        st = json.load(open(fastship.STATE)).get(d["bot"], {})
    except (OSError, ValueError, KeyError):
        return False
    return time.time() - d["t"] < 180 and not str(st.get("status", "")).startswith(("started", "ended", "refused", "skipped", "rebased"))


def release_gates():
    """gate.py's cap only binds when the queue is deep: with few pilot items queued the oldest ticket goes, which lets the next waiting gate in, first come first served.
    A ticket's gate keeps playing without it; every gate, also one waiting on older code, reads the same directory."""
    d = "/data/USER/st/gate/.turns"
    if not os.path.isdir(d) or len(os.listdir("/homes/USER/condor-runs/pilotq/queue")) >= GATE_QUEUE:
        return
    t = sorted(os.listdir(d))
    if len(t) > int(os.environ.get("GATE_CAP", 4)):
        os.remove(os.path.join(d, t[0]))
        log(f"gate released: queue under {GATE_QUEUE}, {len(t) - 1} tickets left")


def releaser():
    while True:
        try:
            release_gates()
        except (Exception, SystemExit) as e:  # noqa: BLE001  a library sys.exit must not end the thread
            log(f"!! release: {str(e)[:200]}")
        time.sleep(20)


TRAIN_SWITCH = os.path.join(Q, "armq_train")  # 6 Nov (owner: "why is it so slow"; Builder): present = ctrunk lines ship as trains; rm = parallel arming
TRAIN_STATE = os.path.join(Q, "armq.train.json")  # {n, running: {slug, bot, lines, t}, groups: [[rows], ...]}


TRAIN_EVERY = os.path.join(Q, "armq_train_every")  # minutes between a ship and the next merge + train (owner 6 Nov: bigger batches); default 45
TRAIN_NOW = os.path.join(Q, "armq_train_now")      # touch: the next merge + train goes now (removed when that train starts)


def train_on():
    return os.path.exists(TRAIN_SWITCH)


def train_every():
    try:
        return float(open(TRAIN_EVERY).read().split()[0])
    except (OSError, ValueError, IndexError):
        return 45.0


def train_hold():
    """ctrunk lines just queue: a train is running, its halves are waiting, or the interval since the last ship has not passed (armq_train_now ends it).
    Held: no merge of their donors, no train, and they do not block other lanes; no rebuild from live unless another lane's line needs one."""
    if not train_on() or os.path.exists(TRAIN_NOW):
        return False
    st = train_load()
    if st.get("running") or st.get("groups"):
        return True
    return bool(st.get("last_end")) and time.time() - st["last_end"] < train_every() * 60


def held_line(q):
    return q.get("lane") == "ctrunk" and not is_train(q)


def train_load():
    try:
        return json.load(open(TRAIN_STATE))
    except (OSError, ValueError):
        return dict(n=0, running=None, groups=[])


def train_save(st):
    with open(TRAIN_STATE + ".new", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(TRAIN_STATE + ".new", TRAIN_STATE)


def is_train(q):
    return str(q.get("slug") or "").startswith("train")


def train_subject(n, slugs):
    s, used = f"fix(ctrunk): train {n}:", 0
    for x in slugs:  # shipwatch's SUBJECT_RE allows a 60-character summary
        if len(s) - len("fix(ctrunk): ") + len(x) + 8 > 60:
            break
        s += (" " if used == 0 else ",") + x
        used += 1
    return s + (f" +{len(slugs) - used}" if used < len(slugs) else "")


def train_start(st, lines):
    """One row at the head of the queue: every line's flips, the normal arm path takes it from there. Two values for one flag: the later line waits."""
    fl, take, wait = {}, [], []
    for q in lines:
        f = flipset(q["flips"])
        if any(k in fl and fl[k] != v for k, v in f.items()):
            wait.append(q)
            continue
        fl.update(f)
        take.append(q)
    st["n"] = st.get("n", 0) + 1
    n, slugs = st["n"], [q.get("slug") or "?" for q in take]
    fx = [float(q["fuelx"]) for q in take if q.get("fuelx")]
    row = dict(donors="-", flips=" ".join(f"{k}={v}" for k, v in fl.items()), lane="ctrunk", subject=train_subject(n, slugs), slug=f"train{n}", bugbar=False,
               parambar=False, seqspar=False, fuelx=max(fx) if fx else None, merged=",".join(q["merged"] for q in take if q.get("merged")) or None, t=time.time())
    gone = {json.dumps(q, sort_keys=True) for q in take}
    edit(lambda ls: [json.dumps(row)] + [y for y in ls if json.dumps(json.loads(y), sort_keys=True) not in gone])
    st["running"] = dict(slug=row["slug"], bot=None, lines=take, t=time.time())
    if os.path.exists(TRAIN_NOW):
        os.remove(TRAIN_NOW)
    inq = {json.dumps(json.loads(y), sort_keys=True) for y in (open(FILE).read().splitlines() if os.path.exists(FILE) else [])}
    off = [q for q in wait if json.dumps(q, sort_keys=True) not in inq]  # a held-back line stays where it was: in the queue, or in a group
    if off:
        st["groups"] = [off] + st.get("groups", [])
    train_save(st)
    log(f"train {n}: {len(take)} lines as one ctrunk shipcheck: {', '.join(slugs)}; flips {row['flips']}" + (f"; {len(wait)} wait (a flag with two values)" if wait else ""))


def train_end(st, why):
    """A train that did not ship: halves go next; a single line is that line's failure."""
    run = st["running"]
    lines, st["running"] = run["lines"], None
    if len(lines) == 1:
        log(f"train {run['slug']}: its one line {lines[0].get('slug')} failed: {why}")
        fail(lines[0], f"train {run['slug']}: {why}")
    else:
        h = len(lines) // 2
        st["groups"] = [lines[:h], lines[h:]] + st.get("groups", [])
        log(f"train {run['slug']} {why}: split into {len(lines[:h])} + {len(lines[h:])} lines for the next trains")
    train_save(st)


def train_tick():
    st = train_load()
    rows = [json.loads(x) for x in (open(FILE).read().splitlines() if os.path.exists(FILE) else [])]
    gone = [q.get("slug") for q in rows if held_line(q) and q["donors"] == "-" and q.get("slug") and dropped_recently(q["slug"]) and not os.path.exists(MERGING)]
    if gone:  # dropped mid-merge: a held line never reaches arm(), which removes tombstoned lines
        edit(lambda ls: [y for y in ls if json.loads(y).get("slug") not in gone])
        log(f"train: dropped lines removed from the queue: {', '.join(gone)}")
        rows = [q for q in rows if q.get("slug") not in gone]
    run = st.get("running")
    if run:
        slug = run["slug"]
        follow = next((q for q in rows if str(q.get("slug") or "") != slug and str(q.get("slug") or "").startswith(slug)), None)
        if any(q.get("slug") == slug for q in rows):
            return
        bots = sorted(glob.glob(f"{REPO}/bots/nova_b*_{slug}"), key=os.path.getmtime)
        bot = os.path.basename(bots[-1]) if bots else None
        if bot and bot != run.get("bot"):
            run["bot"] = bot
            train_save(st)
        if not bot:
            if follow:
                run["slug"] = follow["slug"]
                train_save(st)
            elif time.time() - run["t"] > 900:
                train_end(st, "never armed (smoke disaster or an arm failure: see armq.failed)")
            return
        if bot in {ln.split()[1] for ln in open(fastship.LIVE) if len(ln.split()) > 1}:
            log(f"train {slug} shipped as {bot}: {', '.join(q.get('slug') or '?' for q in run['lines'])}; next merge + train in {train_every():g} min (or touch {TRAIN_NOW})")
            st["running"], st["last_end"] = None, time.time()
            train_save(st)
        else:
            try:
                stv = str(json.load(open(fastship.STATE)).get(bot, {}).get("status", ""))
            except (OSError, ValueError):
                return
            if stv.startswith("ended"):
                if follow:  # shipcheck re-queued it (+r overtaken, +i inconclusive): the same lines ride on
                    log(f"train {slug}: re-queued by shipcheck as {follow['slug']}")
                    run.update(slug=follow["slug"], bot=None, t=time.time())
                    train_save(st)
                elif "PASS" not in stv:
                    train_end(st, f"ended {stv[6:60]}")
        if st.get("running"):
            return
    if os.path.exists(MERGING) or os.path.exists(PAUSED) or not_started():
        return
    trunk = fastship.current_trunk()
    if not built_on_live(trunk) or dirty(trunk):
        return
    if st.get("groups"):
        return train_start(st, st["groups"].pop(0))
    if train_hold():
        return
    ready = [q for q in rows if q.get("lane") == "ctrunk" and q["donors"] == "-" and q.get("flips") is not None and not is_train(q)
             and not (q.get("slug") and dropped_recently(q["slug"])) and not undefined(q["flips"], trunk)]
    pending_d = [q for q in rows if q.get("lane") == "ctrunk" and q["donors"] != "-"]
    if pending_d and time.time() - st.get("since", 0) < 90 and ready:  # the preparer's next pass may bring them in: a short wait makes the train longer
        return
    if not pending_d:
        st.pop("since", None)
    elif "since" not in st or time.time() - st["since"] > 300:
        st["since"] = time.time()
        train_save(st)
        return
    if ready:
        train_start(st, ready)


def step():
    if train_on():
        try:
            train_tick()
        except (Exception, SystemExit) as e:  # noqa: BLE001  a train bug must not stop the other lanes
            log(f"!! train: {str(e)[:200]}")
    rows = open(FILE).read().splitlines() if os.path.exists(FILE) else []
    if train_hold():  # held ctrunk lines do not stand at the head of the other lanes' queue
        rows = [x for x in rows if not held_line(json.loads(x))]
    if diff_mode():  # 7 Nov (owner): no shared trunk to merge, tidy, rebuild or smoke: lines arm on the base + their own diffs,
        # up to bq/arm_par (default 2) at once (Builder 7 Nov: 75-140 s an arm, one at a time, was ~8 min for 5 lines); each its own trunk
        for k in [k for k, th in INFLIGHT.items() if not th.is_alive()]:
            del INFLIGHT[k]
        # 9 Nov 18:10Z (owner: use every shipcheck slot): not_started() (wait up to 3 min for the last armed line to start) guards STACKING,
        # where lines build on each other; in diff mode every line is its own trunk v live, and that wait cut arming to ~1 line per 2-3 min
        if os.path.exists(PAUSED):
            return False
        started = False
        # 9 Nov 18:15Z (owner: behaviour changes over bug fixes; shipwatch caps fix-lane checks at bq/fix_max while others wait): arm the
        # non-fix lines first (stable order within each group), so a slot never waits on a bug fix while a behaviour line is queued
        rows = sorted(rows, key=lambda x: json.loads(x).get("lane", "behaviour") == "fix")
        for x in rows:
            r = json.loads(x)
            if len(INFLIGHT) >= arm_par() or RESTART_PENDING[0]:
                break
            if r.get("flips") is None or smoke_key(r) in INFLIGHT:
                continue
            unknown = set(r) - KNOWN
            if unknown:
                log(f"waiting: line has fields this armq does not know: {sorted(unknown)}")
                break
            th = threading.Thread(target=arm_bg, args=(r, rows), daemon=True)
            INFLIGHT[smoke_key(r)] = th
            th.start()
            started = True
        return started
    if not os.path.exists(PAUSED) and not not_started() and (not rows or json.loads(rows[0])["donors"] == "-") and tidy(locked=False):
        return False  # 4 Nov: also with nothing queued, so a failed line is gone before the next donor arrives
    if rows and json.loads(rows[0])["donors"] != "-":  # first come, first served: everything waits for the head's merge, a donor-only line too (2 Nov: a bundle behind one armed on the old trunk)
        return False
    held = lambda q: train_on() and q.get("lane") == "ctrunk" and not is_train(q)  # noqa: E731  ctrunk lines ride trains, not their own arm
    r = next((json.loads(x) for x in rows if json.loads(x).get("flips") is not None and not held(json.loads(x))), None)
    if not r or r["donors"] != "-":
        return False
    unknown = set(r) - KNOWN
    if unknown:  # a field this code would drop: never arm without it
        log(f"waiting: line has fields this armq does not know: {sorted(unknown)}")
        return False
    if os.path.exists(PAUSED) or not_started():
        return False
    trunk = fastship.current_trunk()
    if not built_on_live(trunk):  # live moved on (a ship, a hand submit): re-bake the trunk from live, as shipcheck would refuse it (3 Nov)
        if WAITING[0] != ("live", trunk):
            WAITING[0] = ("live", trunk)
            rebuild([], f"{trunk} is not built on live")
        return False
    if dirty(trunk):  # failed or dead donors' code on the line: tidy() above rebuilds (once per trunk); never arm on it meanwhile
        return False
    if smoke_gate(r, rows, trunk):  # 6 Nov (sf1): outside the trunk lock (a merge never waits for a smoke); a DISASTER head left the queue
        return True
    with trunk_lock(wait=False) as free:  # never arm while a rebuild makes the next trunk (3 Nov: an arm on 12a ran mid-merge)
        if not free and not os.path.exists(MERGING):
            return False
        # 3 Nov (Builder: speed): during a plain merge the current trunk stays valid, so a line whose flags it already defines arms now
        # (a merge is ~110-230 s); arm() waits when a flag needs the donor being merged, which was the 12a failure
        return arm(r, rows)


SMOKE_SWITCH = os.path.join(Q, "armq_smoke")  # 6 Nov (sf1, owner: "batch test games ... for multiple bugs"): present = smoke the ready lines first
SMOKED = os.path.join(Q, "armq.smoked.jsonl")  # one record per line smoked (its row and verdict): a line is smoked once


def smoke_key(x):
    q = json.loads(x) if isinstance(x, str) else x
    return json.dumps(dict(flips=q.get("flips"), slug=q.get("slug"), t=q.get("t"), merged=q.get("merged")), sort_keys=True)


def smoke_gate(r, rows, trunk):
    """Before a line arms: every ready flip line on this trunk not yet smoked plays tools/lab/smokefarm.py screen v live on ONE shared fresh
    set (one pilot batch); a DISASTER line (score < .40, capped fuel > 1.5x, faults, deaths +0.3/g at z >= 2) goes to armq.failed with its
    smoke row and leaves the queue, so the bundle arms only the clean ones. Off: rm armq_smoke, or ARMQ_SMOKE=0. Any smoke failure (pilots
    down, a build error, a timeout) = no smoke: the lines arm as before, never a block. -> True when the head line r was taken off."""
    if os.environ.get("ARMQ_SMOKE", "1") == "0" or not os.path.exists(SMOKE_SWITCH):
        return False
    try:
        done = {json.loads(ln)["key"] for ln in open(SMOKED)} if os.path.exists(SMOKED) else set()
    except (OSError, ValueError, KeyError):
        done = set()
    todo = []
    for x in rows:
        q = json.loads(x)
        if q["donors"] != "-" or q.get("flips") is None or smoke_key(q) in done:
            continue
        if (q.get("slug") and dropped_recently(q["slug"])) or undefined(q["flips"], trunk):
            continue
        todo.append(q)
    if not todo or smoke_key(r) not in {smoke_key(q) for q in todo}:
        return False
    cands = [trunk + ("+" + " ".join(f"{k}={v}" for k, v in flipset(q["flips"]).items()) if flipset(q["flips"]) else "") for q in todo]
    tag = "aq" + time.strftime("%m%d%H%M%S", time.gmtime())
    js = os.path.join(Q, f".smoke_{tag}.json")
    log(f"smoke: {len(todo)} ready line(s) v live on one shared set (smokefarm --tag {tag}): " + ", ".join(q.get("slug") or q["flips"] for q in todo))
    rec = lambda q, v, rw: open(SMOKED, "a").write(json.dumps(dict(key=smoke_key(q), slug=q.get("slug"), trunk=trunk, verdict=v, row=rw,  # noqa: E731
                                                                   tag=tag, t=time.time())) + "\n")
    try:
        p = subprocess.run([sys.executable, "-I", REPO + "/tools/lab/smokefarm.py", "screen"] + cands + ["--tag", tag, "--json", js,
                           "--maps", os.environ.get("ARMQ_SMOKE_MAPS", "50")], capture_output=True, text=True, cwd=REPO,
                           timeout=int(os.environ.get("ARMQ_SMOKE_TIMEOUT", "900")))
        rows_ = json.load(open(js))["rows"] if p.returncode in (0, 3) and os.path.exists(js) else None
    except (Exception, subprocess.TimeoutExpired) as e:  # noqa: BLE001  never block arming
        p, rows_ = None, None
        log(f"smoke: not run ({str(e)[:160]}): the lines arm as before")
    if rows_ is None or len(rows_) != len(todo):
        if p is not None:
            log(f"smoke: no result (rc {p.returncode}: {(p.stdout + p.stderr).strip()[-200:]}): the lines arm as before")
        for q in todo:
            rec(q, "none", None)
        try:  # a killed run's scratch flips
            subprocess.run([sys.executable, "-I", REPO + "/tools/lab/smokefarm.py", "clean", tag], capture_output=True, text=True, cwd=REPO, timeout=120)
        except (Exception, subprocess.TimeoutExpired):  # noqa: BLE001
            pass
        return False
    head_off = False
    for q, rw in zip(todo, rows_):
        if rw.get("bot") is None:  # a build failure is the tool's, not the line's (flip.sh would refuse the arm itself): arm as before
            rec(q, "none", rw)
            continue
        rec(q, "DISASTER" if rw["disaster"] else "ok", rw)
        if rw["disaster"]:
            edit(lambda ls, q=q: [y for y in ls if json.loads(y) != q])
            fail(q, f"smoke DISASTER ({rw['why']}): score {rw['score']:.3f} [{rw['lo']:.3f}, {rw['hi']:.3f}] n{rw['n']}, faults {rw['faults']}, "
                    f"cap5 fuel {rw['fuel_c']} v {rw['fuel_l']} ({rw['fuel_ratio']:.2f}x), deaths {rw['deaths_d']:+.2f}/g z {rw['deaths_z']:+.1f}; "
                    f"table /data/USER/st/smoke/{tag}/table.txt")
            head_off = head_off or smoke_key(q) == smoke_key(r)
        else:
            log(f"smoke ok {q.get('slug') or q['flips']}: score {rw['score']:.3f} n{rw['n']}, fuel {rw['fuel_ratio']:.2f}x, faults {rw['faults']}")
    try:
        os.remove(js)
    except OSError:
        pass
    return head_off


def dropped_recently(slug, hours=24):
    """the slug's newest record is a drop within HOURS (a later 'revive' record, written by an add of the same slug, clears it)"""
    last = None
    try:
        for ln in open(DROPPED):
            d = json.loads(ln)
            if d.get("slug") == slug:
                last = d
    except (OSError, ValueError):
        pass
    return bool(last) and not last.get("revive") and time.time() - last.get("t", 0) < hours * 3600


def armed_bot(slug):
    """-> (bot, marker path, [running shipcheck pids]) for an armed, not yet live bot of this slug, else None"""
    try:
        live_names = {ln.split()[1] for ln in open(fastship.LIVE) if len(ln.split()) > 1}
    except OSError:
        live_names = set()
    # 12 Nov (Builder: jkc2 armed twice under one slug): a full bot name (nova_bNNNNN_slug) picks exactly that copy
    pat = f"{REPO}/bots/{slug}/SHIPCHECK" if re.fullmatch(r"nova_b\d+_\w+", slug) else f"{REPO}/bots/nova_b*_{slug}/SHIPCHECK"
    for p in sorted(glob.glob(pat), key=os.path.getmtime, reverse=True):
        bot = os.path.basename(os.path.dirname(p))
        if bot in live_names:
            continue
        pids = []
        for q in os.listdir("/proc"):
            if q.isdigit():
                try:
                    c = open(f"/proc/{q}/cmdline", "rb").read().split(b"\0")
                except OSError:
                    continue
                if any(x.endswith(b"shipcheck.py") for x in c) and any(bot.encode() in x for x in c):
                    pids.append(int(q))
        return bot, p, pids
    return None


INFLIGHT = {}  # diff model: smoke_key(line) -> its arm thread
RESTART_PENDING = [False]  # armq.py changed on disk: the loop restarts once INFLIGHT is empty, so step() starts no new arm
_PTK_N = [0]
ARM_RETRIED = set()  # 8 Nov: ideas re-queued once after an arm failed before its shipcheck started (not the line's own fault)


def ptk_name(r):
    """8 Nov (Builder: two slug-less lines armed in the same second both took nova_ptk_x032844; the second died in newbot.sh):
    slug + time + pid + a counter, and never a name that exists"""
    base = "nova_ptk_" + re.sub(r"[^a-z0-9]", "", (r.get("slug") or "x").lower())[:16] + time.strftime("%H%M%S", time.gmtime())
    while True:
        _PTK_N[0] += 1
        nm = f"{base}{os.getpid() % 1000:03d}{_PTK_N[0]}"
        if not os.path.lexists(os.path.join(REPO, "bots", nm)):
            return nm


def arm_par():
    try:
        return max(1, int(open(os.path.join(Q, "arm_par")).read().split()[0]))
    except (OSError, ValueError, IndexError):
        return 2


JOURNAL = os.path.join(Q, "armq_inflight")  # 11 Nov (TB 6ad907: a systemd restart mid-arm lost vcr1/vmd25i/nwb576r and jns6/rte6/sgb3r)


def _jpath(r):
    import hashlib
    return os.path.join(JOURNAL, hashlib.sha1(smoke_key(r).encode()).hexdigest()[:16] + ".json")


def arm_bg(r, rows):
    """Each line is journaled before its arm and the journal entry removed when the thread ends; a process killed mid-arm (SIGTERM,
    systemd restart, OOM) leaves it, and replay_inflight() puts the line back at start unless it was armed meanwhile."""
    jp = None
    try:
        os.makedirs(JOURNAL, exist_ok=True)
        jp = _jpath(r)
        open(jp + ".tmp", "w").write(json.dumps(dict(t=time.time(), line=r)))
        os.replace(jp + ".tmp", jp)
    except OSError as e:
        log(f"!! arm journal not written ({e}): a restart mid-arm would lose this line")
    try:
        arm(r, rows)
    except (Exception, SystemExit) as e:  # noqa: BLE001  one line's arm never stops the loop
        log(f"!! arm {r.get('slug') or r.get('flips')}: {str(e)[:200]}")
    finally:
        if jp:
            try:
                os.remove(jp)
            except OSError:
                pass


def replay_inflight():
    """At start: journaled lines whose arm never finished go back to the head of armq.txt, unless already queued, or armed after the
    journal time (an ARMED line in armq.log naming *_SLUG, or a bots/*_SLUG/SHIPCHECK marker newer than it). -> lines restored"""
    import glob as _g
    back = []
    for jp in sorted(_g.glob(os.path.join(JOURNAL, "*.json"))):
        try:
            j = json.load(open(jp))
            r, t = j["line"], j["t"]
        except (OSError, ValueError, KeyError):
            os.remove(jp)
            continue
        slug = r.get("slug") or ""
        armed = False
        if slug:
            for mk in _g.glob(f"{REPO}/bots/*_{slug}/SHIPCHECK"):
                try:
                    armed = armed or os.path.getmtime(mk) >= t - 5
                except OSError:
                    pass
            try:
                for ln in open(LOG):
                    if ln[:20] >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t - 5)) and re.search(r"ARMED nova_\S+_" + re.escape(slug) + r"\b", ln):
                        armed = True
                        break
            except OSError:
                pass
        if armed:
            log(f"journal: {slug or r.get('flips')} was armed before the restart; not restored")
        else:
            back.append(r)
        os.remove(jp)
    if back:
        def put(ls):
            have = {smoke_key(x) for x in ls}
            return [json.dumps(r) for r in back if smoke_key(r) not in have] + ls
        edit(put)
        log(f"journal: restored {len(back)} line(s) cut mid-arm by a restart: {[r.get('slug') or r.get('flips') for r in back]}")
    return len(back)


def private_plan(r, always=False):
    """7 Nov (Builder: cdw7 2475 and fk1bold 2476 both failed only the trunk-code row of the SAME shared trunk37d, sunk by another donor's
    flag-0 fuel; owner: "merge the diff in ... as if it is shipped"): -> (own donors csv or "-", live bot, [other donors on the shared trunk]).
    always=False (rolling-trunk mode): None when the shared trunk carries no donor this line lacks. The line then arms on live + its own
    donors (each DONOR:BASE a diff, applied 3-way by trunkmerge), so its trunk-code row judges its own flag-0 code only."""
    own = [d for d in (r.get("merged") or r.get("donors") or "-").split(",") if d and d != "-"]
    others = []
    if not always:
        reg = open(fastship.REGISTRY, errors="ignore").read()
        cut = [m.end() for m in re.finditer(r"^- nova_trunk\w+ REBUILT .*$", reg, re.M)]
        reg = reg[cut[-1]:] if cut else reg
        others = [d for d in (f"{a}:{b}" for a, b in line_donors(reg)) if d not in own]
        if not others:
            return None
    live = open(fastship.LIVE).readline().split()[1]
    lsrc = src_of(live)
    base = diff_base(live) if always else live
    bsrc = src_of(base) if base and base != live else None  # 9 Nov (bb8h): a donor that un-bakes a table live still has volatile is NOT shipped
    own = [d for d in own if not (in_live(d, lsrc) and (bsrc is None or contained(d, bsrc)))]
    if base is None:
        raise RuntimeError(f"no base recorded for live {live} yet (tools/lab/shipbake.py, bq/diffbase.txt, bq/shipbake.log)")
    return (",".join(own) if own else "-", base, others, live)


def arm(r, rows):
    if r.get("slug") and dropped_recently(r["slug"]):  # 6 Nov (Builder: bh65d9 was dropped at 12:39 and still armed at 12:42)
        log(f"not arming {r['slug']}: dropped by hand (armq.py drop) while it was being built; line removed")
        edit(lambda ls: [x for x in ls if json.loads(x).get("slug") != r["slug"]])
        return True
    missing = [] if diff_mode() else undefined(r["flips"], fastship.current_trunk())  # diff model: flip.sh on live + the diff decides
    if missing:
        try:  # 5 Nov: SRF_BITS needed nova_b1257_srh, which conflicts with the trunk: queue donor, FAILED, queue donor ... and every line behind it waited
            import ideastore
            ideastore.init()
            fm = json.load(open(FLAGMAP)) if os.path.exists(FLAGMAP) else {}
            need0 = list(dict.fromkeys(fm[k] for k in missing if k in fm))
            bad = ideastore.batchable(fastship.current_trunk(), need0)[1] if need0 else {}
        except (Exception, SystemExit) as e:  # noqa: BLE001
            log(f"donor conflict check not run: {str(e)[:120]}")
            bad = {}
        if bad:
            why = "; ".join(f"{d} conflicts with the trunk in {', '.join(c)}" for d, c in bad.items())
            log(f"line {r.get('slug') or r['flips']} needs a hand rebase, taken off the queue: {why}")
            edit(lambda ls: [y for y in ls if json.loads(y) != r])
            fail(r, f"needs a hand rebase: {why}")
            return False
        need, orphan = bring_donors(missing, rows)
        if WAITING[0] != ("flags", tuple(missing)):
            WAITING[0] = ("flags", tuple(missing))
            log(f"waiting: the trunk does not define {missing}" + (f"; donors {need} merge first" if need else "")
                + (f"; no donor known for {orphan}: fix the line by hand" if orphan else ""))
        return False
    pend, on, par = fastship.pending(""), None, False
    if pend and par_max() > 0:  # 3 Nov (Builder): stacked children voided whenever the parent failed (~55%): read side by side v live instead;
        # a PASS that a sibling's ship overtakes is re-read once v the new live (shipcheck reread_requeue)
        mine = set(flipset(r["flips"]))
        live_pend = [b for b, _ in pend if not os.path.exists(os.path.join(Q, f"seqext_{b}"))]  # a sequential read's extension holds no slot
        def _rare(b):
            try:
                return bool(re.search(r"^RARE=\S", open(f"{REPO}/bots/{b}/SHIPCHECK").read(), re.M))
            except OSError:
                return False
        try:  # 11 Nov ~02:25Z (owner: limit rare reads): running rare checks hold at most bq/rare_max (6) of the parallel slots
            rmax = max(0, int(open(os.path.join(Q, "rare_max")).read().split()[0]))
        except (OSError, ValueError, IndexError):
            rmax = 6
        nr = sum(1 for b in live_pend if _rare(b))
        slots = len(live_pend) - nr + min(nr, rmax)
        others = max(0, sum(1 for th in INFLIGHT.values() if th.is_alive()) - 1) if diff_mode() else 0  # arms in flight hold slots too
        # 9 Nov 19:40Z (owner: every slot used; 18 lines queued, 4 running): in diff mode each line is its own trunk v live, so a running check
        # that merely shares a FLAG NAME (Willow variants, bug bundles) is no conflict; only the same idea (the same flags AND values) waits,
        # which also stops duplicate reads. Stacking mode keeps the old any-shared-flag rule.
        same = (lambda fl: flipset(r["flips"]) == (fl or {})) if diff_mode() else (lambda fl: bool(mine & set(fl or {})))
        if slots + others >= par_max() or any(same(fl) for _, fl in pend):
            return False  # full, or a running check already reads this same idea
        par = True
    elif pend:
        on = stack_target(r["flips"], pend)
        if not on:
            return False
    priv, dm = None, diff_mode()
    if dm and not on:  # 8 Nov: a line armed with no check running had no --parallel; a sibling's check that started during its ~100 s
        par = True     # build made fastship refuse it ('another bundle's shipcheck started meanwhile', 5 in 12 h). Diff lines arm on their own trunk v live.
    if dm or (par and os.path.exists(PRIVATE_SWITCH) and os.environ.get("ARMQ_PRIVATE", "1") != "0"):
        try:
            priv = private_plan(r, always=dm)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            if dm:
                log(f"diff model: no plan for {r.get('slug') or r['flips']} ({str(e)[:160]}): line kept, tried again next round")
                return False
            log(f"private trunk plan not made ({str(e)[:120]}): arming on the shared trunk")
    clash = mcl3_clash(priv[0] if priv else (r.get("merged") or r.get("donors")))
    if clash:
        log(f"line {r.get('slug') or r['flips']} refused: MCL3 donors {clash} in one trunk (each has its own mcl3_compute copy; a merge can drop "
            f"a class bit) until the MCL3 skeleton is live: arm them as separate lines")
        edit(lambda ls: [y for y in ls if json.loads(y) != r])
        fail(r, f"MCL3 co-batch refused: {', '.join(clash)}")
        return False
    edit(lambda ls: [y for y in ls if json.loads(y) != r])
    cmd = [sys.executable, "-I", REPO + "/tools/lab/fastship.py", "-", " ".join(f"{k}={v}" for k, v in flipset(r["flips"]).items()), r["lane"],
           "--subject", r["subject"], "--arm"]  # a code-only line ('-') arms the trunk as it is (fastship: empty flips; fuels2 14:58 'bad flag')
    if priv:
        own, live_bot, others = priv[:3]
        cmd[3] = own
        pb, _, pb_base = (r.get("prebuilt") or "").partition("@")
        if pb and pb_base == live_bot and own != "-" and dm and os.path.isdir(os.path.join(REPO, "bots", pb, "src")):  # 8 Nov (owner: 5-8 min): built beside prearm's checks
            cmd += ["--trunk", live_bot, "--prebuilt", pb]
            log(f"prebuilt trunk {pb} on {pb_base}: flip and marker only")
        else:
            if pb:
                log(f"prebuilt trunk {pb} is on {pb_base}, the base is now {live_bot}: building as usual")
            cmd += ["--trunk", live_bot] + (["--private-trunk", ptk_name(r)] if own != "-" else [])
        log(f"{'diff model' if dm else 'private trunk'} for {r.get('slug') or r['flips']}: live {live_bot} + {own if own != '-' else 'no diff'}"
            + (f" (the shared trunk also carries {', '.join(others)})" if others else ""))
    cmd += ["--name", r["slug"]] if r.get("slug") else []
    cmd += ["--bugbar"] if r.get("bugbar") else []
    cmd += ["--q1bar"] if r.get("q1bar") else []
    cmd += ["--fuelx", str(r["fuelx"])] if r.get("fuelx") else []
    cmd += ["--rare", str(r["rare"])] if r.get("rare") else []
    cmd += ["--rare-fams", str(r["rarefams"])] if r.get("rarefams") else []
    cmd += ["--shadow", str(r["shadow"])] if r.get("rare") and r.get("shadow") else []
    cmd += ["--revises-live", str(r["revises"])] if r.get("revises") else []
    cmd += ["--base-has", str(r["basehas"])] if r.get("basehas") else []
    cmd += ["--class", str(r["cls"])] if r.get("cls") else []
    cmd += ["--wfams", str(r["wfams"])] if r.get("wfams") else []
    cmd += ["--confirm-from", str(r["confirm_from"]), "--confirm-n", str(r.get("confirm_n") or 1)] if r.get("confirm_from") else []  # owner 9 Nov: CONFIRM MODE marker
    cmd += ["--parambar"] if r.get("parambar") else []
    cmd += ["--seqspar"] if r.get("seqspar") else []
    cmd += ["--stack-on", on] if on else []
    cmd += ["--parallel"] if par else []
    if os.environ.get("ARMQ_DRY") == "1":
        print("DRY: " + " ".join(cmd))
        return True
    log("arming: " + " ".join(cmd[3:]))
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if priv and not dm and p.returncode and not re.search(r"another bundle's shipcheck|started meanwhile", p.stdout + p.stderr):
        log(f"private trunk arm failed ({((p.stdout + p.stderr).strip().splitlines() or [''])[-1][:160]}): arming on the shared trunk")
        own_, live_, _ = priv[:3]
        cmd = [x for x in cmd if x not in ("--trunk", "--private-trunk", live_) and not x.startswith("nova_ptk_")]
        cmd[3] = "-"  # the shared trunk, with every flag the line had (--name, --bugbar, --parallel ...)
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if dm and priv and p.returncode:  # 7 Nov (rf5all7): a ship moved live mid-build, so identity v the NEW live failed: re-plan on it, once
        now_live = open(fastship.LIVE).readline().split()[1]
        if now_live != priv[3]:
            try:
                p2 = private_plan(r, always=True)
            except (Exception, SystemExit) as e:  # noqa: BLE001
                p2 = None
                log(f"diff model: re-plan on {now_live} failed ({str(e)[:120]})")
            if p2:
                own2 = p2[0]
                cmd[3] = own2
                cmd[cmd.index("--trunk") + 1] = p2[1]
                nm = ptk_name(r)
                if "--private-trunk" in cmd:
                    i = cmd.index("--private-trunk")
                    cmd[i:i + 2] = ["--private-trunk", nm] if own2 != "-" else []
                elif own2 != "-":
                    cmd += ["--private-trunk", nm]
                if "--prebuilt" in cmd:  # the prebuilt trunk is on the old base
                    i = cmd.index("--prebuilt")
                    del cmd[i:i + 2]
                priv = p2
                log(f"diff model: live moved to {now_live} during the build: rebuilding {r.get('slug') or r['flips']} on it once")
                log("arming: " + " ".join(cmd[3:]))
                p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    line_fault = dm and p.returncode and re.search(r"conflict|refused|not defined|no flag|merge|mergecheck|identity", p.stdout + p.stderr, re.I)
    tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
    # 8 Nov: a late pilotcc line can follow fastship's ARMED line; the log showed 'rc 0: pilotcc ... ok' and talresp's arm looked lost
    armed_ln = [x for x in p.stdout.splitlines() if re.match(r"\s*ARMED \S+", x)]
    log(f"rc {p.returncode}: {(armed_ln[-1].strip() if armed_ln and not p.returncode else tail[0])[:200]}")
    if p.returncode and re.search(r"another bundle's shipcheck|started meanwhile", p.stdout + p.stderr):
        edit(lambda ls: [json.dumps(r)] + ls)  # a shipcheck got in first: wait, never drop the line
        log("put back: a shipcheck is running")
    elif line_fault:  # diff model: the line's own diff does not apply on live (or its flags are not in live + diff): back to its agent
        fail(r, "diff model: live + this line's diff did not build: " + (p.stdout + p.stderr)[-600:])
    elif p.returncode and dm and (key := f"{r.get('donors')}|{r.get('flips')}|{r.get('lane')}") not in ARM_RETRIED:
        ARM_RETRIED.add(key)  # 8 Nov (Builder): a tool failure before the shipcheck (name clash, a build hiccup) dropped the line; once more first
        edit(lambda ls: [json.dumps(r)] + ls)
        log(f"put back once: the arm failed before its shipcheck, not on the line's own diff ({tail[0][:120]})")
    elif p.returncode:
        FAILS[0] += 1
        if FAILS[0] >= 2:  # 2 Nov: a tool bug refused every arm and dropped 4 lines: two running look like the tool, not the candidate
            edit(lambda ls: [json.dumps(r)] + ls)
            open(PAUSED, "w").write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {(p.stdout + p.stderr)[-300:]}\n")
            log(f"PAUSED: two arms failed running; line kept; fix it, then remove {PAUSED}")
        else:
            fail(r, p.stdout + p.stderr)
    else:
        FAILS[0] = 0
        m = re.search(r"ARMED (\S+)", p.stdout)
        if m:
            json.dump(dict(bot=m.group(1), t=time.time()), open(LAST, "w"))
            # 5 Nov (Builder, px3 -> px3i 1445): the donors this line carried, so shipcheck's one INCONCLUSIVE re-arm queues them again
            # (it re-armed only the own flips with '-', armq then dropped the donor as unneeded and px3i was live itself)
            with open(ARMED_DONORS, "a") as f:
                f.write(json.dumps(dict(bot=m.group(1), donors=r.get("merged") or r.get("donors") or "-", t=time.time())) + "\n")
            # 9 Nov 22:15Z (Builder: mjp2k150/k200 were dropped at 22:1x while already arming; a drop only wrote a tombstone and the arms finished):
            # a line dropped WHILE it was being armed has its marker withdrawn now, as drop-armed would, before shipwatch can start it
            if r.get("slug") and dropped_recently(r["slug"], hours=1):
                mk = os.path.join(REPO, "bots", m.group(1), "SHIPCHECK")
                try:
                    os.replace(mk, mk + ".dropped")
                    log(f"dropped mid-arm: {r['slug']} was dropped while arming; {m.group(1)} marker -> SHIPCHECK.dropped (never started)")
                except OSError as e:
                    log(f"!! dropped mid-arm: {r['slug']}: could not withdraw {mk} ({e}); drop-armed it by hand")
    return True


def preparer():
    while True:
        if diff_mode():  # the diff model has no rolling trunk to merge donors into
            time.sleep(10)
            continue
        try:
            if os.path.exists(BATCH_SWITCH):
                requeue_voided()
            prepare()
        except (Exception, SystemExit) as e:  # noqa: BLE001  a library sys.exit must not end the thread
            log(f"!! prepare: {str(e)[:200]}")
        time.sleep(10)


def shipbake_tick():
    """7 Nov (owner: "when shipping, remove the switch and just have diffs instead"): diff model only, once per new live: tools/lab/shipbake.py
    bakes the shipped flag into the next base (identity v live first; bq/diffbase.txt). Off: touch bq/shipbake_OFF. bq/shipbake_last: last live."""
    if not diff_mode():
        return
    try:
        ver = open(os.path.join(Q, "live.txt")).readline().split()[0]
        p = os.path.join(Q, "shipbake_last")
        if os.path.exists(os.path.join(Q, "shipbake_OFF")) or (os.path.exists(p) and open(p).read().strip() == ver):
            return
        open(p, "w").write(ver + "\n")
        subprocess.Popen(["sh", os.path.join(REPO, "tools/lab/detach.sh"), "-l", os.path.join(Q, "shipbake.out"), f"shipbake-{ver}", "python3", "-I", "tools/lab/shipbake.py"],
                         cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"shipbake started for {ver}")
    except (OSError, IndexError) as e:
        log(f"shipbake: {e}")


SKIP_SEEN = os.path.join(Q, "armq.skipreq.json")  # shipwatch skip lines already handled
SKIP_IDEAS = os.path.join(Q, "armq.skipideas.json")  # {donors|flips|lane: re-queues done}: one per idea


def skipped_tick():
    """7 Nov (Builder: mcg3 armed on nova_base_v602, v603 shipped, shipwatch logged 'skip ...: not built on live' and the line was lost):
    diff model only: every armed candidate shipwatch skips as not built on live goes back to the FRONT of the queue with its own flips
    and donors (armed_donors.jsonl) and its marker's lane, bars and subject, so its diff re-applies on the new base. Each skip once."""
    if not diff_mode():
        return
    try:
        seen = set(json.load(open(SKIP_SEEN)))
    except (OSError, ValueError):
        seen = set()
    new = []
    try:
        for ln in open(os.path.join(Q, "shipwatch.log"), errors="replace").readlines()[-3000:]:
            m = re.match(r"(\S+ \S+) skip (nova_b\d+_\w+): not built on live", ln)
            if m and f"{m[1]} {m[2]}" not in seen:
                new.append((f"{m[1]} {m[2]}", m[2]))
    except OSError:
        return
    if not new:
        return
    import shipcheck as sc_
    for key, bot in new:
        seen.add(key)
        mk = os.path.join(REPO, "bots", bot, "SHIPCHECK")
        # 12 Nov (RC C765: fpz4s, dropped by hand at 17:01:58Z, came back 21 s later as a behaviour line without --rare, rebuilt from defaults
        # because its marker was gone): a line whose marker is gone or renamed (SHIPCHECK.dropped) was dropped on purpose: never re-queued,
        # and a re-queue never falls back to default lane / subject / bars
        if not os.path.exists(mk):
            log(f"skipped {bot}: its marker is gone{' (dropped by hand)' if os.path.exists(mk + '.dropped') else ''}: not re-queued")
            continue
        try:
            kv = dict(x.split("=", 1) for x in open(mk).read().splitlines() if "=" in x)
        except OSError:
            log(f"skipped {bot}: marker unreadable: not re-queued")
            continue
        fl = sc_.own_flip_text(bot, kv.get("LIVEVALS", ""))
        dn = sc_.armed_donors(bot)
        lane = kv.get("LANE", "behaviour")
        try:  # 12 Nov (RC C765: trua1s re-queued although its exact form had just FAILED as trua1u): the same donors + own flips FAILED since
            #      this line was armed -> not re-queued
            t_arm = os.path.getmtime(mk)
            failed = None
            for ln2 in open(os.path.join(Q, "shipwatch.log"), errors="replace").readlines()[-6000:]:
                m2 = re.match(r"(\S+ \S+) ended (nova_b\d+_\w+): FAIL", ln2)
                if not m2 or m2[2] == bot:
                    continue
                try:
                    t2 = time.mktime(time.strptime(m2[1][:19], "%Y-%m-%d %H:%M:%S")) - time.timezone
                except ValueError:
                    continue
                if t2 < t_arm:
                    continue
                o_kv = {}
                for nm in ("SHIPCHECK", "SHIPCHECK.done", "SHIPCHECK.dropped"):
                    pth = os.path.join(REPO, "bots", m2[2], nm)
                    if os.path.exists(pth):
                        o_kv = dict(x.split("=", 1) for x in open(pth).read().splitlines() if "=" in x)
                        break
                if sc_.armed_donors(m2[2]) == dn and sc_.own_flip_text(m2[2], o_kv.get("LIVEVALS", "")) == fl:
                    failed = m2[2]
                    break
            if failed:
                log(f"skipped {bot}: the same donors + flips FAILED as {failed} since it was armed: not re-queued")
                continue
        except Exception as e:  # noqa: BLE001
            log(f"skipped {bot}: fail-check error {type(e).__name__}: {e} (re-queue goes ahead)")
        if dn == "-" and not fl:
            log(f"skipped {bot}: no own flips or donors recorded: not re-queued (re-add it by hand)")
            continue
        # 7 Nov (Builder: slim1 looped slim1s -> slim1ssssssssss, a real base failure re-queued 5 times): ONE re-queue per idea,
        # keyed by its donors + own flips, not its slug; a second skip of the same idea goes to armq.failed with shipwatch's reason
        idea = f"{dn}|{fl}|{lane}"
        # 12 Nov (Builder: jkc3s, gsx32s, gopa1s, srj1s, fsq1s were stranded after their 3rd live move): the count is per idea AND live version:
        # one re-queue for each new live (an honest line re-queues on EVERY ship), while a real base failure on one live still stops at once
        try:
            idea += "|" + open(os.path.join(Q, "live.txt")).readline().split()[0]
        except (OSError, IndexError):
            pass
        try:
            cnt = json.load(open(SKIP_IDEAS))
        except (OSError, ValueError):
            cnt = {}
        if cnt.get(idea, 0) >= int(os.environ.get("ARMQ_SKIP_REQUEUE_MAX", "1")):  # per live version since 12 Nov (was 3 over all time)  # 9 Nov: 1 -> 3; ships every ~10 min, so an honest line can lose the live race twice (dcck 10236)
            why = next((ln.split("not built on live", 1)[1].strip()[:300] for ln in reversed(open(os.path.join(Q, "shipwatch.log"), errors="replace").readlines()[-3000:])
                        if f"skip {bot}:" in ln), "")
            fail(dict(donors=dn, flips=fl, lane=lane, subject=kv.get("SUBJECT", ""), slug=re.sub(r"s+$", "", re.sub(r"[^a-z0-9]", "", bot.split("_", 2)[-1]))),
                 f"skipped by shipwatch again as not built on live{(': ' + why) if why else ''}: not re-queued (one re-queue per idea); fix the diff and re-add it")
            log(f"skipped {bot} again: not re-queued (already re-queued once for {idea[:120]}); to armq.failed")
            continue
        cnt[idea] = cnt.get(idea, 0) + 1
        json.dump(cnt, open(SKIP_IDEAS, "w"))
        slug = re.sub(r"s+$", "", re.sub(r"[^a-z0-9]", "", bot.split("_", 2)[-1]))[:14] + "s"
        cmd = [sys.executable, "-I", os.path.abspath(__file__), "front", dn, fl, lane, kv.get("SUBJECT") or f"feat(trunk): {fl}"[:60], slug]
        cmd += ["--bugbar"] if kv.get("BUGBAR") == "1" and lane == "fix" else []
        cmd += ["--q1bar"] if kv.get("Q1BAR") == "1" and lane == "fix" else []
        cmd += ["--parambar"] if kv.get("PARAMBAR") == "1" else []
        cmd += ["--fuelx", kv["FUELX"]] if kv.get("FUELX") else []
        cmd += ["--rare", kv["RARE"]] if kv.get("RARE") else []
        cmd += ["--rare-fams", kv["RAREFAMS"]] if kv.get("RARE") and kv.get("RAREFAMS") else []
        cmd += ["--shadow", kv["SHADOW"]] if kv.get("RARE") and kv.get("SHADOW") else []
        cmd += ["--revises-live", kv["REVISES"]] if kv.get("REVISES") else []
        cmd += ["--base-has", kv["BASEHAS"]] if kv.get("BASEHAS") else []
        cmd += ["--class", kv["CLASS"]] if kv.get("CLASS") else []
        cmd += ["--wfams", kv["WFAMS"]] if kv.get("WFAMS") else []
        cn = (int(kv["CONFIRM_N"]) if kv.get("CONFIRM_N", "").isdigit() else 1) + 1
        if kv.get("CONFIRM_FROM") and cn <= 2:  # a CONFIRM marker skipped as live moved before its start: still that chain, one more live move (as shipwatch's rebase)
            cmd += ["--confirm-from", kv["CONFIRM_FROM"], "--confirm-n", str(cn)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        log(f"skipped {bot} (live moved before its shipcheck): re-queued at the front as {slug}: rc {r.returncode} {(r.stdout + r.stderr).strip()[-160:]}")
    json.dump(sorted(seen)[-2000:], open(SKIP_SEEN, "w"))


def rescreen_tick():
    """7 Nov (owner: keep features that show positives): once per new live, the failed-positive bank's top entries are screened on it
    (flagscreen.py bank rescreen: one factorial run at the lowest pilot priority).
    11 Nov (owner: "some ideas do improve, what do we do about that"): a live whose trigger met a running bank screen is retried once that
    screen ends (it used to be marked done: v755 and v756 got no screen while bk754 ran), and an IDLE pipeline (no armq line, no shipcheck,
    none started for 20 min) starts one too, at most every 60 min, so idle compute goes to the bank.
    Off: touch bq/bankrescreen_OFF. bq/bankrescreen_last: the last live a screen was started for; bq/bankrescreen_started: its time."""
    try:
        if os.path.exists(os.path.join(Q, "bankrescreen_OFF")):
            return
        for pc in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                c = open(pc).read().split("\0")
            except OSError:
                continue
            if any(x.endswith("flagscreen.py") for x in c) and "drive" in c and any(x.startswith("bk") for x in c):
                return  # a bank screen runs: try again after it ends (the live is not marked)
        ver = open(os.path.join(Q, "live.txt")).readline().split()[0]
        p, ps = os.path.join(Q, "bankrescreen_last"), os.path.join(Q, "bankrescreen_started")
        last = open(p).read().strip() if os.path.exists(p) else ""
        why = "new live"
        if last == ver:
            now = time.time()
            started = os.path.getmtime(ps) if os.path.exists(ps) else 0
            queued = os.path.exists(os.path.join(Q, "armq.txt")) and open(os.path.join(Q, "armq.txt")).read().strip()
            sw = [ln for ln in open(os.path.join(Q, "shipwatch.log"), errors="replace").readlines()[-400:] if " start " in ln]
            last_start = __import__("calendar").timegm(time.strptime(sw[-1][:20], "%Y-%m-%d %H:%M:%SZ")) if sw else 0
            running = subprocess.run(["pgrep", "-fc", "[s]hipcheck.py"], capture_output=True, text=True).stdout.strip() not in ("", "0")
            if queued or running or now - last_start < 1200 or now - started < 3600:
                return
            why = "idle pipeline"
        open(p, "w").write(ver + "\n")
        open(ps, "w").write(f"{why}\n")
        subprocess.Popen(["sh", os.path.join(REPO, "tools/lab/detach.sh"), "-l", os.path.join(Q, "bankrescreen.out"), f"bankrescreen-{ver}-{int(time.time())}", "python3", "-I",
                          "tools/lab/flagscreen.py", "bank", "rescreen", "--top", "8"], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"bank rescreen started for {ver} ({why})")
    except (OSError, IndexError, ValueError) as e:
        log(f"bank rescreen: {e}")


def diff_base(live):
    """the base recorded for LIVE (bq/diffbase.txt, written by shipbake after its identity check), else LIVE itself while that bake is
    pending or after it failed. Owner 7 Nov ~18:00Z: shipping must never wait on the bake; a switch a live-built candidate carries is
    baked by the next base anyway (shipbake's ledger is cumulative)."""
    try:
        a = open(os.path.join(Q, "diffbase.txt")).readline().split()
        if len(a) > 1 and a[0] == live and a[1] != "-" and (a[1] == live or os.path.isdir(os.path.join(REPO, "bots", a[1], "src"))):
            return a[1]
    except OSError:
        pass
    return live


def reline_tick():
    """Once per new live: tools/lab/reline.py builds the next nova_cbase trunk with live's flags as defaults (6 Nov; it publishes only after identity v live).
    Off: touch bq/reline_OFF. bq/reline_last is the last live it was started for."""
    try:
        ver = open(os.path.join(Q, "live.txt")).readline().split()[0]
        p = os.path.join(Q, "reline_last")
        if os.path.exists(os.path.join(Q, "reline_OFF")) or (os.path.exists(p) and open(p).read().strip() == ver):
            return
        open(p, "w").write(ver + "\n")
        subprocess.Popen(["sh", os.path.join(REPO, "tools/lab/detach.sh"), "-l", os.path.join(Q, "reline.out"), f"reline-{ver}", "python3", "-I", "tools/lab/reline.py"], cwd=REPO,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"reline started for {ver}")
    except (OSError, IndexError) as e:
        log(f"reline: {e}")


def main():
    a = sys.argv[1:]
    if a[:1] == ["add"]:
        return add(a[1:])
    if a[:1] == ["rebuild"]:  # rebuild [DONOR:BASE,...] "why": the Builder's call
        keep = [x for x in (a[1].split(",") if len(a) > 2 else []) if x]
        return print("ok" if rebuild(keep, a[-1] if len(a) > 1 else "by hand") else "failed: see armq.log")
    if a[:1] == ["front"]:  # a void stacked bundle keeps its place (shipcheck.py)
        # 9 Nov 19:40Z (Builder: wgl4r/wglmr were re-queued while a hand wglmc of the same idea was queued; 4 Willow lines ran): a re-queue
        # of donors + flips + lane already waiting in the queue is skipped
        if len(a) >= 4 and os.path.exists(FILE):
            for ln in open(FILE):
                try:
                    q = json.loads(ln)
                except ValueError:
                    continue
                if (q.get("donors"), q.get("lane")) == (a[1], a[3]) and flipset(q.get("flips") or "") == flipset(a[2]):
                    # 11 Nov (TB, lah1i 12557: a PASS refused for base asked for its CONFIRM re-read while lah1r, a plain capacity
                    # re-arm of the same idea, waited; the confirm was dropped and a full 3,300-map read ran instead): carry the
                    # confirm onto the waiting line
                    if "--confirm-from" in a and not q.get("confirm_from"):
                        i = a.index("--confirm-from")
                        cf = a[i + 1]
                        cn = a[a.index("--confirm-n") + 1] if "--confirm-n" in a else "1"
                        slug = q.get("slug")

                        def up(ls, slug=slug, cf=cf, cn=cn):
                            out = []
                            for x in ls:
                                try:
                                    r = json.loads(x)
                                except ValueError:
                                    out.append(x)
                                    continue
                                if r.get("slug") == slug and not r.get("confirm_from"):
                                    r.update(confirm_from=cf, confirm_n=cn)
                                    x = json.dumps(r)
                                out.append(x)
                            return out
                        edit(up)
                        log(f"front: the same idea is queued as {slug}: gave it CONFIRM_FROM={cf} (confirm read, not a full one)")
                        return print(f"merged: {slug} now carries --confirm-from {cf}")
                    log(f"front: skipped, the same idea is already queued as {q.get('slug') or q.get('flips')}")
                    return print(f"skipped: the same donors/flips/lane is already queued ({q.get('slug')})")
        return add(a[1:], True)
    if a[:1] == ["donor"] and len(a) == 2:
        row = json.dumps(dict(donors=a[1], flips=None, t=time.time()))
        edit(lambda ls: ls + [row])
        return print(f"queued donor {a[1]}")
    if a[:1] == ["fuelbank"]:
        return fuelbank(a[1:])
    if a[:1] == ["drop"] and len(a) == 2:  # 3 Nov (Builder): remove a waiting line by slug; never the line being merged now
        mg = open(MERGING).read() if os.path.exists(MERGING) else ""
        hit = []

        def rm(ls):
            for x in ls:
                if json.loads(x).get("slug") == a[1] and x.strip() != mg.strip() and not (mg.strip() and a[1] in (json.loads(mg).get("slugs") or [])):
                    hit.append(x)
                    return [y for y in ls if y is not x]
            return ls
        edit(rm)
        with open(DROPPED, "a") as f:  # a tombstone: a line already merging or arming is not armed after all
            f.write(json.dumps(dict(slug=a[1], t=time.time())) + "\n")
        if hit:
            log(f"dropped by hand: {hit[0].strip()[:200]}")
            print(f"dropped {a[1]}")
        elif a[1] in mg:
            log(f"drop {a[1]}: being merged now; it will not be armed (tombstone)")
            print(f"{a[1]} is being merged now: it will not be armed (tombstone in {DROPPED})")
        ab = armed_bot(a[1])
        if ab:
            bot, mk, pids = ab
            log(f"drop {a[1]}: already armed as {bot} (marker {mk}, shipcheck pids {pids or 'none'})")
            print(f"{a[1]} is already ARMED as {bot}: marker {mk}" + (f", shipcheck running (pid {', '.join(map(str, pids))})" if pids else "")
                  + ". To stop it: python3 -I tools/lab/armq.py drop-armed " + a[1])
        elif not hit and a[1] not in mg:
            print(f"no waiting line has slug {a[1]} (tombstone written: it will not be armed)")
        return
    if a[:1] == ["train"]:  # state of the ctrunk train
        st = train_load()
        r_ = st.get("running")
        le = st.get("last_end")
        print(f"cadence {train_every():g} min; " + (f"held for {max(0, le + train_every() * 60 - time.time()) / 60:.0f} min more; " if le and train_hold() else "") + ("armq_train_now set; " if os.path.exists(TRAIN_NOW) else ""))
        print(f"train mode {'on' if train_on() else 'off'}; last train {st.get('n', 0)}; running: "
              + (f"{r_['slug']} {r_.get('bot') or '(arming)'}: " + ", ".join(q.get("slug") or "?" for q in r_["lines"]) if r_ else "none"))
        for g in st.get("groups", []):
            print("  next: " + ", ".join(q.get("slug") or "?" for q in g))
        return
    if a[:1] == ["drop-armed"] and len(a) == 2:  # 6 Nov: stop an armed, not yet submitted bot: marker renamed, its shipcheck signalled
        ab = armed_bot(a[1])
        with open(DROPPED, "a") as f:
            f.write(json.dumps(dict(slug=a[1], t=time.time())) + "\n")
        if not ab:
            return print(f"no armed, unsubmitted bot for slug {a[1]}")
        bot, mk, pids = ab
        os.replace(mk, mk + ".dropped")
        import signal
        legs = []  # 10 Nov: the scope's other processes naming this bot, read BEFORE the shipcheck exits (its /proc entry goes with it)
        for pid in pids:
            try:
                cg = open(f"/proc/{pid}/cgroup").read().strip().split("::", 1)[-1]
                for q in open(f"/sys/fs/cgroup{cg}/cgroup.procs").read().split():
                    if int(q) not in pids and bot in open(f"/proc/{q}/cmdline").read().replace("\0", " "):
                        legs.append(int(q))
            except (OSError, ValueError):
                pass
        for pid in pids:  # only shipcheck.py processes whose command line names this bot (checked in armed_bot)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for q in legs:  # 10 Nov (fsb1/fsb2: their stylepanel legs outlived the SIGTERMed shipcheck): each leg cancels its own pilot batch
            try:
                os.kill(q, signal.SIGTERM)
            except OSError:
                pass
        fb = []
        try:  # 10 Nov (Builder: x5id passed and was BATCHED at 10:13Z, dropped at 10:17Z: the batch still held it): a batched pass goes too
            import fixbatch
            fb = [e for e in fixbatch.entries() if e["bot"] == bot or re.fullmatch(r"nova_b\d+_" + re.escape(a[1]) + r"[a-z0-9_]*", e["bot"])]
            if fb:
                fixbatch.remove_entries(fb)
                fixbatch.log(f"DROPPED {', '.join(e['bot'] for e in fb)} (armq drop-armed {a[1]})")
        except Exception as e:  # noqa: BLE001  the drop itself must not fail on the batch
            log(f"!! drop-armed {a[1]}: fixbatch not checked ({e!r})")
        log(f"drop-armed {a[1]}: {bot} marker -> SHIPCHECK.dropped; shipcheck pids signalled: {pids or 'none'}"
            + (f"; fixbatch entries removed: {', '.join(e['bot'] for e in fb)}" if fb else ""))
        return print(f"stopped {bot}: marker renamed to SHIPCHECK.dropped" + (f"; SIGTERM to shipcheck pid {', '.join(map(str, pids))}" if pids else ""))
    if a[:1] == ["promote"] and len(a) == 2:  # 3 Nov (Builder): queue order, e.g. a gain candidate behind fix lines
        hit = []

        def mv(ls):
            i = next((k for k, x in enumerate(ls) if json.loads(x).get("slug") == a[1]), None)
            if i is None:
                return ls
            hit.append(ls[i])
            return [ls[i]] + ls[:i] + ls[i + 1:]
        edit(mv)
        return print(f"promoted {a[1]} to the head" if hit else f"no waiting line has slug {a[1]}")
    if a[:1] == ["list"]:
        print(open(FILE).read() if os.path.exists(FILE) else "", end="")
        try:  # owner 5 Nov: which queued ideas fight, before anyone arms them (in memory, no build)
            import ideastore
            ideastore.init()
            ds = ideastore.queued_donors()
            if len(ds) > 0:
                print("conflicts: " + ("; ".join(ideastore.conflicts(fastship.current_trunk(), ds)) or "none"))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"conflicts: not checked ({str(e)[:100]})")
        return None
    if a[:1] == ["--once"]:
        return print(step())
    if a[:1] == ["--loop"]:
        open(PID, "w").write(f"{os.getpid()}\n")
        log(f"armq start pid {os.getpid()}")
        try:
            replay_inflight()
        except Exception as e:  # noqa: BLE001
            log(f"!! journal replay failed: {str(e)[:200]}")
        threading.Thread(target=preparer, daemon=True).start()
        threading.Thread(target=releaser, daemon=True).start()
        me = os.path.abspath(__file__)
        born = os.path.getmtime(me)
        while True:
            busy = [k for k, th in INFLIGHT.items() if th.is_alive()]  # 8 Nov (Builder): an exec mid-arm dropped rcx silently (no marker, no line)
            RESTART_PENDING[0] = os.path.getmtime(me) != born  # 11 Nov (TB 6ad907: 01:45-01:52 the wait never ended): no NEW arms meanwhile
            if RESTART_PENDING[0] and busy and not getattr(main, "_wait_logged", False):
                log(f"armq.py changed: restart waits for {len(busy)} arm(s) in flight (no new arms start meanwhile)")
                main._wait_logged = True
            if os.path.getmtime(me) != born and not busy:  # 2 Nov: a line's new field (parambar) was dropped by a daemon running older code: reload, between steps
                with trunk_lock(wait=False) as free:  # never mid-merge: the merge's queue edit would be lost (3 Nov)
                    if free:
                        log("armq.py changed: restarting on the new code")
                        os.execv(sys.executable, [sys.executable, "-I", me, "--loop"])
            reline_tick()
            shipbake_tick()
            rescreen_tick()
            try:  # 11 Nov (owner: better + faster iterations): every 5 ships, live v live-5 on new fresh maps, information only (shipaudit.py)
                subprocess.Popen([sys.executable, "-I", os.path.join(REPO, "tools/lab/shipaudit.py"), "tick"], cwd=REPO,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                log(f"shipaudit tick: {e}")
            try:
                skipped_tick()
            except (Exception, SystemExit) as e:  # noqa: BLE001
                log(f"!! skipped_tick: {str(e)[:200]}")
            try:
                step()
            except (Exception, SystemExit) as e:  # noqa: BLE001  the queue must outlive one bad line, incl. a library sys.exit (4 Nov)
                tb = traceback.extract_tb(e.__traceback__)[-4:]  # 3 Nov (Builder): where, not only what
                log(f"!! {str(e)[:200]} [at " + " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(tb)) + "]")
            time.sleep(20)
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
