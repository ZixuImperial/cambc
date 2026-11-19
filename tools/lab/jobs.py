"""jobs.py - a job record written before the job starts, so a restart can reconcile instead of guessing (cambc-4e, 27 Oct).

Why: the 20:14 restart on 27 Oct stopped readers and background commands; nobody could tell which had finished, which
still ran outside the sessions and which needed redoing, so work was both lost and run twice. Launch through `run`: it
records the command, host, bot source hashes, output and recovery note in jobs.jsonl, then runs the command and records
its exit status. After a restart, `reconcile` comes first; launch replacements only for LOST jobs.

  jobs.py run --card ID --name NAME --out PATH [--recover TEXT] [--games N] [--as S] -- CMD ARG...
      Use it as the background Bash command itself (keeps CMD's exit status; prefix nice -n 10 for bulk work).
      Condor: name the cluster in --recover ("condor_q 681; results in ...").
  jobs.py reconcile [--hours 48]
      DONE / FAILED (exit status recorded), RUNNING (the recorded pid is alive and still this job), LOST (no exit
      status and no process: the session or machine died; the recovery note says how to redo it), and UNREAD (ended
      after the card's last board entry: results nobody has analysed yet).
  jobs.py reconcile --plain             one line per job (brief.py reads this)
  jobs.py list [--hours 48]
State: reports/state/jobs.jsonl (append-only; one start and one end line per job)."""
import hashlib, json, os, re, socket, subprocess, sys
from datetime import datetime, timedelta, timezone

REPO = '/homes/USER/cambc'
ST = os.environ.get('BOARD_STATE') or '/homes/USER/condor-work/reports/state'
J, B = ST + '/jobs.jsonl', ST + '/board.json'


def ts():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def when(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)


def append(r):
    with open(J, 'a') as f:                     # one short line per write: O_APPEND keeps concurrent writers whole
        f.write(json.dumps(r) + '\n')


def opt(a, k, d=None):
    if k in a:
        i = a.index(k)
        v = a[i + 1]
        del a[i:i + 2]
        return v
    return d


def bot_hashes(cmd):
    """Source hash of every bots/ dir the command names (the same files relqueue.py hashes)."""
    out = {}
    for tok in cmd:
        name = tok.split('/')[-1] if tok.startswith('bots/') else tok
        d = os.path.join(REPO, 'bots', name)
        if re.fullmatch(r'[\w.-]+', name or '') and os.path.isdir(d):
            h = hashlib.sha256()
            for root, dirs, files in os.walk(os.path.realpath(d)):
                dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
                for f in sorted(files):
                    if re.search(r'\.(cpp|h|hpp|c|cc|toml|json|txt)$', f):
                        p = os.path.join(root, f)
                        h.update(os.path.relpath(p, d).encode() + b'\0' + open(p, 'rb').read())
            out[name] = h.hexdigest()[:12]
    return out


def records(hours):
    starts, ends = {}, {}
    try:
        for l in open(J):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            (starts if r['ev'] == 'start' else ends)[r['job']] = r
    except FileNotFoundError:
        pass
    cut = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [(r, ends.get(j)) for j, r in starts.items() if when(r['t']) >= cut], starts


def alive(r):
    if r.get('host') != socket.gethostname():
        return None                             # another machine: cannot tell from here
    try:
        cl = open('/proc/%d/cmdline' % r['pid'], 'rb').read().decode(errors='replace')
    except OSError:
        return False
    return 'jobs.py' in cl and '\0--name\0%s\0' % r['name'] in cl    # pid reused by something else = gone


def state(r, e):
    if e:
        return 'DONE' if e['rc'] == 0 else 'FAILED'
    a = alive(r)
    return 'RUNNING' if a else ('ELSEWHERE' if a is None else 'LOST')


def last_board(card):
    try:
        for c in json.load(open(B))['cards']:
            if c['id'] == card:
                h = [x['t'] for x in c['history'] if x['by'] != 'sync']     # board.py's sync notes are not a reading
                return h[-1] if h else c['created']
    except (OSError, ValueError, KeyError):
        pass
    return None


def run(a):
    if '--' not in a:
        sys.exit('run needs -- CMD')
    i = a.index('--')
    a, cmd = a[:i], a[i + 1:]
    card, name, out = opt(a, '--card'), opt(a, '--name'), opt(a, '--out')
    if not (card and name and out and cmd):
        sys.exit('run needs --card, --name, --out and -- CMD')
    job = '%s.%s.%d' % (name, datetime.now(timezone.utc).strftime('%m%d%H%M%S'), os.getpid())
    append({'ev': 'start', 'job': job, 't': ts(), 'card': card, 'name': name, 'out': out, 'cmd': cmd,
            'cwd': os.getcwd(), 'host': socket.gethostname(), 'pid': os.getpid(), 'by': opt(a, '--as', '?'),
            'recover': opt(a, '--recover', ''), 'games': int(opt(a, '--games', '0')), 'bots': bot_hashes(cmd)})
    os.environ['LAB_JOB'] = job                 # the command can stamp its own output with the job id
    try:
        rc = subprocess.call(cmd)
    except KeyboardInterrupt:
        rc = 130
    except OSError as ex:
        print(ex, file=sys.stderr)
        rc = 127
    append({'ev': 'end', 'job': job, 't': ts(), 'rc': rc})
    sys.exit(rc)


