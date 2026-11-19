#!/usr/bin/env python3
"""cxefarm: play a list of cxe games on the Condor pilots instead of this machine (Tool builder, 6 Nov; owner: "speeding up testing time
allows more tests which allow more certainty"). Measured that morning: maple02 (16 cores, shared with another user's 5 gem5 jobs) sat at
load 25-27, so local cxe tools waited at the load gate (estcheck's build 45 min), while the pilots were busy only 52% of their time
(queue empty 65% of checks since 06Z). Generalises loopprof's condor_play: any tool's games, any per-game env, any output files.

Python use (stackprof / fuelprof / estcheck / loopprof):
    import cxefarm
    games = [dict(id=k, a=SO_A, b=SO_B, map=MAP, env={"CXE_STACKPROF": "@D@/sp.tsv"}, args=["--fuel-log"],
                  files={"sp.tsv": f"{out}/sp_{k}.tsv", "g.repl26a": f"{out}/g{k}.repl26a"}), ...]
    cxefarm.run(games, say=print)        -> number of games whose files came back (None: no pilotd: play locally)
  Each game runs in its own node dir D: `cxe A B MAP D/g ARGS` with @D@ in env values and args replaced by D; files maps a name under D to
  the local path it is copied to. A .so path ending in .gz is unpacked on the node. decode=True also writes D/g.dec.json (cxe --decode); decode=["g", "g.alt0"] decodes each D/NAME.repl26a to D/NAME.dec.json (fork branches); libs=[SO, ...] stages extra libraries, named in args as "@SO:SO@" (cxe --alt). With a decode list, a decoded replay not in files is removed on the node. Items are gzipped tars, unpacked and removed as they
  arrive, so the home stage stays small (home quota: condab refuses batches at 10 GB).
Home files (6 Nov: parallel batches took home 49k -> 59k in minutes, a keeper read died on Errno 122): one jobs.sh per batch (items are byte ranges of it, condab_node.sh
  run:FILE:OFFSET:LENGTH), at most CXEFARM_WINDOW items out at once (256), job_p*.out removed as results arrive, results unpacked on /data. A batch waits in a queue before staging,
  and stops feeding, while the home holds more than CXEFARM_HOME_FILES (54,000); after `wait` seconds at the gate run() returns None (local play).
CLI: python3 -I tools/cxe/cxefarm.py --selftest   (8 games v nochase2 on the pilots, compared byte for byte with the same games run locally)
Env: CXEFARM=0 makes run() return None (local play), CXEFARM=1 always uses the pilots; by default a run goes to the pilots when it has
>= CXEFARM_MIN games (40) or this machine's load is >= CXEFARM_LOAD (20). CXEFARM_PER (games per item, 6), CXEFARM_CPUS (per item, 6)."""
import fcntl
import glob
import gzip
import hashlib
import json
import os
import threading
import re
import shutil
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lab"))
STAGE = "/homes/zw4424/condor-runs/stage"
SD = STAGE + "/shared"  # 11 Nov (TB 6ad907): content-addressed maps tars and bot .so.gz shared by batches; quotaguard reaps files untouched 6 h
SHARED = os.environ.get("CXEFARM_SHARED", "1") != "0"


def _touch(p):
    try:
        os.utime(p)
    except OSError:
        pass
XTMP = "/data/zw4424/st/cxe/farmx"  # results are unpacked here, not on the home
GATE = "/data/zw4424/st/cxe/farm_home_gate.lock"
GATE_LOG = "/data/zw4424/st/bq/home_gate.log"  # who waited on the home, with the numbers. Not preflight_hold: this wait is normal queuing (6 Nov: it set off healthwatch's condab alarm at 54k)
HOME_MAX = int(os.environ.get("CXEFARM_HOME_FILES", 58000))  # 12 Nov (TB): 54,000 -> 55,500 -> 57,500 -> 58,000 (22:5xZ: 375 pilots churn ~2.5k files); soft 60k, hard 61k
WINDOW = int(os.environ.get("CXEFARM_WINDOW", 256))
PRIO = int(os.environ.get("CXEFARM_PRIO", 9))  # 6 Nov: was 12, level with shipcheck's panel legs and over its deciding reads (11): 1,000 screen items sat in front of a ship. Now below reads (10)


def _id_opp():
    sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
    import idopp
    return idopp.id_opp()


