#!/usr/bin/env python3
"""Condor pilot pool for condab.py (owner approved 30 Oct ~12:45 UTC: cut the daytime Condor queue wait).

Why: a condab game costs ~4 CPU-s and a full 1272-game h2h runs in ~2 min once slots are held, but by day a fresh cluster
waits 10-23 min in the Condor queue. Pilots are long-lived Condor jobs (12 cpus, like condab's jobs) that pull condab's job
parts from a queue directory on the shared home and run exactly what a normal job runs (sh condab_node.sh PART PAR ...).

Queue (QDIR = /homes/USER/condor-runs/pilotq, shared with the execute nodes over NFS):
  queue/PPP_TTTTTTTTTTTTT_BID_NNNN   an item (JSON: run dir, part index, node args). PPP = 500 - priority, so a plain sort
                                      gives the highest priority first, then the oldest; BID = the batch id, NNNN = part.
  claimed/ITEM.PILOT                 claimed by an atomic rename; the pilot touches it every HB s (its lease). A lease older
                                      than LEASE s (a pilot died, was evicted or suspended) is renamed back into queue/.
  done/ITEM.PILOT                    finished (kept 1 h for --status).
  cancel/BID                         condab stopped the batch: its queued items are deleted, running ones killed.
  pilots/PILOT                       each running pilot's heartbeat (JSON, rewritten every HB s).
  pilotd.hb, demand                  manager heartbeat; condab touches demand on every batch (pilot path or not).
  logs/                              one log per pilot (pruned after 24 h).
Times are compared as NFS server mtimes against a freshly touched clock file, never across node clocks. Directory listings
are refreshed by creating and deleting a dummy file in the dir (NFSv3 attribute caching would hide new names up to 60 s).

PRIORITY RULES (30 Oct 20:25, Builder): batch ids matching PILOT_BOOST (default: driftv2, shipcheck's lh / lx / anN / pcN / plN / fpN legs, N its tag) move to
key 001, PILOT_DEMOTE (default: sweepd's sws / swl / swx / swc / swd) to key 900; small batches (below) still go first.
SMALL BATCHES FIRST (Builder 30 Oct: 2-4-item mechanism KEEPs at priority -5 waited 30+ min behind 1,300-game runs): the
manager renames the queued items of every batch with <= PILOT_SMALL (6) items left (queued + claimed) to key 000, so pilots
(old code or new: they claim in name order) take them before any normal priority, oldest first. Status shows them as 'small'.

A pilot writes its part's output to RUN/job_pNNNN.out (written to .tmp, then renamed), in the runner.sh format condab's
collect() reads ("CQ {..}" lines, "## end"). It exits after PILOT_IDLE s without work or PILOT_MAX_LIFE s.

usage: pilotd.py            the manager loop: keeps PILOT_N pilots submitted while work is queued or was in the last
                            DEMAND_WINDOW s, none otherwise (idle never-started pilots are removed); requeues dead leases.
       pilotd.py --status   pilots alive, items queued / claimed / done
       pilotd.py --pilot    a pilot (the Condor job body)
Log /data/USER/st/bq/pilot.log, pid /data/USER/st/bq/pilotd.pid. Stop: kill $(cat /data/USER/st/bq/pilotd.pid)
(running pilots exit on idle within PILOT_IDLE s). condab.py: CONDAB_PILOT=0 disables the pilot path.
"""
import glob
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

QDIR = os.environ.get("PILOT_QDIR", "/homes/USER/condor-runs/pilotq")
NODE = os.environ.get("PILOT_NODE", "/homes/USER/cambc/tools/lab/condab_node.sh")  # PILOT_NODE: tests only
LOG = os.environ.get("PILOT_LOG", "/data/USER/st/bq/pilot.log")
PIDF = os.environ.get("PILOT_PIDF", "/data/USER/st/bq/pilotd.pid")
PILOT_N = int(os.environ.get("PILOT_N", 4))
# AUTOSCALE (30 Oct, iteration-speed): PILOT_N pilots while work is queued; with a deep queue (> PILOT_DEPTH x PILOT_N items) up to
# PILOT_MAX (default PILOT_N: off) when the pool has free 12-cpu slots (night), never more than half of them; PILOT_MIN when
# the queue is empty but demand is recent (running pilots also leave on their own after PILOT_IDLE s).
PILOT_MAX = int(os.environ.get("PILOT_MAX", PILOT_N))
PILOT_MIN = int(os.environ.get("PILOT_MIN", min(4, PILOT_N)))
# EASY HOURS (owner 6 Nov via the Builder: use Condor more at night): between PILOT_NIGHT's hours UTC (default 20-7), or with >= PILOT_FREE_EASY free slots, grow from
# > PILOT_DEPTH_NIGHT x PILOT_N queued (day PILOT_DEPTH 2: a 40-item batch stayed on 20 pilots, two rounds of ~6 min) toward one pilot per PILOT_PER_NIGHT queued items
# (day PILOT_PER 2), and keep unstarted pilots PILOT_HOLD s after the queue drops (1 s items drained 631 queued in 16 s; 31 pilots were submitted and removed). Free slots still cap it all.
NIGHT = os.environ.get("PILOT_NIGHT", "20-7")
DEPTH, DEPTH_NIGHT = float(os.environ.get("PILOT_DEPTH", 2)), float(os.environ.get("PILOT_DEPTH_NIGHT", 0.5))
PER, PER_NIGHT = float(os.environ.get("PILOT_PER", 2)), float(os.environ.get("PILOT_PER_NIGHT", 1))
FREE_EASY, HOLD_S = int(os.environ.get("PILOT_FREE_EASY", 30)), int(os.environ.get("PILOT_HOLD", 180))
FREE_FRAC = float(os.environ.get("PILOT_FREE_FRAC", "0.5"))  # share of the pool's free slots autoscale may take (owner 30 Oct 22:25: "give Condor as much as possible" at night)
PILOT_IDLE = int(os.environ.get("PILOT_IDLE", 120))  # 2 Nov: 600 held slots from direct jobs after the queue emptied
TMP_MIN_MB = int(os.environ.get("PILOT_TMP_MIN_MB", 2000))  # free /tmp a pilot needs before it claims an item (01 Nov, gpu32)
PILOT_MAX_LIFE = int(os.environ.get("PILOT_MAX_LIFE", 4 * 3600))
RETIRE = 1200          # a pilot this close to its end of life is replaced early (no gap while its successor queues)
DEMAND_WINDOW = 600    # keep pilots while work was queued this recently
HB, LEASE, ALIVE = 20, 180, 90
BOOST_RE = os.environ.get("PILOT_BOOST", r"^cq-(driftv2|lh|lx|an[0-9]|p[cl][0-9]|fp[0-9]|dp[0-9])")  # 9 Nov 18:15Z: + shipcheck draft-probe batches (dpTAG, 1-round games)  # batch ids moved to key 001 (just behind small batches)
DEMOTE_RE = os.environ.get("PILOT_DEMOTE", r"^cq-sw[slxcd][0-9]")  # batch ids moved to key 900 (behind every normal priority)
PAR_MAX, GAME_MB = 48, 100  # an item holds at most 48 games (condab.py); 100 MB a game leaves room over the measured 65
SMALL_N = int(os.environ.get("PILOT_SMALL", 2))  # a batch with this many items or fewer left jumps the queue (0 = off)
AGE_S = int(os.environ.get("PILOT_AGE_S", 900))  # 2 Nov (Builder): killgate items at priority 0 waited 43 min behind a stream of newer priority-10 legs
FAVOUR = os.environ.get("PILOT_FAVOUR", "/data/USER/st/bq/pilot_favour.txt")  # one batch-name regex a line
AGE_KEY = 489  # 500 - priority: behind shipcheck's panel at 12 (488), ahead of agents' legs at 10 (490)
AGE_OLD_KEY = 490  # 7 Nov: where an aged priority-0 item goes (level with priority 10, behind 11 and 12); AGE_KEY stays for FAVOUR batches
BOOST_KEY = 0  # queue key 000: before every normal priority (enqueue keys are 500 - priority, clamped to 0..999)
GONE_AFTER = 900       # a run dir still unseen when its item is this old (s) really is gone: the item is dropped
ITEM_TIMEOUT = 2400    # a part running longer is killed and dropped (condab's straggler rule handles the batch)
CPUS, MEM = int(os.environ.get("PILOT_CPUS", 8)), 10000  # 30 Oct 20:20: 8 (was 12) fits the pool's 8-cpu slots and 3 per 24-cpu slot; items still run 12 games at once
CONDOR_PRIO = 10       # orders only our own queued jobs: pilots before our other jobs
BATCH_NAME = "cq_pilots"
CONDOR_ENV = dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", ""))


