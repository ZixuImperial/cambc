# b1863 RLF: result and our team's deaths (seat from meta).
import replay
def read(path, meta):
    seat = str(meta.get('seat', 'a')).upper()
    g = replay.load(path, us=seat)
    f = g.final
    us = 0 if seat == 'A' else 1
    dth = 0
    for b in (g.d.get('stats') or {}).get('bodies', []):
        if g.who(b['id']).endswith('(' + seat + ')'):
            dth += b['deaths']
    return dict(win=1 if f.get('outcome') == us + 1 else 0, r=f.get('round'), sub=f.get('submitted'), deaths=dth)
