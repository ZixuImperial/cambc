"""board.py - the lab's task board: one card per candidate idea, its stage, owner and next action (cambc-4e, 27 Oct).

Why: on 26-27 Oct the build session ran up to eight agents on overlapping ideas at once. One Prism agent made 813 tool
calls in 3.8 h without a report; "we need a diagnostic trace" went round three sessions with nobody running it; the
build session made 95 message calls, mostly status. The board replaces status messages, holds at most two candidates
in implementing+testing (ADR 0010), and every card names who acts next.

What the limit covers: implementing = building the change on the release base; testing = the decisive read or the live
sets for a release (a release train is one card). Screening an idea locally (abl/sprt/Condor screens) is investigating:
not limited, but held to the card's games budget (--budget GAMES, counted from jobs.py --games).
Fast lane (owner 28 Oct, ADR 0010): on top of the two slots, econ, combat and experiments may each have one small change
(one switch or a few constants) in flight (implementing, testing or ready), marked --lane fast with that role as --owner.
It does not use a slot; a second one from the same role is refused (--over REASON), and lint flags one that slips through.
A fast card that grows into a larger change leaves the lane (link --lane slot) and then needs a slot.
A fast-lane pair (relqueue.py add --lane fast --parts A,B --card IDA --card IDB) is one build and one live read for two
cards from two roles: each card stays its role's one fast-lane item, and sync moves both (ready, released, rejected).
The board keeps itself current: every call first syncs from the release queue (an open entry moves the card to ready;
KEEP -> released, REVERT -> rejected/refuted), autoread verdicts, hypothesis-card observations and jobs.py records
(notes, by 'sync'). Only decisions and next actions are typed by hand. `lint` lists what needs a person.

Stages: proposed -> investigating -> implementing -> testing -> ready -> released | rejected
  (ready = in the release queue: relqueue.py add; released/rejected are decisions, a well-supported rejection counts)
Roles (executors are roles; `role` maps them to the current session names, which change on every restart):
  coordinator (the build session), econ (economy, farming, routing), combat (combat, survival, team play),
  experiments (comparisons, compute budget, reports), review (critic reads, lab tools)

  board.py add ID --title T [--stage proposed] [--over REASON] [--owner ROLE] [--lane fast] [--hypo CARD] [--budget GAMES]
               [--next ACTION --by ROLE --deliverable FILE --stop TEXT] [--as S]
  board.py next ID ACTION --by ROLE --deliverable FILE --stop TEXT [--as S]
      The one next step: who, what file it leaves, when it stops. End every review or read with one.
  board.py move ID STAGE [--why TEXT] [--kind refuted|abandoned|duplicate] [--over REASON] [--as S]
      Into implementing/testing is refused when 2 cards are there already (--over REASON: the owner's or the
      coordinator's call, logged). released/rejected need --why (verdict file or LR:n); rejected needs --kind.
  board.py block ID --on permission|owner|input|compute --why TEXT [--as S]   |   unblock ID [--as S]
  board.py note ID TEXT [--as S]          a finding or a file, one line; not a status ping
  board.py link ID [--relq NAME] [--autoread NAME] [--hypo NAME] [--budget GAMES] [--owner ROLE] [--lane fast|slot] [--over R] [--as S]
      Ties the card to its queue entry, autoread registration and hypothesis cards (a queue entry named like the card
      is linked without this), and sets its games budget for investigating. --lane fast puts the card in the fast lane
      (a queue entry added with relqueue --lane fast does it too); --lane slot takes it out, into the two slots.
  board.py lint                           what needs a person: no next action, deliverable written but no next step,
                                          stale, blocked, over budget, testing with no hypothesis card, a second fast-lane
                                          card from one role or one with no fast-lane owner (review role)
  board.py role [ROLE SESSION]            print or set the role map (one role per session; a session name with its
                                          [ref] when two sessions share a name)
  board.py list [--all] | show ID [--json] | stats [--days 7] | brief (compact lines for brief.py)
State: reports/state/board.json, rendered to board.md after every change. --as names the acting session (or agent)."""
import fcntl, json, os, re, statistics, sys
from datetime import datetime, timedelta, timezone

