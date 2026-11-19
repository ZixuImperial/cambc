"""ubaudit.py - one-command undefined-behaviour audit of a candidate bot against its base (driver of tools/lab/ubaudit.sh).

usage: python3 -I tools/lab/ubaudit.py CAND BASE [N]   (normally via `sh tools/lab/ubaudit.sh CAND BASE [N]`)
  CAND, BASE: bot names under /homes/USER/cambc/bots (symlinks are resolved; the real source is copied), or a bot dir path.
  N: games (default 40). v2 (29 Oct): each side is audited in MIRROR games, CAND vs CAND and BASE vs BASE, one game on
  each of N maps (a mirror gives both seats of a map in one game). BASE's site list is cached per (BASE source hash, SEED,
  N, map names + map file contents, FUEL, harness files), so an audit against a cached base builds and plays only CAND.
env: JOBS (game/compile processes one audit asks for, default 3), UBAUDIT_SLOTS (machine-wide cap on the game and
  compile processes of ALL audits together, default 6; an audit takes min(JOBS, free) slots, at least 1), FUEL (fuel per turn, default 1000000 = 10x, so the slower instrumented code still runs its background work,
  as the v271 audit's run2), SEED (map draw, default 1: every audit plays the same maps; change it for more coverage),
  KEEP (1 = keep the replays, default 1), STAMP (run-dir time stamp; ubaudit.sh passes $(date -u)).

Reuses the v271 audit harness in /data/USER/st/audit (code_audit_v271.md section 1.2):
  - proj/cmake/CMakeLists.txt: -g, -fsanitize=undefined,float-divide-by-zero, -fno-sanitize=vptr,function,
    -fsanitize-recover=all, libc++ hardening mode DEBUG (8); ubrt.cpp itself uninstrumented;
  - ubrt.cpp: recoverable UBSan runtime, logs "UBX kind file:line:col n= r= values" to the team stdout (fuel paused),
    and libc++ hardening failures print "UBX libcxx-assert ..." then trap;
  - patch_pos.py: map-bounds checks with the caller's file:line on common.h's raw buffer readers (kind pos-oob);
  - ubx.py: the collector.
Concurrency (v2): no global lock.
  - A per-bot build lock (ubproj/.locks/DIR.lock) covers the copy, the build, and run-batch's own up-to-date check of that
    bot (released when the first game starts), so two audits never build or check one instrumented copy at once.
  - A per-key lock (ubcache/.locks/KEY.lock) covers computing one base cache entry; the entry is written to a temp name,
    then renamed.
  - v3 (29 Oct, load ~320): UBAUDIT_SLOTS slot locks (ubslots/gK.lock) are a machine-wide counting semaphore over single
    game or compile processes. A build runs with ninja -j = its slots (CMAKE_BUILD_PARALLEL_LEVEL), a batch with
    run-batch --jobs = its slots; slots are released after each build or batch.
  - The project files (sdk, cmake) are refreshed under ubproj/.locks/project.lock. Run dirs, manifests, replays and team
    logs are per run (the run dir gets a pid suffix if the name is taken).
  - v4 (30 Oct 22:10): priority runs (full audits, --build-only of SHIPCHECK-marked bots) go first and may use every slot;
    other --build-only runs use TOTAL_SLOTS - UBAUDIT_RESERVE (3) slots. A --build-only skips a build another run already
    does (its build lock is held) and a source that changed while it waited.
  - v5 (30 Oct night): REMOTE mode (flag file /data/USER/st/audit/REMOTE or UB_REMOTE=1): each side builds and plays in
    one Condor job (ubaudit_node.sh, 8 cpus), both sides at once; local fallback on any failure, or when the job is still idle
    after UB_REMOTE_START (300 s). Validated: 40/40 games byte-identical statistics and team logs vs the local run; 73-83 s wall
    vs 877 s local.
Outputs: /data/USER/st/audit/runs/CAND_STAMP/ (manifest, run.log, rep/, st/, side/, ubx_cand.txt, report.txt);
base cache: /data/USER/st/audit/ubcache/base_au_NAME-HASH_KEY.json (its games: runs/base_NAME_KEY_STAMP/).

Diff: a site is (kind, file, line, col) (pos-oob: the caller's file:line). BASE sites are carried to CAND's line numbers
through a line diff of the two instrumented sources, so code moved by an insertion still matches. CAND-only = NEW.
Verdict: PASS = 0 new sites, 0 CAND traps / hardening asserts, 0 CAND bot faults. Exit 0 pass, 1 fail, 2 harness error.
"""
import collections, difflib, fcntl, hashlib, io, json, os, random, re, shutil, subprocess, sys, tarfile, threading, time, zipfile

