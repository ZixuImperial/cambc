#!/usr/bin/env python3
"""gamesum: a durable store of decoded games, so whole-population census readers take seconds, not minutes (Tool Builder, 10 Nov;
Econ asked). replay.load decodes every game again whenever its rdec_cache entry is gone (prune3h drops entries unread for 3 h), so a
census over 750 games paid ~0.5 s of decoding per game, every run. gamesum keeps one file per distinct replay under /data and
rebuilds the SAME replay.Game object from it in ~15 ms: every reader field and helper works unchanged (events, by_champ, turns, ci,
team_of, groups, camps, rounds, altars, zone(), who(), R.classify_all, R.camp_hits, R.hostile_hits, ...), so numbers match
replay.load exactly.

Store: /data/USER/st/gamesum/<dup_key>.gs2 (dup_key = gameindex's SIZE:CRC32 with ':' -> '_'; ids that are byte-identical
re-plays share one file). Contents (format 2, pickle of zstd'd parts, ~140 KB/game): the decoder's dict minus 'stats'/'decoder'
(map, bodies, draft, final, rounds, events as decoded: replay.Game's kill-credit repair is re-applied at load), the turn rows split
into an int matrix (columns that are ints in that game), the other scalar columns, an acts digest (each turn's action kinds) and the
full acts lists, plus locate()'s meta. Each file records its rdec.js id (build --check-rdec redoes stale ones). Seat, version, foe,
map, result and lane come from /data/USER/st/gameindex.tsv at load time. Failures: gamesum/fail.tsv (retried with --retry).
Speed (1419 v697+ games, load ~30): events/groups/numpy-series census 5 s (replay.load: 66 s with a warm rdec cache, ~0.5 s/game
more for every game prune3h has dropped from it); readers that touch g.turns / g.by_champ pay ~30 ms/game to build the rows.

usage:
  python3 -I tools/lab/gamesum.py build [--from-index] [--since vNNN|-K] [--jobs N] [--retry] [--if-older SECS] [--quiet]
      every gameindex row with a replay on disk (form replay|zip) and version >= since (-K: newest indexed version minus K)
      that has no current store file. Heavy runs: systemd-run --user --unit nova-tb-gamesum -p MemoryMax=8G
      --working-directory=/homes/USER/cambc nice -n 10 python3 -I tools/lab/gamesum.py build --jobs 3
  python3 -I tools/lab/gamesum.py load ID          one game's summary line (checks the file loads)
  python3 -I tools/lab/gamesum.py status [--since vNNN]   rows indexed / stored / missing / failed

Python API (sys.path.insert(0, '/homes/USER/cambc/tools/lab'); import gamesum as GS):
  GS.load(id, us=None) -> SumGame, a replay.Game subclass (g.us from gameindex's our_seat unless us='A'|'B'), plus g.gid, g.row
      (the gameindex row dict: id path our_seat version foe map result lane created dup_key form); g.series(body, col) -> numpy
      array of that body's values of a turnCols column ('x','y','hp','maxHp','gems','gold','earned','alive',...) in round order;
      g.column(col), g.turn_r, g.turn_c (per turn, all bodies), g.kinds (acts digest). KeyError if the game is not stored.
      g.summary (10 Nov): {'lu': {'a': [kit per body], 'b': [...]}, 'cs': {'a': [[kills, deaths, gold earned, gems tributed] per
      body], 'b': [...]}, 'fk': [round, killer label, kit, victim label, kit]} (first champion kill; absent when none); bodies in id
      order = g.label order (A 1..6, B K L N P R S); the same fields as condab's OTF_GAMES records. Stored at build from the
      decoder's stats (exact); files built before 10 Nov compute it on load from events + turn columns (kills/earned from the
      last turn row, so a final-round kill or income can be missing: 3 of 418 bodies' earned gold differed in a check).
  GS.iter(since=None, lane=None, foe=None, result=None, versions=None, ids=None, dedup=True, seat_known=True, missing='skip')
      -> yields Games (one per dup_key when dedup). foe: case-insensitive substring; lane/result: exact or a set; missing='load'
      decodes a game that is not stored yet through replay.load (and does not store it).
  GS.rows(...) the same filters, yielding gameindex row dicts only (no load).

Switching a census reader (e.g. econ_readers_1109/monoclear.py) from replay.load to gamesum:
    # before: glob climb games.tsv + plat dirs, then for each:  g = R.load(path, us=seat.upper())
    #         and a hand-made dedup on (W, H, last_round, str(final))
    import sys; sys.path.insert(0, '/homes/USER/cambc/tools/lab'); import replay as R, gamesum as GS
    for g in GS.iter(since='v697', result={'win', 'loss'}):   # deduped by replay bytes; seat from gameindex
        ui = g.us                                               # 0/1, as replay.load sets it
        mono = {gi for gi, G in g.groups.items() if G['types'].get('monolith')}
        caps = [e for e in g.events if e[1] == 'capture' and e[3] == ui]     # events: no turn rows built (fast)
        for b, tm in g.team_of.items():                         # numpy per-body series: also fast
            r, gold = g.series(b, 'r'), g.series(b, 'gold')     # g.kinds[i]: turn i's action kinds ('x a rc')
            gold600 = int(gold[r <= 600][-1]) if (r <= 600).any() else 0
        acts = R.classify_all(g)                                # helpers and g.by_champ / g.turns work as before
        print(g.gid, g.row['version'], g.row['foe'], g.row['map'], g.row['result'], len(caps))
Run `gamesum.py build --since v697` first if the store lags (livepipe refreshes it hourly for the newest 50 versions).
"""
import argparse
import collections
import os
import pickle
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay as R  # noqa: E402

