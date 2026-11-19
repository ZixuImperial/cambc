#!/usr/bin/env python3
"""critgame: flag a game as CRITICAL; it is cut into its key windows of rounds and stays OPEN until every window has a full
verdict and an independent grill agrees (Tool builder 2, 5 Nov; owner: 'analysts need a way to flag a game as critical and it
would force the investigation to be deeper or section some rounds out').

usage: python3 -I tools/lab/critgame.py flag GAME --why "TEXT" [--us A|B] [--by NAME] [--rounds 120-140,300] [--k 4]
       python3 -I tools/lab/critgame.py close GAME "why" [--who WHO]   no more work on it (status and the open cap skip it)
       python3 -I tools/lab/critgame.py close --batch ID... "why" [--file F] [--who WHO] [--dry]   close many in one process (the
           last argument is the why; --file F adds ids, first word per line, '#' comments); one line per id: closed / FAIL / DRY
       python3 -I tools/lab/critgame.py brief GAME N [--grill|--compare]   the exact prompt for a walker on window N; --grill is step 1 of a BLIND grill (a copy of the evidence in blind_N/, no verdict path), --compare its step 2 (the newest blind_N*/walk.txt, or --blind DIR)
       python3 -I tools/lab/critgame.py claim GAME WHO [--force]   take the game: one analyser per game (a second claim is refused;
                                                                 brief warns a caller who isn't the owner: pass --who WHO); status shows owners
       python3 -I tools/lab/critgame.py status [GAME]            OPEN / DISPUTED / DONE per game and window (IDENTICAL: a turn-for-turn copy of an earlier flag)
       python3 -I tools/lab/critgame.py link COPY FIRST [--force] mark a flagged COPY identical to FIRST (8 Nov: flag does this itself; --windows forces windows)
       python3 -I tools/lab/critgame.py check GAME               re-check every verdict and grill file, say what is missing
       python3 -I tools/lab/critgame.py addwin GAME R0-R1 [--kind early]   one more window; regen GAME rebuilds missing dossiers
  windows also include an EARLY one: the first round our deaths lead theirs by 3 (Econ: an early collapse can set the game)
       python3 -I tools/lab/critgame.py auto [--gap 50] [--dry] [--loop --every 900]   flag every ranked or unranked loss of the LIVE version
           to a team rated >= GAP Elo below us (owner 5 Nov: such a loss means a critical flaw); 100+ below are marked HIGH.
           Every other loss (and every win, at 0.3x priority: owner 'improve our wins, lower priority') is TRIAGED for free (owner 5 Nov: 'analyse games we lose in general, priority by how bad a mistake or the
           difference; deep dives cost too much'): replay-based severity (worst 25-round fall, best lead held, faults; x1.5 when that
           fall exceeds the final margin; repeated kinds of fall weigh up to 1.5x; 12 games a pass, losses first, ~25 s each) into triage.jsonl. When no flagged game of the live
           version is open, the top-priority one is flagged LIGHT every --light-every s (1800): ONE window (its worst stretch), one
           walker, no grill.
       python3 -I tools/lab/critgame.py triage [--version vNNN] [--top 25]   the live version's losses ranked by priority
           Lists our ranked games from the platform (createdAt after the live version's ship), rates teams from the current ladder,
           downloads the replay into /data/USER/plat/crit_auto and flags it (by=auto). Daemon: pid /data/USER/st/crit/auto.pid,
           log auto.log; start: setsid nohup python3 -I tools/lab/critgame.py auto --loop --every 900 >> /data/USER/st/crit/auto.log 2>&1 &
       python3 -I tools/lab/critgame.py prune [--apply]   delete what a finished or stale game no longer needs (owner 5 Nov:
           'delete files'): its downloaded replay (plat/crit_auto/x_ID) and its window_N.txt dossiers, when the game is DONE (> 6 h
           ago) or its version is no longer live. verdict/grill/meta files stay (a few hundred bytes: the findings). DRY by default;
           the auto loop runs it with --apply every pass.
           Each pass also runs `replaycheck.py track`: flaws whose fix is live are retested on their game; a lost retest is flagged here, prio high.
  status lists unfinished games of the last 6 h, most urgent first, whatever version they were flagged under (ships come every 30-60 min,
  and a ship must not hide open work); new games come from the live version only. At most 8 unfinished critical games: more wait in triage. --all shows everything.
  GAME: a match id (or 8+ chars), a visualiser link (https://2026a.battlecode.co.uk/game/visualiser/<id>), RUN:ID or a .repl26a.
flag cuts the game into windows (files in /data/USER/st/crit/<id8>/):
  - the K (4) windows where OUR net position fell most, plus the one where it rose most, plus every --rounds window the analyst
    names (R0-R1, or R = R-10..R+8). Net position = (our tributed + carried gems) - (theirs), from the replay's round rows;
    windows grow around the moments in them (deaths, fights, bag losses, stolen captures, lead changes, fuel) and never overlap.
  - window_N.txt, the evidence dossier: net position through the window, its moments, every champion hit in it with the
    victim's vision class (rvision: SEEN / TEAM / FOG), turn-by-turn tracks of the 2-4 champions most involved, and the map at
    the window's end with our most involved champion's trail. A walker reads this one file first.
  - window_N.verdict, written by the walker: WHAT (what happened), WHY (the decision that caused it: a bot file:line, or
    'unknown: <what would tell>'), BETTER (the better play and what it was worth, in gems or gold), CHECK (how it was verified:
    re-walk, rvision, puppet, local repro), CONF (high / medium / low).
  - window_N.grill, written by a SECOND walker that re-walks the window without trusting the verdict: AGREE (yes / no), WHY, BY.
    A verdict rewritten after its grill needs a new grill.
A game is DONE when every window has a valid verdict and an agreeing grill; DISPUTED when a grill says no; else OPEN.
Nothing here plays games: puppet.py / local repro are the walker's choice, named in CHECK."""
import collections
import contextlib
import glob
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay as R  # noqa: E402

ROOT = os.environ.get("CRIT_ROOT", "/data/USER/st/crit")  # CRIT_ROOT: a test area
INDEX = f"{ROOT}/index.jsonl"
FIELDS = ("WHAT", "WHY", "BETTER", "CHECK", "CONF")


def game_spec(s):
    m = re.search(r"visuali[sz]er/([0-9a-f-]{8,})", s)
    return m.group(1) if m else s


def gdir(spec):
    """the game's dir: the full match id (games of one match group share their first 13 characters), a prefix if one dir matches it"""
    if re.match(r"^[0-9a-f-]{8,}$", spec):
        if len(spec) < 36 and os.path.isdir(ROOT):
            hits = [d for d in os.listdir(ROOT) if d.startswith(spec)]
            if len(hits) > 1:
                sys.exit(f"critgame: {spec} matches {len(hits)} flagged games; give more of the id: {', '.join(hits[:4])}")
            if hits:
                return f"{ROOT}/{hits[0]}"
        return f"{ROOT}/{spec}"
    mid = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", spec)  # a replay path that names its match (x_ID/replay.repl26a)
    if mid:
        return f"{ROOT}/{mid.group(0)}"
    return f"{ROOT}/{re.sub(r'[^\w.-]', '_', os.path.basename(spec))}"


