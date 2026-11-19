#!/usr/bin/env python3
"""inforead: an agent's whole info read in one command. Tool builder, 3 Nov (Builder: every agent hand-rolled its h2h, third-party read,
capped fuel and deaths; b998 could not get capped fuel on fresh games, b996's manifest cut map names and kept 364 of 1196 replays).

usage: python3 -I tools/lab/inforead.py CAND BASE --who bNNN [--n 300] [--opps hd126,nochase2,alldash] [--par 8] [--second] [--fg] [--maps-from TAG] [--engine cxe] [--vs-live]
  A flip (bots/CAND/FLIP from flip.sh) is read against its donor at flag 0 (FLIP's TRUNK), as shipcheck decides it;
  --vs-live compares with BASE instead (no-harm only: the donor's code reshuffle enters every map)
  --engine cxe: play every leg on HOST with cxe (tools/cxe, verified game-identical to the CLI; a 2% CLI spot-check per batch,
    the batch goes to Condor on any mismatch); replay-keeping reads (--keep-replays/--fight/--rounds) stay on Condor
                                               [--keep-replays] [--rounds R] [--fight [--fight-readers A.py,B.py]]
                                               [--draft-changed N [--draft-max 40000] [--probe-from PANELTAG] [--base-has F]]
                                               [--changed N [--changed-max 40000] [--wfams w_a,w_b]]
       python3 -I tools/lab/inforead.py mech TAG READER.py [--per-job 20]   a reader over a run's kept replays, CAND v BASE paired
       python3 -I tools/lab/inforead.py status [TAG]      runs and their state (all, or one)
       python3 -I tools/lab/inforead.py read TAG          re-read finished legs into result.txt (no games)
       python3 -I tools/lab/inforead.py resume TAG        play what a stopped run did not (same maps, same legs)
  CAND, BASE: bots in bots/ (BASE is usually live: head -1 /data/USER/st/bq/live.txt). --opps: third-party bots, short names
  (hd126 = nova_spar_hd126) or full; 'none' plays the h2h only. --n: new maps from the fresh pool (stratmaps --take: unsaved, half
  pathological), both seats of each. --par: legs at once (default 8: every leg of a 3-opponent read at once; 4 Nov, games on Condor; a leg is 2 x n games).
What it plays (tools/lab/stylepanel.py, the shipcheck fresh + panel legs, on Condor): CAND v BASE, CAND v each opp, BASE v each opp.
What it prints (result.txt, the same block on stdout with --fg):
  h2h      CAND v BASE map-pair score with a 95% CI and the per-kind table (stylepanel's FRESH block; kind flags are info here: no
           second set unless --second)
  third    per opp D = CAND's score v opp - BASE's score v opp, paired by map, and the pooled D (stylepanel's PANEL block)
  fuel     exhaustions CAND v BASE in the h2h games, each side's count per game capped at 5, paired by map (shipcheck's FUEL rule:
           fail when the diff > max(5%, 1.645 SE, 5)), and raw counts
  deaths, kills, earned gold, collected gems: CAND - BASE per game, paired by map, 95% CI
Not here: firing counts (a diag build's stdout); count firing on your own diag copy.
RARE CHANGES (7 Nov, owner): --changed N plays every leg ONLY on N new maps where CAND's games differ from BASE's (tools/lab/changedprobe.py: full games in both seats on fresh maps until N
  maps' two replays differ; identical replays are the base mirror game and read exactly .500, so they are dropped). CAND must be a flip of BASE. result.txt adds the CHANGED-MAP block: changed
  share, unchanged count, implied whole-pool effect, and the share from --wfams targeted families (those over-represent, so share and implied effect use the pool draw only).
DRAFT (4 Nov, owner): --draft-changed N plays every leg ONLY on N new maps where CAND's champion picks differ from BASE's in a seat,
  N/2 weird and N/2 std (tools/lab/draftprobe.py: 1-round CAND v BASE probes on pool maps first; skipped maps are kept, never deleted).
  result.txt adds the DRAFT-CHANGED block: firing share overall, per half and per family, and the implied whole-pool effect
  (share x (changed-map h2h - .5), share x third-party D). Valid for changes that act through the draft or kit-specific play only.
  Probing runs until N changed maps or --draft-max probed maps (default 40,000) or 4 h, then reads what it found. Probes are reused
  across arms with the same draft source (verified on a re-probed sample); --probe-from PANELTAG names a donor (e.g. the same draft
  rule written differently), also verified.
KEEP / MECH (3 Nov, Econ: mechanism games on the same maps as the score read). --keep-replays keeps every leg's replays (replay
  only, ~0.06 MB a game) in /data/USER/st/info/TAG/rep/<leg>/ with a set.json (readmany trunkset source; per game map, seat = the
  side of CAND or BASE, us, opp, leg, family, labels). --rounds R plays ONLY the CAND v opp and BASE v opp legs, every game stopped
  at round R, replays kept, no score lines (a capped game has no result): cheap early-game mechanism reads.
  --fight (Combat): --keep-replays, then Combat's fight readers (default /data/USER/st/combat_py/fq/fq.py and ele/ele.py; --fight-readers to
  change) over every kept leg on Condor; each reader's own records land in TAG/fight_<reader>.jsonl for its aggregator. Readers see
  meta id MAP__candVopp|baseVopp__seat (their name convention; the node's staged copy has no name) and meta us/opp/seat/leg as well.
  mech TAG READER.py: READER.py defines read(path, meta) -> {name: number} for side meta['seat'] (readmany's contract: load with
  replay.load(path, us=meta['seat'].upper())); it runs on Condor over the panel legs (tools/lab/readmany.py) and prints, per opp and
  pooled, per metric: CAND mean, BASE mean, D (paired by map: each arm's mean over the map's seats), %, z, the changed share of game
  pairs and the share of changed maps where CAND is higher. The h2h leg (CAND v BASE) is read but not paired. Output
  TAG/mech_<READER>.txt and .jsonl.
Runs detach by default (setsid): the command prints TAG and returns. Files /data/USER/st/info/TAG/: cmd.txt, run.log, result.txt,
and .done when finished (its one line: the h2h, third-party and fuel summary), so the Builder can pick a read up without the agent.
TAG = ir<who>_<UTC stamp>: unique, short, safe in condab's run names (fp<TAG>, pc<TAG>_K, pl<TAG>_K in /data/USER/st/bq)."""
import collections
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
BQ = "/data/USER/st/bq"
INFO = "/data/USER/st/info"
PANEL_DIR = "/data/USER/st/panel"
CAP = 5
KEEP_MIN_FREE_GB = float(os.environ.get('KEEP_MIN_FREE_GB', 25))  # /data free GB: below it --keep-replays and --fight are dropped; quotaguard expires kept replays 18 h after a read finishes. 5 Nov (TB2): /data holds root's cachefilesd cache (/data/.fscache, ~215 GB, keeps free space at 3-10%), so % used reads 90-97% whatever we store; guard on absolute free space