def _so_arg(x, libs):
    """An arg '@SO:/local/path.so@' -> the node's copy of that library (it must be in the game's libs)."""
    if x.startswith("@SO:") and x.endswith("@"):
        return f"$PWD/{libs[x[4:-1]]}.so"
    return x


def pilotd_up():
    import pilotd as pl
    hb = pl.mtime(pl.q("pilotd.hb"))
    return hb is not None and time.time() - hb < 300


_hq = [0.0, 0]


def home_files():
    """files on the home, read at most every 15 s; 0 when unreadable (never blocks on a broken quota read)"""
    if time.time() - _hq[0] > 15:
        import homequota
        _hq[:] = [time.time(), (homequota.home_quota() or {}).get("files", 0)]
    return _hq[1]


def gate_log(msg):
    try:
        with open(GATE_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}\n")
    except OSError:
        pass


def wait_home(say, wait):
    """The queue in front of staging: waiters line up on one lock, the head polls the home. -> False after `wait` s"""
    if home_files() <= HOME_MAX:
        return True
    t0 = time.time()
    say(f"cxefarm: home {home_files()} files > {HOME_MAX}: waiting to stage")
    gate_log(f"cxefarm pid {os.getpid()}: home {home_files()} files > {HOME_MAX}: waiting")
    with open(GATE, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        while home_files() > HOME_MAX:
            if time.time() - t0 > wait:
                say(f"cxefarm: home still {home_files()} files after {wait} s")
                return False
            time.sleep(15)
    say(f"cxefarm: home {home_files()} files: staging after {time.time() - t0:.0f} s")
    gate_log(f"cxefarm pid {os.getpid()}: home {home_files()} files: staged after {time.time() - t0:.0f} s")
    return True


def run(games, say=print, wait=7200, per=None, cpus=None, prio=PRIO):
    """-> games whose files all came back, or None when pilots can't be used (the caller plays locally)."""
    if os.environ.get("CXEFARM", "1") == "0" or not games or not pilotd_up():
        return None
    # pilots cost ~30 s of pickup and staging: a small run on an unloaded machine is faster here (6 games: 2 s local v 33 s)
    load = float(open("/proc/loadavg").read().split()[0])
    if os.environ.get("CXEFARM") != "1" and len(games) < int(os.environ.get("CXEFARM_MIN", 40)) and load < float(os.environ.get("CXEFARM_LOAD", 20)):
        return None
    import cxecondab
    import pilotd as pl
    try:
        pl.reap_maybe()  # 7 Nov: batches of killed callers leave the queue within ~2 min of the next run anywhere
    except Exception:  # noqa: BLE001
        pass
    per = per or int(os.environ.get("CXEFARM_PER", 6))
    cpus = cpus or int(os.environ.get("CXEFARM_CPUS", 6))
    if not wait_home(say, wait):
        return None
    rt, _ = cxecondab.stage_condor([], lambda *x: None)
    pd = f"{STAGE}/cf_{os.getpid()}_{time.time_ns()}"  # ns, not s: changedprobe's batch threads start in the same second (7 Nov: the second makedirs failed, its games read as lost)
    xd = f"{XTMP}/{os.path.basename(pd)}"
    bids = []
    os.makedirs(pd)
    if SHARED:
        os.makedirs(SD, exist_ok=True)
    os.makedirs(xd)
    try:
        libs, maps = {}, {}
        for g in games:  # libraries by content (gzipped once), maps by path
            for s in [g["a"], g["b"]] + list(g.get("libs") or []):  # libs: extra .so files an arg names as @SO:path@ (fork alts)
                if s not in libs:
                    h = hashlib.sha1(open(s, "rb").read()).hexdigest()[:16]
                    dst = f"{SD if SHARED else pd}/{h}.so.gz"
                    if not os.path.exists(dst):
                        tmp = f"{dst}.tmp{os.getpid()}_{threading.get_ident()}"  # 11 Nov: per thread (changedprobe batches share a pid; a shared tmp name lost a rename)
                        if s.endswith(".gz"):
                            shutil.copyfile(s, tmp)
                        else:
                            with open(s, "rb") as fi, gzip.open(tmp, "wb", compresslevel=6) as fo:
                                shutil.copyfileobj(fi, fo)
                        os.replace(tmp, dst)
                    elif SHARED:
                        _touch(dst)
                    libs[s] = h
            maps.setdefault(g["map"], f"m{len(maps)}.map26a")
        mt = f"{pd}/maps.tar"
        if SHARED:  # 11 Nov (TB 6ad907): one tar per map set, shared by every batch that plays it (23 batches held the same 25 MB tar)
            k = hashlib.sha1()
            for m, nm in maps.items():
                st = os.stat(os.path.realpath(m))
                k.update(f"{nm}\0{os.path.realpath(m)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
            mt = f"{SD}/maps_{k.hexdigest()[:20]}.tar"
        if not (SHARED and os.path.exists(mt)):
            tmp = f"{mt}.tmp{os.getpid()}_{threading.get_ident()}"
            with tarfile.open(tmp, "w") as t:
                for m, nm in maps.items():
                    t.add(os.path.realpath(m), arcname=nm)  # 8 Nov (b1651): a symlinked map went in as a link to /data, dangling on the node: 0 of 160 games in 4 s
            os.replace(tmp, mt)
        else:
            _touch(mt)
        lp = SD if SHARED else pd  # where the .so.gz files live
        cxe = f'"{rt}/ld-linux-x86-64.so.2" --library-path "{rt}" "{rt}/cxe"'
        # SLOT PAR (7 Nov, game throughput): an item ran a fixed `xargs -P cpus` (8) on slots of 8-40 cores (static slots: a pilot
        # holds the whole machine, ~15 cores on average) and waited for its slowest game; now it runs "$1" games at once, the
        # pilot's slot_par (cores - 1, capped by free memory), and big batches use wider items so the slowest-game tail is shared.
        # CXEFARM_SLOTPAR=0: the old fixed width. Games are fuel-bound and deterministic at any parallelism (slot_par note, 2 Nov).
        slotpar = os.environ.get("CXEFARM_SLOTPAR", "1") != "0"
        wide = int(os.environ.get("CXEFARM_WIDE", 24))
        if slotpar and len(games) >= 10 * wide:
            per = max(per, wide)
        chunks = [games[i:i + per] for i in range(0, len(games), per)]
        px = f'"${{1:-{cpus}}}"' if slotpar else str(cpus)  # the node passes the pilot's slot_par as $1
        items, want, pos = [], {}, 0
        jobs = open(f"{pd}/jobs.sh", "wb")
        for i, ch in enumerate(chunks):
            hs = sorted({libs[g["a"]] for g in ch} | {libs[g["b"]] for g in ch} | {libs[x] for g in ch for x in (g.get("libs") or [])})
            ms = sorted({maps[g["map"]] for g in ch})
            # SO CACHE (7 Nov): a node keeps each bot .so it unzipped in /var/tmp/zw4424-socache by content hash (a hit is a local copy, no
            # NFS read or gunzip: ~25% of a 24-game item); cached only while /tmp has > 4 GB free, pruned after 3 h unused;
            # pilotd's tmp_ok drops it when /tmp runs low. CXEFARM_SOCACHE=0: unzip every time, as before.
            if os.environ.get("CXEFARM_SOCACHE", "1") != "0":
                sh = [f"tar -xf {mt} {' '.join(ms)} || exit 1",
                      "C=/var/tmp/zw4424-socache; mkdir -p $C 2>/dev/null && find $C -name '*.so' -mmin +180 -delete 2>/dev/null"]
                sh += [f"if [ -s $C/{h}.so ]; then touch $C/{h}.so; cp $C/{h}.so {h}.so || exit 1; else gzip -dc {lp}/{h}.so.gz > {h}.so || exit 1; "
                       f"[ \"$(df -Pm /var/tmp | awk 'NR==2{{print $4}}')\" -gt 4000 ] 2>/dev/null && cp {h}.so $C/.{h}.$$ && mv $C/.{h}.$$ $C/{h}.so; fi" for h in hs]
            else:
                sh = [f"tar -xf {mt} {' '.join(ms)} || exit 1"] + [f"gzip -dc {lp}/{h}.so.gz > {h}.so || exit 1" for h in hs]
            for g in ch:
                d = f"w{g['id']}"
                env = " ".join(f"{k}=\"{str(v).replace('@D@', '$PWD/' + d)}\"" for k, v in (g.get("env") or {}).items())
                args = " ".join(f"\"{_so_arg(str(x), libs).replace('@D@', '$PWD/' + d)}\"" for x in (g.get("args") or []))
                sh.append(f"mkdir -p {d} && echo 'cd \"$PWD\" && {env} nice -n 10 {cxe} \"$PWD/{libs[g['a']]}.so\" \"$PWD/{libs[g['b']]}.so\" "
                          f"\"$PWD/{maps[g['map']]}\" \"$PWD/{d}/g\" {args} > \"$PWD/{d}/stdout\" 2>&1"
                          + "".join(f" ; nice -n 10 {cxe} --decode \"$PWD/{d}/{nm}.repl26a\" \"$PWD/{d}/{nm}.dec.json\""
                                    + ("" if g.get("decode") is True or f"{nm}.repl26a" in (g.get("files") or {}) else f" ; rm -f \"$PWD/{d}/{nm}.repl26a\"")
                                    for nm in ((["g"] if g.get("decode") is True else list(g.get("decode") or []))))  # 11 Nov: decode may list names (eventfork: g, g.alt0, g.alt1)
                          + (f" ; sha1sum < \"$PWD/{d}/g.repl26a\" | cut -c1-40 > \"$PWD/{d}/g.sha1\"" + ("" if "g.repl26a" in (g.get("files") or {}) else f" ; rm -f \"$PWD/{d}/g.repl26a\"") if g.get("digest") else "")  # digest=True: only the replay's hash comes back (7 Nov: 96% of a game's bytes)
                          + (f" ; awk '\\''NR>1 && $1==1 && $6>0 {{u=(NF>=23 ? $23 : $7); b=int(100*u/$6); if(b>100)b=100; c[$3\" \"b]++}} END{{for(k in c)print k, c[k]}}'\\'' \"$PWD/{d}/g.fuel.tsv\" > \"$PWD/{d}/g.fsum\" ; awk '\\''NR>1 && $1==1 && $6>0 {{b=int(100*$7/$6); if(b>100)b=100; c[$3\" \"b]++}} END{{for(k in c)print k, c[k]}}'\\'' \"$PWD/{d}/g.fuel.tsv\" > \"$PWD/{d}/g.fsumw\""
                             f" ; rm -f \"$PWD/{d}/g.fuel.tsv\" \"$PWD/{d}/g.repl26a\"" if g.get("fuelsum") else "")  # fuelsum=True (heavyfuel): a 100-bin histogram of play turns' fuel per team, not ~1 MB of log
                          + f"' > {d}.sh")  # decode=True: the replay is decoded on the node too (6 Nov: ~30 local decodes took maple02 to load 36)
                want[g["id"]] = (i, g)
            sh.append(f"ls -d w*.sh | xargs -P {px} -n 1 sh")
            sh.append(f"tar -czf out.tgz w*/ && cp out.tgz {pd}/.o_{i} && mv {pd}/.o_{i} {pd}/out_{i}.tgz")
            body = ("\n".join(sh) + "\n").encode()
            jobs.write(body)
            items.append((i, [f"run:{pd}/jobs.sh:{pos}:{len(body)}", cpus]))
            pos += len(body)
        jobs.close()
        pl.demand()
        st, t0, last, sent, healed = {}, time.time(), time.time(), 0, False
        done, got, lost = set(), 0, []
        retried = {}
        say(f"cxefarm: {len(games)} games as {len(items)} pilot items ({per} a item, {cpus} cpus, {WINDOW} out at once), stage {pd}")
        while len(done) < len(chunks) and time.time() - t0 < wait:
            room = min(WINDOW - (sent - len(done)), len(items) - sent)
            if room >= min(max(1, WINDOW // 4), len(items) - sent) and room > 0 and (sent == 0 or home_files() <= HOME_MAX):  # top-ups of a quarter window: pilotd moves a batch of <= 2 items to the front
                b = pl.enqueue(pd, items[sent:sent + room], prio)
                sent += room
                bids.append(b)
            elif sent == len(done) and sent < len(items):
                t0 += 2  # held at the home limit with nothing out: a queue, not a timeout
            pl.poke(pd)
            names = set(os.listdir(pd))
            for n in names:  # a finished item's pilot output: only the heal of an unfinished item reads these
                m = re.fullmatch(r"job_p(\d+)\.out", n)
                if m and int(m[1]) in done:
                    try:
                        os.remove(f"{pd}/{n}")
                    except OSError:
                        pass
            for i in range(sent):
                if i in done or f"out_{i}.tgz" not in names:
                    continue
                p = f"{pd}/out_{i}.tgz"
                tmp = f"{xd}/x_{i}"
                with tarfile.open(p) as t:
                    t.extractall(tmp, filter="data")
                os.remove(p)
                for g in chunks[i]:
                    d, ok, gone = f"{tmp}/w{g['id']}", True, []
                    for nm, dst in (g.get("files") or {}).items():
                        if os.path.exists(f"{d}/{nm}"):
                            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                            shutil.move(f"{d}/{nm}", dst)
                        else:
                            ok = False
                            gone.append(nm)
                    for nm, dst in (g.get("optfiles") or {}).items():  # 12 Nov (PCQ): files a game writes only sometimes (OUT.cphase.tsv)
                        if os.path.exists(f"{d}/{nm}"):
                            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                            shutil.move(f"{d}/{nm}", dst)
                    got += ok
                    if not ok and len(lost) < 20:  # 8 Nov: 8 items 'finished' in 4 s with 0 of 160 games and nothing said why: the game's own stdout does
                        try:
                            tail = open(f"{d}/stdout", errors="replace").read()[-300:].strip()
                        except OSError:
                            tail = "(no stdout: the game never started)"
                        lost.append(f"game {g['id']} {os.path.basename(g['map'])}: missing {','.join(gone)}: {tail}")
                shutil.rmtree(tmp, ignore_errors=True)
                done.add(i)
            if time.time() - last > 60:
                last = time.time()
                # 13 Nov (TB, shipchecks 13916/13917/13945 waited 60-80 min): an item that ENDED without its out_N.tgz (rc 1 'Stale file handle' on
                # the shared .so, rc 2 'Unterminated quoted string' reading jobs.sh over NFS) counts as done for pilotd.heal (done_parts reads only
                # '## end'), so it was never queued again and the batch waited for its 2 h timeout. Re-queue such an item, at most 2 times each.
                for i in range(sent):
                    jo = f"{pd}/job_p{i:04d}.out"
                    if i in done or f"out_{i}.tgz" in names or retried.get(i, 0) >= 2 or not os.path.exists(jo):
                        continue
                    try:
                        ended = "## end" in open(jo, errors="replace").read() and time.time() - os.path.getmtime(jo) > 60
                    except OSError:
                        ended = False
                    if not ended or os.path.exists(f"{pd}/out_{i}.tgz"):
                        continue
                    retried[i] = retried.get(i, 0) + 1
                    try:
                        tail = open(jo, errors="replace").read().strip().splitlines()[-4:-2]
                        os.rename(jo, f"{jo}.fail{retried[i]}")
                    except (OSError, IndexError):
                        tail = []
                    getattr(pl, "_DONE", {}).get(pd, set()).discard(i)
                    bids.append(pl.enqueue(pd, [items[i]], prio))
                    say(f"cxefarm: item {i} ended with no output ({' | '.join(t.strip()[:90] for t in tail)}): queued again ({retried[i]} of 2)")
                left = [it for it in items[:sent] if it[0] not in done]
                nb, _ = pl.heal(bids, pd, left, prio, st)
                if nb:
                    bids.append(nb)
                    healed = True
            time.sleep(2)
        why = ""
        if got < len(games):  # 7 Nov (b006: 8,578 of 9,730 'lost', Deep's readmany): say WHY on the same line callers already log
            names = pl.ls(pl.q("queue"))
            mine = set(bids)
            nq = sum(1 for n in names if (pl.parse(n) or (0, 0, ""))[2] in mine)
            nc = sum(1 for n in pl.ls(pl.q("claimed")) if (pl.parse(n) or (0, 0, ""))[2] in mine)
            short = sum(1 for i in done for g in chunks[i]) - got
            why = (f"; INCOMPLETE: " + ", ".join(x for x in (
                f"wait {wait} s ran out with {nq} item(s) never started (priority {prio}, pilot queue {len(names)} items: starved)" if nq else "",
                f"{nc} item(s) still running" if nc else "",
                f"{len(chunks) - len(done) - nq - nc} item(s) not sent (window/home limit)" if len(chunks) - len(done) - nq - nc > 0 else "",
                f"{short} game(s) missing from finished items (node or engine failure)" if short > 0 else "") if x))
            try:
                with open("/data/zw4424/st/bq/batchfail.jsonl", "a") as f:  # healthwatch alarms on a batch short by > 5%
                    f.write(json.dumps(dict(t=time.time(), pid=os.getpid(), stage=os.path.basename(pd), games=len(games), back=got, items=len(chunks),
                                            done=len(done), queued=nq, running=nc, short=short, prio=prio, wait=wait, qdepth=len(names),
                                            caller=" ".join(sys.argv)[:200])) + "\n")
            except OSError:
                pass
            if short > 0:  # 8 Nov (Tool builder 2): 15 batches came back 0 of 160 from FINISHED items and the stage (job logs) was gone
                try:       # before anyone could look: keep the job logs and the jobs script on /data (newest 40 batches)
                    kd = os.path.join("/data/zw4424/st/bq/cxefarm_short", os.path.basename(pd))
                    os.makedirs(kd, exist_ok=True)
                    for f in glob.glob(os.path.join(pd, "job_p*.out")) + [os.path.join(pd, "jobs.sh")]:
                        if os.path.isfile(f) and os.path.getsize(f) < 5_000_000:
                            shutil.copy(f, kd)
                    old = sorted(glob.glob("/data/zw4424/st/bq/cxefarm_short/*"), key=os.path.getmtime)[:-40]
                    for o in old:
                        shutil.rmtree(o, ignore_errors=True)
                    if lost:
                        with open(os.path.join(kd, "lost_games.txt"), "w") as f:
                            f.write("\n".join(lost) + "\n")
                    why += f"; first lost {lost[0][:200]!r}" if lost else ""
                    why += f"; job logs kept in {kd}"
                except OSError:
                    pass
        say(f"cxefarm: {got} of {len(games)} games back from {len(done)} of {len(chunks)} items in {time.time() - t0:.0f} s{why}")
        if len(done) == len(chunks) and not healed:
            bids.clear()  # nothing left queued: no cancel marker (~800 batches an hour, markers live 6 h, on the home quota)
        return got
    finally:
        for b in bids:  # 6 Nov: a caller leaving early deleted the stage but not its queued items: pilots ran 856 items with no script (rc 2) and recreated the folder for their job_p*.out
            pl.cancel(b)
        if os.environ.get("CXEFARM_KEEP") == "1":  # 8 Nov: keep the stage (job_p*.out, files) to debug a short batch
            say(f"cxefarm: CXEFARM_KEEP=1: stage kept at {pd}")
        else:
            shutil.rmtree(pd, ignore_errors=True)
            shutil.rmtree(xd, ignore_errors=True)


def selftest():
    import random
    import subprocess
    import cxebuild
    live = open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    so_a, so_b, exe = cxebuild.build_bot(live), cxebuild.build_bot(_id_opp()), cxebuild.build_host()
    md = "/data/zw4424/ablproj_4.0.0/maps"
    ms = random.Random(5).sample(sorted(f for f in os.listdir(md) if f.endswith(".map26a")), 4)
    out = f"/data/zw4424/st/cxe/farmtest_{os.getpid()}"
    os.makedirs(out)
    games = [dict(id=2 * i + s, a=so_a if s == 0 else so_b, b=so_b if s == 0 else so_a, map=f"{md}/{m}",
                  env={"CXE_FUELPROF": "@D@/fp.tsv"}, files={"g.repl26a": f"{out}/farm_{2 * i + s}.repl26a"})
             for i, m in enumerate(ms) for s in (0, 1)]
    t0 = time.time()
    os.environ['CXEFARM'] = '1'
    n = run(games)
    t1 = time.time()
    same = 0
    for g in games:
        k = g["id"]
        subprocess.run([exe, g["a"], g["b"], g["map"], f"{out}/loc_{k}"], capture_output=True)
        a, b = f"{out}/farm_{k}.repl26a", f"{out}/loc_{k}.repl26a"
        same += os.path.exists(a) and os.path.exists(b) and open(a, "rb").read() == open(b, "rb").read()
    print(f"cxefarm selftest: {n} of {len(games)} back in {t1 - t0:.0f} s; {same}/{len(games)} replays identical to local cxe")
    shutil.rmtree(out, ignore_errors=True)
    return 0 if same == len(games) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(__doc__)