def cenv():
    """CONDOR_ENV with a live Kerberos ticket cache (30 Oct 18:07-20:15: the cache this manager was started with was replaced
    when its session renewed, every condor_q failed, and no pilot was submitted for 2 h): when KRB5CCNAME's file is gone,
    use the newest /tmp/krb5cc_<uid>_* file."""
    import glob
    cc = CONDOR_ENV.get("KRB5CCNAME", "")
    path = cc[5:] if cc.startswith("FILE:") else cc
    if path and os.path.exists(path):
        return CONDOR_ENV
    files = sorted(glob.glob(f"/tmp/krb5cc_{os.getuid()}_*"), key=os.path.getmtime)
    if files:
        CONDOR_ENV["KRB5CCNAME"] = "FILE:" + files[-1]
        log(f"Kerberos ticket cache {path or '(none)'} is gone: now using {files[-1]}")
    return CONDOR_ENV
HOST = re.sub(r"[^A-Za-z0-9]", "", socket.gethostname().split(".")[0]) or "host"
SUBDIRS = ("queue", "claimed", "done", "cancel", "pilots", "logs")


def q(*p):
    return os.path.join(QDIR, *p)


def ensure():
    for d in SUBDIRS:
        os.makedirs(q(d), exist_ok=True)


def poke(d):
    """Force this client to re-read directory d: our own create/delete makes the NFS client see the server's newer mtime."""
    p = os.path.join(d, f".poke.{HOST}.{os.getpid()}")
    try:
        os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o644))
        os.unlink(p)
    except OSError:
        pass


def ls(d):
    poke(d)
    try:
        return sorted(x for x in os.listdir(d) if not x.startswith("."))
    except FileNotFoundError:
        return []


def mtime(p):
    """The server's mtime of p, revalidated (open() does close-to-open GETATTR); None when p is gone."""
    try:
        fd = os.open(p, os.O_RDONLY)
    except OSError:
        return None
    try:
        return os.fstat(fd).st_mtime
    except OSError:  # 13 Nov (TB, 14783 cys768 live h2h died: ESTALE, the heartbeat file was replaced over NFS between open and fstat): gone
        return None
    finally:
        os.close(fd)


def now():
    """The NFS server's clock: touch our clock file and read its mtime back (node clocks may differ)."""
    p = q(f".clock.{HOST}")
    try:
        os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o644))
        os.utime(p)  # times=None: NFSv3 SETATTR with SET_TO_SERVER_TIME
        return mtime(p) or time.time()
    except OSError:
        return time.time()


def touch(p):
    try:
        os.utime(p)
        return True
    except OSError:
        return False


def parse(name):
    """queue/claimed/done name -> (prio key, enqueue ms, batch id, part index, pilot or None)."""
    base, _, pil = name.partition(".")
    f = base.split("_")
    if len(f) == 5 and f[4] == "g":  # a generic item (own script, 4 Nov): pilots older than that skip 5-field names
        f = f[:4]
    if len(f) != 4:
        return None
    try:
        return int(f[0]), int(f[1]), f[2], int(f[3]), (pil or None)
    except ValueError:
        return None


def log(msg, path=None):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}\n"
    try:
        with open(path or LOG, "a") as f:
            f.write(line)
    except OSError:
        sys.stderr.write(line)


# ---------------------------------------------------------------- condab side
def demand():
    """condab calls this on every batch: work is about, so pilotd keeps (or starts) pilots for the next batches."""
    try:
        ensure()
        p = q("demand")
        os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o644))
        os.utime(p)
    except OSError:
        pass


def alive_pilots():
    """Heartbeats of running pilots (fresh within ALIVE s): [{pilot, host, item, retiring, ...}]."""
    t, out = now(), []
    for n in ls(q("pilots")):
        m = mtime(q("pilots", n))
        if m is not None and t - m < ALIVE:
            try:
                with open(q("pilots", n)) as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = {}
            d["pilot"] = n
            out.append(d)
    return out


def batch_id(run):
    tag = re.sub(r"[^A-Za-z0-9-]", "-", os.path.basename(os.path.dirname(run.rstrip("/"))) or "batch")[-40:]
    return f"{tag}-{os.urandom(3).hex()}"


def enqueue(run, items, prio, node=None):
    """items: [(part index, [node args])]. -> batch id. Each item is written to a dot-file and renamed into queue/.
    NODE: a script the pilot runs instead of condab_node.sh (`sh NODE ARGS`; args[1] is the parallelism, fitted to the slot), e.g.
    freshjobs' map-set builds (4 Nov: as separate Condor jobs they waited behind our own pilots)."""
    ensure()
    os.makedirs(run, exist_ok=True)
    bid, key, ms = batch_id(run), max(0, min(999, 500 - int(prio))), int(time.time() * 1000)
    for idx, args in items:
        name = f"{key:03d}_{ms:013d}_{bid}_{idx:04d}" + ("_g" if node else "")
        tmp = q("queue", f".{name}.tmp")
        with open(tmp, "w") as f:
            json.dump(dict(bid=bid, idx=idx, run=run, args=[str(a) for a in args], prio=int(prio), t=time.time(),
                           **({"node": node} if node else {})), f)
        os.rename(tmp, q("queue", name))
    return bid


def heal(bids, run, items, prio, st):
    """Call about once a minute while a batch waits; items as for enqueue. 2 Nov (gate 7981): an item can leave the queue with no output (a pilot that
    did not see a new run dir yet threw 125 items away in 3 s, and the batch then waited 82 min for nothing). With nothing queued or claimed on two looks
    in a row and parts unfinished, those parts are queued again, at most st["max"] times. st: this batch's state dict. -> (new batch id or None, parts)."""
    poke(q("queue"))
    poke(q("claimed"))
    poke(run)
    if any((parse(n) or (0, 0, ""))[2] in bids for n in ls(q("queue")) + ls(q("claimed"))):
        st["empty"] = 0
        return None, 0
    st["empty"] = st.get("empty", 0) + 1
    if st["empty"] < 2 or st.get("times", 0) >= st.get("max", 2):
        return None, 0
    done = done_parts(run)
    lost = [it for it in items if it[0] not in done]
    if not lost:
        return None, 0
    st["empty"] = 0
    st["times"] = st.get("times", 0) + 1
    return enqueue(run, lost, prio), len(lost)


