"""cxecondab: the cxe backend of tools/lab/condab.py (CONDAB_ENGINE=cxe). Plays a condab batch on HOST with cxe
instead of Condor and returns the same {game index: CQ record} condab builds from the CLI's statistics, so every
consumer (gate, stylepanel, inforead, shipcheck legs, the game index) reads it unchanged.
Guards (any one sends the whole batch back to Condor, as before):
  - /data/USER/st/cxe/STATUS says FAIL (the regular check found a game that differs from the CLI)
  - CLI spot-check: CXE_SPOT (default 2%, at least CXE_SPOT_MIN=4) of the batch's games are re-played with the
    official CLI (run-batch --release, its default fuel) and must give the same record (winner, rounds, every metric)
  - a build or game failure
Interim looks run at the same shares of the batch as on Condor (condab LOOKS), so early stops behave the same.
Games take the machine-wide cxe slots (CXE_SLOTS, default 8), shared by every caller."""
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cxebuild  # noqa: E402

STATUS = os.path.join(cxebuild.ROOT, "STATUS")
XMAPS = os.path.join(cxebuild.ROOT, "xmaps")
WS_MAPS = "/data/USER/ablproj_4.0.0/maps"


def unpack(xmaps):
    """condab's on-the-fly map pack (<xmaps>.tar) -> a dir of its maps (cached by pack name)."""
    d = os.path.join(XMAPS, os.path.basename(xmaps))
    if not os.path.isdir(d):
        tmp = f"{d}.{os.getpid()}.tmp"
        os.makedirs(tmp, exist_ok=True)
        with tarfile.open(xmaps + ".tar") as tf:
            tf.extractall(tmp, filter="data")
        try:
            os.replace(tmp, d)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        try:
            os.utime(d)  # 9 Nov: a reused dir counts as in use (the age rule below kept idle dirs 6 h and could drop busy ones)
        except OSError:
            pass
    try:  # 12 Nov 21:1xZ (Builder: /data 99%; xmaps held 34 GB = ~3 h of packs): 1 h while /data has < 40 GB free
        age = 3600 if shutil.disk_usage(XMAPS).free < 40 * 2 ** 30 else 3 * 3600
    except OSError:
        age = 3 * 3600
    for f in os.listdir(XMAPS):  # untouched 3 h: gone (9 Nov: 6 h held 25 GB on /data)
        p = os.path.join(XMAPS, f)
        try:
            if time.time() - os.path.getmtime(p) > age and not f.endswith(".tmp"):
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
    os.utime(d)
    return d


def rounds_arg(path):
    """' --rounds N' for an on-the-fly map game under condab's OTF_ROUNDS (saved-map games never), as the Condor nodes do."""
    cap = os.environ.get("OTF_ROUNDS", "")
    return f" --rounds {cap}" if cap.isdigit() and os.path.realpath(path).startswith(os.path.realpath(XMAPS) + "/") else ""


def map_path(m, xdir, proj):
    for d in ([xdir] if xdir else []) + [os.path.join(proj, "maps"), WS_MAPS]:
        p = os.path.join(d, m + ".map26a")
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"map {m}")


def map_paths(games, xdir, proj):
    """[map_path(m, xdir, proj) for each game], once per map and on threads (8 Nov: one stat per game over NFS, serially, twice a batch). A missing map still raises."""
    import concurrent.futures as cf
    ms = sorted({g[2] for g in games})
    with cf.ThreadPoolExecutor(max(1, int(os.environ.get("CONDAB_SYNC_THREADS", "32")))) as ex:
        found = dict(zip(ms, ex.map(lambda m: map_path(m, xdir, proj), ms)))
    return [found[g[2]] for g in games]


def local_batches():
    """Local cxe batches playing now (one cxerun.py each; spot-check re-plays are CLI runs, not counted)."""
    n, me = 0, os.getuid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat("/proc/" + pid).st_uid == me and b"cxerun.py" in open(f"/proc/{pid}/cmdline", "rb").read() \
                    and b"/cxe/m" in open(f"/proc/{pid}/cmdline", "rb").read():
                n += 1
        except OSError:
            pass
    return n