ST = os.environ.get('BOARD_STATE') or '/homes/zw4424/condor-work/reports/state'      # override for tests
B, MD, LOCK = ST + '/board.json', ST + '/board.md', ST + '/board.lock'
JOBS, STALLS = ST + '/jobs.jsonl', ST + '/stalls.log'
QUEUE, LEDGER, VERD = ST + '/queue.json', ST + '/hypotheses/ledger.tsv', ST + '/verdicts'
REPO = '/homes/zw4424/cambc'
STALE_H = {'implementing': 6, 'testing': 6, 'ready': 12, 'investigating': 24, 'proposed': 72}
STAGES = ['proposed', 'investigating', 'implementing', 'testing', 'ready', 'released', 'rejected']
ACTIVE, DONE = ('implementing', 'testing'), ('released', 'rejected')
ROLES = ['coordinator', 'econ', 'combat', 'experiments', 'review']
WIP = 2
FAST_ROLES, FLIGHT = ('econ', 'combat', 'experiments'), ('implementing', 'testing', 'ready')
KINDS = ('refuted', 'abandoned', 'duplicate')
BLOCKS = ('permission', 'owner', 'input', 'compute')


def now():
    return datetime.now(timezone.utc)


def ts():
    return now().strftime('%Y-%m-%d %H:%M:%S UTC')


def when(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)


def load():
    try:
        return json.load(open(B))
    except FileNotFoundError:
        return {'wip': WIP, 'roles': {r: '' for r in ROLES}, 'cards': []}


def save(b):
    for p, text in ((B, json.dumps(b, indent=1)), (MD, render(b))):
        tmp = '%s.tmp%d' % (p, os.getpid())
        open(tmp, 'w').write(text + '\n')
        os.replace(tmp, p)


def opt(a, k, d=None):
    if k in a:
        i = a.index(k)
        if i + 1 >= len(a):
            sys.exit('%s needs a value' % k)
        v = a[i + 1]
        del a[i:i + 2]
        return v
    return d


def card(b, cid):
    for c in b['cards']:
        if c['id'] == cid:
            return c
    sys.exit('no card %r (board.py list --all)' % cid)


def who(b, role):
    return b['roles'].get(role) or '(unassigned)'


def log(c, by, what):
    c['history'].append({'t': ts(), 'by': by, 'what': what})


def set_next(b, c, a, by):
    action, role = (a[0] if a else None), opt(a, '--by')
    deliv, stop = opt(a, '--deliverable'), opt(a, '--stop')
    if not (action and role and deliv and stop):
        sys.exit('a next action needs ACTION, --by ROLE, --deliverable FILE and --stop TEXT')
    if role not in ROLES:
        sys.exit('--by must be a role: %s' % ', '.join(ROLES))
    c['next'] = {'action': action, 'by': role, 'deliverable': deliv, 'stop': stop, 't': ts()}
    log(c, by, 'next -> %s (%s): %s' % (role, who(b, role), action))


def active(b):
    """The cards in the two slots (fast-lane cards do not take one)."""
    return [c for c in b['cards'] if c['stage'] in ACTIVE and c.get('lane') != 'fast']


def fast(b, owner=None, but=None):
    """Fast-lane cards in flight (implementing, testing or ready), of one owner role if given, other than card `but`."""
    return [c for c in b['cards'] if c.get('lane') == 'fast' and c['stage'] in FLIGHT and c is not but
            and (owner is None or c.get('owner') == owner)]


def fast_refusal(b, c, stage):
    """Why card c may not be a fast-lane card in `stage`, or None."""
    if c.get('owner') not in FAST_ROLES:
        return 'a fast-lane card needs --owner %s (the role whose one fast item it is), not %s' % (
            '|'.join(FAST_ROLES), c.get('owner') or 'none')
    other = fast(b, c['owner'], c)
    if stage in FLIGHT and other:
        return ('fast lane: %s already has %s in flight (one per role). Finish or reject it first, or --over REASON '
                '(the coordinator\'s call).' % (c['owner'], ', '.join(x['id'] for x in other)))
    return None


