#!/usr/bin/env python3
"""readmany: run a replay reader over many games on Condor nodes, in parallel, off HOST. Tool builder, 2 Nov.

usage: python3 -I tools/lab/readmany.py READER.py SOURCE... --out OUT.jsonl [--per-job 20] [--wait-max 3600]
       python3 -I tools/lab/readmany.py --resume RUN --out OUT.jsonl   (7 Nov) read again only the chunks of run dir RUN that have no
         output (RUN is printed on the first line: /data/USER/readmany/runs/...), then write OUT over every game
--wait-max (pilots): the read stops there only when none of its items is queued or running (a wait in a deep queue is not a loss);
  READMANY_HARD (6 h) is the hard stop.
       python3 -I tools/lab/readmany.py --cmd "COMMAND {}" SOURCE... --out OUT.jsonl    (or: tools/lab/rmany "COMMAND {}" SOURCE... --out OUT.jsonl)
--cmd (4 Nov): any script, no read() module needed: COMMAND runs once per replay on a node with {} = the replay path ({seat},
{id}, {map} = its meta); res = its stdout (parsed as JSON when it is JSON) and rc. The script must live under /homes (nodes read
/homes over NFS, not /data). Use it for any reader over more than ~20 replays: local decoding loads HOST (primer RULE READMANY).
READER.py must be ONE self-contained file (12 Nov, Path Finding): only reader.py goes to the nodes, so it may import tools/lab modules
(replay, ...) but not sibling modules or data files next to it; readmany imports it in an empty dir first and exits 2 if that fails, and
a node whose reader import fails writes an err line for every game (no silent wait). Put data inline or under /homes by absolute path.
READER.py defines read(path, meta) -> a JSON-able dict (load the game with replay.load(path, us=meta.get("seat", "A").upper()):
`import replay` works as usual). SOURCE is any of: a live set dir (matches.txt + x_ID/replay.repl26a; meta: id, map, seat, result, set),
a trunkset dir (set.json; meta: map, seat, labels), a run dir with rep/*.repl26a (meta: id), or a text file of replay paths.
OUT gets one line per game: {"path", "meta", "res"} or {"path", "meta", "err"}, in source order; failed games are counted, not dropped.
Nodes cannot read this machine's /data, so such replays reach each job by Condor file transfer (2 Nov, owner: no bitbucket), and decodes are
cached in the node's /tmp (RDEC_CACHE, read by replay.py). 1 CPU per job at nice 10. Run files stay on /data, off the home quota.
--local (Tool builder 2, 4 Nov; Condor down): the jobs run here instead, ONE at a time at nice 19, each waiting while the
1-minute load is above 24 (owner: don't load HOST; READMANY_LOAD sets the limit). Also used by itself when condor_submit
fails. Same output; slow, so keep sets small (a few hundred games)."""
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import traceback

X = "/data/USER/readmany"
XCACHE = "/tmp/USER-rdec"
JOB = """#!/bin/sh
find %s -type f -mmin +720 -delete 2>/dev/null
[ -f in_$1.tar ] && tar -xf in_$1.tar && rm -f in_$1.tar
nice -n 10 python3 -I %s/readmany.py --node reader.py list_$1.jsonl out_$1.jsonl
rc=$?
rm -f reader.py list_$1.jsonl stage_*.repl26a job.sh
exit $rc
"""
LAB = "/homes/USER/cambc/tools/lab"
SHARED = ("/homes/", "/vol/")
SETTLE = 120  # s to wait for outputs NFS hasn't shown yet once the jobs have left the queue


def seat_tag(name):
    """'a' or 'b' from a name ending _A/__b/-B before .repl26a (replay.seat_of's rule), else None."""
    m = re.search(r"[_.\-]([ABab])\.repl26a$", os.path.basename(name))
    return m.group(1).lower() if m else None