def play(out, games, say, look, stop, xmaps, proj, looks, record, force=False):
    """-> (got, stopped) like condab.play; None to fall back to the CLI on Condor; "condor" to play cxe on Condor instead
    (local cxe busy: CXE_LOCAL_MAX, default 3, batches already share HOST's CXE_SLOTS; 4 Nov 58 inforead batches queued
    on 8 slots of the 16-core machine while ~100 Condor pilots idled). record(gid, a, b, map, stats_json) -> CQ dict."""
    if os.path.exists(STATUS) and open(STATUS).read().startswith("FAIL"):
        say("cxe backend: the regular cxe check is FAIL: Condor")
        return None
    if not force:
        # owner 4 Nov ~20:30Z: while Condor is back, use it as much as possible: with CXE_CONDOR_PILOTS (4) pilots alive, an
        # --engine cxe batch plays cxe on the Condor nodes (the local slots stay for my tools and starved times)
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lab"))
            import pilotd
            np = len(pilotd.alive_pilots())
        except Exception:  # noqa: BLE001
            np = 0
        if np >= int(os.environ.get("CXE_CONDOR_PILOTS", "4")):
            say(f"cxe backend: {np} Condor pilots alive: cxe on Condor")
            return "condor"
    busy, load = local_batches(), os.getloadavg()[0]
    # force: Condor has no pilots (condab), so local is the only fast way; cxerun's slot cap (4 while load > 40) still holds
    if not force and (busy >= int(os.environ.get("CXE_LOCAL_MAX", "3")) or load > float(os.environ.get("CXE_LOAD_MAX", "24"))):
        say(f"cxe backend: {busy} local cxe batches running, load {load:.0f}: cxe on Condor instead")
        return "condor"
    t0 = time.time()
    xdir = unpack(xmaps) if xmaps else None
    bots = sorted({g[0] for g in games} | {g[1] for g in games})
    so = {b: cxebuild.build_bot(b) for b in bots}
    exe = cxebuild.build_host()
    t_build = time.time() - t0
    wd = os.path.join(cxebuild.ROOT, "work", os.path.basename(out.rstrip("/")))  # on /data: a mark's replays (~44 MB a
    # batch) under out/ on the home filled its 10 GB quota on 4 Nov with 58 batches at once
    os.makedirs(wd, exist_ok=True)
    n = len(games)
    paths = [map_path(m, xdir, proj) for _, _, m in games]
    marks = sorted({max(1, math.ceil(f * n)) for f in looks} | {n})
    got, stopped, done, looked = {}, None, 0, set()
    jobs = int(os.environ.get("CXE_JOBS", "8"))
    for mark in marks:
        man = os.path.join(wd, f"m{mark}.txt")
        with open(man, "w") as f:
            for j in range(done, mark):
                a, b, m = games[j]
                f.write(f"{so[a]} {so[b]} {paths[j]} {wd}/{j + 1}{rounds_arg(paths[j])}\n")
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "cxerun.py"), man, "--jobs", str(jobs), "--statistics"],
                           capture_output=True, text=True)
        for j in range(done, mark):
            a, b, m = games[j]
            g = record(j + 1, a, b, m, f"{wd}/{j + 1}.json")
            if not g.get("ok"):
                say(f"cxe backend: game {j + 1} failed ({g.get('err', '')[:100]}; {r.stdout[-200:]}): Condor")
                shutil.rmtree(wd, ignore_errors=True)
                return None
            got[j + 1] = g
            for ext in (".repl26a", ".json"):
                if os.path.exists(f"{wd}/{j + 1}{ext}"):
                    os.remove(f"{wd}/{j + 1}{ext}")
        done = mark
        due = [f for f in looks if f not in looked and done >= math.ceil(f * n)]
        if look and due and done < n:
            looked.update(due)
            lines, dec, _ = look(got)
            for line in ([lines] if isinstance(lines, str) else lines):
                say(f"INTERIM {int(round(100 * due[-1]))}% of games ({done}/{n}, cxe): {line}")
            if dec and stop:
                stopped = (int(round(100 * done / n)), dec)
                say(f"STOP: decided {dec} at {done}/{n} games (cxe)")
                break
    shutil.rmtree(wd, ignore_errors=True)
    t_cxe = time.time() - t0
    ok, note = spot_check(out, games, got, paths, bots, record, jobs, f"engine cxe: {len(got)} games in {t_cxe - t_build:.0f} s (+ {t_build:.0f} s builds)")
    if not ok:
        say(note)
        return None
    say(note)
    return got, stopped