def die(m):
    sys.exit("inforead: " + m)


def bot(x):
    for c in (x, "nova_spar_" + x):
        if os.path.isdir(f"{REPO}/bots/{c}/src"):
            return c
    die(f"no bot {x} (nor nova_spar_{x}) in bots/")


def ci(v):
    n = len(v)
    if n < 2:
        return (v[0] if v else float("nan")), float("nan"), n
    m = sum(v) / n
    return m, math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1) / n), n


def paired(tag, cand, base):
    """{stat: per-map CAND - BASE (sum over seats / games)} and capped fuel totals from the h2h leg's game records."""
    per = collections.defaultdict(lambda: collections.defaultdict(float))
    games = collections.Counter()
    p = f"{PANEL_DIR}/{tag}/fp_games.jsonl"
    for line in open(p) if os.path.exists(p) else ():
        try:
            g = json.loads(line)
        except ValueError:
            continue
        if {g.get("a"), g.get("b")} != {cand, base}:
            continue
        c, b = (g["sa"], g["sb"]) if g["a"] == cand else (g["sb"], g["sa"])
        m = per[g["map"]]
        games[g["map"]] += 1
        for k in ("deaths", "kills", "earnedGold", "collectedGems"):
            m[k] += c.get(k, 0) - b.get(k, 0)
        if "pair" in c and "pair" in b:  # 9 Nov (owner): a linked C&I pair death counts once
            m["pdeaths"] += (c["deaths"] - c["pair"]) - (b["deaths"] - b["pair"])
            m["np"] += 1
        m["fc"] += min(int(c.get("fuel", 0)), CAP)
        m["fb"] += min(int(b.get("fuel", 0)), CAP)
        m["rc"] += int(c.get("fuel", 0))
        m["rb"] += int(b.get("fuel", 0))
    return per, games


def extra(tag, cand, base):
    per, games = paired(tag, cand, base)
    if not per:
        return ["fuel / deaths: no h2h game records yet"], "fuel ?"
    L = []
    d = [m["fc"] - m["fb"] for m in per.values()]
    mu, se, n = ci(d)
    se_sum = se * n if se == se else 0.0
    c, b = sum(m["fc"] for m in per.values()), sum(m["fb"] for m in per.values())
    fail = c - b > max(0.05 * b, 1.645 * se_sum, 5)
    z = (c - b) / se_sum if se_sum > 0 else 0.0
    fl = f"cap{CAP} {c:.0f} v {b:.0f} ({c / max(1, b):.2f}x, z {z:+.1f}, {n} maps) {'FAIL' if fail else 'ok'} by the FUEL rule"
    L.append(f"fuel     exhaustions in the h2h games, {fl}; raw {sum(m['rc'] for m in per.values()):.0f} v {sum(m['rb'] for m in per.values()):.0f}")
    ng = sum(games.values())
    allp = all(m.get("np", 0) == games[mp] for mp, m in per.items())
    for k, lab in ((("pdeaths", "deaths (pair once)"),) if allp else ()) + (("deaths", "deaths (raw)" if allp else "deaths"), ("kills", "kills"),
                                                                               ("earnedGold", "gold earned"), ("collectedGems", "gems collected")):
        v = [m[k] / games[mp] for mp, m in per.items()]
        mu, se, n = ci(v)
        L.append(f"{lab:15s} CAND - BASE per game {mu:+.2f} [{mu - 1.96 * se:+.2f}, {mu + 1.96 * se:+.2f}] z {mu / se if se and se == se else 0:+.1f}"
                 f" ({n} maps, {ng} games)")
    return L, (f"fuel {c / b:.2f}x" if b else f"fuel {c:.0f} v 0") + (" FAIL" if fail else "")