def wip_refusal(b):
    return ('WIP limit: %s are implementing/testing. Finish or reject one first, or --over REASON '
            '(the owner\'s or coordinator\'s call).' % ', '.join(x['id'] for x in active(b)))


def short(p):
    """A path as people say it: condor-work/..., a repo path, ~/..."""
    for a, b in (('/homes/zw4424/condor-work/', 'condor-work/'), (REPO + '/', ''), ('/homes/zw4424/', '~/')):
        if p and p.startswith(a):
            return b + p[len(a):]
    return p or ''


def dur(sec):
    m = sec / 60
    if m < 1:
        return 'under a minute'
    return '%d min' % m if m < 90 else ('%.1f h' % (m / 60) if m < 2880 else '%.0f days' % (m / 1440))


def ago(t):
    return dur((now() - t).total_seconds()) + ' ago'


def clip(s, n):
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + ' ...'


def facts(b, c):
    f = [c['stage'], 'owner ' + (c.get('owner') or 'none')] + (['fast lane'] if c.get('lane') == 'fast' else [])
    if c.get('budget'):
        f.append('games %d of %s' % (games_used(c, jobrecs()[0]), format(c['budget'], ',')))
    return ' · '.join(f + ['last entry ' + ago(human(c))])


def compact(b, c):
    """One card in a few lines: title, facts, then the block or the next step."""
    n, blk = c.get('next') or {}, c.get('blocked')
    out = ['- **%s**: %s' % (c['id'], c.get('title', '')), '  - ' + facts(b, c)]
    if blk:
        out.append('  - **Blocked** on %s for %s: %s' % (blk['on'], dur((now() - when(blk['t'])).total_seconds()), blk['why']))
    if n:
        out.append('  - Next, by %s: %s -> %s' % (n['by'], clip(n['action'], 160), short(n['deliverable'])))
    elif c['stage'] not in DONE:
        out.append('  - Next: none named')
    return out


def links(c, k):
    return (c.get('links') or {}).get(k, [])


def jobrecs():
    starts, ends = {}, {}
    try:
        for l in open(JOBS):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            (starts if r['ev'] == 'start' else ends)[r['job']] = r
    except OSError:
        pass
    return starts, ends


def games_used(c, starts):
    return sum(r.get('games') or 0 for r in starts.values() if r.get('card') == c['id'])