def promote_small():
    """Rename the queued items of batches with <= SMALL_N items left (queued + claimed) to key BOOST_KEY. -> items moved.
    A pilot racing for the same item wins or loses the rename atomically; the loser skips it."""
    if SMALL_N <= 0:
        return 0
    poke(q("queue"))  # NFS: refresh the listings first (the manager's view was 0 queued with 54 there, 30 Oct)
    poke(q("claimed"))
    queued = ls(q("queue"))
    left = {}
    for n in queued + ls(q("claimed")):
        p = parse(n)
        if p:
            left[p[2]] = left.get(p[2], 0) + 1
    moved = 0
    try:
        fav = "|".join(x.strip() for x in open(FAVOUR) if x.strip() and not x.startswith("#"))
        fav = re.compile(fav) if fav else None
    except (OSError, re.error):
        fav = None
    for n in queued:  # 30 Oct 20:25 (Builder): rollback / shipcheck legs first, sweeps last, by batch id
        p = parse(n)
        if not p or p[0] == BOOST_KEY:
            continue
        key = None
        if fav and AGE_KEY < p[0] and fav.search(p[2]):
            key = AGE_KEY  # the Builder's pipeline-deciding runs: ahead of gate legs, still behind a shipcheck's
        elif AGE_S and p[0] == 500 and time.time() - p[1] / 1000 > AGE_S:
            key = AGE_OLD_KEY  # a priority-0 item that waited AGE_S: level with agents' priority-10 legs (490), never above a priority 11 read.
            # 7 Nov: the old rule lifted EVERY item at priority 0-10 to 489 after 15 min: ~1,600 aged screen items (priority 9) then sat
            # level with readmany's priority-11 items in age order, and Deep's 550-game read timed out at 1,800 s ("job lost").
        elif DEMOTE_RE and re.search(DEMOTE_RE, p[2]) and p[0] != 900:
            key = 900
        elif BOOST_RE and re.search(BOOST_RE, p[2]) and p[0] > (2 if p[2].startswith("cq-lh") else 1):
            key = 2 if p[2].startswith("cq-lh") else 1  # 11 Nov ~00:30Z: BIG legs stay at 002 (boost_ships); this rule had lifted them back to 001
        if key is not None and (key in (AGE_KEY, AGE_OLD_KEY) or left.get(p[2], 0) > SMALL_N):  # note: the age keys apply to every size
            try:
                os.rename(q("queue", n), q("queue", f"{key:03d}_" + n.split("_", 1)[1]))
                moved += 1
            except OSError:
                pass
            continue
    for n in ls(q("queue")):
        p = parse(n)
        if not p or p[0] == BOOST_KEY or left.get(p[2], 0) > SMALL_N:
            continue
        try:
            os.rename(q("queue", n), q("queue", f"{BOOST_KEY:03d}_" + n.split("_", 1)[1]))
            moved += 1
        except OSError:
            pass  # a pilot claimed it meanwhile
    return moved


_DONE = {}  # run -> part indices already seen complete: an output is renamed in whole and stays, so each is read once (a look read every file)


def done_parts(run):
    """Part indices whose pilot output (RUN/job_pNNNN.out) is complete."""
    out = _DONE.setdefault(run, set())
    try:
        names = os.listdir(run)
    except OSError:
        return set(out)  # 2 Nov: a failed listing read as nothing back (shipcheck 1071: "0/67 jobs done")
    for n in names:
        m = re.fullmatch(r"job_p(\d+)\.out", n)
        if m and int(m.group(1)) not in out:
            try:
                if "## end" in open(os.path.join(run, n), errors="replace").read():
                    out.add(int(m.group(1)))
            except OSError:
                pass
    return set(out)


def cancel(bid):
    """Stop a batch: mark it cancelled (running items are killed by their pilots) and delete its queued items.
    -> (queued items removed, items running)."""
    ensure()
    try:
        open(q("cancel", bid), "w").close()
    except OSError:
        pass
    nq = 0
    for n in ls(q("queue")):
        p = parse(n)
        if p and p[2] == bid:
            try:
                os.unlink(q("queue", n))
                nq += 1
            except OSError:
                pass
    nr = sum(1 for n in ls(q("claimed")) if (parse(n) or (0, 0, ""))[2] == bid)
    return nq, nr


def reap_orphans(min_age=120, say=None, dry=False):
    """7 Nov (Builder: 3,301 queued items, 13 pilots): cancel queued batches of cxefarm runs whose caller is dead. cxefarm names its
    stage dir cf_<caller pid>_<ns>; a caller killed by a signal skips its own cancel (finally does not run on SIGTERM/SIGKILL), so
    its items stayed queued and pilots played games nobody reads (~570 items at 14:55Z). Only this host's callers (pilotd and
    every cxefarm caller run on the pipeline host), only dirs older than min_age s. -> [(bid, queued items removed, pid)]"""
    by = {}
    for n in ls(q("queue")):
        p = parse(n)
        if p and p[2].startswith("stage-") and p[2] not in by:
            by[p[2]] = n
    out = []
    for bid, n in by.items():
        try:
            run = json.load(open(q("queue", n)))["run"]
        except (OSError, ValueError, KeyError):
            continue
        m = re.fullmatch(r"cf_(\d+)_(\d{16,})", os.path.basename(run))
        if not m or time.time() - int(m[2]) / 1e9 < min_age:
            continue
        cpid = int(m[1])
        try:
            os.kill(cpid, 0)
            continue  # alive (or a reused pid: then the items stay, as before)
        except PermissionError:
            continue
        except ProcessLookupError:
            pass
        nq = sum(1 for x in ls(q("queue")) if (parse(x) or (0, 0, ""))[2] == bid) if dry else cancel(bid)[0]
        out.append((bid, nq, cpid))
        if say:
            say(f"orphan batch {bid}: caller pid {cpid} is dead; {'would cancel' if dry else 'cancelled'} {nq} queued item(s)")
    return out


SHIPWATCH_LOG = "/data/USER/st/bq/shipwatch.log"


def starved_ship_tags():
    """11 Nov (TB 6ad907: xic1 PASSed 4 times and lost every ship race): TAGs of running shipchecks whose marker has CONFIRM_N >= 2 (a
    confirm read refused for base at least twice). boost_ships puts their items at key 000, ahead of every other ship leg."""
    out, run = set(), {}
    try:
        for ln in open(SHIPWATCH_LOG, errors="replace").readlines()[-400:]:
            m = re.search(r" start (\S+): shipcheck TAG=(\S+)", ln)
            if m:
                run[m[1]] = m[2]
                continue
            m = re.search(r" ended (\S+):", ln)
            if m:
                run.pop(m[1], None)
    except OSError:
        return out
    for bot, tag in run.items():
        try:
            mk = open(os.path.join("/homes/USER/cambc/bots", bot, "SHIPCHECK"), errors="replace").read()
        except OSError:
            continue
        m = re.search(r"^CONFIRM_N=(\d+)", mk, re.M)
        if m and int(m.group(1)) >= int(os.environ.get("PILOT_STARVED_N", 2)):
            out.add(tag)
    return out


def running_ship_tags():
    """TAGs of shipchecks shipwatch started and has not ended (its log: 'start BOT: shipcheck TAG=N ...', 'ended BOT: ...')"""
    run = {}
    try:
        for ln in open(SHIPWATCH_LOG, errors="replace").readlines()[-400:]:
            m = re.search(r" start (\S+): shipcheck TAG=(\S+)", ln)
            if m:
                run[m[1]] = m[2]
                continue
            m = re.search(r" ended (\S+):", ln)
            if m:
                run.pop(m[1], None)
    except OSError:
        pass
    return set(run.values())


