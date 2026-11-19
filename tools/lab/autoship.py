"""autoship.py - auto-push: ships the head of the release queue, one step per tick (owner-prompts section 7, 28 Oct).

On 27 Oct m3 (v248) passed its read at 22:53 and its grill at 23:19; a restart at 23:26 stopped the session preparing
it and nothing moved until 11:26. Tabs now do the judgment before the queue (build, read, grill, prereg with dry runs:
relqueue.py add refuses an entry without them); this code does the mechanics after it, from a systemd user timer.

  autoship.py tick [--dry-run]   one step of the release in flight (below), under state/autoship.lock. --dry-run prints
                                 the step a tick would take now and changes nothing (platform reads only).
  autoship.py status             armed or not, autoship.off, the state, the head of the queue
  autoship.py arm [--reset]      install and start the timer (every 5 min); removes autoship.off. The coordinator arms
                                 it, never review or a subagent. --reset clears a state stopped by an error.
  autoship.py disarm             stop the timer; units already started (sets, autoread) run on
  autoship.py kick [--poll]      a tick in ~10 s (--poll: ~45 s), only while armed and with no autoship.off. Each unit
                                 autoship starts (base, drift, new, read) kicks when it ends; a tick kicks after a step it
                                 took, and polls while it waits for a submitted version. The 5-min timer stays the fallback.
  autoship.py trial              the pin trial (card pin, owner 28 Oct; the coordinator runs it, no set playing, phase idle):
                                 pin the live version, resubmit its frozen copy (same source), check Live stays put while
                                 the new version builds to ready, activate it, check Live switches, activate the live
                                 version again. PASS turns pin mode on. Every platform answer goes to state/pin_trial.txt.
  autoship.py pin on|off         pin mode by hand, only while no set plays (off: only between releases, and never while a
                                 newer version is building or ready: "latest" would put it live).

Steps (state/autoship.json keeps the phase, so a restart loses nothing; each tick takes at most one):
  idle       relqueue.py next --json. Only an entry with a ship gate ships; one queued before the gate waits for a hand
             ship. Base not live (the entry ahead was reverted; owner 28 Oct, LR:2780): the entry is merged onto the
             live build by diff: per file, git merge-file (the live build's frozen shipped copy, the base it was built
             on, the candidate) in MERGED/.work; the identity check (its change against its base equals the merged
             build's change against the live build), the switch check, a SMOKE_ROUNDS-round release smoke game in
             MERGED/.smoke; then MERGED/TAG is linked as bots/TAG (TAG = nova_as_ENTRY_LIVEVERSION), relqueue.py
             rebase makes it the entry's bot (base = the live build) with the identity logged, and the next tick goes on.
             A conflict or a failed check: board.py next ID "rebuild on the live build" --by the card's owner role,
             logged once, then wait with the reason. An entry queued without its base's hash: --by coordinator, wait.
             A set playing, or quota short: wait. Base sets missing: start the BASE half
             (release_sets.sh on the live version), unless base reuse (below) takes K's sets. All clear: submit (below).
  drift      base reuse on every release (ADR 0006; owner 28 Oct, it20 + itfastq). K is a half played on the live build X:
             the NEW half of X's KEEP, or (itfastq) the BASE half of a release on X that was reverted (its BASE sets, or an
             alias of a half of X; symlinks are followed); autoread.py --reuse K names one, else pick_reuse gives the
             freshest. K under NODRIFT_H old: BASE_T/_P become aliases of K_T/_P and the submit follows at once, with no
             drift check. If K finished under
             REUSE_MAX_H - DRIFT_EST_H ago (the drift check must fit before the submit), drift.py run K BASE_drift replays
             2 of K's groups (2 unranked groups, counted in the platform's quota like any set's) as its own unit. Back in
             idle: drift PASS (>= 70% of at least 8 games byte-identical) and K still under REUSE_MAX_H old: BASE_T/_P and
             their logs become symlinks to K_T/_P, and the submit follows in the same tick. Drift FAIL, K too old, or
             no drift result: the fresh BASE half plays as before. Each path is logged with its reason.
  base       the BASE half plays; when both sets say DONE (and its unit ended), submit.
  submit     re-verified in the same tick: source hash, the switch grep, the base is live.json's build, live.json's
             version is the platform's active one (not pinned, paused or frozen), no set playing, quota. The queued source
             and its base are copied to /data/USER/autoship/frozen/NAME (bundled locally to prove the copy), and the
             frozen copy is submitted through platlock.sh.
  submitted  waits for the new version to be active, then (2 min after the submit at the earliest) starts the NEW half
             and autoread run, each as its own systemd user unit (through jobs.py run).
  new        acts on the verdict file: KEEP: relqueue.py done --result KEEP, then the next entry. REVERT: resubmit the
             frozen base, then relqueue.py done --result REVERT. NEEDS REVIEW: the same as REVERT, plus board.py next ID
             "read the verdict" --by review. TIMEOUT: an error.
  reverting  waits for the resubmitted base to be active, then relqueue.py done.
Pin mode (state/autoship.pin, written by a trial PASS; owner 28 Oct): the live selection is pinned (submissions activate
N). A submit un-pins it and selects the new version (trial 28 Oct 16:15), so every pin-mode submit is followed at once by
activating the live version again (submit_pinned), before the new one is built: Live never moves. submit becomes: pre-submit
the frozen copy (sets may play: Live stays pinned), wait
until its version is ready, then activate it once no set plays (the NEW half starts from the activation). While a NEW half
plays, a queue head built on the release in flight is pre-submitted, so its build is ready at the verdict. KEEP: the new
version stays pinned. REVERT and NEEDS REVIEW: activate the base version (no resubmit). check_submit refuses a selection not
pinned to the live version; without pin mode it refuses a pinned one, and never submits while a set plays.
Any error (or a timeout): resubmit the frozen base (pin mode: activate the base version) if the new build may be live and
no set plays, block the card with the error, write state/autoship.off, and stop. Every step is logged in live_results.md and on the card.
Never logs in, never touches proj400, and submits nothing but the head of the queue or its frozen base."""
import calendar, fcntl, glob, json, os, re, shutil, socket, subprocess, sys, time, zipfile
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader

REPO = '/homes/USER/cambc'
REPORTS = os.environ.get('AUTOREAD_REPORTS') or '/homes/USER/condor-work/reports'      # override for tests
STATE = REPORTS + '/state'
ST, LOCK, OFF, VERD = STATE + '/autoship.json', STATE + '/autoship.lock', STATE + '/autoship.off', STATE + '/verdicts'
KICK = STATE + '/autoship.kick'                 # stamped by each kick, read by the tick it may have been merged into
PIN, TRIAL = STATE + '/autoship.pin', STATE + '/pin_trial.txt'      # pin mode on; the trial's platform answers
LR = REPORTS + '/live_results.md'
FROZEN = os.environ.get('AUTOSHIP_FROZEN') or '/data/USER/autoship/frozen'
UNIT_DIR = os.environ.get('AUTOSHIP_UNIT_DIR') or os.path.expanduser('~/.config/systemd/user')
RQ = os.environ.get('AUTOSHIP_RELQUEUE') or REPO + '/tools/lab/relqueue.py'
AR = os.environ.get('AUTOSHIP_AUTOREAD') or REPO + '/tools/lab/autoread.py'
JOBS, BOARD = REPO + '/tools/lab/jobs.py', REPO + '/tools/lab/board.py'
DRIFT = os.environ.get('AUTOSHIP_DRIFT') or REPO + '/tools/lab/drift.py'
PLATLOCK, RELSETS = REPO + '/tools/lab/platlock.sh', '/data/USER/mf/py/release_sets.sh'
CLI, BUILDS = '/data/USER/cambc400/bin/cambc400', '/data/USER/mf/v188/builds.txt'
PY, WHO = '/usr/bin/python3', 'autoship'
SELF = REPO + '/tools/lab/autoship.py'         # what the service and the units' kicks run (not __file__: selftest loads a copy)
SOON_S, POLL_S = 10, 45                        # kick delays: after an event, and while a submitted version builds
QUOTA_MIN = 12                  # a lean half is 10 groups
NEW_DELAY = 120                 # the NEW half starts 2 min after the submit at the earliest
SUBMIT_WAIT_MIN = 30            # the submitted version must be active by then
BASE_MAX_H = 4                  # a BASE half still not DONE after this is an error
REUSE_MAX_H = 2                 # base reuse: K finished under this long before the submit (owner 28 Oct, ADR 0006)
NODRIFT_H = 0.5                 # ... and under this long: reused with no drift check (owner 28 Oct, it20 ~20-min cycle)
DRIFT_EST_H = 0.5               # a drift check takes up to this long, so it starts only while K is younger than 2 - 0.5 h
DRIFT_MAX_H = 1.5               # a drift unit still running after this is an error
REVERT_WAIT_H = 2               # a resubmit held back by a playing set this long is an error
NEW_MAX_H = 8                   # no verdict this long after the submit is an error (autoread itself times out at 6 h)
READY = ('ready', 'inactive', 'active')         # a built version (pinned: not the selection); the trial logs the real words
# cancelled: the platform builds only the selected version, so an activation cancels a queued build (pin trial 2, 28 Oct 16:32)
FAILED = ('failed', 'error', 'rejected', 'invalid', 'cancelled', 'canceled')
TRIAL_POLL_S = 20
MERGED = os.environ.get('AUTOSHIP_MERGED') or '/data/USER/autoship/merged'   # merged builds; bots/MERGE_PFX* link here
MERGE_PFX = 'nova_as_'          # autoship's own bot-name prefix: a merged build is bots/nova_as_<entry>_<live version>
SMOKE_PROJ = os.environ.get('AUTOSHIP_SMOKE_PROJ') or '/data/USER/cambc400/proj'    # sdk/, cmake/, cambc.toml for the smoke
SMOKE_MAP, SMOKE_ROUNDS = REPO + '/maps/00anvil.map26a', 300
SMOKE_BAD = r'RUN_FAIL|panic|\btrap\b|\berror\b'     # in the smoke's output: the merged build is not clean

rq = SourceFileLoader('relqueue_as', RQ).load_module()


def now():
    return time.time()