def sources(srcs):
    out = []
    for s in srcs:
        if os.path.isfile(os.path.join(s, "set.json")):
            base = json.load(open(os.path.join(s, "set.json")))
            out += [(os.path.join(s, g["replay"]), g) for g in base["games"]]
        elif os.path.isfile(os.path.join(s, "matches.txt")):
            for ln in open(os.path.join(s, "matches.txt")):
                p = ln.split()
                if len(p) >= 3:
                    f = os.path.join(s, "x_" + p[0], "replay.repl26a")
                    if os.path.exists(f):
                        out.append((f, dict(id=p[0], map=p[1], seat=p[2], result=p[3] if len(p) > 3 else "", set=os.path.basename(s.rstrip("/")))))
        elif os.path.isdir(os.path.join(s, "rep")):
            # 3 Nov: the seat from a seat-tagged name (NAME__a / NAME_B, replay.seat_of), since a node reads a staged copy without the name
            out += [(os.path.join(s, "rep", f), dict(id=f[:-8], **({"seat": st} if (st := seat_tag(f)) else {})))
                    for f in sorted(os.listdir(os.path.join(s, "rep"))) if f.endswith(".repl26a")]
        elif os.path.isdir(s) and any(f.endswith(".repl26a") for f in os.listdir(s)):  # a bare dir of replays (e.g. DIR/rep)
            out += [(os.path.join(s, f), dict(id=f[:-8], **({"seat": st} if (st := seat_tag(f)) else {})))
                    for f in sorted(os.listdir(s)) if f.endswith(".repl26a")]
        elif os.path.isfile(s):
            out += [(ln.strip(), {"seat": seat_tag(ln.strip())} if seat_tag(ln.strip()) else {}) for ln in open(s) if ln.strip()]
        else:
            sys.exit(f"readmany: cannot read source {s}")
    return out


def staged(path):
    """(path the job reads, file to send or None): shared paths as they are, others by name in the job's own directory."""
    # 10 Nov (Deep): a symlinked replay was sent as a link (tarfile keeps links), or read through a shared-home link into /data,
    # so the node met a dangling link. Resolve first: send or read the real file; a link to nothing fails here, by name.
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        sys.exit(f"readmany: {path} -> {real}: no such file (dangling link? the target may have stayed on another machine)")
    if real.startswith(SHARED):
        return real, None
    # 11 Nov (Builder/b1979: a reader that took the seat from the file name read team B on every staged copy, .2817 reported as
    # .5217): the staged name keeps the original name after "__", so seat_of and NAME__a / NAME_B slicing still see the seat tag.
    return "stage_" + hashlib.sha1(path.encode()).hexdigest()[:16] + "__" + os.path.basename(path), real


HARD = int(os.environ.get("READMANY_HARD", 6 * 3600))