VERSION = 'ubaudit-v2-mirror'  # v3 changed only scheduling, so cache entries stay valid
REPO = '/homes/USER/cambc'
AUD = '/data/USER/st/audit'
CLI = os.environ.get('UB_CLI', '/data/USER/cambc500/bin/cambc500')
WS = '/data/USER/work301_4.0.0'      # abl.sh's cambc 4.0.0 workspace: sdk, cmake, every map
PROJ = AUD + '/ubproj'
CACHE = AUD + '/ubcache'
SLOTS = AUD + '/ubslots'
MAPS = WS + '/maps'
JOBS = max(1, int(os.environ.get('JOBS', '3')))  # slots one audit asks for (2 audits fill the 6 slots)
TOTAL_SLOTS = max(1, int(os.environ.get('UBAUDIT_SLOTS', '6')))  # all audits together: game + compile processes
# PRIORITY (30 Oct 22:10, Builder: a ship candidate's audit waited 10 min behind prebuilds): a full audit, or a --build-only of a
# bot carrying a SHIPCHECK marker, is a priority run: it may take every slot, and while it waits (file SLOTS/want/PID) no
# low-priority run takes a slot. Low-priority runs (other --build-only, e.g. variantfarm survivors) use at most
# TOTAL_SLOTS - RESERVE slots, so RESERVE slots stay free for a priority run that arrives later.
PRIO = True
RESERVE = min(TOTAL_SLOTS - 1, max(0, int(os.environ.get('UBAUDIT_RESERVE', '3'))))
WANT = SLOTS + '/want'
# REMOTE (30 Oct night, Tool builder; Builder: "move the UB-audit work off this machine"): each side's instrumented build and
# mirror games run as one Condor job (tools/lab/ubaudit_node.sh, RCPUS cpus) instead of on this machine's CPU slots, and the
# two sides run at once. On by UB_REMOTE=1, or (UB_REMOTE unset) while the flag file AUD/REMOTE exists. Any remote failure
# (submit, hold, timeout, bad output) tries Condor once more, then stops (exit 2; UB_LOCAL=1: the local path). A compile or link error stops at once.
# Same CLI binary (condor-work/bin/cambc400 == the local one) and same sources, so the games and their sites are the same.
REMOTE = os.environ.get('UB_REMOTE', '1' if os.path.exists(AUD + '/REMOTE') else '0') == '1'
UBQ = '/homes/USER/condor-work/ubq'  # per-side job dirs (in.tgz, out.tgz, logs: ~7 files), removed after each side
NODE_SH = REPO + '/tools/lab/ubaudit_node.sh'
RCPUS = int(os.environ.get('UB_REMOTE_CPUS', '8'))
RTIMEOUT = int(os.environ.get('UB_REMOTE_TIMEOUT', '2700'))  # s from submit to a complete OUT.tgz, else local fallback
RSTART = int(os.environ.get('UB_REMOTE_START', '300'))  # s a job may stay idle (busy pool, day) before the local fallback
LOGLIM = 4 << 20                       # bytes of each team's stdout kept by the runner
INFRA = re.compile(r'Killed|No space|out of memory|timed out|Connection (refused|reset)|failed to download')  # a node's trouble, not the source's
LOCAL_FALLBACK = os.environ.get('UB_LOCAL', '0') == '1'  # 2 Nov (Builder, HOST kept light): off, a failed remote audit is INCONCLUSIVE; on a machine of ours set UB_LOCAL=1
HARNESS = [AUD + '/ubrt.cpp', AUD + '/patch_pos.py', AUD + '/ubx.py', AUD + '/proj/cmake/CMakeLists.txt']
FAMILIES = [  # (family, share, source)
    ('pool', 0.35, 'pool'),
    ('gen', 0.15, 'gen_s'),
    ('patho', 0.10, '/data/USER/patho4.txt'),
    ('genpatho', 0.10, '/data/USER/genmaps_p/maplist.txt'),
    ('islands', 0.10, '/data/USER/genmaps_p/maplist_islands.txt'),
    ('dominant', 0.10, '/data/USER/genmaps_dom/maplist_dev.txt'),
    ('crossing', 0.10, '/data/USER/genmaps_xing/maplist_dev.txt'),
]


def die(msg, code=2):
    print('ubaudit: ' + msg, flush=True)
    sys.exit(code)


def log(msg):
    print('## %s %s' % (time.strftime('%H:%M:%S', time.gmtime()), msg), flush=True)


def src_hash(d):
    h = hashlib.sha1()
    for root, dirs, files in os.walk(d + '/src'):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, d).encode() + b'\0')
            with open(p, 'rb') as fh:
                h.update(fh.read())
    return h.hexdigest()[:12]


def resolve(arg):
    p = arg if '/' in arg else os.path.join(REPO, 'bots', arg)
    real = os.path.realpath(p)
    if not os.path.isdir(real + '/src'):
        die('no bot source at %s (%s)' % (p, real))
    return os.path.basename(real.rstrip('/')), real


class Lock:
    """Exclusive flock on a file; `with Lock(path, 'what'):` waits, saying so once."""
    def __init__(self, path, what=''):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path, self.what, self.fh = path, what, None

    def acquire(self):
        self.fh = open(self.path, 'a')
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('waiting for %s (%s)' % (self.what or 'lock', self.path))
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def release(self):
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *a):
        self.release()


def prio_waiting():
    """True while another live priority run waits for a slot (SLOTS/want/PID; files of dead processes are removed)."""
    try:
        names = os.listdir(WANT)
    except OSError:
        return False
    for f in names:
        if not f.isdigit() or int(f) == os.getpid():
            continue
        try:  # alive and not a zombie (shipwatch never reaps its prebuild children)
            if open('/proc/%s/stat' % f).read().rsplit(')', 1)[1].split()[0] != 'Z':
                return True
        except (OSError, IndexError):
            pass
        try:
            os.remove(os.path.join(WANT, f))
        except OSError:
            pass
    return False