def capture(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            fn(*a)
        except SystemExit:
            pass
    return buf.getvalue()


def net_series(g):
    us = g.us
    out = {}
    for row in g.rounds:
        sub = (row[1], row[2])
        car = (row[3], row[4])
        out[row[0]] = (sub[us] + car[us]) - (sub[1 - us] + car[1 - us])
    return out


def moments(g):
    txt = capture(R.cmd_moments, g, 10 ** 6)
    res = []
    for ln in txt.split("\n"):
        m = re.match(r"^\s*(\d+)\s{2}(\w+)\s+(.*)$", ln)
        if m and m.group(2) not in ("monster", "bag"):
            res.append((int(m.group(1)), m.group(2), m.group(3)))
    for e in g.events:  # every champion death, not only big bags
        if e[1] == "death":
            side = "OUR" if g.team_of.get(e[2]) == g.us else "their"
            how = f"by a camp (camp {e[4]})" if e[3] == 2 else f"by {g.who(e[4]) if e[4] >= 0 else '?'}"
            res.append((e[0], "death", f"{side} {g.who(e[2])} killed {how} at ({e[6]},{e[7]}) carrying {e[5]} gems"))
    res.sort()
    return res


def cut(g, k, asked, rise=True):
    N = net_series(g)
    rs = sorted(N)
    if not rs:
        sys.exit("critgame: the replay has no round rows")
    last = rs[-1]
    mom = moments(g)
    cands = []
    for r, kind, _ in mom:
        if kind in ("fight", "death", "stolen", "lead", "fuel", "contest"):
            cands.append((max(1, r - 10), min(last, r + 8)))
    for w in range(1, last, 10):  # slow drifts without a single moment (a lost race, a long siege)
        cands.append((w, min(last, w + 25)))

    def delta(w):
        a, b = w
        na = N.get(max(r for r in rs if r <= a) if any(r <= a for r in rs) else rs[0], 0)
        nb = N.get(max(r for r in rs if r <= b), 0)
        return nb - na
    picked = [(a, b, "asked") for a, b in asked]

    def free(a, b):
        return all(b < x or a > y for x, y, _ in picked)
    # Econ 5 Nov: an early collapse can set the game without being the biggest gem fall (00ribs: 4 bodies lost before r170, gold
    # 440 v 909 at r300). EARLY window: the first round our deaths lead theirs by 3, from 10 rounds before the first of those deaths
    dd, first = 0, None
    for e in sorted((e for e in g.events if e[1] == "death"), key=lambda e: e[0]):
        dd += 1 if g.team_of.get(e[2]) == g.us else -1
        if dd <= 0:
            first = None
        elif first is None:
            first = e[0]
        if dd >= 3:
            w = (max(1, first - 10), min(last, e[0] + 5))
            if free(*w) and w[1] - w[0] <= 80:
                picked.append((w[0], w[1], "early"))
            break
    for w in sorted(set(cands), key=delta):
        if len([p for p in picked if p[2] == "fall"]) >= k:
            break
        if delta(w) < 0 and free(*w):
            picked.append((w[0], w[1], "fall"))
    for w in sorted(set(cands), key=lambda w: -delta(w)) if rise else []:
        if delta(w) > 0 and free(*w):
            picked.append((w[0], w[1], "rise"))
            break
    picked.sort()
    # grow each window back to the start of a fight or death just before it (the cause comes first), without overlapping
    mr = sorted(r for r, kind, _ in mom if kind in ("fight", "death", "stolen", "contest"))
    grown = []
    for i, (a, b, why) in enumerate(picked):
        lo = grown[-1][1] + 1 if grown else 1
        early = [r for r in mr if a - 15 <= r < a]
        if early:
            a = max(lo, early[0] - 5)
        late = [r for r in mr if b < r <= b + 6]
        hi = picked[i + 1][0] - 1 if i + 1 < len(picked) else last
        if late:
            b = min(hi, late[-1] + 3)
        grown.append((a, b, why))
    return [(a, b, why, delta((a, b))) for a, b, why in grown], N, mom


def involvement(g, a, b):
    """per body: HP lost + champion damage dealt + |gem change| + 500 per death, over rounds a..b"""
    sc = collections.Counter()
    for c, ts in g.by_champ.items():
        prev = None
        for t in ts:
            if not (a <= t[0] <= b):
                prev = t if t[0] < a else prev
                continue
            if prev is not None:
                sc[c] += max(0, prev[4] - t[4]) + abs(t[8] - prev[8]) * 5
                if prev[g.ci["alive"]] and not t[g.ci["alive"]]:
                    sc[c] += 500
            sc[c] += sum(d for _, d in R.hostile_hits(g, t))
            prev = t
    return sc


def rvision_hits(spec, us, a, b, cache={}):
    if spec not in cache:
        try:
            r = subprocess.run(["nice", "-n", "19", "python3", "-I", f"{HERE}/rvision.py", spec, "--us", "AB"[us], "--hits", "all"],
                               capture_output=True, text=True, timeout=600)
            cache[spec] = r.stdout.split("\n")
        except (subprocess.TimeoutExpired, OSError):
            cache[spec] = []
    out = []
    for ln in cache[spec]:
        m = re.match(r"^\s+r\s*(\d+)\s", ln)
        if m and a <= int(m.group(1)) <= b:
            out.append(ln.rstrip())
    return out


def vision_table(spec, us, d, cache={}):
    """{(round, acting label): {label: set of enemy labels it saw at that turn start}} from rvision --tsv (cached in the game dir)"""
    if spec in cache:
        return cache[spec]
    out = f"{d}/vision.tsv"
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(f"{HERE}/rvision.js"):
        try:
            subprocess.run(["nice", "-n", "19", "python3", "-I", f"{HERE}/rvision.py", spec, "--us", "AB"[us], "--tsv", out],
                           capture_output=True, text=True, timeout=600)
        except (subprocess.TimeoutExpired, OSError):
            pass
    tab = {}
    try:
        rows = [ln.rstrip("\n").split("\t") for ln in open(out)]
        head = rows[0]
        for r in rows[1:]:
            tab[(int(r[0]), r[1])] = {head[i][5:]: set(x for x in r[i].split(",") if x) for i in range(2, len(r))}
    except (OSError, ValueError, IndexError):
        pass
    cache[spec] = tab
    return tab


def near_foes(g, spec, d, bodies, a, b, radius=6):
    """for each turn of our tracked bodies: foes within radius at its turn start, with HP, channel + timer and whether it saw them"""
    vt = vision_table(spec, g.us, d)
    L = []
    for c in bodies:
        for t in g.by_champ.get(c, []):
            if not (a <= t[0] <= b) or not t[g.ci["alive"]]:
                continue
            seen = vt.get((t[0], g.label[c]), {}).get(g.label[c], set())
            fs = []
            for o, (x, y, u) in sorted(g.positions_before(t).items(), key=lambda kv: R.cheb(t[2], t[3], kv[1][0], kv[1][1])):
                if g.team_of[o] == g.us or not u[g.ci["alive"]] or x < 0:
                    continue
                dd = R.cheb(t[2], t[3], x, y)
                if dd > radius:
                    continue
                ch = u[g.ci["chType"]]
                cht = f" {R.CH_NAME.get(ch, 'channel').upper()} {u[g.ci['chTimer']]} left" if ch else ""
                fs.append(f"{g.label[o]} d{dd} {u[g.ci['hp']]}hp{cht} {'seen' if g.label[o] in seen else 'UNSEEN'}")
            if fs:
                L.append(f"  r{t[0]} {g.label[c]}@({t[2]},{t[3]}): " + "; ".join(fs))
    return L or ["  (no foe within %d of our tracked bodies at their turn starts)" % radius]


def turn_order(g, a, b):
    rows = collections.OrderedDict()
    for t in g.turns:
        if a <= t[0] <= b:
            rows.setdefault(t[0], []).append(g.label[t[1]])
    if not rows:
        return []
    orders = collections.Counter(tuple(v) for v in rows.values())
    common = orders.most_common(1)[0][0]
    L = [f"  usual order this window: {' '.join(common)} (left acts first)"]
    L += [f"  r{r}: {' '.join(v)}" for r, v in rows.items() if tuple(v) != common]
    return L


def dossier(g, spec, n, w, N, mom, why_flag, gd=None):
    a, b, why, d = w
    sc = involvement(g, a, b)
    ours = [c for c, _ in sc.most_common() if g.team_of[c] == g.us][:2]
    theirs = [c for c, _ in sc.most_common() if g.team_of[c] != g.us][:2]
    gold = {r[0]: (r[5 + g.us], r[5 + 1 - g.us]) for r in g.rounds}  # earned gold (captures + kills), us / them
    ga = gold.get(max([r for r in gold if r <= a] or [min(gold)]), (0, 0)) if gold else (0, 0)
    gb = gold.get(max([r for r in gold if r <= b] or [min(gold)]), (0, 0)) if gold else (0, 0)
    L = [f"CRITICAL GAME {spec}, window {n}: rounds {a}-{b} ({why}; our net position {d:+d} gems over the window)",
         f"earned gold us / them: r{a} {ga[0]} / {ga[1]}, r{b} {gb[0]} / {gb[1]} (this window: us +{gb[0] - ga[0]}, them +{gb[1] - ga[1]})",
         f"flagged because: {why_flag}",
         f"us = team {'AB'[g.us]} ({g.team_name(g.us)}); labels: team A 1-6, team B K L N P R S. "
         "Net = (our tributed + carried gems) - (theirs).",
         "", "NET POSITION (every 2 rounds): " + " ".join(f"r{r}:{N[r]:+d}" for r in sorted(N) if a <= r <= b and (r - a) % 2 == 0),
         "", "MOMENTS IN THE WINDOW:"]
    L += [f"  r{r} {k}: {s}" for r, k, s in mom if a <= r <= b] or ["  (none: a slow drift; look at farming, routes and captures)"]
    L += ["", "HITS ON CHAMPIONS (victim's vision at the hit: SEEN = victim saw the attacker, TEAM = only a mate did, FOG = nobody):"]
    L += rvision_hits(spec, g.us, a, b) or ["  (none)"]
    L += ["", "TURN ORDER (labels of the bodies acting, in order; dead bodies don't act):"] + turn_order(g, a, b)
    L += ["", f"FOES NEAR OUR TRACKED BODIES at each turn start (within 6; channel = what the foe was doing and its timer; "
              f"seen = in that body's own vision):"] + near_foes(g, spec, gd, ours, a, b)
    for c in ours + theirs:
        L += ["", f"TRACK {g.who(c)} ({'us' if g.team_of[c] == g.us else 'them'}), involvement {sc[c]}:"]
        L += capture(R.cmd_track, g, c, a, b).rstrip().split("\n")
    if ours:
        # the key round: our first death in the window, else the round of its biggest one-round net change, else its end
        dead = [r for r, k, t in mom if a <= r <= b and k == "death" and t.startswith("OUR")]
        steps = [(N[r] - N[q], r) for q, r in zip(sorted(N), sorted(N)[1:]) if a < r <= b]
        key = dead[0] if dead else (min(steps)[1] if steps and min(steps)[0] < 0 else b)
        L += ["", f"MAP AT ROUND {key} (the key round) with the trail of {g.who(ours[0])} since round {a}:"]
        L += capture(R.cmd_show, g, key, None, None, (ours[0], max(1, key - a))).rstrip().split("\n")
    L += ["", "TO ANSWER (write window_%d.verdict, one line each):" % n,
          "  WHAT: what happened, in order, with rounds and labels",
          "  WHY: the decision that caused it: the bot rule at file:line (tools/lab/card.py FUNCTION), or 'unknown: <what would tell>'",
          "  BETTER: the better play and what it was worth (gems / gold / a death), and whether the bot had the information (vision)",
          "  CHECK: how you verified it (re-walk of N turns, rvision, puppet.py, a local repro, a count over other games)",
          "  CONF: high / medium / low"]
    return "\n".join(L) + "\n"


def parse(path):
    d = {}
    try:
        for ln in open(path, errors="replace"):
            m = re.match(r"^\s*([A-Z][A-Z_]*)\s*:\s*(.*)$", ln)  # 13 Nov: underscores (VERDICT_SHA)
            if m:
                d[m.group(1)] = (d.get(m.group(1), "") + " " + m.group(2)).strip()
    except OSError:
        return None
    return d


def verdict_problems(v):
    if v is None:
        return ["no verdict"]
    p = [f"{f} missing" for f in FIELDS if not v.get(f)]
    w = v.get("WHY", "")
    if w and not (re.search(r"\w+\.(cpp|cc|h|hpp):\d+", w) or w.lower().startswith("unknown:")):  # 9 Nov: .cc (the current layout) too
        p.append("WHY needs a file:line or 'unknown: <what would tell>'")
    if v.get("CONF") and v["CONF"].split()[0].lower() not in ("high", "medium", "low"):
        p.append("CONF must be high / medium / low")
    return p


def verdict_sha(v):
    """13 Nov (Econ, Deep): a grill is tied to the verdict's CONTENT (every field but notes), not to file mtimes, so appending a note does not
    void it and a rewrite does."""
    import hashlib
    core = {k: str(x).strip() for k, x in (v or {}).items() if not k.upper().startswith("NOTE")}
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:12]