def iso(t=None):
    return datetime.fromtimestamp(now() if t is None else t, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def run_cmd(argv, cwd=REPO, timeout=1800):
    """(rc, output) of one external command; the single seam selftest replaces."""
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -1, 'timed out after %d s' % timeout
    except OSError as ex:
        return 127, str(ex)


class Fail(Exception):
    pass


def plat(args, cwd=REPO):
    return run_cmd(['sh', PLATLOCK, CLI] + args, cwd=cwd)


def plat_json(args):
    rc, out = plat(args + ['--json'])
    try:
        return json.loads(out[out.index('{'):])
    except ValueError:
        raise Fail('platform read %s failed (exit %d): %s' % (' '.join(args), rc, out.strip()[-300:]))


def quota_left():
    q = plat_json(['match-groups', 'quota'])['quota']
    return q['limit'] - q['used']


def subs():
    return plat_json(['submissions', 'list'])


def act_ver(s):
    return (s.get('active') or {}).get('version')


def sel_ver(s):
    return (s.get('selected') or {}).get('version')


def pinned_to(s, v):
    """The platform plays v and the selection is pinned to it (a submit then leaves Live alone)."""
    return bool(s.get('pinned')) and sel_ver(s) == v and act_ver(s) == v


def sel_text(s):
    return 'pinned %s, selected v%s, active v%s' % (bool(s.get('pinned')), sel_ver(s), act_ver(s))


def pin_mode():
    return os.path.exists(PIN)


def activate(v):
    """Select version v (a number, or 'latest' = follow the newest ready version); the platform's answer."""
    rc, out = plat(['submissions', 'activate', str(v)])
    if rc:
        raise Fail('submissions activate %s failed (exit %d): %s' % (v, rc, out.strip()[-300:]))
    return out.strip().splitlines()[-1] if out.strip() else ''


def queue_next():
    rc, out = run_cmd([PY, '-I', RQ, 'next', '--json'], timeout=600)
    try:
        return json.loads(out[out.index('{'):])
    except ValueError:
        raise Fail('relqueue.py next --json failed (exit %d): %s' % (rc, out.strip()[-300:]))


def load():
    try:
        return json.load(open(ST))
    except (OSError, ValueError):
        return dict(phase='idle', history=[])


def save(st):
    os.makedirs(STATE, exist_ok=True)
    tmp = ST + '.tmp%d' % os.getpid()
    json.dump(st, open(tmp, 'w'), indent=1)
    os.replace(tmp, ST)


def lr(head, rest=''):
    stamp = subprocess.run(['date', '-u'], capture_output=True, text=True).stdout.strip()
    with open(LR, 'a') as f:
        f.write('- %s | %s | **%s** %s\n' % (stamp, WHO, head, rest))


def board(*args):
    rc, out = run_cmd([PY, '-I', BOARD] + list(args) + ['--as', WHO], timeout=300)
    if rc:
        print('board.py %s: exit %d %s' % (args[0], rc, out.strip()[-200:]))


def log(st, head, rest=''):
    """A step: live_results.md, the card, and the state's history."""
    lr(head, rest)
    for c in cards(st):
        board('note', c, 'autoship: %s %s' % (head, rest))
    st.setdefault('history', []).append('%s %s %s' % (iso(), head, rest))
    print(head, rest)


def ecards(e):
    """The board cards of queue entry e (both of a fast-lane pair)."""
    return list(e.get('cards') or ([e['card']] if e.get('card') else []))


def who(e):
    """The state fields naming e's cards: card (the first, which units and the status line show) and cards (all)."""
    return dict(card=e.get('card'), cards=ecards(e))


def cards(st):
    return list(st.get('cards') or ([st['card']] if st.get('card') else []))


def unit_start(tag, card, out, cmd):
    unit = 'autoship-' + re.sub(r'[^A-Za-z0-9_.-]', '_', tag)
    argv = ['systemd-run', '--user', '--unit=' + unit, '--collect', '--quiet', '--property=Nice=10',
            '--working-directory=' + REPO, '--setenv=PATH=' + os.environ.get('PATH', '/usr/bin:/bin'),
            '--setenv=HOME=' + os.path.expanduser('~'), '--property=ExecStopPost=-%s -I %s kick' % (PY, SELF), '--',
            PY, '-I', JOBS, 'run', '--card', card, '--name', tag, '--out', out,
            '--recover', 'autoship tick picks it up from state/autoship.json', '--as', WHO, '--'] + cmd
    rc, o = run_cmd(argv, timeout=120)
    if rc:
        raise Fail('systemd-run %s failed (exit %d): %s' % (unit, rc, o.strip()[-300:]))
    return unit


def unit_running(unit):
    rc, out = run_cmd(['systemctl', '--user', 'is-active', unit], timeout=60)
    return out.strip() in ('active', 'activating', 'reloading')


def set_done(pfx):
    """Both sets of a half say DONE in their logs (replays and summaries in)."""
    for s in (pfx + '_T', pfx + '_P'):
        try:
            if not re.search(r'^DONE', open('%s/%s.log' % (rq.PLAT, s), errors='replace').read(), re.M):
                return False
        except OSError:
            return False
    return True


def half_age_h(pfx):
    """Hours since the half PFX finished (the later of its two logs' last writes: diag.sh writes DONE last)."""
    return (now() - max(os.path.getmtime('%s/%s%s.log' % (rq.PLAT, pfx, s)) for s in ('_T', '_P'))) / 3600


def spec_of(x):
    """The autoread registration of queue entry x, or {}."""
    try:
        return json.load(open('%s/%s.json' % (rq.SPECS, x['autoread']))) if x.get('autoread') else {}
    except (OSError, ValueError):
        return {}


def base_halves(lv):
    """[(K, family, how)]: the halves played on the live build lv['bot'] (itfastq, 28 Oct): the NEW half of the KEEP that
    made it live, and the BASE half of each release built on it that was reverted (REVERT or NEEDS REVIEW; it played while
    lv was live, before that release's submit). A merged entry's base is the build it was merged onto."""
    try:
        q = json.load(open(rq.Q))
    except (OSError, ValueError):
        return []
    out = []
    keeps = [x for x in q if x.get('bot') == lv['bot'] and x.get('result') == 'KEEP']
    if keeps and spec_of(keeps[-1]).get('new'):
        out.append((spec_of(keeps[-1])['new'], keeps[-1].get('family'), 'the NEW half of %s, the KEEP that made %s live' % (keeps[-1]['name'], lv['bot'])))
    for x in q:
        if x.get('base') == lv['bot'] and str(x.get('result') or '').startswith('REVERT') and spec_of(x).get('base'):
            out.append((spec_of(x)['base'], x.get('family'), 'the BASE half of %s, reverted on %s' % (x['name'], lv['bot'])))
    return out


def real_half(k):
    """The half whose sets K's really are: K, or the half its BASE-reuse aliases (make_aliases) point to; None if K_T and
    K_P point to different halves or out of the platform dir."""
    got = set()
    for s in ('_T', '_P'):
        f = '%s/%s%s' % (rq.PLAT, k, s)
        r = os.path.realpath(f)
        if os.path.dirname(r) != os.path.realpath(rq.PLAT) or not os.path.basename(r).endswith(s):
            return None
        got.add(os.path.basename(r)[:-2])
    return got.pop() if len(got) == 1 else None


def reuse_ok(k, lv, fam):
    """(real half or None, why): K may stand in for this release's BASE half if its sets were played on the live build:
    K is one of base_halves(lv) (following aliases: a reused BASE half counts as the half it aliases, which must itself be
    one played on lv), on the entry's layout."""
    hs = base_halves(lv)
    hit = [h for h in hs if h[0] == k]
    if not hit:
        news = [h[0] for h in hs if h[2].startswith('the NEW')]
        revs = [h[0] for h in hs if h[2].startswith('the BASE')]
        return None, '%s is not the NEW half of the live build %s\'s KEEP (%s) nor the BASE half of a release on it that was reverted (%s)' % (
            k, lv['bot'], ', '.join(news) or 'none recorded', ', '.join(revs) or 'none')
    k0, kf, how = hit[-1]
    real = real_half(k)
    played = {h[0] for h in hs if real_half(h[0]) == h[0]}
    if real is None or real not in played:
        return None, '%s (%s) is an alias of %s, not a half played on %s' % (k, how, real or 'two halves', lv['bot'])
    if kf != fam:
        return None, 'layouts differ: %s played %s, this entry %s' % (k, kf, fam)
    return real, how + ('' if real == k else '; its sets are aliases of %s' % real)


def pick_reuse(lv, fam):
    """(K, why) the freshest finished half played on the live build on layout fam (for base reuse without --reuse), or
    (None, why)."""
    best, why = None, 'no half played on %s' % lv['bot']
    for k, kf, how in base_halves(lv):
        real, w = reuse_ok(k, lv, fam)
        if real and set_done(real) and (best is None or half_age_h(real) < half_age_h(best[0])):
            best = (real, w)
        elif not real:
            why = w
    return best or (None, why)


def reuse_state(spec, e, lv):
    """Base reuse for queue entry e on live lv: (path, why, K, drift tag, drift result or None).
    path: 'drift' (run the check), 'reuse' (alias the BASE sets to K and submit) or 'fresh' (play the BASE half).
    K is a half played on the live build (reuse_ok: its KEEP's NEW half, or a reverted release's BASE half): the
    registration's --reuse, else (it20: every release reuses) pick_reuse's freshest. An alias is followed to the half it
    stands for, which is the K returned."""
    k, tag = spec.get('reuse'), spec['base'] + '_drift'
    res = None
    try:
        res = json.load(open('%s/%s.json' % (rq.PLAT, tag)))
    except (OSError, ValueError):
        pass
    if k:
        real, how = reuse_ok(k, lv, e['family'])
        if not real:
            return 'fresh', how, k, tag, res
    else:
        real, how = pick_reuse(lv, e['family'])
        if not real:
            return 'fresh', how, real, tag, res
        if real in (spec['base'], spec.get('new')):
            return 'fresh', 'the live build\'s half %s is this entry\'s own --base or --new tag' % real, real, tag, res
    k = real
    if not set_done(k):
        return 'fresh', '%s_T/_P do not both say DONE' % k, k, tag, res
    age = half_age_h(k)
    if res is not None:
        if not res.get('pass'):
            return 'fresh', 'drift FAIL: %s of %s games byte-identical (%.0f%%, need %.0f%% of at least 8)' % (
                res.get('identical'), res.get('games'), 100 * (res.get('share') or 0), 100 * res.get('share_min', 0.7)), k, tag, res
        if age >= REUSE_MAX_H:
            return 'fresh', 'drift passed, but %s finished %.2f h ago (limit %d h)' % (k, age, REUSE_MAX_H), k, tag, res
        return 'reuse', 'drift PASS: %d of %d games byte-identical (%.0f%%); %s (%s) finished %.2f h ago' % (
            res['identical'], res['games'], 100 * res['share'], k, how, age), k, tag, res
    if os.path.exists('%s/%s.log' % (rq.PLAT, tag)):
        return 'fresh', 'drift %s ended without a result (%s/%s.log)' % (tag, rq.PLAT, tag), k, tag, res
    if age < NODRIFT_H:
        return 'reuse', '%s finished %.0f min ago: under %.0f min, no drift check' % (k, 60 * age, 60 * NODRIFT_H), k, tag, res
    if age + DRIFT_EST_H >= REUSE_MAX_H:
        return 'fresh', '%s finished %.2f h ago: too old to reuse (limit %d h, the drift check needs %.1f h)' % (k, age, REUSE_MAX_H, DRIFT_EST_H), k, tag, res
    return 'drift', '%s (%s) finished %.2f h ago' % (k, how, age), k, tag, res


def drift_groups(fam):
    """The group lines drift.py run replays (the first of each tier's layout file), or why they cannot be read."""
    try:
        dr = SourceFileLoader('drift_as', DRIFT).load_module()
        return [[l.strip() for l in open(f) if l.strip() and not l.startswith('#')][0] for f in dr.layout(fam)]
    except (OSError, IndexError, SystemExit) as ex:
        return ['unreadable: %s' % ex]


def make_aliases(k, base):
    """BASE_T/_P (and their logs) as symlinks to K's: the checks read them as BASE; V3 holds (K played before this submit)."""
    for s in ('_T', '_P', '_T.log', '_P.log'):
        dst, src = '%s/%s%s' % (rq.PLAT, base, s), k + s
        if os.path.islink(dst) and os.readlink(dst) == src:
            continue
        if os.path.lexists(dst):
            raise Fail('base reuse: %s exists and is not an alias of %s' % (dst, src))
        os.symlink(src, dst)


def build_time(ver):
    for l in open(BUILDS):
        p = l.split()
        if len(p) == 2 and p[1] == ver:
            return p[0]
    raise Fail('live version %s has no submit time in %s' % (ver, BUILDS))


def verdict(name, since):
    """The final verdict of autoread NAME written after `since`, or None."""
    f = '%s/%s.md' % (VERD, name)
    if not os.path.exists(f) or os.path.getmtime(f) < since:
        return None
    first = open(f, errors='replace').readline()
    if 'TIMEOUT' in first:
        return 'TIMEOUT'
    m = re.match(r'# autoread \S+: (.+)', first)
    return m.group(1).strip() if m else 'UNREADABLE'


def platform_version(s, after=0):
    """(version, status) of the newest submission above `after`, or (None, None)."""
    new = [x for x in s.get('submissions', []) if x.get('version', 0) > after]
    if not new:
        return None, None
    x = max(new, key=lambda x: x['version'])
    return x['version'], x.get('status')


def vnum(v):
    return int(str(v).lstrip('v')) if v and re.match(r'^v?\d+$', str(v)) else 0


# ---- the frozen copy -------------------------------------------------------------------------------------------------

def freeze(name, bot):
    """Copy bots/DIR into FROZEN/NAME/bots/DIR (with the repo's cambc.toml at FROZEN/NAME) and prove it: the source hash
    and a local bundle of the copy (no platform call). Returns the frozen project dir."""
    proj = os.path.join(FROZEN, name)
    dst = os.path.join(proj, bot)
    if not os.path.isdir(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(REPO, 'cambc.toml'), os.path.join(proj, 'cambc.toml'))
        shutil.copytree(os.path.join(REPO, bot), dst, ignore=shutil.ignore_patterns('.*'))
    return proj


def prove_frozen(proj, bot, want):
    dst = os.path.join(proj, bot)
    if rq.src_hash(dst) != want:
        raise Fail('frozen copy %s has src %s, not %s' % (dst, rq.src_hash(dst), want))
    z = os.path.join(proj, os.path.basename(bot) + '.zip')
    rc, out = run_cmd([CLI, 'bundle', bot, '--output', z], cwd=proj, timeout=300)
    if rc or not os.path.exists(z):
        raise Fail('bundle of the frozen copy %s failed (exit %d): %s' % (dst, rc, out.strip()[-300:]))
    names = {n for n in zipfile.ZipFile(z).namelist() if not n.endswith('/')}
    srcs = {os.path.relpath(f, dst) for f in rq.src_files(dst) if '/src/' in f}
    if not srcs or not any(n.endswith(s) for s in srcs for n in names):
        raise Fail('bundle of %s holds none of its src files: %s' % (dst, sorted(names)[:5]))


def submit(proj, bot, note):
    rc, out = plat(['submit', '-n', note[:80], bot], cwd=proj)
    if rc:
        raise Fail('submit of %s/%s failed (exit %d): %s' % (proj, bot, rc, out.strip()[-300:]))
    return out


def submit_pinned(proj, bot, note, expect):
    """Pin mode: a submit un-pins the selection and selects the new version (pin trial 28 Oct 16:15: pinned False,
    selected v250, active v249 while v250 built). Activate v`expect` again at once, before the new version is built, so
    Live never moves; Fail unless the selection is then pinned to it. Returns (submit answer, activation answer)."""
    try:
        out = submit(proj, bot, note)
    finally:
        how = activate(expect)
    s = subs()
    if not pinned_to(s, expect):
        raise Fail('the submit of %s un-pinned Live and activate v%s left %s' % (bot, expect, sel_text(s)))
    return out, how


# ---- a queued candidate onto another live build, by diff (owner 28 Oct, LR:2780) ------------------------------------

def queued_as(e):
    """What e was queued as: {bot, base, src, lab, base_src, base_lab} (its first rebase keeps it in rebased_from)."""
    return e.get('rebased_from') or dict(bot=e['bot'], base=e['base'], src=e['src'], lab=e.get('gate', {}).get('lab'),
                                         base_src=e.get('base_src'), base_lab=e.get('base_lab'))


def live_copy(lv):
    """(dir, what): the live build's source as it shipped: the frozen copy autoship submitted it from (its KEEP, or the
    base a REVERT resubmitted), else its bot dir."""
    try:
        q = json.load(open(rq.Q))
    except (OSError, ValueError):
        q = []
    for x in reversed(q):
        res = str(x.get('result') or '')
        if x.get('status') != 'done' or not ((res == 'KEEP' and x['bot'] == lv['bot']) or (res.startswith('REVERT') and x['base'] == lv['bot'])):
            continue
        d = os.path.join(FROZEN, x['name'], lv['bot'])
        if os.path.isdir(d) and (res != 'KEEP' or rq.src_hash(d) == x['src']):
            return d, 'the frozen copy %s (%s %s)' % (d, x['name'], res)
        break
    return os.path.join(REPO, lv['bot']), 'its bot dir %s (no frozen copy)' % lv['bot']


def base_copy(fr):
    """A dir holding the source e was built on (lab hash base_lab): its base dir, else a frozen copy of it; or None."""
    for d in [os.path.join(REPO, fr['base'])] + sorted(glob.glob(os.path.join(FROZEN, '*', fr['base']))):
        if os.path.isdir(d) and rq.lab_hash(d) == fr.get('base_lab'):
            return d
    return None


def smoke(bot_dir, tag):
    """(ok, text): build bot_dir in release mode and play it against itself (SMOKE_ROUNDS rounds) in autoship's own
    project MERGED/.smoke, on a real copy (the CLI builds inside the bot dir)."""
    proj = os.path.join(MERGED, '.smoke')
    if not os.path.isdir(proj + '/sdk'):
        os.makedirs(proj, exist_ok=True)
        for x in ('sdk', 'cmake'):
            shutil.copytree(os.path.join(SMOKE_PROJ, x), os.path.join(proj, x), dirs_exist_ok=True)
        shutil.copy2(os.path.join(SMOKE_PROJ, 'cambc.toml'), proj + '/cambc.toml')
    dst = os.path.join(proj, 'bots', tag)
    if os.path.lexists(dst):
        shutil.rmtree(dst) if not os.path.islink(dst) else os.remove(dst)
    shutil.copytree(bot_dir, dst, ignore=shutil.ignore_patterns('.*'))
    rc, out = run_cmd([CLI, 'run', '--release', 'bots/' + tag, 'bots/' + tag, '--map', SMOKE_MAP, '--rounds', str(SMOKE_ROUNDS),
                       '-o', os.path.join(proj, 'out')], cwd=proj, timeout=1200)
    open(os.path.join(proj, tag + '.smoke.log'), 'w').write(out)
    shutil.rmtree(dst, ignore_errors=True)
    bad = re.findall(r'^.*(?:%s).*$' % SMOKE_BAD, out, re.M | re.I)
    if rc or bad:
        return False, 'smoke failed (exit %d): %s (log %s/%s.smoke.log)' % (rc, ' | '.join(bad[:3]) or out.strip()[-200:], proj, tag)
    return True, 'smoke clean: %d rounds, %s (log %s/%s.smoke.log)' % (SMOKE_ROUNDS, os.path.basename(SMOKE_MAP), proj, tag)


def merge_onto(e, lv):
    """Put entry e on the live build lv by diff: per file, git merge-file -p (the live build's shipped source, the base e
    was built on, e's candidate) into a new dir under MERGED made with cp -rL from the live copy (relqueue.merge3: no
    symlinks, no write into any input; owner tab LR 15:48); then the identity check (e's change against its base is the
    merged build's change against the live build, file by file), the switch check, a smoke game. Returns (bot or None,
    text). On success the merged build is MERGED/TAG, linked as bots/TAG, TAG = MERGE_PFX + entry + live version; nothing
    is written anywhere else."""
    fr = queued_as(e)
    cand = os.path.join(REPO, fr['bot'])
    if not os.path.isdir(cand) or rq.lab_hash(cand) != fr['lab']:
        return None, 'the candidate %s changed since it was queued (src %s, queued %s)' % (fr['bot'], rq.lab_hash(cand) if os.path.isdir(cand) else 'gone', fr['lab'])
    base = base_copy(fr)
    if not base:
        return None, 'no copy of its base %s with src %s (the base dir changed and no frozen copy holds it)' % (fr['base'], fr.get('base_lab'))
    live, lwhat = live_copy(lv)
    tag = MERGE_PFX + re.sub(r'[^A-Za-z0-9_]', '_', e['name']) + '_' + lv['version']
    work = os.path.join(MERGED, '.work', tag)
    if os.path.lexists(work):
        os.remove(work) if os.path.islink(work) else shutil.rmtree(work)
    os.makedirs(os.path.dirname(work), exist_ok=True)
    head = '%s (src %s) on %s (src %s) onto %s %s, %s (src %s)' % (fr['bot'], fr['lab'], fr['base'], fr.get('base_lab'), lv['bot'], lv['version'], lwhat, rq.lab_hash(live))
    try:                                        # a new dir (cp -rL of the live copy); the three inputs are only read
        bad = rq.merge3(cand, base, live, work)
    except RuntimeError as ex:
        return None, 'merge failed, %s: %s' % (head, ex)
    if bad:
        return None, 'merge conflict, %s: %s' % (head, '; '.join(bad))
    diff = rq.same_change(cand, base, live, work)
    if diff:
        return None, 'identity check failed, %s: the change differs in %s' % (head, ', '.join(diff))
    sw = ['%s wanted %s, #define gives %s' % (nm, w, v or 'none') for nm, w, v, _ in rq.switch_check(work, e['switches']) if v != [w]]
    if sw:
        return None, 'switch check failed on the merged build, %s: %s' % (head, '; '.join(sw))
    ok, sm = smoke(work, tag)
    if not ok:
        return None, '%s, %s' % (sm, head)
    final, link = os.path.join(MERGED, tag), os.path.join(REPO, 'bots', tag)
    if os.path.isdir(final) and rq.lab_hash(final) != rq.lab_hash(work):
        return None, '%s exists with other source (src %s, merged %s): drop it by hand' % (final, rq.lab_hash(final), rq.lab_hash(work))
    if os.path.lexists(link) and os.path.realpath(link) != os.path.realpath(final):
        return None, 'bots/%s exists and is not autoship\'s merged build' % tag
    if os.path.isdir(final):
        shutil.rmtree(work)
    else:
        os.rename(work, final)
    if not os.path.lexists(link):
        os.symlink(final, link)
    return 'bots/' + tag, 'identity OK (the same change in each file), switches OK, %s; %s' % (sm, head)


def owner_role(e):
    """Who fixes a merge that failed: the role owning e's card on the board, else the coordinator."""
    try:
        bc = {c.get('id'): c for c in json.load(open('%s/board.json' % rq.BOARD)).get('cards', [])}
    except (OSError, ValueError):
        bc = {}
    return (bc.get(e.get('card')) or {}).get('owner') or 'coordinator'


# ---- planning: read-only; returns (what, act) with act None for a wait ---------------------------------------------

def check_submit(n):
    """Problems that stop the submit, re-read now: (hard, soft) lists; soft ones (sets, quota) only make it wait."""
    e, lv = n['entry'], rq.live()
    bot = os.path.join(REPO, e['bot'])
    hard, soft = [], []
    if not os.path.isdir(bot):
        return ['bot dir %s is gone' % e['bot']], []
    if rq.src_hash(bot) != e['src']:
        hard.append('source changed since it was queued (src %s, queued %s)' % (rq.src_hash(bot), e['src']))
    hard += ['%s wanted %s, #define gives %s' % (nm, w, v or 'none') for nm, w, v, _ in rq.switch_check(bot, e['switches']) if v != [w]]
    if not lv or not lv.get('version'):
        hard.append('the live build is not recorded with its version (relqueue.py live --set)')
    elif e['base'] != lv['bot']:
        hard.append('its base %s is not the live build %s' % (e['base'], lv['bot']))
    try:                                        # the base dir must still hold the source that shipped (it is resubmitted on a REVERT)
        shipped = [x['src'] for x in json.load(open(rq.Q)) if x['bot'] == e['base'] and x.get('result') == 'KEEP']
    except (OSError, ValueError, KeyError):
        shipped = []
    if shipped and rq.src_hash(os.path.join(REPO, e['base'])) != shipped[-1]:
        hard.append('base dir %s changed since it shipped (src %s, shipped %s)' % (e['base'], rq.src_hash(os.path.join(REPO, e['base'])), shipped[-1]))
    s = subs()
    act = (s.get('active') or {}).get('version')
    if lv and act != vnum(lv.get('version')):
        hard.append('the platform runs v%s, live.json says %s' % (act, lv.get('version')))
    for k in ('pinned', 'frozen', 'submissionPause', 'compilationPaused'):
        if s.get(k) and not (k == 'pinned' and pin_mode()):
            hard.append('platform %s: %s (pin mode is off: a submit would not go live)' % (k, s[k]) if k == 'pinned' else 'platform %s: %s' % (k, s[k]))
    if pin_mode() and lv and not pinned_to(s, vnum(lv.get('version'))):
        hard.append('pin mode: the selection is not pinned to live %s (%s)' % (lv.get('version'), sel_text(s)))
    busy = rq.playing()
    if busy:
        soft.append('sets playing: ' + ', '.join(busy))
    bt = '%s/%s_T' % (rq.PLAT, (n.get('spec') or {}).get('base'))
    k = os.readlink(bt)[:-2] if os.path.islink(bt) else None
    if k and half_age_h(k) >= REUSE_MAX_H:
        hard.append('base sets %s are aliases of %s, which finished %.2f h ago (base reuse limit %d h)' % (n['spec']['base'], k, half_age_h(k), REUSE_MAX_H))
    left = quota_left()
    if left < QUOTA_MIN:
        soft.append('quota: %d groups left (a half needs 10)' % left)
    return hard, soft


def plan(st):
    ph = st.get('phase', 'idle')
    if ph == 'stopped':
        return 'stopped by an error: %s (fix it, then autoship.py arm --reset)' % st.get('error'), None
    if ph == 'idle':
        return plan_idle(st)
    if ph == 'base':
        return plan_base(st)
    if ph == 'drift':
        return plan_drift(st)
    if ph == 'submitted':
        return plan_submitted(st)
    if ph == 'new':
        return plan_new(st)
    if ph == 'reverting':
        return plan_reverting(st)
    if ph == 'submitting':
        return 'error: a tick died during the submit of %s' % st.get('entry'), lambda: fail(st, 'a tick died during the submit (phase submitting)')
    raise Fail('unknown phase %s' % ph)


def plan_idle(st):
    n = queue_next()
    p = st.get('pre')
    if p and (p.get('entry') != n.get('name') or p.get('src') != (n.get('entry') or {}).get('src')):
        def drop():                             # its version stays built on the platform and is never activated
            log(dict(st, card=(n.get('entry') or {}).get('card')), 'autoship: pre-submitted %s dropped' % p.get('entry'),
                'head now %s; its version is never activated' % (n.get('name') or 'none'))
            st.pop('pre', None)
            save(st)
        return 'drop the pre-submitted %s: the head is now %s' % (p.get('entry'), n.get('name') or 'none'), drop
    if not n.get('name'):
        return 'wait: the queue is empty', None
    e, name = n['entry'], n['name']
    if not e.get('gate'):
        return 'wait: head %s was queued before the ship gate; it ships by hand only (relqueue.py next/done)' % name, None
    kinds = {k for k, t in n['problems']}
    probs = '; '.join(t for k, t in n['problems'])
    hard = kinds & {'gone', 'src', 'switch', 'autoread'}
    if hard:
        return 'error: head %s is not shippable: %s' % (name, probs), lambda: fail(dict(st, entry=name, **who(e)), probs)
    if not n.get('live') or not n['live'].get('version'):
        return 'error: the live build is not recorded', lambda: fail(dict(st, entry=name, **who(e)),
                                                                       'live build not recorded: relqueue.py live --set bots/DIR --version vNNN')
    if 'notlive' in kinds and getattr(rq, 'rebasable', lambda e: False)(e):
        lv = n['live']
        key = [name, queued_as(e)['src'], lv['bot'], lv['version']]
        if st.get('merge', {}).get('key') == key:
            return 'wait: %s does not go onto the live build %s by diff: %s; %s fixes it' % (name, lv['bot'], st['merge']['why'], owner_role(e)), None
        if 'playing' in kinds:
            return 'wait: ' + '; '.join(t for k, t in n['problems'] if k == 'playing'), None

        def rebase():
            bot, why = merge_onto(e, lv)
            if bot:
                rc, out = run_cmd([PY, '-I', RQ, 'rebase', name, '--bot', bot, '--onto', lv['bot'], '--live-src', rq.lab_hash(live_copy(lv)[0]),
                                   '--why', why[:300], '--by', WHO])
                if rc:
                    raise Fail('relqueue.py rebase %s failed: %s' % (name, out.strip()[-300:]))
                log(dict(st, entry=name, **who(e)), 'autoship %s: merged onto the live build %s %s by diff' % (name, lv['bot'], lv['version']),
                    '%s (src %s / %s): %s' % (bot, rq.src_hash(os.path.join(REPO, bot)), rq.lab_hash(os.path.join(REPO, bot)), why))
                st.pop('merge', None)
                save(st)
                return
            role = owner_role(e)
            for c in ecards(e):
                board('next', c, 'rebuild on the live build (the merge by diff failed)', '--by', role, '--deliverable',
                      'relqueue.py add of the rebuilt entry, or a fix that merges', '--stop', 'queued on base %s' % lv['bot'])
            st['merge'] = dict(key=key, why=why)
            log(dict(st, entry=name, **who(e)), 'autoship waits: %s does not go onto the live build by diff' % name,
                'its base %s, live %s %s: %s; %s asked to rebuild it' % (e['base'], lv['bot'], lv['version'], why, role))
            save(st)
        return 'merge %s onto the live build %s %s by diff (git merge-file, identity, switches, smoke), then go on' % (name, lv['bot'], lv['version']), rebase
    if 'notlive' in kinds:
        if st.get('told') == name:
            return 'wait: %s is built on %s, not the live build %s; the coordinator rebuilds it' % (name, e['base'], n['live']['bot']), None

        def tell():
            board('next', e['card'], 'rebuild on the live build', '--by', 'coordinator', '--deliverable', 'relqueue.py add of the rebuilt entry',
                  '--stop', 'queued on base %s' % n['live']['bot'])
            st['told'] = name
            log(dict(st, **who(e)), 'autoship waits: %s is not on the live build' % name,
                'its base %s, live %s %s; card %s asked to rebuild' % (e['base'], n['live']['bot'], n['live']['version'], e.get('card')))
            save(st)
        return 'tell the coordinator to rebuild %s on the live build %s, then wait' % (name, n['live']['bot']), tell
    pp = pin_problem()
    if pp:
        return 'error: ' + pp, lambda: fail(dict(st, card=e.get('card'), entry=name), pp)
    if 'playing' in kinds:
        busy = '; '.join(t for k, t in n['problems'] if k == 'playing')
        if pin_mode() and not has_pre(st, n):
            what, act = plan_presubmit(st, n, vnum(n['live']['version']))
            return '%s (%s: activated after them)' % (what, busy), act
        return 'wait: ' + busy, None
    spec, lv = n['spec'], n['live']
    if 'baseset' in kinds:
        path, why, k, tag, res = reuse_state(spec, e, lv)
        if path == 'reuse':
            return plan_submit(st, n, reuse=(k, why))
        left = quota_left()                     # the platform's own counter: drift and set groups alike
        if left < QUOTA_MIN:
            return 'wait: quota %d groups left, the %s needs %s' % (left, 'drift check' if path == 'drift' else 'BASE half',
                                                                    '2 (and 10 more if it fails)' if path == 'drift' else '10'), None
        if path == 'drift':
            cmd = [PY, '-I', DRIFT, 'run', k, tag, '--family', e['family']]
            groups = drift_groups(e['family'])

            def start_drift():
                unit = unit_start('%s-drift' % name, e['card'], '%s/%s.json' % (rq.PLAT, tag), cmd)
                st.update(phase='drift', entry=name, **who(e), spec=spec, family=e['family'], drift_unit=unit, drift_at=now(),
                          drift_tag=tag, reuse=k, live_bot=lv['bot'], live_version=lv['version'], told=None)
                log(st, 'autoship %s: base reuse drift check started' % name, '%s; %s (unit %s); groups: %s' % (why, ' '.join(cmd[2:]), unit, ' | '.join(groups)))
                save(st)
            return 'base reuse of %s (%s): start the drift check: %s; 2 groups: %s' % (k, why, ' '.join(cmd), ' | '.join(groups)), start_drift
        bt = build_time(lv['version'])
        note = '; base reuse%s not taken: %s' % (' of %s' % k if k else '', why)

        def start_base():
            unit = unit_start('%s-base' % name, e['card'], '%s/%s_T.log' % (rq.PLAT, spec['base']),
                              ['sh', RELSETS, lv['version'], bt, spec['base'], e['family']])
            st.update(phase='base', entry=name, **who(e), ar=e['autoread'], spec=spec, family=e['family'], base_unit=unit, base_at=now(),
                      live_bot=lv['bot'], live_version=lv['version'], told=None)
            log(st, 'autoship %s: BASE half started' % name, 'release_sets.sh %s %s %s %s (unit %s)%s' % (lv['version'], bt, spec['base'], e['family'], unit, note))
            save(st)
        return 'start the BASE half of %s: release_sets.sh %s %s %s %s%s' % (name, lv['version'], bt, spec['base'], e['family'], note), start_base
    stale = stale_base(spec['base'], lv['version'])
    if stale:
        if st.get('told') == name:
            return 'wait: %s; the coordinator re-registers it with a fresh base tag' % stale, None

        def tell_stale():
            for c in ecards(e):
                board('next', c, 'register a fresh BASE tag', '--by', 'coordinator', '--deliverable', 'autoread.py prereg/register with a new base tag',
                      '--stop', 'its base sets play on %s' % lv['version'])
            st['told'] = name
            log(dict(st, **who(e)), 'autoship waits: %s has stale base sets' % name, stale)
            save(st)
        return 'tell the coordinator %s, then wait' % stale, tell_stale
    return plan_submit(st, n)


def stale_base(tag, ver):
    """Why the DONE base sets TAG_T/TAG_P were not played on live VER (they record no build), or ''."""
    t0 = calendar.timegm(time.strptime(build_time(ver), '%Y-%m-%dT%H:%M:%S'))
    for s in (tag + '_T', tag + '_P'):
        d = '%s/%s' % (rq.PLAT, s)
        first = min([os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)] or [0]) if os.path.isdir(d) else 0
        if first < t0:
            return 'base set %s began before live %s was submitted (%s UTC)' % (s, ver, build_time(ver))
    return ''


