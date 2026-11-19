#!/usr/bin/env python3
"""vercheck: was a live game played by the bot version we file it under? (8 Nov; b1570: unranked groups other teams open against us
can be played by an OLD submission, and livepipe/critgame filed them by the clock under the newest version.)

A bot's first draft turn (and each champion's first turn, its setup) is deterministic: its fuel depends only on the bot and the map (it runs before any pick it can see from a
foe it doesn't know). The game bundle carries our team's per-turn fuel (team-a.fuel / team-b.fuel; draft turns first); one cxe round
of the claimed version on the game's map gives that version's first draft turn. Equal: 'ok'. Different: 'foreign' (another version
played it). Not checkable (no fuel file, no map, build failed): 'unknown' (callers keep the game).
Measured on v609/v610 (b1570): 99/100 and 20/20 of our own games match to the unit; the 4 old-bot groups differ.

usage: python3 -I tools/lab/vercheck.py X_DIR SIDE MAP BOT       one game (X_DIR holds replay.repl26a and team-X.fuel) -> ok|foreign|unknown
       python3 -I tools/lab/vercheck.py --set SETDIR BOT         every game of a fetched set (matches.txt): counts and the foreign ids
Results are cached in /data/zw4424/st/bq/vercheck.jsonl (match id + bot)."""
import json
import os
import struct
import subprocess
import sys
import tempfile

REPO = "/homes/zw4424/cambc"
CACHE = "/data/zw4424/st/bq/vercheck.jsonl"
MAPDIRS = ["/data/zw4424/ablproj_4.0.0/maps", "/data/zw4424/st/cxe/proj/maps"]
REPL2MAP = "/data/zw4424/st/b746/py/repl2map.py"
sys.path.insert(0, f"{REPO}/tools/cxe")
_cache = None
_so = {}


def _load():
    global _cache
    if _cache is None:
        _cache = {}
        try:
            for ln in open(CACHE):
                try:
                    r = json.loads(ln)
                    _cache[(r["mid"], r["bot"])] = r["v"]
                except (ValueError, KeyError):
                    pass
        except OSError:
            pass
    return _cache


def _save(mid, bot, v, why):
    _load()[(mid, bot)] = v
    try:
        with open(CACHE, "a") as f:
            f.write(json.dumps(dict(mid=mid, bot=bot, v=v, why=why)) + "\n")
    except OSError:
        pass


