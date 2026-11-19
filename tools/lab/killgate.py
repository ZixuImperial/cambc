#!/usr/bin/env python3
"""killgate: a staged early-kill screen, so weak ideas die in minutes instead of 30-90 min. KILLGATE tool agent, 1 Nov
(owner: "speed up iterations"). Run it FIRST on every candidate; stop at a KILL.

usage: python3 -I tools/lab/killgate.py CAND BASE TAG [--trigger LIST] [--mech CMD] [--lane behaviour|fix]
                                        [--cached] [--a-maps 100] [--first 800] [--chunk 400] [--no-b] [--no-a]
                                        [--exclude LIST] [--within LIST]
  CAND, BASE  bots under bots/ (BASE = the live bot the candidate is built on, so a later shipcheck BIG leg reuses the games).
  TAG         [A-Za-z0-9]+; condab runs kg<TAG>a (stage A) and kg<TAG>b (stage B); state, log and verdict in
              /data/USER/st/kg/<TAG>/ (verdict.txt = the one-screen result). Re-running a TAG resumes: every game already in
              the index (tools/lab/abindex.py, same two sources and map) is reused, never replayed.
  --trigger   maps where the change fires (one name per line, hyphenated map-file names): stage A plays them (a seeded sample of
              100 if longer); without it stage A plays the first 100 maps of stage B's order (a family-stratified BIG sample).
  --mech CMD  mechanism bar: stage A then runs with KEEP=1 and CMD runs (shlex-split, no shell, cwd = the repo) with
              {KEEPDIR} {CAND} {BASE} {TRIGGER} {MAPS} replaced (as shipcheck's MECHCMD, plus {MAPS} = stage A's map list).
              Its LAST line that starts with PASS or FAIL (after optional spaces / 'mech:') is the bar; FAIL = KILL. No such
              line = MECH UNREAD (reported, no kill).
  --lane fix  bug-fix lane: no futility kill; KILL only on harm (score + 2.5 se < 0.49 at >= 800 maps, shipcheck's
              SC_LH_EARLY bar); NOHARM early at >= 1200 maps once score - 2.5 se >= 0.49; PROMOTE as the behaviour lane.
  --cached    play nothing: evaluate both stages on the games the index already has (re-reads, validation, dry runs).
  --no-b      stage A only.  --no-a: stage B only.
  --exclude   maps left out of stage B's BIG order (armfarm.py: an arm picked on its selection maps is confirmed on the rest;
              the boundaries then use t = maps / the remaining set's size).
  --within    only BIG maps in LIST (re-reads of runs made on an older BIG, e.g. bank v2 only).
  Env: KG_PRIO (condab priority, default 0), KG_TIMEOUT (s per condab run, default 3600).

STAGE A (minutes, ~200 games): CAND vs BASE, both seats, on 100 maps (trigger or BIG sample), OTF=0.
  changed share = maps whose two seats' games differ (condab's definition; an unchanged map scores exactly 0.5).
  KILL if: any CAND bot fault; no trigger and changed share < 1%; a trigger list with 0 maps changed (VACUOUS); the mechanism
  bar FAILs; or the score on CHANGED maps has 95% CI upper < 0.47 (>= 8 changed maps).
STAGE B (sequential BIG): CAND vs BASE on the 2,621 BIG maps (condab 'all' 636 + BIGSET=ladderw 2000, as shipcheck's BIG leg)
  in a family-stratified order seeded by the two source hashes (stage A's sample = its first 100 maps, so they are reused).
  Looks after 800 maps, then every 400, then all 2,621; each look = one condab run on the cumulative list (only new maps play).
  z = (won both - lost both) / sqrt(won both + lost both) (LOS = Phi(z), abstat's LOS); t = maps / 2621.
  PROMOTE when z >= 1.75 / sqrt(t)  (O'Brien-Fleming boundary: LOS > 95% at the full set, stricter before; a null promotes ~5%).
  Behaviour lane (owner 3 Nov ~03:20Z, after audit b935): BIG is no-harm only. KILL at >= 800 maps when score + 2.5 se < 0.495 (no-harm out of
  reach), and at the full set when the point is < 0.495; otherwise FLAT or PROMOTE, and the pooled BIG + fresh read (gate.py, shipcheck.py) decides.
  The old LOS < 10% and conditional-power kills are gone: they acted as a second superiority bar.
    true 0.510: PROMOTE 52%, KILL 33%     true 0.515: PROMOTE 81%, KILL 12% (~1740)   true 0.520: PROMOTE 95%, KILL 3%
  (the full 2621-map BIG read at z 1.96 ships a true 0.515 ~76% of the time.) The test adapts to the change size: a data-flag
  candidate that changes 5% of maps has a small se and decides on fewer maps.
A PROMOTE is not a ship: arm a SHIPCHECK (BIG=2000 BIGSET=ladderw reuses every stage B game when BASE is live).
"""
import fcntl
import hashlib
import json
import math
import os
import random
import re
import shlex
import signal
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
LAB = os.path.join(REPO, "tools/lab")
KG = "/data/USER/st/kg"
ABL = "/data/USER/abl"
N_FULL = 2621  # BIGSET=ladderw; main() resets it to the BIG list's real size (ladderw_nh: about 2,105)
sys.path.insert(0, LAB)
import abindex  # noqa: E402

