#!/usr/bin/env python3
"""rvision: who saw whom, from the engine's own vision (Tool builder 2, 4 Nov; owner: make the website visualiser readable for
Claude; analysts: per-champion vision, first-seen, 'hit from fog', what each body knew).

usage: python3 -I tools/lab/rvision.py GAME [--us A|B] [--hits all|fog] [--tsv OUT.tsv] [--mem]
       python3 -I tools/lab/rvision.py --tsv-dir OUTDIR [GAMES...] [--from-tsv ALL.tsv] [--us A|B] [--jobs N] [--redo]
  --tsv-dir (10 Nov, Combat): batch --tsv. One OUTDIR/<name>.tsv per game, byte-identical to `rvision.py GAME --tsv`;
  <name> is the match id (x_<id>/replay.repl26a, <id>.zip, --from-tsv rows) else the spec with / and : as _. N workers
  (default 4, max 8, nice 10; each waits while the 1-min load is over 40). A game whose OUTDIR/<name>.tsv exists is
  skipped (--redo: re-write). --from-tsv: gameindex.py's all.tsv (columns by header: id, path, our_seat); each row's path
  (else id) with its seat. The table's labels do not depend on the seat; with no seat known, A is assumed.
  Prints one summary line: done / cached (vision from the cache) / skipped / failed (with reasons); exit 1 if any failed.
  GAME as replay.py takes it (match id or prefix, RUN:ID, a .repl26a file).
  Runs tools/lab/rvision.js once per replay (about 1.6 s, cached in /data/USER/rvision_cache/<sha1>.json.gz): at the start of
  every champion turn the engine's visualiser gives EACH champion's own vision, ward included (a dead one: its ward only), exactly the fog the
  website shows for that champion. Checked: 32/32 champion basic attacks made before moving had the target in the attacker's
  engine vision; turn starts match replay.py's 9,777/9,777.
Prints, for our team ('us') and theirs:
  first seen   the first round each enemy body was in any of the team's views (and which body saw it)
  coverage     share of enemy alive turn-starts in view of at least one body (team), and in view of the body nearest to it
  hits         every hit on a champion (basic attacks and spells, from the decoded effects), classified at the moment of the
               hit by the VICTIM's last turn-start view and the team's: SEEN (victim saw the attacker), TEAM (only a mate
               saw it), FOG (nobody on the victim's team saw it); totals by class and damage, then the list (--hits fog: fog only)
  --mem        the team memory (8 bytes per team) at every change, in hex, IF the replay holds it (live and CLI replays
               don't: they record actions, not the bots' memory writes)
  --tsv OUT    the per-turn table: round, acting body, then for each body the enemy labels it saw
Labels are replay.py's: team A 1-6, team B K L N P R S. Vision is per champion by the rules (GameRules 'Vision is not shared'),
so 'team' here means 'some body of the team saw it', i.e. what the team COULD have known through its 8-byte memory."""
import collections
import gzip
import hashlib
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay as RP  # noqa: E402

CACHE = os.path.exists("/data/USER/st/bq/live.txt") and '/data/USER/rvision_cache' or os.path.join(os.environ.get("_CONDOR_SCRATCH_DIR") or "/tmp", 'USER-rvision_cache')  # 10 Nov: /data only on the main machine (live.txt there); on Condor nodes the job's scratch dir, else /tmp (a lab user found our caches on their desktop's /data)
SCHEMA = 3  # 3 (7 Nov): dead bodies' ward vision counts


def cached(out):
    """a cache entry of the current schema, else None (the caller re-renders: old entries had dead bodies' masks at 0)"""
    try:
        v = json.load(gzip.open(out))
    except (OSError, ValueError, EOFError):
        return None
    return v if v.get("schema") == SCHEMA else None


def vision(spec, info=None):
    raw, d, summary, meta = RP.locate(spec)
    if raw is None:
        sys.exit(f"rvision: no replay bytes for {spec} (only a decoded copy)")
    h = hashlib.sha1(raw).hexdigest()
    out = f"{CACHE}/{h}.json.gz"
    v = cached(out)
    if info is not None:
        info["cached"] = v is not None
    if v is None:
        os.makedirs(CACHE, exist_ok=True)
        tmp = f"{CACHE}/.{h}.{os.getpid()}.repl26a"
        open(tmp, "wb").write(raw)
        try:
            try:  # 10 Nov: the shared decode timeout (REPLAY_DECODE_TIMEOUT, default 120 s)
                r = subprocess.run(["nice", "-n", "19", "node", os.path.join(HERE, "rvision.js"), tmp, out], capture_output=True, text=True,
                                   timeout=RP.DECODE_TIMEOUT)
            except subprocess.TimeoutExpired:
                RP._note_timeout(spec, "rvision.js")
                raise RP.DecodeTimeout(f"rvision.js on {spec} ran over {RP.DECODE_TIMEOUT:.0f} s (REPLAY_DECODE_TIMEOUT)") from None
            if r.returncode:
                sys.exit(f"rvision.js failed: {(r.stdout + r.stderr).strip()[-400:]}")
        finally:
            os.remove(tmp)
        v = json.load(gzip.open(out))
    return v


