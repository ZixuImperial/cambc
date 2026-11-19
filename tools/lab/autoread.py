"""autoread.py - the pre-registered live read runs itself when a release's live sets finish (cambc-71, 27 Oct).

Measured on v241 (27 Oct): the sets finished downloading at 13:09/13:30 and the verdict was posted at 13:35, after two
readers ran their checks by hand; earlier releases waited up to an hour for a session to notice. This runs the
registered checks the moment both sets are in, and posts the verdict. It never submits: the build session reads the
verdict (its background call exits) and acts.

  autoread.py register NAME --new PFX --base PFX --check 'CMD' [--check 'CMD'...] [--by SESSION] [--prereg FILE] [--family F]
      Before any game: freezes the check commands and the sha256 of every script they run (plus the local modules
      those import). A set that already has games is noted as "registered after data". Records the family (live layout)
      the checks pair: lean:L1 when a check runs livecheck.py, which refuses another --family; relqueue.py add takes it
      from here (itfast3 T7: pznofast was queued as s2 against lean:L1 checks, LR:2745). With --reuse, the release
      ahead's family must be the same.
  autoread.py run NAME [--max-hours H] [--no-post]
      Run as a background Bash call right after the submit and release_sets.sh. Waits for PFX_T and PFX_P
      (/data/zw4424/plat) to say DONE: replays and summaries, as checks read statistics too (27 Oct: started at REPLAYS IN,
      v247n's check 2 read 16 of 50 games and said NEEDS REVIEW). If a set is FINISHED but nobody downloads it (no .dl.log
      change for 10 min), or its downloader died after REPLAYS IN, it downloads it (diag.sh --dl, through platlock). With no
      DONE 45 min after REPLAYS IN it goes on, and the verdict's sets line says so. Then decset.sh, setd_rows.py, and each
      check (nice, 40 min cap). While it waits (a look every 15 s) it decodes ahead, one decset.sh at a time: the BASE sets
      that say DONE (and their rows), then the NEW sets' replays as they land (itfast2, 28 Oct: the verdict came ~2 min
      after the summaries). The verdict still waits for DONE and prints nothing earlier.
  autoread.py show NAME
  autoread.py dry NAME [--on NEW,BASE]
      Runs every registered check exactly as registered, with NAME's prefixes swapped for sets that already played
      (default: the last release with a verdict), and records whether each printed a DECISION line
      (reports/state/autoread_dry/NAME.json and NAME.checkN.txt). Posts nothing. relqueue.py add needs it.
  autoread.py prereg NAME --card ID --new PFX --base PFX [--reuse PFX] [--term T...] [--check CMD...]
                     [--bot bots/DIR --base-bot bots/DIR] [--by SESSION] [--out FILE]
      The standard live prereg (owner-prompts section 7): writes it (reports/<card>_<NAME>_live_prereg_MMDD.md), registers
      livecheck.py sguard (S guard; the card's terms paired per tier) and livecheck.py faults (faults and RUN_FAIL), plus
      any --check, then runs dry. Terms come from --term, else from the card's hypothesis predictions.
      --reuse PFX (ADR 0006 base reuse, owner 28 Oct): PFX is a half played on the base build: the NEW half of the
      release ahead (another registration's --new), or (itfastq, 28 Oct) the BASE half of a release on the base build
      that was reverted (another registration's --base; autoship.py checks which build it was played on); --base PFX with such a tag means the same, with NEWPFX's 'n' turned to 'b' as the fallback tag. autoship.py makes the BASE sets aliases of PFX's when PFX finished under 2 h before the submit and drift.py's
      2-group check finds at least 70% byte-identical games; otherwise it plays a fresh BASE half under --base as usual,
      so the registration holds either way. dry checks the reuse tag (reuse_problems) and fails on a bad one.
      The family is lean:L1 (livecheck.py's layout); relqueue.py add takes it from the registration.
  autoread.py prereg NAME --background --card ID [--new PFX] [--bot bots/DIR [--base-bot bots/DIR]] [--by SESSION]
                     [--out FILE] [--force]
      Owner ruling LR:2824 (28 Oct 17:19:57 UTC): local tests decide KEEP, and each live version gets a short NEW-only
      background set on lean:L1 (PFX_T top 5, PFX_P near Elo; PFX defaults to rvNNN, the version's rv<N> set) as gamerev
      data. Writes the background template (reports/<card>_<NAME>_live_prereg_MMDD.md) and a registration with
      background true and no check, so nothing it registers can decide: run prints NO VERDICT (background) and exits 5,
      dry records nothing. autoship.py reverts only a broken build (faults or resignations of ours in the version's
      games, a near-tier collapse below the F(n) floor). Refuses --check, --term and --reuse; --base is ignored.
Each check must print `DECISION (pre-registered): ...`. Combined: REVERT if any check says REVERT; KEEP if all say
KEEP; otherwise NEEDS REVIEW (a check failed, printed no DECISION, or a frozen script changed after registration).
Writes reports/state/verdicts/NAME.md (and NAME.checkN.txt with each check's full output) and, unless --no-post,
appends a stamped entry to reports/live_results.md. The verdict also shows the release queue's next candidate
(relqueue.py next). Exit status: 0 KEEP, 3 REVERT, 4 NEEDS REVIEW, 2 timeout, 5 NO VERDICT (a background
registration, or one with no check: nothing was run, written or posted)."""
import hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timezone

