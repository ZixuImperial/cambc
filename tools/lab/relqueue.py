"""relqueue.py - the release queue: the next live candidate is ready before the current verdict lands (cambc-71, 27 Oct).

On 26-27 Oct the live slot sat empty 30-90 min after each verdict while the next candidate was prepared. Candidates
that passed their local gates wait here, with their live checks registered (autoread.py) and their switches verified,
so the build session submits the next one as soon as autoread exits.

  relqueue.py add NAME --bot bots/DIR --base bots/DIR --switches 'SW=1,SW2=1' --autoread ARNAME [--family lean:L1]
                  --card ID --grill FILE --prereg FILE
                  --evidence 'SW: local read, file/LR line' [--evidence ...] [--parts bots/A,bots/B] [--by SESSION] [--front]
                  [--lane fast --screen FILE [--screen FILE2]]
  relqueue.py add NAME --lane fast --parts bots/A,bots/B --card IDA --card IDB --screen FILE [--screen FILE2] ...  (a pair)
      Checks every #define SW VALUE in the bot's source and freezes the source hash. The family (the live layout
      release_sets.sh plays) defaults to the one ARNAME's checks pair (autoread.py; lean:L1 for livecheck.py), and a
      --family they cannot pair is refused: pznofast went in as s2 and would have ended NEEDS REVIEW (LR:2745). A release train (several switches
      in one release, owner 26 Oct) gives --parts: one single-switch variant per switch, each with its own local
      evidence; the parts' changed functions (funcdiff vs --base) must not overlap, or the add is refused (--allow-overlap
      to override, and say why in --evidence).
      The ship gate (auto-push, owner-prompts section 7, 28 Oct): an entry is refused unless
        --grill FILE  has a verdict line saying PASS, none saying FAIL, and the bot's source hash (tourney.src_hash's 12
                      hex, or this file's 16);
        --prereg FILE is the prereg of the autoread registration ARNAME, whose frozen files are unchanged;
        autoread.py dry ARNAME has run every registered check, as registered, and each printed a DECISION line;
        --base        is the live build (relqueue.py live) or the bot of the last open entry (built on the release in flight).
      Only entries that passed this gate carry 'gate'; autoship.py ships nothing else.
      --lane fast (ADR 0010 fast lane, owner 28 Oct): one small change (one switch or a few constants) from econ, combat or
      experiments, outside the two board slots. It needs --screen FILE, the ~30-min Condor screen against the anchors on
      fresh maps (recipe: reports/fastlane_recipe_1028.md), whose path and hash the entry keeps; no --parts. The gate is
      otherwise the same, plus fastgate.py (owner LR:2776): gate() runs on --bot against --base with the --switches, the
      screen, the prereg and the family, and a FAIL refuses the add with its FAIL lines. A PASS replaces the grill and
      co-sign: --grill is optional on the fast lane (checked if given). The entry keeps fastgate = {ok, rules, screen_sha,
      lab, at}. The live sets and the automatic revert decide.
      A fast-lane pair (owner 28 Oct, itfastq): two fast-lane changes from different roles in one build and one live read.
      It needs exactly two --parts and two --card IDs on the board whose owners are two different roles of econ, combat
      and experiments; the parts' changed functions must not overlap (no --allow-overlap), the parts must merge cleanly
      onto --base (git merge-file) into exactly --bot's source, and neither card may be in another open entry. The entry
      keeps cards [IDA, IDB] (card = IDA); done records the verdict on both cards (board.py sync), and a REVERT reverts
      the one combined build. On the board the pair takes each role's fast-lane slot. fastgate runs on the combined
      --bot with --items 2, on the --screen whose fldecide tourney lines name the combined build (the A+B arm of the 2x2
      screen, LR:2776); a pair with no such screen FAILs the gate.
      Every entry keeps base_src / base_lab, the source hashes of the --base it was built on: if another build is live
      when it reaches the head (the entry ahead was reverted), autoship.py merges it onto the live build by diff
      (owner 28 Oct, LR:2780) and records that with rebase.
      A registration with base reuse (autoread.py --reuse) passes only if its dry run checked the reuse tag.
  relqueue.py next [--json]  the first ready entry, re-verified (source unchanged, switches, autoread registered, no live
                        set still playing, base sets present, its base is the live build), and the exact commands to ship
                        it. Never submits. --json: {name, entry, problems: [[kind, text]]} for autoship.py.
  relqueue.py live [--set bots/DIR --version vNNN --why TEXT]   the live build (state/live.json); done keeps it current.
      since = when that version went live (its builds.txt line), else the time it was recorded; recorded = the latter.
  relqueue.py rebase NAME --bot bots/MERGED --onto bots/LIVE [--live-src H] [--why TEXT] [--by S]
      (autoship.py) the entry now ships MERGED, built on LIVE; the build it was queued as stays in rebased_from.
  relqueue.py list      | done NAME --result KEEP|REVERT [--version vNNN] [--live-version vNNN] | drop NAME --why TEXT
      done KEEP: the entry's bot goes live as --version. done REVERT: its base is live again, as --live-version (the
      version the resubmit created) if given.
State: reports/state/queue.json, live.json (and queue.md for readers). Only the build session (or autoship.py) submits."""
import fcntl, glob, hashlib, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader

REPO = '/homes/zw4424/cambc'
PLAT = os.environ.get('RELQUEUE_PLAT') or '/data/zw4424/plat'          # override for tests
REPORTS = os.environ.get('AUTOREAD_REPORTS') or '/homes/zw4424/condor-work/reports'      # override for tests
Q, QMD, SPECS = REPORTS + '/state/queue.json', REPORTS + '/state/queue.md', REPORTS + '/state/autoread'
LIVE = REPORTS + '/state/live.json'
BOARD = os.environ.get('BOARD_STATE') or REPORTS + '/state'
SUBMIT = '/data/zw4424/cambc400/bin/cambc400 submit'
BUILDS = os.environ.get('RELQUEUE_BUILDS') or '/data/zw4424/mf/v188/builds.txt'      # vNNN -> submit time (release_sets.sh)
WASI = os.environ.get('RELQUEUE_WASI') or os.path.expanduser('~/.cache/cambc/wasi-sdk-33')     # the toolchain cambc builds with
SDK_INC = os.environ.get('RELQUEUE_SDK_INC') or '/data/zw4424/cambc400/proj/sdk/cpp'               # cambc.h
FASTGATE = os.environ.get('RELQUEUE_FASTGATE') or REPO + '/tools/lab/fastgate.py'     # the fast-lane gate (owner LR:2776)
PLAYING_H = 3                                   # a set log changed within this many hours, no DONE/FINISHED, no matches.txt = playing


def utc(fmt='%Y-%m-%d %H:%M UTC'):
    return datetime.now(timezone.utc).strftime(fmt)


def src_files(bot):
    root = os.path.realpath(bot)
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith('.')]
        out += [os.path.join(d, f) for f in files if re.search(r'\.(cpp|h|hpp|c|cc|toml|json|txt)$', f)]
    return sorted(out)


def src_hash(bot):
    h = hashlib.sha256()
    root = os.path.realpath(bot)
    for f in src_files(bot):
        h.update(os.path.relpath(f, root).encode() + b'\0' + open(f, 'rb').read())
    return h.hexdigest()[:16]


def lab_hash(bot):
    """tourney.src_hash: the 12-hex hash grills and reads cite."""
    out = subprocess.run("find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12", shell=True, cwd=bot,
                         capture_output=True, text=True)
    return out.stdout.strip()


def live():
    """{bot, version, since, by, why} of the live build, or None if nobody recorded it (relqueue.py live --set)."""
    try:
        return json.load(open(LIVE))
    except (OSError, ValueError):
        return None


def went_live(version):
    """'YYYY-MM-DD HH:MM UTC' of version's builds.txt line (its submit), or None."""
    try:
        hit = [l.split()[0] for l in open(BUILDS) if l.split()[1:2] == [version]]
    except (OSError, IndexError):
        return None
    return hit[-1][:16].replace('T', ' ') + ' UTC' if hit else None


def set_live(bot, version, by, why):
    os.makedirs(os.path.dirname(LIVE), exist_ok=True)
    tmp = LIVE + '.tmp%d' % os.getpid()
    # since = when the version went live, not when someone recorded it (28 Oct: v247 read "since 28 Oct 12:41", live 27 Oct 22:41)
    now = utc()
    json.dump(dict(bot=bot, version=version, since=went_live(version) or now, recorded=now, by=by, why=why), open(tmp, 'w'), indent=1)
    os.replace(tmp, LIVE)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def grill_ok(f, bot):
    """'' if grill file f passes bot (a PASS verdict line, no FAIL one, the bot's source hash in it), else why not."""
    try:
        txt = open(f, errors='replace').read()
    except OSError:
        return 'grill %s not found' % f
    said = [m.group(1).upper() for l in txt.splitlines() if re.search(r'verdict', l, re.I)
            for m in [re.search(r'\b(PASS(?:ES|ED)?|FAIL(?:S|ED)?)\b', l, re.I)] if m]
    if not said or any(s.startswith('FAIL') for s in said) or not any(s.startswith('PASS') for s in said):
        return 'grill %s: verdict lines say %s (need PASS and no FAIL)' % (f, ', '.join(said) or 'nothing')
    h12, h16 = lab_hash(bot), src_hash(bot)
    if h12 not in txt and h16 not in txt:
        return 'grill %s does not name this source (src %s / %s): grill the code that is queued' % (f, h12, h16)
    return ''


def dry_ok(ar, prereg):
    """[problems] with autoread registration ar: its prereg is prereg, its frozen files are unchanged, and a dry run of
    every registered check printed a DECISION line (autoread.py dry ar)."""
    try:
        spec = json.load(open('%s/%s.json' % (SPECS, ar)))
    except (OSError, ValueError):
        return ['autoread %s is not registered (autoread.py register %s ... or autoread.py prereg)' % (ar, ar)]
    probs = []
    if not spec.get('prereg') or not prereg or os.path.realpath(spec['prereg']) != os.path.realpath(prereg):
        probs.append('autoread %s was registered with prereg %s, not %s' % (ar, spec.get('prereg') or 'none', prereg))
    changed = [p for c in spec['checks'] for p, h in c['frozen'].items() if not os.path.exists(p) or sha(p) != h]
    if changed:
        probs.append('frozen files changed since registration: ' + ', '.join(changed))
    try:
        dry = json.load(open('%s_dry/%s.json' % (SPECS, ar)))
    except (OSError, ValueError):
        return probs + ['no dry run: autoread.py dry %s' % ar]
    if dry.get('registered') != spec['registered'] or [c['cmd'] for c in dry.get('checks', [])] != [c['cmd'] for c in spec['checks']]:
        probs.append('the dry run is of another registration: autoread.py dry %s' % ar)
    for i, c in enumerate(dry.get('checks', [])):
        if not c.get('decision') or c.get('rc') not in (0, 3, 4):
            probs.append('dry run check %d: %s (output %s)' % (i + 1, 'exit %s' % c.get('rc') if c.get('decision') else 'no DECISION line', c.get('out')))
    if spec.get('reuse'):
        r = dry.get('reuse')
        if not r or r.get('tag') != spec['reuse']:
            probs.append('the dry run did not check base reuse --reuse %s: autoread.py dry %s' % (spec['reuse'], ar))
        elif r.get('problems'):
            probs.append('base reuse --reuse %s: %s' % (spec['reuse'], '; '.join(r['problems'])))
    return probs