def cpu_slots(want, what):
    """Machine-wide counting semaphore over CPU slots (one game process or one compile job each): flock on TOTAL_SLOTS
    files ubslots/gK.lock. Takes up to `want` free slots (at least 1, waiting if none) and returns the open files; closing
    them frees the slots. Every audit's builds and game batches go through it, so all audits together run at most
    TOTAL_SLOTS game or compile processes. Priority (PRIO) runs go first; low-priority runs use slots 0..TOTAL-RESERVE-1."""
    os.makedirs(SLOTS, exist_ok=True)
    said, mark = False, None
    top = TOTAL_SLOTS if PRIO else TOTAL_SLOTS - RESERVE
    try:
        while True:
            got = []
            if PRIO or not prio_waiting():
                for i in range(top):
                    if len(got) >= want:
                        break
                    fh = open('%s/g%d.lock' % (SLOTS, i), 'a')
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        got.append(fh)
                    except BlockingIOError:
                        fh.close()
            if got:
                log('%d of %d CPU slots for %s%s' % (len(got), TOTAL_SLOTS, what, '' if PRIO else ' (low priority)'))
                return got
            if PRIO and mark is None:
                os.makedirs(WANT, exist_ok=True)
                mark = '%s/%d' % (WANT, os.getpid())
                open(mark, 'w').write(what + '\n')
            if not said:
                log('waiting for a CPU slot (%s, %s) for %s' % (
                    'priority' if PRIO else 'low priority: slots 0-%d, after every waiting priority run' % (top - 1), SLOTS, what))
                said = True
            time.sleep(2 + random.random())
    finally:
        if mark:
            try:
                os.remove(mark)
            except OSError:
                pass


def free_slots(got):
    for fh in got:
        fh.close()


def build_lock(d):
    return Lock('%s/.locks/%s.lock' % (PROJ, os.path.basename(d)), 'the build lock of ' + os.path.basename(d))


def setup_project():
    """The fixed instrumented project (rsync keeps unchanged files, so cached builds stay valid)."""
    os.makedirs(PROJ + '/bots', exist_ok=True)
    os.makedirs(PROJ + '/cmake', exist_ok=True)
    orig, inst = AUD + '/proj/cmake/CMakeLists.txt.orig', AUD + '/proj/cmake/CMakeLists.txt'
    if open(orig).read() != open(WS + '/cmake/CMakeLists.txt').read():
        die('the workspace CMakeLists.txt (%s) no longer matches the one the audit instrumented (%s): re-derive %s'
            % (WS + '/cmake/CMakeLists.txt', orig, inst))
    with Lock(PROJ + '/.locks/project.lock', 'the project lock'):
        subprocess.run(['rsync', '-a', WS + '/cambc.toml', PROJ + '/cambc.toml'], check=True)
        subprocess.run(['rsync', '-a', WS + '/sdk/', PROJ + '/sdk/'], check=True)
        subprocess.run(['rsync', '-a', inst, PROJ + '/cmake/CMakeLists.txt'], check=True)


def copy_src(name, real, h, d):
    """The instrumented copy's source: the real source (no symlinks) + ubrt.cpp + patch_pos.py. Caller holds the lock."""
    if os.path.isdir(d + '/src'):
        return
    t = d + '.tmp.%d' % os.getpid()
    shutil.rmtree(t, ignore_errors=True)
    os.makedirs(t)
    subprocess.run(['rsync', '-a', '--exclude', '.cambc', '--exclude', 'build', '--exclude', 'compile_commands.json',
                    real + '/src', t + '/'], check=True)
    links = subprocess.run(['find', t, '-type', 'l'], capture_output=True, text=True).stdout.strip()
    if links:
        shutil.rmtree(t)
        die('copy of %s holds symlinks, refusing to patch:\n%s' % (real, links))
    if src_hash(t) != h:
        shutil.rmtree(t)
        die('%s changed while being copied; retry' % real)
    shutil.copy(AUD + '/ubrt.cpp', t + '/src/ubrt.cpp')
    if os.path.exists(t + '/src/common.h'):
        r = subprocess.run([sys.executable, '-I', AUD + '/patch_pos.py', t + '/src'], capture_output=True, text=True)
        if r.returncode != 0:
            shutil.rmtree(t)
            die('patch_pos.py failed on %s (common.h anchors changed?): %s%s' % (name, r.stdout, r.stderr))
    os.rename(t, d)


def bot_dir(name, real):
    h = src_hash(real)
    return '%s/bots/au_%s-%s' % (PROJ, name, h), h


def harness_stale(d):
    try:
        return open(d + '/src/ubrt.cpp').read() != open(AUD + '/ubrt.cpp').read()
    except OSError:
        return False


def instrumented(name, real, build=True, fresh=False):
    """Copy (and build, in debug mode) the instrumented bot, once per source hash, under its build lock. fresh (--build-only):
    skip the build when the bot's source changed while this run waited for a slot (a newer run builds the new source)."""
    d, h = bot_dir(name, real)
    if harness_stale(d):
        with build_lock(d):
            if harness_stale(d):  # 2 Nov: the dir is keyed by the bot's source only, so a harness change kept building the old copy
                os.makedirs(AUD + '/stale', exist_ok=True)
                os.replace(d, '%s/stale/%s_%d' % (AUD, os.path.basename(d), time.time()))
    if os.path.exists(d + '/.ubbuilt') or (not build and os.path.isdir(d + '/src')):
        return d, h, 'cached'
    with build_lock(d):
        copy_src(name, real, h, d)
        if not build or os.path.exists(d + '/.ubbuilt'):
            return d, h, 'cached'
        got = cpu_slots(JOBS, 'building ' + os.path.basename(d))
        if fresh and src_hash(real) != h:
            free_slots(got)
            return d, h, 'stale (source changed while waiting; not built)'
        env = dict(os.environ, CMAKE_BUILD_PARALLEL_LEVEL=str(len(got)))  # ninja -j = the slots held
        with open(d + '/build.log', 'w') as fh:
            r = subprocess.run([CLI, 'build', d], cwd=PROJ, stdout=fh, stderr=subprocess.STDOUT, env=env)
        if r.returncode != 0 and 'Terminated' in open(d + '/build.log', errors='replace').read():
            # 30 Oct 18:20: compilers killed by a signal under load (343c, 350c), not a compile error: retry once; ninja keeps
            # the objects already built, so the retry only redoes what was cut off
            log('instrumented build of %s was killed (Terminated), retrying once' % name)
            with open(d + '/build.log', 'a') as fh:
                fh.write('\n## retry after Terminated\n')
                fh.flush()
                r = subprocess.run([CLI, 'build', d], cwd=PROJ, stdout=fh, stderr=subprocess.STDOUT, env=env)
        free_slots(got)
        if r.returncode != 0:
            die('instrumented build of %s failed, see %s' % (name, d + '/build.log'))
        open(d + '/.ubbuilt', 'w').write(h + '\n')
    return d, h, 'built'