def boost_ships(say=None):
    """7 Nov (Builder: two behaviour shipchecks sat behind agent screens): every queued batch of a RUNNING shipcheck goes to key
    BOOST_KEY + 1 (001), and so do the nochase2 reference runs a shipcheck waits on (cq-nd*ref). The age rule (AGE_KEY 489) had
    lifted ~1,600 agent screen items above a shipcheck's priority-0 legs (cq-nd2462 waited at key 500). cxecondor stage
    batches carry no TAG in their id: matched by their run dir instead (shipcheck's own cxecondab stage dirs name the TAG).
    -> items moved"""
    tags = [t for t in running_ship_tags() if not RARE_DEMOTE or t not in rare_ship_tags()]  # 10 Nov: rare checks wait at the back (demote_rare)
    # 12 Nov (owner: "speed up testing the draft changes"): with PILOT_RARE_DEMOTE off (default) rare checks are boosted like the others, incl.
    # their trunk-code gate (bky1 12701 sat 51 min at 488 on it)
    # 11 Nov ~01:10Z (Builder: fwb1r/x3i31f INCONCLUSIVE "trunk code vs live: gate did not finish"): a shipcheck's trunk-code gate runs
    # under its own tag (tc + 20 hex), so its 34-item killgate batches sat at 488 behind every 001/002 ship leg until the timebox
    # 11 Nov ~01:20Z (TB 6ad907: orphan tc gates of ENDED checks were lifted too): only tc hashes named in a running check's .out
    tch = set()
    for t in tags:
        for o in glob.glob(os.path.join(os.path.dirname(SHIPWATCH_LOG), f"shipwatch_*_{t}.out")):
            try:
                tch.update(re.findall(r"gate (tc[0-9a-f]{20})", open(o, errors="replace").read(20000)))
            except OSError:
                pass
    tcg = (r"|^cq-[a-z]+(" + "|".join(sorted(tch)) + r")") if tch else ""
    pat = re.compile(r"^cq-[a-z]+(" + "|".join(re.escape(t) for t in tags) + r")([^0-9a-z]|$)|^cq-nd\w*ref-" + tcg) if tags else re.compile(r"^cq-nd\w*ref-" + tcg)
    starved = [t for t in starved_ship_tags() if t in tags]
    stp = re.compile(r"^cq-[a-z]+(" + "|".join(re.escape(t) for t in starved) + r")([^0-9a-z]|$)") if starved else None
    moved = 0
    for n in ls(q("queue")):
        p = parse(n)
        if not p or p[0] <= 0 or p[0] >= 500 + 10 or not pat.search(p[2]):  # never lift post-ship/bank/drift reads (prio < -10)
            continue
        # 12 Nov (TB: with 1,128 items at 001, every live h2h leg at 002 sat unplayed for 70+ min: 12955/12956/12958/12965 INCONCLUSIVE,
        # 'live h2h no result'): the BIG legs share key 001 (oldest first) unless PILOT_LH_BEHIND=1 restores 002
        key = "002" if p[2].startswith("cq-lh") and os.environ.get("PILOT_LH_BEHIND") == "1" else "001"
        if starved and stp.search(p[2]):
            key = "000"  # a twice-refused confirm runs ahead of every ship leg (11 Nov)
        if p[0] <= int(key):
            continue
        try:
            os.rename(q("queue", n), q("queue", f"{key}_" + n.split("_", 1)[1]))
            moved += 1
        except OSError:
            pass
    if moved and say:
        say(f"ship legs first: {moved} queued item(s) of running shipchecks {sorted(tags)} moved to key 001/002 (BIG legs 002)")
    return moved


RARE_KEY = 515  # prio -15: after every non-rare ship leg AND after Step 0 diags (prio 9, key 491)
RARE_DEMOTE = os.environ.get("PILOT_RARE_DEMOTE", "0") == "1"  # 12 Nov (owner: "speed up testing the draft changes"): rare items keep their own key (488); 1 restores the 10 Nov demotion to RARE_KEY
RARE_AGE = int(os.environ.get("PILOT_RARE_AGE", 1800))  # 12 Nov (owner: "speed up testing the draft changes"): a rare item queued this
# long (s) is not demoted, and one already at RARE_KEY joins the ship legs at key 001 (oldest first there; 002 sat behind 816 items of 8 checks): with 5 checks always feeding legs, RARE_KEY was
# never reached (12638/12642: 150 items, 0 claimed in 60 min).


def rare_ship_tags():
    """10 Nov ~20:50Z (owner via Builder: "move the rare changes to the end as the maps would be better to generate when we have more
    condor compute"): TAGs of running shipchecks with RARE= in their environment, except live-bug fixes (slug dkh*, or RARE_KEEP_PRIO=1)."""
    tags = set()
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            c = open(p).read().split("\0")
            if not any(x.endswith("shipcheck.py") for x in c):
                continue
            i = next(k for k, x in enumerate(c) if x.endswith("shipcheck.py"))
            bot, tag = c[i + 1], c[i + 2]
            env = open(p.replace("cmdline", "environ")).read().split("\0")
            if any(e.startswith("RARE=") and e != "RARE=" for e in env) and "dkh" not in bot and "RARE_KEEP_PRIO=1" not in env:
                tags.add(tag)
        except (OSError, IndexError, StopIteration):
            continue
    return tags


SMALL_BATCH = int(os.environ.get("PILOT_SMALL_BATCH", 30))


def boost_small(say=None):
    """10 Nov ~23:20Z (owner: "do anything to make it go faster"; Builder: b1822's fault leg waited 22 min, firecount batches starved behind
    BIG legs): a batch of at most SMALL_BATCH items in all (queued + claimed) at priority 5-12 (keys 488-495) goes to key 001, level with
    ship legs and ahead of the long BIG legs (002). Rare-demoted items (RARE_KEY) are left alone. -> items moved"""
    if SMALL_BATCH <= 0:
        return 0
    size = {}
    for sub in ("queue", "claimed"):
        for n in ls(q(sub)):
            p = parse(n.split(".")[0] if sub == "claimed" else n)
            if p:
                size[p[2]] = size.get(p[2], 0) + 1
    moved = 0
    for n in ls(q("queue")):
        p = parse(n)
        # 11 Nov ~00:25Z (Builder: prearms pnt2/gsc1/gscm stalled 8-13 min): priority > 12 (keys 3-487: prearm's ident/capped/fire/fault at 20)
        # had sat behind every 001/002 item since ship legs moved there; any size goes to 001 now
        if not p or not ((488 <= p[0] <= 495 and size.get(p[2], 0) <= SMALL_BATCH) or 3 <= p[0] <= 487):
            continue
        try:
            os.rename(q("queue", n), q("queue", "001_" + n.split("_", 1)[1]))
            moved += 1
        except OSError:
            pass
    if moved and say:
        say(f"small batches first: {moved} queued item(s) of batches of <= {SMALL_BATCH} items moved to key 001")
    return moved


def _rare_bid(n, pat, tagre):
    """True when queue item N belongs to a running RARE shipcheck (same test as demote_rare's)."""
    b = parse(n)[2]
    if pat.search(b):
        return True
    try:
        run = json.load(open(q("queue", n))).get("run", "")
        m = re.search(r"/(?:cf_|\d{8}T\d{6}Z?_)(\d+)(?:_\d+)?$", run)
        return bool(m and tagre.search(open(f"/proc/{m[1]}/cmdline").read().replace("\0", " ")))
    except (OSError, ValueError):
        return False


def demote_rare(say=None):
    """Queued items of running RARE shipchecks (cq-<leg><TAG>-... ids, or stage runs whose owner's command line names the TAG) go to
    RARE_KEY. Their completed legs keep their results; nothing is killed. -> items moved"""
    tags = rare_ship_tags()
    if not tags:
        return 0
    pat = re.compile(r"(^cq-[a-z]+(" + "|".join(map(re.escape, tags)) + r")([^0-9a-z]|$))")
    tagre = re.compile(r"\b(" + "|".join(map(re.escape, tags)) + r")\b")
    seen, moved, aged = {}, 0, [0]
    for n in ls(q("queue")):
        p = parse(n)
        if not p:
            continue
        if time.time() - p[1] / 1000.0 > RARE_AGE:
            # 12 Nov (bky1 12701: its trunk-code gate sat at 488 for 51 min once demotion was off): any aged rare item above 001 moves
            if p[0] > 1 and (p[0] == RARE_KEY or seen.setdefault(p[2], _rare_bid(n, pat, tagre))):  # aged: join the ship legs at 001 (oldest first there)
                try:
                    os.rename(q("queue", n), q("queue", "001_" + n.split("_", 1)[1]))
                    aged[0] += 1
                except OSError:
                    pass
            continue
        if p[0] >= RARE_KEY:
            continue
        b = p[2]
        if b not in seen:
            hit = bool(pat.search(b))
            if not hit:
                try:
                    run = json.load(open(q("queue", n))).get("run", "")
                    m = re.search(r"/(?:cf_|\d{8}T\d{6}Z?_)(\d+)(?:_\d+)?$", run)
                    if m:
                        hit = bool(tagre.search(open(f"/proc/{m[1]}/cmdline").read().replace("\0", " ")))
                except (OSError, ValueError):
                    pass
            seen[b] = hit
        if seen[b] and RARE_DEMOTE:
            try:
                os.rename(q("queue", n), q("queue", f"{RARE_KEY}_" + n.split("_", 1)[1]))
                moved += 1
            except OSError:
                pass
    if moved and say:
        say(f"rare checks last: {moved} queued item(s) of RARE shipchecks {sorted(tags)} moved to key {RARE_KEY}")
    if aged[0] and say:
        say(f"rare checks aged: {aged[0]} item(s) queued > {RARE_AGE} s moved from {RARE_KEY} to 001 (oldest first among ship legs)")
    return moved