REPO = '/homes/zw4424/cambc'
PLAT = '/data/zw4424/plat'
MF = '/data/zw4424/mf'
REPORTS = os.environ.get('AUTOREAD_REPORTS') or '/homes/zw4424/condor-work/reports'      # override for tests
SPECS, VERD = REPORTS + '/state/autoread', REPORTS + '/state/verdicts'
DRY = SPECS + '_dry'
BOARD = os.environ.get('BOARD_STATE') or REPORTS + '/state'
LIVECHECK = '/data/zw4424/mf/py/livecheck.py'
CELL_TERMS = {'score': 'S', 's': 'S', 'late': 'LD', 'ld': 'LD', 'tc250': 'TC250', 'tc1000': 'TC1000', 'd1000': 'D1000',
              'lk': 'LK', 'len': 'LEN', 'eg': 'EG', 'kl': 'KL'}      # ledger term -> livecheck.py cell term
LR = REPORTS + '/live_results.md'
DL_IDLE_MIN, SUM_WAIT_MIN, CHECK_SECS = 10, 45, 2400
POLL_S = 15                     # a look at the sets (itfast2, 28 Oct: was 60 s)


def utc(fmt='%d %b %H:%M'):
    return datetime.now(timezone.utc).strftime(fmt)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def scripts(cmd):
    """Files a check runs: script paths in the command, plus same-directory modules they import (recursively)."""
    todo = [t for t in cmd.split() if re.search(r'\.(py|sh)$', t) and os.path.isfile(t)]
    seen = set()
    while todo:
        p = os.path.realpath(todo.pop())
        if p in seen:
            continue
        seen.add(p)
        if p.endswith('.py'):
            d = os.path.dirname(p)
            for mod in re.findall(r'^\s*(?:from\s+(\w+)\s+import|import\s+([\w, ]+))', open(p, errors='replace').read(), re.M):
                for m in re.split(r'[, ]+', mod[0] or mod[1]):
                    if m and os.path.isfile('%s/%s.py' % (d, m)):
                        todo.append('%s/%s.py' % (d, m))
    return sorted(seen)


def sets(pfx):
    return [pfx + '_T', pfx + '_P']


LIVECHECK_FAMILY = 'lean:L1'    # livecheck.py pairs lean:L1 cells only (its V4)


def checks_family(spec):
    """The layout a registration's checks pair: its family, else lean:L1 if a check runs livecheck.py, else ''."""
    return spec.get('family') or (LIVECHECK_FAMILY if any('livecheck.py' in c.get('cmd', '') for c in spec.get('checks', [])) else '')


def grep(path, pat):
    try:
        return [l.rstrip('\n') for l in open(path, errors='replace') if re.match(pat, l)]
    except OSError:
        return []


def reuse_of(spec, halves=('new',)):
    """Names of the other registrations whose NEW half (or, with halves=('new', 'base'), NEW or BASE half) is spec's reuse
    tag. A BASE half counts for reuse (itfastq, 28 Oct): the BASE sets of a release that was reverted were played on the
    build that is live again; autoship.py checks which build a half was played on before it reuses it."""
    out = []
    for f in sorted(os.listdir(SPECS)) if os.path.isdir(SPECS) else []:
        try:
            sp = json.load(open('%s/%s' % (SPECS, f))) if f.endswith('.json') else {}
        except ValueError:
            continue
        if any(sp.get(h) == spec.get('reuse') for h in halves) and sp.get('name') != spec.get('name'):
            out.append(sp['name'])
    return out


def reuse_desc(spec):
    """'the NEW half of X, the BASE half of Y' for spec's reuse tag."""
    return ', '.join('the %s half of %s' % (h.upper(), r) for h in ('new', 'base')
                     for r in reuse_of(spec, (h,))) or 'no registration'



def reuse_problems(spec):
    """[problems] with spec's --reuse tag: it must be the NEW or BASE half of another registration (a half played on the
    base build: the NEW half of its KEEP, or the BASE half of a release on it that was reverted), not this one's NEW or
    BASE, and on the same lean layout (every prereg is lean:L1). Which build the half was played on, and its age, are
    autoship.py's checks at the submit."""
    k = spec.get('reuse')
    if not k:
        return []
    p = []
    if k in (spec.get('new'), spec.get('base')):
        p.append('the reuse tag must differ from --new and --base (the BASE sets become aliases of it)')
    if not reuse_of(spec, ('new', 'base')):
        p.append('%s is not the --new or --base of any registration: reuse only a half played on the base build' % k)
    if any(os.path.exists('%s/%s/matches.txt' % (PLAT, s)) for s in sets(spec.get('base', ''))):
        p.append('base sets %s already played: nothing to reuse' % spec.get('base'))
    return p