def _spot_k(n):
    # 10 Nov ~23:05Z (owner: "lighten the main machine"): above CXE_SPOT_LOAD (40) 1-min load, the minimum sample of 2 games
    # (still every batch, still game by game against the CLI); the full 0.5% only when the machine has room
    try:  # 10 Nov ~23:58Z (TB 6ad907: 84-97 spot games queued behind the local slots, the testing bottleneck): 1 game while the local slot
        # queue (cxerun's WAIT dir) holds more than CXE_SPOT_QUEUE (20) waiters; still every batch, still game by game against the CLI
        if len(os.listdir(os.path.join(cxebuild.ROOT, "slots", "wait"))) > int(os.environ.get("CXE_SPOT_QUEUE", "20")):
            return min(n, 1)
    except OSError:
        pass
    try:
        if os.getloadavg()[0] > float(os.environ.get("CXE_SPOT_LOAD", "40")):
            return min(n, int(os.environ.get("CXE_SPOT_MIN_LOADED", "2")))
    except OSError:
        pass
    # 9 Nov (/var 95%: root's syslog logs every process start; a 16,294-game leg's 0.5% = 82 local CLI games, ~10 starts/s with the other legs):
    # at most CXE_SPOT_MAX (24) games per batch. Every batch is still checked game by game against the CLI.
    k = max(int(os.environ.get("CXE_SPOT_MIN", "4")), math.ceil(float(os.environ.get("CXE_SPOT", "0.005")) * n))
    try:  # /var nearly full: the minimum sample only, until it recovers
        st = os.statvfs("/var")
        if st.f_bavail * st.f_frsize < 3e9:
            return min(n, int(os.environ.get("CXE_SPOT_MIN", "4")))
    except OSError:
        pass
    return min(n, k, int(os.environ.get("CXE_SPOT_MAX", "8")))  # 9 Nov 18:00Z (owner: offload load): 24 -> 8 local CLI games per batch; >= 4 still checked


def _spot_play(sd, games, paths, bots, jobs, sample):
    """The CLI side of a spot-check: each sampled game through the CLI's own match runner (`cambc __run-match`, what run-batch spawns
    after building) on the exact wasm each cxe library was translated from, so no CLI build is needed (4 Nov: background CLI builds of
    every flip were most of HOST's load; runner v cxe checked identical, replay and record). Round-capped games (OTF_ROUNDS, no
    CLI statistics) are also played on cxe for a replay comparison.
    10 Nov (TB): CXE_SPOT_PILOT=1 (default) plays the CLI games on a Condor pilot (one generic pilotd item, _spot_pilot); any game it
    does not bring back within CXE_SPOT_PILOT_WAIT (900 s), or any failure, is played here as before (a note goes to engine.txt).
    CXE_SPOT_PILOT=0: the old local path only."""
    os.makedirs(sd, exist_ok=True)
    wasm = {b: cxebuild.wasm_for(b) for b in bots}
    left = list(sample)
    if os.environ.get("CXE_SPOT_PILOT", "1") not in ("", "0") and sample:
        t0 = time.time()
        try:
            got, why = _spot_pilot(sd, games, paths, wasm, sample)
        except Exception as e:  # noqa: BLE001  never let the pilot path break a batch: the local path below
            got, why = set(), f"error {str(e)[:120]}"
        left = [j for j in sample if j not in got]
        _SPOT_NOTE[sd] = (f"CLI side on a pilot ({len(got)}/{len(sample)} games, {time.time() - t0:.0f} s)" if not left else
                          f"CLI side: pilot {why}; {len(left)}/{len(sample)} games played locally")
    if left:
        _spot_cli_local(sd, games, paths, wasm, jobs, left)
    capped = [j for j in sample if rounds_arg(paths[j - 1])]
    if capped:  # round-capped games: the CLI writes no statistics for them, so compare replays with cxe's at the same cap
        man = os.path.join(sd, "cxe.txt")
        with open(man, "w") as f:
            for j in capped:
                a, b, m = games[j - 1]
                f.write(f"{cxebuild.build_bot(a)} {cxebuild.build_bot(b)} {paths[j - 1]} {sd}/x{j}{rounds_arg(paths[j - 1])}\n")
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "cxerun.py"), man, "--jobs", str(min(jobs, len(capped)))],
                       capture_output=True)
    return capped