_UNOWNED_SAID = [0.0]
TOP_FILE = "/data/USER/st/bq/pilot_top.txt"  # 7 Nov (owner: "focus all our compute into the refactor"): one regex a line


def boost_top(say=None):
    """Queued items whose batch id, or whose stage owner's command line (cf_<pid> / <stamp>_<pid> run dirs), matches a regex in
    bq/pilot_top.txt go to key 000, ahead of ship legs: the owner's chosen work first. Empty or missing file: nothing. -> items moved"""
    # 10 Nov (Builder: unowned lines crept back and flattened priorities): a line counts only with an owner tag,
    # "REGEX  # owner: NAME". Lines without one are ignored (logged); the release train's own '^cq-[a-z]+TAG-' lines are exempt.
    pats, unowned = [], []
    try:
        for x in open(TOP_FILE):
            if not x.strip() or x.startswith("#"):
                continue
            rx, _, tail = x.partition("#")
            rx = rx.strip()
            if "owner:" in tail or re.fullmatch(r"\^cq-\[a-z\]\+\w+-", rx):
                pats.append(re.compile(rx))
            else:
                unowned.append(rx)
    except (OSError, re.error):
        return 0
    if unowned and say and time.time() - _UNOWNED_SAID[0] > 600:
        _UNOWNED_SAID[0] = time.time()
        say(f"pilot_top: {len(unowned)} line(s) without '# owner: NAME' ignored: {', '.join(unowned)[:200]}")
    if not pats:
        return 0
    seen, moved = {}, 0
    for n in ls(q("queue")):
        p = parse(n)
        if not p or p[0] == 0:
            continue
        b = p[2]
        if b not in seen:
            txt = b
            try:
                run = json.load(open(q("queue", n))).get("run", "")
                m = re.search(r"/(?:cf_|\d{8}T\d{6}Z?_)(\d+)(?:_\d+)?$", run)
                if m:
                    txt += " " + open(f"/proc/{m[1]}/cmdline").read().replace("\0", " ")
            except (OSError, ValueError):
                pass
            seen[b] = any(x.search(txt) for x in pats)
        if seen[b]:
            try:
                os.rename(q("queue", n), q("queue", "000_" + n.split("_", 1)[1]))
                moved += 1
            except OSError:
                pass
    if moved and say:
        say(f"top work first: {moved} queued item(s) matching {TOP_FILE} moved to key 000")
    return moved


RESERVE_N = int(os.environ.get("PILOT_RESERVE", 6))  # 12 Nov ~05:2xZ 4 -> 6 (Coordinator: info reads 131 min, Step 0 backlog growing); 12 Nov (Coordinator/Builder: Step 0 diags starved, median 68 min, with 8 shipchecks)


def reserve_low(say=None):
    """12 Nov: keep RESERVE_N items of priority 1..11 (keys 489-499: Step 0 diags at 9, info reads, rare-free reads) in flight while ship
    legs fill the queue. Counts claimed items and items already promoted (queued at 000) whose JSON prio is 1..11; when fewer than
    RESERVE_N, the oldest queued keys 489-499 move to 000. Moves no bar; ship legs keep the other pilots. PILOT_RESERVE=0 turns it off.
    -> items moved"""
    if RESERVE_N <= 0:
        return 0
    def lowprio(path):
        try:
            return 1 <= int(json.load(open(path)).get("prio", 0)) <= 11
        except (OSError, ValueError, TypeError):
            return False
    # count by the item's CURRENT key: boosted ship legs carry prio 10-12 in their JSON but sit at 001/002, so the JSON prio alone
    # counted them as low (first version, 04:51Z); low = keys 489-499 still, or promoted by this reserve to 000 with JSON prio 1..11
    def low_now(name, path):
        k = name.split("_", 1)[0]
        return (k.isdigit() and 489 <= int(k) <= 499) or (k == "000" and lowprio(path))
    have = sum(1 for c in ls(q("claimed")) if low_now(c, q("claimed", c)))
    have += sum(1 for n in ls(q("queue")) if n.startswith("000_") and lowprio(q("queue", n)))
    need = RESERVE_N - have
    if need <= 0:
        return 0
    # oldest first across keys 489-499 (12 Nov ~06:0xZ: by key first, the 490 stream kept Step 0 at 491 and info at 495 waiting 84 / 164 min)
    cand = sorted((p[1], p[0], n) for n in ls(q("queue")) if (p := parse(n)) and 489 <= p[0] <= 499)
    moved = 0
    for _, _, n in cand[:need]:
        try:
            os.rename(q("queue", n), q("queue", "000_" + n.split("_", 1)[1]))
            moved += 1
        except OSError:
            pass
    if moved and say:
        say(f"reserve: {moved} low-priority item(s) (Step 0 / info, keys 489-499) moved to 000 ({have} of {RESERVE_N} in flight)")
    return moved


def reap_maybe(every=120, say=None):
    """reap_orphans at most every `every` s across processes (a stamp file); cxefarm calls this on every run"""
    st = q("logs", "reap.stamp")
    try:
        if time.time() - os.path.getmtime(st) < every:
            return []
    except OSError:
        pass
    try:
        open(st, "a").close()
        os.utime(st)
    except OSError:
        return []
    r = reap_orphans(say=say)
    for bid, nq, cpid in r:
        log(f"reaped orphan batch {bid} (caller pid {cpid} dead): {nq} queued item(s) cancelled")
    try:
        boost_ships(say=log)
    except Exception as e:  # noqa: BLE001
        log(f"boost_ships failed: {e}")
    try:
        boost_small(say=log)
    except Exception as e:  # noqa: BLE001
        log(f"boost_small failed: {e}")
    try:
        demote_rare(say=log)
    except Exception as e:  # noqa: BLE001
        log(f"demote_rare failed: {e}")
    try:
        reserve_low(say=log)
    except Exception as e:  # noqa: BLE001
        log(f"reserve_low failed: {e}")
    try:
        boost_top(say=log)
    except Exception as e:  # noqa: BLE001
        log(f"boost_top failed: {e}")
    return r


def cancelled(bid, fresh=False):
    if fresh:
        poke(q("cancel"))
    return os.path.exists(q("cancel", bid))


def requeue_expired(say=None):
    """Claimed items whose lease is older than LEASE s go back to queue/ (their pilot died, was evicted or suspended)."""
    t, n = now(), 0
    for c in ls(q("claimed")):
        m = mtime(q("claimed", c))
        if m is None or t - m < LEASE:
            continue
        base = c.partition(".")[0]
        try:
            os.rename(q("claimed", c), q("queue", base))
            n += 1
            (say or log)(f"requeued {base} (lease of {c.partition('.')[2]} {t - m:.0f} s old)")
        except OSError:
            pass
    return n


