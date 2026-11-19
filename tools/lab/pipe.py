#!/usr/bin/env python3
"""pipe.py: one page of every active spec/idea and where it stands (read-only; writes only stdout). Tool Builder, 10 Nov.

  python3 -I tools/lab/pipe.py [--idea CODE[,CODE]] [--since HOURS] [--json] [--all]

Stages (pipeline order): spec posted, Step 0 running, armed, shipcheck running, PASS, FAIL, closed, shipped.
Evidence, merged per idea code (HFX, FAF3, ...; slugs nova_bNNNN_slug and FLAG_BITS map onto codes):
  condor-work/reports/builder_queue.md (bq)   Builder/analyst log, sentence-level keywords (PREREG, ARMED, FAIL, CLOSED, SHIP vN)
  bq/armq.txt, armq.log, armq.failed (armq)   waiting rows, arming / ARMED / drop-armed / arm failures
  bq/shipwatch.log + bq/shipcheck_TAG.txt (sw) queue / start / ended, OVERALL + first leg
  running processes (proc)                    shipcheck.py (shipcheck running), dgkit.py run / cqbatch.py --debug (Step 0 running)
  bq/failure_chains.md (chains), bq/pending_reads.txt (pend: stalls only), condor-work/reports/idea_queue.md (iq: fallback)
The newest event decides the stage; a live process outranks a log line. An idea is listed only when some event set
a stage within --since (default 48 h); by default log-only rows past HIDE_AFTER (closed/shipped 6 h, FAIL/PASS/Step 0 12 h, spec 24 h, armed 8 h) are hidden; --all or --idea shows them. --idea matches a code or a code prefix (FAF -> FAF1, FAF3).
  python3 -I tools/lab/pipe.py handoff [--alarm] [--hours H] [--json]
HANDOFF AUDIT (Coordinator 10 Nov): every analysts/spec_*.md modified in --hours (24) -> its codes (file name, title code, XXX_BITS in
the first 12 lines) and any downstream entry posted after it (post time = earliest builder_queue mention of the spec, else mtime):
bots/ dir, st/b1NNN prereg.md or file names, builder_queue PREREG/ARMED/FAIL/PASS/ship/closed/agent sentence, armq.txt/.log/.failed,
pilot_top.txt, live processes (cmdline + cwd), pilot queue/claimed item names, abl run dirs < 3 h (bots.txt), an agent dir whose agent
has queue items or processes (batch). NONE rows first, oldest first. --alarm writes bq/handoff.alarm when a NONE spec is > 60 min old
(deletes it when none); healthwatch reads it. Timer: nova-handoff (*:10,40).
STALLS: Step 0 / shipcheck running > 3 h with no output newer than 3 h, armed lines waiting > 2 h, PENDING reads > 24 h.
"""
import json, os, re, sys, time
from datetime import datetime, timezone

ROOT = "/homes/zw4424/cambc"
Q = "/data/zw4424/st/bq"
BQ = os.path.join(ROOT, "condor-work/reports/builder_queue.md")
IQ = os.path.join(ROOT, "condor-work/reports/idea_queue.md")
STAGES = ["spec posted", "Step 0 running", "armed", "shipcheck running", "PASS", "FAIL", "closed", "shipped"]
RANK = {s: i for i, s in enumerate(STAGES)}
# default view (no --all / --idea): a log-only row whose deciding event is older than this many hours is hidden (counted)
HIDE_AFTER = {"closed": 6, "shipped": 6, "FAIL": 12, "PASS": 12, "Step 0 running": 12, "spec posted": 24, "armed": 8}

TS_RE = re.compile(r"(\d{4}-\d\d-\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?Z")
CODE_RE = re.compile(r"(?<![A-Za-z0-9_&/-])([A-Z]{2,5}\d?)(?![A-Za-z0-9&])")
BITS_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})_BITS\b")
SPEC_RE = re.compile(r"\bspec_([a-z]{2,5}\d?)_\d{4}")
SLUGBOT_RE = re.compile(r"\bnova_b\d+_([a-z][a-z0-9]*)")
SLUGTOK_RE = re.compile(r"(?<![A-Za-z0-9_./-])([a-z]{2,5}\d[a-z0-9]*)(?![A-Za-z0-9_])")
AGENT_RE = re.compile(r"(?<![A-Za-z0-9_])b(1\d{3})(?![0-9])")
STOP = set("""PASS BIG GO CI TB ARMED CAND FAIL FAILS FAILED LOS RC HP SE LIVE THE FOR OWNER KILL SHIP OK VV UTC SPSA AND EXT
FIGHT SEQ HAND NO FLEE BUG NOT NEW MODE GR BAR NEEDS TICK INT ENTRY SBG FAILS MAL QUEUE NEXT MISS MAP DENSE CHECK MB TEAM
SLOT CLI GB ETA CALM KP DONE PENDING CLOSED PREREG ALONE REVISED INFRA DRAFT FIX TOP QUEUED WITHDRAWN ADAPTATION CORRECTION
NULL PRIO MAX MIN ONESRC DG API JSON CXE ALL ONE TWO BUT OR IF IS IN ON AT TO OF BY AN AS UP US WE ME IT BE DO SO NA ID
YES NOW ANY OFF SET RUN END WIN LOSS WINS GAP AREA ROW ROWS LEAD DATA PRE POST STOP HOLD HELD KEEP SKIP LOW HIGH MID
SHIPPED REOPENED NOTE TODO WAIT IDLE READ CELL ARM ARMS FROM WITH THEN WHEN ONLY ALSO BOTH NONE EACH SAME OWN FULL HALF
TIME GOLD GEMS DEAD DIED RISK PHASE STEP AUTO FOE FOES OUR HER HIS SHE HE THEY THEM WHY WHAT HOW WHO CAP NEAR FAR BASE
FUEL CPU RAM OOM SSH TSV PID HTTP URL HTML MD PY CPP WASM VS CC WAS ARE HAS HAD CAN MAY MUST WILL ROOT FILE DIR GATE
CORRECT REFUTED VERIFIED POSS DONE NB FYI ASAP EOD NOTE FINAL CLOSE CLEAN CONFIRMED BUILT FD1 KILLED NOGO REPLAY ISSUE AMEND""".split())
STOP_SLUG = {"cap", "dg", "top", "pt", "fed", "rk", "cm", "ms", "mb", "gb", "px", "cs", "dr", "ft", "gr", "id", "bq", "lab", "max", "min", "run", "set", "log", "maps", "rng", "nov", "oct", "seed", "sec", "dash"}

SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Za-z(])")
ARROW_SPLIT = re.compile(r"\s+(?:->|=>)\s+")
K_SHIP = re.compile(r"\bSHIP v\d+\b|\bSHIPPED\b|\bv\d{3} = ")
K_CLOSED = re.compile(r"\bKILLED\b|\bNO GO\b|\bNOT BUILT\b|Step 0 KILL\b|\bsuperseded\b|-> fuelbank|failed-positive bank|\bbanked\b|bundle-bank|\bCLOSED\b|\bWITHDRAWN\b|\bclosed\b|\bretracted\b|\bdrop-armed\b|\bparked\b|\bPARKED\b")
K_FAIL = re.compile(r"\bFAIL(?:ED|S)?\b")
K_ARMED = re.compile(r"(?<!not )(?<!never )(?<!not re-)\b(?:ARMED|armed|re-armed|arming|Arm(?:ed)?:)\b")
K_PASS = re.compile(r"\bPASS\b")
K_PASS_REAL = re.compile(r"(?:shipcheck|OVERALL|pooled|confirm|BIG|h2h|ended)[^.;]{0,60}\bPASS\b|\bPASS\b[^.;]{0,30}(?:pooled|BIG|shipcheck)")
K_STEP0 = re.compile(r"\bPREREG\b|Step 0[^.;]{0,40}\b(?:running|started|launched|queued|submitted)\b")
K_SPEC = re.compile(r"queue \+=|\bspec_[a-z0-9]+_\d{4}|\bQUEUED\b|FOR THE ACTIVE BUILDER|-> Builder|\bspec\b")


