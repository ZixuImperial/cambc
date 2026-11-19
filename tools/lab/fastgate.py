"""fastgate.py - the fast-lane gate: automatic sign-off for one switch or a few constants (owner LR:2776, 28 Oct).

The owner ruled that a fast-lane entry (ADR 0010 fast lane; recipe condor-work/reports/fastlane_recipe_1028.md) needs no
per-item grill or co-sign when this gate passes; the live sets and the automatic revert decide. Slot cards keep the full
path. Every rule prints one line, `PASS rule: detail` or `FAIL rule: detail`; a rule that cannot be evaluated FAILs.

  fastgate.py check CAND_DIR BASE_DIR --screen FILE --prereg FILE [--switches 'SW=1,SW2=0'] [--family lean:L1]
                    [--items 1|2] [--smoke-out FILE] [--json]
      (--bot DIR / --base DIR are accepted in place of the two positionals.) Without --switches the switches are inferred
      as compiled: every name the bot's own sources #define whose value, in any unit, differs from the base's.
      exit 0 FASTGATE PASS, 1 FASTGATE FAIL, 2 usage.

Rules (thresholds and their evidence: condor-work/reports/fastgate_1028.md):
  size      the diff vs --base, comments and blank lines ignored: at most LIMITS['code'] changed code lines, of which at most
            LIMITS['ungated'] neither name a --switches switch nor sit inside an #if/#elif/#else that tests one; at most
            LIMITS['funcs'] changed functions (relqueue.changed_funcs, i.e. funcdiff); at most LIMITS['consts'] changed
            #define names that are not --switches; at most LIMITS['pp'] changed preprocessor lines; no deleted function or
            file, no new .cpp. --items 2 (two fast-lane changes paired in one release, owner LR:2776) doubles each limit.
  switches  as compiled (relqueue.switch_check, clang -dM -E per unit): each SW is #defined to V in every unit that sees it,
            the base does not give V, and the bot reads SW somewhere besides its own #ifndef/#define lines; at most
            LIMITS['knobs'] changed define names (switches plus constants) in all.
  header    each SW is #defined in a .h and in no .cpp; every file that reads SW is, or includes (transitively), a header that
            defines it; every unit that reads it has it defined as compiled. No #if/#elif in the bot tests a float-valued
            define (a float literal in its value, or a define built from one). CLAUDE.md: else RUN_FAIL or silently off.
  mapid     no map identity in the added lines (CLAUDE.md, ADR 0002): no string literal naming an installed map or a map
            family prefix, no map id/hash/fingerprint/name identifier, no condition that compares two map dimensions to
            literals, no added table row of MAPTABLE_NUMS or more integer literals. A heuristic over the diff, not a proof.
  wards     every ward file of the base (src files named *ward*) is in the bot with every function the base defines in it,
            each ward::NAME the base calls from another file is still called from that file, and every WARD_* define keeps
            the base's compiled value. CLAUDE.md: a build wards all game; a merge may not drop the ward modules.
  smoke     the bot builds (release) and plays SMOKE_MAPS against the base in a private project (FASTGATE_DIR/proj, nice 10):
            exit 0, both games finish, 0 crashes, 0 botFaults, no botFault or resignation event of ours. A log is kept per
            bot and base source (FASTGATE_DIR/smoke) and reused; --smoke-out FILE takes a given log if its sources match.
  screen    --screen is the screen report (recipe section 2 step 5): its last fldecide DECISION is PASS, none is FAIL, GUARD
            FAIL or NOT EXERCISED; a typed-row PASS also needs GUARD OK; every FLT3 faults line has ours=0; each fldecide
            `tourney` line names CAND = this bot's source hash (tourney.src_hash, 12 hex) and BASE = the base's. Prints its
            sha256[:16] (relqueue keeps it). Gain on all our maps (owner rulings relayed by the coordinator, 28 Oct
            ~15:45 and ~15:50): the deciding look's mean D must be > IMPROVE_MIN_D (a no-harm PASS is not enough), and the
            file must carry one line per band in BANDS (ladder 70, fresh FLG1/FLP1, gen_c, gen_i, held-out ux/gen_u),
              `band KEY: CAND NAME (lab12), BASE NAME (lab12), N maps, mean D +x [lo, hi] (95%)`
            naming this pair, with N >= the band's minimum; 'gain' bands (ladder, fresh) need mean D > BAND_GAIN_MIN_D and
            'gain'/'nonneg' bands an interval not wholly below BAND_HI_MIN (significantly negative); 'cover' bands only
            have to be there. A missing band FAILs (fllaunch/fldecide play no ladder, gen_c, gen_i or held-out maps today).
            Typed change (owner ruling LR 16:48:53, 28 Oct): when the ladder line's `identical K of N` (flbands.py) has
            K/N >= TYPED_MIN, the ladder bar is nonneg; the gain must come from the fresh band, where the change acts.
            A ladder line without the field keeps the gain bar.
  prereg    --prereg was written by autoread.py prereg (the standard live template, itfast3 section 2.3): its header
            `# Live prereg NAME: card C (...), NEW against BASE on FAMILY`, its sections and fixed rule lines unedited, check 1
            `livecheck.py sguard NEW BASE`, check 2 `livecheck.py faults NEW BASE`; FAMILY = --family (default lean:L1); its
            Builds lines, when given, name this bot's and base's source; its autoread registration (state/autoread/NAME.json,
            read only) names this prereg, the same NEW and BASE, and records that family (its 'family' field, else the family
            its checks pair, relqueue.checks_family).

Python use (relqueue.py add --lane fast): gate(bot_dir, base_dir, switches, screen, prereg, family) -> (ok, lines).
Paths may be absolute or relative to the repo. Reads bots/ only; writes only under FASTGATE_DIR (/data/USER/st/fg)."""
import ast, difflib, fcntl, hashlib, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fractions import Fraction
from importlib.machinery import SourceFileLoader

