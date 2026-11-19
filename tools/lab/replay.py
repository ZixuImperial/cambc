#!/usr/bin/env python3
"""In-depth analysis of cambc replays: what every champion did, turn by turn, not just the totals.

usage: python3 -I tools/lab/replay.py COMMAND GAME [options]
  GAME: a live match id (or its first 8+ characters; found in /data/USER/plat/*/x_<id>/replay.repl26a),
        RUN:ID (a local abl.sh game whose replay was kept: KEEP=1 abl.sh or `restat.py --keep RUNDIR`),
        a .repl26a file (raw or the zip bundle run-batch writes), or a decoded .json / .json.gz.
  Replays are decoded by /homes/USER/condor-work/tools/rdec.js (the real engine replaying the game, 1-6 s;
  engines 1.0.0-1.0.3 in condor-work/engine) and cached in /data/USER/rdec_cache.
  --us A|B|BOT: our team, or (local games) the bot whose side is "us" wherever it played, e.g. --us nova_m18c
        (default: the live side from matches.txt; team A for local games).

commands (all read one game unless noted):
  info               teams, drafts, result, per-champion totals
  timeline [--every 50]   the race every N rounds: tributed, carried, gold, kills, alive, and what happened
  moments            key moments: lead changes, fights, big bag losses, deaths to monsters, contested captures,
                     captures stolen after a clear, fuel exhaustion, long idle stretches
  show --round R [--box x0,y0,x1,y1 | --around LABEL[,radius]] [--trail LABEL[,N]]   ASCII map at the start of round R with every
                     (--trail: that body's path over the N (20) rounds before R as letters a..z, map framed on it)
                     champion (HP, carried gems, channel), camps alive, wards and camp groups' capture state
  track --champ LABEL [--from R] [--to R]   one champion turn by turn: position, zone, HP, gems, nearest enemy,
                     what it did (moves, attacks with damage, casts, tribute, recall, shop)
  activity           time budget of every champion: dead, recall, tribute, fight, farm, capture, shop, walk,
                     idle; distance walked, zones, cohesion
  fights [--all]     fight reconstruction: rounds, place, zone, numbers at the start, damage, deaths, gems lost
  presence [--radius 5]   per camp group: our and their body-rounds nearby, damage dealt, clears, captures
  group GAME GID     one camp group's story: respawns, who was near, damage, kills, capture starts/resets/captures
  diff GAME2         compare with another game on the same map (e.g. candidate vs base in the same seat): first
                     divergence, the race side by side, activity side by side
  report GAME... [--out FILE] [--jobs N]   replay-based aggregates over many games (a live set dir expands to its
                     games): time budgets, fights by numbers, presence on contested groups, in wins and losses
  warm GAME... [--jobs 2]   decode games into the cache ahead of a read (under nice 10; set and run dirs expand):
                     a first read of an undecoded game, or of one cached by an older rdec.js (~22% of the cache on
                     26 Oct), pays the 1-20 s engine replay; a cached read takes ~0.15 s
Champion labels: team A bodies are 1-6, team B bodies are K L N P R S (in body order); the ASCII legend lists them.
"""
import collections
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile

RDEC = "/homes/USER/condor-work/tools/rdec.js"
DECODE_TIMEOUT = float(os.environ.get("REPLAY_DECODE_TIMEOUT", "120") or 120)  # 10 Nov (b1815: some replays never finish decoding): s
DECODE_TIMEOUT_LOG = "/data/USER/st/bq/decode_timeouts.log"  # one line per timed-out replay (main machine only)


class DecodeTimeout(RuntimeError):
    """A replay decode ran past REPLAY_DECODE_TIMEOUT (default 120 s) and was killed. Readers count it as a failed game."""