def register(name, a):
    opt = lambda k: [a[i + 1] for i, x in enumerate(a[:-1]) if x == k]
    new, base, checks = (opt('--new') or [''])[0], (opt('--base') or [''])[0], opt('--check')
    if not (new and base and checks):
        sys.exit('register NAME --new PFX --base PFX --check CMD [--check CMD...] [--by SESSION] [--prereg FILE]')
    os.makedirs(SPECS, exist_ok=True)
    f = '%s/%s.json' % (SPECS, name)
    if os.path.exists(f) and '--force' not in a:
        sys.exit('%s exists: a registration is frozen (--force only before any game)' % f)
    played = [s for s in sets(new) if os.path.exists('%s/%s/matches.txt' % (PLAT, s)) or grep('%s/%s.log' % (PLAT, s), r'(DONE|FINISHED)')]
    spec = dict(name=name, new=new, base=base, by=(opt('--by') or [''])[0], prereg=(opt('--prereg') or [''])[0],
                **({'reuse': opt('--reuse')[0]} if opt('--reuse') else {}),
                registered=utc('%Y-%m-%d %H:%M:%S UTC'), after_data=played,
                checks=[dict(cmd=c, frozen={p: sha(p) for p in scripts(c)}) for c in checks])
    fam, cf = (opt('--family') or [''])[0], checks_family(dict(checks=[dict(cmd=c) for c in checks]))
    if fam and cf and fam != cf:
        sys.exit('register %s refused: --family %s, but livecheck.py pairs %s cells only (an entry on %s ends NEEDS REVIEW, LR:2745)'
                 % (name, fam, cf, fam))
    if fam or cf:
        spec['family'] = fam or cf
    for r in reuse_of(spec, ('new', 'base')) if spec.get('reuse') else []:
        try:
            rf = checks_family(json.load(open('%s/%s.json' % (SPECS, r))))
        except (OSError, ValueError):
            continue
        if rf and spec.get('family') and rf != spec['family']:
            sys.exit('register %s refused: --reuse %s: %s was read on %s, this registration on %s; a reuse needs the same layout'
                     % (name, spec['reuse'], r, rf, spec['family']))
    if not spec.get('reuse') and reuse_of(dict(name=name, reuse=base)):
        sys.exit('register %s refused: --base %s is the NEW half of %s; reuse it with --reuse %s and a fresh --base tag, so that '
                 'autoship.py runs the drift check (ADR 0006)' % (name, base, ', '.join(reuse_of(dict(name=name, reuse=base))), base))
    bad = reuse_problems(spec)
    if bad:
        sys.exit('register %s refused: --reuse %s: %s' % (name, spec['reuse'], '; '.join(bad)))
    json.dump(spec, open(f, 'w'), indent=1)
    print('registered %s: %d check(s), %d frozen file(s), family %s%s -> %s' % (name, len(checks), sum(len(c['frozen']) for c in spec['checks']),
          spec.get('family') or 'unknown (relqueue.py add needs --family)',
          ('; WARNING: registered after data in ' + ', '.join(played)) if played else '', f))


def downloader(d):
    """True while a diag.sh process works on set dir d (release_sets.sh and diag.sh --dl both pass the dir as an argument)."""
    for p in os.listdir('/proc'):
        try:
            a = open('/proc/%s/cmdline' % p, 'rb').read().decode(errors='replace').split('\0') if p.isdigit() else []
        except OSError:
            continue
        if d in a and any(x.endswith('diag.sh') for x in a):
            return True
    return False


def fetch(s, why):
    print('%s UTC %s: %s; downloading' % (utc('%H:%M'), s, why), flush=True)
    return subprocess.Popen('nice -n 10 sh tools/lab/diag.sh --dl %s/%s --zips >> %s/%s.dl.log 2>&1' % (PLAT, s, PLAT, s),
                            shell=True, cwd=REPO)


def set_status(s, started, seen):
    """One look at set s: the line that says it is in, or None while it is still coming in."""
    log, dl = '%s/%s.log' % (PLAT, s), '%s/%s.dl.log' % (PLAT, s)
    done = grep(log, r'DONE') or grep(dl, r'DONE')
    if done:
        return done[-1]
    part = grep(log, r'REPLAYS IN') or grep(dl, r'REPLAYS IN')
    if part:                                    # replays in, summaries still coming (diag.sh fetches replays first)
        mins = (time.time() - seen.setdefault(s, time.time())) / 60
        ended = s in started and started[s].poll() is not None
        if ended or mins >= SUM_WAIT_MIN:       # go on with what is in; the verdict's sets line says so
            return '%s; no DONE after %d min%s' % (part[-1], mins, ' (its download ended)' if ended else '')
        if s not in started and not downloader('%s/%s' % (PLAT, s)):
            started[s] = fetch(s, 'its downloader died after the replays')
    elif grep(log, r'FINISHED') and s not in started:
        idle = (time.time() - os.path.getmtime(dl)) / 60 if os.path.exists(dl) else 1e9
        if idle >= DL_IDLE_MIN:      # nobody is downloading it: fetch it (idempotent, skips complete files)
            started[s] = fetch(s, 'FINISHED but not downloaded')
    return None