def sync(b):
    """Fold in what other tools already know; returns True if a card changed. History entries by 'sync'."""
    try:
        q = json.load(open(QUEUE))
    except (OSError, ValueError):
        q = []
    try:
        import csv
        hyp = [r for r in csv.DictReader(open(LEDGER), delimiter='\t') if r.get('kind') == 'obs']
    except OSError:
        hyp = []
    starts, ends = jobrecs()
    changed = False
    for c in b['cards']:
        if c['stage'] in DONE:
            continue
        seen = set(c.setdefault('synced', []))

        def note(key, what):
            nonlocal changed
            if key not in seen:
                seen.add(key)
                c['synced'].append(key)
                log(c, 'sync', what)
                changed = True
        names = set(links(c, 'relq')) | {c['id']}
        ars = set(links(c, 'autoread'))
        for e in q:
            if e.get('name') not in names and c['id'] not in e.get('cards', ()):
                continue            # a fast-lane pair (relqueue --card A --card B) syncs both cards
            if e.get('autoread'):
                ars.add(e['autoread'])
            if e.get('lane') == 'fast' and c.get('lane') != 'fast':
                c['lane'] = 'fast'
                note('q:%s:lane' % e['name'], 'lane fast: relqueue %s was added with --lane fast%s' % (
                    e['name'], ' (a pair with %s: it takes each role\'s fast-lane slot)' % ' + '.join(e['cards']) if len(e.get('cards', ())) > 1 else ''))
            st = e.get('status')
            if st == 'done' and e.get('result') in ('KEEP', 'REVERT'):
                keep = e['result'] == 'KEEP'
                note('q:%s:%s' % (e['name'], st), 'relqueue %s %s %s' % (e['name'], e['result'], e.get('version', '')))
                why = 'relqueue %s %s %s (closed %s)' % (e['name'], e['result'], e.get('version', ''), e.get('closed', ''))
                log(c, 'sync', 'move %s -> %s: %s' % (c['stage'], 'released' if keep else 'rejected', why))
                c['stage'], c['why'], c['kind'], c['next'] = ('released', why, None, None) if keep else ('rejected', why, 'refuted', None)
                changed = True
                break
            if st in ('done', 'dropped'):
                note('q:%s:%s' % (e['name'], st), 'relqueue %s %s (%s): decide the card' % (e['name'], st, e.get('result') or e.get('why', '')))
            elif c['stage'] in STAGES[:4]:
                note('q:%s:open' % e['name'], 'relqueue %s open: in the release queue' % e['name'])
                log(c, 'sync', 'move %s -> ready: relqueue %s' % (c['stage'], e['name']))
                c['stage'] = 'ready'
                changed = True
        if c['stage'] in DONE:
            continue
        for n in ars:
            v = '%s/%s.md' % (VERD, n)
            try:
                head = next((l.split(':', 1)[1].strip() for l in open(v) if l.startswith('# autoread')), None)
            except OSError:
                head = None
            if head:
                note('ar:%s:%s' % (n, head[:40]), 'autoread %s verdict: %s (%s)' % (n, head, v))
        hs = set(links(c, 'hypo')) | ({c['hypo']} if c.get('hypo') else set())
        for r in hyp:
            if r['name'] in hs:
                note('h:%s:%s:%s:%s' % (r['name'], r['term'], r['stage'], r['time']), 'hypo %s %s=%s%s (%s) %s' % (
                    r['name'], r['term'], r['value'], ('+-' + r['hw']) if r.get('hw') else '', r['stage'], r.get('source', '')))
        for j, r in starts.items():
            if r.get('card') == c['id']:
                note('j:%s' % j, 'job %s started by %s -> %s' % (r['name'], r.get('by', '?'), r.get('out')))
                if j in ends:
                    note('je:%s' % j, 'job %s %s (rc %s) -> %s' % (r['name'], 'DONE' if ends[j]['rc'] == 0 else 'FAILED',
                                                                     ends[j]['rc'], r.get('out')))
    return changed


def human(c):
    """Time of the card's last entry made by a person or agent (not by sync)."""
    h = [x['t'] for x in c['history'] if x['by'] != 'sync']
    return when(h[-1] if h else c['created'])


def lint(b):
    """(card, what needs doing) for every open card that needs a person."""
    out, t = [], now()
    starts, _ = jobrecs()
    for c in b['cards']:
        if c['stage'] in DONE:
            continue
        n, cid = c.get('next'), c['id']
        if c.get('blocked'):
            sec = (t - when(c['blocked']['t'])).total_seconds()
            if sec >= 7200:
                out.append((cid, 'blocked for %s on %s: %s' % (dur(sec), c['blocked']['on'], c['blocked']['why'])))
        elif not n:
            if c['stage'] != 'proposed':                    # a proposed card waits for a slot
                out.append((cid, 'no next step. Name one with board.py next.'))
        else:
            d = n['deliverable'] if n['deliverable'].startswith('/') else os.path.join(REPO, n['deliverable'])
            if os.path.exists(d) and os.path.getmtime(d) > when(n['t']).timestamp() + 60:
                out.append((cid, "%s's output is written (%s). Read it, then set the next step or move the card."
                            % (n['by'], short(n['deliverable']))))
            elif n['by'] and not b['roles'].get(n['by']):
                out.append((cid, "the next step is %s's, and no session holds that role." % n['by']))
        idle = (t - human(c)).total_seconds()
        if idle >= STALE_H[c['stage']] * 3600:
            out.append((cid, 'no entry for %s while %s.' % (dur(idle), c['stage'])))
        used, bud = games_used(c, starts), c.get('budget')
        if bud and used > bud:
            out.append((cid, 'over its games budget: %d of %d.' % (used, bud)))
        if c['stage'] == 'testing' and not (c.get('hypo') or links(c, 'hypo')):
            out.append((cid, 'in testing with no hypothesis card. Add one: hypo.py new, then board.py link --hypo.'))
        if c.get('lane') == 'fast' and c['stage'] in FLIGHT:
            if c.get('owner') not in FAST_ROLES:
                out.append((cid, 'a fast-lane card owned by %s: the lane is for %s. Set link --owner, or take it out '
                            '(link --lane slot).' % (c.get('owner') or 'nobody', ', '.join(FAST_ROLES))))
            else:
                first = fast(b, c['owner'])[0]
                if first is not c:
                    out.append((cid, 'a second fast-lane card from %s (with %s): one per role. Finish one, or move this '
                                'one to the slots (link --lane slot).' % (c['owner'], first['id'])))
    return out