def plan_drift(st):
    n = queue_next()
    if n.get('name') != st['entry']:
        return 'reset: %s is no longer the head of the queue (now %s); its drift check stays on disk' % (st['entry'], n.get('name')), \
            lambda: (log(st, 'autoship %s: left the queue during its drift check' % st['entry'], 'head now %s' % n.get('name')), reset(st))[1]
    if unit_running(st['drift_unit']):
        if now() - st['drift_at'] > DRIFT_MAX_H * 3600:
            return 'error: drift check over %.1f h' % DRIFT_MAX_H, lambda: fail(st, 'drift check %s still running after %.1f h' % (st['drift_tag'], DRIFT_MAX_H))
        return 'wait: drift check %s playing (unit %s)' % (st['drift_tag'], st['drift_unit']), None
    try:
        res = json.load(open('%s/%s.json' % (rq.PLAT, st['drift_tag'])))
        what = '%s %d of %d games byte-identical (%.0f%%)' % ('PASS' if res.get('pass') else 'FAIL', res['identical'], res['games'], 100 * res['share'])
    except (OSError, ValueError, KeyError):
        what = 'no result (%s/%s.log): the fresh BASE half plays' % (rq.PLAT, st['drift_tag'])

    def ended():
        log(st, 'autoship %s: drift check of %s %s' % (st['entry'], st['reuse'], what), 'unit %s; the next tick takes the reuse or plays the BASE half' % st['drift_unit'])
        reset(st)
    return 'drift check %s ended: %s; back to idle' % (st['drift_tag'], what), ended


