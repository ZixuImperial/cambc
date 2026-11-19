# b1863 PNW: result, final round, tributed, our Prism's kills/deaths/gems (team = seat from file name: a/b = the diag bot's seat).
import replay
def read(path, meta):
    seat = str(meta.get('seat', 'a')).upper()
    g = replay.load(path, us=seat)
    f = g.final
    us = 0 if seat == 'A' else 1
    pr = None
    for b in (g.d.get('stats') or {}).get('bodies', []):
        w = g.who(b['id'])
        if 'prism' in w and w.endswith('(' + seat + ')'):
            pr = dict(k=b['kills'], d=b['deaths'], gg=b['gemsGained'], gt=b['gemsTributed'])
    return dict(seat=seat, win=1 if f.get('outcome') == us + 1 else 0, out=f.get('outcome'), r=f.get('round'), sub=f.get('submitted'), prism=pr)