class Ahead:
    """Decoding ahead while the NEW sets play (itfast2, 28 Oct): each BASE set that says DONE once (decset.sh, and
    setd_rows.py if it has no rows), then a NEW set's replays whenever more have landed. One decset.sh at a time (two on
    one set share its temp dirs); decset.sh skips decoded games, so the end-of-set decode only does what is left."""
    def __init__(self, spec):
        self.base = [s for s in sets(spec['base']) if grep('%s/%s.log' % (PLAT, s), r'DONE') or grep('%s/%s.dl.log' % (PLAT, s), r'DONE')]
        self.new, self.zips, self.p = sets(spec['new']), {}, None

    def step(self):
        if self.p is not None and self.p.poll() is None:
            return
        self.p, cmd = None, None
        dec = 'nice -n 10 sh py/decset.sh %s/%s > /dev/null 2>&1'
        if self.base:
            s = self.base.pop(0)
            cmd = dec % (PLAT, s)
            if not os.path.exists('%s/day2/rows_%s.json' % (MF, s)):
                cmd += '; nice -n 10 python3 -I py/setd_rows.py %s > /dev/null 2>&1' % s
        for s in ([] if cmd else self.new):
            d = '%s/%s' % (PLAT, s)
            n = len([f for f in os.listdir(d) if f.endswith('.zip')]) if os.path.isdir(d) else 0
            if n > self.zips.get(s, 0):
                self.zips[s], cmd = n, dec % (PLAT, s)
                break
        if cmd:
            self.p = subprocess.Popen(cmd, shell=True, cwd=MF)

    def finish(self):
        if self.p is not None:
            self.p.wait()


def wait_sets(spec, max_h):
    t0, started, seen, ahead = time.time(), {}, {}, Ahead(spec)
    while True:
        status = {s: set_status(s, started, seen) for s in sets(spec['new'])}
        if all(status.values()):
            ahead.finish()
            return status
        if time.time() - t0 > max_h * 3600:
            ahead.finish()
            return None
        ahead.step()
        time.sleep(POLL_S)


def run(name, a):
    spec = json.load(open('%s/%s.json' % (SPECS, name)))
    if spec.get('background') or not spec.get('checks'):     # owner ruling LR:2824: background data decides nothing
        print('NO VERDICT (background): %s is a background registration (owner ruling LR:2824): its set %s is gamerev data '
              'and decides nothing; no check ran, nothing was written or posted.' % (name, spec.get('new')) if spec.get('background')
              else 'NO VERDICT: %s registers no check; nothing was run, written or posted.' % name)
        sys.exit(5)
    max_h = float(a[a.index('--max-hours') + 1]) if '--max-hours' in a else 6
    os.makedirs(VERD, exist_ok=True)
    status = wait_sets(spec, max_h)
    if status is None:
        open('%s/%s.md' % (VERD, name), 'w').write('# %s: TIMEOUT after %.1f h (sets not DONE), %s UTC\n' % (name, max_h, utc()))
        print('TIMEOUT')
        sys.exit(2)
    t_in = utc('%H:%M:%S')
    for s in sets(spec['new']) + sets(spec['base']):
        subprocess.run('nice -n 10 sh py/decset.sh %s/%s > /dev/null 2>&1' % (PLAT, s), shell=True, cwd=MF)
        if not os.path.exists('%s/day2/rows_%s.json' % (MF, s)) or s in sets(spec['new']):
            subprocess.run(['nice', '-n', '10', 'python3', '-I', 'py/setd_rows.py', s], cwd=MF, capture_output=True)
    raw = {}
    for s in sets(spec['new']) + sets(spec['base']):
        try:
            res = [l.split()[3] for l in open('%s/%s/matches.txt' % (PLAT, s)) if len(l.split()) >= 4]
            raw[s] = '%d-%d' % (res.count('win'), res.count('loss'))
        except OSError:
            raw[s] = 'missing'
    lines, decs, review = [], [], []
    for i, c in enumerate(spec['checks']):
        changed = [p for p, h in c['frozen'].items() if not os.path.exists(p) or sha(p) != h]
        if changed:
            review.append('check %d: frozen file changed after registration: %s' % (i + 1, ', '.join(changed)))
        t = time.time()
        try:
            r = subprocess.run('nice -n 10 ' + c['cmd'], shell=True, cwd=REPO, capture_output=True, text=True, timeout=CHECK_SECS)
            out, rc = r.stdout + ('\n[stderr]\n' + r.stderr if r.stderr.strip() else ''), r.returncode
        except subprocess.TimeoutExpired:
            out, rc = '(timed out after %d s)' % CHECK_SECS, -1
        outf = '%s/%s.check%d.txt' % (VERD, name, i + 1)
        open(outf, 'w').write('$ %s\n%s' % (c['cmd'], out))
        d = re.findall(r'DECISION \(pre-registered\):\s*(.+)', out)
        dec = d[-1].strip() if d else None
        if rc != 0 or not dec:
            review.append('check %d: %s' % (i + 1, 'exit %d' % rc if rc != 0 else 'printed no DECISION line'))
        decs.append(dec)
        lines.append('check %d (%.0f s, exit %d): %s\n    %s\n    output: %s' % (i + 1, time.time() - t, rc, dec or '-', c['cmd'], outf))
    if spec.get('after_data'):
        review.append('registered after data in ' + ', '.join(spec['after_data']))
    kinds = {('REVERT' if d.startswith('REVERT') else 'KEEP' if d.startswith('KEEP') else 'OTHER') for d in decs if d}
    if 'REVERT' in kinds:
        final = 'REVERT' + (' (checks disagree)' if 'KEEP' in kinds else '')
    elif review or kinds != {'KEEP'}:
        final = 'NEEDS REVIEW'
    else:
        final = 'KEEP'
    stamp = utc('%Y-%m-%d %H:%M:%S UTC')
    md = ['# autoread %s: %s' % (name, final), '',
          '%s (sets in at %s UTC). New %s vs base %s; registered %s by %s%s.' % (
              stamp, t_in, spec['new'], spec['base'], spec['registered'], spec['by'] or '?',
              (', prereg ' + spec['prereg']) if spec['prereg'] else ''),
          '', 'raw: ' + ', '.join('%s %s' % kv for kv in raw.items()),
          'sets: ' + '; '.join('%s: %s' % kv for kv in status.items()), ''] + lines
    if review:
        md += ['', 'review:'] + ['  - ' + x for x in review]
    md += ['', 'autoread never submits: the build session acts on this (resubmit the base on REVERT).']
    try:                                        # the next candidate, so the live slot never waits for one
        r = subprocess.run([sys.executable, '-I', REPO + '/tools/lab/relqueue.py', 'next'], capture_output=True, text=True, timeout=300)
        md += ['', '## Release queue: next', '', '```', r.stdout.strip(), '```']
    except Exception as ex:
        md += ['', 'release queue: %r' % ex]
    vf = '%s/%s.md' % (VERD, name)
    open(vf, 'w').write('\n'.join(md) + '\n')
    print('\n'.join(md))
    if '--no-post' not in a:
        entry = '- %s **autoread %s: %s** (tools/lab/autoread.py, pre-registered %s by %s). %s vs base %s raw %s. %s%s Verdict file: %s\n' % (
            utc(), name, final, spec['registered'][:16], spec['by'] or '?', spec['new'],
            spec['base'], ', '.join('%s %s' % kv for kv in raw.items()),
            ' '.join('check %d: %s.' % (i + 1, d or '-') for i, d in enumerate(decs)),
            (' Review: ' + '; '.join(review) + '.') if review else '', vf)
        with open(LR, 'a') as f:
            f.write(entry)
    sys.exit(0 if final == 'KEEP' else 3 if final.startswith('REVERT') else 4)