def tu_defines(bot):
    """{name: {value}} over the bot's translation units, as the compiler sees them: each .cpp through clang -dM -E with the
    release flags. None when the toolchain or the SDK header is missing or any unit fails to preprocess."""
    cxx = WASI + '/bin/clang++'
    if not (os.path.exists(cxx) and os.path.exists(SDK_INC + '/cambc.h')):
        return None
    cpps = [f for f in src_files(bot) if f.endswith('.cpp')]
    cmd = [cxx, '--target=wasm32-wasip1', '--sysroot=' + WASI + '/share/wasi-sysroot',
           '-isystem', WASI + '/share/wasi-sysroot/include/wasm32-wasip1/eh/c++/v1', '-I' + SDK_INC,
           '-std=c++20', '-fwasm-exceptions', '-DNDEBUG', '-dM', '-E']

    def one(f):
        try:
            return subprocess.run(cmd + [f], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
    with ThreadPoolExecutor(8) as ex:
        runs = list(ex.map(one, cpps))
    if not cpps or any(r is None or r.returncode for r in runs):
        return None
    out = {}
    for r in runs:
        for m in re.finditer(r'^#define (\w+) (.*)$', r.stdout, re.M):
            out.setdefault(m.group(1), set()).add(m.group(2).strip())
    return out


def switch_check(bot, switches):
    """[(name, wanted, found values, uses)]. Found values are each switch's value in every .cpp that sees it, from the
    preprocessor (tu_defines), so #ifndef defaults, ship builds' hard defines and #if fallbacks such as rs.h's
    `#if !RULES_SYNC ... #define RS_C1 0` read as compiled; two values mean the units disagree. Without the toolchain
    it falls back to the #define lines: a default under `#ifndef NAME` counts only when no unguarded #define sets NAME
    (that fallback misreads #if blocks)."""
    text = {f: open(f, errors='replace').read() for f in src_files(bot) if re.search(r'\.(cpp|h|hpp|c|cc)$', f)}
    tu = tu_defines(bot)
    out = []
    for name, want in switches.items():
        if tu is not None:
            vals = sorted(tu.get(name, ()))
        else:
            guard = r'^\s*#\s*ifndef\s+%s\b[^\n]*\n\s*#\s*define\s+%s\s+(\S+)' % (re.escape(name), re.escape(name))
            dflt = {v for t in text.values() for v in re.findall(guard, t, re.M)}
            hard = {v for t in text.values() for v in re.findall(r'^\s*#\s*define\s+%s\s+(\S+)' % re.escape(name), re.sub(guard, '', t, flags=re.M), re.M)}
            vals = sorted(hard or dflt)
        uses = sum(len(re.findall(r'\b%s\b' % re.escape(name), t)) for t in text.values())
        out.append((name, want, vals, uses))
    return out


BUILD_PRODUCTS = ('compile_commands.json',)   # the CLI rewrites it on every build (with absolute paths): never merged


def tree(bot):
    """{relpath: bytes} of a bot dir: every file outside dot dirs and dot files (the build cache is .cambc), less the
    build products the CLI writes at the bot's root."""
    root, out = os.path.realpath(bot), {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith('.')]
        for f in files:
            if not f.startswith('.') and not (d == root and f in BUILD_PRODUCTS):
                out[os.path.relpath(os.path.join(d, f), root)] = open(os.path.join(d, f), 'rb').read()
    return out


def merge3(cand, base, live, out):
    """Put cand's changes against base on top of live (owner 28 Oct, LR:2780: queued candidates follow the live build by
    diff), per file: one side unchanged takes the other; both changed: git merge-file -p on temporary copies of the
    three versions (LIVE BASE CAND), its output written to a new file. Returns [conflicts]; with none, the merged tree is
    in out, a NEW dir made with cp -rL from live (owner tab, LR 15:48: bots/ entries are often symlinks into /data, and a
    15:30 check patched the live base through one): no symlink is followed for writing, and out holds none.
    The three inputs are only read."""
    import tempfile
    c, b, l = tree(cand), tree(base), tree(live)
    res, bad = {}, []
    with tempfile.TemporaryDirectory(prefix='merge3_') as td:
        for f in sorted(set(c) | set(b) | set(l)):
            cv, bv, lv = c.get(f), b.get(f), l.get(f)
            if '/' not in f:  # 12 Nov (Builder: fsz4iu/esr3ru PASSes refused at submit, "FLIP: added on one side, changed on the other"):
                # root-level files (BASE, FLIP, SHIPCHECK ...) are the bot's own bookkeeping, not code; since rebases merge from the BAKED
                # base (which has none), they read as conflicts. The candidate's copy wins (its flips and trunk), else live's
                m = cv if cv is not None else lv
                if m is not None:
                    res[f] = m
                continue
            if cv == bv:
                m = lv
            elif lv == bv or lv == cv:
                m = cv
            elif None in (cv, bv, lv):
                bad.append('%s: %s on one side, changed on the other' % (f, 'added' if bv is None else 'deleted'))
                continue
            else:
                for n, v in (('l', lv), ('b', bv), ('c', cv)):
                    open(os.path.join(td, n), 'wb').write(v)
                r = subprocess.run(['git', 'merge-file', '-p', '-L', 'live', '-L', 'base', '-L', 'candidate',
                                    os.path.join(td, 'l'), os.path.join(td, 'b'), os.path.join(td, 'c')], capture_output=True)
                if r.returncode > 0 and f.endswith('_flags.h'):
                    # 12 Nov (RC C780: kcv7, obv13, vkd1rs refused after v831: live and the candidate each APPENDED a flag block at the
                    # same end of *_flags.h): when every conflict block is a pure addition on both sides (empty base part), keep both,
                    # live's first then the candidate's (git merge-file --union), as armq's merge3 already does
                    d3 = subprocess.run(['git', 'merge-file', '-p', '--diff3', os.path.join(td, 'l'), os.path.join(td, 'b'), os.path.join(td, 'c')],
                                        capture_output=True).stdout.decode('utf-8', 'surrogateescape')
                    bl = re.findall(r'^\|{7}[^\n]*\n(.*?)^={7}$', d3, re.M | re.S)
                    if bl and all(not x.strip() for x in bl):
                        r = subprocess.run(['git', 'merge-file', '-p', '--union', os.path.join(td, 'l'), os.path.join(td, 'b'), os.path.join(td, 'c')],
                                           capture_output=True)
                if r.returncode:
                    bad.append('%s: %s' % (f, '%d conflict(s)' % r.returncode if r.returncode > 0 else 'git merge-file error %s' % r.stderr[-200:]))
                    continue
                m = r.stdout
            if m is not None:
                res[f] = m
    if bad:
        return bad
    if os.path.lexists(out):
        raise RuntimeError('merge3: %s exists: the merge goes into a new dir only' % out)
    r = subprocess.run(['cp', '-rL', os.path.realpath(live), out], capture_output=True, text=True)
    links = subprocess.run(['find', out, '-type', 'l'], capture_output=True, text=True).stdout.strip()
    if r.returncode or links or os.path.islink(out):
        raise RuntimeError('merge3: cp -rL %s %s failed or left symlinks: %s %s' % (live, out, r.stderr[-200:], links[:200]))
    root = os.path.realpath(out)
    for x in os.listdir(out):                   # the build cache, dot files and build products of the live copy
        if x.startswith('.') or x in BUILD_PRODUCTS:
            subprocess.run(['rm', '-rf', os.path.join(out, x)])
    for f in sorted(set(c) | set(b) | set(l)):
        dst = os.path.join(out, f)
        if not os.path.realpath(os.path.dirname(dst)).startswith(root + os.sep) and os.path.realpath(os.path.dirname(dst)) != root:
            raise RuntimeError('merge3: %s is outside %s' % (dst, out))
        if os.path.lexists(dst):
            os.unlink(dst)                      # a new file, never a write into the copied one
        if f in res:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'xb').write(res[f])
    links = subprocess.run(['find', out, '-type', 'l'], capture_output=True, text=True).stdout.strip()
    if links or tree(out) != res:
        raise RuntimeError('merge3: %s is not the merged tree (symlinks: %s)' % (out, links[:200] or 'none'))
    return []