PROMOTE_C = 1.75     # OBF constant: z >= C / sqrt(t)
KILL_LOS = 0.10      # spec: KILL at LOS < 10% after >= KILL_MIN maps
KILL_MIN = 800
CP_MIN = 0.02        # futility: conditional power (current trend) of reaching LOS >= 95% at the full set
CP_TARGET = 1.645
A_CHANGED_MIN = 0.01
A_HI_KILL = 0.47
A_MIN_CHANGED = 8
FIX_HARM, FIX_Z = 0.49, 2.5
BEH_NOHARM = 0.495  # behaviour lane's BIG no-harm point (owner 3 Nov)


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ---------------------------------------------------------------- maps
def big_maps():
    import condab
    import ladderw
    os.environ.setdefault("BIGSET", ladderw.default_bigset())  # condab's set_maps and every condab leg read it
    ms = condab.set_maps("all")
    have = set(ms)
    ms += [m for m in ladderw.bank_list(2000) if m not in have]
    mp = abindex.maps()
    return [m for m in ms if m in mp]


def strat_order(maps, seed):
    """Family-stratified random order: every prefix keeps the families' shares (largest deficit first)."""
    rng = random.Random(seed)
    fam = {}
    for m in sorted(maps):
        fam.setdefault(abindex.map_set(m) or "other", []).append(m)
    for v in fam.values():
        rng.shuffle(v)
    n, out, taken = len(maps), [], {k: 0 for k in fam}
    live = dict(fam)
    while len(out) < n:
        k = max(live, key=lambda f: (len(fam[f]) * (len(out) + 1) / n - taken[f], len(fam[f]), f))
        if taken[k] >= len(fam[k]):
            live.pop(k)
            continue
        out.append(fam[k][taken[k]])
        taken[k] += 1
    return out


def read_list(p):
    return [x.split()[0] for x in open(p) if x.strip() and not x.lstrip().startswith("#")]


# ---------------------------------------------------------------- statistics
def same(g1, g2):
    return (g1["win"], g1.get("rounds"), g1["sa"], g1["sb"]) == (g2["win"], g2.get("rounds"), g2["sa"], g2["sb"])


def pair_rows(hc, hb, maps):
    """{map: dict(s=score of CAND, ch=changed, g1, g2)} for maps with both seats in the index."""
    ix = abindex.Index({hc, hb})
    mp = abindex.maps()
    out = {}
    for m in maps:
        if m not in mp:
            continue
        g1, g2 = ix.games.get((hc, hb, mp[m][0])), ix.games.get((hb, hc, mp[m][0]))
        if g1 and g2:
            out[m] = dict(s=((g1["win"] == "A") + (g2["win"] == "B")) / 2, ch=not same(g1, g2), g1=g1, g2=g2)
    return out