REPO = '/homes/USER/cambc'
HERE = os.path.dirname(os.path.abspath(__file__))
RQP = os.environ.get('FASTGATE_RELQUEUE') or os.path.join(HERE, 'relqueue.py')
ARP = os.environ.get('FASTGATE_AUTOREAD') or os.path.join(HERE, 'autoread.py')
CLI = os.environ.get('FASTGATE_CLI') or '/data/USER/cambc500/bin/cambc500'
SKEL = os.environ.get('FASTGATE_SKEL') or '/data/USER/work301_4.0.0'        # abl.sh's cambc 4.0.0 workspace (read only)
FGDIR = os.environ.get('FASTGATE_DIR') or '/data/USER/st/fg'
SMOKE_MAPS = [('00fragment', 'A'), ('adgato-gemcombat1', 'B')]     # a general map with the bot as A; a gold-free one
SMOKE_TIMEOUT = 600                                                  # (Prism drafted first) with the bot as B
FAMILY = 'lean:L1'
# per fast-lane item; evidence in reports/fastgate_1028.md (pznofast 5/2/3/0/22, winchan 3/0/1/1/10 measured as code/
# ungated/funcs/consts/pp; the smallest slot-sized diffs measured 27+ code lines and 4+ functions)
LIMITS = dict(code=12, ungated=4, funcs=4, consts=4, pp=40, knobs=6)
# Screen gain on all our maps (owner rulings relayed by the coordinator 28 Oct ~15:45 and ~15:50).
# TODO(experiments): fastlane_recipe_1028.md's band layout replaces these constants when it is published; until then they
# are the rulings as given. key: (label, condition, minimum maps). gain = mean D > BAND_GAIN_MIN_D and the interval not
# wholly below BAND_HI_MIN; nonneg = the interval not wholly below BAND_HI_MIN; cover = the line must be there.
IMPROVE_MIN_D = 0.0                                                   # the deciding fldecide look's mean D
BAND_GAIN_MIN_D = 0.0
BAND_HI_MIN = 0.0
# typed change (owner ruling LR 16:48:53, 28 Oct, experiments' item 6): when at least this share of the ladder band's maps
# give identical games (flbands.py `identical K of N`), the ladder bar is nonneg and the gain must come from the fresh band
TYPED_MIN = Fraction(9, 10)
BANDS = {
    'ladder': ('ladder 70', 'gain', 60),                              # the 70 published ladder maps
    'fresh': ('fresh FLG1/FLP1', 'gain', 80),                         # the screen's own row, one look
    'gen_c': ('gen_c', 'cover', 15),                                  # 15 maps
    'gen_i': ('gen_i', 'nonneg', 40),                                 # 40 maps (8 families of 5); validation only, ADR 0003
    'heldout': ('held-out ux/gen_u', 'nonneg', 30),                   # gen_ux_ 17 + gen_u; validation only, never tuned on
}
MAPTABLE_NUMS = 12                                                    # integer literals on one added line = a table row
SRC_EXT = ('.cpp', '.h', '.hpp', '.c', '.cc')
SPECS = None                                                          # state/autoread (relqueue's), set on first use

_rq = None


def rq():
    """relqueue.py, loaded once (switch_check, changed_funcs, src_hash, lab_hash, sha, checks_family, tu_defines)."""
    global _rq, SPECS
    if _rq is None:
        _rq = SourceFileLoader('relqueue_fg', RQP).load_module()
        if SPECS is None:
            SPECS = _rq.SPECS
    return _rq


def utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def absbot(p):
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(REPO, p))


def srcdir(bot):
    return os.path.join(bot, 'src') if os.path.isdir(os.path.join(bot, 'src')) else bot


def sources(bot):
    """{path relative to src: text} of the compiled sources (.cpp .h .hpp .c .cc)."""
    root, out = srcdir(bot), {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith('.') and x != 'build']
        for f in files:
            if f.endswith(SRC_EXT):
                p = os.path.join(d, f)
                out[os.path.relpath(p, root)] = open(p, encoding='utf-8', errors='replace').read()
    return out


def other_changed(bot, base):
    """Non-compiled files under src that differ (e.g. econ.cpp.orig): reported, never counted."""
    def files(b):
        r = srcdir(b)
        return {os.path.relpath(os.path.join(d, f), r): os.path.join(d, f) for d, dirs, fs in os.walk(r)
                for f in fs if not f.endswith(SRC_EXT) and '/.' not in d and '/build' not in d}
    a, b = files(bot), files(base)
    return sorted(k for k in set(a) | set(b) if k not in a or k not in b or open(a[k], 'rb').read() != open(b[k], 'rb').read())


# ---------------------------------------------------------------- source model: significant lines, kinds, #if gating