try:
    from compression import zstd  # Python 3.14 stdlib
except ImportError:  # pragma: no cover
    zstd = None

ST = "/data/USER/st"
STORE = os.path.join(ST, "gamesum")
INDEX = os.path.join(ST, "gameindex.tsv")
FAIL = os.path.join(STORE, "fail.tsv")
STAMP = os.path.join(STORE, ".last_build")
LOG = os.path.join(STORE, "build.log")
FMT = 2
DROP = ("stats", "decoder")


def _vnum(v):
    return int(v[1:]) if v and v[0] == "v" and v[1:].isdigit() else -1


def fname(dup_key):
    return os.path.join(STORE, dup_key.replace(":", "_") + ".gs2")


def read_index(path=INDEX):
    rows = []
    with open(path) as f:
        cols = f.readline().rstrip("\n").split("\t")
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) == len(cols):
                rows.append(dict(zip(cols, p)))
    return rows


_IDX = {}


def _index():
    st = os.stat(INDEX)
    if _IDX.get("m") != (st.st_mtime, st.st_size):
        _IDX.clear()
        _IDX["m"] = (st.st_mtime, st.st_size)
        _IDX["rows"] = read_index()
        _IDX["by_id"] = {r["id"]: r for r in _IDX["rows"]}
    return _IDX


def _since(since, rows):
    if since is None:
        return -1
    s = str(since)
    if s.startswith("-"):
        return max((_vnum(r["version"]) for r in rows), default=0) - int(s[1:])
    return _vnum(s if s.startswith("v") else "v" + s)


def _as_set(x):
    return None if x is None else ({x} if isinstance(x, str) else set(x))


def rows(since=None, lane=None, foe=None, result=None, versions=None, ids=None, dedup=True, seat_known=True):
    """gameindex rows (dicts) with a replay on disk, filtered; dedup keeps the first id of each dup_key."""
    allr = _index()["rows"]
    lo = _since(since, allr)
    lane, result, versions = _as_set(lane), _as_set(result), _as_set(versions)
    ids = set(ids) if ids is not None else None
    foe = foe.lower().replace("_", " ") if foe else None
    seen = set()
    for r in allr:
        if r["form"] not in ("replay", "zip") or r["dup_key"] in ("", "-"):
            continue
        if ids is not None and r["id"] not in ids:
            continue
        if lo >= 0 and _vnum(r["version"]) < lo:
            continue
        if versions and r["version"] not in versions:
            continue
        if lane and r["lane"] not in lane or result and r["result"] not in result:
            continue
        if foe and foe not in r["foe"].lower().replace("_", " "):
            continue
        if seat_known and r["our_seat"] not in ("a", "b"):
            continue
        if dedup:
            if r["dup_key"] in seen:
                continue
            seen.add(r["dup_key"])
        yield r