def change(old, new):
    """(removed lines, added lines) of one file, in order: a diff with its line numbers and hunk grouping left out."""
    import difflib
    a, b = (old or b'').decode(errors='replace').splitlines(), (new or b'').decode(errors='replace').splitlines()
    rm, ad = [], []
    for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if t != 'equal':
            rm += a[i1:i2]
            ad += b[j1:j2]
    return rm, ad


def same_change(cand, base, live, merged):
    """[files whose change differs]: the candidate's diff against its base must equal the merged build's against live
    (coordinator 28 Oct: the merged build is not the one the grill saw, so it ships only with the same change)."""
    c, b, l, m = tree(cand), tree(base), tree(live), tree(merged)
    return [f for f in sorted(set(c) | set(b) | set(l) | set(m))
            if (c.get(f) != b.get(f) or l.get(f) != m.get(f)) and change(b.get(f), c.get(f)) != change(l.get(f), m.get(f))]


def changed_funcs(part, base):
    r = subprocess.run([sys.executable, '-I', REPO + '/tools/lab/funcdiff.py', part, base], capture_output=True, text=True)
    fn, decl = set(), set()
    for l in r.stdout.splitlines():
        m = re.match(r'^\s+([\w./-]+):\d+-\d+\s+\+\d+ -\d+\s+(.*)$', l)
        if m:
            sig = re.sub(r'^(NEW|DELETED)\s+', '', m.group(2)).strip()
            (decl if sig.startswith('(outside functions') else fn).add('%s %s' % (m.group(1), sig))
    return fn, decl


class Locked:
    def __enter__(self):
        os.makedirs(os.path.dirname(Q), exist_ok=True)
        self.f = open(Q + '.lock', 'w')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        try:
            self.q = json.load(open(Q))
        except (OSError, ValueError):
            self.q = []
        return self.q

    def __exit__(self, *exc):
        if exc[0] is None:
            tmp = Q + '.tmp%d' % os.getpid()
            json.dump(self.q, open(tmp, 'w'), indent=1)
            os.replace(tmp, Q)
            render(self.q)
        fcntl.flock(self.f, fcntl.LOCK_UN)


