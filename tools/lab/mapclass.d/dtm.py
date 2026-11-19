"""dtm (12 Nov, Tool Builder; Builder/RC C634 DTZ arm B filtered draft read): the bot's OWN draft-time dash-time term state, S.dtm_ok / S.dtm_x /
S.dtm_h (draft_map_features.cc dash_walk_times), as a LOOKUP, never a game: the values come from a release dglog copy (nova_tbdg_dfeat, tag 105)
played 1 round on every draftstock map by tools/lab/draftdiag.py and stored in /data/zw4424/st/draftstock/cols/dtm_<draft_key>.tsv
(maphash = sha1(map file)[:16], seat, ok, x, h). A map not in the table (new maps, Condor nodes: /data is not mounted there) reads None, so a
filter term on it passes nothing rather than everything. Draft key = live's draftprobe.draft_key when the table was made (f7938d48f3987edf,
v815-v820 draft code); a draft-code change needs a new table.
Classes (either seat = the larger of the two seats' values):
  dtm_x_max   max over seats of dtm_x where dtm_ok, else 0
  dtm_ok_any  1 when either seat has dtm_ok, else 0
  dtm_h_max   max over seats of dtm_h where dtm_ok, else 0"""
import hashlib
import os

TABLE = os.environ.get("DTM_TABLE", "/data/zw4424/st/draftstock/cols/dtm_f7938d48f3987edf.tsv")
_T = {}


def _load():
    if _T or not os.path.exists(TABLE):
        return _T
    for ln in open(TABLE):
        p = ln.rstrip("\n").split("\t")
        if len(p) != 5 or p[0] == "maphash":
            continue
        h, _seat, ok, x, hh = p
        cur = _T.setdefault(h, [0, 0.0, 0.0])
        if ok == "1":
            cur[0] = 1
            cur[1] = max(cur[1], float(x))
            cur[2] = max(cur[2], float(hh))
    return _T


def _row(path):
    t = _load()
    if not t:
        return None
    try:
        h = hashlib.sha1(open(path, "rb").read()).hexdigest()[:16]
    except OSError:
        return None
    return t.get(h)


def dtm_x_max(path):
    r = _row(path)
    return None if r is None else (r[1] if r[0] else 0.0)


def dtm_ok_any(path):
    r = _row(path)
    return None if r is None else float(r[0])


def dtm_h_max(path):
    r = _row(path)
    return None if r is None else (r[2] if r[0] else 0.0)


CLASSES = {"dtm_x_max": dtm_x_max, "dtm_ok_any": dtm_ok_any, "dtm_h_max": dtm_h_max}
