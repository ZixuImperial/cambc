"""hypo.py - hypothesis cards and the calibration ledger (cambc-71, 27 Oct).

Why: first reads of a change shrink a lot by the time fresh or live data come in (C&I mirror +0.21 -> +0.03 paired,
gem-heavy fixture +0.102 -> -0.005, GOLEM_CHIP +0.088 -> -0.021). Writing the prediction down before the test, then the
observation after, measures that shrinkage. The release queue can then rank candidates by shrunk expected value, and a
test too small to see the shrunk effect is caught before it runs (see pitfalls.md item 9).

  hypo.py new NAME --change TEXT --mech TEXT --predict TERM=VAL[+-HW] [--predict ...] --refute TEXT --test TEXT [--by S]
      Before any game: writes the card (reports/state/hypotheses/NAME.md) and one ledger row per predicted term.
      TERM is a paired measure in the glossary's sense, e.g. score (net map score vs base), gold750, deaths500.
  hypo.py observe NAME TERM=VAL[+-HW] --stage first|fresh|heldout|live --source FILE [--by S]
      After a read: appends the observation (cite the report or verdict file).
  hypo.py ledger [--term score]
      Predicted vs latest observation per card, and the shrink: median of observed/predicted, sign agreement.
  hypo.py shrink [--term score]
      Prints the shrink factor alone (for relqueue / power checks).
Ledger rows marked seed=1 were reconstructed from memory notes of 26-27 Oct (first read -> later read), not predictions."""
import csv, os, re, statistics, sys
from datetime import datetime, timezone

D = (os.environ.get('HYPO_DIR') or '/homes/zw4424/condor-work/reports/state/hypotheses')
LEDGER = D + '/ledger.tsv'
COLS = ['time', 'name', 'kind', 'stage', 'term', 'value', 'hw', 'source', 'by', 'seed']


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def parse(tv):
    m = re.fullmatch(r'([A-Za-z][\w.]*)=([-+]?[\d.]+)(?:(?:\+-|±)([\d.]+))?', tv.strip())
    if not m:
        sys.exit('bad TERM=VAL[+-HW]: %r' % tv)
    return m.group(1), float(m.group(2)), (float(m.group(3)) if m.group(3) else '')


def rows():
    if not os.path.exists(LEDGER):
        return []
    return list(csv.DictReader(open(LEDGER), delimiter='\t'))


def append(rs):
    os.makedirs(D, exist_ok=True)
    new = not os.path.exists(LEDGER)
    with open(LEDGER, 'a', newline='') as f:
        w = csv.DictWriter(f, COLS, delimiter='\t')
        if new:
            w.writeheader()
        for r in rs:
            w.writerow({k: r.get(k, '') for k in COLS})


def opts(a, k):
    return [a[i + 1] for i, x in enumerate(a[:-1]) if x == k]


def new(name, a):
    one = lambda k: (opts(a, k) or [''])[0]
    preds = [parse(p) for p in opts(a, '--predict')]
    need = ['--change', '--mech', '--refute', '--test']
    if not preds or not all(one(k) for k in need):
        sys.exit('new NAME needs --change --mech --predict TERM=VAL --refute --test')
    card = '%s/%s.md' % (D, name)
    if os.path.exists(card) or any(r['name'] == name for r in rows()):
        sys.exit('%s exists: a card is frozen once written' % name)
    t, by = now(), one('--by')
    os.makedirs(D, exist_ok=True)
    open(card, 'w').write('\n'.join([
        '# Hypothesis %s (%s%s)' % (name, t, ', ' + by if by else ''), '',
        '- **Change:** ' + one('--change'),
        '- **Mechanism:** ' + one('--mech'),
        '- **Prediction:** ' + '; '.join('%s %+g%s' % (k, v, (' ± %g' % h) if h != '' else '') for k, v, h in preds),
        '- **Refuted if:** ' + one('--refute'),
        '- **Test:** ' + one('--test'),
        '- **Shrunk prediction** (ledger median %s): %s' % (
            fmt(shrink_of('score')), '; '.join('%s %+.3f' % (k, v * s) for k, v, _ in preds
                                              for s in [shrink_of(k)] if s is not None) or 'no ledger yet'),
        '', 'Observations: `hypo.py observe %s ...` (ledger.tsv).' % name, '']))
    append([dict(time=t, name=name, kind='pred', stage='card', term=k, value=v, hw=h, source=card, by=by) for k, v, h in preds])
    print('card %s; %d prediction(s) in %s' % (card, len(preds), LEDGER))


def observe(name, a):
    tvs = [x for x in a if '=' in x and not x.startswith('--')]
    stage, src = (opts(a, '--stage') or [''])[0], (opts(a, '--source') or [''])[0]
    if not tvs or stage not in ('first', 'fresh', 'heldout', 'live') or not src:
        sys.exit('observe NAME TERM=VAL[+-HW] --stage first|fresh|heldout|live --source FILE')
    if not any(r['name'] == name and r['kind'] == 'pred' for r in rows()):
        sys.exit('no card %s: write the prediction first (hypo.py new)' % name)
    rs = []
    for tv in tvs:
        k, v, h = parse(tv)
        rs.append(dict(time=now(), name=name, kind='obs', stage=stage, term=k, value=v, hw=h, source=src,
                       by=(opts(a, '--by') or [''])[0]))
    append(rs)
    print('observed %s: %s' % (name, ', '.join(tvs)))


def pairs(term):
    """(name, predicted, latest observation row) per card with both, for TERM."""
    pred, obs = {}, {}
    for r in rows():
        if r['term'] != term:
            continue
        if r['kind'] == 'pred':
            pred.setdefault(r['name'], r)
        else:
            obs[r['name']] = r              # rows are in time order: the last one is the latest read
    return [(n, pred[n], obs.get(n)) for n in pred]


def shrink_of(term):
    rs = [float(o['value']) / float(p['value']) for _, p, o in pairs(term) if o and float(p['value']) != 0]
    return statistics.median(rs) if rs else None


def fmt(x):
    return '-' if x is None else '%.2f' % x


def ledger(term):
    ps = pairs(term)
    print('%-26s %9s %9s %-8s %7s  %s' % ('card', 'predicted', 'observed', 'stage', 'ratio', 'source'))
    for n, p, o in ps:
        r = float(o['value']) / float(p['value']) if o and float(p['value']) else None
        print('%-26s %+9.3f %9s %-8s %7s  %s%s' % (n, float(p['value']), ('%+.3f' % float(o['value'])) if o else 'open',
              o['stage'] if o else '', fmt(r), (o or p)['source'][-60:], '  (seed)' if p.get('seed') == '1' else ''))
    done = [(float(p['value']), float(o['value'])) for _, p, o in ps if o]
    if done:
        same = sum((a > 0) == (b > 0) and b != 0 for a, b in done)
        print('\n%s: %d closed of %d; median shrink observed/predicted %s; sign kept %d of %d; mean |pred| %.3f vs |obs| %.3f' % (
            term, len(done), len(ps), fmt(shrink_of(term)), same, len(done),
            statistics.mean(abs(a) for a, _ in done), statistics.mean(abs(b) for _, b in done)))


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ('new', 'observe', 'ledger', 'shrink'):
        sys.exit(__doc__)
    term = (opts(a, '--term') or ['score'])[0]
    if a[0] == 'new' and len(a) > 1:
        new(a[1], a[2:])
    elif a[0] == 'observe' and len(a) > 1:
        observe(a[1], a[2:])
    elif a[0] == 'ledger':
        ledger(term)
    elif a[0] == 'shrink':
        print(fmt(shrink_of(term)))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