def pick_maps(m, seed):
    have = set(f[:-7] for f in os.listdir(MAPS) if f.endswith('.map26a'))
    rng = random.Random(seed)
    islands = set(open(FAMILIES[4][2]).read().split())
    want = [m * s for _, s, _ in FAMILIES]
    cnt = [int(w) for w in want]
    for i in sorted(range(len(want)), key=lambda i: -(want[i] - cnt[i]))[:m - sum(cnt)]:
        cnt[i] += 1
    out = []
    for (fam, _, src), k in zip(FAMILIES, cnt):
        if src == 'pool':
            names = [n for n in have if re.match(r'(00|01|02|adgato-)', n)]
        elif src == 'gen_s':
            names = [n for n in have if n.startswith('gen_s_')]
        else:
            names = [n for n in open(src).read().split() if n in have]
            if fam == 'genpatho':
                names = [n for n in names if n not in islands]
        names = sorted(names)
        for n in rng.sample(names, min(k, len(names))):
            out.append((fam, n))
    return out


UBX_LINE = re.compile(r'^(\S+)\s+(.+?)\s+games=(\d+)\s*maxn=(\S+)\s+(.*)$')


def collect(sidedir, outfile):
    """Run the harness collector ubx.py on a dir of team-stdout bundles; return {(kind, loc): (games, maxn, example)}."""
    r = subprocess.run([sys.executable, '-I', AUD + '/ubx.py', sidedir], capture_output=True, text=True)
    open(outfile, 'w').write(r.stdout + r.stderr)
    sites, bad = {}, 0
    for ln in r.stdout.splitlines():
        if ln.startswith('# bundles') or not ln.strip():
            continue
        if ln.startswith('bad '):
            bad += 1
            continue
        mm = UBX_LINE.match(ln)
        if not mm:
            sites[('unparsed', ln[:120])] = (1, '-', ln)
            continue
        kind, loc, g, mx, ex = mm.groups()
        sites[(kind, loc.strip())] = (int(g), mx, ex)
    sites.pop(('hello', 'start:0:0'), None)
    return sites, bad


def new_run_dir(prefix, stamp):
    run = '%s/runs/%s_%s' % (AUD, prefix, stamp)
    if os.path.exists(run):
        run += '_%d' % os.getpid()
    os.makedirs(run + '/rep')
    os.makedirs(run + '/st')
    os.makedirs(run + '/side')
    return run


