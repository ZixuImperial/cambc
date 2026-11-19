#!/usr/bin/env python3
"""cqbatch: `cambc400 run-batch` on Condor, a drop-in for agents' local diag batches (30 Oct night, Tool builder; Builder:
"make condab the easy path for agents' small diag batches (20-100 games), so nobody runs them locally").

usage: python3 -I tools/lab/cqbatch.py MANIFEST [run-batch options] [--per-job 25] [--cpus 8] [--wait-max 5400] [--fast]
  MANIFEST: run-batch's own format, one game a line: BOT_A BOT_B MAP REPLAY [--statistics PATH] [--json]
    (`cambc400 run A B --map M -o DIR` = the line `A B M DIR/NAME.repl26a`). Relative paths are read from the current
    directory, as run-batch reads them. Every replay and statistics file lands at the path its line names.
  run-batch options passed on: --rounds N, --fuel-quantum Q, --log-limit BYTES, --timeout S, --release, --json.
  Build (2 Nov, b802: a non-release score differs from condab's on the same maps): release by default, as condab and the platform play. A bot with
  more than DIAG_BLOCKS debug_block lines is a diag copy, so the whole run plays debug to keep its records. --debug forces debug. The first line of
  stdout says which. Debug timing differs from release: measure with it, never score with it.
  --per-job: games per Condor job (default 25; each job builds its bots once, ~35 s at -j8), raised so one run never queues
  more than CQB_MAX_JOBS (40) jobs. --cpus: per job (8). Before submitting it waits while our Condor jobs would pass 400
  or more than CQB_IDLE_MAX (60) cqbatch jobs already wait.
Project (cambc.toml, sdk, cmake): the nearest directory up from the current one that holds cambc.toml, else the 4.0.0
workspace /data/USER/work301_4.0.0. Bot directories are shipped as source (no .cambc / build dirs).
--fast (2 Nov: small diag and firing runs waited 15-20 min): at most FAST_MAX games, Condor priority FAST_PRIO, ahead of waiting pilots and readmany, and no wait for
other cqbatch jobs to clear. It only orders our own waiting jobs: slots still have to free up. Not for scoring runs; those belong in condab.
Stdout: every job's run-batch lines, then a summary. Exit 0 when every job returned, 1 otherwise (failed jobs are named).
Inputs and outputs travel by Condor file transfer between /data/USER/cqb/RUN (the schedd is this machine) and the node,
so nothing touches the home quota. The node CLI is byte-identical to /data/USER/cambc400/bin/cambc400 and compiled modules
come from a node-local wasmtime cache: the same games as a local run. Condor priority 5: after pilots (shipcheck, drift,
BIG legs) and UB audits.
"""
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

LAB = os.path.dirname(os.path.abspath(__file__))
NODE_SH = os.environ.get("CQB_NODE_SH") or os.path.join(LAB, "cqbatch_node.sh")  # 10 Nov: override to test a node script before it goes live
PILOT_STAGE, WINDOW = "/homes/USER/condor-runs/stage", 8
ROOT = "/data/USER/cqb"
WS = "/data/USER/work301_4.0.0"
SKIP = re.compile(r"/(\.cambc|build|target|compile_commands\.json|\.ubbuilt|\.built)$")
VALUED = {"--rounds", "--fuel-quantum", "--log-limit", "--timeout"}
FLAGS = {"--release", "--json"}
FAST_MAX, FAST_PRIO = 200, "12"  # above pilots' 10 and readmany's 8, below fresh sets' 15 and identity's 20
RELEASE_PRIO = "10"  # 9 Nov 21:40Z: a release run (an agent's read, e.g. b1771's HVG re-read) went at 5, below every other read, got no pilot in
# 90 min during the backlog and timed out with 0 games; reads (inforead) run at 10, so release cqbatch runs now do too
DEBUG_PRIO = "9"  # 10 Nov 19:3xZ (Builder: Step 0 diags must never hold a ship confirm; 906 debug items at 11 sat over CONFIRM and lh legs at 10): 9, under every ship leg (10-12), over readmany 8. Was 11: 9 Nov (Builder; owner: faster iteration): --debug runs (step-0 firing/diag measurement) went at 5 (key 495), behind agents' 1,200-game
# score reads at 10; a step-0 measure decides what gets built, so it goes ahead of reads (key 489), still behind shipcheck legs and panels
PILOT_PRIO = 10  # a run above this skips the idle-job wait: it goes ahead of those jobs anyway (2 Nov: two trunk identities sat 19 min unsubmitted at priority 20)
DIAG_BLOCKS = 4  # debug_block lines in a normal bot's source (live, trunks and spars have 0-4)
NODE_OUT = re.compile(r"/tmp/USER-cqb-\d+/res/out/(\d+)\.(repl26a|json)")