def plan_base(st):
    n = queue_next()
    if n.get('name') != st['entry']:
        return 'reset: %s is no longer the head of the queue (now %s); its BASE half stays on disk' % (st['entry'], n.get('name')), \
            lambda: (log(st, 'autoship %s: left the queue during its BASE half' % st['entry'], 'head now %s' % n.get('name')), reset(st))[1]
    if not set_done(st['spec']['base']) or unit_running(st['base_unit']):
        if unit_running(st['base_unit']):
            if now() - st['base_at'] > BASE_MAX_H * 3600:
                return 'error: BASE half over %d h' % BASE_MAX_H, lambda: fail(st, 'BASE half %s not DONE after %d h' % (st['spec']['base'], BASE_MAX_H))
            return 'wait: BASE half %s playing (unit %s)' % (st['spec']['base'], st['base_unit']), None
        return 'error: the BASE half unit ended without DONE', lambda: fail(st, 'BASE half unit %s ended; %s_T/_P not DONE' % (st['base_unit'], st['spec']['base']))
    return plan_submit(st, n)


def take_reuse(st, e, name, n, reuse):
    """Re-read in the same command as the submit (or the activation): K's age, then the aliases."""
    if half_age_h(reuse[0]) >= REUSE_MAX_H:
        raise Fail('base reuse: %s turned %d h old before the submit' % (reuse[0], REUSE_MAX_H))
    if 'no drift check' in reuse[1] and half_age_h(reuse[0]) >= NODRIFT_H:
        raise Fail('base reuse: %s turned %.0f min old before the submit, with no drift check' % (reuse[0], 60 * NODRIFT_H))
    make_aliases(reuse[0], n['spec']['base'])
    log(dict(st, **who(e)), 'autoship %s: base reuse taken, %s_T/_P = %s_T/_P' % (name, n['spec']['base'], reuse[0]), reuse[1])