# ---------------------------------------------------------------- pilot (Condor job body)
def slot_par(par):
    """Games at once in this slot, from what Condor gave us: cores - 1, at most PAR_MAX, and what free memory holds. 2 Nov: the batch's fixed 12 left
    2 80-core machines at 13 games/s; a game is ~0.5 CPU-s and 65 MB at its peak, and play is fuel-bound: 60 of 60 games identical at 48 at once on 16 cores."""
    s = os.environ.get("PILOT_SLOT_CPUS", "")
    if not s.isdigit():
        return par
    n = max(1, int(s) - 1)
    try:
        kb = next(int(x.split()[1]) for x in open("/proc/meminfo") if x.startswith("MemAvailable"))
        n = min(n, max(1, (kb // 1024 - 2000) // GAME_MB))
    except (OSError, StopIteration, ValueError):
        pass
    return str(min(n, PAR_MAX))


class Pilot:
    def __init__(self):
        ensure()
        self.id = f"{HOST}-{os.getpid()}"
        self.t0 = time.time()
        self.life = PILOT_MAX_LIFE - int.from_bytes(os.urandom(2), "big") % 600  # staggered ends
        self.item, self.child, self.claim = None, None, None
        # 12 Nov (TB: ~200 lab helper pilots exit after idle and restart, one home log file per process: 3,770 files in 15 min pushed the home
        # past cxefarm's 54,000-file gate): a helper pilot (HOSTPILOT=1) appends to ONE log per host; Condor pilots keep one per pilot
        self.logf = q("logs", f"host-{HOST}.log") if os.environ.get("HOSTPILOT") == "1" else q("logs", f"{self.id}.log")
        self.done = 0

    def say(self, msg):
        log(f"{self.id} {msg}", self.logf)

    def beat(self):
        d = dict(host=socket.gethostname(), pid=os.getpid(), start=self.t0, age=int(time.time() - self.t0),
                 retiring=time.time() - self.t0 > self.life - RETIRE, item=self.item, done=self.done,
                 cluster=os.environ.get("PILOT_JOB", ""))
        tmp = q("pilots", f".{self.id}.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(d, f)
            os.rename(tmp, q("pilots", self.id))
        except OSError:
            pass

    def kill_child(self):
        c = self.child
        if c and c.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(c.pid, sig)
                except OSError:
                    pass
                try:
                    c.wait(5)
                    break
                except subprocess.TimeoutExpired:
                    pass
        if c:
            j = f"/var/tmp/USER-condab-{c.pid}"  # condab_node.sh's job dir (J=/var/tmp/USER-condab-$$), left behind by a kill
            if os.path.isdir(j):
                subprocess.run(["chmod", "-R", "u+w", j], capture_output=True)
                shutil.rmtree(j, ignore_errors=True)

    def on_term(self, *_):
        self.say("SIGTERM: giving back my item")
        self.kill_child()
        if self.claim:
            try:
                os.rename(q("claimed", self.claim), q("queue", self.claim.partition(".")[0]))
            except OSError:
                pass
        try:
            os.unlink(q("pilots", self.id))
        except OSError:
            pass
        sys.exit(143)

    def claim_next(self):
        poke(q("cancel"))
        for n in ls(q("queue")):
            p = parse(n)
            if not p:
                continue
            if cancelled(p[2]):
                try:
                    os.unlink(q("queue", n))
                except OSError:
                    pass
                continue
            c = f"{n}.{self.id}"
            try:
                os.rename(q("queue", n), q("claimed", c))
            except FileNotFoundError:  # someone else took it (or an NFS retry of our own rename that had succeeded)
                if mtime(q("claimed", c)) is None:
                    continue
            except OSError:
                continue
            touch(q("claimed", c))
            try:
                with open(q("claimed", c)) as f:
                    it = json.load(f)
            except (OSError, ValueError) as e:
                self.say(f"bad item {n}: {e}")
                self.finish(c)
                continue
            return c, it
        return None, None

    def finish(self, c):
        try:
            os.rename(q("claimed", c), q("done", c))
        except OSError:
            pass

    def run_item(self, c, it):
        run, idx = it["run"], it["idx"]
        outp = os.path.join(run, f"job_p{idx:04d}.out")
        for _ in range(4):  # NFS can answer "no such dir" for a new one for a few seconds (2 Nov, gate 7981): refresh before believing it
            if os.path.isdir(run):
                break
            poke(os.path.dirname(os.path.dirname(run)))
            poke(os.path.dirname(run))
            time.sleep(5)
        if not os.path.isdir(run) and time.time() - it.get("t", 0) < GONE_AFTER:  # an unseen dir this young is this node's view: another pilot may see it
            self.say(f"give back {c}: run dir not visible here")
            try:
                os.rename(q("claimed", c), q("queue", c.partition(".")[0]))
            except OSError:
                pass
            time.sleep(30)
            return
        if not os.path.isdir(run) or os.path.exists(outp):
            self.say(f"skip {c}: {'run dir gone' if not os.path.isdir(run) else 'already done'}")
            self.finish(c)
            return
        self.item, self.claim = c.partition(".")[0], c
        self.beat()
        tmpout = f"/var/tmp/USER-pilot-{os.getpid()}.out"
        t0 = time.time()
        start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.say(f"run {self.item} (prio {it.get('prio')}, queued {t0 - it.get('t', t0):.0f} s ago)")
        with open(tmpout, "w") as fo:
            args = [str(x) for x in it["args"]]
            args[1] = slot_par(args[1])
            self.child = subprocess.Popen(["sh", it.get("node") or NODE] + args, stdout=fo, stderr=subprocess.STDOUT, cwd=run,
                                          start_new_session=True)
        last_hb, why = time.time(), None
        while True:
            try:
                rc = self.child.wait(5)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancelled(it["bid"], True):
                why = "cancelled"
            elif time.time() - last_hb >= HB:
                last_hb = time.time()
                poke(q("claimed"))
                if not os.path.exists(q("claimed", c)):
                    why = "lease lost (requeued)"
                else:
                    touch(q("claimed", c))
                    self.beat()
            if not why and time.time() - t0 > ITEM_TIMEOUT:
                why = f"timeout {ITEM_TIMEOUT} s"
            if why:
                self.kill_child()
                rc = None
                break
        took = time.time() - t0
        if why is None:
            poke(q("claimed"))
            if cancelled(it["bid"], True):
                why = "cancelled"
            elif not os.path.exists(q("claimed", c)):
                why = "lease lost (requeued)"
        if why is None and os.path.isdir(run):
            body = open(tmpout, errors="replace").read().splitlines()
            txt = (f"## host {socket.gethostname()} cpus {os.cpu_count()} start {start} pilot {self.id}\n"
                   + "".join(f"[1] {x}\n" for x in body) + f"[1] ## rc={rc}\n"
                   + f"## end {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            tmp = f"{outp}.tmp.{self.id}"
            try:
                with open(tmp, "w") as f:
                    f.write(txt)
                os.rename(tmp, outp)
                self.say(f"done {self.item} rc {rc} in {took:.0f} s")
            except OSError as e:
                self.say(f"could not write {outp}: {e}")
        else:
            self.say(f"dropped {self.item} after {took:.0f} s: {why or 'run dir gone'}")
        try:
            os.unlink(tmpout)
        except OSError:
            pass
        if why != "lease lost (requeued)":
            self.finish(c)
        self.done += 1
        self.item, self.claim, self.child = None, None, None

    def tmp_ok(self):
        """01 Nov: gpu32's /tmp filled ("No space left on device") and its pilot failed 96 games of a BIG in one item.
        Before each claim: with < PILOT_TMP_MIN_MB (2000) free in /tmp, drop our own node caches (the wasmtime compile cache
        and the condab build workspaces not used for 60 min) and look again; still short -> leave, so the slot goes to
        another node and no item is claimed here."""
        try:
            free = shutil.disk_usage("/var/tmp").free // (1 << 20)
        except OSError:
            return True
        if free >= TMP_MIN_MB:
            return True
        me = str(os.getuid())
        shutil.rmtree("/var/tmp/USER-socache", ignore_errors=True)  # 7 Nov: cxefarm's .so cache (content-addressed, rebuilt on demand)
        for d in glob.glob("/var/tmp/USER-wtcache") + glob.glob("/var/tmp/USER-cqws-*/bots/*"):
            try:
                if str(os.stat(d).st_uid) == me and time.time() - os.path.getmtime(d) > 3600:  # never a build a running part uses
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
        free2 = shutil.disk_usage("/var/tmp").free // (1 << 20)
        self.say(f"/tmp low on {socket.gethostname()}: {free} MB free, {free2} MB after dropping our caches")
        if free2 < TMP_MIN_MB:
            self.say(f"/tmp still under {TMP_MIN_MB} MB: exit after {self.done} items (the slot goes to another node)")
            return False
        return True

    def main(self):
        signal.signal(signal.SIGTERM, self.on_term)
        signal.signal(signal.SIGINT, self.on_term)
        self.say(f"start on {socket.gethostname()} ({os.cpu_count()} cpus), life {self.life} s, idle {PILOT_IDLE} s")
        idle0, last_rq = time.time(), 0
        while True:
            self.beat()
            age = time.time() - self.t0
            if age > self.life:
                self.say(f"end of life after {self.done} items")
                break
            if not self.tmp_ok():
                break
            if take_yield():
                self.say(f"leaving my slot to a waiting direct job, after {self.done} items")
                break
            c, it = self.claim_next()
            if c:
                self.run_item(c, it)
                idle0 = time.time()
                continue
            if time.time() - idle0 > PILOT_IDLE:
                self.say(f"idle {PILOT_IDLE} s: exit after {self.done} items")
                break
            if time.time() - last_rq > 60:
                last_rq = time.time()
                requeue_expired(self.say)
            time.sleep(3)
        try:
            os.unlink(q("pilots", self.id))
        except OSError:
            pass


# ---------------------------------------------------------------- manager
def condor_pilots():
    """Our pilot jobs in Condor: [(cluster.proc, JobStatus)] (1 idle, 2 running, 5 held)."""
    r = subprocess.run(["condor_q", "-constraint", f'JobBatchName == "{BATCH_NAME}"', "-af", "ClusterId", "ProcId",
                        "JobStatus"], capture_output=True, text=True, env=cenv())
    if r.returncode != 0:
        log(f"condor_q: {(r.stderr or r.stdout).strip()[-160:]}")
        return None
    out = []
    for ln in r.stdout.splitlines():
        f = ln.split()
        if len(f) == 3 and f[2].isdigit():
            out.append((f"{f[0]}.{f[1]}", int(f[2])))
    return out


RESERVE, YIELD_AFTER, YIELD_N = 2, 120, 3  # free slots pilots leave for direct jobs; a pilot yields once a job has waited this long, at most this many at a time


def direct_idle():
    """QDates of our non-pilot jobs waiting for a slot at priority >= 5: builds, identity games, diag runs, reads."""
    r = subprocess.run(["condor_q", "-constraint", f'JobStatus == 1 && JobBatchName != "{BATCH_NAME}" && JobPrio >= 5', "-af", "QDate"],
                       capture_output=True, text=True, env=cenv())
    return [int(x) for x in r.stdout.split() if x.isdigit()]


def offer_yields(spare):
    """A running pilot never gives its slot up and Condor does not preempt it, so direct jobs starved (2 Nov: 984 s). With a job waiting over YIELD_AFTER and
    pilots above PILOT_MIN (spare), up to YIELD_N pilots leave after their item. -> tokens written."""
    waits = [time.time() - t for t in direct_idle()]
    os.makedirs(q("yield"), exist_ok=True)
    for n in ls(q("yield")):
        if (mtime(q("yield", n)) or 0) < time.time() - 120:
            try:
                os.unlink(q("yield", n))
            except OSError:
                pass
    k = max(0, min(YIELD_N - len(ls(q("yield"))), sum(1 for w in waits if w > YIELD_AFTER), spare))
    for i in range(k):
        open(q("yield", f"y{int(time.time())}_{i}"), "w").close()
    return k


def take_yield():
    """In a pilot: one token, if any, is mine."""
    for n in ls(q("yield")) if os.path.isdir(q("yield")) else ():
        try:
            os.unlink(q("yield", n))
            return True
        except OSError:
            continue
    return False


def easy_hours(free, hour=None):
    """night by the clock (a window may wrap midnight), or a pool with FREE_EASY free slots"""
    h = time.gmtime().tm_hour if hour is None else hour
    a, b = (int(x) for x in NIGHT.split("-"))
    return free >= FREE_EASY or (a <= h or h < b if a > b else a <= h < b)


def grow_want(n_queued, alive, room, easy):
    """pilots wanted for n_queued queued items: alive + room is what the pool can take"""
    depth, per = (DEPTH_NIGHT, PER_NIGHT) if easy else (DEPTH, PER)
    if PILOT_MAX <= PILOT_N or n_queued <= depth * PILOT_N:
        return PILOT_N
    return max(PILOT_N, min(PILOT_MAX, alive + room, math.ceil(n_queued / per)))


def free_slots():
    """Unclaimed slots with >= CPUS cpus in the pool now."""
    r = subprocess.run(["condor_status", "-constraint", f'State == "Unclaimed" && Cpus >= {CPUS}', "-af", "Name"],
                       capture_output=True, text=True, env=cenv())
    return len([x for x in r.stdout.splitlines() if x.strip()])


def submit(k):
    sub = q("logs", "pilot.sub")
    me = os.environ.get("PILOT_SELF", "/homes/USER/cambc/tools/lab/pilotd.py")
    open(sub, "w").write(f"""universe     = vanilla
executable   = /usr/bin/env
arguments    = PILOT_JOB=$(Cluster).$(Process) PILOT_SLOT_CPUS=$$(Cpus) nice -n 10 python3 -I {me} --pilot
initialdir   = {q('logs')}
output       = /dev/null
error        = {q('logs')}/condor_$(Cluster).$(Process).err
request_cpus = {CPUS}
request_memory = {MEM}
priority     = {CONDOR_PRIO}
batch_name   = {BATCH_NAME}
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22" || OpSysAndVer == "Ubuntu20") && (has_avx2 =?= true)
getenv       = True
should_transfer_files = NO
queue {k}
""")
    r = subprocess.run(["condor_submit", sub], capture_output=True, text=True, env=cenv(), cwd=q("logs"))
    m = re.search(r"submitted to cluster (\d+)", r.stdout)
    if r.returncode != 0 or not m:
        log(f"!! condor_submit failed (Kerberos ticket? klist): {(r.stdout + r.stderr).strip()[-200:]}")
        return None
    return m.group(1)


def prune():
    t = now()
    # home inode quota (30 Oct: 56.1k of 60k, done/ held 5,040 markers): done markers 5 min, finished pilots' logs 1 h;
    # 30 Oct 22:45 (Builder: 742 markers in 25 min at the night's throughput): done markers 60 s (only --status counts them)
    for d, age in (("done", 5), ("cancel", 6 * 3600), ("logs", 3600), ("pilots", 3600)):
        for n in ls(q(d)):
            if n == "pilot.sub":
                continue
            m = mtime(q(d, n))
            # 12 Nov (TB, Builder: home 54,058 over the cxefarm gate, ~760 cancel markers/h): a cancel marker matters while an item of its
            # batch can still run (ITEM_TIMEOUT 40 min); stage markers keep 2 h (their callers wait <= 2 h), the rest 1 h
            if d == "cancel":
                age = 7200 if n.startswith("stage-") else max(3600, ITEM_TIMEOUT + 600)
            if m is not None and t - m > age:
                try:
                    os.unlink(q(d, n))
                except OSError:
                    pass
    for n in ls(q("queue")):  # items of cancelled batches nobody has picked up
        p = parse(n)
        if p and cancelled(p[2]):
            try:
                os.unlink(q("queue", n))
            except OSError:
                pass


def manager():
    ensure()
    os.makedirs(os.path.dirname(PIDF), exist_ok=True)
    try:
        old = int(open(PIDF).read().split()[0])
        if old != os.getpid() and os.path.exists(f"/proc/{old}") and "pilotd" in open(f"/proc/{old}/cmdline").read():
            sys.exit(f"pilotd already runs as pid {old}")
    except (OSError, ValueError, IndexError):
        pass
    open(PIDF, "w").write(f"{os.getpid()}\n")
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    last_yield = 0
    log(f"pilotd start pid {os.getpid()}: PILOT_N {PILOT_N}, PILOT_MAX {PILOT_MAX}, FREE_FRAC {FREE_FRAC}, night {NIGHT} depth {DEPTH}/{DEPTH_NIGHT} per {PER}/{PER_NIGHT} free-easy {FREE_EASY}, idle {PILOT_IDLE} s, life {PILOT_MAX_LIFE} s, qdir {QDIR}")
    last_sub, last_prune, last_state = 0, 0, None
    free_at, hold = [0.0, 0], [0.0, 0]
    while not stop:
        touch(q("pilotd.hb")) or open(q("pilotd.hb"), "w").close()
        t = now()
        requeue_expired()
        mv = promote_small()
        if mv:
            log(f"small batches first: {mv} queued item(s) moved to the front")
        if time.time() - last_prune > 60:
            last_prune = time.time()
            prune()
        queued, claimed = ls(q("queue")), ls(q("claimed"))
        dm = mtime(q("demand")) or 0
        busy = bool(queued or claimed)
        want = 0
        if queued:
            want = PILOT_N
            # 1 Nov ~19:40 (Builder: idle slots while batches wait): grow from > 2 queued items per pilot (was 6), toward
            # one pilot per 2 queued items (condab now cuts batches into 16-48-game items for a 60-pilot pool)
            if PILOT_MAX > PILOT_N:  # deep queue: grow into free slots
                if time.time() - free_at[0] > 60:
                    free_at[:] = [time.time(), free_slots()]
                easy = easy_hours(free_at[1])
                want = grow_want(len(queued), len(alive_pilots()), max(0, int(free_at[1] * FREE_FRAC) - RESERVE - len(direct_idle())), easy)  # 2 Nov: was PILOT_N + free: 12 + 8 < 25 alive
                if easy and want > PILOT_N:
                    hold[:] = [time.time(), want]
        elif claimed or t - dm < DEMAND_WINDOW:
            want = PILOT_MIN
        jobs = condor_pilots()
        if jobs is None:
            log("!! condor_q failed")
            time.sleep(30)
            continue
        alive = alive_pilots()
        retiring = sum(1 for a in alive if a.get("retiring"))
        held = [j for j, s in jobs if s == 5]
        if held:
            subprocess.run(["condor_rm"] + held, capture_output=True, text=True, env=cenv())
            log(f"removed {len(held)} held pilots {' '.join(held)}")
        idle = [j for j, s in jobs if s == 1]
        if time.time() - last_yield > 60:
            last_yield = time.time()
            ny = offer_yields(max(0, len(alive) - PILOT_MIN))
            if ny:
                log(f"offered {ny} slots to waiting direct jobs")
        have = sum(1 for _, s in jobs if s in (1, 2)) - retiring
        home_hi = False
        if want > have and time.time() - last_sub > 60:
            try:  # 12 Nov ~20:5xZ (Coordinator: pilots churn ~2k home files; hard quota 61k): no NEW pilots at >= PILOT_HOME_STOP files
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import homequota
                hq = (homequota.home_quota() or {}).get("files", 0)
                home_hi = hq >= int(os.environ.get("PILOT_HOME_STOP", 58800))
                if home_hi:
                    log(f"home holds {hq} files >= {os.environ.get('PILOT_HOME_STOP', 58500)}: no new pilots this round (running ones go on)")
                    last_sub = time.time()
            except Exception:  # noqa: BLE001
                pass
        if want > have and time.time() - last_sub > 60 and not home_hi:
            cl = submit(want - have)
            last_sub = time.time()
            if cl:
                log(f"submitted {want - have} pilots as cluster {cl} (queued {len(queued)}, claimed {len(claimed)}, "
                    f"alive {len(alive)}, condor {len(jobs)}, retiring {retiring})")
        elif idle and have > (keep := max(want, hold[1] if time.time() - hold[0] < HOLD_S else 0)):  # never-started pilots beyond the need: no slot is held for nothing
            drop = idle[:have - keep]
            subprocess.run(["condor_rm"] + drop, capture_output=True, text=True, env=cenv())
            log(f"removed {len(drop)} idle pilots {' '.join(drop)} (want {want}, keep {keep})")
        state = (want, len(alive), len(jobs), len(queued), len(claimed))
        if state != last_state:
            log(f"want {want} alive {len(alive)} condor {len(jobs)} (idle {len(idle)}) queued {len(queued)} "
                f"claimed {len(claimed)}")
            last_state = state
        for _ in range(15):
            if stop:
                break
            time.sleep(1)
    log(f"pilotd stop pid {os.getpid()} (running pilots exit on idle)")
    try:
        if int(open(PIDF).read().split()[0]) == os.getpid():
            os.unlink(PIDF)
    except (OSError, ValueError, IndexError):
        pass


def status():
    ensure()
    t = now()
    try:
        pid = int(open(PIDF).read().split()[0])
        run = os.path.exists(f"/proc/{pid}")
    except (OSError, ValueError, IndexError):
        pid, run = None, False
    hb = mtime(q("pilotd.hb"))
    print(f"pilotd: pid {pid} {'running' if run else 'NOT running'}; heartbeat "
          + (f"{t - hb:.0f} s ago" if hb else "none") + f"; qdir {QDIR}")
    dm = mtime(q("demand"))
    print(f"last demand {t - dm:.0f} s ago" if dm else "no demand yet")
    alive = alive_pilots()
    print(f"pilots alive: {len(alive)}")
    for a in alive:
        print(f"  {a['pilot']} {a.get('cluster', '')} age {a.get('age', 0) // 60} min, {a.get('done', 0)} items done, "
              + (f"on {a['item']}" if a.get("item") else "idle") + (" (retiring)" if a.get("retiring") else ""))
    jobs = condor_pilots()
    if jobs is not None:
        print(f"pilot jobs in Condor: {sum(1 for _, s in jobs if s == 1)} idle, {sum(1 for _, s in jobs if s == 2)} "
              f"running, {sum(1 for _, s in jobs if s == 5)} held")
    queued, claimed, done = ls(q("queue")), ls(q("claimed")), ls(q("done"))
    by = {}
    for n in queued:
        p = parse(n)
        if p:
            by.setdefault((500 - p[0], p[2]), 0)
            by[(500 - p[0], p[2])] += 1
    print(f"items queued: {len(queued)}" + "".join(f"\n  {'small' if pr == 500 - BOOST_KEY else f'prio {pr}'} {b}: {k}"
                                                   for (pr, b), k in sorted(by.items(), key=lambda x: -x[0][0])))
    print(f"items claimed: {len(claimed)}")
    print(f"items done (last minute): {len(done)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--status"]:
        status()
    elif a[:1] == ["--reap"]:  # cancel queued batches of dead cxefarm callers (--dry: list them)
        r = reap_orphans(say=print, dry="--dry" in a)
        print(f"{len(r)} orphan batch(es), {sum(x[1] for x in r)} queued item(s)")
        if "--dry" not in a:
            print(f"running shipchecks {sorted(running_ship_tags())}: {boost_ships(say=print)} item(s) moved to key 001")
    elif a[:1] == ["--pilot"]:
        # 12 Nov 20:3xZ (b2347: birnhorn, a Xeon E5-2643 v1 without AVX2, killed whole cxe items with "Illegal instruction": 20 lost games
        # in a BIG and a prearm fault row turned FAIL): a node whose CPU lacks the instructions our native builds use takes no items.
        try:
            flags = set(next((ln for ln in open("/proc/cpuinfo") if ln.startswith("flags")), "").split())
        except OSError:
            flags = set()
        miss = [x for x in os.environ.get("PILOT_CPU_FLAGS", "avx2 fma bmi2").split() if flags and x not in flags]
        if miss:
            log(f"{HOST}-{os.getpid()} no pilot here: CPU lacks {' '.join(miss)} (native cxe builds die with Illegal instruction)")
            sys.exit(0)
        Pilot().main()
    elif not a:
        manager()
    else:
        sys.exit(__doc__)