def die(msg):
    print("cqbatch: " + msg, file=sys.stderr)
    sys.exit(2)


def condor_env():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import condorroute  # 5 Nov HOST: no local schedd -> the HOST route (pilotd's), or every condor_q failed with CEDAR:6001
    env = condorroute.env()
    cc = env.get("KRB5CCNAME", "")
    path = cc[5:] if cc.startswith("FILE:") else cc
    if not (path and os.path.exists(path)):
        files = sorted(glob.glob(f"/tmp/krb5cc_{os.getuid()}_*"), key=os.path.getmtime)
        if files:
            env["KRB5CCNAME"] = "FILE:" + files[-1]
    return env


MAX_JOBS = int(os.environ.get("CQB_MAX_JOBS", 40))
IDLE_MAX = int(os.environ.get("CQB_IDLE_MAX", 60))  # our idle cqbatch jobs (all runs) above this: wait before submitting
CAP = 400  # condab's CAP: our queued Condor jobs (condor-work/reports/condor_selfservice.md)


def wait_room(k, t0, wait_max, idle_max=IDLE_MAX):
    """Before submitting k jobs: wait while our Condor jobs + k would pass CAP, or while more than IDLE_MAX cqbatch jobs
    already wait in the queue (31 Oct 02:30, Builder: 400+ idle cqbatch jobs made condab refuse two shipchecks' legs)."""
    said = False
    while time.time() - t0 < wait_max:
        q = subprocess.run(["condor_q", "-af", "JobBatchName", "JobStatus"], capture_output=True, text=True, env=condor_env())
        if q.returncode == 0:
            rows = [ln.split() for ln in q.stdout.splitlines() if ln.strip()]
            ours = sum(1 for f in rows if len(f) >= 2 and f[1] in ("1", "2"))
            idle = sum(1 for f in rows if len(f) >= 2 and f[1] == "1" and f[0].startswith("cqb_"))
            if ours + k <= CAP and idle <= idle_max:
                return
            if not said:
                print(f"## cqbatch: waiting for room ({ours} of our jobs queued, {idle} cqbatch jobs idle; caps {CAP} / "
                      f"{idle_max})", flush=True)
                said = True
        time.sleep(30)
    die(f"no room on Condor within {wait_max} s")


def project_dir():
    """The nearest project up from the cwd whose cambc.toml is SDK 4.0.0 (the CLI's), else the 4.0.0 workspace. 31 Oct: the
    repo root /homes/USER/cambc is an SDK 2.2.5 project, and a batch run from there shipped the old SDK (builds failed)."""
    d = os.getcwd()
    while d != "/":
        t = os.path.join(d, "cambc.toml")
        if os.path.isfile(t) and os.path.isdir(os.path.join(d, "sdk")):
            if re.search(r'^sdk_version\s*=\s*"4\.0\.0"', open(t).read(), re.M):
                return d
            print(f"## cqbatch: {d} is not an SDK 4.0.0 project ({t}): using {WS}", file=sys.stderr)
            return WS
        d = os.path.dirname(d)
    return WS