def after_flight(st):
    """The first ready entry after the one in flight, as {name, entry}: relqueue next names the in-flight entry until its
    verdict. Its problems are checked again (relqueue next, check_submit) before it is activated."""
    try:
        r = [e for e in json.load(open(rq.Q)) if e.get('status') == 'ready' and e.get('name') != st.get('entry')]
    except (OSError, ValueError):
        r = []
    return dict(name=r[0]['name'], entry=r[0], problems=[]) if r else {}


def pin_problem():
    """Why the platform's selection does not match pin mode, or ''. Read before any half is played: a mismatch is an error."""
    s, lv = subs(), rq.live()
    if pin_mode() and not pinned_to(s, vnum((lv or {}).get('version'))):
        return 'pin mode: the selection is not pinned to live %s (%s)' % ((lv or {}).get('version'), sel_text(s))
    if not pin_mode() and s.get('pinned'):
        return 'the selection is pinned (%s) but pin mode is off: a submit would not go live (autoship.py pin on, after the trial)' % sel_text(s)
    return ''


def has_pre(st, n):
    p = st.get('pre') or {}
    return p.get('entry') == n['name'] and p.get('src') == n['entry']['src'] and not p.get('failed')


def plan_presubmit(st, n, expect):
    """Pin mode: submit the queue head while Live stays pinned to v`expect` (sets may play). Its version builds beside
    the live one; plan_submit_pinned activates it once it is ready and no set plays."""
    e, name = n['entry'], n['name']

    def go():
        s = subs()
        if not pinned_to(s, expect):
            raise Fail('pre-submit of %s refused: the selection is not pinned to v%s (%s)' % (name, expect, sel_text(s)))
        if rq.src_hash(os.path.join(REPO, e['bot'])) != e['src']:
            raise Fail('pre-submit of %s: source changed since it was queued' % name)
        proj = freeze(name, e['bot'])
        freeze(name, e['base'])
        prove_frozen(proj, e['bot'], e['src'])
        after = max([x.get('version', 0) for x in s.get('submissions', [])] + [act_ver(s) or 0])
        st['pre'] = dict(entry=name, src=e['src'], proj=proj, bot=e['bot'], base=e['base'], after=after, at=now(), live=expect)
        save(st)
        out, how = submit_pinned(proj, e['bot'], 'autoship %s src %s' % (name, e['gate']['lab']), expect)
        log(dict(st, **who(e)), 'autoship %s: pre-submitted, Live stays pinned to v%s' % (name, expect), 'frozen copy %s/%s (src %s / %s); %s' % (
            proj, e['bot'], e['src'], e['gate']['lab'], out.strip().splitlines()[-1] if out.strip() else '') + '; v%s activated again: %s' % (expect, how))
        save(st)
    return 'pre-submit %s: frozen copy of %s (src %s); Live stays pinned to v%s' % (name, e['bot'], e['src'], expect), go


