"""(versioned copy of /data/USER/st/deepan/artef/tempo.py, Deep 10 Nov; shipcheck tempo step) Per champion body, r1-150 and r1-300: fight turns (classify_all 'fight' = hits dealt to an enemy champion), walk-to-fight turns
(walk run ended by a fight turn), farm turns, first fight round, deaths, plus contact rounds (dealt or taken a champion hit).
usage: tempo.py LIST OUT.jsonl   LIST lines: PATH LABEL_A LABEL_B (side label for team 0 / team 1)"""
import collections, json, sys
sys.path.insert(0, '/homes/USER/cambc/tools/lab')
import replay
from multiprocessing import Pool
LIMS = (150, 300)
def one(line):
    ff = line.split(); path, la, lb = ff[0], ff[1], ff[2]
    try:
        g = replay.load(path, us='A'); act = replay.classify_all(g)
    except Exception as e:
        return []
    ci = g.ci; team = g.team_of; out = []
    taken = collections.defaultdict(set)
    for t in g.turns:
        if t[0] > 300: break
        for v, d in replay.hostile_hits(g, t): taken[v].add(t[0])
    for b in g.d['bodies']:
        c = b['id']; tm = team[c]; ser = g.by_champ.get(c, [])
        if not ser: continue
        row = dict(mid=path, side=(la, lb)[tm], kit=b['name'], team=tm, last=ser[-1][0])
        for L in LIMS:
            s = [t for t in ser if t[0] <= L]
            C = collections.Counter(act.get((t[0], c)) for t in s)
            wf = 0; run = 0
            for t in s:
                a = act.get((t[0], c))
                if a == 'walk': run += 1
                else:
                    if a == 'fight': wf += run
                    run = 0
            ff_ = [t[0] for t in s if act.get((t[0], c)) == 'fight']
            dealt = {t[0] for t in s if act.get((t[0], c)) == 'fight'}
            cont = len(dealt | {r for r in taken[c] if r <= L})
            row[str(L)] = dict(fight=C['fight'], wtf=wf, farm=C['farm'], walk=C['walk'], dead=C['dead'], contact=cont,
                               first=(ff_[0] if ff_ else None), deaths=(s[-1][ci['deaths']] if s else 0), earned=(s[-1][ci['earned']] if s else 0))
        out.append(row)
    return out
if __name__ == '__main__':
    lines = [l for l in open(sys.argv[1]) if l.strip()]
    with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as p, open(sys.argv[2], 'w') as o:
        for rows in p.imap_unordered(one, lines, chunksize=2):
            for r in rows: o.write(json.dumps(r) + '\n')