def legs_note(tag, txt, fr):
    """3 Nov (irb1030: 'third-party D +.012 n298' was one opponent of three, quoted as a panel read): each opponent's D and n in the summary line, and
    PARTIAL naming every leg that is missing or under 90% of the read's maps."""
    cfg = json.load(open(f"{INFO}/{tag}/cmd.json"))
    try:
        nm = len(json.load(open(f"{PANEL_DIR}/{tag}/otf.json"))["maps"])
    except (OSError, ValueError, KeyError):
        nm = cfg.get("n", 0)
    rows = {}
    for m in re.finditer(r"^  (\S+)\s+n\s+(\d+)\s+CAND \S+\s+LIVE \S+\s+D ([+\-\d.nan]+) \[", txt, re.M):
        rows[m.group(1)] = (m.group(3), int(m.group(2)))
    short = lambda o: o.replace("nova_spar_", "")  # noqa: E731
    parts, lost = [], []
    for o in cfg.get("opps", []):
        d, n = rows.get(o, ("?", 0))
        parts.append(f"{short(o)} {d} n{n}")
        if n < 0.9 * nm:
            lost.append(f"{short(o)} n{n}")
    h2hn = int(fr.group(3)) if fr else 0
    if h2hn < 0.9 * nm:
        lost.insert(0, f"h2h n{h2hn}")
    return (f" | {', '.join(parts)}" if parts else "") + (f" | PARTIAL of {nm} maps: {', '.join(lost)} (inforead.py resume {tag})" if lost else "")


def write_result(tag, cand, base, hetero=True):
    sp = f"{BQ}/sp{tag}.txt"
    txt = open(sp).read() if os.path.exists(sp) else "(no stylepanel summary yet)\n"
    small = re.compile(r"^  \S+\s+\S+\s+n\s+(\d+)\s+[\d.]+ \[")  # kind rows under n 10 are noise in an info read
    txt = "".join(x for x in txt.splitlines(True) if not (small.match(x) and int(small.match(x).group(1)) < 10))
    L, fsum = extra(tag, cand, base)
    fr = re.search(r"^FRESH: (\S+)\s+CAND vs LIVE ([\d.na]+ \[[^\]]*\]) over (\d+)", txt, re.M)
    pa = re.search(r"^PANEL: (\S+)\s+pooled D ([+\-\d.na]+ \[[^\]]*\]) over (\d+)", txt, re.M)
    head = (f"h2h {fr.group(2)} n{fr.group(3)}" if fr else "h2h ?") + "; " + \
           (f"third-party D {pa.group(2)} n{pa.group(3)}" if pa else "third-party -") + "; " + fsum
    head += legs_note(tag, txt, fr)
    try:  # 8 Nov: a stock filter that fails its safety row (or a too-rare probe) ends the read before any game: say why, not 'h2h ?'
        inc = re.findall(r"(?:DRAFT|CHANGED): INCONCLUSIVE \((.+)\)\s*$", open(f"{INFO}/{tag}/run.log", errors="replace").read(), re.M)
        if inc:
            head = f"INCONCLUSIVE (no read played): {inc[-1]}; " + head
    except OSError:
        pass
    try:
        c = json.load(open(f"{INFO}/{tag}/cmd.json"))
        if c.get("flip_base"):
            head += f" | base = donor at flag 0 ({base})"
        elif c.get("vs_live"):
            head += " | v live: NO-HARM ONLY (code reshuffle in every map)"
    except (OSError, ValueError):
        pass
    # 4 Nov (Builder, b1089): a leg with no maps must never read as D +0.000; say so first, loudly (stylepanel rows 'n 0', FRESH over 0)
    empty = [m.group(1) for m in re.finditer(r"^  (\S+)\s+n\s+0\s", txt, re.M)]
    if fr and fr.group(3) == "0":
        empty.insert(0, "h2h (FRESH)")
    if empty:
        head = f"EMPTY LEG (0 maps, the read is invalid): {', '.join(empty)}; " + head
        print(f"inforead: EMPTY LEG in {tag}: {', '.join(empty)}", file=sys.stderr)
    if hetero and fr and os.path.exists(f"{PANEL_DIR}/{tag}/fp_games.jsonl"):  # 4 Nov (owner: which maps is it good on?): hetero.py's lead line
        try:
            r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", "tools/lab/hetero.py", "read", tag, "--cand", cand, "--brief",
                                "--perm", "500", "--min-half", "40"], cwd=REPO, capture_output=True, text=True, timeout=900)
            hl = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        except subprocess.TimeoutExpired:
            hl = "(hetero timed out)"
        L = L + ["", f"{hl}  [one read, min-half 40: a lead only; pool reads with `hetero.py flag REGEX` for a claim]"]
    out = (f"# INFO READ {tag}: {cand} v {base} ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})\n{head}\n\n"
           "h2h = stylepanel FRESH (CAND v BASE); third = stylepanel PANEL (D = CAND v opp - BASE v opp). Verdict words in the\n"
           "block below are shipcheck's bars, printed for reference: an info read decides nothing.\n\n"
           + txt.replace("CAND vs LIVE", "CAND vs BASE") + "\n" + "\n".join(L) + "\n")
    open(f"{INFO}/{tag}/result.txt.part", "w").write(out)
    os.replace(f"{INFO}/{tag}/result.txt.part", f"{INFO}/{tag}/result.txt")
    return head