def pilot_read(run, n, opt, t0, games, window=16):
    """The jobs as pilot items, at most window at a time, staged on the home only while they play. False: no pilot alive, use Condor."""
    try:
        sys.path.insert(0, LAB)
        import pilotd as pl
        if not pl.alive_pilots():
            return False
    except Exception:  # noqa: BLE001
        return False
    pd = f"/homes/USER/condor-runs/stage/rm_{os.path.basename(run)}"
    os.makedirs(pd, exist_ok=True)
    for x in ("reader.py", "job.sh"):
        shutil.copy(f"{run}/{x}", pd)
    print(f"## readmany: {games} games, {n} pilot items, {window} at a time, run {run}", flush=True)
    todo, sent, bids, st, last = [k for k in range(n) if not os.path.exists(f"{run}/out_{k}.jsonl")], [], [], {}, time.time()
    finished, done_at, said = [], {}, 0

    def waiting():  # our items still in the pilot queue or on a pilot: a wait, not a loss
        return sum(1 for x in pl.ls(pl.q("queue")) + pl.ls(pl.q("claimed")) if (pl.parse(x) or (0, 0, ""))[2] in bids)
    try:
        while True:
            left = [k for k in sent if not os.path.exists(f"{run}/out_{k}.jsonl")]
            if not todo and not left:
                break
            el = time.time() - t0
            # 7 Nov (Deep's fci_new: 550 games 'job lost' after 1,800 s, every item still queued behind a deep queue): --wait-max
            # ends the read only when none of its items is queued or running; READMANY_HARD (6 h) is the hard stop
            if el > HARD or (el > opt["wait"] and not todo and not waiting()):
                print(f"## readmany: stopping after {el:.0f} s with {len(left)} item(s) not back ({'hard limit' if el > HARD else 'none queued or running'})", flush=True)
                break
            if el > opt["wait"] and time.time() - said > 600:
                said = time.time()
                print(f"## readmany: past --wait-max ({opt['wait']} s) with {waiting()} item(s) still queued or running: waiting (a wait is not a loss); "
                      f"resume later with --resume {run}", flush=True)
            now = todo[:window - len(left)]
            todo = todo[len(now):]
            items = []
            for k in now:
                shutil.copy(f"{run}/list_{k}.jsonl", pd)
                shutil.copy(f"{run}/in_{k}.tar", pd)
                open(f"{pd}/job_{k}.sh", "w").write(f"cp {pd}/reader.py {pd}/job.sh {pd}/list_{k}.jsonl {pd}/in_{k}.tar . && sh job.sh {k}; cp out_{k}.jsonl {pd}/.o_{k} && mv {pd}/.o_{k} {pd}/out_{k}.jsonl; rm -f {pd}/in_{k}.tar\n")
                items.append((k, [f"run:{pd}/job_{k}.sh", 1]))
            if items:
                bids.append(pl.enqueue(pd, items, min(12, int(os.environ.get('READ_PRIO') or 11))))  # 10 Nov (Deep): READ_PRIO honoured, capped at 12 (ship legs' top)  # just behind a shipcheck, ahead of gate legs: a reader item takes seconds
                sent += now
            for k in left:
                if os.path.exists(f"{pd}/out_{k}.jsonl"):
                    shutil.move(f"{pd}/out_{k}.jsonl", f"{run}/out_{k}.jsonl")
                    finished.append(k)
            for k in finished[:]:  # 3 Nov (home at 50k files: 3 stage files per item until a read's end, 5,500 across 11 reads): gone once an item is home
                pout = f"{pd}/job_p{k:04d}.out"
                for f in (f"{pd}/job_{k}.sh", f"{pd}/list_{k}.jsonl", f"{pd}/in_{k}.tar", f"{run}/in_{k}.tar", pout):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                if not os.path.exists(pout) and time.time() - done_at.setdefault(k, time.time()) > 30:  # the pilot's .out lands just after the output
                    finished.remove(k)
            if time.time() - last > 60:
                last = time.time()
                nb, _ = pl.heal(bids, pd, [(k, [f"run:{pd}/job_{k}.sh", 1]) for k in left], 11, st)
                if nb:
                    bids.append(nb)
            time.sleep(3)
    finally:
        shutil.rmtree(pd, ignore_errors=True)
    return True


CMD_READER = """# generated by readmany --cmd: run a command per replay and return its output
import json
import subprocess
CMD = %s


def read(path, meta):
    cmd = CMD.replace("{}", path)
    for k in ("seat", "id", "map"):
        cmd = cmd.replace("{" + k + "}", str(meta.get(k, "")))
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=900)
    out = r.stdout.strip()
    try:
        out = json.loads(out)
    except ValueError:
        pass
    d = dict(rc=r.returncode, out=out)
    if r.returncode:
        d["stderr"] = r.stderr[-600:]
    return d
"""