def parse_args(a):
    man, rb, opt = None, [], dict(per_job=25, cpus=8, wait_max=5400)
    i = 0
    while i < len(a):
        x = a[i]
        if x in ("--per-job", "--cpus", "--wait-max"):
            opt[x[2:].replace("-", "_")] = int(a[i + 1])
            i += 2
        elif x in VALUED:
            rb += [x, a[i + 1]]
            i += 2
        elif x in FLAGS:
            rb.append(x)
            i += 1
        elif x == "--fast":
            opt["fast"] = True
            i += 1
        elif x == "--debug":
            opt["debug"] = True
            i += 1
        elif x == "--jobs":  # a local run-batch's --jobs: ignored (each Condor job uses --cpus)
            i += 2
        elif x.startswith("-"):
            die(f"unknown option {x} (see the usage at the top of {__file__})")
        elif man is None:
            man = x
            i += 1
        else:
            die(f"unexpected argument {x}")
    if not man:
        sys.exit(__doc__)
    return man, rb, opt


def read_manifest(man):
    games, bots, maps = [], {}, {}
    for n, ln in enumerate(open(man), 1):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        t = shlex.split(ln)
        if len(t) < 4:
            die(f"{man}:{n}: needs BOT_A BOT_B MAP REPLAY")
        a, b, m, rep, rest = t[0], t[1], t[2], t[3], t[4:]
        stat, extra = None, []
        j = 0
        while j < len(rest):
            if rest[j] == "--statistics":
                stat = os.path.abspath(rest[j + 1])
                j += 2
            else:
                extra.append(rest[j])
                j += 1
        names = []
        for p in (a, b):
            src = os.path.realpath(p)
            if not os.path.isdir(src):
                die(f"{man}:{n}: no bot directory {p}")
            nm = os.path.basename(os.path.abspath(p).rstrip("/"))
            if bots.setdefault(nm, src) != src:
                die(f"{man}:{n}: two different bot directories are both called {nm}: {bots[nm]} and {src}")
            names.append(nm)
        msrc = os.path.realpath(m)
        if not os.path.isfile(msrc):
            die(f"{man}:{n}: no map file {m}")
        mn = os.path.basename(m)
        if maps.setdefault(mn, msrc) != msrc:
            die(f"{man}:{n}: two different map files are both called {mn}")
        games.append(dict(a=names[0], b=names[1], m=mn, rep=os.path.abspath(rep), stat=stat, extra=extra))
    if not games:
        die(f"{man}: no games")
    # 6 Nov (Combat, rpe): 400 lines named 44 replays; each game overwrote the last and the summary still said 400 of 400
    outs = [p for x in games for p in (x["rep"], x["stat"]) if p]
    dup = sorted({p for p in outs if outs.count(p) > 1}) if len(set(outs)) != len(outs) else []
    if dup:
        die(f"{man}: {len(outs)} output paths, only {len(set(outs))} distinct: games would overwrite each other, e.g. {dup[0]}")
    return games, bots, maps


def debug_blocks(bot):
    n = 0
    for f in glob.glob(bot + "/src/*"):
        if os.path.isfile(f):
            n += sum("debug_block" in ln for ln in open(f, errors="replace"))
    return n


def choose_build(rb, opt, bots):
    """Adds --release to rb unless the run must play debug, and says which: a score from a debug build is not a score of the bot."""
    if "--release" in rb:
        if opt.get("debug"):
            die("--release and --debug together")
        print("## cqbatch build: release", flush=True)
        return
    diag = sorted(nm for nm, src in bots.items() if debug_blocks(src) > DIAG_BLOCKS)
    if opt.get("debug") or diag:
        print(f"## cqbatch build: DEBUG ({'--debug' if opt.get('debug') else 'diag copy ' + diag[0]}): measure with these games, never score them", flush=True)
        return
    rb.append("--release")
    print("## cqbatch build: release (debug_block skipped; add --debug if a diag copy's records are missing)", flush=True)