def mech_legs(tag, cfg):
    """--rounds R: CAND v opp and BASE v opp on n new maps, each game capped at R rounds, replays kept (condab OTF_KEEP/OTF_ROUNDS)."""
    d, md = f"{INFO}/{tag}", f"{INFO}/{tag}/maps"
    empty = f"{BQ}/subsets/empty.txt"
    if not os.path.exists(empty):
        open(empty, "w").close()
    with open(f"{d}/run.log", "a") as lg:
        if not os.path.exists(f"{md}/otf.json") and cfg.get("maps_from"):  # 12 Nov (Builder, b2119: --rounds drew fresh maps despite --maps-from)
            src = f"{PANEL_DIR}/{cfg['maps_from']}"
            os.makedirs(md, exist_ok=True)
            for fn in os.listdir(src):
                if fn == "otf.json" or fn.endswith(".map26a"):
                    shutil.copyfile(os.path.join(src, fn), os.path.join(md, fn))
            lg.write(f"maps from {src} ({cfg['n']} maps)\n")
        if not os.path.exists(f"{md}/otf.json"):
            r = subprocess.run([sys.executable, "-I", "tools/lab/stratmaps.py", md, "--n", str(cfg["n"]), "--take", "--who", f"inforead:{tag}"],
                               cwd=REPO, stdout=lg, stderr=subprocess.STDOUT)
            if r.returncode:
                die(f"stratmaps rc {r.returncode} (see {d}/run.log)")
        legs = [(f"mk{tag}{arm}{k}", x, o) for k, o in enumerate(cfg["opps"]) for arm, x in (("c", cfg["cand"]), ("b", cfg["base"]))]
        todo, live = [lg_ for lg_ in legs if kept_n(f"{d}/rep/{lg_[0]}") < 1.9 * cfg["n"]], []
        for name, x, o in todo:
            while len([p for p in live if p.poll() is None]) >= cfg["par"]:
                time.sleep(20)
            env = dict(os.environ, OTF_DIR=md, OTF_KEEP=f"{d}/rep/{name}", OTF_ROUNDS=str(cfg["rounds"]), CONDAB_PRIO=os.environ.get("CONDAB_PRIO") or os.environ.get("READ_PRIO") or "10")  # 10 Nov: READ_PRIO (b1802)
            for k in ("KEEP", "SET", "SUBSET", "CONFIRM", "BIG", "STOP", "OTF_GAMES"):
                env.pop(k, None)
            lg.write(f"{time.strftime('%H:%M:%SZ', time.gmtime())} leg {name}: {x} v {o}, {cfg['rounds']} rounds\n")
            lg.flush()
            live.append(subprocess.Popen(["nice", "-n", "10", "sh", "tools/lab/condab.sh", x, o, name, empty], cwd=REPO, env=env,
                                         stdout=open(f"{BQ}/{name}.inforead.log", "w"), stderr=subprocess.STDOUT))
        for p in live:
            p.wait()
    for f in os.listdir(md):
        if f.endswith(".map26a"):
            os.remove(os.path.join(md, f))  # otf.json keeps every seed and recipe (condab.py --otf-regen)
    L = [f"# MECH LEGS {tag}: {cfg['cand']} v {cfg['base']}, {cfg['n']} new maps, games capped at {cfg['rounds']} rounds "
         f"({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})", "no scores: capped games have no result. Replays kept:"]
    L += [f"  {name} {x} v {o}: {kept_n(f'{d}/rep/{name}')} games" for name, x, o in legs]
    L.append(f"next: python3 -I tools/lab/inforead.py mech {tag} READER.py")
    open(f"{d}/result.txt", "w").write("\n".join(L) + "\n")
    head = f"mech legs: {sum(kept_n(f'{d}/rep/{n}') for n, _, _ in legs)} replays, r<={cfg['rounds']}"
    open(f"{d}/.done", "w").write(head + "\n")
    print(head)


def kept_n(leg_dir):
    try:
        return len(json.load(open(f"{leg_dir}/set.json"))["games"])
    except (OSError, ValueError, KeyError):
        return 0


