#!/usr/bin/env python3
"""qa.py KEEPDIR CAND: rewrite QA (Builder 30 Oct), CAND side ('us') vs the base side of the same KEEP games. Moved here from
/data/zw4424/st/bugx 2 Nov. "Unchannelled" follows replay.chosen_channel: since SPIN_SELF (v383) about 84% of our turns end with a
lazy recall that the next turn restarts, and the raw chType test dropped those turns, so stuck, loop2, idlet and dlock read ~0 for us
from v383 to 2 Nov while opponents counted in full: compare only with reads after that date. Per body:
 stuck  = >= 20 consecutive alive, unchannelled turns on one tile with no attack/cast (moves blocked or none);
 loop2  = >= 20 consecutive rounds alternating between exactly two tiles, no attack/cast;
 idlet  = >= 10 consecutive turns with no move/attack/cast while a live camp of an alive group is within 2 or a foe within 3 (idle with a target);
 nobank = a bag >= 100 gems held >= 300 consecutive alive rounds with no tribute;
 dlock  = rounds where >= 3 bodies of the team are all inside an empty streak (no move/attack/cast) of >= 20 rounds;
 fuel   = exhausted turns (end == 1); fault = end == 2."""
import collections, json, os, sys
sys.path.insert(0, '/homes/zw4424/cambc/tools/lab')
import replay as R