def plan_submit_pinned(st, n, reuse):
    e, name = n['entry'], n['name']
    hard, soft = check_submit(n)
    if hard:
        return 'error before the submit of %s: %s' % (name, '; '.join(hard)), lambda: fail(dict(st, entry=name, **who(e)), '; '.join(hard))
    lv = rq.live()
    live = vnum(lv['version'])
    if not has_pre(st, n):
        return plan_presubmit(st, n, live)
    p = st['pre']
    ver, status = platform_version(subs(), p['after'])
    if ver is None or status not in READY:
        if status in FAILED:
            return 'error: the build of %s (v%s) %s' % (name, ver, status), lambda: fail(dict(st, entry=name, **who(e)),
                                                                                     'pre-submitted v%s of %s: build %s' % (ver, name, status))
        if now() - p['at'] > SUBMIT_WAIT_MIN * 60:
            return 'error: pre-submitted %s not ready after %d min' % (name, SUBMIT_WAIT_MIN), \
                lambda: fail(dict(st, entry=name, **who(e)), 'pre-submitted %s: v%s %s after %d min' % (name, ver, status, SUBMIT_WAIT_MIN))
        return 'wait: pre-submitted %s is v%s %s; Live stays pinned to v%d' % (name, ver, status or 'not listed yet', live), None
    if soft:
        return 'wait before activating v%d (%s, ready): %s' % (ver, name, '; '.join(soft)), None

    def go():
        hard, soft = check_submit(n)                 # the same command as the activation: nothing changed in between
        if hard or soft:
            raise Fail('re-check before the activation: %s' % '; '.join(hard + soft))
        if platform_version(subs(), p['after']) != (ver, status):
            raise Fail('re-check before the activation: v%d of %s is no longer the newest %s version' % (ver, name, status))
        if reuse:
            take_reuse(st, e, name, n, reuse)
        st.update(phase='submitted', entry=name, **who(e), ar=e['autoread'], spec=n['spec'], family=e['family'], proj=p['proj'], bot=e['bot'],
                  base=e['base'], base_src=rq.src_hash(os.path.join(p['proj'], e['base'])), live_bot=lv['bot'], live_version=lv['version'],
                  old_version=live, told=None, reuse=reuse[0] if reuse else None, version='v%d' % ver, pinned=True, submit_at=now())
        st.pop('pre', None)
        save(st)
        out = activate(ver)
        st['submit_at'] = now()                       # pinned: the version is live from its activation
        log(st, 'autoship %s: v%d activated (pre-submitted, %s)' % (name, ver, status), 'frozen copy %s/%s (src %s / %s) on base %s %s; %s' % (
            p['proj'], e['bot'], e['src'], e['gate']['lab'], lv['bot'], lv['version'], out))
        save(st)
    return 'activate v%d = %s (pre-submitted, %s), base %s = live %s%s' % (ver, name, status, e['base'], lv['version'],
                                                                         '; base reuse of %s (%s)' % reuse if reuse else ''), go


def plan_submit(st, n, reuse=None):
    if pin_mode():
        return plan_submit_pinned(st, n, reuse)
    e, name = n['entry'], n['name']
    hard, soft = check_submit(n)
    if hard:
        return 'error before the submit of %s: %s' % (name, '; '.join(hard)), lambda: fail(dict(st, entry=name, **who(e)), '; '.join(hard))
    if soft:
        return 'wait before the submit of %s: %s' % (name, '; '.join(soft)), None
    lv = rq.live()

    def go():
        hard, soft = check_submit(n)                 # the same command as the submit: nothing changed in between
        if hard or soft:
            raise Fail('re-check before the submit: %s' % '; '.join(hard + soft))
        if reuse:
            take_reuse(st, e, name, n, reuse)
        proj = freeze(name, e['bot'])
        freeze(name, e['base'])
        prove_frozen(proj, e['bot'], e['src'])
        base_src = rq.src_hash(os.path.join(proj, e['base']))
        old = vnum(lv['version'])
        st.update(phase='submitting', entry=name, **who(e), ar=e['autoread'], spec=n['spec'], family=e['family'], proj=proj, bot=e['bot'],
                  base=e['base'], base_src=base_src, live_bot=lv['bot'], live_version=lv['version'], old_version=old, told=None,
                  reuse=reuse[0] if reuse else None)
        save(st)
        out = submit(proj, e['bot'], 'autoship %s src %s' % (name, e.get('lab') or e['gate']['lab']))
        st.update(phase='submitted', submit_at=now())
        log(st, 'autoship %s: submitted' % name, 'frozen copy %s/%s (src %s / %s) on base %s %s; %s' % (
            proj, e['bot'], e['src'], e.get('lab') or e['gate']['lab'], lv['bot'], lv['version'], out.strip().splitlines()[-1] if out.strip() else '')
            + ('; merged by diff from %s on %s' % (e['rebased_from']['bot'], e['rebased_from']['base']) if e.get('rebased_from') else ''))
        save(st)
    return 'submit %s: frozen copy of %s (src %s), base %s = live %s%s' % (name, e['bot'], e['src'], e['base'], lv['version'],
                                                                         '; base reuse of %s (%s)' % reuse if reuse else ''), go


def plan_submitted(st):
    if st.get('pinned'):                        # activated: wait until the platform plays it
        ver, a = vnum(st['version']), act_ver(subs())
        status = 'active' if a == ver else 'activated, the platform still plays v%s' % a
    else:
        ver, status = platform_version(subs(), st['old_version'])
    if ver is None or status != 'active':
        if now() - st['submit_at'] > SUBMIT_WAIT_MIN * 60:
            return 'error: no active new version %d min after the submit' % SUBMIT_WAIT_MIN, \
                lambda: fail(st, 'submitted %s: newest version %s status %s after %d min' % (st['entry'], ver, status, SUBMIT_WAIT_MIN))
        return 'wait: the submitted build is v%s %s' % (ver, status or 'not listed yet'), None
    if now() - st['submit_at'] < NEW_DELAY:
        return 'wait: v%d is active; the NEW half starts %d s after the submit' % (ver, NEW_DELAY), None
    spec, fam, t = st['spec'], st['family'], iso(st['submit_at'])

    def start_new():
        st.update(version='v%d' % ver)
        u1 = unit_start('%s-new' % st['entry'], st['card'], '%s/%s_T.log' % (rq.PLAT, spec['new']),
                        ['sh', RELSETS, 'v%d' % ver, t, spec['new'], fam])
        u2 = unit_start('%s-read' % st['entry'], st['card'], '%s/%s.md' % (VERD, st['ar']), [PY, '-I', AR, 'run', st['ar']])
        st.update(phase='new', new_unit=u1, read_unit=u2, new_at=now())
        log(st, 'autoship %s: v%d live, NEW half and autoread started' % (st['entry'], ver),
            'release_sets.sh v%d %s %s %s; autoread.py run %s (units %s, %s)' % (ver, t, spec['new'], fam, st['ar'], u1, u2))
        save(st)
    return 'start the NEW half of %s (v%d, submitted %s) and autoread run %s' % (st['entry'], ver, t, st['ar']), start_new


def plan_new(st):
    v = verdict(st['ar'], st['new_at'])
    if v is None:
        if now() - st['new_at'] > NEW_MAX_H * 3600:
            return 'error: no verdict %d h after the submit' % NEW_MAX_H, lambda: fail(st, 'no verdict for %s %d h after the submit' % (st['ar'], NEW_MAX_H))
        if not unit_running(st['read_unit']):
            return 'error: autoread ended without a verdict', lambda: fail(st, 'autoread unit %s ended without a verdict file' % st['read_unit'])
        waiting = 'wait: %s playing, autoread %s waiting for it' % (st['spec']['new'], st['ar'])
        if st.get('pinned') and pin_mode():         # pre-build the next candidate on this one (owner 28 Oct)
            n = after_flight(st)
            e2 = n.get('entry') or {}
            if n.get('name') and e2.get('gate') and e2.get('base') == st['bot'] and os.path.isdir(os.path.join(REPO, e2['bot'])) and \
                    not [x for x in rq.switch_check(os.path.join(REPO, e2['bot']), e2.get('switches') or {}) if x[2] != [x[1]]] and \
                    not ((st.get('pre') or {}).get('entry') == n['name'] and st['pre'].get('src') == e2['src']):
                what, go = plan_presubmit(st, n, vnum(st['version']))

                def pre_safe():                 # a failed pre-submit never touches the release in flight
                    try:
                        go()
                    except Fail as ex:
                        st['pre'] = dict(entry=n['name'], src=e2['src'], failed=str(ex), at=now())
                        log(dict(st, card=e2.get('card')), 'autoship %s: pre-submit failed during the NEW half of %s' % (n['name'], st['entry']),
                            '%s; it is submitted again from idle' % ex)
                        save(st)
                return '%s, during the NEW half of %s' % (what, st['entry']), pre_safe
        return waiting, None
    vf = '%s/%s.md' % (VERD, st['ar'])
    if v == 'KEEP':
        def keep():
            rc, out = run_cmd([PY, '-I', RQ, 'done', st['entry'], '--result', 'KEEP', '--version', st['version'], '--by', WHO])
            if rc:
                raise Fail('relqueue.py done %s KEEP failed: %s' % (st['entry'], out.strip()[-300:]))
            pin = ''
            if st.get('pinned'):                    # activate the live version after each act
                s = subs()
                pin = '; pinned v%s' % act_ver(s) if pinned_to(s, vnum(st['version'])) else '; %s, then pinned: %s' % (sel_text(s), activate(vnum(st['version'])))
            log(st, 'autoship %s: KEEP, %s stays live' % (st['entry'], st['version']), 'verdict %s; %s%s' % (vf, out.strip().splitlines()[-1], pin))
            reset(st)
        return 'act on KEEP: relqueue.py done %s --result KEEP --version %s' % (st['entry'], st['version']), keep
    if v == 'REVERT' or v.startswith('REVERT') or v == 'NEEDS REVIEW':
        busy = rq.playing()
        if busy:
            st.setdefault('revert_wait', now())
            if now() - st['revert_wait'] > REVERT_WAIT_H * 3600:
                return 'error: base resubmit held %d h by playing sets' % REVERT_WAIT_H, lambda: fail(st, 'verdict %s; base not resubmitted: sets playing %s' % (v, ', '.join(busy)))
            return 'wait: verdict %s, base resubmit waits for playing sets %s' % (v, ', '.join(busy)), (lambda: save(st))

        def revert():
            if st.get('pinned'):                    # the base version is still built: activate it, no resubmit
                p = st.get('pre') or {}
                if p.get('base') == st['bot']:
                    log(st, 'autoship %s: pre-submitted %s dropped' % (st['entry'], p['entry']), 'its base %s is reverted' % st['bot'])
                    st.pop('pre', None)
                out = activate(vnum(st['live_version']))
                st.update(phase='reverting', verdict=v, revert_at=now())
                log(st, 'autoship %s: %s, base %s activated' % (st['entry'], v, st['live_version']), 'verdict %s; %s' % (vf, out))
                save(st)
                return
            out = submit(st['proj'], st['base'], 'autoship revert %s to %s' % (st['entry'], st['live_version']))
            st.update(phase='reverting', verdict=v, revert_at=now())
            log(st, 'autoship %s: %s, base resubmitted' % (st['entry'], v), 'frozen %s/%s (src %s); verdict %s; %s' % (
                st['proj'], st['base'], st['base_src'], vf, out.strip().splitlines()[-1] if out.strip() else ''))
            save(st)
        return 'act on %s: %s' % (v, 'activate the base version %s' % st['live_version'] if st.get('pinned') else
                                  'resubmit the frozen base %s/%s' % (st['proj'], st['base'])), revert
    return 'error: verdict %s' % v, lambda: fail(st, 'autoread %s: %s (%s)' % (st['ar'], v, vf))