def hits_of(g):
    """[(turn index, round, attacker, victim, damage, kind)] from decoded acts: basic attacks ('a') and casts ('c') whose effects
    lower a champion's HP."""
    out = []
    for ti, t in enumerate(g.turns):
        for a in t[-1]:
            if a[0] not in ("a", "c"):
                continue
            fx = a[5] if a[0] == "a" else (a[7] if len(a) > 7 else [])
            for e in fx or []:
                if len(e) >= 3 and e[0] == 1 and e[2] < 0 and g.team_of.get(e[1]) != g.team_of.get(t[1]):
                    out.append((ti, t[0], t[1], e[1], -e[2], "basic" if a[0] == "a" else "spell"))
    return out


def main():
    a = sys.argv[1:]
    if "--tsv-dir" in a:
        return batch(a)
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    g = RP.load(a[0], us=opt("--us"))
    v = vision(a[0])
    n, team = v["n"], v["teamOf"]
    lab = lambda b: g.label.get(b, str(b))  # noqa: E731
    name = lambda b: f"{lab(b)}:{g.bodies[b]['name']}" if b in g.bodies else str(b)  # noqa: E731
    rows = v["turns"]
    if len(rows) != len(g.turns):
        print(f"!! turn starts differ: vision {len(rows)} v decode {len(g.turns)}; matching by (round, body)", file=sys.stderr)
    by_key = {(r[0], r[1]): r for r in rows}
    us = g.us
    # first seen + coverage
    first = {}
    cov = {0: [0, 0], 1: [0, 0]}
    for r in rows:
        rnd, am, masks = r[0], r[2], r[3:]
        for t in (0, 1):
            seen = 0
            for i in range(n):
                if team[i] == t:
                    seen |= masks[i]
            for j in range(n):
                if team[j] == t or team[j] < 0:
                    continue
                if (seen >> j) & 1 and (t, j) not in first:
                    first[(t, j)] = (rnd, next(i for i in range(n) if team[i] == t and (masks[i] >> j) & 1))
            alive = [j for j in range(n) if team[j] not in (t, -1) and (am >> j) & 1]
            cov[t][0] += sum((seen >> j) & 1 for j in alive)
            cov[t][1] += len(alive)
    side = {us: "us", 1 - us: "them"}
    print(f"rvision {a[0]}: {g.W}x{g.H}, {n} bodies, {len(rows)} turn starts, our side {'AB'[us]} (vision.js {v['seconds']:.1f} s)")
    for t in (us, 1 - us):
        print(f"  {side[t]:4s} first saw: " + ", ".join(f"{name(j)} r{first[(t, j)][0]} (by {lab(first[(t, j)][1])})" if (t, j) in first
                                                    else f"{name(j)} never" for j in range(n) if team[j] == 1 - t))
        c = cov[t]
        print(f"  {side[t]:4s} saw {100 * c[0] / max(1, c[1]):.1f}% of the enemy's living body-turn-starts (some body of the team had it in view)")
    # hits classified by the victim's and its team's last views before the hit
    last = [0] * n  # latest mask per body (updated at its own turn starts)
    cls = {t: {"SEEN": [0, 0], "TEAM": [0, 0], "FOG": [0, 0]} for t in (0, 1)}
    hl = []
    hits = hits_of(g)
    hi = 0
    for ti, t in enumerate(g.turns):
        r = by_key.get((t[0], t[1]))
        if r:
            last[t[1]] = r[3 + t[1]]
        while hi < len(hits) and hits[hi][0] == ti:
            _, rnd, att, vic, dmg, kind = hits[hi]
            hi += 1
            vt = team[vic]
            team_seen = 0
            for i in range(n):
                if team[i] == vt:
                    team_seen |= last[i]
            c = "SEEN" if (last[vic] >> att) & 1 else "TEAM" if (team_seen >> att) & 1 else "FOG"
            cls[vt][c][0] += 1
            cls[vt][c][1] += dmg
            hl.append((rnd, att, vic, dmg, kind, c, vt))
    for t in (us, 1 - us):
        tot = sum(x[1] for x in cls[t].values()) or 1
        print(f"  hits taken by {side[t]}: " + ", ".join(f"{k} {x[0]} ({x[1]:.0f} dmg, {100 * x[1] / tot:.0f}%)" for k, x in cls[t].items()))
    mode = opt("--hits")
    if mode:
        for rnd, att, vic, dmg, kind, c, vt in hl:
            if mode == "fog" and c != "FOG":
                continue
            print(f"    r{rnd:4d} {name(att):>16s} -> {name(vic):16s} {kind:5s} -{dmg:.0f}  {c}")
    if "--mem" in a and not any(h0.strip("0") or h1.strip("0") for _, h0, h1 in v["mem"]):
        print("  team memory: not recorded in this replay (the engine's replay holds game actions, not the bots' memory writes)")
    elif "--mem" in a:
        prev = None
        for rnd, h0, h1 in v["mem"]:
            cur = (h0, h1)
            if cur != prev:
                print(f"    mem r{rnd:4d}  A {h0}  B {h1}")
                prev = cur
    if opt("--tsv"):
        write_tsv(opt("--tsv"), g, v)
        print(f"  per-turn table: {opt('--tsv')}")