def _note_timeout(src, what):
    import time
    if not os.path.exists("/data/USER/st/bq/live.txt"):
        return
    try:
        with open(DECODE_TIMEOUT_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{src or '?'}\t{what}\tpid {os.getpid()}\n")
    except OSError:
        pass
CACHE = os.environ.get("RDEC_CACHE") or (os.path.exists("/data/USER/st/bq/live.txt") and "/data/USER/rdec_cache" or os.path.join(os.environ.get("_CONDOR_SCRATCH_DIR") or "/tmp", "USER-rdec_cache"))  # 10 Nov: /data on the main machine only  # readmany.py: nodes cache on the shared scratch
PLAT = "/data/USER/plat"
ABL = "/data/USER/abl"
CAMP_CH = "weg$MG"  # wolf, elk, gem cluster, gold cluster, monolith, golem
CAMP_NAMES = ["wolf", "elk", "gem_cluster", "gold_cluster", "monolith", "golem"]
LABEL_B = "KLNPRS"
DIRS8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


# ---------------------------------------------------------------- locating and decoding replays
PREFER = {}  # match id -> the set dir it was expanded from (expand_specs), searched before the other plat sets


def _live_lookup(gid, prefer=None):
    """A live match's replay, summary and meta. A match stored in several sets takes its meta (side, result, opponent)
    from the preferred set: the one given, or the set expand_specs found it in, else the first plat set holding it."""
    if len(gid) < 8 or "/" in gid or ":" in gid:
        return None
    pref = prefer or next((v for k, v in PREFER.items() if k.startswith(gid)), None)
    dirs = [os.path.join(PLAT, sd) for sd in sorted(os.listdir(PLAT))]
    if pref:
        dirs = [os.path.abspath(pref)] + [d for d in dirs if os.path.abspath(d) != os.path.abspath(pref)]
    if len(gid) < 36:  # Econ 5 Nov: games of one match group share their first 13 characters; a short prefix must not pick one
        ids = set()
        for d in dirs:
            if os.path.isdir(d):
                ids |= {x[2:] for x in os.listdir(d) if x.startswith("x_" + gid)}
        if len(ids) > 1:
            sys.exit(f"replay: {gid} matches {len(ids)} games ({', '.join(sorted(ids)[:4])}{' ...' if len(ids) > 4 else ''}): give the full match id")
    for d in dirs:
        sd = os.path.basename(d)
        if not os.path.isdir(d):
            continue
        for x in os.listdir(d):
            if x.startswith("x_" + gid):
                mid = x[2:]
                rp = os.path.join(d, x, "replay.repl26a")
                if os.path.exists(rp):
                    meta = {"source": "live", "set": sd, "match": mid}
                    mf = os.path.join(d, "matches.txt")
                    if os.path.exists(mf):
                        for line in open(mf):
                            p = line.split()
                            if p and p[0] == mid and len(p) >= 5:
                                meta.update(map=p[1], side=p[2].upper(), result=p[3], opponent=p[4])
                    if "side" not in meta:
                        # Shared replays have no matches.txt: the platform hands us only OUR team's logs
                        # (team-a.* or team-b.*), so their name gives our side (agrees with matches.txt 70/70, 31 Oct).
                        own = {f[5] for f in os.listdir(os.path.join(d, x)) if f.startswith("team-") and len(f) > 6}
                        if len(own) == 1 and own <= {"a", "b"}:
                            meta["side"] = own.pop().upper()
                            meta["side_from"] = "team-log files"
                    sm = os.path.join(d, mid + ".json")
                    return rp, (sm if os.path.exists(sm) else None), meta
    return None


def _raw_replay(path):
    """Replay bytes: run-batch writes zip bundles (replay.repl26a + team logs); platform replays are raw."""
    b = open(path, "rb").read()
    if b[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            return z.read("replay.repl26a")
    return b


def locate(spec):
    """GAME spec -> (raw replay bytes or None, decoded dict or None, summary path, meta)."""
    if os.path.exists(spec) and (spec.endswith(".json") or spec.endswith(".json.gz")):
        op = gzip.open if spec.endswith(".gz") else open
        return None, json.load(op(spec, "rt")), None, {"source": "file", "file": spec}
    if os.path.exists(spec):
        xdir = os.path.dirname(os.path.abspath(spec))
        x = os.path.basename(xdir)
        # a live bundle's replay: its side and statistics, from the set dir that holds this file
        hit = _live_lookup(x[2:], prefer=os.path.dirname(xdir)) if x.startswith("x_") else None
        if hit and os.path.samefile(hit[0], spec):
            return _raw_replay(spec), None, hit[1], hit[2]
        return _raw_replay(spec), None, None, {"source": "file", "file": spec}
    if ":" in spec:
        run, gid = spec.split(":", 1)
        rd = run if os.path.isabs(run) else os.path.join(ABL, run)  # a run name in ABL, or a run dir's path
        rp = os.path.join(rd, "rep", gid + ".repl26a")
        meta = {"source": "local", "run": run, "game": gid}
        gl = os.path.join(rd, "games.list")
        if os.path.exists(gl):
            for line in open(gl):
                p = line.split()
                if p and p[0] == gid:
                    meta.update(a=p[1], b=p[2], map=p[3])
        if not os.path.exists(rp):
            sys.exit(f"no replay {rp}: abl.sh keeps replays only with KEEP=1; `python3 -I tools/lab/restat.py --keep {rd}` "
                     f"re-simulates the run and keeps them")
        sm = os.path.join(rd, "st", gid + ".json")  # kept statistics: rdec.js checks the decode against them
        return _raw_replay(rp), None, (sm if os.path.exists(sm) else None), meta
    hit = _live_lookup(spec)
    if hit:
        rp, sm, meta = hit
        return _raw_replay(rp), None, sm, meta
    sys.exit(f"cannot find game {spec!r} (live match id, RUN:ID, .repl26a or decoded .json)")


RDEC_CACHED = "431dce932f15"  # rdec.js (21 Oct) that wrote the cache entries without an "rdec" field
_rdec_id = []


def rdec_id():
    """sha1 of rdec.js: a decode cached by another rdec.js is decoded again, so a decoder fix reaches cached games."""
    if not _rdec_id:
        try:
            _rdec_id.append(hashlib.sha1(open(RDEC, "rb").read()).hexdigest()[:12])
        except OSError:
            _rdec_id.append("?")
    return _rdec_id[0]


def decode_bytes(raw, summary=None, src=None):
    """rdec.js decode with a content-addressed cache (decoding replays the whole game in the engine: 1-6 s with rdec.js,
    0.1-1.5 s natively through tools/cxe/cxedec.py, which gives the same JSON and is tried first).
    10 Nov: the decode has REPLAY_DECODE_TIMEOUT s (default 120, both decoders together); past it the decoder is killed, the replay
    (src, when given) is logged to DECODE_TIMEOUT_LOG and DecodeTimeout is raised."""
    import time
    t0 = time.time()
    h = hashlib.sha1(raw).hexdigest()[:16]
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, h + ".json.gz")
    if os.path.exists(cp):
        try:
            with gzip.open(cp, "rt") as f:
                d = json.load(f)
            if d.get("rdec", RDEC_CACHED) == rdec_id():
                return d
        except (OSError, ValueError, EOFError):  # a cache file cut short raises EOFError: decode again
            pass
    rp = os.path.join(CACHE, f".{h}.{os.getpid()}.repl26a")
    op = os.path.join(CACHE, f".{h}.{os.getpid()}.json")
    open(rp, "wb").write(raw)
    d = None
    try:  # tools/cxe/cxedec.py: rdec.js ported to cxe (identical output, ~4x faster); None -> rdec.js
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cxe"))
        import cxedec
        d = cxedec.decode(rp, None, summary, timeout=DECODE_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - any failure of the fast path falls back to rdec.js; a timeout does not (the game hangs both)
        if type(e).__name__ == "DecodeTimeout":
            os.remove(rp)
            _note_timeout(src, "cxedec")
            raise DecodeTimeout(f"decode of {src or 'replay'} ran over {DECODE_TIMEOUT:.0f} s (cxedec)") from None
        d = None
    if d is None:
        cmd = ["node", RDEC, rp, op] + (["--summary", summary] if summary else [])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=max(5.0, DECODE_TIMEOUT - (time.time() - t0)))
        except subprocess.TimeoutExpired:
            for x in (rp, op):
                if os.path.exists(x):
                    os.remove(x)
            _note_timeout(src, "rdec.js")
            raise DecodeTimeout(f"decode of {src or 'replay'} ran over {DECODE_TIMEOUT:.0f} s (rdec.js)") from None
        if r.returncode != 0 or not os.path.exists(op):
            os.remove(rp)
            sys.exit(f"rdec.js failed: {(r.stdout + r.stderr)[-400:]}")
        d = json.load(open(op))
        os.remove(op)
    os.remove(rp)
    d["rdec"] = rdec_id()
    with gzip.open(cp + f".{os.getpid()}", "wt") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(cp + f".{os.getpid()}", cp)
    return d


def seat_of(path):
    """'A' or 'B' from a replay file name that ends in a seat tag before .repl26a (NAME_A.repl26a, NAME__b.repl26a, NAME-B...),
    else None. Readers that name kept games by seat should take the seat from here, not by slicing the name."""
    m = re.search(r"[_.\-]([ABab])\.repl26a$", os.path.basename(str(path)))
    return m.group(1).upper() if m else None


def reader_seat(path, meta=None):
    """11 Nov (Builder; b1979 read team B on every readmany-staged copy): the seat a reader must use, 'A' or 'B'. meta["seat"]
    (readmany passes it from matches.txt / set.json / the source name) first, then a seat tag in the file name (seat_of);
    neither -> ValueError, never a guess. Readers: g = replay.load(path, us=replay.reader_seat(path, meta)), and return
    "us": g.us so readmany's SEAT MISMATCH guard can check it."""
    sm = str((meta or {}).get("seat", "")).strip().upper()
    if sm in ("A", "B"):
        return sm
    st = seat_of(path)
    if st:
        return st
    raise ValueError(f"reader_seat: no seat for {path} (meta {meta!r}): pass it in meta or tag the name NAME__a/NAME__b")


def load(spec, us=None):
    """us: 'A' or 'B' (any case), or a bot name in this game (local games: our side is wherever that bot played).
    3 Nov (Deep research: dr17/dr20/dr45 read the spar's side in every B-seat game; a name sliced with [:-9] passed us=''):
    an empty or unknown us raises ValueError. With us=None the side comes from the source (matches.txt, team logs) or the
    file name (seat_of); if none gives it, ValueError too. REPLAY_ASSUME_A=1 restores the old guess (team A, with a warning)."""
    raw, d, summary, meta = locate(spec)
    if d is None:
        d = decode_bytes(raw, summary, src=spec)
    chk = d.get("check") or {}
    if chk.get("ok") is False:  # rdec.js compared the decode with the match statistics (live games, kept st/)
        print(f"!! {spec}: the decoded replay disagrees with the match statistics: {'; '.join(chk.get('diffs', [])[:4])}",
              file=sys.stderr)
    g = Game(d, meta)
    if us is not None:
        u = str(us).strip()
        if u.upper() in ("A", "B"):
            g.us = "AB".index(u.upper())
        elif u and meta.get("a") == u:
            g.us = 0
        elif u and meta.get("b") == u:
            g.us = 1
        else:
            raise ValueError(f"replay.load({spec!r}): us={us!r} is not 'A', 'B' or a bot of this game "
                             f"(a={meta.get('a')!r}, b={meta.get('b')!r})")
        return g
    side = meta.get("side") or seat_of(spec)
    if side in ("A", "B"):
        g.us = "AB".index(side)
    elif os.environ.get("REPLAY_ASSUME_A") == "1":
        print(f"!! {spec}: our side is unknown: ASSUMING TEAM A (REPLAY_ASSUME_A=1)", file=sys.stderr)
        g.us = 0
    else:
        raise ValueError(f"replay.load({spec!r}): our side is unknown (no us=, no matches.txt or team logs, no seat in the "
                         f"file name): pass us='A'|'B' (e.g. replay.seat_of(path), or meta['seat'] in readmany)")
    return g


# ---------------------------------------------------------------- the decoded game
def repair_kill_credit(events, team_of):
    """rdec.js names, for every death of a step, the last body whose kill count rose in that step. In a mutual kill
    (Ren's retaliation kills the attacker that kills Ren) both deaths then name the same body, and one victim is its
    own killer. Credit that death to the enemy that died in the same step, as the engine's statistics do."""
    n = 0
    for i, e in enumerate(events):
        if e[1] != "death" or e[3] != 1 or team_of.get(e[4], -1) != team_of.get(e[2]):
            continue
        j, k = i, i + 1  # the run of deaths in the same round and step around e
        while j > 0 and events[j - 1][1] == "death" and events[j - 1][0] == e[0] and events[j - 1][8:] == e[8:]:
            j -= 1
        while k < len(events) and events[k][1] == "death" and events[k][0] == e[0] and events[k][8:] == e[8:]:
            k += 1
        foes = [x[2] for x in events[j:k] if team_of.get(x[2], team_of.get(e[2])) != team_of.get(e[2])]
        if len(foes) == 1:
            e[4] = foes[0]
            n += 1
    return n


class Game:
    def __init__(self, d, meta):
        self.d, self.meta = d, meta
        m = d["map"]
        self.W, self.H, self.rows = m["width"], m["height"], m["rows"]
        self.spawn = m["spawn"]
        self.altars = [tuple(a) for a in m["altars"]]
        self.camps = {c[0]: {"id": c[0], "type": c[1], "x": c[2], "y": c[3], "group": c[4], "hp": c[5]} for c in m["camps"]}
        self.groups = {}
        for gid, gems, gold, resp, cs in m["groups"]:
            pts = [(self.camps[c]["x"], self.camps[c]["y"]) for c in cs if c in self.camps]
            cx = sum(p[0] for p in pts) / max(1, len(pts))
            cy = sum(p[1] for p in pts) / max(1, len(pts))
            types = collections.Counter(CAMP_NAMES[self.camps[c]["type"]] for c in cs if c in self.camps)
            self.groups[gid] = {"id": gid, "gems": gems, "gold": gold, "respawn": resp, "camps": cs, "cx": cx, "cy": cy,
                                "pts": pts, "types": dict(types)}
        self.bodies = {b["id"]: b for b in d["bodies"]}
        self.team_of = {b["id"]: b["team"] for b in d["bodies"]}
        self.label = {}
        k = [0, 0]
        for b in sorted(d["bodies"], key=lambda b: b["id"]):
            t = b["team"]
            self.label[b["id"]] = str(k[t] + 1) if t == 0 else LABEL_B[k[t]]
            k[t] += 1
        cols = d["turnCols"]
        self.ci = {c: i for i, c in enumerate(cols)}
        self.turns = d["turns"]
        self.by_champ = collections.defaultdict(list)
        for t in self.turns:
            self.by_champ[t[1]].append(t)
        self.rounds = d["rounds"]
        self.events = d["events"]
        repair_kill_credit(self.events, self.team_of)
        self.final = d.get("final") or {}
        self.last_round = self.final.get("round") or (self.rounds[-1][0] if self.rounds else 0)
        side = meta.get("side")
        self.us = "AB".index(side) if side in ("A", "B") else 0  # load() sets or refuses the side (3 Nov)
        self._round_turns = None
        self._df = None
        self._pos_cache = {}
        self._zone = {}

    # names
    def team_name(self, t):
        """A DISPLAY label only (10 Nov, Econ/Coordinator pitfall): live games give "us" for our seat and the opponent's name (or "them")
        for the other; it never returns "BattleCats", so never derive a seat from it. Our seat is self.us (0 = A, 1 = B), set from
        meta["side"] by load(); the foe is 1 - self.us. Checked 10 Nov: replay.load and gamesum agree with gameindex our_seat on all
        585 v700+ games (296 seat B)."""
        m = self.meta
        if m.get("source") == "live":
            return "us" if t == self.us else m.get("opponent", "them")
        if m.get("source") == "local" and m.get("a"):
            return m["a"] if t == 0 else m["b"]
        return "team " + "AB"[t]

    def who(self, c):
        b = self.bodies.get(c, {})
        return f"{self.label.get(c, '?')}:{b.get('name', '?')}({'AB'[b.get('team', 0)]})"

    def col(self, t, name):
        return t[self.ci[name]]

    # geometry
    def walk_fields(self):
        if self._df is None:
            blocked = {(x, y) for y, row in enumerate(self.rows) for x, ch in enumerate(row) if ch in "#o"} | set(self.altars)
            out = []
            for s in self.spawn:
                src = [(x, y) for x in range(s[0], s[2]) for y in range(s[1], s[3])]
                d = {p: 0 for p in src}
                q = collections.deque(src)
                while q:
                    x, y = q.popleft()
                    for dx, dy in DIRS8:
                        p = (x + dx, y + dy)
                        if 0 <= p[0] < self.W and 0 <= p[1] < self.H and p not in blocked and p not in d:
                            d[p] = d[(x, y)] + 1
                            q.append(p)
                out.append(d)
            self._df = out
        return self._df

    def zone(self, x, y, team):
        """own / mid / enemy seen from `team`, by walk distance from the two spawns; 'offwalk' if not walkable."""
        z = self._zone.get((x, y, team))
        if z is None:
            z = "offwalk"
            df = self.walk_fields()
            me, them = df[team], df[1 - team]
            for dx, dy in ((0, 0),) + tuple(DIRS8):
                p = (x + dx, y + dy)
                if p in me and p in them:
                    r = me[p] / max(1, me[p] + them[p])
                    z = "own" if r < 0.4 else ("enemy" if r > 0.6 else "mid")
                    break
            self._zone[(x, y, team)] = z
        return z

    def positions_at(self, r):
        """{body: turn row} of every body's latest turn starting at or before round r (state at that turn start). So a body that has
        already acted in round r reads where it started, a move or a dash behind: for a range claim at one turn, use positions_before."""
        if r in self._pos_cache:
            return self._pos_cache[r]
        out = {}
        for c, ts in self.by_champ.items():
            lo, hi = 0, len(ts) - 1
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                if ts[mid][0] <= r:
                    best = ts[mid]
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is not None:
                out[c] = best
        if len(self._pos_cache) < 4096:
            self._pos_cache[r] = out
        return out

    def positions_before(self, t):
        """{body: (x, y, row)} at the moment turn t starts: a body that acted earlier in t's round is where that turn ended (turn_end_pos), any other
        as in positions_at. Not covered: a death earlier in the round (row still alive), a recall that lands at the body's own later turn start."""
        if self._round_turns is None:
            self._round_turns = collections.defaultdict(list)
            for u in self.turns:
                self._round_turns[u[0]].append(u)
        out = {c: (u[2], u[3], u) for c, u in self.positions_at(t[0]).items()}
        for u in self._round_turns[t[0]]:
            if u is t:
                break
            out[u[1]] = (*turn_end_pos(u), u)
        return out

    def round_row(self, r):
        lo, hi, best = 0, len(self.rounds) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.rounds[mid][0] <= r:
                best = self.rounds[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def camp_state_at(self, r):
        """(camp hp {id: hp}, group state {gid: (rewards ready, capturing team 0/1/2)}) at the start of round r."""
        hp = {c: v["hp"] for c, v in self.camps.items()}
        gs = {gid: (0, 2) for gid in self.groups}
        for row in self.rounds:
            if row[0] > r:
                break
            for cid, h in row[11]:
                hp[cid] = h
            for gid, ra, ct in row[12]:
                gs[gid] = (ra, ct)
        return hp, gs

    def camps_alive_at(self, r):
        """{camp id: alive} as a body's turn in round r sees it (12 Nov, Coordinator/Econ: the 'live group' HP read). Round row r holds the state
        at the END of round r - 1 (a camp killed in round 10 first shows hp 0 in row 11; a group respawning at round 78's start shows in row 79),
        so: row r's hp, then round r's own events: group_respawn (round start) revives the group's camps, camp_death in round r marks the camp dead
        (counted dead for the whole round: turn order inside the round is not resolved). Readers that build hp from rows with round < r (one
        round late) see a group cleared in round r - 1 as live: replay idle-at-a-live-group rows on capture holds came from that."""
        hp, _ = self.camp_state_at(r)
        alive = {c: h > 0 for c, h in hp.items()}
        for e in self.events:
            if e[0] != r:
                continue
            if e[1] == "group_respawn" and e[2] in self.groups:
                for c in self.groups[e[2]]["camps"]:
                    alive[c] = True
        for e in self.events:
            if e[0] == r and e[1] == "camp_death":
                alive[e[2]] = False
        return alive


def cheb(a, b, c, d):
    return max(abs(a - c), abs(b - d))


DRAFT = ["ryth", "vesper_vale", "vendetta", "cassi_issac", "stellar", "prism", "marcella", "willow", "ren", "varg", "tavi",
         "heart_of_ruin"]
ABILITY = ["none", "attack_reset", "damage", "aoe_damage", "cc", "heal", "dash", "shield"]
# engine 2.0.0 items (BotAPICpp item_type / item_family / item_stat): id = family * 6 + stat * 2 + (1 for the emblem)
ITEM_FAM = ["monster", "power", "durability", "treasure", "jungle", "home", "bruiser", "tribute", "capture",
            "prospector", "hunter", "skirmish", "greed", "collectors"]
ITEM_STAT = ["strength", "focus", "health"]


def item_name(t):
    if not 0 <= t < 6 * len(ITEM_FAM):
        return str(t)
    return f"{ITEM_FAM[t // 6]}_{ITEM_STAT[(t % 6) // 2]}" + ("_emblem" if t % 2 else "")


# ---------------------------------------------------------------- info and timeline
def cmd_info(g):
    m = g.meta
    print(f"map {m.get('map', '?')} {g.W}x{g.H}, {g.d['map']['teamSize']} per team, {len(g.groups)} camp groups, "
          f"{len(g.altars)} altars; source {m.get('source')} {m.get('set', m.get('run', ''))} {m.get('match', m.get('game', ''))}")
    f = g.final
    win = {1: "A", 2: "B"}.get(f.get("outcome"), "?")
    print(f"result: team {win} won at round {f.get('round')}, tributed {f.get('submitted')}; us = team {'AB'[g.us]}")
    for t in (0, 1):
        dr = [DRAFT[k] if 0 <= k < len(DRAFT) else str(k) for k in (g.d.get("draft") or [[], []])[t]]
        print(f"team {'AB'[t]} ({g.team_name(t)}): draft {', '.join(dr)}")
    print("\nchampion            kills deaths assists  gems gained  tributed  gold earned  gold spent")
    for b in (g.d.get("stats") or {}).get("bodies", []):
        print(f"{g.who(b['id']):20s} {b['kills']:5d} {b['deaths']:6d} {b['assists']:7d} {b['gemsGained']:12d} {b['gemsTributed']:9d} "
              f"{b['earnedGold']:12d} {b['goldSpent']:11d}")


def window_events(g, lo, hi):
    """Counts of captures, deaths and tributes per team in rounds (lo, hi]."""
    w = {t: collections.Counter() for t in (0, 1)}
    for e in g.events:
        r = e[0]
        if not lo < r <= hi:
            continue
        k = e[1]
        if k == "capture" and e[3] in (0, 1):
            w[e[3]]["caps"] += 1
            w[e[3]]["cap_gems"] += sum(x[2] for x in e[4])
        elif k == "death":
            t = g.team_of.get(e[2], 0)
            w[t]["deaths"] += 1
            w[t]["deaths_camp"] += e[3] == 2
            w[t]["bag"] += e[5]
        elif k == "tribute":
            w[e[3]]["tributes"] += 1
            w[e[3]]["trib_gems"] += e[4]
    return w


def cmd_timeline(g, every=50):
    print(f"race every {every} rounds (A = {g.team_name(0)}, B = {g.team_name(1)}); window columns count what happened "
          f"since the previous row: captures (gems), deaths (to monsters, carried gems lost), tributes (gems)")
    print(f"{'round':>5} {'tributed A-B':>13} {'lead':>5} {'carried':>9} {'gold earned':>13} {'kills':>6} {'alive':>5} | "
          f"{'A: caps  deaths  tributes':27s} | {'B: caps  deaths  tributes':27s}")
    prev, lead_prev = 0, 0
    marks = []
    rs = list(range(every, g.last_round + every, every))
    for r in rs:
        row = g.round_row(min(r, g.last_round))
        if not row:
            continue
        w = window_events(g, prev, r)
        lead = row[1] - row[2]
        flip = " <-- lead change" if lead and lead_prev and (lead > 0) != (lead_prev > 0) else ""
        if lead:
            lead_prev = lead
        cell = lambda t: (f"{w[t]['caps']:2d} ({w[t]['cap_gems']:4.0f}) {w[t]['deaths']:2d} ({w[t]['deaths_camp']}, {w[t]['bag']:3.0f}) "  # noqa: E731
                          f"{w[t]['tributes']:2d} ({w[t]['trib_gems']:3.0f})")
        print(f"{row[0]:5d} {row[1]:6d}-{row[2]:<6d} {lead:+5d} {row[3]:4d}/{row[4]:<4d} {row[5]:6d}/{row[6]:<6d} "
              f"{row[7]:2d}/{row[8]:<3d} {row[9]}/{row[10]} | {cell(0):27s} | {cell(1):27s}{flip}")
        prev = r
    f = g.final
    print(f"final (round {f.get('round')}): tributed {f.get('submitted')}, team {({1: 'A', 2: 'B'}).get(f.get('outcome'), '?')} won "
          f"(rows show the state at the start of each round, before that round's tributes)")


# ---------------------------------------------------------------- show: the map at one round
def turn_end_pos(t):
    """Where a turn ended: walk steps and dash landings (a cast of ability type 6 lands on its target tile). A teleport
    ('tp') only starts a 3-turn channel: the body arrives at the start of its turn 3 rounds later, so it doesn't move here."""
    x, y = t[2], t[3]
    for a in t[-1]:
        if a[0] == "m":
            x, y = a[1], a[2]
        elif a[0] == "c" and a[2] == 6:
            x, y = a[3], a[4]
    return x, y


def wards_at(g, r):
    """Latest ward placement of each body at or before round r: {body: (x, y)}."""
    out = {}
    for c, ts in g.by_champ.items():
        for t in ts:
            if t[0] > r:
                break
            for a in t[-1]:
                if a[0] == "w":
                    out[c] = (a[1], a[2])
    return out


TRAIL_L = "abcdfhijkmnpqrstuvyz"  # no e g w o x: those letters are camps, holes and wards on the map


def cmd_show(g, r, box=None, around=None, trail=None):
    """trail = (body, N): mark that body's turn-start tiles over the N rounds before r with letters a, b, c ... (oldest first,
    one letter per tile stay, skipping e g w o x; a tile visited twice keeps the later letter) and frame the map on the trail unless --box/--around."""
    r = max(1, min(r, g.last_round))
    pos = g.positions_at(r)
    hp, gs = g.camp_state_at(r)
    grid = [list(row) for row in g.rows]
    for y in range(g.H):
        for x in range(g.W):
            ch = grid[y][x]
            grid[y][x] = {"A": "@", "a": "_", "b": "_"}.get(ch, ch)
    for c in g.camps.values():
        grid[c["y"]][c["x"]] = CAMP_CH[c["type"]] if hp.get(c["id"], 0) > 0 else ","
    for c, (x, y) in wards_at(g, r).items():
        if 0 <= x < g.W and 0 <= y < g.H:
            grid[y][x] = "+" if g.team_of[c] == 0 else "x"
    tr = []
    if trail:
        tc, tn = trail
        tr = []  # stays: [first round, last round, x, y]
        for t in g.by_champ.get(tc, []):
            if r - tn <= t[0] < r and t[g.ci["alive"]] and t[2] >= 0:
                if tr and (tr[-1][2], tr[-1][3]) == (t[2], t[3]):
                    tr[-1][1] = t[0]
                else:
                    tr.append([t[0], t[0], t[2], t[3]])
        for k, (r0, r1, x, y) in enumerate(tr):
            grid[y][x] = TRAIL_L[k] if k < len(TRAIL_L) else "*"
    for c, t in pos.items():
        if t[g.ci["alive"]] and 0 <= t[2] < g.W and 0 <= t[3] < g.H:
            grid[t[3]][t[2]] = g.label[c]
    x0, y0, x1, y1 = 0, 0, g.W - 1, g.H - 1
    if tr and not box and around is None:
        xs = [s_[2] for s_ in tr] + ([pos[trail[0]][2]] if trail[0] in pos and pos[trail[0]][2] >= 0 else [])
        ys = [s_[3] for s_ in tr] + ([pos[trail[0]][3]] if trail[0] in pos and pos[trail[0]][3] >= 0 else [])
        box = (min(xs) - 6, min(ys) - 6, max(xs) + 6, max(ys) + 6)
    if box:
        x0, y0, x1, y1 = box
    elif around is not None:
        cid, rad = around
        t = pos.get(cid)
        if t is not None and t[2] >= 0:
            x0, y0, x1, y1 = t[2] - rad, t[3] - rad, t[2] + rad, t[3] + rad
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(g.W - 1, x1), min(g.H - 1, y1)
    row = g.round_row(r)
    print(f"round {r}: tributed A {row[1] if row else '?'} - B {row[2] if row else '?'}; showing x {x0}-{x1}, y {y0}-{y1}")
    print("legend: # wall, o hole, \" bush, @ altar, _ spawn, w e g $ M G camps alive (wolf elk gem gold monolith golem), "
          ", dead camp, + team-A ward, x team-B ward, 1-6 team A, K L N P R S team B")
    print("    " + "".join(str((x // 10) % 10) if x % 10 == 0 else " " for x in range(x0, x1 + 1)))
    print("    " + "".join(str(x % 10) for x in range(x0, x1 + 1)))
    for y in range(y0, y1 + 1):
        print(f"{y:3d} " + "".join(grid[y][x0:x1 + 1]))
    if tr:
        seq = [f"{TRAIL_L[k] if k < len(TRAIL_L) else '*'}=({x},{y}) r{r0}" + (f"-{r1}" if r1 > r0 else "")
               for k, (r0, r1, x, y) in enumerate(tr)]
        print(f"trail of {g.who(trail[0])} over rounds {r - trail[1]}-{r - 1}: one letter per tile it started a turn on, a = oldest"
              f" (a later visit overwrites the letter; '*' after 26 tiles); its label marks round {r}: " + " ".join(seq))
    print("\nbodies (state at their turn start in this round or the latest before it):")
    for c in sorted(pos):
        t = pos[c]
        cl = lambda n: t[g.ci[n]]  # noqa: E731
        spin_rc = cl("chType") == 1 and any(a_[0] == "x" for a_ in t[-1])  # SPIN_SELF: the recall it cancels this turn
        status = "dead, respawn in %d" % cl("respawnTimer") if not cl("alive") else (
            "(spin recall, cancelled this turn)" if spin_rc else
            {1: "RECALLING", 2: "tributing", 3: "capturing", 4: "teleporting", 5: "locking"}.get(cl("chType"), "")
            + (f" ({cl('chTimer')} left)" if cl("chType") else ""))
        z = g.zone(t[2], t[3], g.team_of[c]) if cl("alive") else "-"
        print(f"  {g.who(c):22s} turn r{t[0]:4d} at ({t[2]:3d},{t[3]:3d}) {z:7s} hp {cl('hp'):5d}/{cl('maxHp'):<5d} carrying "
              f"{cl('gems'):3d} gems, {cl('gold'):4d} gold {('stunned ' if cl('stunned') else '') + status}")
    act = [(gid, ra, ct) for gid, (ra, ct) in gs.items() if ra or ct in (0, 1)]
    if act:
        print("camp groups with a reward waiting or a capture running: " + ", ".join(
            f"g{gid} ({self_desc(g, gid)}) {'ready' if ra else ''}{', team ' + 'AB'[ct] + ' capturing' if ct in (0, 1) else ''}"
            for gid, ra, ct in act))


def self_desc(g, gid):
    gr = g.groups[gid]
    return f"{'+'.join(f'{n}x{k}' if n > 1 else k for k, n in gr['types'].items())}, {gr['gems']} gems {gr['gold']} gold @({gr['cx']:.0f},{gr['cy']:.0f})"


# ---------------------------------------------------------------- activities: what each turn was spent on
ACTS = ["dead", "fight", "farm", "capture", "hold", "tribute", "recall", "teleport", "lock", "shop", "walk", "idle"]


def lethal_hit(g, r, victim, killer, cause):
    """9 Nov (Coordinator, Econ's grill of 01a1c19d: a Marcella hit read as "exactly 600" was ~820): the decoded effects list HP
    changes, so a killing hit shows the HP the target had left, not the damage the hit would do. True when a champion 'death' event
    names this round, victim, killer and cause ('attack' / 'cast'): that hit was capped and the true damage is at least what shows."""
    k = getattr(g, "_lethal", None)
    if k is None:
        k = g._lethal = {(e[0], e[2], e[4], e[8] if len(e) > 8 else "") for e in g.events if e[1] == "death" and e[3] == 1}
    return (r, victim, killer, cause) in k


def hostile_hits(g, t):
    """[(victim, damage)] dealt to enemy champions by this turn's attacks and casts."""
    team = g.team_of[t[1]]
    out = []
    for a in t[-1]:
        fx = a[5] if a[0] == "a" else (a[7] if a[0] == "c" else [])
        for k, i, dd in fx:
            if k == 1 and dd < 0 and g.team_of.get(i, team) != team:
                out.append((i, -dd))
    return out


def camp_hits(g, t):
    out = []
    for a in t[-1]:
        fx = a[5] if a[0] == "a" else (a[7] if a[0] == "c" else [])
        for k, i, dd in fx:
            if k == 2 and dd < 0:
                out.append((i, -dd))
    return out


class GroupTrack:
    """Camp-group state (rewards ready, capturing team) as rounds advance; turns are visited in round order."""

    def __init__(self, g):
        self.g, self.k, self.state = g, 0, {gid: (0, 2) for gid in g.groups}

    def at(self, r):
        rows = self.g.rounds
        while self.k < len(rows) and rows[self.k][0] <= r:
            for gid, ra, ct in rows[self.k][12]:
                self.state[gid] = (ra, ct)
            self.k += 1
        return self.state


def real_channel(ci, t, prev):
    """t's channel type, or 0 for a lazy recall start (SPIN_SELF, see chosen_channel): a recall counts only when t did not cancel it (x). prev is
    unused, kept for callers (it missed the first turn of each kept recall). For per-turn readers: chosen_channel rescans the body's turns on every call."""
    ch = t[ci["chType"]]
    if ch == 1 and any(a[0] == "x" for a in t[-1]):
        return 0
    return ch


def chosen_channel(g, ts, r):
    """Channel type (CH: 1 recall, 2 tribute, 3 capture, 4 teleport, 5 lock) a body CHOSE at its last turn before round r, else 0.
    A tribute, capture, teleport or lock always counts. A recall counts only when it was KEPT: its timer counted down from one
    turn to the next (the turn before r is a recall turn, the turn before that too, with a higher timer). Since SPIN_SELF
    (v383) almost every turn ends with a lazy recall start that the next turn restarts, so 'recalling at r-1' alone tags nearly
    every death (Builder 1 Nov: 18 of 19 vault/the_line centre deaths). ts: the body's turns in round order."""
    ci = g.ci
    prev = [t for t in ts if t[0] <= r - 1]
    if not prev or not prev[-1][ci["alive"]]:
        return 0
    tv = prev[-1]
    ch = tv[ci["chType"]]
    if ch != 1:
        return ch
    if len(prev) >= 2 and prev[-2][ci["alive"]] and prev[-2][ci["chType"]] == 1 and tv[ci["chTimer"]] < prev[-2][ci["chTimer"]]:
        return 1
    return 0


def kept_recall(ci, t, nxt):
    """t was spent in a recall the body kept. chType is the state at turn start and SPIN_SELF cancels (x) and restarts (rc) a recall nearly every
    turn, so neither chType 1 nor rc alone means a recall: staying in one has no x, and a start counts when the body's next turn nxt does not cancel it."""
    kinds = {a[0] for a in t[-1]}
    if t[ci["chType"]] == 1 and "x" not in kinds:
        return True
    return "rc" in kinds and bool(nxt) and nxt[ci["alive"]] and nxt[ci["chType"]] == 1 and not any(a[0] == "x" for a in nxt[-1])


HOLD_N = 6  # rounds after a turn in which an own capture event must fall for an on-tile wait to count as 'hold'


def hold_default():
    """12 Nov (Coordinator/Econ): 'hold' on by default; REPLAY_IDLE_OLD=1 restores the old labels (those turns read 'idle') for comparisons."""
    return os.environ.get("REPLAY_IDLE_OLD", "") not in ("1", "true", "yes")


def hold_turns(g, out):
    """Relabel 'idle' turns as 'hold' (12 Nov, Coordinator; Econ's idle-by-cause close, econ_capture.cc:824 'Hold the tile'): the body stands ON
    a monster tile of a camp group (its capture region) and an own-team capture_start or capture of that group, or a capture_reset of it, falls in
    rounds r .. r + HOLD_N. These are the step-on round before the round-start capture phase starts the timer (the replay's group state row for
    round r is written before that phase, so 'capture' saw no running capture yet) and extra holders on a region. Respawn waits on a tile with no
    capture event in the window stay 'idle'."""
    tile = {}
    for gid, gr in g.groups.items():
        for cid in gr["camps"]:
            cp = g.camps[cid]
            tile[(cp["x"], cp["y"])] = gid
    ev = collections.defaultdict(list)  # gid -> [(round, team or None)]
    for e in g.events:
        if e[1] in ("capture_start", "capture", "capture_reset"):
            for gid in (e[2] if isinstance(e[2], list) else [e[2]]):
                ev[gid].append((e[0], e[3] if e[1] != "capture_reset" and len(e) > 3 else None))
    for t in g.turns:
        k = (t[0], t[1])
        if out.get(k) != "idle":
            continue
        gid = tile.get((t[2], t[3]))
        if gid is None:
            continue
        team = g.team_of[t[1]]
        if any(t[0] <= r <= t[0] + HOLD_N and (tm is None or tm == team) for r, tm in ev[gid]):
            out[k] = "hold"
    return out


def classify_all(g, recall_arrival=True, hold=None):
    """{(round, body): activity} for every turn.
    recall_arrival (4 Nov, b1085): a run of 'recall' turns counts as a recall only if the body starts it off its own spawn and begins
    its next turn on it (the recall completed), or dies in it (interrupted). Otherwise it is a wait inside a recall it never finishes
    (Fish stands by respawning groups this way) and is labelled 'idle' ('capture' beside a running own capture), like any other wait.
    recall_arrival=False: the old labels (every kept recall turn is 'recall').
    hold (12 Nov): None = hold_default(); True relabels on-tile capture waits 'idle' -> 'hold' (see hold_turns); False keeps the old labels."""
    out = {}
    nxt = {(a[0], a[1]): b for ts in g.by_champ.values() for a, b in zip(ts, ts[1:])}
    gt = GroupTrack(g)
    near = {}  # group -> camp points
    for gid, gr in g.groups.items():
        near[gid] = gr["pts"]
    for t in g.turns:
        r, c = t[0], t[1]
        team = g.team_of[c]
        kinds = {a[0] for a in t[-1]}
        ch = t[g.ci["chType"]]
        if not t[g.ci["alive"]]:
            a = "dead"
        elif hostile_hits(g, t):
            a = "fight"
        elif camp_hits(g, t):
            a = "farm"
        elif "t" in kinds or (ch == 2 and "m" not in kinds):
            a = "tribute"
        elif "tp" in kinds or (ch == 4 and "m" not in kinds):
            a = "teleport"
        elif "m" not in kinds and kept_recall(g.ci, t, nxt.get((r, c))):
            a = "recall"  # channelling a recall in place, kept (some bots start one every turn: see kept_recall, recall_starts)
        elif "l" in kinds or any(x[0] == "a" and x[1] == 6 for x in t[-1]):
            a = "lock"
        elif "m" in kinds:
            a = "walk"
        elif "s" in kinds:
            a = "shop"
        else:
            st = gt.at(r)
            a = "idle"
            for gid, (ra, ct) in st.items():
                if ra and ct == team and any(cheb(t[2], t[3], x, y) <= 2 for x, y in near[gid]):
                    a = "capture"
                    break
        out[(r, c)] = a
    if recall_arrival:
        def on_spawn(team, x, y):
            if not (0 <= team < len(g.spawn)):
                return False
            x0, y0, x1, y1 = g.spawn[team]
            return x0 <= x < x1 and y0 <= y < y1

        for c, ts in g.by_champ.items():
            team, k = g.team_of[c], 0
            gtc = GroupTrack(g)  # 5 Nov (b1199): the main loop's gt sits at the LAST round, so rewrites read the final group state
            while k < len(ts):
                if out.get((ts[k][0], c)) != "recall":
                    k += 1
                    continue
                j = k
                while j + 1 < len(ts) and out.get((ts[j + 1][0], c)) == "recall":
                    j += 1
                nx = ts[j + 1] if j + 1 < len(ts) else None
                done = (nx is not None and not on_spawn(team, ts[k][2], ts[k][3])
                        and ((nx[g.ci["alive"]] and on_spawn(team, nx[2], nx[3])) or not nx[g.ci["alive"]]))
                if not done:
                    st = None
                    for t in ts[k:j + 1]:
                        lab = "idle"
                        st = gtc.at(t[0])
                        for gid, (ra, ct) in st.items():
                            if ra and ct == team and any(cheb(t[2], t[3], x, y) <= 2 for x, y in near[gid]):
                                lab = "capture"
                                break
                        out[(t[0], c)] = lab
                k = j + 1
    if hold_default() if hold is None else hold:
        hold_turns(g, out)
    return out


CH_NAME = {1: "recall", 2: "tribute", 3: "capture", 4: "teleport", 5: "altar lock"}


def fmt_acts(g, t, prev=None, nxt=None, spin=None):
    """One turn's actions in words. With prev/nxt (the body's previous and next turn) the SPIN_SELF pair is hidden: the bot ends
    most turns by starting a recall and cancels it at the start of its next turn (no cost, no effect). Then 'RECALL (kept)' is a
    recall the body really stayed in, 'cancel recall' cancels one it had kept, and spin (a Counter) counts the hidden pairs."""
    parts, moves = [], []
    ctx = prev is not None or nxt is not None

    def flush():
        if moves:
            parts.append(f"move x{len(moves)} ->({moves[-1][0]},{moves[-1][1]})")
            moves.clear()
    for a in t[-1]:
        k = a[0]
        if k == "m":
            moves.append((a[1], a[2]))
            continue
        flush()
        if k == "a":
            tgt = {1: lambda: g.who(a[2]), 2: lambda: camp_txt(g, a[2]),
                   6: lambda: "altar lock"}.get(a[1], lambda: f"({a[3]},{a[4]})")()
            dmg = sum(-d for kk, i, d in a[5] if d < 0)
            sh = ""
            if a[1] == 1 and dmg == 0:  # decoded effects list HP changes only: a hit that a shield took shows -0
                u = g.positions_at(t[0]).get(a[2])
                if u and u[g.ci["shield"]] > 0:
                    sh = f" [target shield {u[g.ci['shield']]:.0f}]"
            if a[1] == 1 and lethal_hit(g, t[0], a[2], t[1], "attack"):
                sh += " LETHAL (HP left, not the hit: damage is capped at the target's HP)"
            parts.append(f"attack {tgt} -{dmg:.0f}{sh}")
        elif k == "c":
            hit = ", ".join(f"{g.who(i) if kk == 1 else 'camp' + str(i)} {d:+.0f}"
                            + (" LETHAL (HP left, capped)" if kk == 1 and lethal_hit(g, t[0], i, t[1], "cast") else "") for kk, i, d in a[7])
            parts.append(f"cast s{a[1]} {ABILITY[a[2]] if a[2] < len(ABILITY) else a[2]} ->({a[3]},{a[4]})" + (f" [{hit}]" if hit else ""))
        elif k == "t":
            parts.append(f"tribute {a[3]} gems at ({a[1]},{a[2]})")
        elif k == "rc":
            if not ctx:
                parts.append("recall")
            elif nxt is None:
                parts.append("recall start")
            elif nxt[g.ci["alive"]] and nxt[g.ci["chType"]] == 1 and not any(b[0] == "x" for b in nxt[-1]):
                parts.append("RECALL (kept)")
            elif spin is not None:  # cancelled next turn, or broken by damage before it
                spin["rc"] += 1
        elif k == "x":
            ch = t[g.ci["chType"]]
            if ctx and ch == 1 and prev is not None and any(b[0] == "rc" for b in prev[-1]):
                pass  # cancels last turn's spin recall
            else:
                parts.append("cancel " + CH_NAME.get(ch, "channel") if ctx else "cancel channel")
        elif k == "w":
            parts.append(f"ward ({a[1]},{a[2]})")
        elif k == "l":
            parts.append(f"altar lock ({a[1]},{a[2]})")
        elif k == "tp":
            parts.append(f"teleport ->({a[1]},{a[2]})")
        elif k == "s":
            items = ", ".join(f"{item_name(i)} x{n}" for i, n in a[1])
            cons = ", ".join(f"{['crystal', 'c1', 'lock', 'c3'][i]} x{n}" for i, n in a[2])
            parts.append(f"shop {items}{'; ' + cons if cons else ''} (-{a[3]} gold)")
        elif k == "b":  # engine step movement_blocked: a move, dash, crystal or ward placement aimed at a tile that
            # something unseen holds (a bush hides it; teammates' views are not shared). The call returned false, revealed
            # the tile for the round and spent nothing. 150 cached games: a mate's ward 64% (ward picks at range 2), a mate
            # in a bush 33%, an enemy 2%. The holder named here is a guess from round-start positions and placed wards.
            occ = [g.who(o) for o, u in g.positions_at(t[0]).items() if u[g.ci["alive"]] and (u[2], u[3]) == (a[1], a[2])]
            occ = occ or [f"ward of {g.who(o)}" for o, p in wards_at(g, t[0]).items() if p == (a[1], a[2])]
            parts.append(f"blocked at ({a[1]},{a[2]}) by unseen {occ[0] if occ else 'unit'}")
        elif k == "p":
            parts.append(f"priority {a[1]}")
    flush()
    if t[g.ci["end"]] == 1:
        parts.append("FUEL EXHAUSTED")
    elif t[g.ci["end"]] == 2:
        parts.append("BOT ERROR")
    return "; ".join(parts) or "-"


def camp_txt(g, cid):
    c = g.camps.get(cid)
    if not c:
        return f"camp{cid}"
    return f"{CAMP_NAMES[c['type']]} camp{cid} of group g{c['group']}"


def nearest_enemy(g, t):
    team = g.team_of[t[1]]
    best = None
    for o, (x, y, u) in g.positions_before(t).items():
        if g.team_of[o] != team and u[g.ci["alive"]] and x >= 0:
            d = cheb(t[2], t[3], x, y)
            if best is None or d < best[0]:
                best = (d, o)
    return best


def cmd_track(g, champ, lo=0, hi=10 ** 9):
    ts = [t for t in g.by_champ.get(champ, []) if lo <= t[0] <= hi]
    if not ts:
        sys.exit(f"no turns for body {champ} in rounds {lo}-{hi} (bodies: {', '.join(g.who(c) for c in sorted(g.bodies))})")
    acts = classify_all(g)
    allts = g.by_champ.get(champ, [])
    idx = {id(t): i for i, t in enumerate(allts)}
    spin = collections.Counter()
    print(f"{g.who(champ)}, {g.team_name(g.team_of[champ])}: {len(ts)} turns, rounds {ts[0][0]}-{ts[-1][0]}")
    print("columns: state at the START of the turn (pos x,y; zone = own/mid/enemy half by walk distance from the spawns; hp now/max;"
          " gems and gold carried); foe = distance (Chebyshev tiles, hidden or not) and label of the nearest living enemy;"
          " activity = replay.py's class of the turn; then what the body did this turn, in order")
    print(f"{'round':>5} {'pos':>9} {'zone':7s} {'hp':>11} {'gems':>4} {'gold':>5} {'foe':>6} {'activity':8s} what it did")
    for t in ts:
        ne = nearest_enemy(g, t)
        i = idx[id(t)]
        pv = allts[i - 1] if i > 0 else None
        nx = allts[i + 1] if i + 1 < len(allts) else None
        z = g.zone(t[2], t[3], g.team_of[champ]) if t[g.ci["alive"]] else "-"
        print(f"{t[0]:5d} ({t[2]:3d},{t[3]:3d}) {z:7s} {t[4]:5d}/{t[5]:<5d} {t[8]:4d} {t[7]:5d} "
              f"{(str(ne[0]) + ' ' + g.label[ne[1]]) if ne else '-':>6} {acts[(t[0], champ)]:8s} {fmt_acts(g, t, pv, nx, spin) if t[g.ci['alive']] else 'dead' + ('; ' + fmt_acts(g, t) if t[-1] else '')}")
    if spin["rc"]:
        print(f"note: {spin['rc']} spin recalls hidden (the bot starts a recall at a turn end and cancels it next turn: SPIN_SELF, no cost)."
              " 'RECALL (kept)' marks a recall the body stayed in.")


def budgets(g, acts=None):
    """Per body: activity counts, tiles walked, turns per zone, mean distance to the nearest living teammate."""
    acts = acts or classify_all(g)
    out = {}
    for c, ts in g.by_champ.items():
        team = g.team_of[c]
        b = {"acts": collections.Counter(), "walked": 0, "zones": collections.Counter(), "cohesion": [], "turns": len(ts),
             "recall_starts": 0, "recall_walking": 0}
        for t in ts:
            b["acts"][acts[(t[0], c)]] += 1
            b["walked"] += sum(1 for a in t[-1] if a[0] == "m")
            if any(a[0] == "rc" for a in t[-1]):
                b["recall_starts"] += 1
                b["recall_walking"] += any(a[0] == "m" for a in t[-1])
            if t[g.ci["alive"]] and t[2] >= 0:
                b["zones"][g.zone(t[2], t[3], team)] += 1
                if t[0] % 10 == 0:  # sampled: every 10th round keeps this cheap
                    ds = [cheb(t[2], t[3], u[2], u[3]) for o, u in g.positions_at(t[0]).items()
                          if o != c and g.team_of[o] == team and u[g.ci["alive"]] and u[2] >= 0]
                    if ds:
                        b["cohesion"].append(min(ds))
        out[c] = b
    return out


def walk_ends(g, acts, team):
    """Walking turns of a team, counted by the activity that ended each walking stretch (farm, tribute, ...)."""
    out = collections.Counter()
    for c, ts in g.by_champ.items():
        if g.team_of[c] != team:
            continue
        run = 0
        for t in ts:
            a = acts[(t[0], c)]
            if a == "walk":
                run += 1
            else:
                if run:
                    out[a] += run
                run = 0
        if run:
            out["game end"] += run
    return out


def cmd_activity(g):
    acts = classify_all(g)
    bs = budgets(g, acts)
    print("share of each champion's turns by activity (fight = hit an enemy champion, farm = hit a camp, capture = standing"
          " in a camp group's region while own team captures, hold = on a capture tile with an own capture event within 6 rounds (REPLAY_IDLE_OLD=1: idle), walk = moved only, idle = did nothing while alive and free)")
    print(f"{'champion':22s} {'turns':>5} " + " ".join(f"{a:>8s}" for a in ACTS) + f" {'walked':>7} {'own/mid/enemy %':>16} {'nearest mate':>12}")
    for team in (0, 1):
        tot = collections.Counter()
        tw = tz = 0
        zt = collections.Counter()
        for c in sorted(c for c in bs if g.team_of[c] == team):
            b = bs[c]
            n = max(1, b["turns"])
            tot.update(b["acts"])
            tw += b["walked"]
            zt.update(b["zones"])
            zn = max(1, sum(b["zones"].values()))
            coh = sum(b["cohesion"]) / len(b["cohesion"]) if b["cohesion"] else float("nan")
            print(f"{g.who(c):22s} {b['turns']:5d} " + " ".join(f"{100 * b['acts'][a] / n:7.1f}%" for a in ACTS)
                  + f" {b['walked']:7d} {100 * b['zones']['own'] / zn:4.0f}/{100 * b['zones']['mid'] / zn:3.0f}/{100 * b['zones']['enemy'] / zn:3.0f}"
                  + f"       {coh:6.1f}")
        n = max(1, sum(tot.values()))
        zn = max(1, sum(zt.values()))
        print(f"{'TEAM ' + 'AB'[team] + ' (' + g.team_name(team)[:12] + ')':22s} {sum(tot.values()):5d} "
              + " ".join(f"{100 * tot[a] / n:7.1f}%" for a in ACTS)
              + f" {tw:7d} {100 * zt['own'] / zn:4.0f}/{100 * zt['mid'] / zn:3.0f}/{100 * zt['enemy'] / zn:3.0f}")
        rs = sum(b["recall_starts"] for c, b in bs.items() if g.team_of[c] == team)
        rw = sum(b["recall_walking"] for c, b in bs.items() if g.team_of[c] == team)
        arr = sum(1 for e in g.events if e[1] == "recall_arrive" and g.team_of.get(e[2]) == team)
        print(f"  recall starts {rs} ({100 * rs / n:.0f} per 100 turns; {rw} of them while walking), completed recalls {arr}")
        ends = walk_ends(g, acts, team)
        wn = max(1, sum(ends.values()))
        print(f"  walking turns by what they led to: " + ", ".join(f"{k} {100 * v / wn:.0f}%" for k, v in ends.most_common()) + "\n")


# ---------------------------------------------------------------- fights
def fights(g, gap=6, radius=10):
    """Cluster champion-vs-champion damage (and champion kills) into fights: an interaction joins an open fight
    within `gap` rounds and `radius` tiles of its centre, else starts a new one."""
    inter = []
    for t in g.turns:
        hits = hostile_hits(g, t)
        if hits:
            for v, dmg in hits:
                inter.append((t[0], t[1], v, dmg, t[2], t[3]))
    for e in g.events:
        if e[1] == "death" and e[3] == 1 and e[4] >= 0:
            k = g.positions_at(e[0]).get(e[4])
            if k is not None and cheb(k[2], k[3], e[6], e[7]) > radius:
                continue  # a linked death (Cassi & Issac die together) far from the killer: not a fight of its own
            inter.append((e[0], e[4], e[2], 0.0, e[6], e[7]))
    inter.sort()
    open_f, done = [], []
    for r, a, v, dmg, x, y in inter:
        for f in list(open_f):
            if r - f["end"] > gap:
                open_f.remove(f)
                done.append(f)
        best = None
        for f in open_f:
            d = cheb(x, y, f["cx"], f["cy"])
            if d <= radius and (best is None or d < best[0]):
                best = (d, f)
        if best is None:
            f = {"start": r, "end": r, "cx": x, "cy": y, "n": 0, "dmg": collections.Counter(), "part": [set(), set()]}
            open_f.append(f)
        else:
            f = best[1]
        f["end"] = r
        f["n"] += 1
        f["cx"] += (x - f["cx"]) / f["n"]
        f["cy"] += (y - f["cy"]) / f["n"]
        f["dmg"][g.team_of[a]] += dmg
        f["part"][g.team_of[a]].add(a)
        f["part"][g.team_of[v]].add(v)
    done += open_f
    for f in done:
        f["deaths"], f["bags"] = [0, 0], [0, 0]
    for e in g.events:  # each death counts in one fight: the nearest one whose rounds and area contain it
        if e[1] != "death":
            continue
        best = None
        for f in done:
            if f["start"] <= e[0] <= f["end"] + 2:
                dd = cheb(e[6], e[7], f["cx"], f["cy"])
                if dd <= radius + 4 and (best is None or (dd, f["start"]) < best[0]):
                    best = ((dd, f["start"]), f)
        if best:
            t = g.team_of.get(e[2], 0)
            best[1]["deaths"][t] += 1
            best[1]["bags"][t] += e[5]
    for f in done:
        pos = g.positions_at(f["start"])
        f["near"] = [sum(1 for c, u in pos.items() if g.team_of[c] == t and u[g.ci["alive"]] and u[2] >= 0
                         and cheb(u[2], u[3], f["cx"], f["cy"]) <= 8) for t in (0, 1)]
    done.sort(key=lambda f: f["start"])
    return done


def fight_result(f, us):
    them = 1 - us
    if f["deaths"][us] < f["deaths"][them]:
        return "won"
    if f["deaths"][us] > f["deaths"][them]:
        return "lost"
    return "even"


def cmd_fights(g, show_all=False):
    fs = fights(g)
    us = g.us
    big = [f for f in fs if show_all or sum(f["deaths"]) or sum(f["dmg"].values()) >= 300]
    print(f"{len(fs)} fights ({len(big)} shown: {'all' if show_all else 'any death or 300+ damage'}); us = team {'AB'[us]} "
          f"({g.team_name(us)}); numbers = bodies within 8 tiles of the fight centre when it starts")
    print(f"{'rounds':>11} {'centre':>9} {'zone':7s} {'numbers us-them':>15} {'damage us-them':>15} {'deaths us-them':>14} "
          f"{'bags lost us-them':>17} result  champions (us | them)")
    for f in big:
        z = g.zone(round(f["cx"]), round(f["cy"]), us)
        print(f"{f['start']:5d}-{f['end']:<5d} ({f['cx']:3.0f},{f['cy']:3.0f}) {z:7s} {f['near'][us]:7d}-{f['near'][1 - us]:<7d} "
              f"{f['dmg'][us]:7.0f}-{f['dmg'][1 - us]:<7.0f} {f['deaths'][us]:6d}-{f['deaths'][1 - us]:<7d} "
              f"{f['bags'][us]:8d}-{f['bags'][1 - us]:<8d} {fight_result(f, us):6s}  "
              f"{' '.join(g.label[c] for c in sorted(f['part'][us]))} | {' '.join(g.label[c] for c in sorted(f['part'][1 - us]))}")
    print("\n" + summary_line(fight_summary(g, fs, us)))


def summary_line(s):
    if not s.get("fights"):
        return "no fights"
    parts = [f"{s['fights']} fights: won {s.get('won', 0)}, lost {s.get('lost', 0)}, even {s.get('even', 0)}"]
    for k in ("outnumbered", "even numbers", "outnumbering"):
        n = s.get(f"{k} fights", 0)
        if n:
            parts.append(f"{k} {n} (won {s.get(k + ' won', 0)}, lost {s.get(k + ' lost', 0)}, even {s.get(k + ' even', 0)})")
    parts.append(f"deaths us {s.get('our deaths', 0)} them {s.get('their deaths', 0)}")
    return "; ".join(parts)


def fight_summary(g, fs, us):
    s = collections.Counter()
    for f in fs:
        if not (sum(f["deaths"]) or sum(f["dmg"].values()) >= 300):
            continue
        res = fight_result(f, us)
        s["fights"] += 1
        s[res] += 1
        adv = f["near"][us] - f["near"][1 - us]
        key = "outnumbered" if adv < 0 else ("outnumbering" if adv > 0 else "even numbers")
        s[f"{key} fights"] += 1
        s[f"{key} {res}"] += 1
        s["our deaths"] += f["deaths"][us]
        s["their deaths"] += f["deaths"][1 - us]
    return dict(s)


# ---------------------------------------------------------------- camp groups: presence, damage, clears, captures
def group_stats(g, radius=5):
    us = g.us
    camp_group = {c: v["group"] for c, v in g.camps.items()}
    st = {gid: {"pres": [0, 0], "dmg": [0.0, 0.0], "kills": [0, 0], "caps": [0, 0], "cap_gems": [0, 0], "first_pres": [None, None],
                "first_cap": [None, None], "resets": 0} for gid in g.groups}
    near = {}  # tile -> groups with a camp within `radius` of it
    for t in g.turns:
        if not t[g.ci["alive"]] or t[2] < 0:
            continue
        team = g.team_of[t[1]]
        gl = near.get((t[2], t[3]))
        if gl is None:
            gl = near[(t[2], t[3])] = [gid for gid, gr in g.groups.items()
                                       if any(cheb(t[2], t[3], x, y) <= radius for x, y in gr["pts"])]
        for gid in gl:
            s = st[gid]
            s["pres"][team] += 1
            if s["first_pres"][team] is None:
                s["first_pres"][team] = t[0]
        for cid, dmg in camp_hits(g, t):
            gid = camp_group.get(cid)
            if gid in st:
                st[gid]["dmg"][team] += dmg
    for e in g.events:
        if e[1] == "camp_death" and e[3] == 1 and e[4] >= 0:
            gid = camp_group.get(e[2])
            if gid in st:
                st[gid]["kills"][g.team_of[e[4]]] += 1
        elif e[1] == "capture" and e[3] in (0, 1):
            for gid in (e[2] if isinstance(e[2], list) else [e[2]]):
                if gid in st:
                    s = st[gid]
                    s["caps"][e[3]] += 1
                    s["cap_gems"][e[3]] += sum(x[2] for x in e[4])
                    if s["first_cap"][e[3]] is None:
                        s["first_cap"][e[3]] = e[0]
        elif e[1] == "capture_reset" and e[2] in st:
            st[e[2]]["resets"] += 1
    return st


def cmd_presence(g, radius=5):
    us = g.us
    st = group_stats(g, radius)
    print(f"camp groups (us = team {'AB'[us]}, {g.team_name(us)}); presence = body-turns within {radius} tiles of the "
          f"group's camps; kills = camps finished off; zone seen from our spawn")
    print(f"{'group':>5} {'zone':7s} {'what':34s} {'presence us/them':>16} {'damage us/them':>15} {'kills us/them':>13} "
          f"{'captures us/them':>16} {'gems us/them':>12} {'first capture':>13} resets")
    order = sorted(st, key=lambda q: -(st[q]["cap_gems"][0] + st[q]["cap_gems"][1]))
    for gid in order:
        s, gr = st[gid], g.groups[gid]
        z = g.zone(round(gr["cx"]), round(gr["cy"]), us)
        fc = "/".join(str(s["first_cap"][t]) if s["first_cap"][t] is not None else "-" for t in (us, 1 - us))
        print(f"{gid:5d} {z:7s} {self_desc(g, gid)[:34]:34s} {s['pres'][us]:7d}/{s['pres'][1 - us]:<8d} {s['dmg'][us]:7.0f}/{s['dmg'][1 - us]:<7.0f} "
              f"{s['kills'][us]:5d}/{s['kills'][1 - us]:<7d} {s['caps'][us]:7d}/{s['caps'][1 - us]:<8d} {s['cap_gems'][us]:5d}/{s['cap_gems'][1 - us]:<6d} "
              f"{fc:>13} {s['resets']:6d}")


def cmd_group(g, gid, radius=5):
    if gid not in g.groups:
        sys.exit(f"no group {gid} (groups 0-{len(g.groups) - 1})")
    gr = g.groups[gid]
    camps = set(gr["camps"])
    print(f"group {gid}: {self_desc(g, gid)}, respawn {gr['respawn']} rounds; zone for A {g.zone(round(gr['cx']), round(gr['cy']), 0)}, "
          f"for B {g.zone(round(gr['cx']), round(gr['cy']), 1)}")
    ev = []
    for e in g.events:
        if e[1] == "group_respawn" and e[2] == gid:
            ev.append((e[0], "respawned"))
        elif e[1] == "camp_death" and e[2] in camps:
            ev.append((e[0], f"camp {e[2]} ({CAMP_NAMES[g.camps[e[2]]['type']]}) killed by " + (g.who(e[4]) if e[3] == 1 else "?")))
        elif e[1] == "capture_start" and e[2] == gid:
            ev.append((e[0], f"capture started by team {'AB'[e[3]]}" if e[3] in (0, 1) else "capture started"))
        elif e[1] == "capture_reset" and e[2] == gid:
            ev.append((e[0], "capture RESET (contested or left)"))
        elif e[1] == "capture" and gid in (e[2] if isinstance(e[2], list) else [e[2]]):
            who = ", ".join(f"{g.who(c)} +{dm} gems +{dg} gold" for c, dg, dm in e[4])
            ev.append((e[0], f"CAPTURED by team {'AB'[e[3]] if e[3] in (0, 1) else '?'}: {who}"))
    # presence and damage per 25-round window
    win = collections.defaultdict(lambda: [[0, 0], [0.0, 0.0]])
    for t in g.turns:
        if t[g.ci["alive"]] and t[2] >= 0 and any(cheb(t[2], t[3], x, y) <= radius for x, y in gr["pts"]):
            win[t[0] // 25][0][g.team_of[t[1]]] += 1
        for cid, dmg in camp_hits(g, t):
            if cid in camps:
                win[t[0] // 25][1][g.team_of[t[1]]] += dmg
    for k in sorted(win):
        (pa, pb), (da, db) = win[k]
        ev.append((k * 25, f"rounds {k * 25}-{k * 25 + 24}: presence A {pa} B {pb} body-turns, damage A {da:.0f} B {db:.0f}"))
    for r, s in sorted(ev, key=lambda q: (q[0], "rounds" in q[1])):
        print(f"{r:5d}  {s}")


# ---------------------------------------------------------------- key moments
def cmd_moments(g, limit=80):
    us = g.us
    out = []
    lead_prev = 0
    for row in g.rounds:
        lead = row[1] - row[2]
        if lead and lead_prev and (lead > 0) != (lead_prev > 0) and abs(lead) >= 20:
            out.append((row[0], "lead", f"team {'A' if lead > 0 else 'B'} takes the lead {row[1]}-{row[2]}"))
        if lead:
            lead_prev = lead
    for f in fights(g):
        if sum(f["deaths"]) >= 2 or max(f["bags"]) >= 60:
            out.append((f["start"], "fight", f"fight at ({f['cx']:.0f},{f['cy']:.0f}) {g.zone(round(f['cx']), round(f['cy']), us)} "
                        f"rounds {f['start']}-{f['end']}: numbers us {f['near'][us]} them {f['near'][1 - us]}, deaths us "
                        f"{f['deaths'][us]} them {f['deaths'][1 - us]}, bags lost us {f['bags'][us]} them {f['bags'][1 - us]} -> {fight_result(f, us)}"))
    last_kill = {}  # group -> (round, team, champion) of the latest camp kill so far (events are in game order)
    for e in g.events:
        r, k = e[0], e[1]
        if k == "camp_death" and e[3] == 1 and e[4] >= 0:
            last_kill[g.camps[e[2]]["group"]] = (r, g.team_of[e[4]], e[4])
        elif k == "death":
            if e[3] == 2:
                out.append((r, "monster", f"{g.who(e[2])} killed by a camp (camp {e[4]}) at ({e[6]},{e[7]}) carrying {e[5]} gems (destroyed)"))
            elif e[5] >= 40:
                out.append((r, "bag", f"{g.who(e[2])} killed by {g.who(e[4]) if e[4] >= 0 else '?'} at ({e[6]},{e[7]}) carrying {e[5]} gems (taken)"))
        elif k == "capture_reset":
            out.append((r, "contest", f"capture of group {e[2]} reset (team {'AB'[e[3]] if e[3] in (0, 1) else '?'} was capturing)"))
        elif k == "capture" and e[3] in (0, 1):
            for gid in (e[2] if isinstance(e[2], list) else [e[2]]):
                lk = last_kill.get(gid)
                if lk and lk[1] != e[3] and 0 <= r - lk[0] <= 30:
                    out.append((r, "stolen", f"team {'AB'[e[3]]} captured group {gid} ({self_desc(g, gid)}) that {g.who(lk[2])} cleared at round {lk[0]}"))
        elif k == "tribute" and e[4] >= 100:
            out.append((r, "bank", f"{g.who(e[2])} tributes {e[4]} gems at ({e[5]},{e[6]})"))
    acts = classify_all(g)
    for c, ts in g.by_champ.items():
        run = []
        for t in ts:
            if t[g.ci["end"]] in (1, 2):
                out.append((t[0], "fuel", f"{g.who(c)} {'fuel exhausted' if t[g.ci['end']] == 1 else 'bot error'}"))
            if acts[(t[0], c)] == "idle":
                run.append(t)
            else:
                if len(run) >= 20:
                    out.append((run[0][0], "idle", f"{g.who(c)} idle for {len(run)} turns (rounds {run[0][0]}-{run[-1][0]}) at "
                                                   f"({run[0][2]},{run[0][3]}) {g.zone(run[0][2], run[0][3], g.team_of[c])}"))
                run = []
    out.sort()
    kinds = collections.Counter(k for _, k, _ in out)
    print(f"{len(out)} moments ({', '.join(f'{k} {n}' for k, n in kinds.most_common())}); us = team {'AB'[us]} ({g.team_name(us)})")
    for r, k, s in out[:limit]:
        print(f"{r:5d}  {k:8s} {s}")
    if len(out) > limit:
        print(f"... {len(out) - limit} more (--limit N)")


# ---------------------------------------------------------------- diff two games
def cmd_diff(g1, g2):
    if (g1.W, g1.H, g1.rows) != (g2.W, g2.H, g2.rows):
        print("!! the two games are on different maps: only the race and the budgets are comparable")
    k1 = {(t[0], t[1]): (t[2], t[3], t[4], t[g1.ci["alive"]]) for t in g1.turns}
    k2 = {(t[0], t[1]): (t[2], t[3], t[4], t[g2.ci["alive"]]) for t in g2.turns}
    first = None
    for key in sorted(set(k1) | set(k2)):
        if k1.get(key) != k2.get(key):
            first = key
            break
    if first is None:
        print("the games are identical turn for turn")
    else:
        r, c = first
        print(f"identical until round {r}: first difference at body {g1.who(c)}: game 1 {k1.get(first)} vs game 2 "
              f"{k2.get(first)} (x, y, hp, alive at its turn start)")
        before = [t for t in g1.by_champ.get(c, []) if t[0] < r][-1:]
        if before:
            print(f"  its previous turn (round {before[0][0]}) in game 1: {fmt_acts(g1, before[0])}")
            b2 = [t for t in g2.by_champ.get(c, []) if t[0] < r][-1:]
            if b2:
                print(f"  ... and in game 2: {fmt_acts(g2, b2[0])}")
    print(f"\n{'round':>5} {'game 1 A-B':>11} {'game 2 A-B':>11}")
    for r in list(range(100, max(g1.last_round, g2.last_round) + 100, 100)):
        a, b = g1.round_row(min(r, g1.last_round)), g2.round_row(min(r, g2.last_round))
        print(f"{r:5d} {a[1]:5d}-{a[2]:<5d} {b[1]:5d}-{b[2]:<5d}")
    print(f"final: game 1 {g1.final.get('submitted')} (round {g1.final.get('round')}), game 2 {g2.final.get('submitted')} "
          f"(round {g2.final.get('round')})")
    b1, b2 = budgets(g1), budgets(g2)
    print("\nteam time budgets (% of turns): game 1 / game 2")
    for team in (0, 1):
        t1, t2 = collections.Counter(), collections.Counter()
        for c, b in b1.items():
            if g1.team_of[c] == team:
                t1.update(b["acts"])
        for c, b in b2.items():
            if g2.team_of[c] == team:
                t2.update(b["acts"])
        n1, n2 = max(1, sum(t1.values())), max(1, sum(t2.values()))
        print(f"team {'AB'[team]} ({g1.team_name(team)} / {g2.team_name(team)}): " + ", ".join(
            f"{a} {100 * t1[a] / n1:.0f}/{100 * t2[a] / n2:.0f}" for a in ACTS))


# ---------------------------------------------------------------- report over many games
def expand_specs(specs):
    out = []
    for s in specs:
        if os.path.isdir(s) and os.path.exists(os.path.join(s, "matches.txt")):  # a live set
            for line in open(os.path.join(s, "matches.txt")):
                p = line.split()
                if p and os.path.exists(os.path.join(s, "x_" + p[0], "replay.repl26a")):
                    out.append(p[0])
                    PREFER[p[0]] = os.path.abspath(s)
        elif os.path.isdir(os.path.join(s, "rep")):  # a local run with kept replays
            run = os.path.basename(s.rstrip("/"))
            if os.path.realpath(os.path.join(ABL, run)) != os.path.realpath(s):
                run = os.path.abspath(s.rstrip("/"))  # a copy outside ABL: not ABL/<same name>, which a rerun overwrites
            for f in sorted(os.listdir(os.path.join(s, "rep")), key=lambda f: int(f.split(".")[0]) if f[0].isdigit() else 0):
                if f.endswith(".repl26a"):
                    out.append(f"{run}:{f[:-8]}")
        else:
            out.append(s)
    return out


def game_summary(spec, us=None):
    """Compact per-game replay metrics for the report (runs in a worker)."""
    try:
        g = load(spec, us)
    except SystemExit as e:
        return {"spec": spec, "error": str(e)}
    usv = g.us
    if g.final.get("outcome") not in (1, 2):
        return {"spec": spec, "error": f"no result in the replay (outcome {g.final.get('outcome')} at round {g.last_round})"}
    acts = classify_all(g)
    bs = budgets(g, acts)
    res = {"spec": spec, "map": g.meta.get("map", "?"), "opp": g.team_name(1 - usv), "us": usv,
           "win": {1: 0, 2: 1}.get(g.final.get("outcome")) == usv, "rounds": g.last_round, "teams": {}}
    for team in (0, 1):
        tot, zones, walked, coh, turns, rst = collections.Counter(), collections.Counter(), 0, [], 0, 0
        for c, b in bs.items():
            if g.team_of[c] == team:
                tot.update(b["acts"])
                zones.update(b["zones"])
                walked += b["walked"]
                coh += b["cohesion"]
                turns += b["turns"]
                rst += b["recall_starts"]
        res["teams"][team] = {"acts": dict(tot), "zones": dict(zones), "walked": walked, "turns": turns, "recall_starts": rst,
                              "recall_done": sum(1 for e in g.events if e[1] == "recall_arrive" and g.team_of.get(e[2]) == team),
                              "walk_ends": dict(walk_ends(g, acts, team)),
                              "cohesion": sum(coh) / len(coh) if coh else None}
    fs = fights(g)
    res["fights"] = fight_summary(g, fs, usv)
    st = group_stats(g)
    cont = {"pres": [0, 0], "caps": [0, 0], "gems": [0, 0], "groups": 0}
    for gid, s in st.items():
        gr = g.groups[gid]
        if g.zone(round(gr["cx"]), round(gr["cy"]), usv) == "mid" and gr["gems"] > 0:
            cont["groups"] += 1
            for t in (0, 1):
                cont["pres"][t] += s["pres"][t]
                cont["caps"][t] += s["caps"][t]
                cont["gems"][t] += s["cap_gems"][t]
    res["contested"] = cont
    idle_runs = collections.Counter()
    for c, ts in g.by_champ.items():
        run = 0
        for t in ts:
            if acts[(t[0], c)] == "idle":
                run += 1
            else:
                if run >= 20:
                    idle_runs[g.team_of[c]] += 1
                run = 0
    res["idle_runs"] = dict(idle_runs)
    return res


def _job(args):
    return game_summary(*args)


def cmd_report(specs, out=None, jobs=4, us=None):
    games = expand_specs(specs)
    work = [(s, us) for s in games]
    if jobs > 1 and len(work) > 1:
        import multiprocessing
        with multiprocessing.get_context("fork").Pool(min(jobs, len(work))) as pool:
            rows = pool.map(_job, work)
    else:
        rows = [_job(w) for w in work]
    bad = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    L = [f"# Replay analysis: {len(rows)} games", "",
         f"Generated by tools/lab/replay.py from the engine's replay of every turn ({len(bad)} games could not be read). "
         f"\"us\" = our side; shares are of all champion turns.", ""]
    for r in bad[:10]:
        L.append(f"- not read: {r['spec']}: {r['error'][:160]}")
    W = [r for r in rows if r["win"]]
    Ls = [r for r in rows if not r["win"]]
    L.append(f"Record {len(W)}-{len(Ls)}.")

    def share(rs, side, a):
        num = sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["acts"].get(a, 0) for r in rs)
        den = sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["turns"] for r in rs)
        return 100 * num / max(1, den)
    L += ["", "## 1. How champions spend their turns (% of turns)", "",
          "| activity | losses: us | losses: them | wins: us | wins: them |", "|---|---|---|---|---|"]
    for a in ACTS:
        L.append(f"| {a} | {share(Ls, 'us', a):.1f} | {share(Ls, 'them', a):.1f} | {share(W, 'us', a):.1f} | {share(W, 'them', a):.1f} |")

    def zsh(rs, side, z):
        num = sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["zones"].get(z, 0) for r in rs)
        den = sum(sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["zones"].values()) for r in rs)
        return 100 * num / max(1, den)
    L += ["", "## 2. Where champions stand (% of living turns, zones seen from each team's own spawn) and movement", "",
          "| measure | losses: us | losses: them | wins: us | wins: them |", "|---|---|---|---|---|"]
    for z in ("own", "mid", "enemy"):
        L.append(f"| in {z} zone | {zsh(Ls, 'us', z):.1f} | {zsh(Ls, 'them', z):.1f} | {zsh(W, 'us', z):.1f} | {zsh(W, 'them', z):.1f} |")

    def per(rs, side, key):
        num = sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]][key] for r in rs)
        den = sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["turns"] for r in rs)
        return num / max(1, den)

    def coh(rs, side):
        v = [r["teams"][r["us"] if side == "us" else 1 - r["us"]]["cohesion"] for r in rs]
        v = [x for x in v if x is not None]
        return sum(v) / len(v) if v else float("nan")
    L.append(f"| tiles walked per turn | {per(Ls, 'us', 'walked'):.2f} | {per(Ls, 'them', 'walked'):.2f} | {per(W, 'us', 'walked'):.2f} | {per(W, 'them', 'walked'):.2f} |")
    L.append(f"| distance to the nearest teammate | {coh(Ls, 'us'):.1f} | {coh(Ls, 'them'):.1f} | {coh(W, 'us'):.1f} | {coh(W, 'them'):.1f} |")
    L.append(f"| recall starts per 100 turns | {100 * per(Ls, 'us', 'recall_starts'):.1f} | {100 * per(Ls, 'them', 'recall_starts'):.1f} | "
             f"{100 * per(W, 'us', 'recall_starts'):.1f} | {100 * per(W, 'them', 'recall_starts'):.1f} |")

    def pg(rs, side, key):
        return sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]][key] for r in rs) / max(1, len(rs))
    L.append(f"| completed recalls per game | {pg(Ls, 'us', 'recall_done'):.0f} | {pg(Ls, 'them', 'recall_done'):.0f} | "
             f"{pg(W, 'us', 'recall_done'):.0f} | {pg(W, 'them', 'recall_done'):.0f} |")

    def wend(rs, side, what):
        num = sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["walk_ends"].get(what, 0) for r in rs)
        den = sum(sum(r["teams"][r["us"] if side == "us" else 1 - r["us"]]["walk_ends"].values()) for r in rs)
        return 100 * num / max(1, den)
    for what in ("farm", "idle", "tribute", "fight"):
        L.append(f"| walking that ends in {what} (% of walking turns) | {wend(Ls, 'us', what):.0f} | {wend(Ls, 'them', what):.0f} | "
                 f"{wend(W, 'us', what):.0f} | {wend(W, 'them', what):.0f} |")
    ir = lambda rs, side: sum(r["idle_runs"].get(str(r["us"] if side == "us" else 1 - r["us"]), r["idle_runs"].get(r["us"] if side == "us" else 1 - r["us"], 0)) for r in rs) / max(1, len(rs))  # noqa: E731
    L.append(f"| idle stretches of 20+ turns per game | {ir(Ls, 'us'):.1f} | {ir(Ls, 'them'):.1f} | {ir(W, 'us'):.1f} | {ir(W, 'them'):.1f} |")

    L += ["", "## 3. Fights (any death or 300+ damage; numbers = bodies within 8 tiles at the start)", ""]
    for lab, rs in (("losses", Ls), ("wins", W)):
        f = collections.Counter()
        for r in rs:
            f.update(r["fights"])
        if not f.get("fights"):
            continue
        L.append(f"- In {lab} ({len(rs)} games): {f['fights'] / max(1, len(rs)):.1f} fights per game; won {f['won']}, lost {f['lost']}, "
                 f"even {f['even']}; deaths in fights us {f['our deaths']} them {f['their deaths']}.")
        for k in ("outnumbered", "even numbers", "outnumbering"):
            n = f.get(f"{k} fights", 0)
            if n:
                L.append(f"  - {k}: {n} fights ({100 * n / f['fights']:.0f}%), won {f.get(k + ' won', 0)}, lost {f.get(k + ' lost', 0)}, "
                         f"even {f.get(k + ' even', 0)}")
    L += ["", "## 4. Contested camp groups (gem groups in the mid zone)", "",
          "| measure | losses: us | losses: them | wins: us | wins: them |", "|---|---|---|---|---|"]

    def cs(rs, side, key, idx_sum=False):
        tot = sum(r["contested"][key][r["us"] if side == "us" else 1 - r["us"]] for r in rs)
        return tot / max(1, len(rs))
    for key, lab in (("pres", "body-turns near them per game"), ("caps", "captures per game"), ("gems", "gems captured per game")):
        L.append(f"| {lab} | {cs(Ls, 'us', key):.0f} | {cs(Ls, 'them', key):.0f} | {cs(W, 'us', key):.0f} | {cs(W, 'them', key):.0f} |")
    pres_share = [r["contested"]["pres"][r["us"]] / max(1, sum(r["contested"]["pres"])) for r in rows if sum(r["contested"]["pres"])]
    gem_share = [r["contested"]["gems"][r["us"]] / max(1, sum(r["contested"]["gems"])) for r in rows if sum(r["contested"]["gems"])]
    if pres_share and gem_share:
        L.append(f"\nOur share of the presence near contested groups: {100 * sum(pres_share) / len(pres_share):.0f}%; our share of their "
                 f"gems: {100 * sum(gem_share) / len(gem_share):.0f}% (mean per game).")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["opp"]].append(r)
    if len(by) > 1:
        L += ["", "## 5. Opponents: how each one plays (their side unless marked)", "",
              "| opponent | games | W-L (ours) | farm % | walk % | walking ends in idle % | recall starts /100 turns | "
              "nearest teammate | fights won-lost (ours) | our mid-presence share |", "|---|---|---|---|---|---|---|---|---|---|"]
        for opp, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            f = collections.Counter()
            for r in rs:
                f.update(r["fights"])
            ps = [r["contested"]["pres"][r["us"]] / max(1, sum(r["contested"]["pres"])) for r in rs if sum(r["contested"]["pres"])]
            L.append(f"| {opp} | {len(rs)} | {sum(r['win'] for r in rs)}-{sum(not r['win'] for r in rs)} | {share(rs, 'them', 'farm'):.1f} | "
                     f"{share(rs, 'them', 'walk'):.1f} | {wend(rs, 'them', 'idle'):.0f} | {100 * per(rs, 'them', 'recall_starts'):.0f} | "
                     f"{coh(rs, 'them'):.1f} | {f.get('won', 0)}-{f.get('lost', 0)} | "
                     f"{100 * sum(ps) / len(ps) if ps else float('nan'):.0f}% |")
        L.append("")
        L.append("Recall starts: some top bots end almost every turn with cancel channel -> act -> start recall, so a recall "
                 "they let run completes a turn earlier; `replay.py track GAME --champ LABEL` shows the pattern.")
    L += ["", "## 6. Games", "", "| game | map | opponent | result | rounds | us: fight/farm/walk/idle % | them: fight/farm/walk/idle % |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["win"], r["map"])):
        def b4(side):
            t = r["teams"][r["us"] if side == "us" else 1 - r["us"]]
            n = max(1, t["turns"])
            return "/".join(f"{100 * t['acts'].get(a, 0) / n:.0f}" for a in ("fight", "farm", "walk", "idle"))
        L.append(f"| {os.path.basename(r['spec'])[:13]} | {r['map']} | {r['opp']} | {'win' if r['win'] else 'loss'} | {r['rounds']} | {b4('us')} | {b4('them')} |")
    text = "\n".join(L) + "\n"
    if out:
        open(out, "w").write(text)
        print(f"wrote {out} ({len(rows)} games)")
    else:
        print(text)


# ---------------------------------------------------------------- command line
def _warm_one(spec):
    """'hit' (cache current), 'decoded' or 'fail ...' for one game; never exits."""
    try:
        raw, d, summary, _ = locate(spec)
        if d is not None:
            return "hit"
        cp = os.path.join(CACHE, hashlib.sha1(raw).hexdigest()[:16] + ".json.gz")
        if os.path.exists(cp):
            try:
                with gzip.open(cp, "rt") as f:
                    if json.load(f).get("rdec", RDEC_CACHED) == rdec_id():
                        return "hit"
            except (OSError, ValueError, EOFError):
                pass
        decode_bytes(raw, summary, src=spec)
        return "decoded"
    except (SystemExit, Exception) as e:
        return f"fail {spec}: {str(e)[:160]}"


def cmd_warm(specs, jobs=2):
    games = expand_specs(specs)
    import multiprocessing
    with multiprocessing.get_context("fork").Pool(max(1, min(jobs, len(games))), os.nice, (10,)) as pool:
        res = pool.map(_warm_one, games, chunksize=1)
    fails = [r for r in res if r.startswith("fail")]
    print(f"{len(games)} games: {res.count('hit')} cached, {res.count('decoded')} decoded, {len(fails)} failed")
    for r in fails[:10]:
        print("  " + r)


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        sys.exit(1)

    def opt(name, default=None, cast=str):
        if name in a:
            i = a.index(name)
            v = cast(a[i + 1])
            del a[i:i + 2]
            return v
        return default
    us = opt("--us")
    cmd = a.pop(0)
    if cmd == "report":
        out, jobs = opt("--out"), opt("--jobs", 4, int)
        cmd_report(a, out, jobs, us)
        return
    if cmd == "warm":
        cmd_warm(a, opt("--jobs", 2, int))
        return
    every, rnd, box, around = opt("--every", 50, int), opt("--round", None, int), opt("--box"), opt("--around")
    trail_s = opt("--trail")
    champ, lo, hi = opt("--champ"), opt("--from", 0, int), opt("--to", 10 ** 9, int)
    radius, limit = opt("--radius", 5, int), opt("--limit", 80, int)
    show_all = "--all" in a
    a = [x for x in a if x != "--all"]
    if cmd == "group" and len(a) > 1 and a[0].isdigit() and not a[1].isdigit():
        a[0], a[1] = a[1], a[0]  # accept `group GID GAME` as well as `group GAME GID`
    g = load(a[0], us)

    def body(v):
        """A body by its label (1-6 team A, K L N P R S team B, as every output prints them) or id:N."""
        by_label = {lab: c for c, lab in g.label.items()}
        if v in by_label:
            return by_label[v]
        if v.startswith("id:") and int(v[3:]) in g.bodies:
            return int(v[3:])
        sys.exit(f"no body {v!r}; bodies: " + ", ".join(g.who(c) for c in sorted(g.bodies)))
    if cmd == "info":
        cmd_info(g)
    elif cmd == "timeline":
        cmd_timeline(g, every)
    elif cmd == "show":
        bx = tuple(int(v) for v in box.split(",")) if box else None
        ar = None
        if around:
            p = around.split(",")
            ar = (body(p[0]), int(p[1]) if len(p) > 1 else 12)
        trl = None
        if trail_s:
            p = trail_s.split(",")
            trl = (body(p[0]), int(p[1]) if len(p) > 1 else 20)
        cmd_show(g, rnd if rnd is not None else g.last_round, bx, ar, trl)
    elif cmd == "track":
        if champ is None:
            sys.exit("track needs --champ LABEL; bodies: " + ", ".join(g.who(c) for c in sorted(g.bodies)))
        cmd_track(g, body(champ), lo, hi)
    elif cmd == "activity":
        cmd_activity(g)
    elif cmd == "fights":
        cmd_fights(g, show_all)
    elif cmd == "presence":
        cmd_presence(g, radius)
    elif cmd == "group":
        cmd_group(g, int(a[1]), radius)
    elif cmd == "moments":
        cmd_moments(g, limit)
    elif cmd == "diff":
        cmd_diff(g, load(a[1], us))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