def window_state(d, n):
    vp = f"{d}/window_{n}.verdict"
    gp = f"{d}/window_{n}.grill"
    v = parse(vp)
    probs = verdict_problems(v)
    if probs:
        return "OPEN", "; ".join(probs)
    if os.path.exists(f"{d}/LIGHT"):
        return "DONE", "light: verdict only (no grill)"
    gr = parse(gp)
    stale = gr is not None and (gr["VERDICT_SHA"].split()[0] != verdict_sha(v) if gr.get("VERDICT_SHA") else os.path.getmtime(gp) < os.path.getmtime(vp))
    if gr is None or stale:
        return "OPEN", "verdict ok; needs a grill" + (" (verdict rewritten after the last grill)" if gr is not None else "")
    ag = gr.get("AGREE", "").lower()
    if ag.startswith("yes"):
        return "DONE", f"grilled by {gr.get('BY', '?')}"
    if ag.startswith("no"):
        return "DISPUTED", f"grill ({gr.get('BY', '?')}): {gr.get('WHY', '')[:120]}"
    return "OPEN", "grill has no AGREE: yes|no"


def turn_hash(g):
    """a fingerprint of the game, turn for turn (replay.py diff's comparison: map, then every turn's body, tile, HP, alive)"""
    import hashlib
    h = hashlib.sha1(repr((g.W, g.H, g.rows)).encode())
    for t in sorted((t[0], t[1], t[2], t[3], t[4], t[g.ci["alive"]]) for t in g.turns):
        h.update(repr(t).encode())
    return h.hexdigest()[:20]


def find_twin(h, g, us, d_new):
    """an earlier flagged game identical turn for turn (Econ 6 Nov: play-identical ships re-flag the same game): -> (dir, meta)
    or None. Metas without a stored hash are hashed once (games with the same round count only) and the hash is saved."""
    try:
        rows = [json.loads(x) for x in open(INDEX)]
    except OSError:
        return None
    seen = set()
    for r in reversed(rows):
        d = r.get("dir")
        if not d or d == d_new or d in seen or not os.path.exists(f"{d}/meta.json"):
            continue
        seen.add(d)
        try:
            meta = json.load(open(f"{d}/meta.json"))
        except (OSError, ValueError):
            continue
        if meta.get("us") != us or meta.get("rounds") != g.last_round:
            continue
        if "turn_hash" not in meta:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    meta["turn_hash"] = turn_hash(R.load(meta["spec"], meta["us"]))
                json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
            except (Exception, SystemExit):  # noqa: BLE001  an unreadable old replay is just not a twin
                continue
        if meta.get("turn_hash") == h:
            return d, meta
    return None


def link_identical(d, spec, us, rounds, th, first_spec, first_dir, why="", version=None, by="?", prio="normal"):
    """mark game dir D as a turn-for-turn copy of FIRST: meta with identical_to and no windows, an IDENTICAL file, an index row"""
    meta = {}
    try:
        meta = json.load(open(f"{d}/meta.json"))
    except (OSError, ValueError):
        pass
    meta.update(spec=spec, us=us, rounds=rounds, turn_hash=th, identical_to=first_spec, identical_dir=first_dir)
    meta.setdefault("why", why)
    meta.setdefault("version", version)
    meta.setdefault("by", by)
    meta.setdefault("prio", prio)
    meta.setdefault("t", time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()))
    meta.setdefault("windows", [])
    json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
    open(f"{d}/IDENTICAL", "w").write(f"{spec} is identical turn for turn to {first_spec} (turn hash {th}): read {first_dir}\n")
    with open(INDEX, "a") as f:
        f.write(json.dumps(dict(spec=spec, dir=d, t=meta["t"], t_s=time.time(), by=meta["by"], why=meta["why"], prio=meta["prio"],
                                version=meta["version"], identical_to=first_spec)) + "\n")


def is_identical(d, m):
    return bool(m.get("identical_to")) or os.path.exists(f"{d}/IDENTICAL")


def load_meta(spec):
    d = gdir(game_spec(spec))
    try:
        return d, json.load(open(f"{d}/meta.json"))
    except (OSError, ValueError):
        sys.exit(f"critgame: {spec} is not flagged (critgame.py flag GAME --why ...)")


def cmd_flag(a):
    spec = game_spec(a[0])
    opt = lambda k, dft=None: a[a.index(k) + 1] if k in a else dft  # noqa: E731
    why = opt("--why")
    if not why:
        sys.exit("critgame flag: --why \"what makes this game critical\" is required")
    k = int(opt("--k", 4))
    asked = []
    for part in (opt("--rounds") or "").split(","):
        if part.strip():
            if "-" in part:
                x, y = part.split("-")
                asked.append((int(x), int(y)))
            else:
                asked.append((max(1, int(part) - 10), int(part) + 8))
    try:
        g = R.load(spec, opt("--us"))
    except SystemExit:
        # a full match id not yet in a fetched live set (Combat 5 Nov): download it into AUTO_SET/x_ID and load that file
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", spec):
            raise
        x = f"{AUTO_SET}/x_{spec}"
        os.makedirs(x, exist_ok=True)
        if not os.path.exists(f"{x}/replay.repl26a"):
            plat(["matches", "download", spec, "-o", f"{x}/r.zip"], timeout=600)
            import zipfile
            with zipfile.ZipFile(f"{x}/r.zip") as z:
                for nm in z.namelist():
                    if "/" not in nm and ".." not in nm and nm:
                        open(f"{x}/{nm}", "wb").write(z.read(nm))
            os.remove(f"{x}/r.zip")
        print(f"  {spec}: not in a fetched set; downloaded to {x}")
        g = R.load(f"{x}/replay.repl26a", opt("--us"))
    light = "--light" in a
    wins, N, mom = cut(g, 0 if light and asked else k, asked, rise=not light)
    d = gdir(spec)
    os.makedirs(d, exist_ok=True)
    th = turn_hash(g)
    tw0 = None if "--windows" in a else find_twin(th, g, "AB"[g.us], d)
    while tw0 and tw0[1].get("identical_to") and os.path.exists(f"{tw0[1].get('identical_dir', '')}/meta.json"):  # link to the first game, not a copy
        tw0 = (tw0[1]["identical_dir"], json.load(open(f"{tw0[1]['identical_dir']}/meta.json")))
    if tw0:  # 8 Nov (Econ via the Builder: one deterministic rematch flagged 3 times, 3 critical slots, 15 window walks): a game identical turn
        # for turn to an earlier flag opens no windows; it links to that game and stays out of the open list and the cap (--windows forces them)
        td, tm = tw0
        link_identical(d, spec, "AB"[g.us], g.last_round, th, tm["spec"], td, why=opt("--why", ""), version=opt("--version", None) or played_version(spec) or live_version()[0],
                       by=opt("--by", os.environ.get("USER", "?")), prio=opt("--prio", "normal"))
        print(f"flagged {spec}: IDENTICAL turn for turn to {tm['spec']} (turn hash {th}); no windows opened, read that game's ({td})")
        return
    for n, w in enumerate(wins, 1):
        open(f"{d}/window_{n}.txt", "w").write(dossier(g, spec, n, w, N, mom, why, d))
    meta = dict(spec=spec, us="AB"[g.us], why=why, version=opt("--version", None) or played_version(spec) or live_version()[0], live_at_flag=live_version()[0], prio=opt("--prio", "normal"), by=opt("--by", os.environ.get("USER", "?")), t=time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
                rounds=g.last_round, windows=[dict(n=n, a=w[0], b=w[1], kind=w[2], net=w[3]) for n, w in enumerate(wins, 1)])
    meta["turn_hash"] = turn_hash(g)
    if opt("--bot", None):  # 9 Nov (Deep): the bot that PLAYED this game; puppet.py --bot BOT re-plays it exactly (live may be a later version)
        meta["bot"] = opt("--bot", None)
    json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
    if light:
        open(f"{d}/LIGHT", "w").write("one window, one walker, no grill\n")
    tw = find_twin(meta["turn_hash"], g, meta["us"], d)
    carried = []
    if tw:  # the same game turn for turn: carry every finished window with the same rounds (verdict, then grill, mtimes kept)
        import shutil
        td, tm = tw
        for w in meta["windows"]:
            tws = next((x for x in tm.get("windows", []) if (x["a"], x["b"]) == (w["a"], w["b"])), None)
            if not tws or window_state(td, tws["n"])[0] != "DONE":
                continue
            for ext in ("verdict", "grill"):
                src = f"{td}/window_{tws['n']}.{ext}"
                if os.path.exists(src):
                    shutil.copy2(src, f"{d}/window_{w['n']}.{ext}")
            carried.append(w["n"])
        if carried:
            open(f"{d}/CARRIED", "w").write(f"windows {carried} carried from {tm['spec']} ({td}): identical turn for turn "
                                            f"(turn hash {meta['turn_hash']}); re-walk only the others\n")
    with open(INDEX, "a") as f:
        f.write(json.dumps(dict(spec=spec, dir=d, t=meta["t"], t_s=time.time(), by=meta["by"], why=why, prio=meta["prio"], version=meta["version"])) + "\n")
    print(f"flagged {spec} (us {meta['us']}, {g.last_round} rounds): {len(wins)} windows in {d}"
          + (f"; windows {carried} CARRIED from {tw[1]['spec']} (identical turn for turn)" if carried else ""))
    for w in meta["windows"]:
        sz = os.path.getsize(f"{d}/window_{w['n']}.txt")
        print(f"  window {w['n']}: rounds {w['a']}-{w['b']} {w['kind']:5s} net {w['net']:+d}  ({sz // 1024} KB dossier)")
    print(f"next: one walker per window, in parallel: python3 -I tools/lab/critgame.py brief {spec} N  (then --grill with a second walker)")


def regen(d, meta):
    """re-create missing window_N.txt dossiers (and the replay) from meta.json's windows; the cut is not redone"""
    miss = [w for w in meta["windows"] if not os.path.exists(f"{d}/window_{w['n']}.txt")]
    if not miss:
        return 0
    spec = meta["spec"]
    if re.fullmatch(r"[0-9a-f-]{36}", spec) and not R._live_lookup(spec):
        fetch_replay(spec, meta["us"].lower(), {"map": "?"}, {"name": "?"})
    g = R.load(spec, meta["us"])
    N, mom = net_series(g), moments(g)
    for w in miss:
        open(f"{d}/window_{w['n']}.txt", "w").write(dossier(g, spec, w["n"], (w["a"], w["b"], w["kind"], w["net"]), N, mom, meta["why"], d))
    return len(miss)