def summ(rows):
    s = [r["s"] for r in rows]
    n = len(s)
    if not n:
        return dict(n=0, w=0, l=0, mean=0.5, se=0.0, lo=0.5, hi=0.5, z=0.0, los=0.5)
    w, l = s.count(1.0), s.count(0.0)
    mean = sum(s) / n
    var = sum((v - mean) ** 2 for v in s) / (n - 1) if n > 1 else 0.25
    se = math.sqrt(var / n)
    z = (w - l) / math.sqrt(w + l) if w + l else 0.0
    return dict(n=n, w=w, l=l, mean=mean, se=se, lo=mean - 1.96 * se, hi=mean + 1.96 * se, z=z, los=phi(z))


def side_counts(rows):
    """CAND / BASE faults, capped fuel exhaustions (5 per side per game, shipcheck's FUEL rule), wards over the rows' games."""
    c = dict(cf=0, bf=0, cfuel=0, bfuel=0, cw=0, bw=0, games=0)
    for r in rows:
        for g, cs, bs in ((r["g1"], "sa", "sb"), (r["g2"], "sb", "sa")):
            c["games"] += 1
            c["cf"] += int(g[cs].get("faults", 0))
            c["bf"] += int(g[bs].get("faults", 0))
            c["cfuel"] += min(5, int(g[cs].get("fuel", 0)))
            c["bfuel"] += min(5, int(g[bs].get("fuel", 0)))
            c["cw"] += int(g[cs].get("wards", 0))
            c["bw"] += int(g[bs].get("wards", 0))
    return c


def fmt(st):
    return (f"{st['n']} maps: won both {st['w']}, lost both {st['l']} | score {st['mean']:.4f} "
            f"[{st['lo']:.4f}, {st['hi']:.4f}] LOS {st['los'] * 100:.1f}%")


def look_rule(st, lane, total=N_FULL):
    """-> (decision or None, reason) at one stage B look; total = the size of the full stage B set."""
    n, z = st["n"], st["z"]
    t = min(1.0, n / total)
    if n == 0:
        return None, "no maps"
    pb = PROMOTE_C / math.sqrt(t)
    if z >= pb:
        return "PROMOTE", f"z {z:.2f} >= {pb:.2f} (OBF {PROMOTE_C}/sqrt(t), t {t:.2f})"
    if lane == "fix":
        if n >= KILL_MIN and st["mean"] + FIX_Z * st["se"] < FIX_HARM:
            return "KILL", f"harm: score + {FIX_Z} se = {st['mean'] + FIX_Z * st['se']:.4f} < {FIX_HARM}"
        if n >= 1200 and st["mean"] - FIX_Z * st["se"] >= FIX_HARM:
            return "NOHARM", f"score - {FIX_Z} se = {st['mean'] - FIX_Z * st['se']:.4f} >= {FIX_HARM}"
        if t >= 1:
            ok = st["mean"] >= 0.49 and st["hi"] >= 0.50
            return ("NOHARM" if ok else "KILL"), f"full set: point {st['mean']:.4f} (>= 0.49) CI upper {st['hi']:.4f} (>= 0.50)"
        return None, f"z {z:.2f} < {pb:.2f}; fix lane: no harm verdict yet"
    # behaviour (owner 3 Nov, POOLED DECIDES): BIG is no-harm only (point >= 0.495); the pooled BIG + fresh read decides, so stop only a BIG that
    # cannot reach no-harm. The LOS < 10% and futility kills are gone: they acted as a second superiority bar (audit b935: true +1% passed 61%).
    if n >= KILL_MIN and st["mean"] + FIX_Z * st["se"] < BEH_NOHARM:
        return "KILL", f"no-harm out of reach: score + {FIX_Z} se = {st['mean'] + FIX_Z * st['se']:.4f} < {BEH_NOHARM}"
    if t >= 1:
        return ("FLAT" if st["mean"] >= BEH_NOHARM else "KILL"), f"full set: point {st['mean']:.4f} (no-harm >= {BEH_NOHARM}); z {z:.2f}"
    return None, f"z {z:.2f} < {pb:.2f}"