def node(reader, lst, out):
    """Runs on the node: one line per game, written as it finishes."""
    os.environ["RDEC_CACHE"] = XCACHE
    sys.path.insert(0, LAB)
    sp = importlib.util.spec_from_file_location("reader_mod", reader)
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, os.path.dirname(os.path.abspath(reader)))
    try:
        sp.loader.exec_module(m)
    except Exception:  # noqa: BLE001  12 Nov: a reader that cannot import returns an err per game, not a silent hang
        e = "reader import failed on the node: " + traceback.format_exc()[-400:]
        with open(out + ".part", "w") as f:
            for ln in open(lst):
                g = json.loads(ln)
                f.write(json.dumps(dict(i=g["i"], path=g.get("path"), meta=g.get("meta"), err=e)) + "\n")
        os.replace(out + ".part", out)
        return
    # 13 Nov (TB; Prism: four top3_v825 replays, e.g. 01a1d062 04sanctum, failed to decode and took their whole chunk down, 60-75 games
    # lost each time): each game gets READMANY_GAME_TIMEOUT (300) s; a hang becomes that game's err line, not the chunk's job timeout
    import signal

    def _alarm(*_):
        raise TimeoutError(f"game read over {os.environ.get('READMANY_GAME_TIMEOUT', '300')} s (decode hang?)")
    signal.signal(signal.SIGALRM, _alarm)
    with open(out + ".part", "w") as f:
        for ln in open(lst):
            g = json.loads(ln)
            try:
                signal.alarm(int(os.environ.get("READMANY_GAME_TIMEOUT", 300)))
                try:
                    res_ = m.read(g["run"], g["meta"])
                finally:
                    signal.alarm(0)
                f.write(json.dumps(dict(i=g["i"], path=g.get("path"), meta=g.get("meta"), res=res_)) + "\n")
            except Exception:  # noqa: BLE001  (one bad game must not lose the job)
                f.write(json.dumps(dict(i=g["i"], path=g.get("path"), meta=g.get("meta"), err=traceback.format_exc()[-400:])) + "\n")
            # 9 Nov (Builder, b1766): path + meta in every chunk record, so a stuck run's out_*.jsonl is readable without joining list_*.jsonl
            f.flush()
    os.replace(out + ".part", out)


def local_read(run, chunks, t0, wait):
    """Each chunk as a local job, one at a time, nice 19, load-gated; replays read in place (this machine has /data)."""
    lim = float(os.environ.get("READMANY_LOAD", "24"))
    print(f"## readmany: {sum(map(len, chunks))} games, {len(chunks)} local jobs one at a time (nice 19, load <= {lim:g}), run {run}", flush=True)
    for k, ch in enumerate(chunks):
        with open(f"{run}/list_{k}.jsonl", "w") as f:
            f.writelines(json.dumps(dict(r, run=r["path"])) + "\n" for r in ch)
        while float(open("/proc/loadavg").read().split()[0]) > lim and time.time() - t0 < wait:
            time.sleep(20)
        if time.time() - t0 >= wait:
            print(f"## readmany: --wait-max reached after {k} of {len(chunks)} local jobs", flush=True)
            return
        subprocess.run(["nice", "-n", "19", sys.executable, "-I", os.path.abspath(__file__), "--node", f"{run}/reader.py",
                        f"{run}/list_{k}.jsonl", f"{run}/out_{k}.jsonl"], cwd=run)


def settle(run, n, wait=None):
    """Wait until this client sees all n outputs, or for wait s. Our own create and delete make the NFS client re-read the directory."""
    end = time.time() + (SETTLE if wait is None else wait)
    while True:
        p = f"{run}/.poke.{os.getpid()}"
        try:
            open(p, "w").close()
            os.unlink(p)
        except OSError:
            pass
        names = set(os.listdir(run))
        if all(f"out_{k}.jsonl" in names for k in range(n)) or time.time() > end:
            return
        time.sleep(5)