def our_turns(xdir, side):
    """our per-turn fuel from the bundle's team-X.fuel (draft turns first), or None"""
    p = os.path.join(xdir, f"team-{side.lower()}.fuel")
    try:
        d = open(p, "rb").read()
        vals = struct.unpack_from("<%dQ" % ((len(d) - 13) // 8), d, 13)
        return list(vals[8:]) if len(vals) > 8 else None
    except (OSError, struct.error):
        return None


def our_first(xdir, side):
    """our first draft turn's fuel, or None"""
    t = our_turns(xdir, side)
    return t[0] if t else None


def map_file(mp, xdir, work):
    for d in MAPDIRS:
        for nm in (mp, mp.replace("_", "-"), mp.replace("-", "_")):
            p = os.path.join(d, nm + ".map26a")
            if os.path.exists(p):
                return p
    out = os.path.join(work, "m.map26a")
    rp = os.path.join(xdir, "replay.repl26a")
    if os.path.exists(REPL2MAP) and os.path.exists(rp):
        subprocess.run([sys.executable, "-I", REPL2MAP, rp, out], capture_output=True, timeout=120)
        if os.path.exists(out):
            return out
    return None


FT_SHORT = ["Ry", "VV", "Ve", "CI", "St", "Pr", "Ma", "Wi", "Re", "Va", "Ta", "HoR"]  # replay.DRAFT order = forceteam's indices


def foe_lineup(xdir, side):
    """the foe's draft (champion indices, in pick order) from the replay, or None"""
    try:
        sys.path.insert(0, os.path.join(REPO, "tools", "lab"))
        import replay as R
        g = R.load(os.path.join(xdir, "replay.repl26a"), side.upper())
        dr = (g.d.get("draft") or [[], []])[1 - g.us]
        return [int(k) for k in dr] if dr and all(0 <= int(k) < len(FT_SHORT) for k in dr) else None
    except (Exception, SystemExit):  # noqa: BLE001
        return None


def forced_foe(lineup, base):
    """a bot that drafts LINEUP (tools/lab/forceteam.py), one per lineup, kept and reused: our first champion turns read the foe's picks
    (8 Nov: v613 v itself missed 6 of 16 of its own ranked games by a constant; v the foe's lineup it matched to the unit)"""
    import fcntl
    name = "nova_ft_vc" + "".join(f"{k:x}" for k in lineup)
    if os.path.isdir(os.path.join(REPO, "bots", name, "src")):
        return name
    with open(f"/data/zw4424/st/bq/.{name}.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if not os.path.isdir(os.path.join(REPO, "bots", name, "src")):
            r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/forceteam.py"), base, name, ",".join(FT_SHORT[k] for k in lineup), "--no-build"],  # cxebuild builds it (one build, not two)
                               capture_output=True, text=True, cwd=REPO, timeout=1800)
            if r.returncode or not os.path.isdir(os.path.join(REPO, "bots", name, "src")):
                return None
    return name


def cxe_early(bot, mapf, side, work, foe=None):
    """BOT's draft turns and each champion's first turn on MAPF in seat SIDE (BOT v itself, 3 rounds) -> (draft list, first champion turns).
    8 Nov (Combat, 00anvil 01a1b9c7): v607-v616 share the first draft turn, so the draft alone can't tell them apart; the first champion
    turns (setup, before any foe contact) can: the game read 171967/171805/172492 = v613 exactly, v616 +77 on each."""
    import cxebuild
    if bot not in _so:
        _so[bot] = cxebuild.build_bot(bot)
    exe = cxebuild.build_host()
    pre = os.path.join(work, "e")
    if foe and foe not in _so:
        _so[foe] = cxebuild.build_bot(foe)
    so_f = _so[foe] if foe else _so[bot]
    a, b = (_so[bot], so_f) if side.upper() == "A" else (so_f, _so[bot])
    subprocess.run(["nice", "-n", "10", exe, a, b, mapf, pre, "--rounds", "3", "--fuel-log"], capture_output=True, timeout=300)
    t = "0" if side.upper() == "A" else "1"
    try:
        rows = [ln.split("\t") for ln in open(pre + ".fuel.tsv").read().splitlines()[1:]]
    except OSError:
        return None, None
    rows = [r for r in rows if r[2] == t]
    draft = [int(r[6]) for r in rows if r[0] == "0"]
    ch = [r for r in rows if r[0] == "1"]
    r0 = min((int(r[1]) for r in ch), default=None)
    return draft, [int(r[6]) for r in ch if int(r[1]) == r0]


def cxe_first(bot, mapf, side, work):
    """BOT's first draft-turn fuel on MAPF in seat SIDE (one cxe round, BOT v itself)"""
    import cxebuild
    if bot not in _so:
        _so[bot] = cxebuild.build_bot(bot)
    exe = cxebuild.build_host()
    pre = os.path.join(work, "g")
    subprocess.run(["nice", "-n", "10", exe, _so[bot], _so[bot], mapf, pre, "--rounds", "1", "--fuel-log"], capture_output=True, timeout=300)
    t = "0" if side.upper() == "A" else "1"
    try:
        for ln in open(pre + ".fuel.tsv").read().splitlines()[1:]:
            c = ln.split("\t")
            if c[0] == "0" and c[2] == t:
                return int(c[6])
    except OSError:
        pass
    return None


DRAFT_MEMO = "/data/zw4424/st/bq/vercheck_draft.jsonl"  # bot|side|map sha -> first draft turn fuel (deep=False checks)
_dmemo = None


def _draft_memo():
    global _dmemo
    if _dmemo is None:
        _dmemo = {}
        try:
            for ln in open(DRAFT_MEMO):
                try:
                    r = json.loads(ln)
                    _dmemo[r["k"]] = r["d"]
                except (ValueError, KeyError):
                    pass
        except OSError:
            pass
    return _dmemo


def check(mid, xdir, side, mp, bot, deep=True):
    """-> 'ok' | 'foreign' | 'unknown'"""
    key = bot + ("#2" if deep else "#1")  # 8 Nov: #2 draft + first champion turns v a forced copy of the foe's lineup; #1 the draft turn only (deep=False:
    # routine triage and livepipe, because a forced-foe build per new lineup doubled critgame's pass time, 23 -> 45 min)
    c = _load().get((mid, key))
    if c:
        return c
    turns = our_turns(xdir, side)
    if not turns:
        return "unknown"  # not cached: the fuel file may arrive later
    have = turns[0]
    with tempfile.TemporaryDirectory(prefix="vck_", dir="/data/zw4424/tmp" if os.path.isdir("/data/zw4424/tmp") else None) as work:
        mapf = map_file(mp, xdir, work)
        if not mapf:
            return "unknown"
        lineup = foe_lineup(xdir, side) if deep else None
        foe = forced_foe(lineup, bot) if lineup else None
        if foe and foe not in _so:
            try:
                import cxebuild
                _so[foe] = cxebuild.build_bot(foe)
            except (Exception, SystemExit):  # noqa: BLE001  no forced foe: the draft decides alone
                foe = None
        # 9 Nov 21:10Z (Coordinator: critgame fell behind; 81 cxebuild calls in one pass): the draft-only check (deep=False) depends on the bot, the
        # map's content and our side alone, and live games reuse ~128 maps: memoise that first draft turn (DRAFT_MEMO) and skip the engine round
        import hashlib
        mkey = None
        if not deep:
            try:
                mkey = f"{bot}|{side}|{hashlib.sha1(open(mapf, 'rb').read()).hexdigest()[:16]}"
            except OSError:
                mkey = None
        memo = _draft_memo()
        if mkey and mkey in memo:
            draft, champ = [memo[mkey]], []
        else:
            try:
                draft, champ = cxe_early(bot, mapf, side, work, foe)
            except (Exception, SystemExit):  # noqa: BLE001  a build failure is not a verdict
                return "unknown"
            if mkey and draft:
                memo[mkey] = draft[0]
                try:
                    with open(DRAFT_MEMO, "a") as fh:
                        fh.write(json.dumps(dict(k=mkey, d=draft[0])) + "\n")
                except OSError:
                    pass
    if not draft:
        return "unknown"
    if draft[0] != have:
        v, why = "foreign", f"first draft turn {have} in the game, {draft[0]} for {bot}"
    else:
        game_ch = turns[len(draft):len(draft) + len(champ)]
        same = sum(a == b for a, b in zip(game_ch, champ))
        # every champion's first turn differing = another build (a single one may differ by what it saw at r1); none to compare = draft only
        # without the foe's lineup the champion turns are not comparable (they read the foe's picks): the draft decides alone
        v = "foreign" if foe and champ and len(game_ch) == len(champ) and same == 0 else "ok"
        why = f"draft {have} equal; v {foe or 'no foe lineup'}: first champion turns {game_ch} in the game v {champ} for {bot}: {same} equal"
    _save(mid, key, v, why)
    return v


def main():
    a = sys.argv[1:]
    if a[:1] == ["--set"] and len(a) == 3:
        d, bot = a[1], a[2]
        cnt, foreign = {"ok": 0, "foreign": 0, "unknown": 0}, []
        for ln in open(os.path.join(d, "matches.txt")):
            x = ln.split()
            if len(x) < 3:
                continue
            v = check(x[0], os.path.join(d, "x_" + x[0]), x[2], x[1], bot)
            cnt[v] += 1
            if v == "foreign":
                foreign.append(x[0])
        print(f"{d} v {bot}: {cnt}" + (f"; foreign: {' '.join(foreign)}" if foreign else ""))
        return 0
    if len(a) != 4:
        sys.exit(__doc__)
    print(check(os.path.basename(a[0].rstrip("/"))[2:], a[0], a[1], a[2], a[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