def plan_reverting(st):
    if st.get('pinned'):
        ver, a = vnum(st['live_version']), act_ver(subs())
        status = 'active' if a == ver else 'activated, the platform still plays v%s' % a
    else:
        ver, status = platform_version(subs(), vnum(st['version']))
    if ver is None or status != 'active':
        if now() - st['revert_at'] > SUBMIT_WAIT_MIN * 60:
            return 'error: resubmitted base not active', lambda: fail(st, 'base resubmit: newest version %s status %s after %d min' % (ver, status, SUBMIT_WAIT_MIN))
        return 'wait: the resubmitted base is v%s %s' % (ver, status or 'not listed yet'), None
    res = 'REVERT' if st['verdict'].startswith('REVERT') else 'REVERT (NEEDS REVIEW)'

    def done():
        try:
            build_time('v%d' % ver)
        except Fail:                            # release_sets.sh records only versions it plays; the next BASE half needs this one
            open(BUILDS, 'a').write('%s v%d\n' % (iso(st['revert_at']), ver))
        rc, out = run_cmd([PY, '-I', RQ, 'done', st['entry'], '--result', res, '--version', st['version'], '--live-version', 'v%d' % ver, '--by', WHO])
        if rc:
            raise Fail('relqueue.py done %s %s failed: %s' % (st['entry'], res, out.strip()[-300:]))
        if res != 'REVERT':
            for c in cards(st):
                board('next', c, 'read the verdict', '--by', 'review', '--deliverable', '%s/%s.md' % (VERD, st['ar']),
                      '--stop', 'the base stays, or the entry goes back in the queue with a fix')
        log(st, 'autoship %s: %s done, base live as v%d' % (st['entry'], res, ver), out.strip().splitlines()[-1] if out.strip() else '')
        reset(st)
    return 'record %s: relqueue.py done %s --result %s --live-version v%d' % (res, st['entry'], res, ver), done


def reset(st):
    hist, pre = st.get('history', [])[-40:], st.get('pre')
    st.clear()
    st.update(phase='idle', history=hist)
    if pre:                                     # a pre-submitted head outlives the release it was built during
        st['pre'] = pre
    save(st)


def fail(st, why):
    """Resubmit the frozen base if the new build may be live and it can, block the card, write autoship.off, stop."""
    note = ''
    landed = True
    if st.get('phase') == 'submitting':         # did the submit reach the platform?
        try:
            landed = platform_version(subs(), st['old_version'])[0] is not None
        except Fail:
            pass
    if st.get('pinned') and st.get('phase') in ('submitted', 'new'):
        busy = rq.playing()
        if busy:
            note = 'base %s NOT activated (sets playing: %s)' % (st.get('live_version'), ', '.join(busy))
        else:
            try:
                note = 'base %s activated: %s' % (st.get('live_version'), activate(vnum(st.get('live_version'))))
            except Fail as ex:
                note = 'base activation FAILED: %s' % ex
    elif st.get('phase') in ('submitting', 'submitted', 'new') and st.get('proj') and st.get('base') and not landed:
        note = 'nothing reached the platform: %s stays live' % st.get('live_version')
    elif st.get('phase') in ('submitting', 'submitted', 'new') and st.get('proj') and st.get('base'):
        busy = rq.playing()
        if busy:
            note = 'base NOT resubmitted (sets playing: %s)' % ', '.join(busy)
        else:
            try:
                submit(st['proj'], st['base'], 'autoship error revert %s' % st['entry'])
                note = 'frozen base %s/%s resubmitted' % (st['proj'], st['base'])
            except Fail as ex:
                note = 'base resubmit FAILED: %s' % ex
    elif st.get('phase') == 'reverting':
        note = 'base already resubmitted'
    for c in cards(st):
        board('block', c, '--on', 'input', '--why', 'autoship stopped: %s %s' % (why, note))
    os.makedirs(STATE, exist_ok=True)
    open(OFF, 'w').write('%s autoship stopped: %s %s\n' % (iso(), why, note))
    st.update(phase='stopped', error='%s %s' % (why, note), stopped_at=iso())
    log(st, 'autoship STOPPED on %s' % (st.get('entry') or 'the queue'), '%s %s; autoship.off written, the coordinator fixes and re-arms' % (why, note))
    save(st)
    return 1


STEPPED = []                                    # set by tick_step when its step changed the phase


def tick(dry):
    t0 = time.time()
    del STEPPED[:]
    rc = tick_step(dry)
    if dry or os.path.exists(OFF):
        return rc
    s1 = load()
    ph1, p1 = s1.get('phase', 'idle'), s1.get('pre') or {}
    if ph1 in ('submitted', 'reverting') or (p1 and not p1.get('failed') and (ph1 == 'idle' or ph1 == 'base' and set_done(s1['spec']['base']))):
        kick(poll=True)                         # waiting on the platform: look again in POLL_S
    try:
        late = os.path.getmtime(KICK) >= t0 - 1  # a unit's kick during this tick was merged into it (file times are coarse)
    except OSError:
        late = False
    if STEPPED or late:
        kick()                                  # the next step may be due at once
    return rc


def tick_step(dry):
    os.makedirs(STATE, exist_ok=True)
    if os.path.exists(OFF) and not dry:
        print('off: ' + open(OFF).read().strip())
        return 0
    lk = open(LOCK, 'w')
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('another tick holds the lock')
        return 0
    st = load()
    try:
        what, act = plan(st)
    except Exception as ex:                     # bind the text now: Python unbinds ex when the block ends
        why = str(ex) if isinstance(ex, Fail) else 'unexpected %s at plan time: %s' % (type(ex).__name__, ex)
        what, act = 'error: ' + why, (lambda: fail(st, why))
    if dry:
        print('%sDRY RUN (phase %s): a tick would %s' % ('[autoship.off present] ' if os.path.exists(OFF) else '', st.get('phase', 'idle'),
                                                        what if not what.startswith(('wait', 'error')) else '-> ' + what))
        return 0
    if act is None:
        print(what)
        return 0
    ph0 = st.get('phase', 'idle')
    try:
        rc = act() or 0
        if not rc and load().get('phase', 'idle') != ph0:
            STEPPED.append(ph0)                 # a step taken, not a note while waiting
        return rc
    except Fail as ex:
        return fail(st, str(ex))
    except Exception as ex:
        return fail(st, 'unexpected %s: %s' % (type(ex).__name__, ex))


# ---- the timer -------------------------------------------------------------------------------------------------------

SERVICE = """[Unit]
Description=autoship tick: ships the head of the release queue (owner-prompts section 7)
ConditionHost=%s

[Service]
Type=oneshot
WorkingDirectory=%s
Nice=10
Environment=PATH=%s
ExecStart=%s -I %s/tools/lab/autoship.py tick
"""
TIMER = """[Unit]
Description=autoship every 5 minutes

[Timer]
OnActiveSec=1min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
"""


KICK_TIMER = """[Unit]
Description=autoship tick %d s after a kick (autoship.py kick)

[Timer]
OnActiveSec=%ds
AccuracySec=1s
Unit=autoship.service
"""


def systemctl(*a):
    return run_cmd(['systemctl', '--user'] + list(a), timeout=120)


def touch(f):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    open(f, 'a').close()
    os.utime(f, None)


def kick_units():
    """Write autoship-soon.timer and autoship-poll.timer if missing (an arm before 28 Oct wrote neither); True if written."""
    new = False
    for name, s in (('soon', SOON_S), ('poll', POLL_S)):
        f = '%s/autoship-%s.timer' % (UNIT_DIR, name)
        if not os.path.exists(f) or open(f).read() != KICK_TIMER % (s, s):
            os.makedirs(UNIT_DIR, exist_ok=True)
            open(f + '.tmp', 'w').write(KICK_TIMER % (s, s))
            os.replace(f + '.tmp', f)
            new = True
    return new


def kick(poll=False):
    """(Re)start the one-shot timer that starts autoship.service in SOON_S (or POLL_S) s. A start request that reaches the
    service while a tick runs is merged into that run, so a soon-kick also stamps KICK, and the running tick starts one
    more on its way out. Nothing while disarmed or stopped: a hand ship never gets an automatic tick."""
    if os.path.exists(OFF) or not armed():
        return 'not armed: no kick'
    if not poll:
        touch(KICK)
    if kick_units():
        systemctl('daemon-reload')
    t = 'autoship-%s.timer' % ('poll' if poll else 'soon')
    rc, out = systemctl('restart', t)
    return 'kick: %s in %d s' % (t, POLL_S if poll else SOON_S) if not rc else 'kick %s failed: %s' % (t, out.strip()[-200:])


def armed():
    return systemctl('is-active', 'autoship.timer')[1].strip() == 'active'