class SumGame(R.Game):
    """replay.Game rebuilt from a gamesum file. Everything but the turn rows is built at load (~2 ms); g.turns / g.by_champ (and
    g.d['turns']) are materialized, identical to replay.load's, on first use (~12 ms: the acts lists are most of it). Numeric reads
    that skip the rows: g.series(body, col) (numpy array of that body's values in round order), g.column(col) (every turn),
    g.turn_r / g.turn_c (each turn's round and body), g.kinds (each turn's action kinds, e.g. 'x a rc': the acts digest)."""
    _ready = False

    def __init__(self, blob):
        self._blob = blob
        d = pickle.loads(zstd.decompress(blob["H"]))
        d["turns"] = []
        cols = d["turnCols"]
        self._tcol = {c: k for k, c in enumerate(cols)}
        M = np.frombuffer(zstd.decompress(blob["M"]), dtype=blob["dtype"]).reshape(blob["shape"])
        self._M, self._intc, self._objc = M, blob["intc"], blob["objc"]
        self._mk = {j: k for k, j in enumerate(self._intc)}
        self._obj = None
        R.Game.__init__(self, d, blob["meta"])
        self._ready, self._turns, self._bc = True, None, None
        self.turn_r = M[:, self._mk[self._tcol["r"]]]
        self.turn_c = M[:, self._mk[self._tcol["c"]]]

    def _objs(self):
        if self._obj is None:
            self._obj = pickle.loads(zstd.decompress(self._blob["O"]))
        return self._obj

    @property
    def kinds(self):
        return self._objs()["kinds"]

    def column(self, col):
        j = self._tcol[col]
        if j in self._mk:
            return self._M[:, self._mk[j]]
        if col == "acts":
            return [t[-1] for t in self.turns]
        return self._objs()["cols"][self._objc.index(j)]

    def series(self, body, col):
        sel = np.flatnonzero(self.turn_c == body)
        v = self.column(col)
        return v[sel] if isinstance(v, np.ndarray) else [v[i] for i in sel]

    def _materialize(self):
        if self._turns is None:
            n = len(self._tcol)
            cols = [None] * n
            for j, k in self._mk.items():
                cols[j] = self._M[:, k].tolist()
            ob = self._objs()["cols"]
            for k, j in enumerate(self._objc):
                cols[j] = ob[k]
            cols[n - 1] = pickle.loads(zstd.decompress(self._blob["A"]))
            self._turns = list(map(list, zip(*cols))) if len(self._M) else []
            self.d["turns"] = self._turns
            bc = collections.defaultdict(list)
            for t in self._turns:
                bc[t[1]].append(t)
            self._bc = bc
        return self._turns

    @property
    def turns(self):
        if not self._ready:
            return self.__dict__.get("_turns0", [])
        return self._materialize()

    @turns.setter
    def turns(self, v):
        self.__dict__["_turns0"] = v

    @property
    def by_champ(self):
        if not self._ready:
            return self.__dict__["_bc0"]
        self._materialize()
        return self._bc

    @by_champ.setter
    def by_champ(self, v):
        self.__dict__["_bc0"] = v


def _series(self, body, col):
    """replay.Game (from replay.load / missing='load'): the same call as SumGame.series, as a list."""
    i = self.ci[col]
    return [t[i] for t in self.by_champ.get(body, ())]


R.Game.series = _series


def _read(path):
    with open(path, "rb") as f:
        return pickle.loads(f.read())


def game_from(blob, row, us=None):
    if blob.get("fmt") != FMT:
        raise ValueError(f"gamesum: file format {blob.get('fmt')} != {FMT}; run gamesum.py build")
    g = SumGame(blob)
    seat = (us or row.get("our_seat") or "").upper()
    if seat in ("A", "B"):
        g.us = "AB".index(seat)
    else:
        side = blob["meta"].get("side")
        if side not in ("A", "B"):
            raise ValueError(f"gamesum.load({row.get('id')}): our seat is unknown in gameindex; pass us='A'|'B'")
        g.us = "AB".index(side)
    g.gid, g.row = row.get("id"), row
    return g