def last_release(skip):
    """(new, base) of the newest registration other than skip with a verdict and all four sets in (matches.txt)."""
    best = None
    for f in os.listdir(SPECS) if os.path.isdir(SPECS) else []:
        if not f.endswith('.json') or f[:-5] == skip:
            continue
        try:
            sp = json.load(open('%s/%s' % (SPECS, f)))
        except ValueError:
            continue
        if os.path.exists('%s/%s.md' % (VERD, sp['name'])) and all(
                os.path.exists('%s/%s/matches.txt' % (PLAT, x)) for x in sets(sp['new']) + sets(sp['base'])):
            if best is None or sp['registered'] > best['registered']:
                best = sp
    return (best['new'], best['base']) if best else None


def swap(cmd, spec, on):
    """cmd with the registration's NEW and BASE prefixes (whole arguments only) replaced by on's."""
    to = {spec['new']: on[0], spec['base']: on[1]}
    pat = r'(?<![\w/.-])(%s)(?![\w/.-])' % '|'.join(re.escape(x) for x in sorted(to, key=len, reverse=True))
    return re.sub(pat, lambda m: to[m.group(1)], cmd)       # one pass: a swapped-in prefix is never swapped again


def dry(name, a):
    spec = json.load(open('%s/%s.json' % (SPECS, name)))
    if spec.get('background'):              # owner ruling LR:2824: no check registered, so no dry record
        print('NO VERDICT (background): %s registers no check (owner ruling LR:2824); nothing to dry-run, no dry record '
              'written.' % name)
        return
    on = a[a.index('--on') + 1].split(',') if '--on' in a else last_release(name)
    if not on or len(on) != 2:
        sys.exit('dry: no earlier release with a verdict and its sets in; give --on NEW,BASE')
    os.makedirs(DRY, exist_ok=True)
    out = dict(name=name, registered=spec['registered'], on=list(on), at=utc('%Y-%m-%d %H:%M:%S UTC'), checks=[])
    for i, c in enumerate(spec['checks']):
        cmd, t = swap(c['cmd'], spec, on), time.time()
        changed = [p for p, h in c['frozen'].items() if not os.path.exists(p) or sha(p) != h]
        try:
            r = subprocess.run('nice -n 10 ' + cmd, shell=True, cwd=REPO, capture_output=True, text=True, timeout=CHECK_SECS)
            txt, rc = r.stdout + ('\n[stderr]\n' + r.stderr if r.stderr.strip() else ''), r.returncode
        except subprocess.TimeoutExpired:
            txt, rc = '(timed out after %d s)' % CHECK_SECS, -1
        outf = '%s/%s.check%d.txt' % (DRY, name, i + 1)
        open(outf, 'w').write('$ %s\n%s' % (cmd, txt))
        d = re.findall(r'DECISION \(pre-registered\):\s*(.+)', txt)
        out['checks'].append(dict(cmd=c['cmd'], ran=cmd, rc=rc, decision=d[-1].strip() if d else None, out=outf,
                                  secs=round(time.time() - t), frozen_changed=changed))
    rl = []
    if spec.get('reuse'):
        out['reuse'] = dict(tag=spec['reuse'], problems=reuse_problems(spec))
        rl = ['  base reuse: --reuse %s %s' % (spec['reuse'], 'REFUSED: ' + '; '.join(out['reuse']['problems']) if out['reuse']['problems']
                                             else 'ok (%s)' % reuse_desc(spec))]
    tmp = '%s/%s.json.tmp%d' % (DRY, name, os.getpid())
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, '%s/%s.json' % (DRY, name))
    ok = all(c['decision'] and c['rc'] in (0, 3, 4) and not c['frozen_changed'] for c in out['checks']) and not (out.get('reuse') or {}).get('problems')
    L = ['dry run of %s on %s vs %s (%s): %s' % (name, on[0], on[1], out['at'], 'every check printed a DECISION line' if ok else 'FAILED')]
    for i, c in enumerate(out['checks']):
        L.append('  check %d (%d s, exit %s): %s\n    $ %s\n    output: %s%s' % (
            i + 1, c['secs'], c['rc'], c['decision'] or 'NO DECISION LINE', c['ran'], c['out'],
            ('\n    frozen file changed: ' + ', '.join(c['frozen_changed'])) if c['frozen_changed'] else ''))
    L += rl
    print('\n'.join(L))
    if spec.get('prereg') and os.path.exists(spec['prereg']):
        with open(spec['prereg'], 'a') as f:
            f.write('\n## Dry run (autoread.py dry, %s; not a decision)\n\n```\n%s\n```\n' % (out['at'], '\n'.join(L)))
    sys.exit(0 if ok else 1)