def parse_ts(s):
    m = TS_RE.search(s)
    if not m:
        return None
    d, hh, mm, ss = m.groups()
    try:
        return datetime(int(d[:4]), int(d[5:7]), int(d[8:10]), int(hh), int(mm), int(ss or 0), tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def read_since(path, since, lead_chars=40):
    """lines of PATH from the first line stamped >= since (bisect on byte offsets; lines without a stamp in their first
    LEAD_CHARS inherit the last stamp). Returns [(t, line)]."""
    try:
        f = open(path, "rb")
    except OSError:
        return []
    with f:
        size = os.fstat(f.fileno()).st_size
        lo, hi = 0, size
        while hi - lo > 65536:
            mid = (lo + hi) // 2
            f.seek(mid)
            f.readline()
            t = None
            for _ in range(40):
                ln = f.readline()
                if not ln:
                    break
                t = parse_ts(ln[:200].decode("utf-8", "replace"))
                if t is not None:
                    break
            if t is None or t < since:
                lo = mid
            else:
                hi = mid
        f.seek(lo)
        data = f.read().decode("utf-8", "replace")
    lines = data.split("\n")
    if lo > 0:
        lines = lines[1:]
    out, cur = [], None
    for ln in lines:
        if not ln.strip():
            continue
        t = parse_ts(ln[:lead_chars + 30]) if TS_RE.search(ln[:lead_chars + 30]) else None
        if t is not None:
            cur = t
        if cur is None or cur < since:
            continue
        out.append((cur, ln))
    return out


def tail_bytes(path, n):
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            f.seek(max(0, size - n))
            d = f.read().decode("utf-8", "replace")
            return d.split("\n")[1:] if size > n else d.split("\n")
    except OSError:
        return []


def mtime(p):
    try:
        return os.stat(p).st_mtime
    except OSError:
        return None


class Pipe:
    def __init__(self, since_h):
        self.now = time.time()
        self.since = self.now - since_h * 3600
        self.known = set()      # exact codes seen
        self.known_alpha = set()
        self.slugcodes = {}     # slug -> set(codes) (from armq arming FLAG_BITS)
        self.slugowner = {}
        self.ev = {}            # code -> list of (t, seq, stage|None, owner, text, src, start_t)
        self.seq = 0
        self.stalls = []
        self.hidden = 0

    # ---------- codes ----------
    def learn(self, text):
        for c in CODE_RE.findall(text):
            if c not in STOP:
                self.known.add(c)
        for c in BITS_RE.findall(text):
            self.known.add(c)
        for c in SPEC_RE.findall(text):
            self.known.add(c.upper())

    def finish_learn(self):
        self.known -= STOP
        self.known_alpha = {re.sub(r"\d$", "", c) for c in self.known}

    def slug_code(self, slug):
        if slug in self.slugcodes:
            return set(self.slugcodes[slug])
        m = re.match(r"([a-z]+)(\d?)", slug)
        if not m:
            return set()
        a, d = m.group(1).upper(), m.group(2)
        if len(a) < 2 or (len(a) < 3 and a not in self.known):
            return set()
        if a in self.known:
            return {a}
        if d and a + d in self.known:
            return {a + d}
        if len(a) <= 5 and a in self.known_alpha:
            return {a}
        for k in range(min(len(a), 5) - 1, 2, -1):
            if a[:k] in self.known:
                return {a[:k]}
        return {a} if len(a) <= 5 else set()

    def code_hits(self, text):
        """[(pos, set(codes))] in text order."""
        hits = []
        for m in CODE_RE.finditer(text):
            c = m.group(1)
            if c not in STOP and c in self.known:
                hits.append((m.start(), {c}))
        for m in BITS_RE.finditer(text):
            hits.append((m.start(), {m.group(1)}))
        for m in SPEC_RE.finditer(text):
            hits.append((m.start(), {m.group(1).upper()}))
        for m in SLUGBOT_RE.finditer(text):
            cs = self.slug_code(m.group(1))
            if cs:
                hits.append((m.start(), cs))
        for m in SLUGTOK_RE.finditer(text):
            s = m.group(1)
            a = re.match(r"[a-z]+", s).group(0)
            if a in STOP_SLUG:
                continue
            if s in self.slugcodes or a.upper() in self.known_alpha:
                cs = self.slug_code(s)
                if cs:
                    hits.append((m.start(), cs))
        hits.sort(key=lambda h: h[0])
        return hits

    def codes_in(self, text):
        cs = set()
        for _, c in self.code_hits(text):
            cs |= c
        return cs

    def add(self, code, t, stage, owner, text, src, start_t=None, prio=0):
        self.seq += 1
        self.ev.setdefault(code, []).append((t, prio, self.seq, stage, owner, text, src, start_t))

    # ---------- text logs ----------
    @staticmethod
    def actor(line):
        s = TS_RE.sub("", line)
        s = re.sub(r"^[-|*\s]+", "", s)
        s = re.sub(r"FOR THE ACTIVE BUILDER,?", "", s)
        s = re.sub(r"^\s*\(\s*\)?|\(\s*\)", "", s).strip(" -|:,")
        m = re.match(r"\(([A-Z][A-Za-z ]{1,20})\)", s)
        if m:
            return m.group(1)
        a = re.match(r"((?:[A-Z][A-Za-z]+)(?: [A-Z][a-z]+){0,2})", s)
        r = a.group(1) if a else "?"
        if r.startswith("SHIP") or r.startswith("Builder"):
            return "Builder"
        return {"Rule Checker": "RC", "Tool Builder": "TB", "Prism Improver": "Prism Impr"}.get(r, r)

    STAGE_KEYS = [("shipped", K_SHIP), ("closed", K_CLOSED), ("FAIL", K_FAIL), ("armed", K_ARMED), ("PASS", K_PASS),
                  ("Step 0 running", K_STEP0), ("spec posted", K_SPEC)]

    def clause_stage(self, cl):
        """(stage, keyword position) for one clause, or (None, None)."""
        for st, rx in self.STAGE_KEYS:
            m = rx.search(cl)
            if not m:
                continue
            if st == "PASS" and not K_PASS_REAL.search(cl):
                continue
            return st, m.start()
        return None, None

    def parse_text(self, rows, src):
        """each sentence splits at '->' into clauses; a clause's stage goes to its subject: the code mentioned nearest
        before the keyword, else the first one after it, else (arrow clauses only) the previous clause's subject.
        Other codes in the line are mentions only (no stage)."""
        for t, line in rows:
            body = re.sub(r"^\s*[-|*]\s*", "", line)
            ag = AGENT_RE.search(body)
            line_owner = "b" + ag.group(1) if ag else self.actor(body)
            txt = TS_RE.sub("", body).strip(" -|:()")
            for sent in SENT_SPLIT.split(body):
                subj = set()
                for cl in ARROW_SPLIT.split(sent):
                    hits = self.code_hits(cl)
                    st, p = self.clause_stage(cl)
                    if st:
                        before = [h for h in hits if h[0] < p]
                        after = [h for h in hits if h[0] >= p]
                        cs = before[-1][1] if before else after[0][1] if after else subj
                        if cs:
                            subj = cs
                        ag2 = AGENT_RE.search(cl) or AGENT_RE.search(sent)
                        owner = "b" + ag2.group(1) if ag2 else line_owner
                        stxt = TS_RE.sub("", sent).strip(" -|:()")
                        if len(stxt) < 40:
                            stxt = txt
                        for c in cs:
                            self.add(c, t, st, owner, stxt, src)
                    elif hits:
                        subj = hits[0][1]
                    for _, cs2 in hits:
                        for c in cs2:
                            self.add(c, t, None, line_owner, txt, src)

    # ---------- sources ----------
    def load(self):
        bq = read_since(BQ, self.since)
        ch = read_since(os.path.join(Q, "failure_chains.md"), self.since)
        sw = read_since(os.path.join(Q, "shipwatch.log"), self.since)
        al = read_since(os.path.join(Q, "armq.log"), self.since)
        for _, l in bq:
            self.learn(l)
        for _, l in ch:
            self.learn(l)
        # armq arming lines: slug -> codes (FLAG_BITS) and owner (donor bNNNN)
        arming = []
        for t, l in al:
            m = re.search(r"arming: (\S+) (.*?) (fix|behaviour|draft|param)\b.*--name (\S+)", l)
            if m:
                donor, flips, lane, slug = m.groups()
                cs = set(BITS_RE.findall(flips))
                for c in cs:
                    self.known.add(c)
                if cs:
                    self.slugcodes[slug] = cs
                ag = AGENT_RE.search(donor.replace("nova_b", "nova_ b"))
                self.slugowner[slug] = "b" + ag.group(1) if ag else "armq"
                arming.append((t, slug, l))
        self.finish_learn()
        self.parse_text(bq, "bq")
        self.parse_text(ch, "chains")
        # armq.log events
        for t, slug, l in arming:
            for c in self.slug_code(slug):
                self.add(c, t, "armed", self.slugowner.get(slug, "armq"), "arming " + slug + " (" + re.sub(r".*arming: \S+ ", "", l)[:70] + ")", "armq")
        for t, l in al:
            m = re.search(r"rc 0: ARMED nova_b\d+_(\S+)", l)
            if m:
                s = m.group(1)
                for c in self.slug_code(s):
                    self.add(c, t, "armed", self.slugowner.get(re.sub(r"(?<=\d)[a-z]$", "", s), self.slugowner.get(s, "armq")), "ARMED nova_b..._" + s, "armq")
            m = re.search(r"drop-armed (\S+?):", l)
            if m:
                for c in self.slug_code(m.group(1)):
                    self.add(c, t, "closed", self.slugowner.get(m.group(1), "armq"), "drop-armed " + m.group(1), "armq")
        # armq waiting rows
        try:
            rows = [json.loads(x) for x in open(os.path.join(Q, "armq.txt")) if x.strip()]
        except (OSError, ValueError):
            rows = []
        for r in rows:
            slug, t = r.get("slug", "?"), r.get("t", self.now)
            cs = set(BITS_RE.findall(r.get("flips", ""))) or self.slug_code(slug)
            ag = AGENT_RE.search(r.get("donors", "").replace("nova_b", "nova_ b"))
            for c in cs:
                self.add(c, t, "armed", "b" + ag.group(1) if ag else "armq", "armq waiting: " + slug + " " + r.get("subject", ""), "armq")
            if self.now - t > 7200:
                self.stalls.append(("armed waiting", ",".join(sorted(cs)) or slug, (self.now - t) / 3600, "armq.txt row " + slug + " not merged"))
        for l in tail_bytes(os.path.join(Q, "armq.failed"), 200000):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            t = r.get("t", 0)
            if t < self.since:
                continue
            slug = r.get("slug", "?")
            cs = set(BITS_RE.findall(r.get("flips", ""))) or self.slug_code(slug)
            why = [x for x in r.get("why", "").split("\n") if x.strip()]
            w = next((x for x in why if "FAIL" in x or "conflict" in x), why[-1] if why else "")
            for c in cs:
                self.add(c, t, "FAIL", self.slugowner.get(slug, "armq"), "arm failed " + slug + ": " + w.strip(), "armq")
        # shipwatch
        tagof, queued_first, started = {}, {}, set()
        for t, l in sw:
            m = re.search(r"Z (queue|start|ended|submitted|submit|shipped) (nova_b\d+_(\S+?)):? (.*)", l)
            if not m:
                continue
            kind, bot, slug, rest = m.groups()
            cs = self.slug_code(slug)
            own = self.slugowner.get(slug, "shipwatch")
            if kind == "queue":
                queued_first.setdefault(bot, t)
                for c in cs:
                    self.add(c, t, "armed", own, "waiting " + bot + ": " + rest, "sw")
            elif kind == "start":
                started.add(bot)
                tm = re.search(r"TAG=(\w+)", rest)
                if tm:
                    tagof[bot] = tm.group(1)
                for c in cs:
                    self.add(c, t, "shipcheck running", own, "shipcheck " + bot + " " + rest.split(";")[0], "sw", start_t=t)
            elif kind == "ended":
                st = "PASS" if "PASS" in rest else "FAIL" if "FAIL" in rest else None
                txt = bot + " " + rest + self.sc_summary(tagof.get(bot, re.sub(r"nova_b(\d+)_.*", r"\1", bot)))
                for c in cs:
                    self.add(c, t, st, own, txt, "sw")
            else:
                for c in cs:
                    self.add(c, t, "shipped", own, bot + " " + rest, "sw")
        for bot, t0 in queued_first.items():
            if bot not in started and self.now - t0 > 7200 and not os.path.exists(os.path.join(ROOT, "bots", bot, "SHIPCHECK.dropped")):
                if os.path.exists(os.path.join(ROOT, "bots", bot, "SHIPCHECK")):
                    m = SLUGBOT_RE.search(bot)
                    self.stalls.append(("armed waiting", ",".join(sorted(self.slug_code(m.group(1)))) if m else bot, (self.now - t0) / 3600, bot + " queued, no shipcheck start"))
        self.procs()
        # pending reads: stalls only
        for l in tail_bytes(os.path.join(Q, "pending_reads.txt"), 150000):
            s = l.strip()
            if not s.startswith("PENDING"):
                continue
            t = parse_ts(s)
            if t is None or self.now - t <= 86400:
                continue
            cs = self.codes_in(s)
            self.stalls.append(("PENDING read", ",".join(sorted(cs))[:20] or "?", (self.now - t) / 3600, s[9:110]))
        # idea_queue: fallback for codes with no stage event
        iqm = mtime(IQ)
        if iqm and iqm >= self.since:
            for l in tail_bytes(IQ, 250000):
                m = re.match(r"\s*-\s*(QUEUED|CLOSED|DONE|ARMED)\b\s*(?:b\d+\s*)?(?:on v\d+\s*)?\(?([A-Z]{2,5}\d?)\b", l)
                if m and m.group(2) not in STOP:
                    st = {"QUEUED": "spec posted", "CLOSED": "closed", "DONE": "closed", "ARMED": "armed"}[m.group(1)]
                    c = m.group(2)
                    if not any(e[3] for e in self.ev.get(c, [])):
                        self.add(c, iqm, st, "idea_queue", l.strip()[2:], "iq", prio=-1)

    def sc_summary(self, tag):
        p = os.path.join(Q, "shipcheck_%s.txt" % tag)
        try:
            with open(p, errors="replace") as f:
                lines = f.read(20000).split("\n")
        except OSError:
            return ""
        leg = next((x.strip() for x in lines[3:] if x.strip() and not x.strip().startswith(("OVERALL", "leg "))), "")
        leg = re.sub(r"\s{2,}", " ", leg)
        return " | " + leg[:70]

    def procs(self):
        try:
            btime = next(float(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
        except (OSError, StopIteration):
            btime = 0
        hz = os.sysconf("SC_CLK_TCK")
        dg_dirs, cq = [], []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    a = f.read().decode("utf-8", "replace").split("\0")
            except OSError:
                continue
            if len(a) < 2 or not a[0].startswith("python"):
                continue
            j = " ".join(a)
            kind = "sc" if "shipcheck.py" in j else "dg" if re.search(r"dgkit\.py run", j) else "cq" if "cqbatch.py" in j and "--debug" in j else None
            if not kind:
                continue
            try:
                st = open("/proc/%s/stat" % pid).read().rsplit(")", 1)[1].split()
                t0 = btime + int(st[19]) / hz
                cwd = os.readlink("/proc/%s/cwd" % pid)
            except (OSError, IndexError, ValueError):
                continue
            a = [x for x in a if x]
            if kind == "sc":
                k = next((i for i, x in enumerate(a) if x.endswith("shipcheck.py")), None)
                if k is None or k + 2 >= len(a) + 1:
                    continue
                bot = a[k + 1] if k + 1 < len(a) else "?"
                tag = a[k + 2] if k + 2 < len(a) else "?"
                m = SLUGBOT_RE.search(bot)
                cs = self.slug_code(m.group(1)) if m else set()
                outs = [os.path.join(Q, "shipwatch_%s_%s.out" % (bot, tag)), os.path.join(Q, "shipcheck_%s.txt" % tag)]
                om = max([x for x in map(mtime, outs) if x] or [t0])
                last = ""
                for l in reversed(tail_bytes(outs[0], 3000)):
                    if l.strip():
                        last = re.sub(r"\s{2,}", " ", l.strip())
                        break
                txt = "shipcheck %s TAG %s pid %s, out %.1fh ago: %s" % (bot, tag, pid, (self.now - om) / 3600, last)
                own = self.slugowner.get(m.group(1), "shipwatch") if m else "shipwatch"
                for c in cs or {bot}:
                    self.add(c, self.now, "shipcheck running", own, txt, "proc", start_t=t0, prio=2)
                if self.now - t0 > 3 * 3600 and self.now - om > 3 * 3600:
                    self.stalls.append(("shipcheck stalled", ",".join(sorted(cs)) or bot, (self.now - t0) / 3600, "%s TAG %s: no output for %.1fh" % (bot, tag, (self.now - om) / 3600)))
            elif kind == "dg":
                k = next(i for i, x in enumerate(a) if x.endswith("dgkit.py"))
                rest = a[k + 2:]
                out = rest[-1] if rest else cwd
                out = out if out.startswith("/") else os.path.join(cwd, out)
                dg_dirs.append((pid, t0, rest[0] if rest else "?", out))
            else:
                cq.append((pid, t0, cwd))
        seen_dirs = [d for _, _, _, d in dg_dirs]
        items = list(dg_dirs) + [(pid, t0, None, cwd) for pid, t0, cwd in cq if not any(cwd.startswith(d) for d in seen_dirs)]
        for pid, t0, bot, d in items:
            ag = re.search(r"/st/b(1\d{3})/", d + "/")
            own = "b" + ag.group(1) if ag else (re.search(r"/st/([^/]+)/", d + "/") or [None, "?"])[1]
            cs = set()
            if bot:
                s = re.sub(r"^nova_(?:dg_|ft_|b\d+_)?(?:b\d+)?", "", bot)
                s = re.sub(r"^_", "", s)
                if s and re.match(r"[a-z]{2,5}", s):
                    c = self.slug_code(s)
                    cs |= {x for x in c if x in self.known or x in self.known_alpha}
            for comp in d.split("/")[4:7]:
                m = re.match(r"([a-z]{2,5}\d?)(?:[_.-]|$)", comp)
                if m and m.group(1).upper() in self.known and m.group(1).upper() not in STOP:
                    cs.add(m.group(1).upper())
            om = self.dir_mtime(d) or t0
            txt = "Step 0 %s pid %s in %s, output %.1fh ago" % (bot or "cqbatch --debug", pid, d.replace("/data/zw4424/st/", "st/"), (self.now - om) / 3600)
            label = cs or {"?" + d.replace("/data/zw4424/st/", "")[:18]}
            for c in label:
                self.add(c, self.now, "Step 0 running", own, txt, "proc", start_t=t0, prio=1)
            if self.now - t0 > 3 * 3600 and self.now - om > 3 * 3600:
                self.stalls.append(("Step 0 stalled", ",".join(sorted(label)), (self.now - t0) / 3600, "%s: no output for %.1fh" % (d, (self.now - om) / 3600)))

    @staticmethod
    def dir_mtime(d):
        best = mtime(d)
        try:
            with os.scandir(d) as it:
                for i, e in enumerate(it):
                    if i > 3000:
                        break
                    try:
                        m = e.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    best = m if best is None or m > best else best
        except OSError:
            pass
        return best

    # ---------- merge ----------
    def table(self, filt, show_all=False):
        out = []
        for c, evs in self.ev.items():
            if filt and not any(c == f or c.startswith(f) for f in filt):
                continue
            staged = [e for e in evs if e[3]]
            if not staged:
                continue
            # live processes outrank log lines; otherwise newest wins (ties: later stage)
            procs = [e for e in staged if e[6] == "proc"]
            pool = procs if procs else staged
            best = max(pool, key=lambda e: (e[1], e[0], RANK[e[3]], e[2]))
            t, _, _, stage, owner, text, src, t0 = best
            if not procs and t < self.since:
                continue
            age = (self.now - (t0 if t0 else t)) / 3600
            if not show_all and not filt and src != "proc" and age > HIDE_AFTER.get(stage, 1e9):
                self.hidden += 1
                continue
            last = text
            if src == "proc":
                logs = [e for e in staged if e[6] != "proc" and e[3] != stage and e[0] > (t0 or 0)]
                if logs:  # a log result newer than the process start (e.g. a shipcheck ended while a Step 0 runs)
                    lg = max(logs, key=lambda e: (e[0], e[2]))
                    last = "[%s %s, %.1fh ago] %s" % (lg[6], lg[3], (self.now - lg[0]) / 3600, lg[5])
            else:
                newest = max(staged, key=lambda e: (e[0], e[2]))
                last = newest[5] if newest[0] >= t else text
            out.append({"idea": c, "stage": stage, "owner": owner, "age_h": round(age, 1), "last": re.sub(r"\s+", " ", last)[:90],
                        "source": src, "n_events": len(evs)})
        out.sort(key=lambda r: (RANK[r["stage"]], -r["age_h"]))
        return out


# ---------------------------------------------------------------------------------------------------------------------
# handoff audit (Coordinator, 10 Nov: PMX sat "Step 0 queued" ~1 h with no batch anywhere)
SPECDIR = os.path.join(ROOT, "condor-work/reports/analysts")
PILOTQ = "/homes/zw4424/condor-runs/pilotq"
ABL = "/data/zw4424/abl"
ST = "/data/zw4424/st"
HO_ALARM = os.path.join(Q, "handoff.alarm")
HO_UP = re.compile(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*")
HO_NOVA = re.compile(r"\bnova_(?:b\d+|dg|ft)_([A-Za-z0-9_]+)")
HO_AGENT = re.compile(r"(?<![A-Za-z0-9_])b(1\d{3})(?![0-9])")
HO_TITLE = re.compile(r"^#\s*(?:Spec\s+)?([A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]+)*)\b")
HO_TOKSTOP = set("""nova dg ft ptk base spar aggro sbg fish data st tools lab maps map txt log lst man json py python3 homes zw4424 cambc
condor runs stage abl run debug limit sh timeout nice live empty subsets bq bin cxe cq fresh pilotq queue claimed vespm""".split())
# 11 Nov (Planner): "routed to b1807" in a Builder line is downstream (a build agent has it) until that agent's PREREG lands
K_ROUTED = re.compile(r"\brouted to b1\d{3}\b|\bwent to b1\d{3}\b|\bhanded to b1\d{3}\b")
HO_KW = [("prereg", K_STEP0), ("armed", K_ARMED), ("ship", K_SHIP), ("fail", K_FAIL), ("pass", K_PASS_REAL), ("closed", K_CLOSED),
         ("routed", K_ROUTED)]
# 11 Nov (Planner): a spec code whose work runs under other prefixes (MOD = REM, REM2, TAM, TAM-S, STM). One line a code in
# /data/zw4424/st/bq/pipe_aliases.txt: "CODE: ALIAS ALIAS ..." (# comments); read each run, so the Planner edits it without a restart
ALIAS_FILE = "/data/zw4424/st/bq/pipe_aliases.txt"


def ho_aliases():
    out = {}
    try:
        for ln in open(ALIAS_FILE, errors="replace"):
            ln = ln.split("#", 1)[0]
            if ":" in ln:
                k, v = ln.split(":", 1)
                out.setdefault(k.strip().upper(), []).extend(x.upper() for x in v.replace(",", " ").split())
    except OSError:
        pass
    return out


def ho_up(text):
    """uppercase codes in TEXT: each token, its hyphen parts, and the token without trailing digits (PMX1 -> PMX)"""
    out = set()
    for t in HO_UP.findall(text):
        out.add(t)
        if "-" in t:
            out.update(t.split("-"))
        s = t.rstrip("0123456789")
        if len(s) >= 2 and s != t:
            out.add(s)
    return out


def ho_slugs(text):
    """lowercase slug tokens of nova_* bot names (nova_dg_b1789lza2 -> lza2)"""
    out = []
    for s in HO_NOVA.findall(text):
        for part in s.lower().split("_"):
            part = re.sub(r"^b1\d{3}", "", part)
            if part and part not in HO_TOKSTOP:
                out.append(part)
    return out


def ho_toks(text):
    """lowercase path/arg tokens (cmdlines, file and queue names), b1NNN prefixes stripped"""
    out = []
    for part in re.split(r"[^A-Za-z0-9]+", text.lower()):
        part = re.sub(r"^b1\d{3}", "", part)
        if len(part) >= 2 and part not in HO_TOKSTOP and not part.isdigit():
            out.append(part)
    return out


def ho_spec_codes(path):
    stem = os.path.basename(path)[5:-3]                 # spec_pmx_1110 -> pmx_1110
    parts = [p for p in stem.split("_") if not re.fullmatch(r"\d{4}", p)]
    codes = []
    if parts:
        codes.append(parts[0].upper())
    try:
        with open(path, errors="replace") as f:
            head = [next(f, "") for _ in range(12)]
    except OSError:
        head = []
    m = HO_TITLE.match(head[0]) if head else None
    if m and m.group(1) not in STOP:
        codes.append(m.group(1))
    for b in BITS_RE.findall("".join(head)):
        codes.append(b)
    al = ho_aliases()
    codes += [a for c in list(codes) for a in al.get(c, [])]
    seen, out = set(), []
    for c in codes:
        if c not in seen and len(c) >= 2:
            seen.add(c)
            out.append(c)
    return out


def ho_match(rec, codes):
    up, low = rec[2], rec[3]
    for c in codes:
        if c in up:
            return True
        cl = c.lower().replace("-", "")
        if len(cl) >= 3 and any(t.startswith(cl) for t in low):
            return True
    return False


def handoff(alarm=False, hours=24.0, as_json=False):
    now = time.time()
    since = now - hours * 3600
    specs = []
    try:
        for e in os.scandir(SPECDIR):
            if e.name.startswith("spec_") and e.name.endswith(".md"):
                mt = e.stat().st_mtime
                if mt >= since:
                    specs.append((e.path, mt))
    except OSError:
        pass
    recs = []      # (t or None, kind, upper set, lower tokens, label, agent or None)

    # (b) builder_queue.md sentences with a downstream keyword; earliest spec mention -> post time
    bql = read_since(BQ, since - 2 * 3600)
    for t, ln in bql:
        for sent in SENT_SPLIT.split(ln):
            kinds = [k for k, rx in HO_KW if rx.search(sent)]
            if not kinds and HO_AGENT.search(sent) and not K_SPEC.search(sent):
                kinds = ["agent"]
            if kinds:
                recs.append((t, "bq-" + kinds[0], ho_up(sent), ho_slugs(sent), sent.strip()[:80], None))
    # failure_chains.md: any close / fail in the window counts (a spec is often re-edited after its chain closed)
    chl = read_since(os.path.join(Q, "failure_chains.md"), since - 2 * 3600)
    for t, ln in chl:
        recs.append((t, "chains", ho_up(ln), ho_slugs(ln), ln.strip()[:80], None))
    # (c) armq
    for p in ("armq.txt", "armq.failed"):
        for ln in tail_bytes(os.path.join(Q, p), 200000):
            if ln.strip():
                recs.append((parse_ts(ln[:40]) or (mtime(os.path.join(Q, p)) if p == "armq.txt" else None), "armq", ho_up(ln), ho_slugs(ln), ln[:80], None))
    for t, ln in read_since(os.path.join(Q, "armq.log"), since - 3600):
        recs.append((t, "armq", ho_up(ln), ho_slugs(ln), ln[:80], None))
    # (d) pilot_top
    try:
        for ln in open(os.path.join(Q, "pilot_top.txt"), errors="replace"):
            if ln.strip():
                body = ln.split("#")[0]
                ag = HO_AGENT.findall(ln)
                recs.append((None, "pilot_top", ho_up(ln), ho_toks(body) + ho_slugs(ln), ln.strip()[:80], ag[0] if ag else None))
    except OSError:
        pass
    # (a) bots/ dirs modified within the window
    try:
        for e in os.scandir(os.path.join(ROOT, "bots")):
            if e.name.startswith("nova_b") or e.name.startswith("nova_dg_"):
                try:
                    mt = e.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if mt >= since:
                    ag = HO_AGENT.findall(e.name)
                    recs.append((mt, "bot", set(), ho_slugs(e.name), e.name, ag[0] if ag else None))
    except OSError:
        pass
    # (a) /data/zw4424/st/b1NNN dirs: prereg.md text and file names
    agent_codes = {}   # agent -> list of (t, upper, lower)
    try:
        for e in os.scandir(ST):
            if not re.fullmatch(r"b1\d{3}", e.name):
                continue
            try:
                if e.stat().st_mtime < since:
                    continue
                ents = list(os.scandir(e.path))
            except OSError:
                continue
            ag = e.name[1:]
            for f in ents:
                try:
                    mt = f.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if mt < since:
                    continue
                if f.name == "prereg.md":
                    try:
                        txt = tail_bytes(f.path, 300000)
                    except OSError:
                        txt = []
                    cur = None
                    for ln in txt:
                        tt = parse_ts(ln[:60])
                        cur = tt if tt is not None else cur
                        if ln.strip():
                            recs.append((cur or mt, "stdir", ho_up(ln), ho_slugs(ln), "%s/prereg.md" % e.name, ag))
                else:
                    recs.append((mt, "stdir", set(), ho_toks(f.name), "%s/%s" % (e.name, f.name), ag))
    except OSError:
        pass
    # (a)/(e) processes: cmdline + cwd
    me = os.getpid()
    procs = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            if os.stat("/proc/" + pid).st_uid != os.getuid():
                continue
            cmd = open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if not cmd or "pipe.py" in cmd or "claude" in cmd.split(" ")[0]:
            continue
        try:
            cwd = os.readlink("/proc/%s/cwd" % pid)
        except OSError:
            cwd = ""
        txt = cmd + " " + cwd
        if not re.search(r"nova_|/st/b1\d{3}|condab|cqbatch|dgkit|gate\.py|inforead|shipcheck|prearm|armfarm", txt):
            continue
        ag = HO_AGENT.findall(txt)
        kind = "batch" if re.search(r"condab|cqbatch|dgkit|gate\.py|inforead|shipcheck|armfarm|killgate", cmd) else "proc"
        procs.append(txt)
        recs.append((None, kind, ho_up(cmd) - STOP, ho_toks(txt), cmd[:80], ag[0] if ag else None))
    # (e) pilot queue + claimed item names, recent abl run dirs (bots.txt / manifest bot names)
    qagents = set()
    for sub in ("queue", "claimed"):
        try:
            names = os.listdir(os.path.join(PILOTQ, sub))
        except OSError:
            continue
        bids = set()
        for n in names:
            m = re.match(r"\d+_\d+_(.+?)_\d{4}(?:_g)?(?:\..*)?$", n)
            bids.add(m.group(1) if m else n)
        for b in bids:
            ag = HO_AGENT.findall(b)
            qagents.update(ag)
            recs.append((None, "pilotq", set(), ho_toks(b), "%s/%s" % (sub, b), ag[0] if ag else None))
    try:
        for e in os.scandir(ABL):
            try:
                mt = e.stat().st_mtime
            except OSError:
                continue
            if mt < now - 3 * 3600:
                continue
            try:
                txt = open(os.path.join(e.path, "bots.txt"), errors="replace").read(2000)
            except OSError:
                txt = ""
            recs.append((mt, "abl", set(), ho_slugs(txt) + ho_toks(e.name[3:]), e.name, None))
    except OSError:
        pass
    busy_agents = set(qagents)
    for txt in procs:
        busy_agents.update(HO_AGENT.findall(txt))

    # inverted index: upper token -> rec ids; lowercase token prefixes (3..7 chars) -> rec ids
    iup, ilow = {}, {}
    for i, r in enumerate(recs):
        for t in r[2]:
            iup.setdefault(t, set()).add(i)
        for t in r[3]:
            for k in range(3, min(len(t), 7) + 1):
                ilow.setdefault(t[:k], set()).add(i)
    rows = []
    for path, mt in specs:
        codes = ho_spec_codes(path)
        if not codes:
            continue
        stem = os.path.basename(path)[:-3]
        # post time: the earliest builder_queue mention of the spec file (a later edit bumps the mtime) or the mtime
        post = mt
        for t, ln in bql + chl:
            if t < post and (stem in ln or ("queue +=" in ln and codes[0] in ho_up(ln))):
                post = t
        found = {}
        hit = set()
        for c in codes:
            hit |= iup.get(c, set())
            cl = c.lower().replace("-", "")
            if len(cl) >= 3:
                hit |= ilow.get(cl[:7], set()) if len(cl) <= 7 else {i for i in ilow.get(cl[:7], set()) if ho_match(recs[i], [c])}
        for i in sorted(hit):
            r = recs[i]
            # closes count anywhere in the window; other entries from 30 min before the post (HH:MMZ-only log lines inherit
            # an older stamp)
            if r[0] is not None and r[0] < post - 1800 and r[1] not in ("chains", "bq-closed"):
                continue
            found.setdefault(r[1], r[4])
            if r[5] and r[1] in ("stdir", "bot") and r[5] in busy_agents:
                found.setdefault("agent-busy", "b%s has queue items or processes" % r[5])
        age = (now - post) / 60
        rows.append({"code": codes[0], "aliases": codes[1:], "spec": os.path.basename(path), "age_min": round(age),
                     "mtime_age_min": round((now - mt) / 60), "found": found, "none": not found})
    rows.sort(key=lambda r: (not r["none"], -r["age_min"] if r["none"] else r["age_min"]))
    stale = [r for r in rows if r["none"] and r["age_min"] > 60]
    if alarm:
        if stale:
            msg = "ALARM handoff: %d spec(s) > 60 min with no downstream entry: %s" % (
                len(stale), ", ".join("%s (%dm)" % (r["code"], r["age_min"]) for r in stale[:25]) + (" ..." if len(stale) > 25 else ""))
            tmp = HO_ALARM + ".tmp%d" % os.getpid()
            with open(tmp, "w") as f:
                f.write(msg + "\n")
            os.replace(tmp, HO_ALARM)
        else:
            try:
                os.unlink(HO_ALARM)
            except OSError:
                pass
    if as_json:
        print(json.dumps({"now": now, "rows": rows}, indent=1))
        return
    order = ["batch", "pilotq", "agent-busy", "pilot_top", "proc", "abl", "armq", "bq-ship", "bq-armed", "bq-pass", "bq-fail", "bq-closed",
             "chains", "bq-prereg", "bq-agent", "bot", "stdir"]
    print("handoff %s  (%d specs modified in %gh; %d NONE, %d NONE > 60 min; %.1f s)" % (
        datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), len(rows), hours,
        sum(r["none"] for r in rows), len(stale), time.time() - now))
    print("%-9s %-24s %6s  %-4s %s" % ("code", "spec", "age(m)", "NONE", "downstream found"))
    for r in rows:
        ks = sorted(r["found"], key=lambda k: order.index(k) if k in order else 99)
        desc = ",".join(ks)
        if ks:
            desc += "  [" + r["found"][ks[0]][:70] + "]"
        code = r["code"] + ("/" + "/".join(r["aliases"]) if r["aliases"] else "")
        print("%-9s %-24s %6d  %-4s %s" % (code[:9], r["spec"][:24], r["age_min"], "NONE" if r["none"] else "", desc))


def main():
    a = sys.argv[1:]
    if a and a[0] == "handoff":
        hrs = float(a[a.index("--hours") + 1]) if "--hours" in a else 24.0
        handoff(alarm="--alarm" in a, hours=hrs, as_json="--json" in a)
        return
    if "-h" in a or "--help" in a:
        print(__doc__)
        return
    since = 48.0
    filt = []
    if "--since" in a:
        since = float(a[a.index("--since") + 1])
    if "--idea" in a:
        filt = [x.strip().upper() for x in a[a.index("--idea") + 1].split(",") if x.strip()]
    p = Pipe(since)
    p.load()
    rows = p.table(filt, "--all" in a)
    stalls = sorted(set(p.stalls), key=lambda s: -s[2])
    if filt:
        stalls = [s for s in stalls if any(f in s[1] for f in filt)]
    if "--json" in a:
        print(json.dumps({"now": p.now, "rows": rows, "stalls": [dict(kind=s[0], idea=s[1], age_h=round(s[2], 1), what=s[3]) for s in stalls]}, indent=1))
        return
    print("pipe %s  (since %gh, %d ideas)" % (datetime.fromtimestamp(p.now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), since, len(rows)))
    print("%-9s %-17s %-11s %6s  %-90s %s" % ("idea", "stage", "owner", "age(h)", "last result", "src"))
    for r in rows:
        print("%-9s %-17s %-11s %6.1f  %-90s %s" % (r["idea"][:9], r["stage"], r["owner"][:11], r["age_h"], r["last"], r["source"]))
    if p.hidden:
        print("(%d older rows hidden: closed/shipped > 6 h, FAIL/PASS/Step 0 > 12 h, spec > 24 h, armed > 8 h; --all shows them)" % p.hidden)
    print("\nSTALLS (%d)" % len(stalls))
    for s in stalls:
        print("  %-17s %-14s %6.1fh  %s" % (s[0], s[1][:14], s[2], s[3][:110]))


if __name__ == "__main__":
    main()