def write_tsv(path, g, v):
    """the per-turn table (--tsv and --tsv-dir write this same text)"""
    n = v["n"]
    lab = lambda b: g.label.get(b, str(b))  # noqa: E731
    with open(path, "w") as f:
        f.write("round\tacting\t" + "\t".join(f"sees_{lab(i)}" for i in range(n)) + "\n")
        for r in v["turns"]:
            f.write(f"{r[0]}\t{lab(r[1])}\t" + "\t".join(",".join(lab(j) for j in range(n) if (r[3 + i] >> j) & 1) for i in range(n)) + "\n")


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def out_name(spec):
    """OUTDIR file stem for a game spec: the match id when the spec holds one, else the spec with / and : as _"""
    m = UUID.findall(spec)
    if m:
        return m[-1]
    b = os.path.basename(spec.rstrip("/")) if os.path.exists(spec) else spec
    return re.sub(r"[^\w.-]", "_", re.sub(r"\.(repl26a|zip|json\.gz|json)$", "", b)) or "game"


def wait_load(limit=40.0, most=600):
    t0 = time.time()
    while time.time() - t0 < most:
        try:
            if float(open("/proc/loadavg").read().split()[0]) < limit:
                return
        except (OSError, ValueError):
            return
        time.sleep(10)


def batch_one(job):
    """(spec, seat, out path) -> (status, spec, note); status done | cached | failed. Writes atomically."""
    spec, seat, out = job
    wait_load()
    info = {}
    try:
        try:
            g = RP.load(spec, us=seat or "A")
        except ValueError:
            g = RP.load(spec, us="A")  # labels do not depend on the seat
        v = vision(spec, info)
        tmp = f"{out}.{os.getpid()}.tmp"
        write_tsv(tmp, g, v)
        os.replace(tmp, out)
    except SystemExit as e:
        return "failed", spec, str(e)[-200:]
    except Exception as e:  # noqa: BLE001 (one bad replay must not stop the batch)
        return "failed", spec, f"{type(e).__name__}: {str(e)[-200:]}"
    return ("cached" if info.get("cached") else "done"), spec, ""


def batch(a):
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d  # noqa: E731
    outdir = opt("--tsv-dir")
    if not outdir:
        sys.exit("rvision: --tsv-dir OUTDIR [GAMES...] [--from-tsv ALL.tsv] [--jobs N]")
    takes = {"--tsv-dir", "--from-tsv", "--jobs", "--us"}
    specs = [(x, opt("--us")) for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in takes)]
    if opt("--from-tsv"):
        rows = [ln.rstrip("\n").split("\t") for ln in open(opt("--from-tsv")) if ln.strip()]
        hd = {k: i for i, k in enumerate(rows[0])}
        if "id" not in hd:
            sys.exit(f"rvision: {opt('--from-tsv')} has no 'id' column (want gameindex.py's all.tsv with its header)")
        get = lambda r, k: r[hd[k]] if k in hd and hd[k] < len(r) else ""  # noqa: E731
        for r in rows[1:]:
            p, seat = get(r, "path"), get(r, "our_seat").upper()
            specs.append((p if p not in ("", "-") and os.path.exists(p) else get(r, "id"), seat if seat in ("A", "B") else None))
    if not specs:
        sys.exit("rvision: --tsv-dir: no games (GAMES... or --from-tsv ALL.tsv)")
    os.makedirs(outdir, exist_ok=True)
    jobs, skipped, dups, names, fails = [], 0, 0, {}, []
    for spec, seat in specs:
        nm = out_name(spec)
        if nm in names:
            dups += 1  # the same match id twice (an id and its path, or a repeated spec)
            continue
        names[nm] = spec
        out = os.path.join(outdir, nm + ".tsv")
        if os.path.exists(out) and "--redo" not in a:
            skipped += 1
            continue
        jobs.append((spec, seat, out))
    nj = max(1, min(8, int(opt("--jobs", "4")), len(jobs) or 1))
    try:
        os.nice(10)
    except OSError:
        pass
    cnt = {"done": 0, "cached": 0}
    t0 = time.time()
    if jobs:
        with multiprocessing.Pool(nj) as pool:
            for st, spec, note in pool.imap_unordered(batch_one, jobs):
                if st == "failed":
                    fails.append((spec, note))
                else:
                    cnt[st] += 1
    for spec, note in fails:
        print(f"  FAIL {spec}: {note}", file=sys.stderr)
    why = collections.Counter(n[:50] for _, n in fails)
    print(f"rvision --tsv-dir {outdir}: {len(names)} games: {cnt['done']} done, {cnt['cached']} cached, {skipped} skipped (exist), " + (f"{dups} repeated, " if dups else "") +
          f"{len(fails)} failed" + (f" ({'; '.join(f'{k} x{c}' for k, c in why.most_common(4))})" if fails else "")
          + f", {nj} jobs, {time.time() - t0:.0f} s")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