def cmd_addwin(a):
    """critgame.py addwin ID R0-R1 [--kind early]: one more window on a flagged game; existing windows and verdicts stay"""
    d, meta = load_meta(a[0])
    x, y = (int(v) for v in a[1].split("-"))
    kind = a[a.index("--kind") + 1] if "--kind" in a else "asked"
    regen(d, meta)
    g = R.load(meta["spec"], meta["us"])
    N, mom = net_series(g), moments(g)
    rs = sorted(N)
    net = N.get(max([r for r in rs if r <= y] or rs[:1]), 0) - N.get(max([r for r in rs if r <= x] or rs[:1]), 0)
    n = max(w["n"] for w in meta["windows"]) + 1
    w = dict(n=n, a=x, b=y, kind=kind, net=net)
    open(f"{d}/window_{n}.txt", "w").write(dossier(g, meta["spec"], n, (x, y, kind, net), N, mom, meta["why"], d))
    meta["windows"].append(w)
    json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
    print(f"{meta['spec']}: window {n} r{x}-{y} ({kind}, net {net:+d}) added; brief it with `critgame.py brief {meta['spec']} {n}`")


def cmd_regen(a):
    d, meta = load_meta(a[0])
    print(f"{meta['spec']}: {regen(d, meta)} window file(s) re-created in {d}")


def cmd_brief(a):
    d, meta = load_meta(a[0])
    if regen(d, meta):
        pass  # a pruned dossier is rebuilt before the walker needs it
    n = int(a[1])
    w = next((x for x in meta["windows"] if x["n"] == n), None)
    if not w:
        sys.exit(f"critgame: no window {n} (1-{len(meta['windows'])})")
    grill = "--grill" in a
    who = a[a.index("--who") + 1] if "--who" in a else None
    if meta.get("owner") and who != meta["owner"]:
        print(f"!! {meta['spec']} is claimed by {meta['owner']} ({meta.get('owner_t', '?')})"
              + (f", not {who}" if who else "; pass --who WHO") + ": don't work on it unless they handed it to you.", file=sys.stderr)
    if "--compare" in a:  # grill step 2 (Combat 6 Nov: a grill that read the verdict with the brief could not walk blind)
        # 8 Nov (Econ): re-grills walk in blind_Nb/, blind_Nc/ ...: compare the NEWEST blind_N* walk (not blind_10 for N=1), or --blind DIR
        cands = [os.path.join(d, x, "walk.txt") for x in os.listdir(d) if re.fullmatch(rf"blind_{n}[a-z]*", x)]
        cands = [x for x in cands if os.path.exists(x) and open(x).read().strip()]
        walk = (os.path.join(a[a.index("--blind") + 1], "walk.txt") if "--blind" in a
                else max(cands, key=os.path.getmtime) if cands else f"{d}/blind_{n}/walk.txt")
        if not os.path.exists(walk) or not open(walk).read().strip():
            sys.exit(f"critgame: no blind walk yet: do step 1 first (`critgame.py brief {meta['spec']} {n} --grill`) and write {walk}")
        gp_ = f"{d}/window_{n}.grill"
        if os.path.exists(gp_):  # 13 Nov (Deep): an earlier grill is archived here, so step 2 writes a fresh one
            k_ = 1
            while os.path.exists(f"{gp_}.v{k_}"):
                k_ += 1
            os.rename(gp_, f"{gp_}.v{k_}")
            print(f"(earlier grill archived as {gp_}.v{k_})", file=sys.stderr)
        vsha_ = verdict_sha(parse(f"{d}/window_{n}.verdict"))
        print(f"GRILL step 2 for {meta['spec']} window {n}. Your blind walk is in {walk}; do not change it now. Read the verdict "
              f"{d}/window_{n}.verdict and compare it with your walk. Try to break the verdict: wrong side or label, a spin recall read "
              "as a recall, a cause that came earlier, information the bot did not have (vision), a one-off presented as a pattern. "
              f"Write {d}/window_{n}.grill with lines AGREE: yes|no / WHY: <what you checked; if no, what is wrong and what you found "
              f"instead> / BY: <your agent name or id> / BLIND: <your walk.txt WHAT and WHY, unchanged> / VERDICT_SHA: {vsha_} (copy exactly). "
              "Your final message: those lines.")
        return
    evid = f"{d}/window_{n}.txt"
    if grill:  # step 1 reads a copy in a dir of its own, so listing it shows no verdict
        bd = f"{d}/blind_{n}"
        # 13 Nov (Econ, Deep): a re-grill walks in a NEW blind dir (blind_Nb, blind_Nc ...), never over the first walk
        if os.path.exists(f"{bd}/walk.txt") and open(f"{bd}/walk.txt").read().strip():
            for c_ in "bcdefghijklmnopqrstuvwxyz":
                if not os.path.exists(f"{bd}{c_}/walk.txt"):
                    bd = f"{bd}{c_}"
                    break
        os.makedirs(bd, exist_ok=True)
        evid = f"{bd}/window_{n}.txt"
        open(evid, "w").write(open(f"{d}/window_{n}.txt").read())
    head = ("First read and follow /homes/USER/cambc/condor-work/reports/primer_core.md (the walker rules; 9 Nov: .claude/agents/nova-walk.md is gone). "
            + ("LIGHT game (one walk, no grill: keep it to ~20 calls). " if os.path.exists(f"{d}/LIGHT") else "")
            + 
            f"CRITICAL game {meta['spec']} (us = team {meta['us']}), window {n}: rounds {w['a']}-{w['b']}, our net {w['net']:+d} gems. "
            f"Flagged because: {meta['why']}. Always pass the FULL match id {meta['spec']} to replay.py / rvision.py (games of one match "
            f"group share their first 13 characters). Your evidence file is {evid}: read it first; then go deeper where it is not "
            "enough (replay.py track/show --trail on other rounds or bodies, rvision.py, card.py for the bot rule, a count over other "
            "games for how often this happens). Look at the turns BEFORE the window too: the cause is often 5-30 rounds earlier. ")
    if not grill:
        body = (f"Write {d}/window_{n}.verdict with exactly these lines: WHAT: ... / WHY: <bot file:line, or 'unknown: <what would "
                "tell>'> / BETTER: <the better play, its worth in gems/gold/deaths, and whether the bot could see it> / CHECK: <how you "
                "verified it> / CONF: high|medium|low. Then check it with `python3 -I tools/lab/critgame.py check "
                f"{meta['spec']}` and fix what it reports. Your final message: the verdict's five lines.")
    else:
        body = ("You are the GRILL, step 1 of 2 (BLIND). card.py and ask.py hide every doc and board line naming this game while "
                "your walk.txt is missing. Another walker has written a verdict on this window, and you must not see "
                f"it yet. Do NOT open, list or cat anything in {d} except {evid} (and do not run critgame.py check/status on this "
                "game); replay.py, rvision.py and card.py are fine. Walk the window yourself and write "
                f"{os.path.dirname(evid)}/walk.txt with exactly two lines: WHAT: ... / WHY: <bot file:line or 'unknown: ...'>. Then run "
                f"`python3 -I tools/lab/critgame.py brief {meta['spec']} {n} --compare`: it gives step 2 (the verdict and how to "
                "compare). Your final message: the .grill file's lines from step 2.")
    print(head + body)