_SPOT_NOTE = {}  # spot dir -> where its CLI side played (spot_check adds it to engine.txt)
SPOT_RUNS = "/homes/USER/condor-runs/cxespot"  # nodes read /homes, not /data
NODE_CLI = "/homes/USER/condor-work/bin"  # the CLIs on /homes (cambc500 byte-identical to /data's cambc500)


def _spot_pilot(sd, games, paths, wasm, sample):
    """Play the sampled CLI games on a pilot: wasm + maps staged in a /homes run dir, one generic pilotd item (its own job.sh) at the
    batch's priority + 1 (a 1-item batch also jumps the queue: pilotd's small-batch boost). -> (set of game indices whose CLI output
    is now in sd, reason when short)."""
    import atexit
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lab"))
    import pilotd
    if not pilotd.alive_pilots():
        return set(), "no pilots alive"
    cli = os.path.join(NODE_CLI, os.path.basename(cxebuild.CLI))
    if not os.path.isfile(cli) or os.path.getsize(cli) != os.path.getsize(cxebuild.CLI):
        return set(), f"no /homes copy of {cxebuild.CLI}"
    base = re.sub(r"[^A-Za-z0-9-]", "-", os.path.basename(sd.rstrip("/")))[-28:]
    run = os.path.join(SPOT_RUNS, f"spot-{base}", f"{os.getpid()}_{int(time.time() * 1000)}")
    os.makedirs(os.path.join(run, "out"))
    bid, bids = None, []

    def clean():
        for x in bids:
            try:
                pilotd.cancel(x)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(os.path.dirname(run), ignore_errors=True)
    atexit.register(clean)  # a stopped batch (sys.exit 143) leaves no item queued nor files on /homes
    try:
        wn = {}
        for b, w in wasm.items():
            wn[b] = f"w{len(wn)}.wasm"
            shutil.copyfile(w, os.path.join(run, wn[b]))
        lines = []
        for j in sample:
            a, b, m = games[j - 1]
            mp = f"m{j}.map26a"
            shutil.copyfile(paths[j - 1], os.path.join(run, mp))
            cap = rounds_arg(paths[j - 1]).split()
            lines.append(f"{j} {wn[a]} {wn[b]} {mp} {cap[1] if cap else '4294967295'}\n")
        open(os.path.join(run, "games.txt"), "w").write("".join(lines))
        # the same __run-match command as the local path; node caches in node /tmp or the Condor scratch (no /data on nodes)
        open(os.path.join(run, "job.sh"), "w").write(f"""#!/bin/sh
R={run}
CLI={cli}
export CAMBC_WASMTIME_CACHE=/var/tmp/USER-wtcache
mkdir -p "$CAMBC_WASMTIME_CACHE"
W=$(mktemp -d "${{_CONDOR_SCRATCH_DIR:-/tmp}}/USER-spot-XXXXXX") || exit 1
trap 'rm -rf "$W"' EXIT
one() {{
  od="$W/run_$1"
  (cd "$W" && nice -n 10 "$CLI" __run-match --rounds "$5" --map "$R/$4" --outdir "$od" --log-limit 0 --statistics "$W/$1.json" --json \\
    --label A --argv0 bot.wasm --language cpp --fuel 1 "$R/$2" -- --label B --argv0 bot.wasm --language cpp --fuel 1 "$R/$3" >/dev/null 2>&1)
  echo "game $1 rc $?"
  [ -f "$od/replay.repl26a" ] && cp "$od/replay.repl26a" "$R/out/.$1.repl26a.tmp" && mv "$R/out/.$1.repl26a.tmp" "$R/out/$1.repl26a"
  [ -f "$W/$1.json" ] && cp "$W/$1.json" "$R/out/.$1.json.tmp" && mv "$R/out/.$1.json.tmp" "$R/out/$1.json"
  rm -rf "$od"
}}
P=${{2:-2}}; [ "$P" -gt {len(sample)} ] && P={len(sample)}
n=0
while read j a b m r; do
  one "$j" "$a" "$b" "$m" "$r" &
  n=$((n + 1)); [ $((n % P)) -eq 0 ] && wait
done < "$R/games.txt"
wait
""")
        prio = os.environ.get("CONDAB_PRIO") or os.environ.get("READ_PRIO") or "10"
        prio = int(prio) + 1 if prio.lstrip("-").isdigit() else 11
        item = [(0, ["spot", min(8, len(sample))])]
        bid = pilotd.enqueue(run, item, prio, node=os.path.join(run, "job.sh"))
        bids.append(bid)
        end, st, last = time.time() + float(os.environ.get("CXE_SPOT_PILOT_WAIT", "900")), {}, time.time()
        want = {j: (f"{j}.repl26a" if rounds_arg(paths[j - 1]) else f"{j}.json") for j in sample}
        why = f"timeout {os.environ.get('CXE_SPOT_PILOT_WAIT', '900')} s"
        while time.time() < end:
            if 0 in pilotd.done_parts(run):
                why = "item ended without every game"
                break
            if time.time() - last > 60:  # an item that left the queue with no output (two looks) is queued once more (pilotd.heal
                last = time.time()  # re-queues without the node script, so not that)
                pilotd.poke(pilotd.q("queue"))
                pilotd.poke(pilotd.q("claimed"))
                live = any((pilotd.parse(n) or (0, 0, ""))[2] in bids for n in pilotd.ls(pilotd.q("queue")) + pilotd.ls(pilotd.q("claimed")))
                st["empty"] = 0 if live else st.get("empty", 0) + 1
                if st["empty"] >= 2 and st.get("times", 0) < 1 and 0 not in pilotd.done_parts(run):
                    st["empty"], st["times"] = 0, 1
                    bid = pilotd.enqueue(run, item, prio, node=os.path.join(run, "job.sh"))
                    bids.append(bid)
            time.sleep(3)
        got = set()
        for j, f in want.items():
            src = os.path.join(run, "out", f)
            if os.path.exists(src):
                for e in (".json", ".repl26a"):
                    if os.path.exists(os.path.join(run, "out", f"{j}{e}")):
                        shutil.copyfile(os.path.join(run, "out", f"{j}{e}"), os.path.join(sd, f"{j}{e}"))
                got.add(j)
        return got, why
    finally:
        clean()
        atexit.unregister(clean)