def main():
    a = sys.argv[1:]
    if a[:1] == ["--node"]:
        return node(*a[1:4])
    opt = dict(per=20, wait=3600)
    local = "--local" in a
    if local:
        a.remove("--local")
    for flag, key in (("--per-job", "per"), ("--wait-max", "wait")):
        if flag in a:
            i = a.index(flag)
            opt[key] = int(a[i + 1])
            del a[i:i + 2]
    resume = None
    if "--resume" in a:
        i = a.index("--resume")
        resume = os.path.abspath(a[i + 1])
        del a[i:i + 2]
    if "--out" not in a or (resume is None and len(a) < (3 if "--cmd" in a else 4)):
        sys.exit(__doc__)
    i = a.index("--out")
    out = os.path.abspath(a[i + 1])
    del a[i:i + 2]
    if resume:
        return resume_main(resume, out, opt, local)
    cmd = None
    if "--cmd" in a:
        i = a.index("--cmd")
        cmd = a[i + 1]
        del a[i:i + 2]
        a.insert(0, "")  # placeholder for READER
    reader, srcs = os.path.abspath(a[0]) if a[0] else "", a[1:]
    games = sources(srcs)
    if not games:
        sys.exit("readmany: no games")
    run = f"{X}/runs/{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}_{os.getpid()}"
    os.makedirs(run)
    rd = f"{run}/reader.py"  # a private copy: the reader may be on /data, and an edit must not change a running batch
    if cmd is not None:
        open(rd, "w").write(CMD_READER % repr(cmd))
    else:
        shutil.copyfile(reader, rd)
    # 12 Nov (Path Finding: a reader importing a sibling file failed on every node and the read waited 26 min): import the private copy
    # alone, as a node does, before staging anything; a failure stops here with the error.
    pre = subprocess.run([sys.executable, "-I", "-c", f"import importlib.util,sys; sys.path.insert(0,{LAB!r}); sys.path.insert(0,{run!r}); "
                          f"sp=importlib.util.spec_from_file_location('reader_mod',{rd!r}); m=importlib.util.module_from_spec(sp); "
                          "sp.loader.exec_module(m); assert hasattr(m,'read'), 'reader defines no read(path, meta)'"],
                         cwd=run, capture_output=True, text=True, timeout=300)
    if pre.returncode:
        sys.exit(f"readmany: the reader does not import on its own (nodes get only reader.py; no sibling files): {pre.stderr.strip()[-600:]}")
    t0 = time.time()
    rows = [dict(i=k, path=p, run=staged(p)[0], meta=m) for k, (p, m) in enumerate(games)]
    chunks = [rows[k:k + opt["per"]] for k in range(0, len(rows), opt["per"])]
    inputs = []
    for k, ch in enumerate(chunks):
        with open(f"{run}/list_{k}.jsonl", "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in ch)
        send = [(r["run"], staged(r["path"])[1]) for r in ch if staged(r["path"])[1]]
        if send and not local:  # local jobs read /data in place
            with tarfile.open(f"{run}/in_{k}.tar", "w") as t:
                for name, p in send:
                    t.add(p, arcname=name)
        inputs.append(k)
    open(f"{run}/job.sh", "w").write(JOB % (XCACHE, LAB))
    os.chmod(f"{run}/job.sh", 0o755)
    open(f"{run}/noinput.tar", "wb").write(b"\0" * 10240)
    for k in inputs:
        if not os.path.exists(f"{run}/in_{k}.tar"):
            os.link(f"{run}/noinput.tar", f"{run}/in_{k}.tar")  # an empty tar: every job names the same input list
    sub = f"{run}/job.sub"
    open(sub, "w").write(f"""universe = vanilla
executable = {run}/job.sh
arguments = $(Process)
transfer_input_files = reader.py, list_$(Process).jsonl, in_$(Process).tar
initialdir = {run}
output = job_$(Process).out
error = job_$(Process).err
log = job.log
request_cpus = 1
request_memory = 3000
priority = 8
batch_name = readmany
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22")
getenv = True
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
periodic_remove = (time() - QDate) > {opt['wait']}
queue {len(chunks)}
""")
    env = dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", ""))
    if local:
        local_read(run, chunks, t0, opt["wait"])
    elif not pilot_read(run, len(chunks), opt, t0, len(rows)):  # 2 Nov: pilots hold the pool's slots, so reader jobs waited for one
        r = subprocess.run(["condor_submit", sub], capture_output=True, text=True, env=env)
        m = re.search(r"submitted to cluster (\d+)", r.stdout)
        if not m:
            print(f"## readmany: condor_submit failed ({(r.stdout + r.stderr).strip()[-160:]}); reading locally", flush=True)
            local_read(run, chunks, t0, opt["wait"])
        else:
            print(f"## readmany: {len(rows)} games, {len(chunks)} jobs, cluster {m.group(1)}, run {run}", flush=True)
            while time.time() - t0 < opt["wait"]:
                done = sum(os.path.exists(f"{run}/out_{k}.jsonl") for k in range(len(chunks)))
                if done == len(chunks):
                    break
                q = subprocess.run(["condor_q", m.group(1), "-af", "JobStatus"], capture_output=True, text=True, env=env).stdout.split()
                if not q:  # the cluster has left the queue: nothing more will arrive, but NFS can hide what did (2 Nov: 0 of 160 "lost", every output there)
                    settle(run, len(chunks))
                    break
                time.sleep(10)
            else:
                subprocess.run(["condor_rm", m.group(1)], capture_output=True, env=env)
                settle(run, len(chunks), SETTLE // 4)
    return finish(run, chunks, rows, out, t0)


def seat_mismatch(meta, res):
    """11 Nov guard: True when a result dict states its side ("seat" A/B, or "us" 0/1) and that differs from the seat in meta."""
    sm = str((meta or {}).get("seat", "")).upper()
    if sm not in ("A", "B") or not isinstance(res, dict):
        return False
    r = res.get("seat")
    if isinstance(r, str) and r.upper() in ("A", "B"):
        return r.upper() != sm
    r = res.get("us")
    if isinstance(r, int) and not isinstance(r, bool) and r in (0, 1):
        return r != "AB".index(sm)
    return False


def finish(run, chunks, rows, out, t0):
    res = {}
    for k in range(len(chunks)):
        p = f"{run}/out_{k}.jsonl"
        for ln in open(p) if os.path.exists(p) else ():
            d = json.loads(ln)
            res[d["i"]] = d
    for f in glob.glob(f"{run}/in_*.tar") + [f"{run}/noinput.tar"]:  # read: the sent replays are copies
        try:
            os.remove(f)
        except OSError:
            pass
    bad = 0
    mis = []
    with open(out + ".part", "w") as f:
        for g in rows:
            d = res.get(g["i"])
            if d is None or "res" not in d:
                bad += 1
            elif seat_mismatch(g["meta"], d["res"]):
                mis.append(g["path"])
            f.write(json.dumps(dict(path=g["path"], meta=g["meta"], **({"res": d["res"]} if d and "res" in d else {"err": (d or {}).get("err", "job lost")}))) + "\n")
    os.replace(out + ".part", out)
    print(f"## readmany: {len(rows) - bad} of {len(rows)} read, {bad} failed, wall {time.time() - t0:.0f} s -> {out}")
    if mis:
        print(f"## readmany: SEAT MISMATCH in {len(mis)} of {len(rows)} results: the reader's us/seat is not the seat readmany passed "
              f"(take it from meta: replay.reader_seat(path, meta)); first {mis[0]}")
        return 2
    return 0 if bad == 0 else 1


def build_inputs(run, chunks, local):
    """in_k.tar for each chunk not yet read (the replays nodes cannot read on /data)"""
    for k, ch in enumerate(chunks):
        if os.path.exists(f"{run}/out_{k}.jsonl"):
            continue
        send = [(r["run"], staged(r["path"])[1]) for r in ch if staged(r["path"])[1]]
        if send and not local:
            with tarfile.open(f"{run}/in_{k}.tar", "w") as t:
                for name, p in send:
                    t.add(p, arcname=name)
        elif not os.path.exists(f"{run}/in_{k}.tar"):
            open(f"{run}/in_{k}.tar", "wb").write(b"\0" * 10240)


def resume_main(run, out, opt, local):
    """--resume RUN (7 Nov): read again the chunks of an earlier run that have no output, then write OUT over all of them"""
    ks = sorted(int(re.search(r"list_(\d+)\.jsonl$", f).group(1)) for f in glob.glob(f"{run}/list_*.jsonl"))
    if not ks or not os.path.exists(f"{run}/reader.py") or not os.path.exists(f"{run}/job.sh"):
        sys.exit(f"readmany: {run} is not a readmany run dir (list_*.jsonl, reader.py, job.sh)")
    chunks = [[json.loads(x) for x in open(f"{run}/list_{k}.jsonl")] for k in ks]
    rows = [r for ch in chunks for r in ch]
    todo = [k for k in ks if not os.path.exists(f"{run}/out_{k}.jsonl")]
    print(f"## readmany: resume {run}: {len(todo)} of {len(ks)} chunks to read", flush=True)
    t0 = time.time()
    build_inputs(run, chunks, local)
    if todo:
        if local:
            local_read(run, chunks, t0, opt["wait"])
        elif not pilot_read(run, len(chunks), opt, t0, len(rows)):
            print("## readmany: no pilot alive: reading locally", flush=True)
            local_read(run, chunks, t0, opt["wait"])
    return finish(run, chunks, rows, out, t0)


if __name__ == "__main__":
    sys.exit(main())