def cmd_close(a):
    """critgame.py close GAME "why" [--who WHO]: the game needs no more work (another version played it, a duplicate, a dead lead).
    Its windows and verdicts stay; status and the open cap skip it (8 Nov, Combat: foreign games could only be closed by editing meta.json)."""
    if "--batch" in a or "--file" in a:
        return close_batch(a)
    who = a[a.index("--who") + 1] if "--who" in a else None
    a = [x for i, x in enumerate(a) if x != "--who" and (i == 0 or a[i - 1] != "--who")]
    if len(a) < 2:
        sys.exit('usage: critgame.py close GAME "why" [--who WHO]')
    d = gdir(game_spec(a[0]))
    mp = f"{d}/meta.json"
    if not os.path.exists(mp):
        sys.exit(f"critgame: no flagged game {a[0]} ({d})")
    m = json.load(open(mp))
    m.update(closed=a[1], closed_by=who or "?", closed_t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    json.dump(m, open(mp + f".{os.getpid()}", "w"), indent=1)
    os.replace(mp + f".{os.getpid()}", mp)
    print(f"closed {m['spec']}: {a[1]}")


def close_batch(a):
    """close --batch ID... "why" [--file F] [--who WHO] [--dry] (10 Nov, Combat: one process instead of one per id). Same effect per
    id as `close ID "why" [--who WHO]`; an id that fails (not flagged, ambiguous prefix) prints FAIL and the rest go on.
    --dry prints what would be closed and writes nothing. Exit 1 if any id failed."""
    who = fl = None
    dry = False
    rest = []
    i = 0
    while i < len(a):
        x = a[i]
        if x in ("--who", "--file") and i + 1 < len(a):
            if x == "--who":
                who = a[i + 1]
            else:
                fl = a[i + 1]
            i += 2
            continue
        if x == "--dry":
            dry = True
        elif x != "--batch":
            rest.append(x)
        i += 1
    if not rest:
        sys.exit('usage: critgame.py close --batch ID... "why" [--file F] [--who WHO] [--dry]')
    why, ids = rest[-1], rest[:-1]
    if fl:
        try:
            ids += [ln.split()[0] for ln in open(fl) if ln.strip() and not ln.lstrip().startswith("#")]
        except OSError as e:
            sys.exit(f"critgame: --file {fl}: {e}")
    if not ids:
        sys.exit('critgame: close --batch: no ids (the last argument is the why: close --batch ID... "why")')
    seen, nok, nfail = set(), 0, 0
    for spec in ids:
        try:
            d = gdir(game_spec(spec))
        except SystemExit as e:
            print(f"FAIL {spec}: {e}")
            nfail += 1
            continue
        if d in seen:
            print(f"skip {spec}: repeated")
            continue
        seen.add(d)
        mp = f"{d}/meta.json"
        try:
            m = json.load(open(mp))
        except (OSError, ValueError) as e:
            print(f"FAIL {spec}: no flagged game ({d}{'' if isinstance(e, FileNotFoundError) else ': ' + str(e)[:80]})")
            nfail += 1
            continue
        if dry:
            print(f"DRY would close {m.get('spec', spec)}: {why}" + (f" (already closed: {m['closed']})" if m.get("closed") else ""))
            nok += 1
            continue
        m.update(closed=why, closed_by=who or "?", closed_t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        json.dump(m, open(mp + f".{os.getpid()}", "w"), indent=1)
        os.replace(mp + f".{os.getpid()}", mp)
        print(f"closed {m['spec']}: {why}")
        nok += 1
    print(f"close --batch: {nok} {'would close' if dry else 'closed'}, {nfail} failed")
    if nfail:
        sys.exit(1)


def cmd_claim(a):
    """one owner per game (Econ 6 Nov: Econ and Combat both took 01a1af8a two minutes apart; a walker rewrote the other's verdict)"""
    if len(a) < 2:
        sys.exit("usage: critgame.py claim GAME WHO [--force]")
    d, meta = load_meta(a[0])
    who = a[1]
    # 11 Nov (Coordinator: an owner column showed a session/match id): WHO is an analyser's name (deep, econ, combat, b1844 ...), never an id
    if re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){1,4}(-[0-9a-f]+)?", who.lower()) or re.fullmatch(r"[0-9a-f-]{12,}", who.lower()) or len(who) > 40:
        sys.exit(f"critgame: {who!r} looks like an id, not an analyser's name: claim GAME WHO (e.g. deep, econ, combat, b1844)")
    import fcntl
    with open(f"{d}/.claim.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        meta = json.load(open(f"{d}/meta.json"))
        cur = meta.get("owner")
        if cur and cur != who and "--force" not in a:
            sys.exit(f"critgame: {meta['spec']} is already claimed by {cur} at {meta.get('owner_t', '?')}; pick another game "
                     "(--force only if they handed it to you)")
        meta["owner"], meta["owner_t"] = who, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        json.dump(meta, open(f"{d}/meta.json.new", "w"), indent=1)
        os.replace(f"{d}/meta.json.new", f"{d}/meta.json")
    print(f"{meta['spec']}: claimed by {who}")


def cmd_link(a):
    """link COPY FIRST: mark an already-flagged COPY as identical to FIRST (checks the turn hashes match unless --force)"""
    if len(a) < 2:
        sys.exit("usage: critgame.py link COPY FIRST [--force]")
    dc, mc = load_meta(a[0])
    df, mf = load_meta(a[1])
    while mf.get("identical_to") and os.path.exists(f"{mf.get('identical_dir', '')}/meta.json"):  # the first game, not a copy
        df, mf = mf["identical_dir"], json.load(open(f"{mf['identical_dir']}/meta.json"))
    if mc.get("turn_hash") != mf.get("turn_hash") and "--force" not in a:
        sys.exit(f"turn hashes differ ({mc.get('turn_hash')} v {mf.get('turn_hash')}): not identical (--force to link anyway)")
    link_identical(dc, mc["spec"], mc["us"], mc.get("rounds"), mc.get("turn_hash"), mf["spec"], df)
    print(f"linked {mc['spec']} -> {mf['spec']}: IDENTICAL, out of the open list (its own files are kept)")


def cmd_status(a):
    try:
        rows = [json.loads(x) for x in open(INDEX)]
    except OSError:
        rows = []
    show_all = "--all" in a
    a = [x for x in a if x != "--all"]
    live = live_version()[0]
    if a:
        rows = [r for r in rows if r["dir"] == gdir(game_spec(a[0]))]
        show_all = True
    else:
        og = open_games()
        print(f"{len(og)} unfinished games (live {live}; last {OPEN_HOURS} h, any version; critical cap {OPEN_CAP}), most urgent first: take from the top")
        for rk, _, m, d, st in og:
            lab = "DISPUTED" if "DISPUTED" in st else "OPEN"
            print(f"{lab:8s} {m['spec']} {m.get('version', '?')} {('[' + m['owner'] + '] ') if m.get('owner') else ''}{m.get('prio', 'normal').upper():6s} {sum(x == 'DONE' for x in st)}/{len(st)} windows done: {m['why'][:120]}")
        try:
            import replaycheck
            print("\n".join(replaycheck.waiting()))
        except (Exception, SystemExit) as e:  # noqa: BLE001  the queue must print whatever the flaw list does
            print(f"replaycheck list unreadable: {str(e)[:120]}")
        if not show_all:
            return
    seen, stale = set(), 0
    for r in reversed(rows):
        if r["dir"] in seen or not os.path.exists(f"{r['dir']}/meta.json"):
            continue
        seen.add(r["dir"])
        meta = json.load(open(f"{r['dir']}/meta.json"))
        if not show_all and meta.get("version") not in (live, None):
            stale += 1
            continue
        if is_identical(r["dir"], meta):
            print(f"IDENTICAL {meta['spec']} -> {meta.get('identical_to', '?')} (turn for turn; read that game)")
            continue
        st = [(w, *window_state(r["dir"], w["n"])) for w in meta["windows"]]
        overall = "DISPUTED" if any(s == "DISPUTED" for _, s, _ in st) else "DONE" if all(s == "DONE" for _, s, _ in st) else "OPEN"
        print(f"{overall:8s} {meta['spec']} {meta.get('version', '?')} {meta.get('prio', 'normal').upper() if meta.get('prio') in ('high', 'low', 'light') else ''}"
              f" flagged {meta['t']} by {meta['by']}: {meta['why'][:140]}")
        for w, s, why in st:
            print(f"    window {w['n']} r{w['a']}-{w['b']} net {w['net']:+d}: {s} ({why})")
    if stale:
        print(f"({stale} flagged games of older versions hidden; --all shows them)")
    if not seen:
        print("no critical games flagged")


def cmd_check(a):
    d, meta = load_meta(a[0])
    bad = 0
    for w in meta["windows"]:
        s, why = window_state(d, w["n"])
        print(f"window {w['n']}: {s}: {why}")
        bad += s != "DONE"
    sys.exit(1 if bad else 0)


LIVE = "/data/USER/st/bq/live.txt"
PLATLOCK = "/homes/USER/cambc/tools/lab/platlock.sh"
CLI = "/data/USER/cambc400/bin/cambc400"
AUTO_SET = "/data/USER/plat/crit_auto"
OUR = "BattleCats"



def played_version(spec):
    """11 Nov (Planner/Coordinator: 01a1ca2f was played by v746 but flagged at v752 live): the version that PLAYED a match, from the
    climb lanes' games.tsv (version first, match id fourth), then gameindex.tsv's version column; None when unknown."""
    import glob as _g
    for p in sorted(_g.glob("/data/USER/st/climb*/games.tsv")):
        try:
            for ln in open(p, errors="replace"):
                c = ln.rstrip("\n").split("\t")
                if len(c) > 3 and c[3] == spec and c[0].startswith("v"):
                    return c[0]
        except OSError:
            continue
    try:
        for ln in open("/data/USER/st/gameindex.tsv", errors="replace"):
            if ln.startswith(spec + "\t"):
                v = ln.split("\t")[3]
                return v if v.startswith("v") else None
    except (OSError, IndexError):
        pass
    return None

def live_version():
    if os.environ.get("CRIT_LIVE"):  # test: "vNNN BOT SINCE"
        return tuple(os.environ["CRIT_LIVE"].split()[:3])
    try:
        p = open(LIVE).readline().split()
        return p[0], p[1], p[2]
    except (OSError, IndexError):
        return "?", "?", "1970-01-01T00:00:00Z"


def plat(args, timeout=180):
    r = subprocess.run(["sh", PLATLOCK, CLI] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"platform {' '.join(args[:2])}: rc {r.returncode} {r.stderr.strip()[:200]}")
    return r.stdout


class Ladder:
    """team name/id -> rating from the current ladder, fetched a page at a time and only as far as needed"""

    def __init__(self):
        self.by, self.page, self.total = {}, 0, None

    def more(self):
        if self.total is not None and self.page * 100 >= self.total:
            return False
        self.page += 1
        d = json.loads(plat(["ladder", "--limit", "100", "--page", str(self.page), "--json"]))
        self.total = d.get("total", 0)
        for t in d.get("teams", []):
            self.by[t["teamId"]] = self.by[t["name"].lower()] = t
        return bool(d.get("teams"))

    def get(self, key):
        k = key if key in self.by else key.lower()
        while k not in self.by and self.more():
            pass
        return self.by.get(k)


TRIAGE = f"{ROOT}/triage.jsonl"


def match_result(mid, m):
    """our result for matches.txt: from m if it has teams, else the platform; '?' rather than a guess (7 Nov: every row said 'loss')"""
    try:
        teams = m.get("teams") or json.loads(plat(["matches", "show", mid, "--json"]))["matches"][0]["teams"]
        return next(t["result"] for t in teams if t["name"] == OUR and t.get("result") in ("win", "loss"))
    except (RuntimeError, OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError):
        return "?"


def fetch_replay(mid, side, m, foe):
    """the replay into AUTO_SET/x_ID (where replay.load finds it) and a matches.txt line; returns the dir"""
    x = f"{AUTO_SET}/x_{mid}"
    os.makedirs(x, exist_ok=True)
    if not os.path.exists(f"{x}/replay.repl26a"):
        plat(["matches", "download", mid, "-o", f"{x}/r.zip"], timeout=600)
        import zipfile
        with zipfile.ZipFile(f"{x}/r.zip") as z:
            for nm in z.namelist():
                if "/" not in nm and ".." not in nm and nm:
                    open(f"{x}/{nm}", "wb").write(z.read(nm))
        os.remove(f"{x}/r.zip")
    if not os.path.exists(f"{x}/replay.repl26a"):
        raise RuntimeError("no replay.repl26a in the download")
    mt = f"{AUTO_SET}/matches.txt"
    if not os.path.exists(mt) or mid not in open(mt).read():
        with open(mt, "a") as fh:
            fh.write(f"{mid} {m['map']} {side} {match_result(mid, m)} {foe['name'].replace(' ', '_')}\n")
    return x


def drop_replay(mid):
    x = f"{AUTO_SET}/x_{mid}"
    if os.path.isdir(x):
        for q in os.listdir(x):
            os.remove(os.path.join(x, q))
        os.rmdir(x)


def triage_metrics(g):
    """cheap, token-free severity of a loss from its replay (owner 5 Nov: prioritise by how bad a mistake we made or the difference)"""
    us = g.us
    N = net_series(g)
    rs = sorted(N)
    vals = [N[r] for r in rs]
    last = g.rounds[-1]
    paid = [0, 0]  # the last round row is written before the game-ending tribute lands (Combat 7 Nov: 00lanes 983 v 1006 real), so the events decide
    for e in g.events:
        if e[1] == "tribute":
            paid[e[3]] += e[4]
    tot = [max(last[1], paid[0]), max(last[2], paid[1])]
    margin = tot[1 - us] - tot[us]  # their tributed - ours at the end
    lead = max(vals + [0])
    worst, wr, j = 0, rs[0] if rs else 0, 0
    for i, r in enumerate(rs):  # the biggest fall from the best point of the previous 25 rounds
        while rs[j] < r - 25:
            j += 1
        dd = vals[i] - max(vals[j:i + 1])
        if dd < worst:
            worst, wr = dd, r
    faults = sum(1 for t in g.turns if g.team_of.get(t[1]) == us and t[g.ci["end"]] in (1, 2))
    errors = sum(1 for t in g.turns if g.team_of.get(t[1]) == us and t[g.ci["end"]] == 2)  # 11 Nov: replay end 2 = bot error (trap)
    fuelcuts = faults - errors  # end 1 = fuel exhausted (a cut-off, not a bot fault)
    deaths = [e for e in g.events if e[1] == "death" and g.team_of.get(e[2]) == us]
    inw = [e for e in deaths if wr - 25 <= e[0] <= wr]
    # a cut-off costs one body one turn: 50 each, and none after the worst stretch (Combat 7 Nov: late cut-offs inflated the rank); a crash is the full 300
    ends = [(t[0], t[g.ci["end"]]) for t in g.turns if g.team_of.get(t[1]) == us and t[g.ci["end"]] in (1, 2)]
    hit = 300 if any(e == 2 for _, e in ends) else min(300, 50 * sum(1 for r, _ in ends if r <= wr))
    bag = max([e[5] for e in inw] + [0])
    # the biggest single capture: summed, ordinary farming reads as this kind too (7 Nov: half of all losses)
    took = max([sum(x[2] for x in e[4]) for e in g.events if e[1] == "capture" and e[3] == 1 - us and wr - 25 <= e[0] <= wr] + [0])
    if hit >= 100:  # a crash, or two cut-offs before the fall; one stray cut-off does not explain it
        kind = "fault"
    elif took and took >= max(bag, -worst / 2):  # one foe capture is most of the fall (Combat 7 Nov: 00rows' 486-gem monolith read as drift)
        kind = "foe capture"
    elif any(e[3] == 2 for e in inw):
        kind = "camp death"
    elif bag >= 30:
        kind = "bag death"
    elif inw:
        kind = "fight death"
    else:
        kind = "drift"  # no death or big foe capture in the worst stretch: race, farming
    flip = -worst >= max(1, abs(margin))  # that one stretch cost more than the final margin (a win: it nearly threw the game)
    sev = -worst + 0.5 * lead + hit
    return dict(margin=margin, lead=lead, worst=worst, worst_r=wr, faults=faults, errors=errors, fuelcuts=fuelcuts, bag=bag, mkind=kind, flip=flip,
                sev=round(sev, 1))


def triage_rows(v=None):
    try:
        rows = [json.loads(x) for x in open(TRIAGE)]
    except OSError:
        return []
    return [r for r in rows if v is None or r.get("version") == v]


WIN_WEIGHT = 0.3  # owner 5 Nov: 'we also eventually want to see how we can improve our wins, but they are less priority'


def priority(r, rows):
    same = sum(1 for q in rows if q["mkind"] == r["mkind"] and q.get("result", "loss") == r.get("result", "loss")) if r["mkind"] != "drift" else 1
    p = r["sev"] * (1.5 if r["flip"] else 1.0) * min(1.5, 1 + 0.05 * (same - 1)) + max(0, r.get("gap", 0))
    return round(p * (WIN_WEIGHT if r.get("result") == "win" else 1.0), 1)


def which_version(mid, xdir, side, mp, deep=False, k=8):
    """9 Nov (Deep: 48 critical losses since v641 skipped as 'played by another version'): the (version, bot) among the last K live versions whose
    first draft turn (deep: and first champion turns) matches this game, via vercheck; retired bots come back from the idea store. None if none does."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import vercheck
    try:
        lines = [ln.split() for ln in open(LIVE) if ln.strip() and not ln.startswith("#")][:k]
    except OSError:
        return None
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for p in lines:
        if len(p) < 2:
            continue
        v, b = p[0], p[1]
        if not os.path.isdir(os.path.join(repo, "bots", b, "src")):
            subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ideastore.py"), "restore", b], capture_output=True)
            if not os.path.isdir(os.path.join(repo, "bots", b, "src")):
                continue
        try:
            if vercheck.check(mid, xdir, side, mp, b, deep=deep) == "ok":
                return v, b
        except Exception:  # noqa: BLE001  a build failure: try the next version
            continue
    return None



SUPERSEDE_N = int(os.environ.get("CRIT_SUPERSEDE_N", 50))


def supersede_old(dry=False):
    """11 Nov (Coordinator): every OPEN game played by a version more than SUPERSEDE_N (50) versions before live is closed as superseded
    (closed_by tb-superseded). Nothing else is touched, so the history stays and `close`/a hand edit can reopen a row; a fresh loss on live
    still opens its own row as before. -> number closed"""
    lv = re.search(r"\d+", live_version()[0])
    if not lv:
        return 0
    cut, n = int(lv.group()) - SUPERSEDE_N, 0
    for p in glob.glob(os.path.join(ROOT, "*", "meta.json")):
        try:
            m = json.load(open(p))
        except (OSError, ValueError):
            continue
        if m.get("closed") or m.get("verdict"):
            continue
        v = re.search(r"\d+", str(m.get("version", "")))
        if not v or int(v.group()) >= cut:
            continue
        n += 1
        if dry:
            continue
        m["closed"] = (f"superseded: played by {m.get('version')}, more than {SUPERSEDE_N} versions before live {live_version()[0]} "
                       f"({time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}; reopen by hand if still wanted)")
        m["closed_by"] = "tb-superseded"
        t = f"{p}.new.{os.getpid()}"
        json.dump(m, open(t, "w"), indent=1)
        os.replace(t, p)
    return n


def cmd_supersede(a):
    n = supersede_old(dry="--dry" in a)
    print(f"supersede: {n} open game(s) played more than {SUPERSEDE_N} versions before live {'would be ' if '--dry' in a else ''}closed")

def auto_pass(gap, dry, light_every=1800, per_pass=int(os.environ.get("CRIT_PER_PASS", "30"))):  # 9 Nov (owner: feed the analysts our losses): 12 a 15-min pass triaged ~48 of ~140 losses an hour
    v, bot, since = live_version()
    try:  # 11 Nov (Coordinator): rolling 50-version supersede of old open rows
        sup = supersede_old(dry)
        if sup:
            print(f"supersede: {sup} old open row(s) closed", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"supersede failed: {e}", flush=True)
    # 9 Nov 22:30Z (Coordinator: ships every ~20 min, so each pass's 'since the live ship' window left the previous versions' late losses to
    # the slow back-fill; untriaged 31 -> 120 in 30 min): the pass lists games from the start of the version CRIT_LOOKBACK (2) ships back;
    # games an older version played are triaged under that version (vercheck), losses first as before
    try:
        rows_ = [ln.split() for ln in open("/data/USER/st/bq/live.txt") if ln.strip() and not ln.startswith("#")]
        k = min(int(os.environ.get("CRIT_LOOKBACK", "2")), len(rows_) - 1)
        if k > 0 and len(rows_[k]) > 2 and rows_[k][2] < since:
            since = rows_[k][2]
    except (OSError, ValueError, IndexError):
        pass
    lad = Ladder()
    me = lad.get(OUR)
    if not me:
        print(f"{time.strftime('%H:%MZ', time.gmtime())} auto: {OUR} not on the ladder")
        return
    flagged = {r["spec"] for r in index_rows()}
    tri = {r["id"] for r in triage_rows()}
    games = []
    # 11 Nov ~22:3xZ owner: "do not use our unranked games for now" (bq/UNRANKED_OFF): ranked only while that file exists
    for kind in (("ranked",) if os.path.exists("/data/USER/st/bq/UNRANKED_OFF") else ("ranked", "unranked")):  # owner 5 Nov: unranked games as well
        cur = None
        for _ in range(10):
            d = json.loads(plat(["matches", "list", "--team", "me", "--kind", kind, "--limit", "100", "--json"] + (["--cursor", cur] if cur else [])))
            ms = d.get("matches", [])
            games += [dict(m, kind=m.get("kind", kind)) for m in ms if m.get("createdAt", "") >= since]
            cur = d.get("nextCursor")
            if not cur or not ms or min(m.get("createdAt", "") for m in ms) < since:
                break
    losses, wins = [], []
    for m in games:
        if m.get("status") != "finished":
            continue
        ours = [t for t in m["teams"] if t["name"] == OUR]
        foe = [t for t in m["teams"] if t["name"] != OUR]
        if not ours or not foe or ours[0].get("result") not in ("loss", "win"):
            continue
        ft = lad.get(foe[0]["teamId"]) or lad.get(foe[0]["name"])
        (losses if ours[0]["result"] == "loss" else wins).append((m, ours[0], foe[0], ft, me["rating"] - ft["rating"] if ft else 0.0))
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    # 1 triage: every loss, from the replay, no tokens
    nt = 0
    for res, (m, us_t, foe, ft, g_) in [("loss", o) for o in losses] + [("win", o) for o in wins]:  # losses first
        mid = m["matchId"]
        if mid in tri or nt >= per_pass or dry:
            continue
        nt += 1
        try:
            fetch_replay(mid, us_t["side"], m, foe)
            if not os.path.exists("/data/USER/st/bq/vercheck_OFF"):  # 8 Nov (b1570): an old submission may have played it (groups other teams open)
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import vercheck
                vplay = v
                if vercheck.check(mid, f"{AUTO_SET}/x_{mid}", us_t["side"], m["map"], live_version()[1], deep=False) == "foreign":
                    vb = which_version(mid, f"{AUTO_SET}/x_{mid}", us_t["side"], m["map"])
                    if not vb:
                        with open(TRIAGE, "a") as fh:  # no recent version matches: its own tag; the critical flag below still opens its windows
                            fh.write(json.dumps(dict(id=mid, version=f"{v}-foreign", result=res, kind=m["kind"], map=m["map"], foe=foe["name"], t=stamp)) + "\n")
                        print(f"  {mid}: played by another version (first draft turn differs from {live_version()[1]} and the last 8 live versions)")
                        if res == "win" or g_ < gap:
                            drop_replay(mid)
                        continue
                    vplay = vb[0]  # 9 Nov (Deep): triaged under the version that played it, not skipped
                    print(f"  {mid}: played by {vb[0]} ({vb[1]}), not {v}: triaged as {vb[0]}")
            g = R.load(mid, us_t["side"].upper())
            row = dict(id=mid, version=vplay, result=res, kind=m["kind"], map=m["map"], foe=foe["name"], foe_rating=round(ft["rating"]) if ft else None,
                       gap=round(g_), t=stamp, **triage_metrics(g))
            with open(TRIAGE, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            if (g_ < gap and m.get("kind") != "ranked") or res == "win":  # kept only if it is flagged below (9 Nov: every ranked loss is flagged, so kept)
                drop_replay(mid)
        except Exception as e:  # noqa: BLE001
            print(f"  triage {mid} failed: {e!r}"[:300])
    rows = triage_rows(v)
    foreign = {r_["id"] for r_ in triage_rows(None) if str(r_.get("version", "")).endswith("-foreign")}
    # 9 Nov 18:25Z (owner via Coordinator/Combat: every loss to the analysts; 16 ranked v651+ losses never reached them): EVERY ranked loss is
    # flagged, whatever the rating gap, ranked first; unranked losses still need the gap
    new = sorted((o for o in losses if (o[4] >= gap or o[0].get("kind") == "ranked") and o[0]["matchId"] not in flagged),
                 key=lambda o: (o[0].get("kind") != "ranked", -o[4]))  # 9 Nov: foreign critical losses flag too
    room = max(0, OPEN_CAP - sum(1 for o in open_games() if o[0] < 2))
    if len(new) > room:
        print(f"  {len(new) - room} critical losses left unflagged: {OPEN_CAP} open is the cap (they stay in the triage table)")
        new = new[:room]
    print(f"{stamp} auto {v}: {len(games)} ranked + unranked games since {since}, {len(losses)} losses {len(wins)} wins ({nt} triaged now, {len(rows)} in "
          f"the table), {len(new)} critical to flag (us {me['rating']:.0f} rank {me['rank']}, gap >= {gap:.0f})")
    todo = []
    for m, us_t, foe, ft, g_ in new:
        prio = "high" if g_ >= 100 or m.get("kind") == "ranked" else "normal"
        why = (f"auto: {m['kind']} loss under {v} ({bot}) on {m['map']} to {foe['name']} (rating {ft['rating']:.0f}, rank {ft['rank']}) "
               + (f"{g_:.0f} below us ({me['rating']:.0f}): a loss to a weaker team means a flaw; find it" if g_ >= gap else
                  f"({g_:+.0f} v us {me['rating']:.0f}): every ranked loss goes to the analysts (owner 9 Nov); find what decided it"))
        todo.append((m, us_t, foe, g_, prio, why, []))
    # 2 LIGHT: owner 5 Nov ('analyse games we lose in general, priority by how bad a mistake or the difference; deep dives cost too
    # much'): when nothing of the live version is open and no LIGHT one in light_every s, the top-priority triaged loss gets ONE
    # window (its worst stretch), one walker, no grill
    busy = open_live(v)
    last_light = max([r_.get("t_s", 0) for r_ in index_rows() if r_.get("prio") in ("light", "low")] or [0])
    cand = sorted((r for r in rows if r["id"] not in flagged and (r.get("gap", 0) < gap or r.get("result") == "win")), key=lambda r: -priority(r, rows))
    if not new and not busy and cand and time.time() - last_light >= light_every:
        r = cand[0]
        lo = next((o for o in losses + wins if o[0]["matchId"] == r["id"]), None)
        if lo:
            m, us_t, foe, ft, g_ = lo
            why = (f"auto LIGHT (priority {priority(r, rows)}, top of {len(cand)} unflagged games): {m['kind']} {r.get('result', 'loss')} under {v} on {m['map']} "
                   f"to {foe['name']} ({g_:+.0f} v us); worst stretch {r['worst']:+d} gems ending r{r['worst_r']} ({r['mkind']}), "
                   f"{'lost by ' + str(r['margin']) if r.get('result', 'loss') == 'loss' else 'won by ' + str(-r['margin'])}, best lead {r['lead']}"
                   f"{', that stretch alone cost more than the margin' if r['flip'] else ''}"
                   + ("; a WIN: find what we could have done better (lower priority than losses)" if r.get("result") == "win" else ""))
            todo.append((m, us_t, foe, g_, "light", why, ["--k", "1", "--rounds", f"{max(1, r['worst_r'] - 25)}-{r['worst_r']}", "--light"]))
    elif cand:
        print(f"  light queue: {len(cand)} triaged games; top {cand[0]['id']} priority {priority(cand[0], rows)} "
              f"({'critical first' if new else str(busy) + ' open game(s)' if busy else 'next LIGHT in ' + str(int(max(0, light_every - (time.time() - last_light)) / 60)) + ' min'})")
    for m, us_t, foe, g_, prio, why, extra in todo:
        mid = m["matchId"]
        print(f"  {prio.upper()} {mid} {m['kind']} {m['map']} v {foe['name']} gap {g_:.0f}")
        if dry:
            continue
        try:
            fetch_replay(mid, us_t["side"], m, foe)
            # 8 Nov (Combat: two v613 'HIGH' losses to Rogue Lock Pickers re-played non-exact at r4; vercheck: another version played
            # them): critical losses skip the triage above, so the version check runs here too
            if not os.path.exists("/data/USER/st/bq/vercheck_OFF"):
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import vercheck
                vflag, bplay = v, live_version()[1]
                if vercheck.check(mid, f"{AUTO_SET}/x_{mid}", us_t["side"], m["map"], live_version()[1]) == "foreign":
                    vb = which_version(mid, f"{AUTO_SET}/x_{mid}", us_t["side"], m["map"], deep=True)
                    vflag, bplay = vb if vb else (f"{v}-unknown", "")  # 9 Nov (Deep): flagged under the version that played it; unknown: windows anyway
                    why = why.replace(f"under {v} ({bot})", f"under {vflag}" + (f" ({bplay})" if bplay else " (version unknown: no exact re-play)"))
                    print(f"  {mid}: played by {vflag}{' (' + bplay + ')' if bplay else ''}, not {v}: flagged as such")
            r = subprocess.run(["nice", "-n", "10", "python3", "-I", os.path.abspath(__file__), "flag", mid, "--us", us_t["side"].upper(),
                                "--why", why, "--by", "auto", "--version", vflag, "--prio", prio] + (["--bot", bplay] if bplay else []) + extra,
                               capture_output=True, text=True, timeout=1800)
            print("    " + (r.stdout.strip().split("\n")[0] if r.returncode == 0 else f"flag failed: {r.stderr.strip()[-300:]}"))
        except Exception as e:  # noqa: BLE001  one bad game must not stop the rest
            print(f"    {mid} failed: {e!r}"[:300])


def cmd_refile(a):
    """9 Nov (Deep): back-fill. Triage rows tagged vNNN-foreign (skipped as 'played by another version') since --since (default v641): find the
    version that played each (which_version), then a critical loss (foe at least --gap, default 50, below us now) is flagged under that version with
    its bot; the rest get a normal triage row under that version. --dry lists only."""
    since = int((a[a.index("--since") + 1] if "--since" in a else "v641").lstrip("v"))
    gap = float(a[a.index("--gap") + 1]) if "--gap" in a else 50.0
    dry = "--dry" in a
    done = {r["spec"] for r in index_rows()} | {r["id"] for r in triage_rows(None) if not str(r.get("version", "")).endswith(("-foreign",))}
    todo, seen = [], set()
    for r in triage_rows(None):
        vv = str(r.get("version", ""))
        if not vv.endswith("-foreign") or r["id"] in done or r["id"] in seen:
            continue
        try:
            if int(vv.split("-")[0].lstrip("v")) < since:
                continue
        except ValueError:
            continue
        seen.add(r["id"])
        todo.append(r)
    lad = Ladder()
    me = lad.get(OUR)
    print(f"refile: {len(todo)} foreign-tagged games since v{since} not yet flagged or re-triaged")
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    nf = nt = nu = 0
    for r in todo:
        mid = r["id"]
        try:
            m = json.loads(plat(["matches", "show", mid, "--json"]))["matches"][0]
            us_t = next(t for t in m["teams"] if t["name"] == OUR)
            foe = next(t for t in m["teams"] if t["name"] != OUR)
            ft = lad.get(foe.get("teamId")) or lad.get(foe["name"])
            g_ = (me["rating"] - ft["rating"]) if (me and ft) else 0.0
            res = us_t.get("result")
            if dry:
                print(f"  {mid} {res} {m['map']} v {foe['name']} gap {g_:.0f}")
                continue
            fetch_replay(mid, us_t["side"], m, foe)
            x = f"{AUTO_SET}/x_{mid}"
            vb = which_version(mid, x, us_t["side"], m["map"], deep=(res == "loss" and g_ >= gap))
            vlab, bplay = vb if vb else (str(r["version"]).split("-")[0] + "-unknown", "")
            nu += not vb
            if res == "loss" and g_ >= gap:
                why = (f"refile (Deep 9 Nov): {m.get('kind', 'ranked')} loss under {vlab}" + (f" ({bplay})" if bplay else " (version unknown: no exact re-play)")
                       + f" on {m['map']} to {foe['name']} (rating {ft['rating']:.0f}) {g_:.0f} below us: skipped earlier as another version; find the flaw")
                q = subprocess.run(["nice", "-n", "10", "python3", "-I", os.path.abspath(__file__), "flag", mid, "--us", us_t["side"].upper(), "--why", why,
                                    "--by", "auto-refile", "--version", vlab, "--prio", "high" if g_ >= 100 else "normal"] + (["--bot", bplay] if bplay else []),
                                   capture_output=True, text=True, timeout=1800)
                print(f"  {mid}: {vlab}: " + (q.stdout.strip().split(chr(10))[0] if q.returncode == 0 else f"flag failed: {q.stderr.strip()[-200:]}"))
                nf += q.returncode == 0
            else:
                g = R.load(mid, us_t["side"].upper())
                row = dict(id=mid, version=vlab, result=res, kind=m.get("kind", "ranked"), map=m["map"], foe=foe["name"],
                           foe_rating=round(ft["rating"]) if ft else None, gap=round(g_), t=stamp, refiled=True, **triage_metrics(g))
                with open(TRIAGE, "a") as fh:
                    fh.write(json.dumps(row) + "\n")
                drop_replay(mid)
                nt += 1
        except Exception as e:  # noqa: BLE001  one bad game must not stop the rest
            print(f"  {mid} failed: {e!r}"[:300])
    print(f"refile: {nf} flagged critical, {nt} re-triaged, {nu} with no matching version (windows only)")


def cmd_triage(a):
    v = a[a.index("--version") + 1] if "--version" in a else live_version()[0]
    rows = triage_rows(v)
    flagged = {r["spec"]: r.get("prio", "normal") for r in index_rows()}
    if not rows:
        print(f"no triaged losses for {v}")
        return
    kinds = collections.Counter(r["mkind"] for r in rows if r.get("result", "loss") == "loss")
    nl = sum(1 for r in rows if r.get("result", "loss") == "loss")
    print(f"{v}: {nl} losses + {len(rows) - nl} wins triaged (no tokens; replay-based). Losses' worst-stretch kinds: "
          + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    print(f"{'priority':>8} {'id':36s} {'res':4s} {'kind':8s} {'map':18s} {'foe':20s} {'gap':>5} {'margin':>6} {'lead':>5} {'worst':>9} {'what':11s} flagged")
    for r in sorted(rows, key=lambda r: -priority(r, rows))[:int(a[a.index("--top") + 1]) if "--top" in a else 25]:
        print(f"{priority(r, rows):8.1f} {r['id']:36s} {r.get('result', 'loss')[:4]:4s} {r['kind']:8s} {r['map'][:18]:18s} {r['foe'][:20]:20s} {r.get('gap', 0):5d} {r['margin']:6d} "
              f"{r['lead']:5d} {r['worst']:+5d}@{r['worst_r']:<4d}{'!' if r['flip'] else ' '}{r['mkind'][:11]:11s} {flagged.get(r['id'], '')}")
    print("priority = worst 25-round fall + half the best lead held (+300 if a fuel/bot fault), x1.5 if that fall exceeds the final margin (!),"
          " x(1 + .05 per other game with the same kind of fall, at most x1.5), + the Elo gap when the foe is below us; wins x0.3 (lower priority)")

def index_rows():
    try:
        rows = [json.loads(x) for x in open(INDEX)]
    except OSError:
        return []
    for r in rows:
        if "prio" not in r or "t_s" not in r:
            try:
                m = json.load(open(f"{r['dir']}/meta.json"))
                r.setdefault("prio", m.get("prio", "normal"))
                r.setdefault("version", m.get("version"))
                r.setdefault("t_s", os.path.getmtime(f"{r['dir']}/meta.json"))
            except (OSError, ValueError):
                r.setdefault("t_s", 0)
    return rows


OPEN_HOURS = 6     # a ship comes every 30-60 min: unfinished games of the last few versions are still the current work
OPEN_CAP = 8       # at most this many unfinished critical games: analysts' agents are capped, each game can take 10 agents


def open_games():
    """unfinished games flagged in the last OPEN_HOURS, any version: [(prio rank, -gap, meta, dir, states)], most urgent first"""
    now = time.time()
    out = []
    for r in {x["dir"]: x for x in index_rows()}.values():
        try:
            m = json.load(open(f"{r['dir']}/meta.json"))
        except (OSError, ValueError):
            continue
        if now - os.path.getmtime(f"{r['dir']}/meta.json") > OPEN_HOURS * 3600 or is_identical(r["dir"], m) or m.get("closed"):
            continue  # 8 Nov (Combat): a closed game (critgame.py close) is neither listed nor counted toward the open cap
        st = [window_state(r["dir"], w["n"])[0] for w in m["windows"]]
        if any(x != "DONE" for x in st):
            out.append(({"high": 0, "normal": 1}.get(m.get("prio"), 2), -sum(x == "DONE" for x in st), m, r["dir"], st))
    out.sort(key=lambda o: (o[0], o[1], o[2]["t"]))
    return out


def open_live(v):
    """kept name: unfinished games, any recent version (a new ship must not make open work look finished)"""
    return len(open_games())


def prune(apply):
    live = live_version()[0]
    linked = set()  # replay dirs other sets (plat/top3_vNNN, climb lanes) point at with a symlink: never pruned from here
    for lk in glob.glob("/data/USER/plat/*/x_*"):
        if os.path.islink(lk):
            linked.add(os.path.realpath(lk))
    try:
        rows = [json.loads(x) for x in open(INDEX)]
    except OSError:
        rows = []
    freed, games = 0, 0
    for r in {x["dir"]: x for x in rows}.values():
        try:
            meta = json.load(open(f"{r['dir']}/meta.json"))
        except (OSError, ValueError):
            continue
        st = [window_state(r["dir"], w["n"])[0] for w in meta["windows"]]
        done = st and all(x == "DONE" for x in st)
        # finished when its last verdict or grill was written (a LIGHT game has no grill)
        fin = [os.path.getmtime(q) for w in meta["windows"] for q in (f"{r['dir']}/window_{w['n']}.grill", f"{r['dir']}/window_{w['n']}.verdict") if os.path.exists(q)]
        done_old = done and bool(fin) and time.time() - max(fin) > 6 * 3600
        # Econ 5 Nov: a ship must never pull files from under running walkers. An older version's game is pruned only when all its
        # windows are DONE, or nothing in its dir changed for 24 h (abandoned)
        # 9 Nov (owner: all our losses analysed; losses must stay readable): an unwalked game is abandoned only after 72 h idle, not 24
        idle = time.time() - max(os.path.getmtime(os.path.join(r["dir"], q)) for q in os.listdir(r["dir"])) > 72 * 3600
        stale = meta.get("version") not in (live, None) and (done or idle)
        if not (done_old or stale):
            continue
        paths = [f"{r['dir']}/window_{w['n']}.txt" for w in meta["windows"]]
        x = f"{AUTO_SET}/x_{meta['spec']}"
        if os.path.isdir(x) and os.path.realpath(x) not in linked:  # 10 Nov (Deep): a top-3 set's symlink still needs this replay
            paths += [os.path.join(x, q) for q in os.listdir(x)]
        paths = [q for q in paths if os.path.isfile(q)]
        if not paths:
            continue
        games += 1
        for q in paths:
            freed += os.path.getsize(q)
            if apply:
                os.remove(q)
        if apply and os.path.isdir(x) and not os.listdir(x):
            os.rmdir(x)
    print(f"{time.strftime('%H:%MZ', time.gmtime())} prune: {games} games {'cleaned' if apply else 'to clean (DRY; --apply deletes)'}, "
          f"{freed / 1e6:.1f} MB (DONE > 6 h or not the live version {live}; verdicts kept)")


def retests(dry):
    """replaycheck's tracker: a flaw whose fix is live gets its game replayed v the same foe bot; a lost one comes back here as a flagged game (owner 7 Nov)"""
    r = subprocess.run([sys.executable, "-I", f"{HERE}/replaycheck.py", "track"] + (["--dry"] if dry else []), capture_output=True, text=True, timeout=1800)
    print((r.stdout + r.stderr).strip()[-1500:])


def cmd_auto(a):
    gap = float(a[a.index("--gap") + 1]) if "--gap" in a else 50.0
    dry = "--dry" in a
    if "--loop" not in a:
        auto_pass(gap, dry, int(a[a.index("--light-every") + 1]) if "--light-every" in a else 1800)
        return
    every = int(a[a.index("--every") + 1]) if "--every" in a else 900
    sys.stdout.reconfigure(line_buffering=True)  # the log shows each line as it happens (a pass can take minutes of downloads)
    low_every = int(a[a.index("--light-every") + 1]) if "--light-every" in a else 1800
    pid = f"{ROOT}/auto.pid"
    try:
        old = int(open(pid).read())
        os.kill(old, 0)
        if old != os.getpid() and "critgame" in open(f"/proc/{old}/cmdline").read():
            sys.exit(f"critgame auto already running: pid {old}")
    except (OSError, ValueError):
        pass
    open(pid, "w").write(str(os.getpid()))
    while True:
        if os.path.exists(f"{ROOT}/AUTO_OFF"):
            print(f"{time.strftime('%H:%MZ', time.gmtime())} auto: {ROOT}/AUTO_OFF present, skipping")
        else:
            for step, fn in (("auto pass", lambda: auto_pass(gap, dry, low_every)), ("prune", lambda: prune(not dry)), ("retests", lambda: retests(dry))):
                try:
                    fn()
                except Exception as e:  # noqa: BLE001  one failed step doesn't stop the other
                    print(f"{time.strftime('%H:%MZ', time.gmtime())} {step} failed: {e!r}"[:400])
        sys.stdout.flush()
        time.sleep(every)


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("flag", "brief", "status", "link", "check", "auto", "prune", "triage", "regen", "addwin", "claim", "close", "refile", "supersede"):
        sys.exit(__doc__)
    os.makedirs(ROOT, exist_ok=True)
    {"supersede": cmd_supersede, "flag": cmd_flag, "claim": cmd_claim, "close": cmd_close, "brief": cmd_brief, "status": cmd_status, "link": cmd_link, "check": cmd_check, "auto": cmd_auto, "triage": cmd_triage, "refile": cmd_refile, "regen": cmd_regen, "addwin": cmd_addwin, "prune": lambda a: prune("--apply" in a)}[a[0]](a[1:])


if __name__ == "__main__":
    main()