def render(q):
    L = ['# Release queue (tools/lab/relqueue.py; written %s)' % utc(), '',
         'The build session ships the first `ready` entry when the live slot frees: `python3 -I tools/lab/relqueue.py next`.', '']
    for e in q:
        L.append('- **%s** [%s]%s %s: switches %s; autoread %s; added %s by %s%s' % (
            e['name'], e['status'], ' FAST LANE (screen %s)' % e['screen']['path'] if e.get('lane') == 'fast' else '', e['bot'], ', '.join('%s=%s' % kv for kv in e['switches'].items()), e.get('autoread') or '-',
            e['added'], e.get('by') or '?', ('; result %s %s' % (e.get('result'), e.get('version') or '')) if e.get('result') else ''))
        for ev in e.get('evidence', []):
            L.append('  - %s' % ev)
        if e.get('overlap'):
            L.append('  - overlap allowed: %s' % '; '.join(e['overlap']))
        if e.get('cards'):
            L.append('  - fast-lane pair: cards %s' % ' + '.join(e['cards']))
        for r in e.get('rebases', []):
            L.append('  - merged onto %s by diff: %s (src %s / %s) %s' % (r['onto'], r['bot'], r['src'], r['lab'], r['at']))
    tmp = QMD + '.tmp%d' % os.getpid()
    open(tmp, 'w').write('\n'.join(L) + '\n')
    os.replace(tmp, QMD)


LIVECHECK_FAMILY = 'lean:L1'    # livecheck.py pairs lean:L1 cells only (its V4)


def checks_family(spec):
    """The layout an autoread registration's checks pair: its family (autoread.py, 28 Oct), else lean:L1 if a check
    runs livecheck.py, else '' (unknown: the entry's --family stands)."""
    return spec.get('family') or (LIVECHECK_FAMILY if any('livecheck.py' in c.get('cmd', '') for c in spec.get('checks', [])) else '')


def opts(a, k):
    return [a[i + 1] for i, x in enumerate(a[:-1]) if x == k]


def fastgate_ok(bot, base, sw, screens, prereg, fam, items):
    """([problems], record): fastgate.gate() on bot against base (owner LR:2776). A pair (items 2) is gated on the screen
    whose tourney lines name bot's source as CAND; else the first. record is kept on the entry as e['fastgate']."""
    try:
        fg = SourceFileLoader('fastgate_rq', FASTGATE).load_module()
    except (OSError, SyntaxError, ImportError) as ex:
        return ['fastgate %s cannot be loaded: %s' % (FASTGATE, ex)], None
    scr = screens[0] if screens else ''
    if items == 2:
        h = lab_hash(os.path.join(REPO, bot))
        named = [s for s in screens if os.path.isfile(s) and re.search(r'^tourney \S+: .*?CAND \S+ \(%s\)' % h, open(s, errors='replace').read(), re.M)]
        scr = named[0] if named else scr
    rep = {}
    try:
        ok, lines = fg.gate(bot, base, sw, scr, prereg, fam, items=items, report=rep)
    except Exception as ex:                       # a gate that cannot run is a FAIL, never a pass
        return ['fastgate crashed: %s: %s' % (type(ex).__name__, ex)], None
    rec = dict(ok=bool(ok), screen=os.path.realpath(scr) if scr else '', screen_sha=rep.get('screen_sha'), lab=rep.get('lab'),
               items=items, at=utc(), rules=['%s %s' % ('PASS' if r.get('ok') else 'FAIL', r.get('rule')) for r in rep.get('rules', [])])
    if ok:
        return [], rec
    return ['fastgate FAIL (owner LR:2776; tools/lab/fastgate.py check %s %s --screen %s --prereg %s --items %d):\n      %s' % (
        bot, base, scr or '(none)', prereg or '(none)', items, '\n      '.join(l for l in lines if not l.startswith('PASS')))], rec