def render(b, decided=True):
    """board.md: what needs attention first, then roles, the active cards in full, the rest in short."""
    act = sorted(active(b), key=lambda c: ACTIVE.index(c['stage']))
    out = ['# Lab board', '', 'Updated %s UTC. A card in full with its history: `board.py show ID`. Rules: docs/adr/0010.'
           % now().strftime('%H:%M, %d %b'), '', '## Needs attention', '']
    out += ['- **%s**: %s' % x for x in lint(b)] or ['Nothing.']
    out += ['', '## Roles', '', '| Role | Session |', '|---|---|'] + ['| %s | %s |' % (r, who(b, r)) for r in ROLES]
    out += ['', '## Active (%d of %d slots used)' % (len(act), b.get('wip', WIP)), '']
    for c in act:
        n, blk = c.get('next') or {}, c.get('blocked')
        out += ['### %s: %s' % (c['id'], c.get('title', '')), '', facts(b, c), '']
        if blk:
            out.append('- **Blocked** on %s for %s: %s' % (blk['on'], dur((now() - when(blk['t'])).total_seconds()), blk['why']))
        if n:
            out += ['- **Next, by %s** (%s): %s' % (n['by'], who(b, n['by']), n['action']),
                    '- **Leaves:** %s' % short(n['deliverable']), '- **Stops when:** %s' % n['stop']]
        else:
            out.append('- **Next:** none named')
        out.append('')
    if not act:
        out += ['None.', '']
    fl = sorted(fast(b), key=lambda c: (FAST_ROLES.index(c['owner']) if c.get('owner') in FAST_ROLES else 9, c['id']))
    out += ['## Fast lane (%d; one per role: %s; no slot)' % (len(fl), ', '.join(FAST_ROLES)), '']
    for c in fl:
        out += compact(b, c)
    out += ([] if fl else ['None.']) + ['']
    for st, head in (('ready', 'Ready: in the release queue'), ('investigating', 'Investigating'), ('proposed', 'Proposed')):
        cs = [c for c in b['cards'] if c['stage'] == st and not (st == 'ready' and c.get('lane') == 'fast')]
        out += ['## %s (%d)' % (head, len(cs)), '']
        for c in cs:
            out += compact(b, c)
        out += ([] if cs else ['None.']) + ['']
    if decided:
        cut = now() - timedelta(days=7)
        out += ['## Decided in the last 7 days', '']
        dec = [c for c in b['cards'] if c['stage'] in DONE and when(c['history'][-1]['t']) >= cut]
        out += ['- **%s** %s%s: %s' % (c['id'], c['stage'], (' (%s)' % c['kind']) if c.get('kind') else '',
                                       clip(c.get('why') or '', 200)) for c in dec] or ['None.']
    return '\n'.join(out).rstrip()


def brief(b):
    """Compact lines for brief.py (about 1 KB)."""
    act = active(b)
    out = ['Roles: ' + ', '.join('%s = %s' % (r, who(b, r)) for r in ROLES),
           'Active %d of %d: %s' % (len(act), b.get('wip', WIP), ', '.join('%s (%s)' % (c['id'], c['stage']) for c in act) or 'none'),
           'Fast lane: %s' % (', '.join('%s (%s, %s)' % (c['id'], c['stage'], c.get('owner')) for c in fast(b)) or 'none')]
    out += ['! %s: %s' % x for x in lint(b)]
    for c in sorted((c for c in b['cards'] if c['stage'] not in DONE), key=lambda c: -STAGES.index(c['stage'])):
        n, blk = c.get('next') or {}, c.get('blocked')
        if blk:
            out.append('%s [%s] BLOCKED on %s: %s' % (c['id'], c['stage'], blk['on'], clip(blk['why'], 110)))
        elif n:
            out.append('%s [%s] next %s: %s' % (c['id'], c['stage'], n['by'], clip(n['action'], 110)))
    return out


