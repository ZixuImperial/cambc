#!/usr/bin/env python3
"""shipbake: after a ship, the next base with the shipped switches gone (owner 7 Nov: "when shipping, remove the switch and just have diffs
instead"; "make sure the ships remove the switches correctly"). The live bot keeps its flag tables; the base the queued diffs apply onto (the
diff model, armq bq/armq_diff) is live with every SHIPPED flag baked: its table a compile-time constant at the shipped value, its off-branches
and the helpers only they used gone (tools/lab/deadstrip.py with every other volatile table kept, so every other flip still works), and a
one-line comment at its site naming the version that first shipped it and the idea. The pre-bake versions stay in the ideastore.

usage: python3 -I tools/lab/shipbake.py [--live BOT] [--new NAME] [--dry] [--maps 20]
  1. this ship's REAL flips: FLIPS= of bots/LIVE/FLIP whose value differs from the parent live's (a refactor's dummy flip at the live value
     is no new value: not baked anew, not commented; its table keeps its first ship's record)
  2. CUMULATIVE: bq/baked.json, the ledger of every table baked so far {X_TAB: {flag, value, version, subject}}, gets the new real flips'
     tables; the bake set is every ledger table still volatile in LIVE (a candidate built on live, not on the base, brings tables back)
  3. deadstrip.py LIVE NEW --keep-file (every other volatile table): bake + fold + unused, NEW = nova_base_vNNN (or --new)
  4. comments: `// vNNN STEM: summary` above each baked site that has none yet, from the ledger (the version that first shipped the value)
  5. NEW builds (its release wasm, on a pilot when one is up) and no bake-set table is still volatile in NEW: then bq/diffbase.txt "LIVE NEW stamp ... identity pending"
     at once (owner 7 Nov: "identity must not cost time"): armq's diff model arms queued diffs on NEW, shipcheck's built-on-live check accepts NEW
  6. identity v the shipped bot after that, on the pilots only: cxeident LIVE NEW, --maps maps x 2 seats (default 20 = 40 games), every game
     equal -> "identity ok". A failure (or 3 tries with no pilots) marks NEW bad (bq/badbase.txt), puts diffbase back to live, and every bot
     armed on NEW (marker TRUNK built on NEW in trunk_registry) is stopped (SHIPCHECK.badbase) and its line requeued at the head, once.
     A strip failure records "LIVE -": armq arms on live meanwhile (owner ~18:00Z: shipping never waits on the bake).
armq starts this once per new live (diff model only; off: touch bq/shipbake_OFF). tools/lab/bake.py, when it exists, does steps 3-5
(b1488's tool; SHIPBAKE_OWN=1 keeps this one). Exit 0 done or nothing to do, 1 failed, 2 bad use."""
import glob
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
LAB = f"{REPO}/tools/lab"
Q = "/data/USER/st/bq"
DIFFBASE = f"{Q}/diffbase.txt"
LEDGER = f"{Q}/baked.json"
LOG = f"{Q}/shipbake.log"
DECL = re.compile(r"inline\s+const\s+volatile\s+int\s+([A-Z][A-Z0-9_]*_TAB)\s*\[[^\]]*\]\s*=\s*\{([^}]*)\}")
DEFINE = re.compile(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*)\s+\(?\s*(-?\d+)\s*\)?\s*(?://.*)?$", re.M)


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def say(s):
    line = f"{stamp()} {s}"
    print(line, flush=True)
    try:
        open(LOG, "a").write(line + "\n")
    except OSError:
        pass


def live_lines():
    """[(version, bot, parent)] newest first, from bq/live.txt"""
    out = []
    for ln in open(f"{Q}/live.txt"):
        a = ln.split()
        if len(a) >= 2:
            p = next((x.split("=", 1)[1] for x in a if x.startswith("parent=")), "")
            out.append((a[0], a[1], p))
    return out


def base_for(live):
    try:
        a = open(DIFFBASE).readline().split()
    except OSError:
        return None
    return a[1] if len(a) > 1 and a[0] == live and a[1] != live and os.path.isdir(f"{REPO}/bots/{a[1]}/src") else None


def defines(bot):
    out = {}
    src = f"{REPO}/bots/{bot}/src"
    for f in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if f.endswith((".h", ".cpp", ".cc")):
            for m in DEFINE.finditer(open(os.path.join(src, f), errors="replace").read()):
                out.setdefault(m.group(1), m.group(2))
    return out


def shipped_flips(bot):
    try:
        t = open(f"{REPO}/bots/{bot}/FLIP").read()
    except OSError:
        return {}
    m = re.search(r"^FLIPS=(.*)$", t, re.M)
    return dict(x.split("=", 1) for x in (m.group(1).split() if m else []) if "=" in x)


def subject_of(bot):
    try:
        m = re.search(r"^SUBJECT=(.*)$", open(f"{REPO}/bots/{bot}/SHIPCHECK").read(), re.M)
    except OSError:
        return ""
    return re.sub(r"^[a-z]+(\([^)]*\))?:\s*", "", m.group(1).strip()) if m else ""


def tables(bot):
    """{X_TAB: identifiers in its initializer} for every volatile table of BOT"""
    out = {}
    src = f"{REPO}/bots/{bot}/src"
    for f in sorted(os.listdir(src)):
        if f.endswith((".h", ".cpp", ".cc")):
            for m in DECL.finditer(open(os.path.join(src, f), errors="replace").read()):
                out[m.group(1)] = set(re.findall(r"[A-Za-z_]\w*", m.group(2)))
    return out


def ledger():
    try:
        return json.load(open(LEDGER))
    except (OSError, ValueError):
        return {}


def save_ledger(led):
    """11 Nov (TB 6ad907: VCR_TAB, baked into nova_base_v723, was missing from the ledger by v732, so later bases left it volatile).
    The ledger only grows; a run loads it at its start, so two overlapping ships' runs overwrote each other's entries. Now: under a lock,
    re-read the file, merge this run's entries over it, write atomically."""
    import fcntl
    with open(LEDGER + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cur = ledger()
        cur.update(led)
        tmp = f"{LEDGER}.new.{os.getpid()}"
        json.dump(cur, open(tmp, "w"), indent=1)
        os.replace(tmp, LEDGER)


def real_flips(bot, parent):
    """(this ship's flips whose value differs from the parent live's #define, the rest: dummies at the live value)"""
    fl = shipped_flips(bot)
    pv = defines(parent) if parent else {}
    return ({k: v for k, v in fl.items() if str(pv.get(k)) != str(v)}, {k: v for k, v in fl.items() if str(pv.get(k)) == str(v)})


def bake_copies(new, ver):
    """11 Nov (RC XBK1): a baked table (now `constexpr ... X_TAB[...]`) whose flag word is COPIED into a variable, either at start-up
    (`inline const int x_bits = X_TAB[1];`) or once a turn (`inline int x_bits = 0;` + `x_bits = X_TAB[1];` in turn code), keeps paying a
    load (and a per-turn store). The copy becomes `inline constexpr int x_bits = X_TAB[1];` and the per-turn assignment goes. Only when the
    variable has no other assignment anywhere; play-identical (the value is the same). -> ["X_TAB:x_bits", ...] rewritten."""
    src = f"{REPO}/bots/{new}/src"
    files = [os.path.join(src, f) for f in os.listdir(src) if f.endswith((".h", ".cpp", ".cc"))]
    txt = {f: open(f, errors="replace").read() for f in files}
    alltxt = "\n".join(txt.values())
    done = []
    for t in sorted(set(re.findall(r"\bconstexpr\s+int\s+([A-Z][A-Z0-9_]*_TAB)\s*\[", alltxt))):
        if not re.search(rf"\binline\s+(?:const\s+)?int\s+\w+\s*=\s*(?:0|{t}\s*\[\s*1\s*\])", alltxt) or f"{t}[1]" not in alltxt.replace(" ", ""):
            continue  # cheap pre-filter: no copy of this table's word anywhere
        decl = re.compile(rf"^(\s*)inline\s+(?:const\s+)?int\s+(\w+)\s*=\s*(0|{t}\s*\[\s*1\s*\])\s*;[^\n]*$", re.M)
        for f, body in list(txt.items()):
            for m in decl.finditer(body):
                name = m.group(2)
                asg = re.compile(rf"^\s*(?:::nova::|nova::)?{re.escape(name)}\s*=\s*{t}\s*\[\s*1\s*\]\s*;[^\n]*$", re.M)
                any_asg = re.compile(rf"(?<![\w.>:])(?:::nova::|nova::)?{re.escape(name)}\s*(?:[-+*/|&^]?=)(?!=)")
                n_asg = sum(len(asg.findall(b)) for b in txt.values())
                n_all = sum(len(any_asg.findall(b)) for b in txt.values()) - 1  # minus the declaration's own '='
                if m.group(3) == "0" and n_asg == 0:
                    continue  # a plain 0-initialised int, not a copy of this table
                if n_all != n_asg:
                    continue  # assigned elsewhere too: leave it
                txt[f] = txt[f].replace(m.group(0), f"{m.group(1)}inline constexpr int {name} = {t}[1]; // {ver} baked: copy of the baked flag word")
                for g in txt:
                    txt[g] = asg.sub(lambda mm: re.match(r"^\s*", mm.group(0)).group(0) + f"// {ver} baked: {name} is constexpr", txt[g])
                done.append(f"{t}:{name}")
                break
    for f in files:
        if txt[f] != open(f, errors="replace").read():
            open(f + ".tmp", "w").write(txt[f])
            os.replace(f + ".tmp", f)
    return done


def annotate(new, recs, replace=False):
    """`// vNNN STEM: summary` above each baked table's #define (else the table) that has no such comment yet; replace=True rewrites one
    already there (bake.py dates a site by the last version line naming its macro, which credits a dummy flip). -> sites marked"""
    src, n = f"{REPO}/bots/{new}/src", 0
    for f in sorted(os.listdir(src)):
        p = os.path.join(src, f)
        if not f.endswith((".h", ".cpp", ".cc")):
            continue
        lines = open(p, errors="replace").read().split("\n")
        out, changed = [], False
        for ln in lines:
            for t, rec in recs.items():
                stem = t[:-4]
                if re.match(rf"\s*inline\s+(constexpr|const)\b.*\b{t}\s*\[", ln):
                    inl = re.search(rf"//\s*(v\d+)\s+{stem}:", ln)
                    if inl:  # bake.py's own comment on the table line: ONE comment per site; fix only a wrong version (a dummy flip's credit)
                        if replace and inl.group(1) != rec["version"]:
                            ln = ln[:inl.start()] + f"// {rec['version']} {stem}: " + (rec.get("subject") or "baked at its shipped value")[:90]
                            changed, n = True, n + 1
                        continue
                    at = len(out) - 1 if out and re.match(rf"\s*#\s*define\s+{stem}_", out[-1]) else len(out)
                    old = [j for j in range(max(0, at - 2), at) if re.match(rf"\s*//\s*v\d+\s+{stem}:", out[j])]
                    if old and replace:
                        out[old[-1]] = f"// {rec['version']} {stem}: " + (rec.get("subject") or "baked at its shipped value")[:90]
                        changed, n = True, n + 1
                    elif not old:
                        out.insert(at, f"// {rec['version']} {stem}: " + (rec.get("subject") or "baked at its shipped value")[:90])
                        changed, n = True, n + 1
            out.append(ln)
        if changed:
            open(p, "w").write("\n".join(out))
    return n


def fold_sites(new, table):
    """bake.py's report of where TABLE's switch was folded: [(file, base line, kept text)] from /data/USER/st/bake/NEW/by_flag/
    (TABLE.txt and STEM_*.txt), folds only (an 'unused ...' entry is a deletion with no site left)"""
    stem = table[:-4]
    out = []
    for p in sorted(glob.glob(f"/data/USER/st/bake/{new}/by_flag/{stem}_*.txt") + glob.glob(f"/data/USER/st/deadstrip/{new}/by_flag/{stem}_*.txt")):
        blocks = re.split(r"^--- ", open(p, errors="replace").read(), flags=re.M)
        for b in blocks[1:]:
            head = b.split("\n", 1)[0]
            m = re.match(r"(\S+)\s+(?:\S+\s+)?(\w+\.(?:cpp|h)):(\d+)", head)
            if not m or head.startswith("unused"):
                continue
            kept = b.split("+++ kept:", 1)[1].strip().split("\n")[0].strip() if "+++ kept:" in b else ""
            out.append((m.group(2), int(m.group(3)), kept))
    # one site per place: the same fold is listed under each bit constant, and folds a few lines apart are one place
    out = sorted(set(out), key=lambda x: (x[0], x[1]))
    sites = []
    for f, ln, kept in out:
        if sites and sites[-1][0] == f and ln - sites[-1][1] <= 6:
            if len(kept) > len(sites[-1][2]):
                sites[-1] = (f, sites[-1][1], kept)
            continue
        sites.append((f, ln, kept))
    return sites


def annotate_sites(new, table, rec):
    """the table itself is gone (bake.py deleted it as unused): ONE comment above each fold site that has none. -> sites marked"""
    stem, n = table[:-4], 0
    text = f"// {rec['version']} {stem}: " + (rec.get("subject") or "baked at its shipped value")[:90]
    for fn, line, kept in fold_sites(new, table):
        p = os.path.join(f"{REPO}/bots/{new}/src", fn)
        try:
            ls = open(p, errors="replace").read().split("\n")
        except OSError:
            continue
        key = kept[:40]
        cand = [i for i, x in enumerate(ls) if key and key in x]
        if not cand:
            continue
        i = min(cand, key=lambda j: abs(j + 1 - line))  # the kept text nearest the base line (the strip shifts lines)
        if i > 0 and re.match(rf"\s*//\s*v\d+\s+{stem}:", ls[i - 1]):
            continue
        ind = re.match(r"\s*", ls[i]).group(0)
        ls.insert(i, ind + text)
        open(p, "w").write("\n".join(ls))
        n += 1
    return n


def leftovers(new, bake):
    """lines of NEW that still TEST a baked switch (STEM_ON(, STEM_TAB[k] in code, STEM_BIT_ in code), its declarations aside"""
    out = []
    src = f"{REPO}/bots/{new}/src"
    stems = {t[:-4] for t in bake}
    # a bit TEST is a switch left over (STEM_ON(...), STEM_TAB[1] & ...); a parameter read (STEM_TAB[4]) is the shipped value, fine
    pat = re.compile(r"\b(" + "|".join(map(re.escape, sorted(stems))) + r")_(ON\s*\(|TAB\s*\[\s*1\s*\]\s*&)") if stems else None
    for f in sorted(os.listdir(src)) if pat else []:
        if not f.endswith((".h", ".cpp", ".cc")):
            continue
        for k, ln in enumerate(open(os.path.join(src, f), errors="replace").read().split("\n"), 1):
            code = ln.split("//", 1)[0]
            if pat.search(code) and not re.match(r"\s*(#\s*define|inline\s+constexpr|constexpr\s+int\s+\w+_BIT_)", code):
                out.append(f"{f}:{k}: {code.strip()[:120]}")
    return out



BAKE_KEEP = os.environ.get("BAKE_KEEP_FILE", "/data/USER/st/bq/bake_keep.txt")


def bake_keep():
    """8 Nov (Builder, Rule Checker R1): tables a test still needs flippable, one X_TAB per line (# comments): never baked, their off
    branches never stripped, by bake.py, deadstrip.py or shipbake.py"""
    try:
        return {w for ln in open(BAKE_KEEP) for w in ln.split("#", 1)[0].split() if w}
    except OSError:
        return set()


def fail(live, why):
    say(f"FAILED: {why}")
    open(DIFFBASE, "w").write(f"{live} - {stamp()} bake FAILED: no base, lines wait (bq/shipbake.log)\n")
    return 1


PATCHQ = os.path.join(Q, "bake_patches")


def bake_patches(new, ver):
    """9 Nov (Builder): queued PLAY-IDENTICAL hand edits (dead writes, no-ops, always-false tests a token folder can't prove) ride the bake: each
    bq/bake_patches/NAME.diff (paths a/src/... or a/<file>, as `git diff` or `diff -ru` of a bot's src) is applied to the stripped copy before it is
    built, and the identity check v live that follows every bake guards it. A patch that doesn't apply cleanly is left queued and logged; an applied one
    moves to bake_patches/applied/NAME.<ver>.diff."""
    if not os.path.isdir(PATCHQ):
        return
    src = f"{REPO}/bots/{new}/src"
    for p in sorted(glob.glob(os.path.join(PATCHQ, "*.diff"))):
        nm = os.path.basename(p)[:-5]
        txt = open(p, errors="replace").read()
        strip = "2" if re.search(r"^\+\+\+ b/src/", txt, re.M) else "1"
        dry = subprocess.run(["patch", "-t", f"-p{strip}", "--dry-run", "-F", "1", "-d", src, "-i", p], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL)
        if dry.returncode:
            say(f"bake patch {nm}: does not apply to {new}, left queued: {(dry.stdout + dry.stderr).strip()[-200:]}")
            continue
        r = subprocess.run(["patch", "-t", f"-p{strip}", "-F", "1", "--no-backup-if-mismatch", "-d", src, "-i", p], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode:
            say(f"!! bake patch {nm}: apply failed after a clean dry run: {(r.stdout + r.stderr).strip()[-200:]}")
            continue
        os.makedirs(os.path.join(PATCHQ, "applied"), exist_ok=True)
        os.replace(p, os.path.join(PATCHQ, "applied", f"{nm}.{ver}.diff"))
        say(f"bake patch {nm}: applied to {new} (play-identical claim; the identity check v live below decides)")
    # 10 Nov (Builder / Rule Checker: sgk_comment, pbb_dead, dzw_dead went into nova_base_v676, but v677 was built on base_v675 and rebased onto
    # v676's UNBAKED live dir, so v677 and base_v677 lost them, and 'applied' meant they were never tried again): every patch applied in the last
    # REAPPLY_H hours that this new base lacks (its reverse does not apply) and that still applies forward is applied again.
    for p in sorted(glob.glob(os.path.join(PATCHQ, "applied", "*.diff"))):
        pv, nv = re.search(r"\.v(\d+)\.diff$", p), re.search(r"(\d+)", str(ver))
        if not pv or not nv or int(pv.group(1)) < int(nv.group(1)) - int(os.environ.get("BAKE_REAPPLY_VERS", "3")):
            continue  # only the last few versions: older missing patches are the Builder's call (an old loss is a code change now)
        nm = os.path.basename(p)[:-5]
        txt = open(p, errors="replace").read()
        strip = "2" if re.search(r"^\+\+\+ b/src/", txt, re.M) else "1"
        base = ["patch", "-t", f"-p{strip}", "-F", "1", "-d", src, "-i", p]
        d = subprocess.run(base[:1] + ["-N", "--dry-run"] + base[1:], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if "previously applied" in d.stdout + d.stderr:  # (patch -R -t ignores the reversal and returns 0: not a presence test)
            continue  # already in this base
        if d.returncode:
            say(f"bake patch {nm} (applied before): missing from {new} and no longer applies; left out")
            continue
        r = subprocess.run(base[:1] + ["--no-backup-if-mismatch"] + base[1:], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        say(f"bake patch {nm}: RE-APPLIED to {new} (lost by a rebase onto an unbaked live; identity check v live below decides)" if r.returncode == 0
            else f"!! bake patch {nm}: re-apply failed: {(r.stdout + r.stderr).strip()[-200:]}")


def unreachable(bot):
    """{(file, the unreachable line)}: statements that follow an unconditional return/break/continue in the same block. A text scan
    (clang's -Wunreachable-code stays silent inside templates such as target_turn<..>, where v687's splice sat). Skipped: a jump that
    is the body of an unbraced if/else/for/while, and a following '}', case/default or label."""
    src = os.path.join(os.path.realpath(os.path.join(REPO, "bots", bot)), "src")
    ctl = re.compile(r"^(?:\}\s*)?(?:if|else|for|while|do)\b")
    out = set()
    for fn in sorted(os.listdir(src)):
        if not fn.endswith((".cc", ".cpp", ".h")):
            continue
        ls = []
        for x in open(os.path.join(src, fn), errors="replace").read().split("\n"):
            k = x.find("//")
            c = (x if k < 0 else x[:k]).strip()
            if c:
                ls.append(c)
        for i, c in enumerate(ls[:-1]):
            if not re.match(r"^(return\b[^;]*|break|continue);$", c):
                continue
            prev = ls[i - 1] if i else ""
            # 11 Nov (Builder, v782 LAH: `if (a ||\n  b) // RC C417\n  return false;` was read as unreachable): a condition spread over
            # several lines: walk back to the line that starts the statement before testing it for if/else/for/while/do
            j = i - 1
            while j > 0 and not ls[j - 1].endswith((";", "{", "}")):
                j -= 1
            start = ls[j] if i else ""
            if (ctl.match(prev) or ctl.match(start)) and not prev.endswith((";", "{", "}")):
                continue  # the body of an unbraced control statement
            nx = ls[i + 1]
            if nx.startswith(("}", "case ", "default", "#")) or re.match(r"^\w+:$", nx):
                continue
            out.add((fn, nx))
    return out


def main():
    a = sys.argv[1:]
    dry = "--dry" in a
    maps = int(a[a.index("--maps") + 1]) if "--maps" in a else 20
    lines = live_lines()
    ver, live, parent = lines[0]
    if "--live" in a:
        live = a[a.index("--live") + 1]
        ver, _, parent = next((x for x in lines if x[1] == live), (ver, live, parent))
    if base_for(live) and "--new" not in a:
        print(f"{live}: base {base_for(live)} already recorded")
        return 0
    led = ledger()
    real, dummy = real_flips(live, parent)
    tabs = tables(live)
    subj = subject_of(live)
    for t, ids in tabs.items():  # new real values enter the ledger under this version
        hit = [k for k in real if k in ids]
        if hit:
            led[t] = dict(flag=hit[0], value=real[hit[0]], version=ver, subject=subj)
    # 11 Nov (RC: VCR (v723) and RWD (v713) shipped with BITS=1 but never entered the ledger: their ships' flips were inside the trunk, so
    # FLIP showed no new value). Sweep: a volatile table whose *_BITS flag is non-zero in live and that the ledger lacks is a shipped value
    # with no record: it enters the ledger now (version: this ship, subject marks the sweep) and is baked like any older ledger table.
    try:
        srcd = f"{REPO}/bots/{live}/src"
        alltxt = "\n".join(open(os.path.join(srcd, x), errors="replace").read() for x in os.listdir(srcd) if x.endswith((".h", ".cpp", ".cc")))
        for t, ids in tabs.items():
            if t in led:
                continue
            for k in sorted(i for i in ids if i.endswith("_BITS")):
                dm = re.search(rf"#\s*define\s+{k}\s+(\S+)", alltxt)
                if dm and dm.group(1) not in ("0", "0x0", "0u"):
                    led[t] = dict(flag=k, value=dm.group(1), version=ver, subject=f"swept {ver}: shipped value with no ledger record")
                    say(f"{live}: ledger sweep: {t} ({k}={dm.group(1)}) was shipped but never recorded: added")
                    break
    except Exception as e:  # noqa: BLE001  the sweep never blocks a bake
        say(f"{live}: ledger sweep skipped ({e!r})")
    bake = sorted(t for t, ids in tabs.items() if any(k in ids for k in real))
    # 9 Nov ~22:55Z, owner (asked directly; replaces the 7 Nov "newest ship only" rule): every OLDER shipped table still volatile in live (in the
    # ledger, e.g. a candidate rebuilt on the unbaked live dir brought it back) is baked too, at its ledger value, unless bake_keep.txt holds it
    # or a queued / running line still flips one of its flags (flip.sh needs the table volatile). Play-identical; the identity check decides.
    busy = set()
    try:
        for ln in open(os.path.join(Q, "armq.txt")):
            try:
                busy.update(re.findall(r"([A-Z][A-Z0-9_]*)=", json.loads(ln).get("flips") or ""))
            except ValueError:
                pass
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import fastship
        for _, fl in fastship.pending(""):
            busy.update((fl or {}).keys())
    except Exception as e:  # noqa: BLE001  without the list, bake only this ship's tables (the old rule)
        say(f"{live}: queued/running flips unreadable ({e!r}): older tables left volatile this time")
        busy = None
    # 12 Nov (RC X593: RCB/RTE/WIC sat volatile for days at 0): a table whose *_BITS is 0 in live AND in the previous live, that no queued,
    # running or waiting line flips and bake_keep does not hold, enters the ledger at 0 (a closed zero-default line), so it is baked too
    if busy is not None:
        try:
            wait = set()
            import hashlib
            st = json.load(open(os.path.join(Q, "shipwatch_state.json")))
            for mk in glob.glob(os.path.join(REPO, "bots", "nova_b*", "SHIPCHECK")):
                nm = os.path.basename(os.path.dirname(mk))
                raw = open(mk, "rb").read()
                if st.get(nm, {}).get("marker") == hashlib.sha1(raw).hexdigest()[:12]:
                    continue  # handled: not waiting
                try:
                    wait.update(re.findall(r"([A-Z][A-Z0-9_]*)=", open(os.path.join(os.path.dirname(mk), "FLIP")).read()))
                except OSError:
                    pass
            prev = [ln.split()[1] for ln in open(os.path.join(Q, "live.txt")) if ln.strip()][1:2]
            ptxt = "\n".join(open(os.path.join(REPO, "bots", prev[0], "src", x), errors="replace").read()
                             for x in os.listdir(os.path.join(REPO, "bots", prev[0], "src")) if x.endswith((".h", ".cpp", ".cc"))) if prev else ""
            keep = bake_keep()
            for t, ids in tabs.items():
                if t in led or t in keep:
                    continue
                ks = [i for i in ids if i.endswith("_BITS")]
                if not ks or any(k in busy or k in wait for k in ks):
                    continue
                def zero(txt, k):
                    m = re.search(rf"#\s*define\s+{k}\s+(\S+)", txt)
                    return bool(m) and m.group(1) in ("0", "0x0", "0u")
                if ptxt and all(zero(alltxt, k) and zero(ptxt, k) for k in ks):
                    led[t] = dict(flag=ks[0], value="0", version=ver, subject=f"swept {ver}: 0 in live and {prev[0]}, no line flips it")
                    say(f"{live}: zero sweep: {t} ({ks[0]}=0 in live and the previous live; no queued/running/waiting line): added at 0")
        except Exception as e:  # noqa: BLE001  the sweep never blocks a bake
            say(f"{live}: zero sweep skipped ({e!r})")
    if busy is not None:
        older = sorted(t for t, ids in tabs.items() if t in led and t not in bake)
        skip = [t for t in older if any(k in busy for k in tabs[t])]
        bake = sorted(set(bake) | (set(older) - set(skip)))
        if skip:
            say(f"{live}: older shipped tables a queued/running line still flips, left volatile: {', '.join(skip)}")
    held = sorted(set(bake) & bake_keep())
    if held:  # 8 Nov: a shipped table a test still flips stays volatile (bq/bake_keep.txt); the next ship that leaves it off the list bakes it
        say(f"{live}: not baked, on bq/bake_keep.txt: {', '.join(held)}")
        bake = [t for t in bake if t not in held]
    note = (f"real flips {' '.join(f'{k}={v}' for k, v in real.items()) or 'none'}"
            + (f"; dummy (= the parent's value, not new) {' '.join(f'{k}={v}' for k, v in dummy.items())}" if dummy else ""))
    if not bake:
        say(f"{live} ({ver}): {note}; nothing shipped is still volatile: the base is live itself")
        if not dry:
            open(DIFFBASE, "w").write(f"{live} {live} {stamp()} nothing to bake\n")
            save_ledger(led)
            queued_conflicts()
        return 0
    new = a[a.index("--new") + 1] if "--new" in a else f"nova_base_{ver}"
    keep = sorted(set(tabs) - set(bake))
    say(f"{live} ({ver}): {note}; bake {len(bake)} shipped table(s) still volatile: "
        + ", ".join(f"{t}={led[t]['value']} ({led[t]['version']})" for t in bake) + f"; keep {len(keep)} -> {new}")
    if dry:
        return 0
    ident_after = False
    if os.path.exists(f"{REPO}/bots/{new}"):
        say(f"{new} exists: not rebuilt (give --new NAME)")
        return 1
    # 10 Nov (Builder, Rule Checker: v687's FB35 merge splice left an unconditional `return false;` and the bake then STRIPPED the code it made
    # unreachable, GT_TMAX and friends): code that clang now calls unreachable in LIVE but not in the previous base refuses the bake, before
    # anything is stripped. The base is then not recorded and lines arm on live; fix live (or SHIPBAKE_UNREACH=0 when it is intended).
    if os.environ.get("SHIPBAKE_UNREACH", "1") != "0":
        try:
            prev = open(DIFFBASE).readline().split()[1]
        except (OSError, IndexError):
            prev = ""
        if prev and prev != "-" and os.path.isdir(os.path.join(REPO, "bots", prev, "src")):
            ul, up = unreachable(live), unreachable(prev)
            if ul is not None and up is not None:
                fresh = sorted(ul - up)
                if fresh:
                    return fail(live, f"{len(fresh)} code line(s) now unreachable in {live} but not in {prev} (a statement after an unconditional return/break/continue): "
                                + "; ".join(f"{fn}: {t[:70]}" for fn, t in fresh[:4]) + " -- a merge splice? fix live; SHIPBAKE_UNREACH=0 if intended")
                say(f"unreachable-code check: nothing new v {prev}")
    bp = f"{LAB}/bake.py"
    t0 = time.time()
    if os.path.exists(bp) and os.environ.get("SHIPBAKE_BAKEPY") == "1":  # 7 Nov (owner: bake in 2-3 min): own path by default; bake.py on request  # b1488's tool (Builder 7 Nov): bake, strip, comment, identity, mergecheck, flagorphan
        r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", bp, live, new, "--bake", ",".join(bake), "--check", "--maps", str(maps)],
                           capture_output=True, text=True, cwd=REPO)  # --bake: ONLY the shipped tables; --check: exit 0 = cxeident identity holds
        tail = (r.stdout + r.stderr).strip().splitlines()
        if r.returncode or not os.path.isdir(f"{REPO}/bots/{new}/src"):
            return fail(live, f"bake.py {live} {new} rc {r.returncode} ({time.time() - t0:.0f} s): " + " | ".join(tail[-3:])[:400])
        say(f"bake.py {live} -> {new} in {time.time() - t0:.0f} s (identity checked): " + (tail[-1][:200] if tail else ""))
        say(f"comments from the ledger at {annotate(new, {t: led[t] for t in bake}, replace=True)} baked site(s)")
        gone = [t for t in bake if not any(re.search(rf"\b{t}\s*\[", open(os.path.join(f'{REPO}/bots/{new}/src', f), errors='replace').read())
                                           for f in os.listdir(f'{REPO}/bots/{new}/src') if f.endswith(('.h', '.cpp', '.cc')))]
        if gone:  # 7 Nov (Builder: v605 SLIM got no comment: bake.py deleted the table, so no declaration site was left)
            say(f"comments at fold sites of {', '.join(gone)} (table deleted): {sum(annotate_sites(new, t, led[t]) for t in gone)}")
    else:
        kf = f"{Q}/shipbake_{ver}.keep"
        open(kf, "w").write("\n".join(keep) + "\n")
        r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", f"{LAB}/deadstrip.py", live, new, "--keep-file", kf], capture_output=True, text=True, cwd=REPO)
        if r.returncode or not os.path.isdir(f"{REPO}/bots/{new}/src"):
            return fail(live, f"deadstrip {live} {new} rc {r.returncode}: {(r.stdout + r.stderr).strip()[-400:]}")
        say(f"deadstrip done in {time.time() - t0:.0f} s; comments at {annotate(new, {t: led[t] for t in bake})} baked site(s)")
        gone = [t for t in bake if not any(re.search(rf"\b{t}\s*\[", open(os.path.join(f'{REPO}/bots/{new}/src', f), errors='replace').read())
                                           for f in os.listdir(f'{REPO}/bots/{new}/src') if f.endswith(('.h', '.cpp', '.cc')))]
        if gone:
            say(f"comments at fold sites of {', '.join(gone)} (table deleted): {sum(annotate_sites(new, t, led[t]) for t in gone)}")
        bake_patches(new, ver)
        try:
            nc = bake_copies(new, ver)
            if nc:
                say(f"copy-at-start flags made constexpr: {nc}")
        except Exception as e:  # noqa: BLE001  a play-identical tidy: never blocks a bake
            say(f"copy-at-start rewrite skipped ({e!r})")
        t0 = time.time()
        try:  # 7 Nov (owner: identity must not cost time): the base is usable once it builds; identity follows on the pilots
            sys.path.insert(0, f"{REPO}/tools/cxe")
            import cxebuild
            w = cxebuild.pilot_wasm(new) or cxebuild.cli_build(new)  # the wasm is what arms need (~30 s on a pilot); the native library is identity's (cxeident builds it)
            if not w or not os.path.exists(w):
                raise RuntimeError(f"no wasm for {new}")
        except BaseException as e:  # noqa: BLE001  SystemExit from a compile error too
            return fail(live, f"{new} does not build ({time.time() - t0:.0f} s): {str(e)[-300:]}")
        say(f"{new} builds ({time.time() - t0:.0f} s)")
        ident_after = True
    left = leftovers(new, bake)
    for x in left:  # 7 Nov (Builder, owner: "remove the switch, keep only the live path"): visible, and the ledger entry stays open
        say(f"switch NOT removed: {x}")
    for t in bake:
        led[t]["partial"] = any(x.split(":", 1)[0] and re.search(rf"\b{t[:-4]}_", x) for x in left)
    still = sorted(t for t in tables(new) if t in bake)
    if still:
        return fail(live, f"{new} still has volatile {', '.join(still)}")
    save_ledger(led)
    baked = ", ".join(f"{t}={led[t]['value']}" for t in bake)
    with open("/homes/USER/condor-work/reports/trunk_registry.md", "a") as f:
        f.write(f"- {new} SHIPBAKE {stamp()} (shipbake): {live} ({ver}) with {baked} baked (cumulative; {len(keep)} tables kept volatile); "
                + (f"identity v {live} running on the pilots (bq/shipbake.log).\n" if ident_after else f"identity {maps * 2}/{maps * 2} v {live} at unlimited fuel.\n"))
    open(DIFFBASE, "w").write(f"{live} {new} {stamp()} baked {','.join(bake)}" + (" identity pending" if ident_after else "") + "\n")
    say(f"base for the diff model: {new} (bq/diffbase.txt)" + (": lines arm on it now; identity v live follows on the pilots" if ident_after else ""))
    queued_conflicts()
    if ident_after:
        return identity(live, new, maps)
    return 0


def identity(live, new, maps):
    """7 Nov (owner via the Builder: "identity must not cost time"): the base is already recorded; cxeident LIVE NEW on the pilots only
    (never local). Not run (no pilots): 2 more tries 2 min apart, then treated as failed. Failed: bad_base()."""
    env = dict(os.environ, CXEIDENT_PILOTS_ONLY="1", PILOTCXE_PRIO=os.environ.get("SHIPBAKE_PRIO", "20"))
    for k in range(3):
        t0 = time.time()
        r = subprocess.run(["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", live, new, "--maps", str(maps), "--seed", "1"],
                           capture_output=True, text=True, cwd=REPO, env=env)
        tail = [x for x in (r.stdout + r.stderr).strip().splitlines() if x.strip()]
        if r.returncode == 0:
            say(f"identity {live} v {new}: {maps * 2} of {maps * 2} games equal on the pilots ({time.time() - t0:.0f} s): base confirmed")
            try:
                a = open(DIFFBASE).readline().split()
                if a[:2] == [live, new]:
                    txt = open(DIFFBASE).read().replace(" identity pending", " identity ok")  # read first: open(.., "w") truncates
                    open(DIFFBASE + ".tmp", "w").write(txt)
                    os.replace(DIFFBASE + ".tmp", DIFFBASE)
            except OSError:
                pass
            # 10 Nov ~22:35Z (Builder): also the 100k identity, as information. A baked base differs from its shipped bot at the real
            # budget (fuel-gated bars; v708 35%, v711 67% of games), which confounds drift reads that mix them. Logged, never blocking.
            try:
                rb = subprocess.run(["nice", "-n", "10", sys.executable, "-I", f"{REPO}/tools/cxe/cxeident.py", live, new, "--maps", str(maps),
                                     "--seed", "1", "--budget"], capture_output=True, text=True, cwd=REPO, timeout=1800, env=env)
                ln = [x.strip() for x in (rb.stdout + rb.stderr).splitlines() if "identity at 100k" in x]
                say(f"identity at 100k (information) {live} v {new}: {ln[0][:200] if ln else 'no result'}")
            except (OSError, subprocess.TimeoutExpired) as e:
                say(f"identity at 100k (information): not run ({str(e)[:100]})")
            return 0
        if r.returncode != 3:
            key = [x.strip() for x in tail if "identity at unlimited fuel" in x or x.startswith("cxeident ")] or tail[-3:]
            return bad_base(live, new, f"identity {live} v {new} rc {r.returncode} ({time.time() - t0:.0f} s): " + " | ".join(key)[:400])
        say(f"identity {live} v {new}: not run, pilots did not play every game (try {k + 1} of 3)")
        if k < 2:
            time.sleep(120)
    return bad_base(live, new, "identity not run in 3 tries (pilots short): an unchecked base is not kept")


BADBASE = f"{Q}/badbase.txt"
BADREQ = f"{Q}/badbase_requeued.json"


def built_on(base):
    """private trunks trunkmerge built on BASE (trunk_registry: '- nova_ptk_X (trunkmerge ...): BASE + donor')"""
    try:
        reg = open("/homes/USER/condor-work/reports/trunk_registry.md", errors="replace").read()
    except OSError:
        return set()
    return set(re.findall(rf"^- (nova_ptk_\w+) \(trunkmerge [^)]*\): {re.escape(base)} \+ ", reg, re.M))


def requeue_bad(base, live):
    """every armed, not yet live bot whose private trunk was built on BASE: marker -> SHIPCHECK.badbase, its shipcheck SIGTERMed (command
    line checked), its line back at the head of the queue (once per bot: bq/badbase_requeued.json)"""
    import signal
    sys.path.insert(0, LAB)
    import armq
    import shipstack
    trunks = built_on(base)
    try:
        done = json.load(open(BADREQ))
    except (OSError, ValueError):
        done = {}
    live_names = {ln.split()[1] for ln in open(f"{Q}/live.txt") if len(ln.split()) > 1}
    try:  # a marker with a verdict keeps its SHIPCHECK file: only not-yet-picked-up (no entry) or running ('started') ones are taken
        sw = json.load(open(f"{Q}/shipwatch_state.json"))
    except (OSError, ValueError):
        sw = {}
    n = 0
    for mk in glob.glob(f"{REPO}/bots/nova_b*/SHIPCHECK"):
        name = os.path.basename(os.path.dirname(mk))
        try:
            kv = dict(ln.strip().split("=", 1) for ln in open(mk) if "=" in ln)
        except OSError:
            continue
        if kv.get("TRUNK") not in trunks or name in live_names or name in done:
            continue
        if isinstance(sw.get(name), dict) and sw[name].get("status") != "started":
            continue
        pids = []
        for q in os.listdir("/proc"):
            if q.isdigit():
                try:
                    c = open(f"/proc/{q}/cmdline", "rb").read().split(b"\0")
                except OSError:
                    continue
                if any(x.endswith(b"shipcheck.py") for x in c) and any(x == name.encode() for x in c):
                    pids.append(int(q))
        try:
            fi = dict(ln.strip().split("=", 1) for ln in open(f"{REPO}/bots/{name}/FLIP") if "=" in ln)
        except OSError:
            fi = {}
        own = shipstack.own_flips(shipstack.parse_flips(fi.get("FLIPS", "")), shipstack.parse_flips(kv.get("LIVEVALS", "")))
        fl = " ".join(f"{k}={v}" for k, v in sorted(own.items()))
        dn = "-"
        if os.path.exists(armq.ARMED_DONORS):
            for ln in open(armq.ARMED_DONORS):
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if d.get("bot") == name:
                    dn = d.get("donors") or "-"
        os.replace(mk, mk + ".badbase")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        done[name] = time.time()
        json.dump(done, open(BADREQ, "w"))
        if not fl and dn == "-":
            say(f"bad base {base}: {name} stopped (marker -> SHIPCHECK.badbase); no own flips or donors: not requeued")
            continue
        slug = re.sub(r"[^a-z0-9]", "", name.split("_", 2)[-1])[:14] + "bb"
        row = dict(donors=dn, flips=fl, lane=kv.get("LANE"), subject=kv.get("SUBJECT"), slug=slug, bugbar=kv.get("BUGBAR") == "1",
                   parambar=kv.get("PARAMBAR") == "1", seqspar=kv.get("SEQSPAR") == "1", rare=kv.get("RARE"), rarefams=kv.get("RAREFAMS"), basehas=kv.get("BASEHAS"), t=time.time(),
                   **({"cls": kv["CLASS"]} if kv.get("CLASS") else {}))
        armq.edit(lambda ls, row=row: [json.dumps(row)] + ls)
        n += 1
        say(f"bad base {base}: {name} stopped (marker -> SHIPCHECK.badbase, shipcheck pids {pids or 'none'}); requeued first as {slug}: {dn} {fl}")
    return n


def bad_base(live, new, why):
    """identity failed: the base is marked bad, diffbase goes back to live (lines arm on live), lines armed on the bad base go back to the
    head of the queue once; arms still building on it are caught by 3 more sweeps over 6 min"""
    say(f"BAD BASE {new}: {why}")
    open(DIFFBASE, "w").write(f"{live} {live} {stamp()} base {new} BAD (identity failed): lines arm on live\n")
    with open(BADBASE, "a") as f:
        f.write(f"{stamp()} {live} {new} {why[:300]}\n")
    for k in range(4):
        try:
            requeue_bad(new, live)
        except Exception as e:  # noqa: BLE001
            say(f"bad base {new}: requeue sweep failed: {str(e)[:200]}")
        if k < 3:
            time.sleep(120)
    return 1


def queued_conflicts():
    """the queued diffs that no longer apply on the new base go back to their agents now (tools/lab/ideas.py conflicts --apply)"""
    r = subprocess.run([sys.executable, "-I", f"{LAB}/ideas.py", "conflicts", "--apply"], capture_output=True, text=True, cwd=REPO)
    for ln in (r.stdout + r.stderr).strip().splitlines():
        say("queued: " + ln.strip()[:220])


if __name__ == "__main__":
    sys.exit(main())