def add(name, a):
    one = lambda k: (opts(a, k) or [''])[0]
    bot, base, ar, fam = one('--bot'), one('--base'), one('--autoread'), one('--family')
    sw = dict(kv.split('=', 1) for kv in one('--switches').split(',') if '=' in kv)
    ev = opts(a, '--evidence')
    try:
        cf = checks_family(json.load(open('%s/%s.json' % (SPECS, ar)))) if ar else ''
    except (OSError, ValueError):
        cf = ''
    fam = fam or cf
    if not (bot and base and sw and ev and fam):
        sys.exit('add NAME --bot bots/DIR --base bots/DIR --switches SW=1,... --evidence TEXT --autoread ARNAME [--family lean:L1] [--parts ...]'
                 + ('' if fam else ' (no --family, and none from the registration\'s checks)'))
    for b in (bot, base):
        if not os.path.isdir(os.path.join(REPO, b)):
            sys.exit('no bot dir %s' % b)
    bad = [s for s in switch_check(os.path.join(REPO, bot), sw) if s[2] != [s[1]]]
    if bad:
        sys.exit('switch mismatch in %s: %s' % (bot, '; '.join('%s wanted %s, #define gives %s' % (n, w, v or 'none') for n, w, v, _ in bad)))
    overlap = []
    parts = [p for p in one('--parts').split(',') if p]
    lane, screens, cids = one('--lane'), opts(a, '--screen'), opts(a, '--card')
    pair = lane == 'fast' and bool(parts)
    if pair and (len(parts) != 2 or len(cids) != 2):
        sys.exit('--lane fast takes one small change, or a pair (owner 28 Oct): --parts bots/A,bots/B with --card IDA --card IDB '
                 '(%d part(s), %d card(s))' % (len(parts), len(cids)))
    if pair and '--allow-overlap' in a:
        sys.exit('--allow-overlap is not for the fast lane: a pair whose parts overlap takes the full path')
    if len(cids) > 1 and not pair:
        sys.exit('one --card per entry (two only for a fast-lane pair)')
    if len(screens) > (2 if pair else 1):
        sys.exit('--screen: one file%s' % (', or one per part of a pair' if pair else ''))
    if parts:
        if len(ev) < len(parts):
            sys.exit('a train needs local evidence for each part (%d parts, %d --evidence)' % (len(parts), len(ev)))
        seen = {}
        for p in parts:
            fn, _ = changed_funcs(os.path.join(REPO, p), os.path.join(REPO, base))
            for f in fn:
                if f in seen:
                    overlap.append('%s and %s both change %s' % (seen[f], p, f))
                seen.setdefault(f, p)
        if overlap and '--allow-overlap' not in a:
            sys.exit('train parts overlap (they interact; a REVERT could not be traced to one part):\n  ' + '\n  '.join(overlap))
    card, grill, prereg = one('--card'), one('--grill'), one('--prereg')
    screen = screens[0] if screens else ''
    if lane not in ('', 'fast'):
        sys.exit('--lane: fast, or leave it out (the normal path)')
    if screen and not lane:
        sys.exit('--screen goes with --lane fast')
    try:
        bcards = {c.get('id'): c for c in json.load(open('%s/board.json' % BOARD)).get('cards', [])}
    except (OSError, ValueError):
        bcards = {}
    probs = ['--card %s is not a board card' % (c or '(missing)') for c in (cids or [card]) if c not in bcards]
    if pair:
        probs += pair_problems(cids, bcards, parts, base, overlap, bot)
    probs += [grill_ok(grill, os.path.join(REPO, bot))] if grill else [] if lane else ['--grill FILE missing']
    probs += dry_ok(ar, prereg) if ar else ['--autoread ARNAME missing']
    if cf and fam != cf:
        probs.append('--family %s: the checks of %s pair %s cells, so its read would end NEEDS REVIEW and auto-revert (pznofast, LR:2745); '
                     'leave --family out to take %s' % (fam, ar, cf, cf))
    for scr in (screens or [''])[:2] if lane else []:
        if not (scr and os.path.isfile(scr) and os.path.getsize(scr)):
            probs.append('--lane fast needs --screen FILE, the Condor screen against the anchors (reports/fastlane_recipe_1028.md): %s'
                         % (scr or 'missing') + ('' if not scr or os.path.isfile(scr) else ' not found'))
    fgrec = None
    if lane and not [p for p in probs if p]:      # the gate builds and smokes: only once every cheap check passed
        fp, fgrec = fastgate_ok(bot, base, sw, screens, prereg, fam, 2 if pair else 1)
        probs += fp
    with Locked() as q:
        lv = live()
        head = [e['bot'] for e in q if e['status'] == 'ready']
        ok_base = ([lv['bot']] if lv else []) + head[-1:]
        if base not in ok_base:
            probs.append('--base %s is neither the live build (%s) nor the last open entry (%s)' % (
                base, lv['bot'] if lv else 'unknown: relqueue.py live --set', head[-1] if head else 'none'))
        probs = [p for p in probs if p]
        if probs:
            sys.exit('add %s refused (the ship gate, owner-prompts section 7):\n  - %s' % (name, '\n  - '.join(probs)))
        if any(e['name'] == name for e in q):
            sys.exit('%s is already queued' % name)
        busy = ['%s (in %s)' % (c, e['name']) for e in q if e['status'] == 'ready' for c in cids if c in entry_cards(e)] if pair else []
        if busy:
            sys.exit('add %s refused: a fast-lane pair\'s cards may not be in another open entry: %s' % (name, ', '.join(busy)))
        if '--front' in a and not (lv and base == lv['bot']):
            sys.exit('--front needs --base the live build: it would ship ahead of the entry it is built on')
        e = dict(name=name, bot=bot, base=base, switches=sw, autoread=ar, family=fam, evidence=ev, parts=parts, overlap=overlap,
                 by=one('--by'), added=utc(), src=src_hash(os.path.join(REPO, bot)), status='ready',
                 # the base it was built on, so autoship can put it on another live build by diff (owner 28 Oct, LR:2780)
                 base_src=src_hash(os.path.join(REPO, base)), base_lab=lab_hash(os.path.join(REPO, base)),
                 card=card, gate=dict(grill=os.path.realpath(grill), prereg=os.path.realpath(prereg), lab=lab_hash(os.path.join(REPO, bot)),
                                      base_was='live' if lv and base == lv['bot'] else 'in flight', at=utc()))
        if lane:
            e['lane'], e['screen'] = lane, dict(path=os.path.realpath(screen), sha=sha(screen)[:16])
            if len(screens) > 1:
                e['screens'] = [dict(path=os.path.realpath(x), sha=sha(x)[:16]) for x in screens]
            e['fastgate'] = fgrec
        if pair:
            e['cards'] = list(cids)
        q.insert(0, e) if '--front' in a else q.append(e)
    print('queued %s (%s, src %s / %s, card %s%s): passed the ship gate' % (name, bot, e['src'], e['gate']['lab'], ' + '.join(entry_cards(e)),
          ', fast lane' + (' pair' if pair else '') if lane else ''))


def entry_cards(e):
    """The board cards of a queue entry: both cards of a fast-lane pair, else its one card."""
    return list(e.get('cards') or ([e['card']] if e.get('card') else []))