def condor_env():
    """os.environ + Condor's PATH, with a live Kerberos ticket cache (a renewed session can remove KRB5CCNAME's file)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import condorroute  # no schedd on this machine: the HOST route, as cqbatch and condab (7 Nov: under shipwatch condor_submit failed twice, CEDAR:6001, and code ships read INCONCLUSIVE)
    env = condorroute.env()
    cc = env.get('KRB5CCNAME', '')
    path = cc[5:] if cc.startswith('FILE:') else cc
    if not (path and os.path.exists(path)):
        import glob
        files = sorted(glob.glob('/tmp/krb5cc_%d_*' % os.getuid()), key=os.path.getmtime)
        if files:
            env['KRB5CCNAME'] = 'FILE:' + files[-1]
    return env


def play_remote(run, d, games, fuel):
    """Build d and play its mirror games in one Condor job (REMOTE). Fills run/rep, run/st, run/run.log, run/build.log as the
    local path does and returns (rc, secs); returns None on any failure, and the caller plays locally."""
    t0 = time.time()
    b = os.path.basename(d)
    q = '%s/%s' % (UBQ, os.path.basename(run))
    tin, tout = q + '/in.tgz', q + '/out.tgz'
    env, cluster = condor_env(), None
    try:
        os.makedirs(q)
        skip = re.compile(r'/(\.cambc|build|build\.log|compile_commands\.json|\.ubbuilt)$')
        man = ''.join('@W@/proj/bots/%s @W@/proj/bots/%s @W@/maps/%s.map26a @W@/out/rep/%d.repl26a --statistics @W@/out/st/%d.json'
                      ' --json\n' % (b, b, mp, gid, gid) for gid, mp, _ in games)
        with tarfile.open(tin + '.tmp', 'w:gz') as tf:
            for f in ('cambc.toml', 'sdk', 'cmake'):
                tf.add(PROJ + '/' + f, 'proj/' + f)
            tf.add(d + '/src', 'proj/bots/%s/src' % b, filter=lambda ti: None if skip.search(ti.name) else ti)
            for mp in sorted({mp for _, mp, _ in games}):
                tf.add('%s/%s.map26a' % (MAPS, mp), 'maps/%s.map26a' % mp)
            for name, text in (('botname', b + '\n'), ('manifest.txt', man)):
                data = text.encode()
                ti = tarfile.TarInfo(name)
                ti.size, ti.mtime = len(data), time.time()
                tf.addfile(ti, io.BytesIO(data))
        os.replace(tin + '.tmp', tin)
        open(q + '/job.sub', 'w').write('''universe = vanilla
executable = /bin/sh
arguments = "%s %s %s %d %d %d"
initialdir = %s
output = %s/node.out
error = %s/node.err
log = %s/job.log
request_cpus = %d
request_memory = 12000
priority = 20
batch_name = ub_%s
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22")
getenv = True
should_transfer_files = NO
queue 1
''' % (NODE_SH, tin, tout, fuel, LOGLIM, RCPUS, q, q, q, q, RCPUS, b[3:43]))
        r = subprocess.run(['condor_submit', q + '/job.sub'], capture_output=True, text=True, env=env, cwd=q, timeout=180)
        m = re.search(r'submitted to cluster (\d+)', r.stdout)
        if r.returncode or not m:
            log('remote %s: condor_submit failed (%s); playing locally' % (b, (r.stdout + r.stderr).strip()[-160:]))
            return None
        cluster = m.group(1)
        log('remote %s: Condor cluster %s (instrumented build + %d mirror games, %d cpus, timeout %d s)'
            % (b, cluster, len(games), RCPUS, RTIMEOUT))
        gone, last_q = 0, 0.0
        while not os.path.exists(tout):
            if time.time() - t0 > RTIMEOUT:
                log('remote %s: no result after %d s; playing locally' % (b, RTIMEOUT))
                return None
            time.sleep(10)
            if time.time() - last_q >= 60:
                last_q = time.time()
                st = subprocess.run(['condor_q', cluster, '-af', 'JobStatus', 'HoldReason'], capture_output=True, text=True,
                                    env=condor_env(), timeout=120)
                if st.returncode == 0:
                    f = st.stdout.split(None, 1)
                    if f and f[0] == '1' and time.time() - t0 > RSTART:
                        log('remote %s: still idle in the Condor queue after %d s; playing locally' % (b, RSTART))
                        return None
                    if f and f[0] == '5':
                        log('remote %s: job held (%s); playing locally' % (b, f[1].strip()[:160] if len(f) > 1 else '?'))
                        return None
                    gone = gone + 1 if not f else 0
                    if gone >= 3 and not os.path.exists(tout):  # left the queue 3 checks ago without a result
                        log('remote %s: job ended without a result (%s); playing locally'
                            % (b, open(q + '/node.err', errors='replace').read()[-160:] if os.path.exists(q + '/node.err') else '-'))
                        return None
        with tarfile.open(tout) as tf:
            tf.extractall(run, filter='data')
        rc = int(open(run + '/rc').read().strip() or 3)
        if rc == 4 and not INFRA.search(open(run + '/build.log', errors='replace').read()):
            log('remote %s: build failed (see %s/build.log)' % (b, run))
            return 'BUILD'
        if rc in (3, 4):
            log('remote %s: %s (see %s/build.log)' % (b, 'build failed' if rc == 4 else 'bad job input', run))
            return None
        secs = time.time() - t0
        bl = open(run + '/build.log', errors='replace').read().strip().splitlines()
        log('remote %s: done in %.0f s (%s), run-batch rc %d' % (b, secs, bl[-1][3:] if bl else '?', rc))
        return rc, secs
    except Exception as e:  # noqa: BLE001  any remote problem: the local path
        log('remote %s: %s: %s; playing locally' % (b, type(e).__name__, e))
        return None
    finally:
        if cluster and not os.path.exists(tout):
            subprocess.run(['condor_rm', cluster], capture_output=True, env=condor_env(), timeout=120)
            for _ in range(15):  # the schedd writes the abort event to job.log after condor_rm returns: wait it out
                st = subprocess.run(['condor_q', cluster, '-af', 'JobStatus'], capture_output=True, text=True,
                                    env=condor_env(), timeout=60)
                if st.returncode == 0 and not st.stdout.strip():
                    break
                time.sleep(2)
            time.sleep(2)
        for f in ('node.err', 'node.out'):
            try:
                txt = open('%s/%s' % (q, f), errors='replace').read()
                if txt.strip():
                    open(run + '/remote_' + f, 'w').write(txt[-20000:])
            except OSError:
                pass
        shutil.rmtree(q, ignore_errors=True)


def play_mirror(run, d, maps, jobs, fuel, keep, ensure_built=None):
    """Mirror games d vs d, one per map, in a game slot (or on Condor, REMOTE); collect the sites of both seats. Returns a
    result dict. ensure_built: called before a local run when the bot was not built here (REMOTE's fallback)."""
    games = []
    with open(run + '/manifest.txt', 'w') as mf, open(run + '/games.list', 'w') as gl:
        for gid, (fam, mp) in enumerate(maps):
            mf.write('%s %s %s/%s.map26a %s/rep/%d.repl26a --statistics %s/st/%d.json --json\n'
                     % (d, d, MAPS, mp, run, gid, run, gid))
            gl.write('%d %s %s\n' % (gid, mp, fam))
            games.append((gid, mp, fam))
    rr = play_remote(run, d, games, fuel) if REMOTE else None
    if REMOTE and rr is None:
        # 11 Nov (Builder, tsxk11 12566: an 8-cpu job sat idle 300 s twice in a busy pool -> INCONCLUSIVE): the retry asks for half the
        # cpus and waits 3x as long in the queue (UB_RETRY_CPUS, UB_RETRY_START)
        g = globals()
        keep = (g['RCPUS'], g['RSTART'])
        g['RCPUS'] = int(os.environ.get('UB_RETRY_CPUS', str(max(2, keep[0] // 2))))
        g['RSTART'] = int(os.environ.get('UB_RETRY_START', str(3 * keep[1])))
        log('remote %s: trying Condor once more (%d cpus, idle limit %d s)' % (os.path.basename(d), g['RCPUS'], g['RSTART']))
        try:
            rr = play_remote(run, d, games, fuel)
        finally:
            g['RCPUS'], g['RSTART'] = keep
    if rr == 'BUILD':  # a compile or link error: the same source fails the same way here
        die('instrumented build of %s failed: see %s/build.log' % (os.path.basename(d), run))
    if REMOTE and rr is None and not LOCAL_FALLBACK:
        die('%s: Condor failed twice, and this machine stays light (UB_LOCAL=1 builds and plays here)' % os.path.basename(d))
    if rr is not None:
        rc, secs = rr
    else:
        if ensure_built:
            ensure_built()
        got = cpu_slots(jobs, '%d mirror games of %s' % (len(games), os.path.basename(d)))
        jobs = len(got)
        t0 = time.time()
        # run-batch re-checks the bot's build before the first game: keep the build lock until a game starts.
        bl = build_lock(d).acquire()
        with open(run + '/run.log', 'w') as fh:
            p = subprocess.Popen([CLI, 'run-batch', run + '/manifest.txt', '--jobs', str(jobs), '--fuel-quantum', str(fuel),
                                  '--timeout', '1800', '--log-limit', str(LOGLIM)], cwd=PROJ, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, errors='replace')
            for ln in p.stdout:
                fh.write(ln)
                if bl and 'STARTING' in ln:
                    bl.release()
                    bl = None
            rc = p.wait()
        if bl:
            bl.release()
        free_slots(got)
        secs = time.time() - t0
    played, faults, hello, trunc, fault_games = 0, 0, 0, 0, []
    for gid, mp, fam in games:
        rp = '%s/rep/%d.repl26a' % (run, gid)
        if not os.path.exists(rp):
            continue
        played += 1
        z = zipfile.ZipFile(rp)
        names = z.namelist()
        out = zipfile.ZipFile('%s/side/%d.repl26a' % (run, gid), 'w')
        for t in ('a', 'b'):
            mem = 'team-%s.stdout' % t
            data = z.read(mem) if mem in names else b''
            if len(data) >= LOGLIM - 4096:
                trunc += 1
            if data and not data.endswith(b'\n'):
                data = data[:data.rfind(b'\n') + 1]  # a line cut by the runner's log limit is not a site
            out.writestr(mem, data)
            if b'UBX hello' in data:
                hello += 1
        out.close()
        try:
            bf = json.load(open('%s/st/%d.json' % (run, gid))).get('diagnostics', {}).get('botFaults', {})
            f = int(bf.get('teamA', 0)) + int(bf.get('teamB', 0))
            faults += f
            if f:
                fault_games.append((gid, mp, int(bf.get('teamA', 0)), int(bf.get('teamB', 0))))
        except (OSError, ValueError):
            pass
    sites, bad = collect(run + '/side', run + '/ubx.txt')
    if not keep:
        shutil.rmtree(run + '/rep', ignore_errors=True)
    return {'sites': sites, 'bad': bad, 'played': played, 'games': len(games), 'faults': faults, 'hello': hello,
            'trunc': trunc, 'fault_games': fault_games, 'rc': rc, 'secs': round(secs, 1), 'run': run}


def file_sha(paths):
    h = hashlib.sha1()
    for p in paths:
        h.update(p.encode() + b'\0')
        with open(p, 'rb') as fh:
            h.update(fh.read())
    return h.hexdigest()


def base_sites(bname, breal, bdir, bh, maps, n, seed, fuel, jobs, keep, stamp):
    """BASE's mirror-game sites, from the cache or computed once (per-key lock, atomic write)."""
    key_fields = {'version': VERSION, 'base_hash': bh, 'seed': seed, 'n': n, 'fuel': fuel, 'loglim': LOGLIM,
                  'maps': [mp for _, mp in maps],
                  'maps_sha': file_sha(['%s/%s.map26a' % (MAPS, mp) for _, mp in maps]),
                  'harness_sha': file_sha(HARNESS), 'cli': CLI}
    key = hashlib.sha1(json.dumps(key_fields, sort_keys=True).encode()).hexdigest()[:12]
    path = '%s/base_%s_%s.json' % (CACHE, os.path.basename(bdir), key)

    def load():
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            return None
        if d.get('key') != key_fields:
            return None
        d['sites'] = {(k, loc): (g, mx, ex) for k, loc, g, mx, ex in d['sites']}
        return d

    d = load()
    if d:
        return d, path, 'cached'
    with Lock('%s/.locks/%s.lock' % (CACHE, key), 'the base cache entry ' + key):
        d = load()
        if d:
            return d, path, 'cached (made by a concurrent audit)'
        if not REMOTE:
            instrumented(bname, breal)
        run = new_run_dir('base_%s_%s' % (bname, key), stamp)
        r = play_mirror(run, bdir, maps, jobs, fuel, keep, ensure_built=lambda: instrumented(bname, breal))
        if r['played'] == 0 or r['hello'] == 0:
            die('base run failed (no games or no UB runtime output), see %s/run.log' % run)
        out = dict(r)
        out['key'] = key_fields
        out['made'] = stamp
        out['sites'] = [[k, loc, g, mx, ex] for (k, loc), (g, mx, ex) in sorted(r['sites'].items())]
        tmp = '%s.tmp.%d' % (path, os.getpid())
        with open(tmp, 'w') as fh:
            json.dump(out, fh, indent=1)
        os.replace(tmp, path)
        d = load()
    return d, path, 'computed'


LOC = re.compile(r'^(.*):(\d+):(\d+)$')


def line_map(a_path, b_path):
    """1-based line map a -> b over the equal blocks of a line diff (None where a's line was changed)."""
    try:
        a = open(a_path, errors='replace').read().splitlines()
        b = open(b_path, errors='replace').read().splitlines()
    except OSError:
        return None
    mp = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                mp[i1 + k + 1] = j1 + k + 1
    return mp


def build_only(bots):
    """--build-only BOT...: the instrumented build of each bot, nothing else (30 Oct, iteration-speed: shipwatch starts it when
    a SHIPCHECK marker appears and variantfarm for its survivor, so the ~7.5 min debug build is done before the audit needs it).
    Same cache (one build per source hash, .ubbuilt), build locks and CPU slots as a full audit."""
    global PRIO
    if REMOTE:
        log('build-only %s: remote mode (%s): the Condor job builds, nothing to do here' % (' '.join(bots), AUD + '/REMOTE'))
        return
    setup_project()
    for b in bots:
        name, real = resolve(b)
        # DEDUPE (30 Oct 22:10, Builder: 3 prebuilds of one bot queued): a build of this source that is done, or that another
        # run is doing now (its build lock is held), is not queued again; the audit later reuses it (it waits on the lock)
        d, h = bot_dir(name, real)
        if os.path.exists(d + '/.ubbuilt'):
            log('build-only %s: %s (cached)' % (name, d))
            continue
        lk = build_lock(d)
        lk.fh = open(lk.path, 'a')
        try:
            fcntl.flock(lk.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lk.fh.close()
            log('build-only %s: another run holds the build lock of %s; not queued again' % (name, os.path.basename(d)))
            continue
        lk.release()
        PRIO = os.path.exists(os.path.join(real, 'SHIPCHECK'))
        d, h, st = instrumented(name, real, fresh=True)
        log('build-only %s: %s (%s%s)' % (name, d, st, ', priority: SHIPCHECK marker' if PRIO else ''))


def main():
    if sys.argv[1:2] == ['--build-only']:
        return build_only(sys.argv[2:])
    if len(sys.argv) < 3:
        die('usage: sh tools/lab/ubaudit.sh CAND BASE [N]  |  --build-only BOT...')
    t_start = time.time()
    cand_arg, base_arg = sys.argv[1], sys.argv[2]
    n = max(1, int(sys.argv[3]) if len(sys.argv) > 3 else 40)
    jobs = JOBS
    fuel = int(os.environ.get('FUEL', '1000000'))
    seed = os.environ.get('SEED', '1')
    keep = os.environ.get('KEEP', '1') == '1'
    stamp = os.environ.get('STAMP') or die('STAMP not set (run through tools/lab/ubaudit.sh)')
    cname, creal = resolve(cand_arg)
    bname, breal = resolve(base_arg)
    maps = pick_maps(n, seed)
    log('ubaudit %s vs %s: %d mirror games each, fuel %d, up to %d jobs (of %d machine-wide slots), seed %s'
        % (cname, bname, len(maps), fuel, jobs, TOTAL_SLOTS, seed))
    setup_project()
    cdir, ch, cst = instrumented(cname, creal, build=not REMOTE)
    bdir, bh, _ = instrumented(bname, breal, build=False)  # the copy is enough for the line diff on a cache hit
    log('CAND instrumented: %s (%s%s)' % (cdir, cst, ', remote mode: the Condor job builds it' if REMOTE else ''))
    if REMOTE:  # both sides at once, each in its own Condor job
        box = {}

        def _base():
            try:
                box['r'] = base_sites(bname, breal, bdir, bh, maps, n, seed, fuel, jobs, keep, stamp)
            except SystemExit as e:  # die() in the thread
                box['e'] = e
        th = threading.Thread(target=_base)
        th.start()
        run = new_run_dir(cname, stamp)
        cr = play_mirror(run, cdir, maps, jobs, fuel, keep, ensure_built=lambda: instrumented(cname, creal))
        th.join()
        if 'e' in box:
            raise box['e']
        base, bpath, bst = box['r']
        log('BASE sites %s: %s' % (bst, bpath))
    else:
        base, bpath, bst = base_sites(bname, breal, bdir, bh, maps, n, seed, fuel, jobs, keep, stamp)
        log('BASE sites %s: %s' % (bst, bpath))
        run = new_run_dir(cname, stamp)
        cr = play_mirror(run, cdir, maps, jobs, fuel, keep)
    csites, bsites = cr['sites'], base['sites']

    # Diff: carry BASE sites to CAND line numbers per file.
    maps_bc = {}

    def carried(kind, loc):
        mm = LOC.match(loc)
        if not mm or loc.startswith('libc++/'):
            return (kind, loc)
        f, l, c = mm.group(1), int(mm.group(2)), mm.group(3)
        if f not in maps_bc:
            maps_bc[f] = None if cdir == bdir else line_map('%s/src/%s' % (bdir, f), '%s/src/%s' % (cdir, f))
        mpf = maps_bc[f]
        if mpf is None:
            return (kind, loc)
        nl = mpf.get(l)
        return (kind, '%s:%d:%s' % (f, nl, c)) if nl else (kind, loc + '@base-changed')

    bcarried = {carried(k, loc): (k, loc) for (k, loc) in bsites}
    new = [k for k in csites if k not in bcarried]
    shared = [k for k in csites if k in bcarried]
    base_only = [bcarried[k] for k in bcarried if k not in csites]
    hard_c = [k for k in csites if k[0] == 'libcxx-assert']

    srcmap = {}

    def where(loc):
        """CAND's instrumented file:line -> the real source line (common.h differs by the patch_pos lines)."""
        mm = LOC.match(loc)
        if not mm or loc.startswith('libc++/'):
            return loc, ''
        f, l = mm.group(1), int(mm.group(2))
        if f not in srcmap:
            srcmap[f] = line_map('%s/src/%s' % (cdir, f), '%s/src/%s' % (creal, f))
        ol = (srcmap[f] or {}).get(l)
        if not ol:
            return '%s (instrumented line %d; not in the real source)' % (os.path.join(creal, 'src', f), l), ''
        try:
            txt = open('%s/src/%s' % (creal, f), errors='replace').read().splitlines()[ol - 1].strip()
        except (OSError, IndexError):
            txt = ''
        return '%s/src/%s:%d:%s' % (creal, f, ol, mm.group(3)), txt[:110]

    ok_run = cr['played'] > 0 and cr['hello'] > 0
    passed = ok_run and not new and not hard_c and cr['faults'] == 0
    rep = []
    rep.append('# UB audit %s vs %s  (%s UTC, %s, run %s)' % (cname, bname, stamp, VERSION, run))
    rep.append('CAND %s = %s (src %s, instrumented %s %s)' % (cand_arg, creal, ch, cdir, cst))
    rep.append('BASE %s = %s (src %s, instrumented %s; sites %s: %s, games %s)' % (base_arg, breal, bh, bdir, bst, bpath,
                                                                                     base.get('run')))
    rep.append('mirror games: CAND %d of %d played (run-batch exit %d, %.0f s), BASE %d of %d; fuel %d/turn, seed %s; '
               'runtime alive in %d/%d CAND team logs' % (cr['played'], cr['games'], cr['rc'], cr['secs'], base['played'],
                                                          base['games'], fuel, seed, cr['hello'], 2 * cr['played']))
    fam = collections.Counter(f for f, _ in maps)
    rep.append('maps (%d): %s' % (len(maps), ', '.join('%s %d' % (k, fam[k]) for k, _, _ in FAMILIES)))
    rep.append('  ' + ' '.join(mp for _, mp in maps))
    rep.append('sites: CAND %d, BASE %d, shared %d, CAND-only (new) %d, BASE-only %d' %
               (len(csites), len(bsites), len(shared), len(new), len(base_only)))
    rep.append('traps (bot faults in the statistics): CAND %d, BASE %d;  libc++ hardening asserts: CAND %d, BASE %d'
               % (cr['faults'], base['faults'], len(hard_c), len([k for k in bsites if k[0] == 'libcxx-assert'])))
    rep.append('')
    rep.append('NEW UB SITES: %d' % len(new))
    for k in sorted(new):
        g, mx, ex = csites[k]
        w, txt = where(k[1])
        rep.append('  NEW %-20s %s  games=%d maxn=%s  %s' % (k[0], w, g, mx, ex[:160]))
        if txt:
            rep.append('      | ' + txt)
    for title, lst, src in (('SHARED (in BASE too)', shared, csites), ('BASE-ONLY', base_only, bsites)):
        if lst:
            rep.append('%s: %d' % (title, len(lst)))
            for k in sorted(lst):
                g, mx, ex = src[k]
                rep.append('  %-20s %s  games=%d maxn=%s  %s' % (k[0], k[1], g, mx, ex[:160]))
    if cr['fault_games']:
        rep.append('TRAPS by game (id map faults-A faults-B); a backtrace with source lines: cd %s && '
                   'WASMTIME_BACKTRACE_DETAILS=1 %s run bots/%s bots/%s --map %s/MAP.map26a --fuel %d -o %s/bt'
                   % (PROJ, CLI, os.path.basename(cdir), os.path.basename(cdir), MAPS, fuel, run))
        for gid, mp, fa, fb in cr['fault_games'][:30]:
            rep.append('  %d %s %d %d' % (gid, mp, fa, fb))
    if base['faults']:
        rep.append('WARNING: BASE trapped %d times (pre-existing; not counted against CAND)' % base['faults'])
    if not ok_run:
        rep.append('HARNESS ERROR: no games played or the UB runtime printed nothing (see %s/run.log)' % run)
    if cr['played'] < cr['games']:
        rep.append('WARNING: %d of %d games produced no replay (see run.log)' % (cr['games'] - cr['played'], cr['games']))
    if cr['trunc'] or base['trunc']:
        rep.append('WARNING: team stdout hit the %d-byte log limit (cand %d, base %d team logs): later sites may be missing'
                   % (LOGLIM, cr['trunc'], base['trunc']))
    if cr['bad'] or base['bad']:
        rep.append('WARNING: unreadable side bundles: cand %d, base %d' % (cr['bad'], base['bad']))
    rep.append('collector tables: %s/ubx.txt, %s/ubx.txt; replays %s' %
               (run, base.get('run'), run + '/rep' if keep else 'deleted (KEEP=0)'))
    rep.append('wall time %.0f s' % (time.time() - t_start))
    verdict = 'PASS' if passed else ('ERROR' if not ok_run else 'FAIL')
    rep.append('VERDICT: %s (pass = 0 new sites, 0 CAND traps or hardening asserts, 0 CAND bot faults)' % verdict)
    open(run + '/report.txt', 'w').write('\n'.join(rep) + '\n')
    print('\n'.join(rep))
    print('report: %s/report.txt' % run)
    sys.exit(0 if passed else (2 if not ok_run else 1))


if __name__ == '__main__':
    # 30 Oct 23:05: a shipcheck that fails early terminates its audit; SIGTERM as SystemExit lets play_remote's finally
    # remove the Condor job and its condor-work/ubq dir (cluster 1931 left ~4 MB there). SIGKILL: quotaguard prunes ubq.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main()