def load(gid, us=None):
    """gid: a full match id from gameindex.tsv (or a unique prefix of 8+ characters)."""
    by = _index()["by_id"]
    row = by.get(gid)
    if row is None and len(gid) >= 8:
        hits = [r for k, r in by.items() if k.startswith(gid)]
        row = hits[0] if len(hits) == 1 else None
    if row is None or row["dup_key"] in ("", "-"):
        raise KeyError(f"gamesum: {gid} is not in {INDEX} with a replay")
    p = fname(row["dup_key"])
    if not os.path.exists(p):
        raise KeyError(f"gamesum: {gid} not stored ({p}); run gamesum.py build")
    return game_from(_read(p), row, us)


def iter(since=None, lane=None, foe=None, result=None, versions=None, ids=None, dedup=True, seat_known=True,  # noqa: A001
         missing="skip"):
    for r in rows(since, lane, foe, result, versions, ids, dedup, seat_known):
        p = fname(r["dup_key"])
        if os.path.exists(p):
            try:
                yield game_from(_read(p), r)
                continue
            except Exception:  # noqa: BLE001 - a damaged file: treat as missing
                pass
        if missing == "load":
            g = R.load(r["path"], us=r["our_seat"].upper())
            g.gid, g.row = r["id"], r
            yield g


# ---------------------------------------------------------------- per-game summary (lineups, per-champion stats, first kill)
KITS = ("ryth", "vesper", "vendetta", "cassi", "issac", "stellar", "prism", "marcella", "willow", "ren", "varg", "tavi", "heart")  # champion_type


def _kit(b):
    t = b.get("type")
    return KITS[t] if isinstance(t, int) and 0 <= t < len(KITS) else str(b.get("name", "?")).split("_")[0]


def summary_from(bodies, events, labels, per_body):
    """bodies: the decoder's body dicts; events: kill-credit-repaired events; labels {id: label}; per_body(id) -> [k, d, gold, trib]."""
    lu, cs = {"a": [], "b": []}, {"a": [], "b": []}
    kit = {}
    for b in sorted(bodies, key=lambda b: b["id"]):
        s = "ab"[b["team"]]
        kit[b["id"]] = _kit(b)
        lu[s].append(kit[b["id"]])
        cs[s].append([int(v) for v in per_body(b["id"])])
    out = {"lu": lu, "cs": cs}
    for e in events:  # [round, 'death', victim, cause (1 = champion), killer, ...], in game order
        if e[1] == "death" and e[3] == 1 and e[4] in kit and e[2] in kit:
            out["fk"] = [int(e[0]), labels[e[4]], kit[e[4]], labels[e[2]], kit[e[2]]]
            break
    return out


def _labels(bodies):
    lab, k = {}, [0, 0]
    for b in sorted(bodies, key=lambda b: b["id"]):
        t = b["team"]
        lab[b["id"]] = str(k[t] + 1) if t == 0 else R.LABEL_B[k[t]]
        k[t] += 1
    return lab


def summary_decoded(d):
    """From the decoder's dict with its 'stats' (build time): per-body numbers exactly as the engine counts them."""
    st = {b["id"]: b for b in (d.get("stats") or {}).get("bodies", [])}
    if not st:
        return None
    team_of = {b["id"]: b["team"] for b in d["bodies"]}
    ev = [list(e) for e in d["events"] if e[1] == "death"]
    R.repair_kill_credit(ev, team_of)
    return summary_from(d["bodies"], ev, _labels(d["bodies"]),
                        lambda i: [st[i][k] for k in ("kills", "deaths", "earnedGold", "gemsTributed")] if i in st else [0, 0, 0, 0])