# ---------------------------------------------------------------- runner
class KillGate:
    def __init__(self, cand, base, tag, opts):
        self.cand, self.base, self.tag, self.o = cand, base, tag, opts
        self.dir = os.path.join(KG, tag)
        os.makedirs(self.dir, exist_ok=True)
        self.t0 = time.time()
        self.log = open(os.path.join(self.dir, "log.txt"), "a")
        self.hc, self.hb = abindex.bot_hash(cand), abindex.bot_hash(base)
        if self.hc == self.hb:
            sys.exit(f"{cand} and {base} have the same source ({self.hc})")
        self.played = 0
        self.used = set()  # maps the decision read
        self.screen = []  # verdict lines
        self.proc = None

    def say(self, s):
        line = f"{time.strftime('%H:%M:%S', time.gmtime())} {s}"
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()

    def condab(self, name, mlist, maps, keep=False):
        """One condab run CAND vs BASE on mlist; returns (games played, games reused, wall s)."""
        before = pair_rows(self.hc, self.hb, maps)
        need = 2 * (len(maps) - len(before))
        if keep:
            need = 2 * len(maps)  # KEEP replays cached games that have no kept replay; upper bound
        if self.o["cached"]:
            self.say(f"--cached: {name} not run ({len(before)} of {len(maps)} maps complete in the index)")
            return 0, 2 * len(before), 0.0
        if not keep and not need:
            self.say(f"{name}: all {len(maps)} maps already in the index (0 games to play)")
            return 0, 2 * len(maps), 0.0
        env = {k: v for k, v in os.environ.items() if k not in (
            "STOP", "STOP_PASS", "STOP_REF", "SET", "SUBSET", "CONDAB_FIRST", "BASE_ND", "KEEP", "CONFIRM", "BIG",
            "BIGSET", "CONDAB_TIMEBOX", "CONDAB_HI_FAIL", "OTF_DIR", "OTF_RULE", "OTF_DOM", "CONDAB_STOPFILE")}
        env.update(OTF="0", CONDAB_PRIO=os.environ.get("KG_PRIO", "0"), CONDAB_TIMEOUT=os.environ.get("KG_TIMEOUT", "3600"))
        if keep:
            env["KEEP"] = "1"
        t = time.time()
        lg = open(os.path.join(self.dir, f"{name}.condab.log"), "a")
        self.say(f"{name}: condab on {len(maps)} maps ({len(before)} complete in the index){' KEEP=1' if keep else ''}")
        self.proc = subprocess.Popen(["nice", "-n", "10", "sh", os.path.join(LAB, "condab.sh"), self.cand, self.base, name,
                                      mlist], cwd=REPO, env=env, stdout=lg, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        rc = self.proc.wait()
        self.proc = None
        wall = time.time() - t
        after = pair_rows(self.hc, self.hb, maps)
        pl = 2 * (len(after) - len(before)) if not keep else 2 * len(after)
        self.say(f"{name}: condab exit {rc}, {len(after)} of {len(maps)} maps complete, {wall / 60:.1f} min")
        return pl, 2 * len(after) - pl, wall

    # -------------------------------------------------- stage A
    def stage_a(self, order):
        o = self.o
        trig = o["trigger"]
        if trig:
            tm = [m for m in read_list(trig) if m in abindex.maps()]
            miss = len(read_list(trig)) - len(tm)
            if miss:
                self.say(f"!! {miss} trigger maps are not installed map files (hyphenated names?) and are skipped")
            if len(tm) > o["a_maps"]:
                tm = sorted(random.Random(self.hc + self.hb).sample(tm, o["a_maps"]))
            maps, src = tm, f"trigger list {trig} ({len(tm)} maps)"
        else:
            maps, src = order[:o["a_maps"]], f"stratified BIG sample (first {o['a_maps']} of stage B's order)"
        mlist = os.path.join(self.dir, "stageA.maps")
        open(mlist, "w").write("".join(m + "\n" for m in maps))
        ta = time.time()
        pl, ru, wall = self.condab(f"kg{self.tag}a", mlist, maps, keep=bool(o["mech"]))
        self.played += pl
        self.used |= set(maps)
        rows = pair_rows(self.hc, self.hb, maps)
        L = [f"STAGE A: {src}; played {pl} games, reused {ru}, wall {(time.time() - ta) / 60:.1f} min"]
        kill = []
        if len(rows) < max(1, 0.5 * len(maps)):
            L.append(f"  only {len(rows)} of {len(maps)} maps complete: condab failed? see {self.dir}/kg{self.tag}a.condab.log")
            self.screen += L
            return "ERROR", L
        st = summ(rows.values())
        ch = [r for r in rows.values() if r["ch"]]
        share = len(ch) / len(rows)
        sc = side_counts(rows.values())
        L.append(f"  all       {fmt(st)}")
        L.append(f"  changed   {len(ch)} of {len(rows)} maps ({share * 100:.1f}%)")
        if ch:
            cs = summ(ch)
            L.append(f"  on changed maps: score {cs['mean']:.4f} [{cs['lo']:.4f}, {cs['hi']:.4f}] (n {cs['n']})")
            if cs["n"] >= A_MIN_CHANGED and cs["hi"] < A_HI_KILL:
                kill.append(f"changed-map score CI upper {cs['hi']:.4f} < {A_HI_KILL}")
        L.append(f"  faults CAND {sc['cf']} BASE {sc['bf']} | fuel exh (cap 5) CAND {sc['cfuel']} BASE {sc['bfuel']} | "
                 f"wards CAND {sc['cw']} BASE {sc['bw']} ({sc['games']} games)")
        if sc["cf"]:
            kill.append(f"CAND bot faults {sc['cf']}")
        if sc["cw"] == 0:
            kill.append("CAND placed no wards")
        if trig and not ch:
            kill.append("VACUOUS: 0 trigger maps changed")
        if not trig and share < A_CHANGED_MIN:
            kill.append(f"changed share {share * 100:.1f}% < {A_CHANGED_MIN * 100:.0f}% with no trigger list")
        if o["mech"]:
            res = self.mech(mlist)
            L.append(f"  mechanism: {res}")
            if res.startswith("FAIL"):
                kill.append(f"mechanism bar {res}")
        if kill:
            L.append("  KILL: " + "; ".join(kill))
        else:
            L.append("  stage A passed")
        self.screen += L
        return ("KILL" if kill else "PASS"), L

    def mech(self, mlist):
        import glob
        kd = sorted(glob.glob(os.path.join(ABL, f"cq_kg{self.tag}a_*", "rep")), key=os.path.getmtime)
        sub = {"{KEEPDIR}": os.path.dirname(kd[-1]) if kd else "", "{CAND}": self.cand, "{BASE}": self.base,
               "{TRIGGER}": self.o["trigger"] or "", "{MAPS}": mlist}
        try:
            argv = shlex.split(self.o["mech"])
        except ValueError as e:
            return f"UNREAD (cannot split the command: {e})"
        argv = [a if a not in sub else sub[a] for a in argv]
        argv = [re.sub(r"\{(KEEPDIR|CAND|BASE|TRIGGER|MAPS)\}", lambda m: sub["{" + m.group(1) + "}"], a) for a in argv]
        self.say("mech: " + " ".join(shlex.quote(a) for a in argv))
        try:
            r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=3600)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"UNREAD (command failed: {e})"
        out = (r.stdout + r.stderr).rstrip()
        open(os.path.join(self.dir, "mech.out"), "w").write(out + "\n")
        hits = [ln.strip() for ln in out.splitlines() if re.match(r"\s*(mech:\s*)?(PASS|FAIL)\b", ln)]
        if not hits:
            return f"UNREAD (exit {r.returncode}, no PASS/FAIL line; output in {self.dir}/mech.out)"
        h = re.sub(r"^mech:\s*", "", hits[-1])
        return h[:160]

    # -------------------------------------------------- stage B
    def stage_b(self, order):
        o = self.o
        looks = list(range(o["first"], len(order), o["chunk"])) + [len(order)]
        L = [f"STAGE B: BIG {len(order)} maps, looks at {', '.join(map(str, looks))} "
             f"({'fix' if o['lane'] == 'fix' else 'behaviour'} lane)"]
        L.append(f"  {'maps':>5s} {'score [95% CI]':26s} {'LOS':>6s} {'z':>5s} {'changed':>8s} {'played':>6s} {'min':>5s}  rule")
        dec, why = None, ""
        for n in looks:
            maps = order[:n]
            mlist = os.path.join(self.dir, f"stageB_{n}.maps")
            open(mlist, "w").write("".join(m + "\n" for m in maps))
            tl = time.time()
            pl, ru, wall = self.condab(f"kg{self.tag}b", mlist, maps)
            self.played += pl
            self.used |= set(maps)
            rows = pair_rows(self.hc, self.hb, maps)
            st = summ(rows.values())
            nch = sum(r["ch"] for r in rows.values())
            if self.o["cached"] and len(rows) < n:
                L.append(f"  {n:5d} only {len(rows)} complete in the index: --cached stops here "
                         f"(would play {2 * (n - len(rows))} more games)")
                dec, why = "INCOMPLETE", f"{len(rows)} of {n} maps cached"
                break
            dec, why = look_rule(st, o["lane"], len(order))
            L.append(f"  {st['n']:5d} {st['mean']:.4f} [{st['lo']:.4f}, {st['hi']:.4f}]  {st['los'] * 100:5.1f}% "
                     f"{st['z']:5.2f} {nch / max(1, st['n']) * 100:7.1f}% {pl:6d} {(time.time() - tl) / 60:5.1f}  {why}")
            self.say(L[-1].strip())
            if len(rows) < 0.9 * n:
                dec, why = "ERROR", f"only {len(rows)} of {n} maps complete (condab failures?)"
                break
            if dec:
                break
        sc = side_counts(rows.values())
        L.append(f"  faults CAND {sc['cf']} BASE {sc['bf']} | fuel exh (cap 5) CAND {sc['cfuel']} BASE {sc['bfuel']} "
                 f"({sc['games']} games)")
        self.screen += L
        return dec, why

    def run(self):
        o = self.o
        excl = set(read_list(o["exclude"])) if o["exclude"] else set()
        within = set(read_list(o["within"])) if o["within"] else None
        order = strat_order([m for m in big_maps() if m not in excl and (within is None or m in within)],
                            "kg:" + self.hc + ":" + self.hb)
        if within is not None:
            self.say(f"--within: the BIG order is cut to {len(order)} maps of {o['within']}")
        if excl:
            self.say(f"--exclude: {len(excl)} maps left out of the BIG order")
        open(os.path.join(self.dir, "order.maps"), "w").write("".join(m + "\n" for m in order))
        self.say(f"killgate {self.tag}: {self.cand}@{self.hc} vs {self.base}@{self.hb}, BIG {len(order)} maps")
        head = [f"KILLGATE {self.tag}: {self.cand}@{self.hc} vs {self.base}@{self.hb}  "
                f"({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(self.t0))}, lane {o['lane']})", ""]
        va = "PASS" if o["no_a"] else self.stage_a(order)[0]
        if o["no_a"]:
            self.screen.append("STAGE A: skipped (--no-a)")
        verdict, why = va, "stage A"
        if va == "PASS" and not o["no_b"]:
            self.screen.append("")
            verdict, why = self.stage_b(order)
            verdict = verdict or "FLAT"
        elif va == "PASS":
            verdict, why = "PASS-A", "stage A only (--no-b)"
        wall = time.time() - self.t0
        used = 2 * len(pair_rows(self.hc, self.hb, sorted(self.used)))
        reused = max(0, used - self.played)
        nxt = {"KILL": "stop here: drop the idea (or fix the mechanism and re-run with a new TAG)",
               "PROMOTE": "arm a SHIPCHECK on the current live base (BIG=2000 BIGSET=ladderw reuses these games when BASE is live)",
               "NOHARM": "fix lane: arm a SHIPCHECK LANE=fix",
               "FLAT": "no decision on the full BIG set: do not ship on it (bundle or drop)",
               "PASS-A": "stage A passed; run stage B (drop --no-b)",
               "ERROR": f"see {self.dir}/log.txt and the condab logs",
               "INCOMPLETE": "--cached: not enough cached games; re-run without --cached"}.get(verdict, "")
        tail = ["", f"VERDICT: {verdict}  ({why})", f"next: {nxt}",
                f"games: {used} read by the decision ({len(self.used)} maps x 2 seats): played {self.played}, reused {reused}; wall {wall / 60:.1f} min",
                f"files: {self.dir}/ (verdict.txt, log.txt, order.maps, stage*.maps, *.condab.log)"]
        txt = "\n".join(head + self.screen + tail) + "\n"
        tmp = os.path.join(self.dir, "verdict.txt.new")
        open(tmp, "w").write(txt)
        os.replace(tmp, os.path.join(self.dir, "verdict.txt"))
        json.dump(dict(cand=self.cand, base=self.base, hc=self.hc, hb=self.hb, verdict=verdict, why=why,
                       played=self.played, used=used, reused=reused, wall_s=round(wall), at=time.time()),
                  open(os.path.join(self.dir, "state.json"), "w"))
        print("\n" + txt)
        return verdict