def card_terms(cid):
    """(card, [ledger prediction lines (term, value, hw)]) of board card cid, from its hypothesis card."""
    try:
        card = next(c for c in json.load(open(BOARD + '/board.json'))['cards'] if c.get('id') == cid)
    except (OSError, ValueError, KeyError, StopIteration):
        sys.exit('prereg: %s is not a board card' % cid)
    hypos = set(([card['hypo']] if card.get('hypo') else []) + ((card.get('links') or {}).get('hypo') or []))
    card['hypo'] = ', '.join(sorted(hypos)) or None
    preds = []
    try:
        for l in open(BOARD + '/hypotheses/ledger.tsv'):
            q = l.rstrip('\n').split('\t')
            if len(q) >= 7 and q[1] in hypos and q[2] == 'pred':
                preds.append((q[4], q[5], q[6]))
    except OSError:
        pass
    return card, preds


def prereg(name, a):
    opt = lambda k: [a[i + 1] for i, x in enumerate(a[:-1]) if x == k]
    one = lambda k: (opt(k) or [''])[0]
    cid, new, base, reuse = one('--card'), one('--new'), one('--base'), one('--reuse')
    if '--background' in a:
        # owner ruling LR:2824 (28 Oct 17:19:57 UTC): local tests decided KEEP before the submit; the version's short NEW-only
        # set on lean:L1 is gamerev data. The registration holds no check, so run and dry can yield no verdict.
        pfx = new or 'rvNNN'
        if not cid:
            sys.exit('prereg NAME --background --card ID [--new PFX] [--bot bots/DIR [--base-bot bots/DIR]] [--by S] [--out FILE] [--force]')
        if not (re.match(r'^[\w.-]+$', pfx) and re.match(r'^[\w.-]+$', name)):
            sys.exit('prereg %s --background refused: NAME and PFX take letters, digits, _ . - only' % name)
        held = [k for k in ('--check', '--term', '--reuse') if opt(k)]
        if held:
            sys.exit('prereg %s --background refused (%s): a background set registers no check and pairs no base half '
                     '(owner ruling LR:2824); a paired read takes the standard template, without --background' % (name, ', '.join(held)))
        if base or opt('--on'):
            print('note: --base/--on ignored: a background set is NEW only and has no dry run (owner ruling LR:2824)')
        card, preds = card_terms(cid)
        bot, bbot = one('--bot'), one('--base-bot')
        ident = []
        for lab, b in (('NEW', bot), ('BASE', bbot)):
            if b:
                if not os.path.isdir(os.path.join(REPO, b, 'src')):
                    sys.exit('prereg %s --background refused: %s has no src dir' % (name, b))
                h = subprocess.run("find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12", shell=True,
                                   cwd=os.path.join(REPO, b), capture_output=True, text=True).stdout.strip()
                ident.append('- %s: %s, src %s (tourney.src_hash)' % (lab, b, h))
        if os.path.exists('%s/%s.json' % (SPECS, name)) and '--force' not in a:
            sys.exit('%s/%s.json exists: a registration is frozen' % (SPECS, name))
        stamp = utc('%Y-%m-%d %H:%M:%S UTC')
        f = one('--out') or '%s/%s_%s_live_prereg_%s.md' % (REPORTS, cid, name, utc('%m%d'))
        if os.path.exists(f):
            sys.exit('%s exists: a prereg is written once' % f)
        played = [s for s in sets(pfx) if os.path.exists('%s/%s/matches.txt' % (PLAT, s)) or grep('%s/%s.log' % (PLAT, s), r'(DONE|FINISHED)')]
        md = ['# Live prereg %s: card %s (%s), background set %s on lean:L1' % (name, cid, card.get('title', ''), pfx), '',
              'Written %s by %s with autoread.py prereg --background (the background template, owner ruling LR:2824). Before any game of %s.' % (
                  stamp, one('--by') or '?', pfx), '',
              '## Builds', ''] + (ident or ['- (not given: --bot/--base-bot; the queue entry records them)']) + [
              '', '## The rule (owner ruling LR:2824)', '',
              'This set is background data for gamerev (owner ruling LR:2824, 28 Oct 17:19:57 UTC): local tests decided KEEP before the',
              'submit. The set never decides KEEP or REVERT, and a submit never waits for it.',
              '', '## Set (lean:L1, NEW only)', '',
              '- %s_T (top 5) and %s_P (5 near-Elo peers), 1 group each on lean:L1: 10 groups, about 50 games, NEW only (no BASE half).' % (pfx, pfx),
              '- autoship.py starts it once the version is active, at least 120 s after the submit and when the quota allows:',
              '  `sh /data/zw4424/mf/py/release_sets.sh vNNN SUBMIT_TIME_UTC %s lean:L1`. The next entry may submit while it plays.' % pfx] + (
              ['- rvNNN stands for rv<N>, N the platform version this release becomes (autoship.py names the set once the version is active).']
              if pfx == 'rvNNN' else []) + [
              '', '## Broken build: the only revert', '',
              'autoship reverts only a broken build: our bot faults or resignations in games attributed to the version, or a near-tier',
              'collapse below the F(n) floor (at most F(n) wins in its n attributed near-tier games), where F(n) = the largest f with',
              'P(Bin(n, p0) <= f) < 0.001.',
              '- A game is attributed to the version when it was created and finished while the version was certainly active.',
              '- p0 and F(n) are as autoship.py computes them (`autoship.py games vNNN` prints n, the wins, p0 and F(n)).',
              '', '## Reported only', '',
              'Reported only: results by tier, margins, fuel, and gamerev losses -> cards.',
              '', '## What autoread does with it', '',
              'No check is registered: autoread.py run prints NO VERDICT (background) on it and writes no verdict; dry records nothing.']
        os.makedirs(SPECS, exist_ok=True)
        open(f, 'w').write('\n'.join(md) + '\n')
        print('wrote %s' % f)
        spec = dict(name=name, new=pfx, base='', by=one('--by'), prereg=f, registered=stamp, after_data=played, checks=[],
                    family=LIVECHECK_FAMILY, background=True)
        tmp = '%s/%s.json.tmp%d' % (SPECS, name, os.getpid())
        json.dump(spec, open(tmp, 'w'), indent=1)
        os.replace(tmp, '%s/%s.json' % (SPECS, name))
        print('registered %s: background set %s on %s, no check (owner ruling LR:2824: it decides nothing)%s -> %s/%s.json' % (
            name, pfx, LIVECHECK_FAMILY, ('; WARNING: registered after data in ' + ', '.join(played)) if played else '', SPECS, name))
        return
    if base and not reuse and new and reuse_of(dict(name=name, reuse=base)):
        # --base K, K the NEW half of the release ahead: that is base reuse; the fresh fallback half gets its own tag
        reuse, base = base, (new[:-1] + 'b' if new.endswith('n') else new + '_b')
        print('--base %s is the NEW half of %s: registering it as --reuse %s, with %s as the fresh BASE half if the reuse fails'
              % (reuse, ', '.join(reuse_of(dict(name=name, reuse=reuse))), reuse, base))
    bad = reuse_problems(dict(name=name, new=new, base=base, reuse=reuse)) if reuse else []
    if bad:
        sys.exit('prereg %s refused: --reuse %s: %s' % (name, reuse, '; '.join(bad)))
    if not (cid and new and base):
        sys.exit('prereg NAME --card ID --new PFX --base PFX [--reuse PFX] [--term T...] [--check CMD...] [--bot bots/DIR --base-bot bots/DIR] [--by S]')
    card, preds = card_terms(cid)
    terms = [CELL_TERMS.get(t.lower(), t.upper()) for t in opt('--term')] or \
        [CELL_TERMS[p[0].lower()] for p in preds if p[0].lower() in CELL_TERMS]
    bad = [t for t in terms if t not in CELL_TERMS.values()]
    if bad:
        sys.exit('prereg: livecheck.py cannot read %s (cell terms: %s); read them with your own --check' % (
            ', '.join(bad), ' '.join(sorted(set(CELL_TERMS.values())))))
    terms = [t for i, t in enumerate(terms) if t not in terms[:i] and t != 'S']
    unread = [p[0] for p in preds if p[0].lower() not in CELL_TERMS]
    checks = ['python3 -I %s sguard %s %s%s' % (LIVECHECK, new, base, (' --terms ' + ','.join(terms)) if terms else ''),
              'python3 -I %s faults %s %s' % (LIVECHECK, new, base)] + opt('--check')
    bot, bbot = one('--bot'), one('--base-bot')
    ident = []
    for lab, b in (('NEW', bot), ('BASE', bbot)):
        if b:
            h = subprocess.run("find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12", shell=True,
                               cwd=os.path.join(REPO, b), capture_output=True, text=True).stdout.strip()
            ident.append('- %s: %s, src %s (tourney.src_hash)' % (lab, b, h))
    if os.path.exists('%s/%s.json' % (SPECS, name)) and '--force' not in a:
        sys.exit('%s/%s.json exists: a registration is frozen' % (SPECS, name))
    stamp = utc('%Y-%m-%d %H:%M:%S UTC')
    f = one('--out') or '%s/%s_%s_live_prereg_%s.md' % (REPORTS, cid, name, utc('%m%d'))
    if os.path.exists(f):
        sys.exit('%s exists: a prereg is written once' % f)
    md = ['# Live prereg %s: card %s (%s), %s against %s on lean:L1' % (name, cid, card.get('title', ''), new, base), '',
          'Written %s by %s with autoread.py prereg (the standard template, owner-prompts section 7). Before any game of %s.' % (
              stamp, one('--by') or '?', new), '',
          '## Builds', ''] + (ident or ['- (not given: --bot/--base-bot; the queue entry records them)']) + [
          '', '## Question', '',
          'Does the release lose games against the build it replaces? The checks guard against harm; KEEP never means a measured gain.'] + (
          ['The card\'s predictions (hypothesis %s): %s.' % (card.get('hypo'), '; '.join('%s %s +- %s' % p for p in preds))] if preds else []) + [
          '', '## Layout and sets (ADR 0006 fresh paired base, ADR 0007 lean layout)', '',
          '- BASE half %s_T (top 5) and %s_P (near Elo), played while the base build is live, before the submit.' % (base, base)] + (
          ['- Base reuse (ADR 0006, owner 28 Oct): if %s (the freshest finished half played on the BASE build: the NEW half of' % reuse,
           '  its KEEP, or the BASE half of a release on it that was reverted) finished under 2 h before this submit and',
           '  drift.py replays 2 of its groups with at least 70%% byte-identical games, autoship.py makes %s_T/_P aliases of %s_T/_P' % (base, reuse),
           '  instead of playing them. It logs which happened. Either way the checks read %s as BASE; V3 holds for a reused half' % base,
           '  (it finished before the submit).'] if reuse else []) + [
          '- NEW half %s_T and %s_P, created at least 120 s after the submit. 10 groups, 50 games a half; layout lean:L1.' % (new, new),
          '', '## Check 1 (decides): the S guard', '',
          '`%s`' % checks[0], '',
          'Cells paired NEW against BASE by (opponent teamId, map, seat). Validity first, else NEEDS REVIEW: V1 at least 45 of 50 cells',
          'paired and decoded; V3 the BASE half finished before the submit, the NEW half began 120 s or more after it, no later submit',
          'before it finished; V4 the layout files unchanged. S = paired score; FAIL if its two-way 90% upper bound < 0. REVERT on a',
          'FAIL that survives leaving out each opponent in turn; NEEDS REVIEW if one omission removes it; else KEEP.',
          'Reported per tier (top, near) and pooled, never deciding: S, LD%s.' % ''.join(', ' + t for t in terms), '',
          '## Check 2 (can only stop a KEEP): faults and RUN_FAIL', '',
          '`%s`' % checks[1], '',
          'NEEDS REVIEW if a NEW game shows a fault of ours or our resignation (the live form of a RUN_FAIL), if under 45 NEW games',
          'have statistics, or if the halves report more than one engine version; else KEEP. Fuel exhaustions reported per tier.'] + (
          ['', '## Further checks (given with --check)', ''] + ['- `%s`' % c for c in checks[2:]] if checks[2:] else []) + (
          ['', 'Not read by these checks (the card predicts them; add a --check to decide on them): ' + ', '.join(unread)] if unread else []) + [
          '', '## How autoread combines the checks', '',
          'REVERT if any check says REVERT; KEEP if all say KEEP; otherwise NEEDS REVIEW (a check failed, printed no DECISION, or a',
          'frozen script changed after registration).', '',
          '## What each result means (owner-prompts section 7)', '',
          '- KEEP: the release stays; relqueue.py done; the next entry ships.',
          '- REVERT: the frozen base is resubmitted at once; relqueue.py done --result REVERT; the next entry built on the base ships.',
          '- NEEDS REVIEW: as REVERT, and review reads the verdict (board.py next %s "read the verdict" --by review).' % cid]
    open(f, 'w').write('\n'.join(md) + '\n')
    print('wrote %s' % f)
    reg = ['--new', new, '--base', base, '--prereg', f, '--by', one('--by'), '--family', LIVECHECK_FAMILY] + \
        [x for c in checks for x in ('--check', c)] + (['--reuse', reuse] if reuse else [])
    register(name, reg + (['--force'] if '--force' in a else []))
    dry(name, ['--on', one('--on')] if one('--on') else [])


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ('register', 'run', 'show', 'dry', 'prereg'):
        sys.exit(__doc__)
    if a[0] == 'register':
        register(a[1], a[2:])
    elif a[0] == 'run':
        run(a[1], a[2:])
    elif a[0] == 'dry':
        dry(a[1], a[2:])
    elif a[0] == 'prereg':
        prereg(a[1], a[2:])
    else:
        print(json.dumps(json.load(open('%s/%s.json' % (SPECS, a[1]))), indent=1))
        vf = '%s/%s.md' % (VERD, a[1])
        if os.path.exists(vf):
            print(open(vf).read())


if __name__ == '__main__':
    main()