def mech(tag, reader, per_job):
    """Run READER over TAG's kept panel legs (readmany on Condor) and pair CAND with BASE per opp, map and seat."""
    d = f"{INFO}/{tag}"
    cfg = json.load(open(f"{d}/cmd.json"))
    srcs = sorted(os.path.dirname(p) for p in glob.glob(f"{d}/rep/*/set.json"))
    if not srcs:
        die(f"{tag} kept no replays (run it with --keep-replays or --rounds R)")
    stem = os.path.splitext(os.path.basename(reader))[0]
    out = f"{d}/mech_{stem}.jsonl"
    r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", "tools/lab/readmany.py", os.path.abspath(reader)] + srcs
                       + ["--out", out, "--per-job", str(per_job)], cwd=REPO)
    if r.returncode or not os.path.exists(out):
        die(f"readmany rc {r.returncode}")
    cand, base = cfg["cand"], cfg["base"]
    arms = {}  # (opp, map, seat) -> {"c": res, "b": res}
    nerr = nh2h = 0
    for line in open(out):
        try:
            g = json.loads(line)
        except ValueError:
            continue
        m = g.get("meta", {})
        if "res" not in g or not isinstance(g["res"], dict):
            nerr += 1
            continue
        if {m.get("us"), m.get("opp")} == {cand, base}:
            nh2h += 1
            continue
        arm = "c" if m.get("us") == cand else "b" if m.get("us") == base else None
        if arm:
            arms.setdefault((m.get("opp"), m.get("map"), m.get("seat")), {})[arm] = g["res"]
    num = lambda v: float(v) if isinstance(v, (int, float)) else None  # noqa: E731  (bools count as 0/1)
    keys = sorted({k for a in arms.values() for res in a.values() for k, v in res.items() if num(v) is not None})
    L = [f"# MECH {tag} {stem}: {cand} (CAND) v {base} (BASE), {sum(1 for a in arms.values() if len(a) == 2)} paired games"
         f"{' (capped at r' + str(cfg['rounds']) + ')' if cfg.get('rounds') else ''}; {nerr} reader errors; {nh2h} h2h games not paired",
         f"{'opp':12s} {'metric':24s} {'CAND':>10s} {'BASE':>10s} {'D':>10s} {'%':>7s} {'z':>6s} {'chg':>5s} {'C>B':>5s} maps"]
    rows = []
    for opp in sorted({k[0] for k in arms}) + ["POOLED"]:
        for key in keys:
            per = collections.defaultdict(lambda: [[], [], 0, 0])  # map -> [cand vals, base vals, pairs, changed pairs]
            for (o, mp, _), a in arms.items():
                if (opp != "POOLED" and o != opp) or len(a) < 2:
                    continue
                c, b = num(a["c"].get(key)), num(a["b"].get(key))
                if c is None or b is None:
                    continue
                p = per[mp]
                p[0].append(c); p[1].append(b); p[2] += 1; p[3] += c != b
            if len(per) < 2:
                continue
            dm = [sum(p[0]) / len(p[0]) - sum(p[1]) / len(p[1]) for p in per.values()]
            mu, se, n = ci(dm)
            mc = sum(sum(p[0]) / len(p[0]) for p in per.values()) / n
            mb = sum(sum(p[1]) / len(p[1]) for p in per.values()) / n
            chg = sum(p[3] for p in per.values()) / max(1, sum(p[2] for p in per.values()))
            nz = [x for x in dm if x != 0]
            better = sum(1 for x in nz if x > 0) / len(nz) if nz else float("nan")
            z = mu / se if se and se == se else 0.0
            rows.append(dict(opp=opp, metric=key, cand=mc, base=mb, d=mu, se=se, z=z, changed=chg, better=better, maps=n))
            L.append(f"{opp[:12]:12s} {key[:24]:24s} {mc:10.3f} {mb:10.3f} {mu:+10.3f} {100 * mu / mb if mb else float('nan'):+7.1f} "
                     f"{z:+6.1f} {chg:5.2f} {better:5.2f} {n}")
    txt = "\n".join(L) + "\n"
    open(f"{d}/mech_{stem}.txt", "w").write(txt)
    json.dump(rows, open(f"{d}/mech_{stem}.rows.json", "w"))
    print(txt)


FIGHT_READERS = ["/data/USER/st/combat_py/fq/fq.py", "/data/USER/st/combat_py/ele/ele.py"]


def fight_reads(tag, cfg):
    """--fight: each fight reader over the kept legs (readmany), its records in TAG/fight_<reader>.jsonl."""
    d = f"{INFO}/{tag}"
    srcs = sorted(os.path.dirname(p) for p in glob.glob(f"{d}/rep/*/set.json"))
    L = []
    for rd in cfg.get("fight_readers") or FIGHT_READERS:
        stem = os.path.splitext(os.path.basename(rd))[0]
        if not os.path.exists(rd) or not srcs:
            L.append(f"fight {stem}: {'no reader ' + rd if srcs else 'no kept replays'}")
            continue
        wrap = f"{d}/fightwrap_{stem}.py"  # the reader's own source inlined (nodes cannot read /data), then a read() that names the game
        open(wrap, "w").write(open(rd).read() + f"""

_fr_read = read
_FR_CAND = {cfg['cand']!r}


def read(path, meta):
    m = dict(meta)
    arm = "cand" if m.get("us") == _FR_CAND else "base"
    m["id"] = f"{{m.get('map', 'map')}}__{{arm}}V{{str(m.get('opp', '')).replace('nova_spar_', '')}}__{{m.get('seat', 'a')}}"
    return _fr_read(path, m)
""")
        out = f"{d}/fight_{stem}.jsonl"
        r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", "tools/lab/readmany.py", wrap] + srcs + ["--out", out], cwd=REPO,
                           stdout=open(f"{d}/fight_{stem}.log", "w"), stderr=subprocess.STDOUT)
        n = ne = 0
        for ln in open(out) if os.path.exists(out) else ():
            n += 1
            ne += '"err"' in ln[:4000] and '"res"' not in ln[:200]
        L.append(f"fight {stem}: {n - ne} of {n} games read (rc {r.returncode}) -> {out}")
    return L