def _summary(self):
    """g.summary: see the module doc."""
    c = self.__dict__.get("_summary_c")
    if c is not None:
        return c
    blob = self.__dict__.get("_blob") or {}
    c = blob.get("S") or (summary_decoded(self.d) if self.d.get("stats") else None)
    if c is None:  # an older gamesum file: events + the last turn row of each body
        trib = collections.Counter()
        deaths = collections.Counter()
        for e in self.events:
            if e[1] == "tribute":
                trib[e[2]] += e[4]
            elif e[1] == "death":
                deaths[e[2]] += 1

        def last(i, col):
            v = self.series(i, col)
            return int(max(v)) if len(v) else 0
        c = summary_from(self.d["bodies"], self.events, self.label,
                         lambda i: [last(i, "kills"), deaths[i], last(i, "earned"), trib[i]])
    self.__dict__["_summary_c"] = c
    return c


R.Game.summary = property(_summary)


# ---------------------------------------------------------------- build
def pack(d, meta, dup_key, summ=None):
    """The decoded dict -> file bytes: header (all but the turn rows, pickled), the turn columns that are ints in this game as one
    int matrix, the other scalar columns (floats in shield/focus/strength) and each turn's action-kind digest as lists, the acts
    lists on their own; each part zstd'd so a load decompresses only what it reads."""
    T = d.pop("turns")
    cols = d["turnCols"]
    assert cols[-1] == "acts", cols
    n = len(cols) - 1
    intc = [j for j in range(n) if all(type(t[j]) is int for t in T)]
    objc = [j for j in range(n) if j not in intc]
    M = np.array([[t[j] for j in intc] for t in T], dtype=np.int64).reshape(len(T), len(intc))
    dt = "<i4" if not len(M) or (M.max() < 2 ** 31 and M.min() >= -2 ** 31) else "<i8"
    M = M.astype(dt)
    kinds = [sys.intern(" ".join(dict.fromkeys(a[0] for a in t[-1] if a))) for t in T]
    blob = {"fmt": FMT, "rdec": d.get("rdec") or R.rdec_id(), "dup_key": dup_key, "meta": meta,
            "H": zstd.compress(pickle.dumps(d, protocol=5), 10),
            "M": zstd.compress(M.tobytes(), 10), "dtype": dt, "shape": M.shape, "intc": intc, "objc": objc,
            "O": zstd.compress(pickle.dumps({"cols": [[t[j] for t in T] for j in objc], "kinds": kinds}, protocol=5), 10),
            "A": zstd.compress(pickle.dumps([t[-1] for t in T], protocol=5), 10)}
    if summ:
        blob["S"] = summ  # g.summary (10 Nov), from the decoder's stats
    d["turns"] = T
    return pickle.dumps(blob, protocol=5)


def _one(job):
    """Worker: decode one replay (replay.py's locate + decode_bytes, so the cache and checks are the same) and store it."""
    path, dup_key, rid = job
    try:
        raw, d, summary, meta = R.locate(path)
        if d is None:
            d = R.decode_bytes(raw, summary, src=path)  # 10 Nov: a DecodeTimeout lands in fail.tsv like any failed decode
        try:
            summ = summary_decoded(d)
        except Exception:  # noqa: BLE001 - the summary is extra; load computes it when absent
            summ = None
        for k in DROP:
            d.pop(k, None)
        b = pack(d, meta, dup_key, summ)
        out = fname(dup_key)
        tmp = f"{out}.{os.getpid()}.part"
        with open(tmp, "wb") as f:
            f.write(b)
        os.replace(tmp, out)
        return rid, dup_key, len(b), None
    except BaseException as e:  # noqa: BLE001 - decode_bytes sys.exits on a failed decode
        return rid, dup_key, 0, f"{type(e).__name__}: {str(e)[:200]}".replace("\t", " ").replace("\n", " ")


def _current(p, rid):
    """True when the stored file exists and was decoded by the current rdec.js (reads only the header fields)."""
    if not os.path.exists(p):
        return False
    try:
        b = _read(p)
        return b.get("rdec") == rid and b.get("fmt") == FMT
    except Exception:  # noqa: BLE001
        return False


def _log(msg, quiet=False):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    if not quiet:
        print(line, flush=True)