def pair_problems(cids, bcards, parts, base, overlap, bot):
    """Why a fast-lane pair (owner 28 Oct, LR:2776) may not queue: two cards of two different fast-lane roles, parts that
    change no function in common, and a combined build that is the two parts' diffs merged onto the base."""
    p = []
    if len(set(cids)) != 2:
        p.append('a pair needs two different cards (--card %s)' % ' --card '.join(cids))
    roles = [(bcards.get(c) or {}).get('owner') for c in cids]
    if any(r not in FAST_ROLES for r in roles):
        p.append('both cards need an owner role among %s (%s)' % (', '.join(FAST_ROLES), ', '.join('%s: %s' % (c, r or 'none') for c, r in zip(cids, roles))))
    elif roles[0] == roles[1]:
        p.append('both cards belong to %s: a pair is one fast item from each of two roles' % roles[0])
    if overlap:
        p.append('the parts overlap (the fast lane takes no --allow-overlap): ' + '; '.join(overlap))
    elif len(parts) == 2 and all(os.path.isdir(os.path.join(REPO, x)) for x in parts + [base, bot]):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='relq_pair_') as td:
            bad = merge3(os.path.join(REPO, parts[1]), os.path.join(REPO, base), os.path.join(REPO, parts[0]), td + '/m')
            if bad:
                p.append('the parts do not merge cleanly: ' + '; '.join(bad))
            elif tree(td + '/m') != tree(os.path.join(REPO, bot)):
                diff = sorted(f for f in set(tree(td + '/m')) | set(tree(os.path.join(REPO, bot))) if tree(td + '/m').get(f) != tree(os.path.join(REPO, bot)).get(f))
                p.append('--bot %s is not the two parts merged onto --base (%s differ): one combined build of exactly the pair' % (bot, ', '.join(diff[:5])))
    return p


FAST_ROLES = ('econ', 'combat', 'experiments')  # board.py's fast-lane roles


def playing():
    out = []
    for log in glob.glob(PLAT + '/*.log'):
        if log.endswith('.dl.log') or time.time() - os.path.getmtime(log) > PLAYING_H * 3600:
            continue
        try:
            txt = open(log, errors='replace').read()
        except OSError:
            continue
        # diag.sh writes matches.txt only once every match has finished; after that it is downloading, not playing
        # (its .log stays empty while it downloads: sAv240_P and unr_1027_1449 read as playing at 15:00 on 27 Oct)
        # unr_watch.sh's batches (unr_STAMP, about every 20 min) only download groups whose matches had all finished
        # (diag.sh --dl creates no group, so no created_*.json): never playing. Stalled v248's ship gate 28 Oct 13:10.
        d = log[:-4]
        if os.path.basename(d).startswith('unr_') and os.path.isfile(d + '/groups.txt') and not glob.glob(d + '/created_*.json'):
            continue
        if not re.search(r'^(DONE|FINISHED|sets done)', txt, re.M) and not os.path.exists(d + '/matches.txt'):
            out.append(os.path.basename(log)[:-4])
    return sorted(out)


def nxt(a):
    try:
        q = json.load(open(Q))
    except (OSError, ValueError):
        q = []
    ready = [e for e in q if e['status'] == 'ready']
    js = '--json' in a
    if not ready:
        print(json.dumps(dict(name=None, entry=None, problems=[])) if js else 'queue empty: nothing ready to ship (the live slot will sit idle)')
        sys.exit(1)
    e, probs = ready[0], []
    bot = os.path.join(REPO, e['bot'])
    if not os.path.isdir(bot):
        probs.append(('gone', 'bot dir %s is gone' % e['bot']))
    else:
        if src_hash(bot) != e['src']:
            probs.append(('src', 'source changed since it was queued (src %s, queued %s): re-run its gates and re-add' % (src_hash(bot), e['src'])))
        for n, w, v, uses in switch_check(bot, e['switches']):
            if v != [w]:
                probs.append(('switch', '%s wanted %s, #define gives %s' % (n, w, v or 'none')))
    spec = None
    if e.get('autoread'):
        try:
            spec = json.load(open('%s/%s.json' % (SPECS, e['autoread'])))
        except OSError:
            probs.append(('autoread', 'autoread %s not registered' % e['autoread']))
    else:
        probs.append(('autoread', 'no autoread registration: register the pre-registered checks before submitting'))
    lv = live()
    if lv and e['base'] != lv['bot']:
        probs.append(('notlive', 'its base %s is not the live build %s (the entry ahead was reverted?): %s' % (e['base'], lv['bot'],
                      'autoship.py merges it onto the live build by diff before the submit' if rebasable(e) else 'rebuild it on the live build')))
    busy = playing()
    if busy:
        probs.append(('playing', 'live sets still playing (they play the CURRENT submission): ' + ', '.join(busy)))
    if spec:
        for s in (spec['base'] + '_T', spec['base'] + '_P'):
            if not re.search(r'^DONE', open('%s/%s.log' % (PLAT, s), errors='replace').read() if os.path.exists('%s/%s.log' % (PLAT, s)) else '', re.M) \
                    and not os.path.exists('%s/%s/matches.txt' % (PLAT, s)):
                probs.append(('baseset', 'base set %s not played: play it while the base build is live, before this submit' % s))
    if js:
        print(json.dumps(dict(name=e['name'], entry=e, spec=spec, live=lv, problems=probs), indent=1))
        sys.exit(2 if probs else 0)
    sw = switch_check(bot, e['switches']) if os.path.isdir(bot) else []
    print('NEXT: %s  (%s, src %s, queued %s by %s)' % (e['name'], e['bot'], e['src'], e['added'], e.get('by') or '?'))
    print('  switches: ' + ', '.join('%s=%s (%d uses)' % (n, w, u) for n, w, v, u in sw))
    print('  ship gate: ' + ('passed %s (card %s, grill %s)' % (e['gate']['at'], e.get('card'), e['gate']['grill']) if e.get('gate')
                             else 'none (queued before the gate): ships by hand only, never by autoship.py'))
    for ev in e.get('evidence', []):
        print('  evidence: ' + ev)
    if probs:
        print('NOT READY:\n  - ' + '\n  - '.join(t for k, t in probs))
        sys.exit(2)
    pfx = spec['new']
    print('commands (build session only):')
    print('  %s %s' % (SUBMIT, e['bot']))
    print('  # note the platform version vNNN and submit time, then:')
    print('  sh /data/zw4424/mf/py/release_sets.sh vNNN SUBMIT_TIME_UTC %s %s   # background' % (pfx, e['family']))
    print('  python3 -I tools/lab/autoread.py run %s   # background: wakes you with the verdict' % e['autoread'])
    print('  python3 -I tools/lab/relqueue.py done %s --result KEEP|REVERT --version vNNN   # after the verdict' % e['name'])


