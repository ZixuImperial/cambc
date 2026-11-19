"""cxerun: play many matches on cxe in parallel (the run-batch of the native engine).
manifest: one game per line, `SO_A SO_B MAP OUT_PREFIX [extra cxe args]` (SO = a library from cxebuild.py).
Each game writes OUT_PREFIX.repl26a, OUT_PREFIX.fuel.tsv and, with --statistics, OUT_PREFIX.json in the CLI's
--statistics --json layout for the fields tools/lab/ablsum.py and condab.py read.
Games take one of CXE_SLOTS (default 6; 2 above load 24) machine-wide slots, so all callers together use at most that many cores.
usage: python3 -I tools/cxe/cxerun.py MANIFEST [--jobs N] [--statistics] [--no-replay]
  --no-replay: each game's .repl26a is removed when it ends (fuel.tsv and the json stay)."""
import concurrent.futures as cf
import fcntl
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402


SLOTS = os.path.join(cxebuild.ROOT, "slots")


PRIO = int(os.environ.get("CXE_PRIO") or os.environ.get("CONDAB_PRIO") or os.environ.get("CQB_PRIO") or 0)  # SP_PRIO reaches condab as CONDAB_PRIO
WAIT = os.path.join(SLOTS, "wait")


def _top_waiting():
    """The highest priority among games waiting for a slot in live processes (WAIT/<prio>_<pid>_<n>).
    5 Nov (TB2): started at -1, so when every waiter had a negative priority (post-ship legs -50, flagscreen -10) the top read -1 and
    no waiter passed `top <= PRIO`: those spot-checks waited forever with every slot free (stuck from ~01:57Z)."""
    top = -10 ** 9
    try:
        names = os.listdir(WAIT)
    except OSError:
        return top
    for f in names:
        try:
            pr, pid, _ = f.split("_")
            os.kill(int(pid), 0)
            try:  # 10 Nov ~23:55Z (Builder: 55 games waited 17 min with 2 slots free): a SIGSTOPped waiter (loadguard / a paused job, state T)
                st_ = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
                if st_ in ("Z", "X"):  # 11 Nov (TB 6ad907: a zombie cxerun held the line): a zombie never waits again: drop its entry
                    try:
                        os.remove(os.path.join(WAIT, f))
                    except OSError:
                        pass
                    continue
                if st_ in ("T", "t"):  # stopped: can't take a slot, must not hold the line
                    continue
            except OSError:
                pass
            top = max(top, int(pr))
        except (ValueError, ProcessLookupError):
            try:
                os.remove(os.path.join(WAIT, f))  # a dead process's entry
            except OSError:
                pass
        except PermissionError:
            pass
    return top


def _lim(key, default):
    """10 Nov 23:4xZ: live-tunable from bq/load_limits (tools/lab/loadlim.py), read on every wait loop pass; env vars still win.
    97 spot-check games queued behind 2 busy slots while maple20 sat at load ~50."""
    try:
        sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
        import loadlim
        v = loadlim.get(key)
        return default if not v or v <= 0 else v
    except Exception:  # noqa: BLE001
        return default


def slot():
    """One of CXE_SLOTS machine-wide game slots (flock), so parallel callers (condab legs, A/Bs) share maple04's cores
    instead of each taking its own --jobs. -> the open lock file (closing it frees the slot). A free slot goes to the highest-priority
    waiting game (CXE_PRIO / CONDAB_PRIO / CQB_PRIO, as on Condor; owner 4 Nov: prio-20 reads jump the queue); a game never loses a slot."""
    os.makedirs(WAIT, exist_ok=True)
    me = os.path.join(WAIT, f"{PRIO:03d}_{os.getpid()}_{threading.get_ident() % 10 ** 9}")
    open(me, "w").close()
    try:
        while True:
            # owner 4 Nov ~20:00Z (via Planner/Builder, Condor starved): 12 slots while maple04's 1-min load is under CXE_LOAD_MAX 96,
            # CXE_SLOTS_BUSY (4) above it (was 8 slots and 40)
            # owner 4 Nov ~21:55Z: VS Code crashed at load ~50 on 16 cores -> 6 slots, 2 above load 24
            n = int(os.environ.get("CXE_SLOTS", "6"))
            if os.getloadavg()[0] > float(os.environ.get("CXE_LOAD_MAX") or _lim("cxe_load_max", 24)):
                n = min(n, int(os.environ.get("CXE_SLOTS_BUSY") or _lim("cxe_slots_busy", 2)))
            if _top_waiting() <= PRIO:
                for k in range(n):
                    f = open(os.path.join(SLOTS, f"slot{k}.lock"), "w")
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        return f
                    except OSError:
                        f.close()
            time.sleep(0.05)
    finally:
        try:
            os.remove(me)
        except OSError:
            pass