def main():
    man, rb, opt = parse_args(sys.argv[1:])
    games, bots, maps = read_manifest(man)
    choose_build(rb, opt, bots)
    if "--release" not in rb:  # a debug (measurement) run
        # 9 Nov 17:40Z (owner: 20-minute iterations): 34 debug runs held ~34,000 slow debug games and pilots sat on 25-game debug items while 333
        # shipcheck items waited; a firing count needs a few hundred games. At most CQB_DEBUG_MAX (300; 0 = no cap) games, taken evenly over
        # the manifest (map and seat spread kept); items of 10 games, so pilots turn over and shipcheck legs get slots.
        cap = int(os.environ.get("CQB_DEBUG_MAX", "300"))
        if cap and len(games) > cap:
            # 10 Nov (b1802: 300 maps x 2 seats came back as 300 seat-A games): every second game of an a/b manifest is one seat, so the cap
            # keeps whole MAPS, evenly over the manifest, with all their games (both seats)
            order, by = [], {}
            for i, g in enumerate(games):
                if g["m"] not in by:
                    by[g["m"]] = []
                    order.append(g["m"])
                by[g["m"]].append(i)
            per = max(1, round(len(games) / len(order)))
            nm = max(1, cap // per)
            pick = sorted({int(k * len(order) / nm) for k in range(nm)}) if nm < len(order) else range(len(order))
            keep = sorted(i for k in pick for i in by[order[k]])
            print(f"## cqbatch: debug run capped at {len(keep)} of {len(games)} games: {len(pick)} of {len(order)} maps, every seat "
                  f"(CQB_DEBUG_MAX={cap}; 0 for all)", flush=True)
            games = [games[i] for i in keep]
            used = {g["m"] for g in games}
            maps = {k: v for k, v in maps.items() if k in used}
        if opt["per_job"] == 25:
            opt["per_job"] = 10
    if opt.get("fast") and len(games) > FAST_MAX:
        die(f"--fast is for small runs: {len(games)} games, at most {FAST_MAX}")
    proj = project_dir()
    run = os.path.join(ROOT, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{os.getpid()}")
    os.makedirs(run)
    t0 = time.time()
    with tarfile.open(run + "/in.tgz", "w:gz") as tf:
        for f in ("cambc.toml", "sdk", "cmake"):
            if os.path.exists(os.path.join(proj, f)):
                tf.add(os.path.join(proj, f), "proj/" + f)
        for nm, src in sorted(bots.items()):
            tf.add(src, "proj/bots/" + nm, filter=lambda ti: None if SKIP.search(ti.name) else ti)
        for mn, src in sorted(maps.items()):
            tf.add(os.path.realpath(src), "maps/" + mn)  # 8 Nov: never a symlink into /data (dangles on nodes)
    per = max(opt["per_job"], -(-len(games) // MAX_JOBS))  # at most MAX_JOBS Condor jobs per run (31 Oct: a 3,500-game
    chunks = [list(range(i, min(i + per, len(games)))) for i in range(0, len(games), per)]  # manifest queued 140 jobs)
    for k, ids in enumerate(chunks):
        with open(f"{run}/manifest_{k}.txt", "w") as fh:
            for g in ids:
                x = games[g]
                fh.write(f"@W@/proj/bots/{x['a']} @W@/proj/bots/{x['b']} @W@/maps/{x['m']} @W@/res/out/{g}.repl26a"
                         + (f" --statistics @W@/res/out/{g}.json" if x["stat"] else "")
                         + "".join(" " + shlex.quote(e) for e in x["extra"]) + "\n")
    args = " ".join(rb)
    open(run + "/job.sub", "w").write(f"""universe = vanilla
executable = {NODE_SH}
arguments = "in.tgz out_$(Process).tgz {opt['cpus']} manifest_$(Process).txt {args}"
initialdir = {run}
transfer_input_files = in.tgz, manifest_$(Process).txt
transfer_output_files = out_$(Process).tgz
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
output = node_$(Process).out
error = node_$(Process).err
log = job.log
request_cpus = {opt['cpus']}
request_memory = 12000
priority = {os.environ.get("CQB_PRIO") or os.environ.get("READ_PRIO") or (FAST_PRIO if opt.get("fast") else DEBUG_PRIO if opt.get("debug") else RELEASE_PRIO)}
batch_name = cqb_{os.path.basename(man)[:40]}
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22")
getenv = True
queue {len(chunks)}
""")
    prio = int(os.environ.get("CQB_PRIO") or os.environ.get("READ_PRIO") or (FAST_PRIO if opt.get("fast") else DEBUG_PRIO if opt.get("debug") else RELEASE_PRIO))
    pd, pl, heal_st, last_heal, cl = None, None, {}, time.time(), None
    if os.environ.get("CQB_PILOT", "1") == "1":
        # 2 Nov: pilots hold the pool's slots, so a job waited for one for 15+ min, up to an hour for big kept runs. All go through the pilot queue; files stay on the home only while they play, at most WINDOW items at a time.
        try:
            sys.path.insert(0, LAB)
            import pilotd as pl
            if not pl.alive_pilots():
                # 6 Nov (b1340): with no pilot alive the direct jobs below were HELD ('Failed to initialize user log'): on HOST the
                # schedd is HOST's, which can't see this machine's /data run dir. A running pilotd starts pilots for queued items,
                # as condab relies on: queue them and mark demand.
                hb = pl.mtime(pl.q("pilotd.hb"))
                if hb is not None and time.time() - hb < 300:
                    pl.demand()
                else:
                    pl = None
        except Exception:  # noqa: BLE001  the normal submit still works
            pl = None
    if pl:
        pd = f"{PILOT_STAGE}/{os.path.basename(run)}"
        os.makedirs(pd)
        shutil.copy(run + "/in.tgz", pd)
        items = []
        for k in range(len(chunks)):
            shutil.copy(f"{run}/manifest_{k}.txt", pd)
            open(f"{pd}/job_{k}.sh", "w").write(f"cp {pd}/in.tgz {pd}/manifest_{k}.txt . && sh {NODE_SH} in.tgz out.tgz \"$1\" manifest_{k}.txt {args} && "
                                                f"cp out.tgz {pd}/.out_{k}.tmp && mv {pd}/.out_{k}.tmp {pd}/out_{k}.tgz\n")
            items.append((k, [f"run:{pd}/job_{k}.sh", opt["cpus"]]))
        todo = list(items)
        sent, bids = [], []
        print(f"## cqbatch: {len(games)} games, {len(bots)} bots, {len(maps)} maps -> {len(chunks)} pilot items, {WINDOW} at a time; run dir {run}", flush=True)
    else:
        sys.path.insert(0, LAB)
        import condorroute
        if not condorroute.local_schedd():
            die("no pilotd heartbeat and this machine has no schedd: direct jobs would go to a remote schedd that can't open the "
                f"run dir {run} (local /data) and be HELD. Start pilotd (CLAUDE.md §6) or set CQB_PILOT=1 with pilotd up")
        wait_room(len(chunks), t0, opt["wait_max"], 10 ** 9 if prio > PILOT_PRIO else IDLE_MAX)
        r = subprocess.run(["condor_submit", run + "/job.sub"], capture_output=True, text=True, env=condor_env(), cwd=run)
        m = re.search(r"submitted to cluster (\d+)", r.stdout)
        if r.returncode or not m:
            die(f"condor_submit failed: {(r.stdout + r.stderr).strip()[-300:]}")
        cl = m.group(1)
        print(f"## cqbatch: {len(games)} games, {len(bots)} bots, {len(maps)} maps -> {len(chunks)} Condor jobs (cluster {cl}, "
              f"{opt['cpus']} cpus each); run dir {run}", flush=True)
    pending, failed, moved, missing = set(range(len(chunks))), [], 0, 0
    absent = {}
    last_prog = t0  # 9 Nov (b1774 buf-run: 'job 12 not done after 5400 s' while its items waited at key 495): on the pilots the budget runs
    # from the last finished item, so a run still making progress behind higher-priority work is not killed; a stalled run still ends
    while pending:
        if time.time() - (max(t0, last_prog) if pd else t0) > opt["wait_max"]:
            if cl:
                subprocess.run(["condor_rm", cl], capture_output=True, env=condor_env())
            failed += [(k, f"not done after {opt['wait_max']} s") for k in sorted(pending)]
            break
        if pd:
            room = WINDOW - sum(1 for it in sent if it[0] in pending)
            if todo and room > 0:
                now, todo = todo[:room], todo[room:]
                bids.append(pl.enqueue(pd, now, prio))
                sent += now
        time.sleep(float(os.environ.get("CQB_POLL", 10)) if pd else 15)  # 9 Nov 17:56Z: 3 -> 10 s; 30+ runs polling the NFS home every 3 s
        # put HOST's load at 77-114 with the CPU 86% idle (tasks blocked on NFS getattr); a result now lands up to 7 s later
        if pd:
            for k in sorted(pending):
                if os.path.exists(f"{pd}/out_{k}.tgz"):
                    shutil.move(f"{pd}/out_{k}.tgz", f"{run}/out_{k}.tgz")
                    last_prog = time.time()
            if time.time() - last_heal > 60:
                last_heal = time.time()
                nb, _ = pl.heal(bids, pd, [it for it in sent if it[0] in pending], prio, heal_st)
                if nb:
                    bids.append(nb)
            if not any(os.path.exists(f"{run}/out_{k}.tgz") for k in pending):
                continue
        q = subprocess.run(["condor_q", cl, "-af", "ProcId", "JobStatus", "HoldReason"], capture_output=True, text=True,
                           env=condor_env()) if cl else subprocess.CompletedProcess([], 0, "", "")
        if q.returncode != 0:
            continue
        inq = {}
        for ln in q.stdout.splitlines():
            f = ln.split(None, 2)
            if f and f[0].isdigit():
                inq[int(f[0])] = (f[1] if len(f) > 1 else "", f[2] if len(f) > 2 else "")
        for k in sorted(pending):
            st, why = inq.get(k, (None, ""))
            if st == "5":
                subprocess.run(["condor_rm", f"{cl}.{k}"], capture_output=True, env=condor_env())
                failed.append((k, "held: " + why.strip()[:200]))
                pending.discard(k)
                continue
            if st is not None:
                continue
            out = f"{run}/out_{k}.tgz"
            if pd and not os.path.exists(out):
                continue
            if not os.path.exists(out):
                absent[k] = absent.get(k, 0) + 1
                if absent[k] >= 3:
                    failed.append((k, "left the queue without output"))
                    pending.discard(k)
                continue
            res = f"{run}/res_{k}"
            with tarfile.open(out) as tf:
                tf.extractall(res, filter="data")
            for ln in open(res + "/run.log", errors="replace"):  # node paths -> the paths the manifest named
                sys.stdout.write(NODE_OUT.sub(lambda mm: games[int(mm.group(1))]["rep" if mm.group(2) == "repl26a" else "stat"]
                                              or mm.group(0), ln))
            rc = open(res + "/rc").read().strip()
            for g in chunks[k]:
                x = games[g]
                for src, dst in ((f"{res}/out/{g}.repl26a", x["rep"]), (f"{res}/out/{g}.json", x["stat"])):
                    if dst and os.path.exists(src):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.move(src, dst)
                        moved += src.endswith(".repl26a")
                    elif dst:
                        missing += 1
                el = f"{res}/out/{g}.repl26a.error.log"  # 6 Nov: runners die by SIGTERM with no sender known; this log is the evidence and was thrown away with res
                if x["rep"] and os.path.exists(el):
                    os.makedirs(os.path.dirname(x["rep"]), exist_ok=True)
                    shutil.move(el, x["rep"] + ".error.log")
            if rc not in ("0",):
                failed.append((k, f"run-batch exit {rc} (log above)"))
            shutil.rmtree(res, ignore_errors=True)
            os.remove(out)
            pending.discard(k)
            sys.stdout.flush()
    moved = sum(1 for x in games if x["rep"] and os.path.exists(x["rep"]))  # what is on disk now, not what was moved
    print(f"## cqbatch: {moved} of {len(games)} replays written, {missing} expected files missing, {len(failed)} failed jobs, "
          f"wall {time.time() - t0:.0f} s", flush=True)
    for k, why in failed:
        print(f"## cqbatch: job {k} ({len(chunks[k])} games) FAILED: {why}; node log {run}/node_{k}.err", flush=True)
    if pd:
        shutil.rmtree(pd, ignore_errors=True)
    if not failed:
        shutil.rmtree(run, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