def build(a):
    if zstd is None:
        sys.exit("gamesum needs compression.zstd (Python 3.14)")
    os.makedirs(STORE, exist_ok=True)
    if a.if_older and os.path.exists(STAMP) and time.time() - os.path.getmtime(STAMP) < a.if_older:
        return 0
    failed = set()
    if os.path.exists(FAIL) and not a.retry:
        failed = {ln.split("\t")[0] for ln in open(FAIL) if ln.strip()}
    rid = R.rdec_id()
    todo, seen = [], set()
    have = {n[:-4] for n in os.listdir(STORE) if n.endswith(".gs2")}
    for r in rows(since=a.since, dedup=True, seat_known=False):
        k = r["dup_key"]
        if k in seen or k in failed:
            continue
        seen.add(k)
        if k.replace(":", "_") in have and not a.check_rdec:
            continue
        if k.replace(":", "_") in have and _current(fname(k), rid):
            continue
        if os.path.exists(r["path"]):
            todo.append((r["path"], k, r["id"]))
    _log(f"build since={a.since} jobs={a.jobs}: {len(seen)} distinct replays, {len(todo)} to store", a.quiet)
    t0, n, nb, nf = time.time(), 0, 0, 0
    if todo:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(max(1, a.jobs), maxtasksperchild=200) as pool, open(FAIL, "a") as ff:
            for gid, k, size, err in pool.imap_unordered(_one, todo, chunksize=4):
                if err:
                    nf += 1
                    ff.write(f"{k}\t{gid}\t{err}\n")
                    ff.flush()
                else:
                    n += 1
                    nb += size
                if not a.quiet and (n + nf) % 500 == 0:
                    _log(f"  {n + nf}/{len(todo)} in {time.time() - t0:.0f}s, load {open('/proc/loadavg').read().split()[0]}")
    open(STAMP, "w").close()
    _log(f"build done: stored {n} ({nb / 1e6:.1f} MB), failed {nf}, {time.time() - t0:.0f}s", a.quiet)
    return 0


def status(a):
    allr = list(rows(since=a.since, dedup=True, seat_known=False))
    have = {n[:-4] for n in os.listdir(STORE) if n.endswith(".gs2")} if os.path.isdir(STORE) else set()
    failed = {ln.split("\t")[0] for ln in open(FAIL) if ln.strip()} if os.path.exists(FAIL) else set()
    st = sum(r["dup_key"].replace(":", "_") in have for r in allr)
    fl = sum(r["dup_key"] in failed for r in allr)
    by = collections.Counter(r["version"] for r in allr if r["dup_key"].replace(":", "_") not in have)
    print(f"distinct replays {len(allr)}: stored {st}, failed {fl}, missing {len(allr) - st - fl}; store files {len(have)}")
    if by:
        print("missing by version (top 10):", ", ".join(f"{v} {c}" for v, c in by.most_common(10)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--from-index", action="store_true", help="(default) rows from gameindex.tsv")
    b.add_argument("--since", default=None)
    b.add_argument("--jobs", type=int, default=3)
    b.add_argument("--retry", action="store_true", help="retry dup_keys listed in fail.tsv")
    b.add_argument("--check-rdec", action="store_true", help="also redo stored files decoded by another rdec.js (reads each)")
    b.add_argument("--if-older", type=float, default=0, help="skip when the last build finished under SECS ago")
    b.add_argument("--quiet", action="store_true")
    ld = sub.add_parser("load")
    ld.add_argument("id")
    ld.add_argument("--us", default=None)
    s = sub.add_parser("status")
    s.add_argument("--since", default=None)
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a)
    if a.cmd == "status":
        return status(a)
    t = time.time()
    g = load(a.id, a.us)
    caps = collections.Counter(e[3] for e in g.events if e[1] == "capture")
    deaths = collections.Counter(g.team_of.get(e[2]) for e in g.events if e[1] == "death" and e[3] == 1)
    print(f"{g.gid} {g.row['version']} us={'AB'[g.us]} foe={g.row['foe']} map={g.row['map']} {g.row['result']} "
          f"rounds={g.last_round} turns={len(g.turns)} events={len(g.events)} captures us/foe {caps[g.us]}/{caps[1 - g.us]} "
          f"deaths us/foe {deaths[g.us]}/{deaths[1 - g.us]} ({(time.time() - t) * 1000:.0f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