def health(stuck_min=15):
    """Slot-wait alarm (5 Nov, TB2: a priority bug left 34 post-ship spot-checks waiting for hours with every slot free) -> '' when
    fine, else one line: the oldest live waiter's age, how many wait, and how many slots are free right now. Alarm when a waiter is
    older than STUCK_MIN minutes while a slot is free (the deadlock signature), or older than 60 minutes at all."""
    now, ages = time.time(), []
    try:
        for f in os.listdir(WAIT):
            try:
                pr, pid, _ = f.split("_")
                os.kill(int(pid), 0)
                ages.append((now - os.path.getmtime(os.path.join(WAIT, f)), int(pr)))
            except (ValueError, OSError):
                pass
    except OSError:
        return ""
    if not ages:
        return ""
    free = 0
    n = int(os.environ.get("CXE_SLOTS", "6"))
    if os.getloadavg()[0] > float(os.environ.get("CXE_LOAD_MAX", "24")):  # the cap slot() applies: count only usable slots (5 Nov: "4 free" at load 32 was 0 usable)
        n = min(n, int(os.environ.get("CXE_SLOTS_BUSY", "2")))
    for k in range(n):
        try:
            with open(os.path.join(SLOTS, f"slot{k}.lock"), "w") as f:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)  # held by a game -> fails; released at once when free
                free += 1
        except OSError:
            pass
    age, pr = max(ages)
    if (age > 60 * stuck_min and free) or age > 3600:
        return (f"cxe slots: {len(ages)} games waiting, the oldest {age / 60:.0f} min (priority {pr}), {free} of {n} usable slot(s) free now"
                + (f" (load {os.getloadavg()[0]:.0f} > CXE_LOAD_MAX: {n} slots)" if n < int(os.environ.get("CXE_SLOTS", "6")) else "")
                + (" -> STUCK (free slots, nobody takes them)" if free else ""))
    return ""


def run_game(exe, line, stats, keep=True):
    p = line.split()
    so_a, so_b, mp, pre = p[:4]
    cmd = ["nice", "-n", "10", exe, so_a, so_b, mp, pre] + p[4:]
    if stats:
        cmd += ["--statistics", pre + ".json"]
    lk = slot()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        lk.close()
    if not keep:  # --no-replay (bk1 5 Nov: the flag was never parsed; 23k replays, 10 GB, filled /data): the engine always writes one
        try:
            os.remove(pre + ".repl26a")
        except OSError:
            pass
    return pre, r.returncode, (r.stdout + r.stderr).strip()


def on_pilots(lines, stats, keep):
    """7 Nov (Builder: diag runners sat ~15 min behind the local load gate while another user's jobs held maple02 at ~37 and the pilots
    were free): the whole manifest as one pilot batch (tools/cxe/cxefarm.py), each game's files back at its OUT_PREFIX as a local run
    writes them (.repl26a unless --no-replay, .fuel.tsv, .json with --statistics, .team-a/b.stdout with CXE_STDOUT=1).
    -> (ok, bad) or None when the pilots cannot take it (the caller then plays locally, as before). CXERUN_LOCAL=1: always local."""
    # 9 Nov 19:35Z (b1775 fb4m2: CXE_LOCAL=1 was ignored and the identity sat 30 min at pilot key 491): CXE_LOCAL=1 also means local
    if "1" in (os.environ.get("CXERUN_LOCAL"), os.environ.get("CXE_LOCAL")) or len(lines) < int(os.environ.get("CXERUN_PILOT_MIN", "4")):
        return None
    import cxefarm
    games = []
    for k, ln in enumerate(lines):
        p = ln.split()
        so_a, so_b, mp, pre = p[:4]
        extra = p[4:]
        if any(x.startswith("/") and not x.startswith("/homes/") for x in extra):  # a node cannot read this machine's /data paths
            return None
        files = {"g.fuel.tsv": pre + ".fuel.tsv"} if "--fuel-log" in extra else {}  # the engine writes it only when asked
        if keep:
            files["g.repl26a"] = pre + ".repl26a"
        if stats:
            files["g.json"] = pre + ".json"
        env = {}
        if os.environ.get("CXE_STDOUT") == "1":
            env["CXE_STDOUT"] = "1"
            files.update({"g.team-a.stdout": pre + ".team-a.stdout", "g.team-b.stdout": pre + ".team-b.stdout"})
        for f in files.values():
            os.makedirs(os.path.dirname(os.path.abspath(f)), exist_ok=True)
        games.append(dict(id=k, a=so_a, b=so_b, map=mp, args=extra + (["--statistics", "@D@/g.json"] if stats else []), env=env, files=files))
    got = cxefarm.run(games, say=lambda m: print(m, flush=True), per=int(os.environ.get("CXERUN_PER", "24")), cpus=8,
                      prio=int(os.environ.get("CXE_PRIO") or os.environ.get("CONDAB_PRIO") or 12))  # 9 Nov: 9 -> 12 (key 488): identity / spot runs gate arms and reads
    if got is None:
        return None
    return got, len(lines) - got


def main():
    a = sys.argv[1:]
    man = a[0]
    jobs = int(a[a.index("--jobs") + 1]) if "--jobs" in a else min(12, os.cpu_count() or 4)
    stats = "--statistics" in a
    keep = "--no-replay" not in a
    lines = [ln.strip() for ln in open(man) if ln.strip() and not ln.startswith("#")]
    pr = on_pilots(lines, stats, keep)
    if pr is not None:
        print(f"cxerun: {pr[0]}/{len(lines)} games ok (on the pilots)")
        return 1 if pr[1] else 0
    exe = cxebuild.build_host()
    bad = 0
    with cf.ThreadPoolExecutor(jobs) as ex:
        for pre, rc, out in ex.map(lambda ln: run_game(exe, ln, stats, keep), lines):
            if rc:
                bad += 1
                print(f"FAIL {pre}: {out[-300:]}", flush=True)
    print(f"cxerun: {len(lines) - bad}/{len(lines)} games ok")
    return 1 if bad else 0


if __name__ == "__main__" and sys.argv[1:2] == ["--health"]:
    print(health() or "cxe slots: ok")
    sys.exit(0)
if __name__ == "__main__":
    sys.exit(main())