def arm(a):
    st = load()
    if st.get('phase') == 'stopped' and '--reset' not in a:
        sys.exit('stopped by an error: %s\nfix it, then autoship.py arm --reset' % st.get('error'))
    if not rq.live() or not rq.live().get('version'):
        sys.exit('the live build is not recorded: relqueue.py live --set bots/DIR --version vNNN --why TEXT')
    try:
        build_time(rq.live()['version'])
    except Fail as ex:                          # a base resubmitted on an error path is not in builds.txt yet
        sys.exit('%s: add "ISO-UTC-submit-time %s" to it first' % (ex, rq.live()['version']))
    if st.get('phase') == 'stopped':
        reset(st)
    os.makedirs(UNIT_DIR, exist_ok=True)
    open(UNIT_DIR + '/autoship.service', 'w').write(SERVICE % (socket.gethostname(), REPO, os.environ.get('PATH', '/usr/bin:/bin'), PY, REPO))
    open(UNIT_DIR + '/autoship.timer', 'w').write(TIMER)
    kick_units()
    for c in (('daemon-reload',), ('enable', '--now', 'autoship.timer')):
        rc, out = systemctl(*c)
        if rc:
            sys.exit('systemctl --user %s: %s' % (' '.join(c), out))
    if os.path.exists(OFF):
        os.remove(OFF)
    lr('autoship armed', 'timer every 5 min on %s only; phase %s' % (socket.gethostname(), load().get('phase')))
    print('armed: %s' % systemctl('list-timers', 'autoship.timer')[1].strip())


def disarm(a):
    rc, out = systemctl('disable', '--now', 'autoship.timer')
    systemctl('stop', 'autoship-soon.timer', 'autoship-poll.timer')
    lr('autoship disarmed', 'phase %s; units already started run on' % load().get('phase'))
    print('disarmed' if not rc else out)


def status(a):
    st = load()
    print('timer: %s' % ('armed' if armed() else 'not armed'))
    print('autoship.off: %s' % (open(OFF).read().strip() if os.path.exists(OFF) else 'absent'))
    print('phase: %s%s' % (st.get('phase', 'idle'), ' (%s, card %s)' % (st.get('entry'), st.get('card')) if st.get('entry') else ''))
    print('pin mode: %s' % ('on (%s)' % open(PIN).read().strip() if pin_mode() else 'off'))
    if st.get('pre'):
        print('pre-submitted: %s' % ', '.join('%s=%s' % (k, st['pre'][k]) for k in ('entry', 'src', 'after', 'failed') if k in st['pre']))
    if st.get('error'):
        print('error: ' + st['error'])
    for h in st.get('history', [])[-5:]:
        print('  ' + h)
    lv = rq.live()
    print('live: %s' % ('%s %s (since %s)' % (lv['bot'], lv['version'], lv['since']) if lv else 'not recorded'))
    try:
        n = queue_next()
        print('head: %s%s%s' % (n.get('name') or 'none', '' if not n.get('name') else ' (gate %s)' % ('passed' if n['entry'].get('gate') else 'none: by hand only'),
                                ''.join('\n  - ' + t for k, t in n.get('problems', []))))
    except Fail as ex:
        print('head: %s' % ex)


# ---- pin mode ---------------------------------------------------------------------------------------------------------

def hold_idle():
    """The tick lock, held until exit, with phase idle and no set playing: pin commands never race a tick."""
    lk = open(LOCK, 'w')
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit('a tick holds the lock: try again in a minute')
    st = load()
    if st.get('phase', 'idle') != 'idle' or st.get('pre'):
        sys.exit('phase %s%s: pin commands run between releases only' % (st.get('phase'), ', a pre-submitted head' if st.get('pre') else ''))
    busy = rq.playing()
    if busy:
        sys.exit('sets playing (%s): the selection never changes while a set plays' % ', '.join(busy))
    lv = rq.live()
    if not lv or not vnum(lv.get('version')):
        sys.exit('the live build is not recorded with its version')
    return lk, st, lv, vnum(lv['version'])


def trial_note(what, s=None):
    os.makedirs(STATE, exist_ok=True)
    top = sorted(s.get('submissions', []), key=lambda x: -x.get('version', 0))[:3] if s else []
    line = '%s %s%s' % (iso(), what, ' | %s | newest %s' % (sel_text(s), [(x.get('version'), x.get('status')) for x in top]) if s else '')
    open(TRIAL, 'a').write(line + '\n')
    print(line)


def await_platform(test, minutes, what):
    """Poll the platform until test(s) is True (returns s) or a string (an error); Fail after `minutes`."""
    t0 = now()
    while True:
        s = subs()
        r = test(s)
        if r is True:
            trial_note(what + ': yes', s)
            return s
        if r:
            trial_note(what + ': ' + r, s)
            raise Fail('%s: %s (%s)' % (what, r, sel_text(s)))
        if now() - t0 > minutes * 60:
            trial_note(what + ': timed out', s)
            raise Fail('%s: not after %d min (%s)' % (what, minutes, sel_text(s)))
        time.sleep(TRIAL_POLL_S)


def trial(a):
    """The supervised pin trial (card pin): every answer to state/pin_trial.txt; PASS writes state/autoship.pin."""
    lk, st, lv, v0 = hold_idle()
    trial_note('pin trial start: live %s v%d' % (lv['bot'], v0))
    s = subs()
    if act_ver(s) != v0:
        sys.exit('the platform plays v%s, live.json says v%d' % (act_ver(s), v0))
    try:
        shipped = [x['src'] for x in json.load(open(rq.Q)) if x['bot'] == lv['bot'] and x.get('result') == 'KEEP']
    except (OSError, ValueError):
        shipped = []
    want = shipped[-1] if shipped else rq.src_hash(os.path.join(REPO, lv['bot']))
    vn, after = None, v0
    try:
        trial_note('activate v%d: %s' % (v0, activate(v0)))
        await_platform(lambda s: pinned_to(s, v0) or None, 3, 'pinned to v%d' % v0)
        proj = freeze('pintrial_%s' % iso().replace(':', ''), lv['bot'])
        prove_frozen(proj, lv['bot'], want)
        after = max([x.get('version', 0) for x in s.get('submissions', [])] + [v0])
        out, how = submit_pinned(proj, lv['bot'], 'autoship pin trial: live v%d resubmitted (src %s)' % (v0, want), v0)
        trial_note('submitted the frozen copy %s/%s (src %s): %s; activate v%d at once: %s' % (
            proj, lv['bot'], want, out.strip().splitlines()[-1] if out.strip() else '', v0, how), subs())

        def built(s):
            if not pinned_to(s, v0):
                return 'Live moved off v%d before the activation' % v0
            v, status = platform_version(s, after)
            if status in FAILED:
                return 'v%s build %s' % (v, status)
            return status in READY or None
        s = await_platform(built, SUBMIT_WAIT_MIN, 'new version ready, Live still v%d' % v0)
        vn = platform_version(s, after)[0]
        if rq.playing():
            raise Fail('a set started during the trial (%s): v%d not activated' % (', '.join(rq.playing()), vn))
        trial_note('activate v%d: %s' % (vn, activate(vn)))
        await_platform(lambda s: pinned_to(s, vn) or None, 5, 'Live switched to v%d' % vn)
        trial_note('activate v%d: %s' % (v0, activate(v0)))
        await_platform(lambda s: pinned_to(s, v0) or None, 5, 'Live back on v%d' % v0)
    except Fail as ex:
        back = ''
        try:
            if not pinned_to(subs(), v0) and not rq.playing():
                back = '; v%d activated again: %s' % (v0, activate(v0))
        except Fail as ex2:
            back = '; re-activating v%d FAILED: %s' % (v0, ex2)
        s = subs()
        trial_note('pin trial FAIL: %s%s' % (ex, back), s)
        pv, pst = platform_version(s, after)
        vn = vn or pv
        now_ = ('the selection is pinned to v%d (autoship refuses to submit while it is: the coordinator decides' % v0 if pinned_to(s, v0) else
                'the selection is NOT pinned to v%d: %s (the coordinator decides' % (v0, sel_text(s)))
        then = ('pin off ("activate latest") keeps v%d live: the trial copy v%s is %s' % (v0, vn, pst) if vn and vn == pv and pst in FAILED else
                'activate latest would put the trial copy%s, same source, live' % (' v%s' % vn if vn else ''))
        lr('pin trial FAIL', '%s%s; pin mode stays off; %s; %s). Answers: %s' % (ex, back, now_, then, TRIAL))
        sys.exit(1)
    open(PIN, 'w').write('%s trial PASS: v%d pinned, v%d (same source) built while Live stayed, switched, switched back\n' % (iso(), v0, vn))
    trial_note('pin trial PASS: pin mode on')
    lr('pin trial PASS: pin mode on', 'live v%d pinned; resubmitted copy v%d reached %s while Live stayed v%d, activation switched Live, v%d '
                                      'activated again. Answers: %s' % (v0, vn, platform_version(subs(), after)[1], v0, v0, TRIAL))


def pin(a):
    if not a or a[0] not in ('on', 'off'):
        sys.exit('autoship.py pin on|off')
    lk, st, lv, v0 = hold_idle()
    if a[0] == 'on':
        print('activate v%d: %s' % (v0, activate(v0)))
        s = subs()
        if not pinned_to(s, v0):
            sys.exit('not pinned after the activation: %s' % sel_text(s))
        open(PIN, 'w').write('%s pin on by hand: v%d\n' % (iso(), v0))
        lr('autoship pin mode on', 'selection pinned to live v%d' % v0)
        return
    s = subs()
    v, status = platform_version(s, v0)
    if v is not None and status not in FAILED:
        sys.exit('v%s (%s) is newer than live v%d: "activate latest" would put it live' % (v, status, v0))
    print('activate latest: %s' % activate('latest'))
    s = subs()
    v, status = platform_version(s, v0)
    if v is not None and status not in FAILED:     # "latest" queued a cancelled version again: it would go live once built
        back = activate(v0)
        sys.exit('after "activate latest": v%s is %s and would go live once built; v%d activated again (%s): %s' % (
            v, status, v0, back, sel_text(subs())))
    if act_ver(s) != v0 or s.get('pinned'):
        sys.exit('after "activate latest": %s (wanted v%d, unpinned)' % (sel_text(s), v0))
    if os.path.exists(PIN):
        os.remove(PIN)
    lr('autoship pin mode off', 'selection follows the newest ready version again; live v%d (%s)' % (v0, sel_text(s)))


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ('tick', 'status', 'arm', 'disarm', 'kick', 'trial', 'pin'):
        sys.exit(__doc__)
    if a[0] == 'tick':
        sys.exit(tick('--dry-run' in a))
    if a[0] == 'kick':
        print(kick('--poll' in a))
        return
    {'status': status, 'arm': arm, 'disarm': disarm, 'trial': trial, 'pin': pin}[a[0]](a[1:])


if __name__ == '__main__':
    main()