def scan(rep, side, row):
    g = R.load(rep, us=side); ci = g.ci
    pos = collections.defaultdict(dict)
    for t in g.turns:
        if t[ci['alive']]: pos[t[0]][t[1]] = (t[2], t[3])
    cdead = collections.defaultdict(list); resp = collections.defaultdict(list); capg = collections.defaultdict(list)
    for e in g.events:
        if e[1] == 'camp_death': cdead[e[2]].append(e[0])
        if e[1] == 'group_respawn': resp[e[2]].append(e[0])
        if e[1] == 'capture': capg[e[2]].append(e[0])
    def camp_alive(cid, r):
        gi = g.camps[cid]['group']; lr = max([x for x in resp[gi] if x <= r], default=-1)
        if any(lr < x <= r for x in capg[gi]): return False  # QA2: captured, not yet respawned
        return not any(lr < x <= r for x in cdead[cid])
    camps = [(cid, c['x'], c['y']) for cid, c in g.camps.items()]
    M = [collections.Counter(), collections.Counter()]; EX = [collections.defaultdict(list), collections.defaultdict(list)]
    empty_rounds = [collections.defaultdict(int), collections.defaultdict(int)]
    def ex(tm, k, v):
        if len(EX[tm][k]) < 3: EX[tm][k].append(v)
    # 11 Nov (Econ: v750 'stuck' flag on 01yellow_brick_road was a Heart farming a wolf from one tile, 33-36 a hit for ~40 turns): a turn
    # in which a camp hits the body (camp_attack) or a champion attack/cast targets it is an engaged turn, never 'stuck' or a loop step
    engaged = set()
    for e in g.events:
        if e[1] == 'camp_attack' and len(e) > 3:
            engaged.add((e[0], e[3]))
    for c0, ts0 in g.by_champ.items():
        for t0 in ts0:
            for a0 in (t0[-1] or []):
                if a0 and a0[0] == 'a' and len(a0) > 2 and a0[1] == 1:
                    engaged.add((t0[0], a0[2]))
                elif a0 and a0[0] == 'c' and len(a0) > 7:
                    for kk, i0, d0 in a0[7]:
                        if kk == 1:
                            engaged.add((t0[0], i0))
    for e in g.events:  # a camp the body killed: e = [round, 'camp_death', camp, killer, ...]
        if e[1] == 'camp_death' and len(e) > 3:
            engaged.add((e[0], e[3]))
    for c0, ts0 in g.by_champ.items():  # income: earned or carried gems rose within the last 3 turns (farming from one tile)
        prev = []
        for t0 in ts0:
            v0 = (t0[ci['earned']], t0[ci['gems']])
            if any(v0[0] > p0[0] or v0[1] > p0[1] for p0 in prev[-3:]):
                engaged.add((t0[0], c0))
            prev.append(v0)
    # capturing: the body's team has a capture of a group in progress (capture_start -> capture / capture_reset) and the body stands within
    # 2 (Chebyshev) of that group's tiles. Standing still on a capture zone is the capture, not 'stuck'
    act_cap = []  # (start, end, team, group)
    open_ = {}
    for e in sorted(g.events, key=lambda e: e[0]):
        if e[1] == 'capture_start' and len(e) > 3:
            open_[(e[3], e[2])] = e[0]
        elif e[1] in ('capture', 'capture_reset') and len(e) > 3 and (e[3], e[2]) in open_:
            act_cap.append((open_.pop((e[3], e[2])), e[0], e[3], e[2]))
    act_cap += [(s0, 10 ** 9, tm0, gi0) for (tm0, gi0), s0 in open_.items()]
    if act_cap:
        gpts = {gid: gr.get('pts') or [] for gid, gr in getattr(g, 'groups', {}).items()}
        for c0, ts0 in g.by_champ.items():
            tm0 = g.team_of[c0]
            for t0 in ts0:
                for s0, e0, tmc, gi0 in act_cap:
                    if tmc == tm0 and s0 <= t0[0] <= e0 and any(max(abs(t0[2] - x), abs(t0[3] - y)) <= 2 for x, y in gpts.get(gi0, [])):
                        engaged.add((t0[0], c0))
                        break
    for c, ts in g.by_champ.items():
        tm = g.team_of[c]; lab = g.label[c]
        st = []; lp = []; it = []; bag = []; er = []; pv = None; hd = []  # hd: 'hold' (11 Nov, Econ): full HP, no move, no income/hits, spin-recall acts only
        def close(k, run, extra=None):
            if not run: return
            n = len(run); M[tm][k + '_ep'] += 1; M[tm][k + '_t'] += n
            ex(tm, k, (run[0], run[-1], lab) + ((extra,) if extra is not None else ()))
        for t in ts + [None]:
            if t is None:
                if len(st) >= 20: close('stuck', st)
                if len(hd) >= 20: close('hold', hd)
                if len(lp) >= 20: close('loop2', [x[0] for x in lp])
                if len(it) >= 10: close('idlet', it)
                if len(er) >= 20:
                    for r in er: empty_rounds[tm][r] += 1
                break
            ch = t[ci['chType']]
            if ch == 1 and not (pv and pv[ci['alive']] and pv[ci['chType']] == 1 and t[ci['chTimer']] < pv[ci['chTimer']]): ch = 0  # a lazy recall start
            pv = t
            r = t[0]; alive = t[ci['alive']] and not ch
            ks = [a[0] for a in t[-1]]
            act = any(k in ('a', 'c') for k in ks) or (r, c) in engaged; mv = 'm' in ks
            if t[ci['end']] == 1: M[tm]['fuel'] += 1
            if t[ci['end']] == 2: M[tm]['fault'] += 1
            # hold: an alive body at full HP whose only acts are recall start / channel cancel (a spin hold), no move, not engaged
            hold = (t[ci['alive']] and t[ci['hp']] >= t[ci['maxHp']] and not mv and (r, c) not in engaged and ks and set(ks) <= {'x', 'rc'})
            if hold:
                hd.append(r)
            else:
                if len(hd) >= 20: close('hold', hd)
                hd = []
            # stuck (a hold turn is not stuck)
            if alive and not act and not hold and (not st or (t[2], t[3]) == st_pos): 
                if not st: st_pos = (t[2], t[3])
                st.append(r)
            else:
                if len(st) >= 20: close('stuck', st)
                st = [r] if alive and not act and not hold else []; st_pos = (t[2], t[3])
            # loop2
            p = (t[2], t[3])
            if alive and not act:
                tiles = {x[1] for x in lp} | {p}
                if len(tiles) <= 2 and (not lp or lp[-1][1] != p):
                    lp.append((r, p))
                else:
                    if len(lp) >= 20 and len({x[1] for x in lp}) == 2: close('loop2', [x[0] for x in lp])
                    lp = [(r, p)]
            else:
                if len(lp) >= 20 and len({x[1] for x in lp}) == 2: close('loop2', [x[0] for x in lp])
                lp = []
            # idle with a target
            tgt = alive and not act and not mv and (any(R.cheb(p[0], p[1], x, y) <= 2 and camp_alive(cid, r) for cid, x, y in camps) or
                                                    any(g.team_of[o] != tm and R.cheb(p[0], p[1], *q) <= 3 for o, q in pos[r].items()))
            if tgt: it.append(r)
            else:
                if len(it) >= 10: close('idlet', it)
                it = []
            # empty streak for deadlock
            if alive and not act and not mv: er.append(r)
            else:
                if len(er) >= 20:
                    for rr in er: empty_rounds[tm][rr] += 1
                er = []
            # never banking
            if t[ci['alive']] and t[ci['gems']] >= 100 and t[ci['chType']] != 2: bag.append(r)
            else:
                if len(bag) >= 300: close('nobank', bag, max(1, 0))
                bag = []
        if len(bag) >= 300: close('nobank', bag)
    for tm in (0, 1):
        dl = sorted(r for r, n in empty_rounds[tm].items() if n >= 3)
        M[tm]['dlock_r'] = len(dl)
        if dl: ex(tm, 'dlock', (dl[0], dl[-1], len(dl)))
    return [dict(mid=rep, map=row['map'], cand=tm == g.us, win=(row['win'] == side) if tm == g.us else (row['win'] != side), m=dict(M[tm]), ex={k: v for k, v in EX[tm].items()}) for tm in (0, 1)]

def job(a):
    rep, side, row = a
    try: return scan(rep, side, row)
    except Exception as e: return [dict(err=repr(e)[:200], mid=rep)]

if __name__ == '__main__':
    import multiprocessing as mp
    keep, cand, out = sys.argv[1:4]
    jobs = []
    for l in open(os.path.join(keep, 'games.jsonl')):
        gm = json.loads(l); rep = os.path.join(keep, 'rep', gm['id'] + '.repl26a')
        if gm.get('ok') and os.path.exists(rep): jobs.append((rep, 'A' if gm['a'] == cand else 'B', gm))
    with mp.Pool(4) as p, open(out, 'w') as o:
        for res in p.imap_unordered(job, jobs):
            for x in res: o.write(json.dumps(x) + '\n')
