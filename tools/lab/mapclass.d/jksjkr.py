"""jksjkr: b2367 probe classes for Deep's two JKC parameter arms (13 Nov), on jackpot.py's group model (draft-time features only).
  jks_add = 1 when the single-jackpot test fails but JKS's twin test holds: top two groups by gems both mid, together >= half of all
            gems, third < .9 x second, largest >= 300, own-half caps as jackpot.  jkr_add / jkr_drop = maps the JKR rate floor
            (largest gems x 100 / (respawn + 5) >= 150 instead of gems >= 300) adds to / drops from the class.  jkr_chg = add or drop."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402
import jackpot as J  # noqa: E402

_c = {}


def _groups(path):
    d = map26a.load(path)
    W, H, camps = d["W"], d["H"], d["camps"]
    block = set(d["wall"]) | set(d["hole"]) | set(d["altar"]) | set(camps)
    da, db = J._bfs(W, H, list(d["spawnA"]), block), J._bfs(W, H, list(d["spawnB"]), block)
    seen, gs = set(), []
    for c in sorted(camps):
        if c in seen:
            continue
        comp, st = [], [c]
        seen.add(c)
        while st:
            x, y = st.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        adj = {(x + dx, y + dy) for (x, y) in comp for dx, dy in J.N8}
        a = min((da[p] for p in adj if p in da), default=None)
        b = min((db[p] for p in adj if p in db), default=None)
        if a is None or b is None:
            zone = "none" if a is None and b is None else ("A" if b is None else "B")
        else:
            r = a / max(1, a + b)
            zone = "A" if r < .4 else ("B" if r > .6 else "mid")
        ty = [camps[p] for p in comp]
        gs.append(dict(gems=sum(J.GEMS[t] for t in ty), gold=sum(J.GOLD[t] for t in ty), rsp=max(J.RSP[t] for t in ty), zone=zone))
    return gs


def _feats(path):
    if path in _c:
        return _c[path]
    gs = _groups(path)
    tg = sum(g["gems"] for g in gs)
    if not tg:
        _c[path] = None
        return None
    gs.sort(key=lambda g: -g["gems"])
    a = gs[0]
    second = gs[1]["gems"] if len(gs) > 1 else 0
    third = gs[2]["gems"] if len(gs) > 2 else 0
    A = [g for g in gs if g["zone"] == "A"]
    caps = sum(g["gems"] * 100.0 / (g["rsp"] + J.CAP) for g in A) < 150 and sum(g["gold"] * 100.0 / (g["rsp"] + J.CAP) for g in A) >= 400
    single = second < 0.9 * a["gems"] and a["gems"] >= 0.5 * tg
    mid = a["zone"] == "mid"
    old = mid and caps and single and a["gems"] >= 300
    twin = len(gs) > 1 and gs[1]["zone"] == "mid" and (a["gems"] + second) >= 0.5 * tg and third < 0.9 * second
    jks = mid and caps and a["gems"] >= 300 and not single and twin
    rate = a["gems"] * 100.0 / (a["rsp"] + J.CAP) >= 150
    new_r = mid and caps and single and rate
    f = dict(jks_add=float(jks), jkr_add=float(new_r and not old), jkr_drop=float(old and not new_r), jkr_chg=float(new_r != old), jkc_old=float(old))
    _c[path] = f
    return f


CLASSES = {k: (lambda k: lambda p: (_feats(p) or {}).get(k))(k) for k in ("jks_add", "jkr_add", "jkr_drop", "jkr_chg", "jkc_old")}