def show(b, c):
    n, blk, L = c.get('next') or {}, c.get('blocked'), c.get('links') or {}
    out = ['%s: %s' % (c['id'], c.get('title', '')), facts(b, c), 'created %s by %s' % (c['created'][:16], c.get('by', '?'))]
    tied = ['%s %s' % (k, ', '.join(v)) for k, v in L.items() if v] + (['hypo ' + c['hypo']] if c.get('hypo') else [])
    if tied:
        out.append('linked: ' + '; '.join(tied))
    if blk:
        out.append('BLOCKED on %s since %s: %s' % (blk['on'], blk['t'][11:16], blk['why']))
    if n:
        out += ['', 'Next, by %s (%s), set %s:' % (n['by'], who(b, n['by']), ago(when(n['t']))), '  ' + n['action'],
                '  leaves: ' + short(n['deliverable']), '  stops when: ' + n['stop']]
    if c['stage'] in DONE:
        out += ['', 'Decided: %s%s: %s' % (c['stage'], (' (%s)' % c['kind']) if c.get('kind') else '', c.get('why') or '')]
    out += ['', 'History:'] + ['  %s  %-14s %s' % (x['t'][5:16], x['by'], x['what']) for x in c['history']]
    return '\n'.join(out)


def stats(b, days):
    cut = now() - timedelta(days=days)
    dec = [c for c in b['cards'] if c['stage'] in DONE and when(c['history'][-1]['t']) >= cut]
    rel = [c for c in dec if c['stage'] == 'released']
    rej = [c for c in dec if c['stage'] == 'rejected']
    hrs = [(when(c['history'][-1]['t']) - when(c['created'])).total_seconds() / 3600 for c in dec]
    print('Last %d days: %d decisions (%d released, %d rejected: %s)' % (
        days, len(dec), len(rel), len(rej), ', '.join('%d %s' % (sum(c.get('kind') == k for c in rej), k) for k in KINDS)))
    if hrs:
        print('  hypothesis to decision: median %.1f h, max %.1f h' % (statistics.median(hrs), max(hrs)))
    blk = {}
    for c in b['cards']:
        for x in c.get('blocks', []):
            if when(x['end']) >= cut:
                blk[x['on']] = blk.get(x['on'], 0) + (when(x['end']) - when(x['t'])).total_seconds() / 3600
    print('  card time blocked: ' + (', '.join('%s %.1f h' % kv for kv in sorted(blk.items())) or 'none recorded'))
    open_s, stall_h = {}, 0.0                   # stallwatch: unanswered prompts/questions, STALL .. CLEARED
    try:
        for l in open(STALLS):
            m = re.match(r'(\d{4}-\d\d-\d\d) (\d\d:\d\d) UTC (STALL|CLEARED) (\w+)\s+(\S+)', l)
            if not m:
                continue
            t = datetime.strptime(m.group(1) + ' ' + m.group(2), '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            k = (m.group(4), m.group(5))
            if m.group(3) == 'STALL':
                open_s[k] = t
            elif k in open_s and t >= cut:
                stall_h += (t - open_s.pop(k)).total_seconds() / 3600
    except OSError:
        pass
    print('  stalled on prompts/questions (stalls.log): %.1f h' % stall_h)
    waste = {c['id'] for c in rej if c.get('kind') in ('abandoned', 'duplicate')}
    jh, games = 0.0, 0
    try:
        starts, ends = {}, {}
        for l in open(JOBS):
            r = json.loads(l)
            (starts if r['ev'] == 'start' else ends)[r['job']] = r
        for j, r in starts.items():
            if r.get('card') in waste and j in ends:
                jh += (when(ends[j]['t']) - when(r['t'])).total_seconds() / 3600
                games += r.get('games') or 0
    except (OSError, ValueError):
        pass
    print('  jobs on abandoned/duplicate cards: %.1f job-hours, ~%d games (jobs.py records only)' % (jh, games))
    print('  open now: %d active of %d, %d blocked, %d with no next action' % (
        len(active(b)), b.get('wip', WIP), sum(bool(c.get('blocked')) for c in b['cards'] if c['stage'] not in DONE),
        sum(not c.get('next') for c in b['cards'] if c['stage'] not in DONE)))


def main(a):
    if not a or a[0] in ('-h', '--help'):
        sys.exit(__doc__)
    cmd, a = a[0], a[1:]
    os.makedirs(ST, exist_ok=True)
    if cmd in ('list', 'show', 'stats', 'lint', 'sync', 'brief') or (cmd == 'role' and len(a) < 2):
        with open(LOCK, 'w') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            b = load()
            if sync(b) or cmd == 'sync':
                save(b)
        if cmd == 'lint':
            print('\n'.join('- %s: %s' % x for x in lint(b)) or 'Nothing needs a person.')
        elif cmd == 'sync':
            print('synced')
        elif cmd == 'brief':
            print('\n'.join(brief(b)))
        elif cmd == 'list':
            print(render(b, decided='--all' in a))
        elif cmd == 'show':
            c = card(b, a[0] if a else '')
            print(json.dumps(c, indent=1) if '--json' in a else show(b, c))
        elif cmd == 'stats':
            stats(b, int(opt(a, '--days', '7')))
        else:
            print('\n'.join('%-12s %s' % (r, who(b, r)) for r in ROLES))
        return
    with open(LOCK, 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        b = load()
        sync(b)
        by = opt(a, '--as', '?')
        if by == 'sync':
            sys.exit('--as sync is reserved for the automatic sync')
        if cmd == 'role':
            if a[0] not in ROLES:
                sys.exit('roles: %s' % ', '.join(ROLES))
            held = [r for r, x in b['roles'].items() if x == a[1] and r != a[0]]
            if held and '--also' not in a:
                sys.exit('%s already holds %s: one role per session (--also to override; the owner\'s call)' % (a[1], held[0]))
            b['roles'][a[0]] = a[1]
        elif cmd == 'add':
            cid = a.pop(0) if a else ''
            if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,40}', cid) or any(c['id'] == cid for c in b['cards']):
                sys.exit('ID: new, lowercase, [a-z0-9_.-]')
            st, title, over = opt(a, '--stage', 'proposed'), opt(a, '--title'), opt(a, '--over')
            if st not in STAGES[:5] or not title:
                sys.exit('add needs --title and an open stage: %s' % ' '.join(STAGES[:5]))
            lane = opt(a, '--lane')
            if lane not in (None, 'fast'):
                sys.exit('add --lane: fast, or leave it out (a slot)')
            bud = opt(a, '--budget')
            c = {'id': cid, 'title': title, 'stage': st, 'owner': opt(a, '--owner'), 'hypo': opt(a, '--hypo'),
                 'created': ts(), 'by': by, 'history': [], 'blocks': [], 'budget': int(bud) if bud else None}
            if c['owner'] and c['owner'] not in ROLES:
                sys.exit('--owner must be a role: %s' % ', '.join(ROLES))
            if lane:
                c['lane'] = 'fast'
                why = fast_refusal(b, c, st)
                if why and not (over and c['owner'] in FAST_ROLES):
                    sys.exit(why)
            elif st in ACTIVE and len(active(b)) >= b.get('wip', WIP) and not over:
                sys.exit(wip_refusal(b))
            b['cards'].append(c)
            log(c, by, 'added as %s%s%s' % (st, ' in the fast lane' if lane else '', (' OVER WIP: ' + over) if over else ''))
            act = opt(a, '--next')
            if act:
                set_next(b, c, [act] + a, by)
        else:
            c = card(b, a.pop(0) if a else '')
            if cmd == 'next':
                set_next(b, c, a, by)
            elif cmd == 'move':
                st, why, kind, over = (a[0] if a else ''), opt(a, '--why'), opt(a, '--kind'), opt(a, '--over')
                if st not in STAGES:
                    sys.exit('stages: %s' % ' '.join(STAGES))
                if c.get('lane') == 'fast':
                    why_f = fast_refusal(b, c, st) if st in FLIGHT and c['stage'] not in FLIGHT else None
                    if why_f and not over:
                        sys.exit(why_f)
                elif st in ACTIVE and c['stage'] not in ACTIVE and len(active(b)) >= b.get('wip', WIP) and not over:
                    sys.exit(wip_refusal(b))
                if st in DONE and not why:
                    sys.exit('%s needs --why (verdict file or LR:n)' % st)
                if st == 'rejected' and kind not in KINDS:
                    sys.exit('rejected needs --kind %s' % '|'.join(KINDS))
                log(c, by, 'move %s -> %s%s%s' % (c['stage'], st, (': ' + why) if why else '', (' OVER WIP: ' + over) if over else ''))
                c['stage'] = st
                if st in DONE:
                    c['why'], c['kind'], c['next'] = why, kind, None
                if st == 'ready':
                    print('ready = in the release queue: relqueue.py add %s ... (the build session ships from there)' % c['id'])
            elif cmd == 'block':
                on, why = opt(a, '--on'), opt(a, '--why')
                if on not in BLOCKS or not why:
                    sys.exit('block needs --on %s and --why' % '|'.join(BLOCKS))
                c['blocked'] = {'on': on, 'why': why, 't': ts()}
                log(c, by, 'blocked on %s: %s' % (on, why))
            elif cmd == 'unblock':
                x = c.get('blocked')
                if x:
                    c.setdefault('blocks', []).append(dict(x, end=ts()))
                c['blocked'] = None
                log(c, by, 'unblocked')
            elif cmd == 'link':
                L = c.setdefault('links', {})
                for k in ('relq', 'autoread', 'hypo'):
                    v = opt(a, '--' + k)
                    if v and v not in L.setdefault(k, []):
                        L[k].append(v)
                bud, own, lane, over = opt(a, '--budget'), opt(a, '--owner'), opt(a, '--lane'), opt(a, '--over')
                if bud:
                    c['budget'] = int(bud)
                if own:
                    if own not in ROLES:
                        sys.exit('--owner must be a role: %s' % ', '.join(ROLES))
                    c['owner'] = own
                if lane == 'fast' and c.get('lane') != 'fast':
                    c['lane'] = 'fast'
                    why_f = fast_refusal(b, c, c['stage'])
                    if why_f and not (over and c['owner'] in FAST_ROLES):
                        sys.exit(why_f)
                elif lane == 'slot' and c.get('lane') == 'fast':
                    c['lane'] = None
                    if c['stage'] in ACTIVE and len(active(b)) > b.get('wip', WIP) and not over:
                        sys.exit(wip_refusal(b))
                elif lane not in (None, 'fast', 'slot'):
                    sys.exit('link --lane: fast or slot')
                elif own and c.get('lane') == 'fast' and c['stage'] in FLIGHT:
                    why_f = fast_refusal(b, c, c['stage'])
                    if why_f and not over:
                        sys.exit(why_f)
                log(c, by, 'link %s%s%s%s%s' % (json.dumps(L), (' budget %s' % bud) if bud else '', (' owner %s' % own) if own else '',
                                              (' lane %s' % lane) if lane else '', (' OVER: ' + over) if over else ''))
                sync(b)
            elif cmd == 'note':
                if not a:
                    sys.exit('note needs TEXT')
                log(c, by, 'note: ' + ' '.join(a))
            else:
                sys.exit(__doc__)
        save(b)
    if cmd == 'role':
        print('\n'.join('%-12s %s' % (r, who(b, r)) for r in ROLES))
    elif cmd == 'note':
        print('noted')
    else:
        print('\n'.join(compact(b, c)))
        print('board: %d of %d active, %d in the fast lane; board.py list for the whole board' % (
            len(active(b)), b.get('wip', WIP), len(fast(b))))


if __name__ == '__main__':
    main(sys.argv[1:])