def decomment(text):
    """text with // and /* */ comments blanked (newlines kept), string and char literals left intact."""
    out, i, n, q = [], 0, len(text), None
    while i < n:
        c = text[i]
        if q:
            out.append(c)
            if c == '\\' and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == q or c == '\n':
                q = None
            i += 1
        elif c in '"\'':
            # a digit separator (1'000) is not a char literal
            if c == "'" and i and text[i - 1].isalnum() and i + 1 < n and text[i + 1].isalnum():
                out.append(c)
                i += 1
                continue
            q = c
            out.append(c)
            i += 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(''.join(ch if ch == '\n' else ' ' for ch in text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def sig_lines(text):
    """[(lineno, sig, kind)] for the significant lines: sig = the line without comments, whitespace collapsed; kind =
    'define' (#define/#undef), 'cond' (#if.. #else #endif), 'pp' (other directives) or 'code'. A directive's backslash
    continuation lines take its kind."""
    out, cont = [], None
    for k, raw in enumerate(decomment(text).split('\n'), 1):
        s = ' '.join(raw.split())
        if not s:
            cont = None
            continue
        if cont:
            kind = cont
        elif s.startswith('#'):
            m = re.match(r'#\s*(\w+)', s)
            d = m.group(1) if m else ''
            kind = 'define' if d in ('define', 'undef') else 'cond' if d in (
                'if', 'ifdef', 'ifndef', 'elif', 'else', 'endif', 'elifdef', 'elifndef') else 'pp'
            s = '#' + s[1:].lstrip()
        else:
            kind = 'code'
        cont = kind if s.endswith('\\') and kind != 'code' else None
        out.append((k, s, kind))
    return out


def gating(lines, names):
    """[bool] per sig line: inside an #if/#elif/#else chain whose condition names one of `names`, or naming one itself."""
    pat = re.compile(r'\b(%s)\b' % '|'.join(map(re.escape, names))) if names else None
    stack, out = [], []
    for k, s, kind in lines:
        if kind == 'cond':
            m = re.match(r'#\s*(\w+)\s*(.*)$', s)
            d, cond = (m.group(1), m.group(2)) if m else ('', '')
            if d in ('if', 'ifdef', 'ifndef'):
                stack.append(bool(pat and pat.search(cond)))
            elif d in ('elif', 'elifdef', 'elifndef') and stack:
                stack[-1] = stack[-1] or bool(pat and pat.search(cond))
            elif d == 'endif' and stack:
                stack.pop()
        out.append(any(stack) or bool(pat and pat.search(s)))
    return out


def define_name(s):
    m = re.match(r'#\s*(?:define|undef)\s+(\w+)', s)
    return m.group(1) if m else None


def includes(path, text, root):
    """Files under root that `#include "x"` in text resolves to (relative to the including file, then to root)."""
    out = []
    for m in re.finditer(r'^\s*#\s*include\s*"([^"]+)"', decomment(text), re.M):
        for cand in (os.path.join(os.path.dirname(path), m.group(1)), m.group(1)):
            c = os.path.normpath(cand)
            if os.path.isfile(os.path.join(root, c)):
                out.append(c)
                break
    return out


def closure(src, root):
    """{file: set of files it includes, transitively}."""
    direct = {f: includes(f, t, root) for f, t in src.items()}
    memo = {}

    def walk(f):
        if f in memo:
            return memo[f]
        memo[f] = set()
        seen, todo = set(), list(direct.get(f, []))
        while todo:
            g = todo.pop()
            if g in seen:
                continue
            seen.add(g)
            todo += direct.get(g, [])
        memo[f] = seen
        return seen
    return {f: walk(f) for f in src}


# ---------------------------------------------------------------- per-unit preprocessing (as compiled)

_tu_cache = {}


def tu_map(bot):
    """{cpp path relative to src: {name: value}} from clang -dM -E with relqueue's release flags, or None when the
    toolchain is missing or a unit fails to preprocess."""
    key = (bot, rq().src_hash(bot))
    if key in _tu_cache:
        return _tu_cache[key]
    r = rq()
    cxx = r.WASI + '/bin/clang++'
    if not (os.path.exists(cxx) and os.path.exists(r.SDK_INC + '/cambc.h')):
        _tu_cache[key] = None
        return None
    root = srcdir(bot)
    cpps = sorted(f for f in sources(bot) if f.endswith(('.cpp', '.cc', '.c')))
    cmd = [cxx, '--target=wasm32-wasip1', '--sysroot=' + r.WASI + '/share/wasi-sysroot',
           '-isystem', r.WASI + '/share/wasi-sysroot/include/wasm32-wasip1/eh/c++/v1', '-I' + r.SDK_INC,
           '-std=c++20', '-fwasm-exceptions', '-DNDEBUG', '-dM', '-E']

    def one(f):
        try:
            return subprocess.run(['nice', '-n', '10'] + cmd + [os.path.join(root, f)], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
    with ThreadPoolExecutor(8) as ex:
        runs = list(ex.map(one, cpps))
    if not cpps or any(x is None or x.returncode for x in runs):
        _tu_cache[key] = None
        return None
    out = {}
    for f, x in zip(cpps, runs):
        out[f] = {m.group(1): m.group(2).strip() for m in re.finditer(r'^#define (\w+)(?:\([^)]*\))? ?(.*)$', x.stdout, re.M)}
    _tu_cache[key] = out
    return out


FLOAT = re.compile(r'(?<![\w.])(?:(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)[fFlL]?(?![\w.])|(?<![\w.])\d+[fF](?!\w)')


def float_defines(src, tus):
    """Names whose value holds a float literal, or names one (to a fixed point), from the bot's #define lines and, as
    compiled, from each unit's macros that the bot's own sources define."""
    vals = {}
    for f, t in src.items():
        for k, s, kind in sig_lines(t):
            m = re.match(r'#\s*define\s+(\w+)(?:\([^)]*\))?\s*(.*)$', s)
            if m and kind == 'define':
                vals.setdefault(m.group(1), set()).add(m.group(2))
    own = set(vals)
    for u in (tus or {}).values():
        for n, v in u.items():
            if n in own:
                vals[n].add(v)
    fl = {n for n, vs in vals.items() if any(FLOAT.search(v) for v in vs)}
    while True:
        more = {n for n, vs in vals.items() if n not in fl and any(re.search(r'\b(%s)\b' % '|'.join(map(re.escape, fl)), v) for v in vs)} if fl else set()
        if not more:
            return fl
        fl |= more


# ---------------------------------------------------------------- the rules

def r_size(bot, base, switches, items):
    lim = {k: v * items for k, v in LIMITS.items()}
    a, b = sources(bot), sources(base)
    names = list(switches)
    code = ungated = pp = 0
    consts, where, structural = set(), {}, []
    for f in sorted(set(a) | set(b)):
        if f not in a:
            structural.append('deleted file %s' % f)
            continue
        if f not in b and f.endswith(('.cpp', '.cc', '.c')):
            structural.append('new unit %s' % f)
        la = sig_lines(a[f])
        lb = sig_lines(b.get(f, ''))
        if [s for _, s, _ in la] == [s for _, s, _ in lb]:
            continue
        ga, gb = gating(la, names), gating(lb, names)
        sm = difflib.SequenceMatcher(a=[s for _, s, _ in lb], b=[s for _, s, _ in la], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            add = [(la[j], ga[j]) for j in range(j1, j2)]
            rem = [(lb[i], gb[i]) for i in range(i1, i2)]
            ca = [g for (k, s, kind), g in add if kind == 'code']
            cr = [g for (k, s, kind), g in rem if kind == 'code']
            n = max(len(ca), len(cr))
            code += n
            ungated += sum(1 for g in ca if not g) + (sum(1 for g in cr if not g) if not ca else max(0, len(cr) - len(ca)))
            pp += max(sum(1 for (k, s, kind), g in add if kind != 'code'), sum(1 for (k, s, kind), g in rem if kind != 'code'))
            for (k, s, kind), g in add + rem:
                if kind == 'define' and define_name(s) and define_name(s) not in switches:
                    consts.add(define_name(s))
            if n:
                where[f] = where.get(f, 0) + n
    fn, decl = rq().changed_funcs(bot, base)
    fd = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'funcdiff.py'), bot, base], capture_output=True, text=True)
    if fd.returncode:
        return False, 'funcdiff failed: %s' % fd.stderr.strip()[-200:]
    structural += ['deleted function %s' % l.strip() for l in fd.stdout.splitlines() if re.search(r'\(in BASE\)\s+-\d+\s+DELETED', l)]
    oth = other_changed(bot, base)
    detail = '%d code lines (%d ungated) in %s; %d functions%s; %d new constants%s; %d preprocessor lines%s' % (
        code, ungated, ', '.join('%s %d' % kv for kv in sorted(where.items())) or 'no file', len(fn),
        ' (%s)' % ', '.join(sorted(x.split(' ', 1)[1][:40] for x in fn)) if fn else '', len(consts),
        ' (%s)' % ', '.join(sorted(consts)) if consts else '', pp,
        '; not compiled, not counted: %s' % ', '.join(oth) if oth else '')
    over = ['code %d > %d' % (code, lim['code'])] * (code > lim['code']) + ['ungated %d > %d' % (ungated, lim['ungated'])] * (ungated > lim['ungated']) \
        + ['functions %d > %d' % (len(fn), lim['funcs'])] * (len(fn) > lim['funcs']) + ['constants %d > %d' % (len(consts), lim['consts'])] * (len(consts) > lim['consts']) \
        + ['preprocessor %d > %d' % (pp, lim['pp'])] * (pp > lim['pp']) \
        + ['switches + constants %d > %d' % (len(consts) + len(switches), lim['knobs'])] * (len(consts) + len(switches) > lim['knobs']) + structural
    if not code and not consts and not pp:
        over.append('no compiled change vs base')
    lims = 'limits code %(code)d, ungated %(ungated)d, functions %(funcs)d, constants %(consts)d, preprocessor %(pp)d, switches + constants %(knobs)d' % lim
    return (not over), (detail + '; ' + lims + ('; over: ' + '; '.join(over) if over else ''))


def infer_switches(bot, base):
    """{name: value} as compiled: names the bot's own sources #define whose value set over the units differs from the
    base's (a name the bot does not define, e.g. one it dropped, is caught by size). None without the toolchain."""
    ta, tb = tu_map(bot), tu_map(base)
    if ta is None or tb is None:
        return None
    own = {define_name(s) for t in sources(bot).values() for k, s, kind in sig_lines(t) if kind == 'define'} - {None}
    va, vb = {}, {}
    for tus, v in ((ta, va), (tb, vb)):
        for u in tus.values():
            for n, x in u.items():
                if n in own:
                    v.setdefault(n, set()).add(x)
    return {n: ','.join(sorted(va[n])) for n in sorted(va) if va[n] != vb.get(n)}


MAPFAM = re.compile(r'\b(gen_[a-z0-9]+_|S2-\d|ux_|0[0-2][a-z]{3,}|adgato-)', re.I)
MAPID = re.compile(r'\b\w*(map_?(id|hash|fp|fingerprint|sig|name|key|seed)|fingerprint|per_?map)\w*\b', re.I)
DIMS = re.compile(r'(?<![\w])(?:G\.|M\.|map\.|W\.map\.)?(width|height|map_w|map_h|mapw|maph|cols|rows|w|h)\s*==\s*\d+')
_maps = None


def map_names():
    global _maps
    if _maps is None:
        try:
            _maps = {f[:-len('.map26a')].lower() for f in os.listdir(SKEL + '/maps') if f.endswith('.map26a')}
        except OSError:
            _maps = set()
    return _maps


def added_lines(bot, base):
    """[(file, lineno, sig)] of significant lines in the bot that the base does not have (per file, difflib)."""
    a, b = sources(bot), sources(base)
    out = []
    for f in sorted(a):
        la, lb = sig_lines(a[f]), sig_lines(b.get(f, ''))
        sm = difflib.SequenceMatcher(a=[s for _, s, _ in lb], b=[s for _, s, _ in la], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ('replace', 'insert'):
                out += [(f, la[j][0], la[j][1]) for j in range(j1, j2)]
    return out


def r_mapid(bot, base):
    names = map_names()
    if not names:
        return False, 'no map list in %s/maps: not evaluated' % SKEL
    hits = []
    add = added_lines(bot, base)
    for f, k, s in add:
        why = []
        for lit in re.findall(r'"((?:[^"\\]|\\.)*)"', s):
            low = lit.lower()
            if low in names or any(len(t) >= 5 and t in names for t in re.split(r'[^\w-]+', low)) or MAPFAM.search(lit):
                why.append('string "%s" names a map' % lit[:40])
        m = MAPID.search(re.sub(r'"(?:[^"\\]|\\.)*"', '""', s))
        if m:
            why.append('identifier %s' % m.group(0))
        if len(DIMS.findall(s)) >= 2:
            why.append('compares map dimensions to literals')
        if '{' in s and len(re.findall(r'(?<![\w.])-?\d+(?![\w.])', s)) >= MAPTABLE_NUMS:
            why.append('a table row of %d+ integers' % MAPTABLE_NUMS)
        if why:
            hits.append('%s:%d %s' % (f, k, ', '.join(why)))
    if hits:
        return False, 'map identity? ' + '; '.join(hits[:6]) + (' (+%d more)' % (len(hits) - 6) if len(hits) > 6 else '')
    return True, '%d added lines: no map name, map id/hash identifier, dimension fingerprint or table row (%d map names)' % (len(add), len(names))


def r_switches(bot, base, switches):
    if tu_map(bot) is None or tu_map(base) is None:
        return False, 'cannot preprocess the bot or the base (toolchain %s/bin/clang++ or a unit fails): not evaluated' % rq().WASI
    got = rq().switch_check(bot, switches)
    was = {n: v for n, w, v, u in rq().switch_check(base, switches)}
    src = sources(bot)
    bad, txt = [], []
    for n, w, v, uses in got:
        reads = 0
        for t in src.values():
            for k, s, kind in sig_lines(t):
                if re.search(r'\b%s\b' % re.escape(n), s) and not re.match(r'#\s*(define|undef|ifndef|ifdef)\s+%s\b' % re.escape(n), s):
                    reads += 1
        if v != [w]:
            bad.append('%s wanted %s, compiled %s' % (n, w, v or 'undefined'))
        elif was[n] == [w]:
            bad.append('%s=%s is already the base\'s value' % (n, w))
        elif not reads:
            bad.append('%s is defined but never read (no #if or code names it)' % n)
        txt.append('%s=%s (base %s, %d reads)' % (n, ','.join(v) or '-', ','.join(was[n]) or 'undefined', reads))
    return (not bad), '; '.join(bad or txt)


def r_header(bot, switches):
    src, root = sources(bot), srcdir(bot)
    tus = tu_map(bot)
    cl = closure(src, root)
    lines = {f: sig_lines(t) for f, t in src.items()}
    bad, txt = [], []
    if tus is None:     # the text checks still run; the as-compiled one cannot (a float #if on a live path lands here)
        bad.append('cannot preprocess the bot (a unit fails, e.g. on a float literal in an #if): the as-compiled check is not evaluated')
    for n in switches:
        defs = sorted({f for f, ls in lines.items() for k, s, kind in ls if kind == 'define' and re.match(r'#\s*define\s+%s\b' % re.escape(n), s)})
        users = sorted(f for f, ls in lines.items() if any(re.search(r'\b%s\b' % re.escape(n), s) and kind != 'define'
                                                          and not re.match(r'#\s*(ifndef|ifdef)\s+%s\b' % re.escape(n), s) for k, s, kind in ls))
        dh = [f for f in defs if f.endswith(('.h', '.hpp'))]
        dc = [f for f in defs if not f.endswith(('.h', '.hpp'))]
        if dc:
            bad.append('%s is #defined in %s (a .cpp: other units never see it)' % (n, ', '.join(dc)))
        if not dh:
            bad.append('%s is #defined in no header' % n)
        blind = [u for u in users if u not in dh and not (cl.get(u, set()) & set(dh))]
        if blind:
            bad.append('%s is read in %s, which include%s no header defining it (%s)' % (n, ', '.join(blind), 's' if len(blind) == 1 else '', ', '.join(dh) or 'none'))
        units = [c for c in (tus or {}) if c in users or cl.get(c, set()) & set(users)]
        undefined = [c for c in units if n not in tus[c]]
        if undefined:
            bad.append('%s is undefined as compiled in %s, which read%s it' % (n, ', '.join(undefined), 's' if len(undefined) == 1 else ''))
        txt.append('%s in %s, read in %d files (%d units)' % (n, ','.join(dh) or '-', len(users), len(units)))
    fl = float_defines(src, tus)
    hits = []
    for f, ls in sorted(lines.items()):
        for k, s, kind in ls:
            m = re.match(r'#\s*(if|elif)\b(.*)$', s)
            if kind == 'cond' and m:
                cond = re.sub(r'\bdefined\s*\(?\s*\w+\s*\)?', ' ', m.group(2))
                used = sorted(set(re.findall(r'\b[A-Za-z_]\w*\b', cond)) & fl) + (['a float literal'] if FLOAT.search(cond) else [])
                if used:
                    hits.append('%s:%d #%s on %s' % (f, k, m.group(1), ', '.join(used)))
    if hits:
        bad.append('#if on a float-valued define: ' + '; '.join(hits[:6]) + (' (+%d more)' % (len(hits) - 6) if len(hits) > 6 else ''))
    return (not bad), '; '.join(bad) if bad else '; '.join(txt) + '; no #if on any of %d float-valued defines' % len(fl)


def r_wards(bot, base):
    a, b = sources(bot), sources(base)
    wf = sorted(f for f in b if re.search(r'ward', os.path.basename(f), re.I))
    if not wf:
        return False, 'no ward file in the base (src/*ward*): not evaluated'
    sys.path.insert(0, HERE)
    from codeindex import index_file
    bad, nfun = [], 0
    for f in wf:
        if f not in a:
            bad.append('ward file %s is gone' % f)
            continue
        have = {(ns, name) for x, y, ns, name, sig, com in index_file(os.path.join(srcdir(bot), f))}
        for x, y, ns, name, sig, com in index_file(os.path.join(srcdir(base), f)):
            nfun += 1
            if (ns, name) not in have:
                bad.append('%s lost %s' % (f, name))
    calls = 0
    for f, t in sorted(b.items()):
        if f in wf:
            continue
        for name in sorted(set(re.findall(r'\bward::(\w+)', decomment(t)))):
            calls += 1
            if f not in a or not re.search(r'\bward::%s\b' % re.escape(name), decomment(a[f])):
                bad.append('%s no longer calls ward::%s' % (f, name))
    ta, tb = tu_map(bot), tu_map(base)
    if ta is None or tb is None:
        bad.append('cannot preprocess for the WARD_* values: not evaluated')
        sw = {}
    else:
        va, vb = {}, {}
        for tus, v in ((ta, va), (tb, vb)):
            for u in tus.values():
                for n, x in u.items():
                    if n.startswith('WARD_'):
                        v.setdefault(n, set()).add(x)
        sw = vb
        for n in sorted(vb):
            if va.get(n) != vb[n]:
                bad.append('%s compiles to %s, the base to %s' % (n, ','.join(sorted(va.get(n, ()))) or 'undefined', ','.join(sorted(vb[n]))))
    return (not bad), '; '.join(bad) if bad else '%s present with all %d base functions; %d ward:: call sites kept; %s as the base' % (
        ', '.join(wf), nfun, calls, ', '.join('%s=%s' % (n, ','.join(sorted(v))) for n, v in sorted(sw.items())) or 'no WARD_ defines')


def _copy(bot, dst):
    """Copy bot (sources only) to dst once (a built dir never moves: CMake records its path)."""
    if os.path.isdir(os.path.join(dst, 'src')):
        return
    tmp = '%s.tmp%d' % (dst, os.getpid())
    subprocess.run(['rm', '-rf', tmp])
    subprocess.run(['rsync', '-a', '--exclude', '.cambc', '--exclude', 'build', bot.rstrip('/') + '/', tmp + '/'], check=True)
    os.rename(tmp, dst)


def smoke(bot, base, log):
    """Build bot and base in FGDIR/proj and play SMOKE_MAPS; write log (header, CLI outputs, fault JSON, verdict)."""
    r = rq()
    proj = FGDIR + '/proj'
    os.makedirs(proj + '/bots', exist_ok=True)
    os.makedirs(proj + '/maps', exist_ok=True)
    L = ['FASTGATE SMOKE bot=%s src=%s lab=%s base=%s base_src=%s cli=%s at=%s' % (
        bot, r.src_hash(bot), r.lab_hash(bot), base, r.src_hash(base), CLI, utc())]
    probs = []
    with open(FGDIR + '/proj.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        subprocess.run(['rsync', '-a', SKEL + '/cambc.toml', proj + '/cambc.toml'], check=True)
        for d in ('sdk', 'cmake'):
            if os.path.isdir(os.path.join(SKEL, d)):
                subprocess.run(['rsync', '-a', os.path.join(SKEL, d) + '/', os.path.join(proj, d) + '/'], check=True)
        for m, _ in SMOKE_MAPS:
            subprocess.run(['rsync', '-a', '%s/maps/%s.map26a' % (SKEL, m), '%s/maps/' % proj], check=True)
        da = '%s/bots/%s-%s' % (proj, os.path.basename(bot), r.lab_hash(bot))
        db = '%s/bots/%s-%s' % (proj, os.path.basename(base), r.lab_hash(base))
        _copy(bot, da)
        _copy(base, db)
        na, nb = os.path.basename(da), os.path.basename(db)
        for i, (m, seat) in enumerate(SMOKE_MAPS):
            A, B = ('bots/' + na, 'bots/' + nb) if seat == 'A' else ('bots/' + nb, 'bots/' + na)
            ours = 'teamA' if seat == 'A' else 'teamB'
            st = '%s/st_%d_%d.json' % (proj, os.getpid(), i)
            cmd = ['nice', '-n', '10', CLI, 'run', A, B, '--map', 'maps/%s.map26a' % m, '--release', '--log-limit', '0',
                   '-o', '%s/rep_%d' % (proj, os.getpid()), '--statistics', st, '--json']
            L.append('$ ' + ' '.join(cmd))
            try:
                x = subprocess.run(cmd, cwd=proj, capture_output=True, text=True, timeout=SMOKE_TIMEOUT)
                out, rc = x.stdout + x.stderr, x.returncode
            except subprocess.TimeoutExpired:
                out, rc = 'timeout after %d s' % SMOKE_TIMEOUT, 'timeout'
            keep = [l for l in out.splitlines() if not re.match(r'(running|drafting): round|\[\d+/\d+\] ', l) and not l.startswith('--')]
            L += keep[-40:]
            row = [l.split() for l in out.splitlines() if re.match(r'\s*%s\s+%s\s' % (seat, re.escape(na)), l)]
            crashes = row[0][6] if row and len(row[0]) > 6 else None
            fin = re.search(r'^finished: round (\d+)', out, re.M)
            f = {}
            try:
                d = json.load(open(st))
                f['botFaults'] = ((d.get('diagnostics') or {}).get('botFaults') or {}).get(ours)
                for e in d.get('events') or []:
                    o = e.get('owner')
                    t = o if isinstance(o, str) else (o or {}).get('team')
                    if e.get('kind') in ('botFault', 'resignation', 'fuelExhausted') and t == ours and e.get('entries'):
                        f[e['kind']] = f.get(e['kind'], 0) + len(e['entries'])
            except (OSError, ValueError) as ex:
                f['stats'] = 'missing (%s)' % ex.__class__.__name__
            for p in (st,):
                if os.path.exists(p):
                    os.remove(p)
            subprocess.run(['rm', '-rf', '%s/rep_%d' % (proj, os.getpid())])
            game = 'game %d %s, bot as %s: exit %s, %s, crashes %s, %s' % (
                i + 1, m, seat, rc, 'finished r%s' % fin.group(1) if fin else 'not finished', crashes,
                json.dumps(f, sort_keys=True))
            L.append('GAME ' + game)
            if rc != 0 or not fin or crashes != '0' or f.get('botFaults') != 0 or f.get('botFault') or f.get('resignation') or 'stats' in f:
                probs.append(game)
    verdict = 'SMOKE FAIL: ' + ' | '.join(probs) if probs else 'SMOKE PASS: %d games, 0 crashes, 0 faults of ours' % len(SMOKE_MAPS)
    L.append(verdict)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    tmp = log + '.tmp%d' % os.getpid()
    open(tmp, 'w').write('\n'.join(L) + '\n')
    os.replace(tmp, log)
    return log


def read_smoke(log, bot, base):
    """(verdict line or None, why not usable)."""
    try:
        txt = open(log, errors='replace').read()
    except OSError:
        return None, 'smoke log %s not found' % log
    h = re.search(r'^FASTGATE SMOKE bot=\S+ src=(\w+) lab=\w+ base=\S+ base_src=(\w+)', txt, re.M)
    v = re.findall(r'^(SMOKE (?:PASS|FAIL).*)$', txt, re.M)
    if not h or not v:
        return None, 'smoke log %s has no FASTGATE SMOKE header or verdict' % log
    if h.group(1) != rq().src_hash(bot) or h.group(2) != rq().src_hash(base):
        return None, 'smoke log %s is of src %s on base %s, not %s on %s' % (log, h.group(1), h.group(2), rq().src_hash(bot), rq().src_hash(base))
    return v[-1], ''


def r_smoke(bot, base, smoke_out=None):
    log = smoke_out or '%s/smoke/%s_%s_on_%s.log' % (FGDIR, os.path.basename(bot), rq().src_hash(bot), rq().src_hash(base))
    v, why = read_smoke(log, bot, base)
    if v is None and smoke_out:
        return False, why
    reused = v is not None
    if v is None:
        smoke(bot, base, log)
        v, why = read_smoke(log, bot, base)
        if v is None:
            return False, why
    return v.startswith('SMOKE PASS'), '%s (%s %s)' % (v[len('SMOKE '):], 'reused' if reused else 'log', log)


def r_screen(bot, base, screen):
    if not screen or not os.path.isfile(screen) or not os.path.getsize(screen):
        return False, 'screen file %s not found or empty' % (screen or '(none)'), None
    txt = open(screen, errors='replace').read()
    sh = rq().sha(screen)[:16]
    dec = re.findall(r'^DECISION \(fast lane[^)]*\):\s*(.*)$', txt, re.M)
    main = [d for d in dec if not d.startswith('GUARD')]
    guard = [d for d in dec if d.startswith('GUARD')]
    bad = []
    if not main:
        bad.append('no fldecide DECISION line (recipe section 2 step 5: every decide_*.txt in full)')
    elif not main[-1].startswith('PASS'):
        bad.append('last decision: %s' % main[-1][:80])
    for d in dec:
        if re.match(r'(FAIL|GUARD FAIL|NOT EXERCISED|INCONCLUSIVE|REFUSED|INCOMPLETE)', d):
            bad.append('decision %s' % d[:60])
    if main and main[-1].startswith('PASS') and 'GUARD OK' in main[-1] and not any(g.startswith('GUARD OK') for g in guard):
        bad.append('a typed-row PASS without a GUARD OK decision')
    for m in re.finditer(r'^faults: FLT3 .*?\bours=(\d+)', txt, re.M):
        if m.group(1) != '0':
            bad.append('faults of ours: %s' % m.group(1))
    tl = re.findall(r'^tourney (\S+): .*?CAND (\S+) \((\w+)\), BASE (\S+) \((\w+)\)', txt, re.M)
    hb, hbase = rq().lab_hash(bot), rq().lab_hash(base)
    if not tl:
        bad.append('no fldecide tourney line naming CAND and BASE source hashes')
    for t, cn, ch, bn, bh in tl:
        if ch != hb:
            bad.append('%s screened %s src %s, this bot is src %s' % (t.rstrip(':'), cn, ch, hb))
        if bh != hbase:
            bad.append('%s ran on base %s src %s, this base is src %s' % (t.rstrip(':'), bn, bh, hbase))
    # improvement: the deciding look's point estimate (the last `look N: mean D` line before the last main DECISION)
    est = None
    if main:
        cut = txt.rfind('DECISION (fast lane', 0, txt.rfind(main[-1]) + len(main[-1]))
        looks = re.findall(r'^look (\d+): mean D ([+-]?\d+\.\d+) \[([+-]?\d+\.\d+), ([+-]?\d+\.\d+)\]', txt[:cut], re.M)
        if looks:
            est = looks[-1]
    if est is None:
        bad.append('no `look N: mean D` estimate for the deciding look')
        imp = 'no estimate'
    else:
        imp = 'look %s mean D %+.4f [%+.4f, %+.4f]' % (est[0], float(est[1]), float(est[2]), float(est[3]))
        if not float(est[1]) > IMPROVE_MIN_D:
            bad.append('no improvement: %s, point estimate not > %+.3f (a no-harm PASS is not enough)' % (imp, IMPROVE_MIN_D))
    # all-maps bands (owner ruling relayed by the coordinator 28 Oct ~15:50): one `band` line per BANDS key, naming this pair
    bl = re.findall(r'^band (\w+): CAND (\S+) \((\w+)\), BASE (\S+) \((\w+)\), (\d+) maps, mean D ([+-]?\d+\.\d+) '
                    r'\[([+-]?\d+\.\d+), ([+-]?\d+\.\d+)\] \((\d+)%\)(.*)$', txt, re.M)
    seen, hod = {}, []
    for key, cn, ch, bn, bh, n, d, lo, hi, lev, rest in bl:
        if key not in BANDS:
            bad.append('band %s is not one of %s' % (key, ', '.join(BANDS)))
            continue
        if ch != hb or bh != hbase:
            bad.append('band %s is of %s (%s) on %s (%s), not this pair' % (key, cn, ch, bn, bh))
            continue
        if key in seen:
            bad.append('band %s given twice' % key)
            continue
        seen[key] = (int(n), float(d), float(lo), float(hi))
        label, cond, nmin = BANDS[key]
        typed = ''
        idm = re.search(r', identical (\d+) of (\d+)\b', rest)
        if key == 'ladder' and idm:
            k, kn = int(idm.group(1)), int(idm.group(2))
            if kn != int(n) or k > kn:
                bad.append('band %s: identical %d of %d does not fit its %s maps' % (key, k, kn, n))
            elif Fraction(k, kn) >= TYPED_MIN:
                cond, typed = 'nonneg', ', typed: %d/%d identical >= %s, nonneg bar' % (k, kn, TYPED_MIN)
            else:
                typed = ', %d/%d identical < %s, gain bar' % (k, kn, TYPED_MIN)
        hod.append('%s %+.4f [%+.4f, %+.4f] (%s%%, %s maps%s)' % (key, float(d), float(lo), float(hi), lev, n, typed))
        if int(n) < nmin:
            bad.append('band %s (%s) has %s maps < %d' % (key, label, n, nmin))
        if cond == 'gain' and not float(d) > BAND_GAIN_MIN_D:
            bad.append('band %s (%s): mean D %s, not > %+.3f (a gain band needs a positive estimate)' % (key, label, d, BAND_GAIN_MIN_D))
        if cond in ('gain', 'nonneg') and float(hi) < BAND_HI_MIN:
            bad.append('band %s (%s) significantly negative: mean D %s [%s, %s] (%s%%)' % (key, label, d, lo, hi, lev))
    miss = [k for k in BANDS if k not in seen]
    if miss:
        bad.append('missing band%s %s for this pair (screens run on all our maps: a `band KEY: CAND .., BASE .., N maps, mean D` line each)'
                   % ('s' if len(miss) > 1 else '', ', '.join('%s (%s)' % (k, BANDS[k][0]) for k in miss)))
    detail = '%s sha256 %s: %s%s; CAND src %s; deciding look %s; bands %s' % (
        screen, sh, main[-1].split(';')[0][:80] if main else 'no decision', (', ' + guard[-1]) if guard else '', hb, imp,
        '; '.join(hod) or 'none')
    return (not bad), (detail + ('; ' + '; '.join(bad) if bad else '')), sh


# the template's fixed rule lines (autoread.py prereg, the standard live template); each must be in the prereg unedited
TEMPLATE_LINES = [
    'Does the release lose games against the build it replaces? The checks guard against harm; KEEP never means a measured gain.',
    'Cells paired NEW against BASE by (opponent teamId, map, seat). Validity first, else NEEDS REVIEW: V1 at least 45 of 50 cells',
    'paired and decoded; V3 the BASE half finished before the submit, the NEW half began 120 s or more after it, no later submit',
    'before it finished; V4 the layout files unchanged. S = paired score; FAIL if its two-way 90% upper bound < 0. REVERT on a',
    'FAIL that survives leaving out each opponent in turn; NEEDS REVIEW if one omission removes it; else KEEP.',
    'NEEDS REVIEW if a NEW game shows a fault of ours or our resignation (the live form of a RUN_FAIL), if under 45 NEW games',
    'have statistics, or if the halves report more than one engine version; else KEEP. Fuel exhaustions reported per tier.',
    'REVERT if any check says REVERT; KEEP if all say KEEP; otherwise NEEDS REVIEW (a check failed, printed no DECISION, or a',
    'frozen script changed after registration).',
    '- KEEP: the release stays; relqueue.py done; the next entry ships.',
    '- REVERT: the frozen base is resubmitted at once; relqueue.py done --result REVERT; the next entry built on the base ships.',
]
SECTIONS = ['## Builds', '## Question', '## Layout and sets (ADR 0006 fresh paired base, ADR 0007 lean layout)',
            '## Check 1 (decides): the S guard', '## Check 2 (can only stop a KEEP): faults and RUN_FAIL',
            '## How autoread combines the checks', '## What each result means (owner-prompts section 7)']


def template_strings():
    """The constant strings of autoread.py's prereg() (to check TEMPLATE_LINES against the installed template)."""
    tree = ast.parse(open(ARP).read())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'prereg')
    return {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def r_prereg(bot, base, prereg, family):
    if not prereg or not os.path.isfile(prereg):
        return False, 'prereg %s not found' % (prereg or '(none)')
    txt = open(prereg, errors='replace').read()
    L = txt.splitlines()
    m = re.match(r'^# Live prereg (\S+): card (\S+) \(.*\), (\S+) against (\S+) on (\S+)\s*$', L[0] if L else '')
    if not m:
        return False, 'first line is not the template header `# Live prereg NAME: card C (...), NEW against BASE on FAMILY`'
    name, card, new, bas, fam = m.groups()
    bad = []
    try:
        consts = template_strings()
        stale = [t for t in TEMPLATE_LINES + SECTIONS if t not in consts]
        if stale:
            bad.append('autoread.py\'s template no longer has %d of fastgate\'s fixed lines (update TEMPLATE_LINES): %s' % (len(stale), stale[0][:60]))
    except (OSError, SyntaxError, StopIteration) as ex:
        bad.append('cannot read the template in %s: %s' % (ARP, ex))
    if fam != family:
        bad.append('family %s, not %s' % (fam, family))
    if 'with autoread.py prereg (the standard template' not in txt:
        bad.append('no "with autoread.py prereg (the standard template" line')
    pos = [txt.find('\n' + s + '\n') for s in SECTIONS]
    miss = [s for s, p in zip(SECTIONS, pos) if p < 0]
    if miss:
        bad.append('missing sections: %s' % ', '.join(miss))
    elif pos != sorted(pos):
        bad.append('sections out of template order')
    edited = [t for t in TEMPLATE_LINES if t not in L]
    if edited:
        bad.append('%d template rule lines edited or missing, e.g. "%s"' % (len(edited), edited[0][:60]))
    c1 = re.search(r'^`(python3 -I \S*livecheck\.py sguard (\S+) (\S+)[^`]*)`$', txt, re.M)
    c2 = re.search(r'^`(python3 -I \S*livecheck\.py faults (\S+) (\S+))`$', txt, re.M)
    if not c1 or (c1.group(2), c1.group(3)) != (new, bas):
        bad.append('check 1 is not livecheck.py sguard %s %s' % (new, bas))
    if not c2 or (c2.group(2), c2.group(3)) != (new, bas):
        bad.append('check 2 is not livecheck.py faults %s %s' % (new, bas))
    hb, hbase = rq().lab_hash(bot), rq().lab_hash(base)
    for lab, h in (('NEW', hb), ('BASE', hbase)):
        g = re.search(r'^- %s: (\S+), src (\w+)' % lab, txt, re.M)
        if g and g.group(2) != h:
            bad.append('Builds names %s %s src %s, this %s is src %s' % (lab, g.group(1).rstrip(','), g.group(2), lab.lower(), h))
    builds = 'Builds name both sources' if re.search(r'^- NEW: ', txt, re.M) else 'Builds not given (the queue entry records them)'
    rq()
    try:
        spec = json.load(open('%s/%s.json' % (SPECS, name)))
    except (OSError, ValueError):
        spec = None
        bad.append('autoread registration %s/%s.json not found' % (SPECS, name))
    regfam = ''
    if spec:
        if not spec.get('prereg') or os.path.realpath(spec['prereg']) != os.path.realpath(prereg):
            bad.append('registration %s names prereg %s' % (name, spec.get('prereg') or 'none'))
        if (spec.get('new'), spec.get('base')) != (new, bas):
            bad.append('registration %s is %s against %s, the prereg %s against %s' % (name, spec.get('new'), spec.get('base'), new, bas))
        if c1 and (not spec.get('checks') or spec['checks'][0].get('cmd') != c1.group(1)):
            bad.append('registration %s check 1 is not the prereg\'s' % name)
        regfam = spec.get('family') or rq().checks_family(spec)
        if regfam != family:
            bad.append('registration %s records family %s (%s), not %s' % (name, regfam or 'none', 'field' if spec.get('family') else 'from its checks', family))
    detail = '%s: %s against %s on %s, card %s, registration %s family %s%s; %s' % (
        prereg, new, bas, fam, card, name, regfam or '?', '' if not spec or spec.get('family') else ' (from its checks)', builds)
    return (not bad), detail + ('; ' + '; '.join(bad) if bad else '')


def _rule(name, f, *a):
    try:
        r = f(*a)
    except Exception as ex:          # a rule that cannot be evaluated FAILs
        r = (False, 'not evaluated: %s: %s' % (ex.__class__.__name__, str(ex)[:200]))
    return r


def gate(bot_dir, base_dir, switches, screen, prereg, family=FAMILY, *, items=1, smoke_out=None, report=None):
    """(ok, lines): one 'PASS rule: detail' / 'FAIL rule: detail' line per rule, then 'FASTGATE PASS|FAIL'.
    report (a dict), if given, gets rules [{rule, ok, detail}], screen_sha, src and lab."""
    bot, base = absbot(bot_dir), absbot(base_dir)
    family = family or FAMILY
    res = []
    if not (os.path.isdir(bot) and os.path.isdir(base)):
        res.append(('input', False, 'bot %s / base %s: not a bot dir' % (bot_dir, base_dir)))
    elif items not in (1, 2):
        res.append(('input', False, 'items %s: 1, or 2 for a paired release' % items))
    else:
        if switches:
            sw = {str(k): str(v) for k, v in switches.items()}
        else:
            sw = infer_switches(bot, base)
            if report is not None:
                report['inferred_switches'] = sw
        if not sw:
            res.append(('switches', False, 'no switch given and none inferred (%s): nothing to gate on' % (
                'no compiled define differs from the base' if sw is not None else 'cannot preprocess')))
            sw = {}
        res.append(('size',) + _rule('size', r_size, bot, base, sw, items))
        if sw:
            res.append(('switches',) + _rule('switches', r_switches, bot, base, sw))
        res.append(('header',) + _rule('header', r_header, bot, sw))
        res.append(('mapid',) + _rule('mapid', r_mapid, bot, base))
        res.append(('wards',) + _rule('wards', r_wards, bot, base))
        res.append(('smoke',) + _rule('smoke', r_smoke, bot, base, smoke_out))
        try:
            ok, d, sh = r_screen(bot, base, screen)
        except Exception as ex:
            ok, d, sh = False, 'not evaluated: %s: %s' % (ex.__class__.__name__, str(ex)[:200]), None
        res.append(('screen', ok, d))
        res.append(('prereg',) + _rule('prereg', r_prereg, bot, base, prereg, family))
        if report is not None:
            report.update(screen_sha=sh, src=rq().src_hash(bot), lab=rq().lab_hash(bot))
    ok = bool(res) and all(r[1] for r in res)
    lines = ['%s %s: %s' % ('PASS' if o else 'FAIL', n, d) for n, o, d in res] + ['FASTGATE %s' % ('PASS' if ok else 'FAIL')]
    if report is not None:
        report.update(ok=ok, rules=[dict(rule=n, ok=o, detail=d) for n, o, d in res], at=utc())
    return ok, lines


def parse_switches(s):
    out = {}
    for kv in (s or '').split(','):
        kv = kv.strip()
        if not kv:
            continue
        if not re.match(r'^[A-Za-z_]\w*=\S+$', kv):
            raise ValueError(kv)
        k, v = kv.split('=', 1)
        out[k] = v
    return out


def main():
    a = sys.argv[1:]
    if not a or a[0] != 'check':
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    a = a[1:]
    flags = {'--json'}
    known = {'--bot', '--base', '--switches', '--screen', '--prereg', '--family', '--items', '--smoke-out'}
    opt, i, pos = {}, 0, []
    while i < len(a):
        if not a[i].startswith('--') and len(pos) < 2:
            pos.append(a[i])
            i += 1
        elif a[i] in flags:
            opt[a[i]] = True
            i += 1
        elif a[i] in known and i + 1 < len(a):
            opt[a[i]] = a[i + 1]
            i += 2
        else:
            print('fastgate.py check: unknown or incomplete argument %s\n%s' % (a[i], __doc__.split('\n\n')[1]), file=sys.stderr)
            sys.exit(2)
    for k, v in zip(('--bot', '--base'), pos):
        if k in opt:
            print('fastgate.py check: %s given twice (positional and flag)' % k, file=sys.stderr)
            sys.exit(2)
        opt[k] = v
    need = [k for k in ('--bot', '--base', '--screen', '--prereg') if k not in opt]
    try:
        sw = parse_switches(opt.get('--switches'))
        items = int(opt.get('--items', 1))
    except ValueError as ex:
        print('fastgate.py check: bad --switches/--items (%s); SW=V,SW2=V2' % ex, file=sys.stderr)
        sys.exit(2)
    if need or items not in (1, 2):
        print('fastgate.py check: missing %s\n%s' % (', '.join(need) or '--items 1|2', __doc__.split('\n\n')[1]), file=sys.stderr)
        sys.exit(2)
    for k in ('--bot', '--base'):
        if not os.path.isdir(absbot(opt[k])):
            print('fastgate.py check: %s %s is not a directory' % (k, opt[k]), file=sys.stderr)
            sys.exit(2)
    rep = {}
    ok, lines = gate(opt['--bot'], opt['--base'], sw, opt['--screen'], opt['--prereg'], opt.get('--family') or FAMILY,
                     items=items, smoke_out=opt.get('--smoke-out'), report=rep)
    if opt.get('--json'):
        rep['lines'] = lines
        print(json.dumps(rep, indent=1))
    else:
        print('\n'.join(lines))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