def short(p):
    for a, b in (('/homes/USER/condor-work/', 'condor-work/'), (REPO + '/', ''), ('/homes/USER/', '~/')):
        if p and p.startswith(a):
            return b + p[len(a):]
    return p or ''


def dur(sec):
    m = sec / 60
    if m < 1:
        return 'under a minute'
    return '%d min' % m if m < 90 else ('%.1f h' % (m / 60) if m < 2880 else '%.0f days' % (m / 1440))


def clock(s):
    t = when(s)
    return t.strftime('%H:%M') if t.date() == datetime.now(timezone.utc).date() else t.strftime('%d %b %H:%M')


def timing(r, e):
    if e:
        return 'started %s, ran %s, ended %s ago' % (clock(r['t']), dur((when(e['t']) - when(r['t'])).total_seconds()),
                                                     dur((datetime.now(timezone.utc) - when(e['t'])).total_seconds()))
    return 'started %s, %s so far' % (clock(r['t']), dur((datetime.now(timezone.utc) - when(r['t'])).total_seconds()))


HEAD = {'LOST': 'Lost: no end recorded and no process left (the session or machine died). Check the output, then redo it',
        'UNREAD FAILED': 'Failed, and nobody has looked since: read the output, then note the card',
        'UNREAD DONE': 'Finished, and nobody has looked since: read the output, then note the card',
        'RUNNING': 'Running: nothing to do',
        'ELSEWHERE': 'Started on another machine: check there',
        'FAILED': 'Failed, already looked at', 'DONE': 'Finished, already looked at'}
ORDER = ['LOST', 'UNREAD FAILED', 'UNREAD DONE', 'RUNNING', 'ELSEWHERE', 'FAILED', 'DONE']


def main(a):
    if not a or a[0] in ('-h', '--help'):
        sys.exit(__doc__)
    cmd, a = a[0], a[1:]
    if cmd == 'run':
        return run(a)
    hours = float(opt(a, '--hours', '48'))
    rs, _ = records(hours)
    if cmd == 'list':
        print('%-9s %-22s %-24s %-14s %s' % ('STATE', 'WHEN', 'JOB', 'CARD', 'BY'))
        for r, e in rs:
            s = state(r, e)
            t = clock(r['t']) + (' +' + dur((when(e['t']) - when(r['t'])).total_seconds()) if e else ' (running)' if s == 'RUNNING' else '')
            print('%-9s %-22s %-24s %-14s %s' % (s.lower(), t, r['name'], r['card'], r['by']))
            print('          $ %s' % ' '.join(r['cmd'])[:110])
        return
    if cmd != 'reconcile':
        sys.exit(__doc__)
    groups = {}
    for r, e in rs:
        s = state(r, e)
        if s in ('DONE', 'FAILED'):
            lb = last_board(r['card'])
            if lb is None or when(lb) <= when(e['t']):
                s = 'UNREAD ' + s
        groups.setdefault(s, []).append((r, e))
    if '--plain' in a:                          # one line per job, for brief.py
        for s in ORDER:
            for r, e in groups.get(s, []):
                print('%-13s %-28s card %-18s started %s by %s -> %s' % (s, r['name'], r['card'], r['t'][5:16], r['by'], short(r['out'])))
        return
    if not rs:
        print('No jobs recorded in the last %g h.' % hours)
        return
    print('Jobs in the last %g h, most urgent first (jobs.py list for the commands)' % hours)
    for s in ORDER:
        g = groups.get(s, [])
        if not g:
            continue
        print('\n%s (%d)' % (HEAD[s], len(g)))
        for r, e in g:
            rc = ', exit code %d' % e['rc'] if e and e['rc'] else ''
            print('  %-24s card %-14s by %-18s %s%s' % (r['name'], r['card'], r['by'], timing(r, e), rc))
            if s in ('DONE', 'FAILED'):
                continue
            print('      output: %s' % short(r['out']))
            if s == 'LOST':
                print('      redo:   %s' % (r['recover'] or ' '.join(r['cmd'])))
            if s == 'ELSEWHERE':
                print('      host:   %s' % r['host'])


if __name__ == '__main__':
    main(sys.argv[1:])