def rebuild_maps(tag):
    """Maps a resume needs that are gone, from otf.json's seeds and recipes (condab.py --otf-regen; closeread's rebuilt games reproduce the original results)."""
    pd = f"{PANEL_DIR}/{tag}"

    import hashlib
    cache = f"{INFO}/_regen"  # 9 Nov (/var: root's syslog logs every process start): three reads --maps-from the same tag each regenerated the
    os.makedirs(cache, exist_ok=True)  # same maps (a python + node per map); a regenerated map is now kept here by seed + recipe and hard-linked

    def one(m):
        p = f"{pd}/{m['name']}.map26a"
        if not os.path.exists(p):
            key = hashlib.sha1((str(m["seed"]) + json.dumps(m["recipe"], sort_keys=True)).encode()).hexdigest()[:20]
            c = f"{cache}/{key}.map26a"
            if os.path.exists(c):
                try:
                    os.link(c, p)
                    return
                except OSError:
                    pass
            with cxebuild.flock_slot("regenslots", "IR_REGEN_SLOTS", 6):  # 8 Nov: six reads resuming at once ran 36 rebuilds (load 56): 6 machine-wide
                if os.path.exists(p):
                    return
                if os.path.exists(c):
                    try:
                        os.link(c, p)
                        return
                    except OSError:
                        pass
                subprocess.run(["nice", "-n", "10", sys.executable, "-I", "tools/lab/condab.py", "--otf-regen", str(m["seed"]), json.dumps(m["recipe"]), p],
                               cwd=REPO, capture_output=True, text=True)
                if os.path.exists(p) and not os.path.exists(c):
                    try:
                        os.link(p, c)
                    except OSError:
                        pass
    try:  # the cache keeps a map 2 days from its last regeneration
        for fn in os.listdir(cache):
            fp = os.path.join(cache, fn)
            if time.time() - os.path.getmtime(fp) > 2 * 86400:
                os.remove(fp)
    except OSError:
        pass
    sys.path.insert(0, os.path.join(REPO, "tools/cxe"))
    import cxebuild
    import concurrent.futures as cf  # 8 Nov: one at a time was ~190 s for 300 maps before every resumed read; same maps, 6 at once (nice 10)
    ms = json.load(open(f"{pd}/otf.json"))["maps"]
    if os.environ.get("IR_REGEN_BATCH", "1") == "1":
        # 11 Nov (Coordinator, /var): a python + node per map was ~2 KB of root syslog per process start. Cache hits link as before; the rest
        # go to IR_REGEN_PAR (6) batch processes (condab --otf-regen-many: one python + one node server each), each inside a regen slot
        todo = []
        for m in ms:
            p = f"{pd}/{m['name']}.map26a"
            if os.path.exists(p):
                continue
            key = hashlib.sha1((str(m["seed"]) + json.dumps(m["recipe"], sort_keys=True)).encode()).hexdigest()[:20]
            c = f"{cache}/{key}.map26a"
            try:
                os.link(c, p)
                continue
            except OSError:
                todo.append((m, p, c))
        if todo:
            k = max(1, min(int(os.environ.get("IR_REGEN_PAR", 6)), (len(todo) + 9) // 10))
            chunks = [todo[i::k] for i in range(k)]

            def batch(ch, i):
                lf = f"{pd}/.regen_{os.getpid()}_{i}.tsv"
                open(lf, "w").write("".join(f"{m['seed']}\t{json.dumps(m['recipe'])}\t{p}\n" for m, p, _ in ch))
                with cxebuild.flock_slot("regenslots", "IR_REGEN_SLOTS", 6):
                    subprocess.run(["nice", "-n", "10", sys.executable, "-I", "tools/lab/condab.py", "--otf-regen-many", lf], cwd=REPO,
                                   capture_output=True, text=True)
                os.remove(lf)
                for _m, p, c in ch:
                    if os.path.exists(p) and not os.path.exists(c):
                        try:
                            os.link(p, c)
                        except OSError:
                            pass
            with cf.ThreadPoolExecutor(k) as ex:
                list(ex.map(batch, chunks, range(k)))
        return
    with cf.ThreadPoolExecutor(int(os.environ.get("IR_REGEN_PAR", 6))) as ex:
        list(ex.map(one, ms))


def run(tag):
    d = f"{INFO}/{tag}"
    cfg = json.load(open(f"{d}/cmd.json"))
    if cfg.get("rounds"):
        return mech_legs(tag, cfg)
    env = dict(os.environ)
    if cfg.get("engine"):  # --engine cxe: every condab leg of this read plays on cxe (CLI spot-checked; Condor on any mismatch)
        env["CONDAB_ENGINE"] = cfg["engine"]
    if cfg.get("keep"):
        env["SP_KEEP"] = f"{d}/rep"
    if not cfg["second"]:
        env["SP_KIND_Z"] = "99"  # kind flags are info here: never a second fresh set
    cmd = ["nice", "-n", "10", sys.executable, "-I", "tools/lab/stylepanel.py", cfg["cand"], cfg["base"], tag, "--n", str(cfg["n"]),
           "--par", str(cfg["par"])]
    pj = f"{PANEL_DIR}/{tag}/probe.json"
    cj = f"{PANEL_DIR}/{tag}/changed.json"
    if cfg.get("changed"):
        env["SP_CHANGED_MAX"] = str(cfg.get("changed_max") or 40000)
        env["SP_CHANGED_WFAMS"] = cfg.get("wfams") or ""
    if cfg.get("base_has"):  # 8 Nov: --draft-changed / --changed from draftstock.py's stock, filtered (draftprobe, changedprobe)
        env["SP_BASE_HAS"] = cfg["base_has"]
    if cfg.get("draft_changed"):
        env["SP_DRAFT_MAX"] = str(cfg.get("draft_max") or 40000)
        if cfg.get("probe_from"):
            env["DP_REUSE_FROM"] = cfg["probe_from"]
    if cfg.get("changed") and not (os.path.exists(cj) and json.load(open(cj)).get("done")):
        cmd += ["--changed", str(cfg["changed"])]  # the probe (or its unfinished part) runs inside stylepanel first
    elif cfg.get("draft_changed") and not (os.path.exists(pj) and json.load(open(pj)).get("done")):
        cmd += ["--draft-changed", str(cfg["draft_changed"])]  # the probe (or its unfinished part) runs inside stylepanel first
    elif os.path.exists(f"{PANEL_DIR}/{tag}/otf.json"):  # a resume: only the short legs play, on the same maps
        rebuild_maps(tag)
        cmd.append("--resume")
    cmd += ["--panel", ",".join(cfg["opps"])] if cfg["opps"] else ["--fresh-only"]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script's dir off sys.path
    import readslots  # 7 Nov: at most bq/bigread_max big reads (> 600 maps, or a changed probe) at once across agents; the rest wait in order
    with open(f"{d}/run.log", "a") as lg:
        run.slot = readslots.acquire(tag, int(cfg["n"]), f"inforead {cfg.get('who', '')}", lambda m: (lg.write(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {m}\n"), lg.flush()),
                                     changed=bool(cfg.get("changed") or cfg.get("draft_changed")))
        lg.write(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {' '.join(cmd)}\n")
        lg.flush()
        rc = subprocess.run(cmd, cwd=REPO, env=env, stdout=lg, stderr=subprocess.STDOUT).returncode
        lg.write(f"{time.strftime('%H:%M:%SZ', time.gmtime())} stylepanel rc {rc}\n")
    # 4 Nov (iterspeed report): the result and .done first, hetero.py's lead line (--perm 500, median 2.8 min) after, so a read is
    # usable as soon as its games are in; result.txt is rewritten with the lead line when it is ready
    head = write_result(tag, cfg["cand"], cfg["base"], hetero=False)
    fl = fight_reads(tag, cfg) if cfg.get("fight") else []
    if fl:
        with open(f"{d}/result.txt", "a") as f:
            f.write("\n" + "\n".join(fl) + "\n")
    open(f"{d}/.done", "w").write(head + "\n")
    print(head, flush=True)
    write_result(tag, cfg["cand"], cfg["base"], hetero=True)
    if fl:
        with open(f"{d}/result.txt", "a") as f:
            f.write("\n" + "\n".join(fl) + "\n")


def status(tag=None):
    tags = [tag] if tag else sorted(os.listdir(INFO)) if os.path.isdir(INFO) else []
    for t in tags:
        d = f"{INFO}/{t}"
        if not os.path.exists(f"{d}/cmd.json"):
            continue
        c = json.load(open(f"{d}/cmd.json"))
        if os.path.exists(f"{d}/.done"):
            st = "done: " + open(f"{d}/.done").read().strip()
        else:
            alive = c.get("pid") and os.path.exists(f"/proc/{c['pid']}")
            st = ("running" if alive else "STOPPED (inforead.py resume " + t + ")") + f", {sum(1 for _ in open(f'{PANEL_DIR}/{t}/fp_games.jsonl')) if os.path.exists(f'{PANEL_DIR}/{t}/fp_games.jsonl') else 0} h2h games in"
        md = f" r<={c['rounds']}" if c.get("rounds") else " keep" if c.get("keep") else ""
        md += " draft-changed" if c.get("draft_changed") else ""
        md += " changed" if c.get("changed") else ""
        print(f"{t:28s} {c['who']:8s} {c['cand']} v {c['base']} n{c['n']}{md} opps {','.join(c['opps']) or '-'} | {st}")


def unit_main():
    """9 Nov (b1766): launched as a systemd unit's main process (the parent is systemd; `nice` execs in place): a detached run would be killed
    when the unit ends right after this returns, so such a launch stays in the foreground on its own."""
    if os.environ.get("INFOREAD_DETACH") == "1":
        return False
    try:
        if open(f"/proc/{os.getppid()}/comm").read().strip() == "systemd":
            return True
    except OSError:
        pass
    try:  # 11 Nov (b1860, b1836: launched via `systemd-run ... sh -c '... inforead ...'`, the parent is sh, the detached child stayed in the
        # unit's cgroup and died with the unit): inside any transient *.service unit, stay in the foreground (INFOREAD_DETACH=1 overrides)
        last = open("/proc/self/cgroup").read().strip().splitlines()[-1].rsplit("/", 1)[-1]
        return last.endswith(".service")
    except (OSError, IndexError):
        return False


def start(tag, fg):
    d = f"{INFO}/{tag}"
    if fg or unit_main():  # 12 Nov (Builder, b2154: a --fg read showed 'STOPPED' while running): record this process as the runner
        try:
            c = json.load(open(f"{d}/cmd.json"))
            c["pid"] = os.getpid()
            json.dump(c, open(f"{d}/cmd.json", "w"))
        except (OSError, ValueError):
            pass
        return run(tag)
    p = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "_run", tag], cwd=REPO, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=open(f"{d}/run.log", "a"))
    c = json.load(open(f"{d}/cmd.json"))
    c["pid"] = p.pid
    json.dump(c, open(f"{d}/cmd.json", "w"))
    print(f"inforead {tag} started (pid {p.pid}); result: {d}/result.txt when {d}/.done exists; "
          f"state: python3 -I tools/lab/inforead.py status {tag}")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if a[0] == "_run":
        return run(a[1])
    if a[0] == "mech":
        if len(a) < 3 or not os.path.exists(f"{INFO}/{a[1]}/cmd.json"):
            die("usage: inforead.py mech TAG READER.py [--per-job 20]")
        return mech(a[1], a[2], int(a[a.index("--per-job") + 1]) if "--per-job" in a else 20)
    if a[0] == "status":
        return status(a[1] if len(a) > 1 else None)
    if a[0] in ("read", "resume"):
        if len(a) < 2 or not os.path.exists(f"{INFO}/{a[1]}/cmd.json"):
            die(f"no run {a[1:2]}")
        c = json.load(open(f"{INFO}/{a[1]}/cmd.json"))
        if a[0] == "read":
            head = write_result(a[1], c["cand"], c["base"])
            if os.path.exists(f"{INFO}/{a[1]}/.done"):
                open(f"{INFO}/{a[1]}/.done", "w").write(head + "\n")
            return print(head)
        if c.get("pid") and os.path.exists(f"/proc/{c['pid']}"):
            die(f"{a[1]} is still running (pid {c['pid']})")
        if os.path.exists(f"{INFO}/{a[1]}/.done"):
            os.remove(f"{INFO}/{a[1]}/.done")
        return start(a[1], "--fg" in a)
    if len(a) < 2 or "--who" not in a:
        sys.exit(__doc__)
    # 12 Nov (Builder, b2119: --base-has=F was silently ignored): --opt=value is the same as --opt value
    a = [y for x in a for y in (x.split("=", 1) if x.startswith("--") and "=" in x else [x])]
    opt = lambda k, dflt: a[a.index(k) + 1] if k in a else dflt
    cand, base, who = bot(a[0]), bot(a[1]), opt("--who", "")
    # 4 Nov (FM: 4 of 4 flags passed the info bar v live and failed shipcheck): a flip's h2h is read against its own
    # donor at flag 0 (FLIP's TRUNK), as shipcheck decides it, so unfired maps are exact ties and the donor's code
    # reshuffle stays out; --vs-live keeps BASE (the old read, labelled no-harm only)
    vs_live = "--vs-live" in a
    try:
        flip = dict(ln.rstrip("\n").split("=", 1) for ln in open(os.path.join(REPO, "bots", cand, "FLIP")) if "=" in ln)
    except OSError:
        flip = {}
    if flip.get("TRUNK") and not vs_live and flip["TRUNK"] != base:
        print(f"inforead: {cand} is a flip of {flip['TRUNK']} ({flip.get('FLIPS', '').strip()}): h2h base = {flip['TRUNK']} at flag 0, "
              f"not {base} (pass --vs-live for the live comparison, no-harm only)", file=sys.stderr)
        base = bot(flip["TRUNK"])
    if not re.fullmatch(r"[A-Za-z0-9]{1,10}", who):
        die("--who: 1-10 letters or digits (it goes into condab run names)")
    if cand == base:
        die("CAND and BASE are the same bot")
    ol = opt("--opps", ",".join(x for x in ("hd126", "nochase2", "alldash") if os.path.isdir(f"{REPO}/bots/nova_spar_{x}/src")) or "none")
    opps = [] if ol == "none" else [bot(x) for x in ol.split(",") if x]
    n = int(opt("--n", 300))
    mfrom = opt("--maps-from", None)  # 4 Nov (hetero confirm): play exactly the maps of PANEL/<TAG>/otf.json (rebuilt from seeds)
    if mfrom:
        try:
            n = len(json.load(open(f"{PANEL_DIR}/{mfrom}/otf.json"))["maps"])
        except (OSError, ValueError, KeyError):
            die(f"--maps-from: no {PANEL_DIR}/{mfrom}/otf.json")
        if "--opps" not in a:
            opps = []  # a confirm read: the h2h on those maps only, unless --opps is given
    dc = int(opt("--draft-changed", 0))
    if dc:
        if mfrom or "--rounds" in a:
            die("--draft-changed: not with --maps-from or --rounds")
        n = dc
    cn = int(opt("--changed", 0))
    if cn:
        if mfrom or "--rounds" in a or dc:
            die("--changed: not with --maps-from, --rounds or --draft-changed")
        n = cn
    base_has = opt("--base-has", None)
    if base_has and not (dc or cn):
        die("--base-has goes with --draft-changed N or --changed N")
    if not 20 <= n <= 1200:
        die("--n: 20-1200")
    if ("--keep-replays" in a or "--fight" in a) and "--rounds" not in a:  # 3 Nov (Builder: /data budget): 0.5 GB a read at n 600 with 4 opps
        u = shutil.disk_usage("/data")
        if u.free / 1e9 < KEEP_MIN_FREE_GB:
            print(f"inforead: /data has under {KEEP_MIN_FREE_GB:.0f} GB free: replays NOT kept for this read (--rounds R stays cheap)", file=sys.stderr)
            a = [x for x in a if x not in ("--keep-replays", "--fight")]
    rounds = int(opt("--rounds", 0))
    if rounds and not (5 <= rounds <= 1999 and opps):
        die("--rounds: 5-1999, with at least one opp (it plays only the CAND v opp and BASE v opp legs)")
    while True:  # 3 Nov: two starts in one second took the same tag and the second crashed
        tag = f"ir{who}_{time.strftime('%d%H%M%S', time.gmtime())}"
        try:
            os.makedirs(f"{INFO}/{tag}")
            break
        except FileExistsError:
            time.sleep(1)
    if mfrom:
        os.makedirs(f"{PANEL_DIR}/{tag}", exist_ok=True)
        shutil.copyfile(f"{PANEL_DIR}/{mfrom}/otf.json", f"{PANEL_DIR}/{tag}/otf.json")  # run() takes the resume path on it
    json.dump(dict(cand=cand, base=base, who=who, opps=opps, n=n, par=int(opt("--par", 8)), second="--second" in a,
                   changed=cn, changed_max=int(opt("--changed-max", 40000)), wfams=opt("--wfams", None), draft_changed=dc, draft_max=int(opt("--draft-max", 40000)), probe_from=opt("--probe-from", None), base_has=base_has, maps_from=mfrom, keep="--keep-replays" in a or "--fight" in a or bool(rounds), rounds=rounds, fight="--fight" in a,
                   fight_readers=[os.path.abspath(x) for x in opt("--fight-readers", "").split(",") if x],
                   engine=opt("--engine", ""), vs_live=vs_live, flip_base=bool(flip.get("TRUNK")) and not vs_live,
                   made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(f"{INFO}/{tag}/cmd.json", "w"))
    start(tag, "--fg" in a)


if __name__ == "__main__":
    main()