def mark(name, a, status):
    with Locked() as q:
        hit = [e for e in q if e['name'] == name]
        if not hit:
            sys.exit('%s is not queued' % name)
        e = hit[0]
        e['status'] = status
        e['closed'] = utc()
        if status == 'done':
            e['result'], e['version'] = (opts(a, '--result') or ['?'])[0], (opts(a, '--version') or [''])[0]
            lv, by = live(), (opts(a, '--by') or ['relqueue.py done'])[0]
            if e['result'] == 'KEEP':
                set_live(e['bot'], e['version'], by, '%s KEEP' % name)
            elif e['result'].startswith('REVERT'):
                ver = (opts(a, '--live-version') or [lv['version'] if lv and lv['bot'] == e['base'] else ''])[0]
                set_live(e['base'], ver, by, '%s %s: base resubmitted' % (name, e['result']))
        else:
            e['why'] = (opts(a, '--why') or [''])[0]
    print('%s: %s' % (name, status))
    lv = live()
    if status == 'done' and lv:
        print('live: %s as %s%s' % (lv['bot'], lv['version'] or '(version unknown)',
                                   '' if lv['version'] else ': relqueue.py live --set %s --version vNNN' % lv['bot']))


def rebasable(e):
    """An entry autoship may put on another live build by diff: it recorded the base it was built on (added since 28 Oct)."""
    return bool(e.get('base_src') or e.get('rebased_from'))


def rebase(name, a):
    """Record that autoship merged entry NAME onto the live build (owner 28 Oct, LR:2780): the entry's bot becomes the
    merged build and its base the live build; what was queued stays in rebased_from (the merge source for any later
    rebase), and each rebase is listed in rebases."""
    one = lambda k: (opts(a, k) or [''])[0]
    bot, onto = one('--bot'), one('--onto')
    if not (bot and onto and os.path.isdir(os.path.join(REPO, bot)) and os.path.isdir(os.path.join(REPO, onto))):
        sys.exit('rebase NAME --bot bots/MERGED --onto bots/LIVE [--live-src H] [--why TEXT] [--by S]')
    with Locked() as q:
        hit = [e for e in q if e['name'] == name and e['status'] == 'ready']
        if not hit:
            sys.exit('%s is not a ready entry' % name)
        e = hit[0]
        if not rebasable(e):
            sys.exit('%s was queued without its base\'s source hash: rebuild it on the live build instead' % name)
        e.setdefault('rebased_from', dict(bot=e['bot'], base=e['base'], src=e['src'], lab=e['gate']['lab'],
                                          base_src=e.get('base_src'), base_lab=e.get('base_lab')))
        src, lab = src_hash(os.path.join(REPO, bot)), lab_hash(os.path.join(REPO, bot))
        e['rebases'] = e.get('rebases', []) + [dict(bot=bot, onto=onto, live_src=one('--live-src'), src=src, lab=lab, at=utc(),
                                                    by=one('--by'), why=one('--why'))]
        e.update(bot=bot, base=onto, src=src, lab=lab)
    print('rebased %s onto %s: %s (src %s / %s), from %s on %s' % (name, onto, bot, src, lab, e['rebased_from']['bot'], e['rebased_from']['base']))


def live_cmd(a):
    if '--set' in a:
        bot, ver = opts(a, '--set')[0], (opts(a, '--version') or [''])[0]
        if not (os.path.isdir(os.path.join(REPO, bot)) and re.match(r'^v\d+$', ver)):
            sys.exit('live --set bots/DIR --version vNNN --why TEXT')
        set_live(bot, ver, (opts(a, '--by') or ['?'])[0], (opts(a, '--why') or [''])[0])
    print(json.dumps(live(), indent=1) if live() else 'live build not recorded: relqueue.py live --set bots/DIR --version vNNN --why TEXT')


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ('add', 'next', 'list', 'done', 'drop', 'live', 'rebase'):
        sys.exit(__doc__)
    if a[0] == 'add' and len(a) > 1:
        add(a[1], a[2:])
    elif a[0] == 'next':
        nxt(a)
    elif a[0] == 'live':
        live_cmd(a[1:])
    elif a[0] == 'rebase' and len(a) > 1:
        rebase(a[1], a[2:])
    elif a[0] == 'list':
        try:
            print(open(QMD).read())
        except OSError:
            print('queue empty')
    elif a[0] in ('done', 'drop') and len(a) > 1:
        mark(a[1], a[2:], 'done' if a[0] == 'done' else 'dropped')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