def _spot_cli_local(sd, games, paths, wasm, jobs, sample):
    """The old local CLI side: each game on this machine, in one of cxerun's machine-wide local game slots."""
    import concurrent.futures as cf
    env = dict(os.environ, CAMBC_WASMTIME_CACHE=os.environ.get("CAMBC_WASMTIME_CACHE", "/data/USER/wtcache"))

    def one(j):
        a, b, m = games[j - 1]
        od = os.path.join(sd, f"run_{j}")
        cap = rounds_arg(paths[j - 1]).split()
        cmd = (["nice", "-n", "10", cxebuild.CLI, "__run-match", "--rounds", cap[1] if cap else "4294967295", "--map", paths[j - 1],
                "--outdir", od, "--log-limit", "0", "--statistics", os.path.join(sd, f"{j}.json"), "--json"]
               + ["--label", "A", "--argv0", "bot.wasm", "--language", "cpp", "--fuel", "1", wasm[a], "--"]
               + ["--label", "B", "--argv0", "bot.wasm", "--language", "cpp", "--fuel", "1", wasm[b]])
        import cxerun  # a spot game takes one of the machine-wide local game slots (4 Nov ~23:55Z: 19-spar panels' spot-checks
        lk = cxerun.slot()  # ran 12+ CLI games at once beside cxe's own cap; load hit 272)
        try:
            subprocess.run(cmd, cwd=cxebuild.PROJ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            lk.close()
        rp = os.path.join(od, "replay.repl26a")
        if os.path.exists(rp):
            os.replace(rp, os.path.join(sd, f"{j}.repl26a"))
        shutil.rmtree(od, ignore_errors=True)
    with cf.ThreadPoolExecutor(max(1, min(2, jobs, len(sample)))) as ex:
        list(ex.map(one, sample))


def spot_start(out, games, paths, bots, jobs=8):
    """Start a batch's CLI spot-check while its games play (4 Nov: at the end it added 14 s a batch, and a new flip's first batch waited
    ~6 min for the CLI build): the sample is drawn from every game index up front, the CLI plays it in a background thread.
    -> handle for spot_check(..., pre=handle)."""
    import threading
    n = len(games)
    sample = sorted(random.Random(zlib.crc32(out.encode())).sample(range(1, n + 1), _spot_k(n)))
    h = dict(sample=sample, sd=os.path.join(cxebuild.ROOT, "work", os.path.basename(out.rstrip("/")) + "_spot"), done=threading.Event(),
             capped=[], err=None, t0=time.time())

    def run():
        try:
            h["capped"] = _spot_play(h["sd"], games, paths, bots, jobs, sample)
        except BaseException as e:  # noqa: BLE001
            h["err"] = str(e)[:200]
        finally:
            h["done"].set()
    threading.Thread(target=run, daemon=True).start()
    return h


def spot_check(out, games, got, paths, bots, record, jobs, head, pre=None):
    """Re-play CXE_SPOT (0.5%, >= CXE_SPOT_MIN 4; 4 Nov: 2% made the CLI side 80 s of a 1,200-game leg whose games took 5 s on Condor) of the batch's games with the official CLI on HOST and compare the
    records (winner, rounds, every metric). pre: spot_start's handle (the CLI side already played; only games that came back are
    compared). -> (ok, note); the note also goes to out/engine.txt."""
    t0 = time.time()
    if pre is not None:
        # 10 Nov ~23:55Z (Builder: csw1s/fwb1s/bhd1s/bgr/hli1 lh legs killed at the timebox): all 340 items were back at 23:23 but the
        # leg sat on the pilot spot-check for 20 min. The batch no longer waits on it: CXE_SPOT_GRACE s (60) after the games, else unchecked.
        if not pre["done"].wait(timeout=float(os.environ.get("CXE_SPOT_GRACE", "60"))):
            note = f"{head}; CLI spot-check unchecked (still playing {time.time() - pre['t0']:.0f} s after the batch began; not waited for)"
            open(os.path.join(out, "engine.txt"), "w").write(note + "\n")
            return True, note
        if pre["err"]:
            return False, f"!! {head}; CLI spot-check failed to play ({pre['err']})"
        sample, sd, capped = [j for j in pre["sample"] if j in got], pre["sd"], pre["capped"]
        t0 = pre["t0"]
    else:
        played = sorted(got)
        sample = sorted(random.Random(zlib.crc32(out.encode())).sample(played, _spot_k(len(played))))
        sd = os.path.join(cxebuild.ROOT, "work", os.path.basename(out.rstrip("/")) + "_spot")
        capped = _spot_play(sd, games, paths, bots, jobs, sample)
    k = len(sample)
    bad, nofail = [], []
    for j in sample:
        a, b, m = games[j - 1]
        if j in capped:
            try:
                cr = open(f"{sd}/{j}.repl26a", "rb").read()
                if cr[:2] == b"PK":
                    import io
                    cr = zipfile.ZipFile(io.BytesIO(cr)).read("replay.repl26a")
                same = cr == open(f"{sd}/x{j}.repl26a", "rb").read()
            except (OSError, KeyError, zipfile.BadZipFile):
                same = False
            if not same:
                bad.append(j)
            continue
        c = record(j, a, b, m, f"{sd}/{j}.json")
        x = got[j]
        if isinstance(x, dict) and not x.get("ok"):
            # 13 Nov (TB: 4 of the last 5 CLI fallbacks, lh14790/lh14509/lh14490/fpfsbk82627, were a cxe game that FAILED on its node, record
            # 'No such file .../st/N.json', not a game that played differently): a failed game is not an engine mismatch; condab's own
            # missing-game handling re-plays it. Counted apart, so a whole batch never re-plays on the CLI for one node fault.
            nofail.append(j)
            continue
        # 11 Nov (TB 6ad907): draftrand comes only from cxe's diagnostics.draftRandomPicks (the CLI's statistics lack it: always 0 there),
        # so it is left out of the compare; every real field still is compared
        def _st(v):
            return {k: w for k, w in v.items() if k != "draftrand"} if isinstance(v, dict) else v
        if not c.get("ok") or any(_st(c.get(f)) != _st(x.get(f)) for f in ("win", "rounds", "sa", "sb")):
            bad.append(j)
    if bad:  # 7 Nov: a mismatch left nothing to look at. A batch's spot files are kept for the games that differ (bots, map, CLI side, cxe's record)
        keep = os.path.join(cxebuild.ROOT, "spotbad", os.path.basename(out.rstrip("/")))
        os.makedirs(keep, exist_ok=True)
        for j in bad:
            a, b, m = games[j - 1]
            with open(f"{keep}/{j}.txt", "w") as f:
                f.write(f"bots {a} {b}\nmap {paths[j - 1]}\ncxe {json.dumps(got.get(j), default=str)[:2000]}\n")
            for e in (f"{j}.repl26a", f"{j}.json", f"x{j}.repl26a"):
                if os.path.exists(f"{sd}/{e}"):
                    shutil.copyfile(f"{sd}/{e}", f"{keep}/{e}")
            if os.path.exists(paths[j - 1]):
                shutil.copyfile(paths[j - 1], f"{keep}/{j}.map26a")
    shutil.rmtree(sd, ignore_errors=True)
    k -= len(nofail)
    note = (f"{head}; CLI spot-check {k - len(bad)}/{k} identical" + (f" ({len(nofail)} sampled games failed on cxe: not compared)" if nofail else "") + (f" ({len(capped)} round-capped: replays)" if capped else "")
            + f" ({time.time() - t0:.0f} s{' alongside the batch' if pre is not None else ''})"
            + (f"; {_SPOT_NOTE.pop(sd)}" if sd in _SPOT_NOTE else ""))
    if bad:
        note = f"!! {note}: games {bad[:8]} differ from the CLI"
    if k == 0:
        note += " (no sampled game came back: unchecked)"
    open(os.path.join(out, "engine.txt"), "w").write(note + "\n")
    return not bad, note


RT_HOME = "/homes/USER/condor-runs/cxe"  # nodes read /homes, not /data


def so_in_use():
    """Library file names (HASH.so.gz) named by the parts.txt.cxe of every batch still in use: pilot items queued or claimed, a running
    condab.py's batch, or a run dir touched in the last 12 h (quotaguard's rules for condor-runs)."""
    import glob
    import re
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lab"))
    import quotaguard
    runs = "/homes/USER/condor-runs"
    dirs = set(quotaguard.pending_runs())
    args = quotaguard.condab_args()
    now = time.time()
    for d in glob.glob(f"{runs}/cq_*"):
        e = os.path.basename(d)
        if quotaguard.held_by_condab(e, args) or now - os.path.getmtime(d) < 12 * 3600:
            dirs.add(d)
    out = set()
    for d in dirs:
        for pf in glob.glob(f"{d}/parts.txt.cxe"):
            out |= set(re.findall(r"cxe/so/([0-9a-f]+\.so\.gz)", open(pf, errors="replace").read()))
    return out


def stage_condor(bots, say):
    """cxe for Condor nodes, on /homes: the host binary with its own runtime (HOST's ld.so, libc, libm, libstdc++,
    libgcc: the pool runs Ubuntu 16-26 and cxe needs glibc 2.38, so nodes start it as `RT/ld-linux-x86-64.so.2
    --library-path RT RT/cxe ...`) and the bots' libraries. -> (rt dir, {bot: library path})."""
    import hashlib
    exe = os.path.realpath(cxebuild.build_host())
    # 11 Nov (/var: root's syslog logs every process start; ldd is a shell script that starts several per call, and this ran per batch):
    # the library list is cached per (host binary, mtime, size) in ROOT/host/ldd_cache.json
    st_ = os.stat(exe)
    ck, cf = f"{exe}|{st_.st_mtime_ns}|{st_.st_size}", os.path.join(cxebuild.ROOT, "host", "ldd_cache.json")
    try:
        cache = json.load(open(cf))
    except (OSError, ValueError):
        cache = {}
    libs = cache.get(ck)
    if not libs or not all(os.path.exists(v) for v in libs.values()):
        libs = {"ld-linux-x86-64.so.2": os.path.realpath("/lib64/ld-linux-x86-64.so.2")}
        for ln in subprocess.run(["ldd", exe], capture_output=True, text=True).stdout.splitlines():
            p = ln.split()
            if "=>" in p and len(p) > 2 and p[2].startswith("/"):
                libs[p[0]] = os.path.realpath(p[2])
        try:
            cache = {ck: libs}
            open(cf + f".{os.getpid()}", "w").write(json.dumps(cache))
            os.replace(cf + f".{os.getpid()}", cf)
        except OSError:
            pass
    h = hashlib.sha1(open(exe, "rb").read())
    for k in sorted(libs):
        h.update(k.encode() + open(libs[k], "rb").read())
    rt = os.path.join(RT_HOME, "rt-" + h.hexdigest()[:12])
    # 5 Nov: a runtime missing any file (a cleanup removed its old-dated library copies) is rebuilt, not reused: nodes then
    # could not start cxe and every batch fell back to CLI re-plays
    if os.path.isdir(rt) and not all(os.path.exists(os.path.join(rt, k)) for k in list(libs) + ["cxe"]):
        shutil.rmtree(rt, ignore_errors=True)
    if not os.path.isdir(rt):
        tmp = f"{rt}.{os.getpid()}.tmp"
        os.makedirs(tmp, exist_ok=True)
        for k, src in libs.items():
            shutil.copy2(src, os.path.join(tmp, k))
        shutil.copy2(exe, os.path.join(tmp, "cxe"))
        try:
            os.replace(tmp, rt)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
        say(f"cxe: staged runtime {rt}")
    os.makedirs(os.path.join(RT_HOME, "so"), exist_ok=True)
    out = {}
    import gzip
    for b in bots:
        so = cxebuild.build_bot(b)
        dst = os.path.join(RT_HOME, "so", os.path.basename(so) + ".gz")  # gzipped (a third the size); jobs unpack into node /tmp
        if not os.path.exists(dst):
            tmp = f"{dst}.{os.getpid()}.tmp"  # per process: concurrent batches staging one library raced on a shared name
            with open(so, "rb") as fi, gzip.open(tmp, "wb", compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo)
            os.replace(tmp, dst)
        os.utime(dst)
        out[b] = dst
    now = time.time()  # keep: libraries used in the last 12 h (the home quota), the 3 newest runtimes
    keep_h, inuse = 12.0, set()
    try:  # 6 Nov (home at 9.45 of condab's 10 GB): 4 h, but never a library a live batch names in its parts.txt.cxe
        inuse = so_in_use()
        keep_h = float(os.environ.get("CXE_SO_KEEP_H", 1.5))  # 10 Nov: home at 9.87 GB (condab slows at 10 GB); in-use libraries are kept anyway
    except Exception:  # noqa: BLE001  the old 12 h rule if the check fails
        pass
    for f in os.listdir(os.path.join(RT_HOME, "so")):
        p = os.path.join(RT_HOME, "so", f)
        try:
            if now - os.path.getmtime(p) > keep_h * 3600 and f not in inuse:
                os.remove(p)
        except OSError:
            pass
    rts = sorted((d for d in os.listdir(RT_HOME) if d.startswith("rt-") and not d.endswith(".tmp")),
                 key=lambda d: os.path.getmtime(os.path.join(RT_HOME, d)))
    for d in rts[:-3]:
        if os.path.join(RT_HOME, d) != rt:
            shutil.rmtree(os.path.join(RT_HOME, d), ignore_errors=True)
    os.utime(rt)
    return rt, out