def main():
    a = sys.argv[1:]
    if len(a) < 3 or a[0].startswith("-"):
        sys.exit(__doc__)
    cand, base, tag = a[0], a[1], a[2]
    if not re.fullmatch(r"[A-Za-z0-9]+", tag):
        sys.exit("TAG must be [A-Za-z0-9]+")
    for b in (cand, base):
        if not os.path.isdir(os.path.join(REPO, "bots", b, "src")):
            sys.exit(f"no bots/{b}/src")

    def opt(k, d=None):
        return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d
    o = dict(trigger=opt("--trigger"), mech=opt("--mech"), lane=opt("--lane", "behaviour"), cached="--cached" in a,
             a_maps=int(opt("--a-maps", 100)), first=int(opt("--first", KILL_MIN)), chunk=int(opt("--chunk", 400)),
             no_b="--no-b" in a, no_a="--no-a" in a, exclude=opt("--exclude"),
             within=opt("--within"))
    if o["lane"] not in ("behaviour", "fix"):
        sys.exit("--lane behaviour|fix")
    for k in ("exclude", "within"):
        if o[k] and not os.path.isfile(o[k]):
            sys.exit(f"no {k} list {o[k]}")
    if o["trigger"] and not os.path.isfile(o["trigger"]):
        sys.exit(f"no trigger list {o['trigger']}")
    os.makedirs(os.path.join(KG, tag), exist_ok=True)
    lk = open(os.path.join(KG, tag, "lock"), "a")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(f"killgate {tag} is already running")
    try:
        os.nice(10)
    except OSError:
        pass
    kg = KillGate(cand, base, tag, o)

    def term(sig, frm):
        if kg.proc and kg.proc.poll() is None:
            try:
                os.killpg(kg.proc.pid, signal.SIGTERM)
            except OSError:
                pass
        sys.exit(1)
    signal.signal(signal.SIGTERM, term)
    signal.signal(signal.SIGINT, term)
    kg.run()


if __name__ == "__main__":
    main()
