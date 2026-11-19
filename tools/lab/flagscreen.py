#!/usr/bin/env python3
"""flagscreen: read many small or near-miss upgrades TOGETHER, then hand the winners to the normal ship bar as one bundle
(Tool builder 2, 5 Nov; owner: "leave the bigger upgrades separately tested, and if one fails but is above average, accumulate a
bunch of them and see how well they do with some sort of pairing"; "as long as it does not slow down our pipeline").

usage: python3 -I tools/lab/flagscreen.py pool [--days 4] [--min 0.500]
       python3 -I tools/lab/flagscreen.py run TAG IDEA [IDEA ...] [--n 1200] [--par 2] [--prio -10] [--dry] [--class COND] [--wfams w_a,w_b] [--maps-from DIR]
              (--class 'grc1:>=1' / --wfams: a CLASS screen, every map drawn from that class (stratmaps --class/--wfams); 11 Nov)
       python3 -I tools/lab/flagscreen.py status TAG
       python3 -I tools/lab/flagscreen.py restart TAG     start a dead driver again
       python3 -I tools/lab/flagscreen.py read TAG
  pool   failed shipchecks (behaviour + fix lane, last --days) whose deciding read was above --min, with their flips; drops ones
         whose values are live now and duplicates (newest kept). Says per idea whether it is a data flip of live or needs its code
         merged. Writes /data/zw4424/st/fs/pool.tsv.
  run    IDEA = a pool bot name (nova_b1421_pmsw19) or raw flips "FLAG=V,FLAG2=V2" (a data flip of live). 2-15 ideas. Steps:
         1 integration trunk: live itself when every idea is a data flip of live; else trunkmerge.py merges every needed donor
           onto live with all the ideas' flags at their off values (merge check, build, unlimited-fuel identity v live);
         2 overlap: which ideas' flags are read in a common function (card.py's index); those pairs get their own pair term;
         3 design: a fold-over Hadamard (8 -> 16 arms for <= 7 ideas, 16 -> 32 for <= 15), random columns and signs from TAG:
           every idea is on in half the arms, every pair of ideas in a quarter, so each game informs every idea, and each idea's
           own effect is separable from every pair effect (resolution IV);
         4 arms: flip.sh data flips of the trunk (nova_fs<TAG>aNN; never shippable names);
         5 maps: ONE new set (stratmaps --take, half pathological), hard-linked into every arm's run dir: same maps for all arms;
         6 a detached driver plays each arm v the trunk (flag 0) with stylepanel --fresh-only at Condor priority --prio (-10:
           pilots take these items only when no normal item waits, and they never get the age boost), --par (<= 4) arms at once,
           and starts an arm only while load < 24, free RAM >= 10 GB, home < 55k files (FS_HOME_MAX) and no normal pilot item is queued.
  read   map-level regression y(arm,map) - .5 = sum of idea effects (+ pair terms for overlapping ideas), clustered by map;
         prints each idea's effect, se, z and PICK (z > 1), the pair terms, and the bundle's armq line. The bundle must then pass
         the usual shipcheck (behaviour bar, every row) on new maps: this screen decides nothing on its own. Never arms.
  bank   the FAILED-POSITIVE BANK (owner 5 Nov: "keep it in a failed positive bank for maybe later, but we need to consider how to
         manage this"): ideas that failed a ship bar but read above average, kept across days (not pool's 4-day window).
           bank list [--all]                       active entries, best read first (--all: expired and shipped too)
           bank add ID [--bot BOT] [--donor DONOR:BASE|-] [--flips "F=V ..."] --point P [--n N] [--base vNNN] [--fail ROW]
                       [--cause base-moved|trunk-code|kind-gate|fuel|sequential-stop|power|other] [--inter "..."] [--note ".."] [--lane L]
                       (--bot fills --flips from bots/BOT/FLIP; --donor - = a data flip of live)
           bank expire ID [--why ".."] | bank ship ID [--version vNNN]
           bank seed                               add pool.tsv ideas above .500 not yet banked
           bank check                              every active entry v live: values already live, flips that clear live bits
           bank store ID [--donor DONOR:BASE|-] [--source ".."]  store the idea's patch in tools/lab/bank/ID.diff + ID.json (flags, flips, last
                       base, source, date): DONOR v its true BASE, flag table included, value-only #define hunks for other flags excluded. `bank add`
                       does this too, so no old bot folder is needed later. --donor -: no code, only the sidecar (a data flip, or a table to un-bake)
           bank rebase [--dry] [--only a,b] [--force] [--no-ident]  each active entry onto current live, on a newbot.sh scratch copy: git merge-file
                       against its last base (plain `patch` with fuzz when that folder is gone), un-bakes the tables its flips need, flip.py check,
                       mergecheck static, cxeident 40 games (flag-0 identity); on success regenerates the patch and sets 'last base', on a conflict or
                       failure marks needs-hand-rebase. An entry already on live is skipped. --dry: merge text and flip check only, stores nothing.
           bank power NEW [--maps 10000] [--run]  (b1463, 7 Nov) every active entry with --cause power, combined as `bank combine NEW
                       --cause power` into one flag-0 trunk on live, then ONE bug-bar bundle read as a full 2x2 factorial in halves (entries
                       alternate by read into half A and half B): smokefarm factorial NEW "A flips" "B flips" --design full --maps N v live
                       (N >= 10,000 so -.003 a member shows). Prints the plan; --run starts the read in its own unit (log power_NEW.out).
                       Ship the bundle on no-harm (shipcheck BUGBAR=1); drop the half the factorial puts below.
           bank combine NEW [--drop a,b] [--no-ident] [--cause C]  every entry that merges, best read first, into ONE flag-0 trunk NEW on live; a flag two entries
                       set keeps the higher read; writes /data/zw4424/st/fs/combine_NEW.json (included, dropped, conflicted, the all-on flips)
           bank rescreen [--top 8] [--n 1200] [--dry]   THE POST-SHIP TRIGGER (Builder, after every behaviour ship): screens the
                       top active entries not yet screened on the current live in ONE factorial run (tag bkNNN), merging donors
                       that are not data flips of live into one integration trunk; a donor that no longer merges cleanly is left
                       out and marked needs-rebase (one agent rebases those in a batch). Does nothing while a bank screen runs.
           run and rescreen take an entry's code from its stored patch (a nova_bkp_ID_<sha> copy of its last base) when it has one.
           `read TAG` of a bank screen records each entry's z on that base: PICK (z > 1) bundles as usual; an entry EXPIRES after
           two non-PICK screens on two different bases.
Files: /data/zw4424/st/fs/TAG/ (design.json, log, maps/, result.txt); bank: /data/zw4424/st/fs/bank.json (+ bank.tsv view). Simulation of the gain: tools/lab/flagscreen_sim.py,
docs/merge_queue.md."""
import glob
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
BQ = "/data/zw4424/st/bq"
FS = "/data/zw4424/st/fs"
PANEL = "/data/zw4424/st/panel"


def live():
    return open(f"{BQ}/live.txt").readline().split()[1]


def defs_of(bot):
    import card
    return card.load_index(os.path.join(REPO, "bots", bot, "src"))


def parse_flips(s):
    out = {}
    for x in re.split(r"[,\s]+", s.strip()):
        if x:
            k, v = x.split("=", 1)
            out[k] = v
    return out


def flippable(bot, flips):
    """flip.py check: every flag is a data-only runtime flag of BOT (a baked constexpr table is not: its value is code)"""
    r = subprocess.run(["python3", "-I", os.path.join(HERE, "flip.py"), "check", os.path.join(REPO, "bots", bot, "src"),
                        " ".join(f"{k}={v}" for k, v in flips.items())], capture_output=True, text=True)
    return r.returncode == 0


def num(v):
    try:
        return int(str(v).strip().split()[0].strip("()"), 0)
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------------ pool
def pool(a):
    days = float(a[a.index("--days") + 1]) if "--days" in a else 4
    mn = float(a[a.index("--min") + 1]) if "--min" in a else 0.500
    lv = live()
    _, ldefs = defs_of(lv)
    rows = {}
    for f in sorted(glob.glob(f"{BQ}/shipwatch_nova_*.out"), key=os.path.getmtime):
        if time.time() - os.path.getmtime(f) > days * 86400:
            continue
        s = open(f, errors="ignore").read()
        h = re.search(r"shipcheck (\S+): (nova_\w+) vs live (nova_\w+) \((v\d+)\), lane (\w+)", s)
        if not h or "OVERALL: FAIL" not in s or h.group(5) not in ("behaviour", "fix"):
            continue
        m = (re.search(r"pooled BIG \+ fresh\s+(0\.\d+) \[(0\.\d+), (0\.\d+)\] n (\d+)", s)
             or re.search(r"live h2h(?: \(near-miss ext\))?\s+(0\.\d+) \[(0\.\d+), (0\.\d+)\] n (\d+)", s))
        if not m or float(m.group(1)) <= mn:
            continue
        bot = h.group(2)
        fp = os.path.join(REPO, "bots", bot, "FLIP")
        if not os.path.exists(fp):
            continue
        fl = dict(re.findall(r"^(\w+)=(.*)$", open(fp).read(), re.M))
        flips = parse_flips(fl.get("FLIPS", ""))
        if not flips:
            continue
        tb = re.search(r"trunk built on live (nova_\w+)", s)
        fr = [re.split(r"\s{2,}", x.strip())[0] for x in s[s.rfind(f"SHIPCHECK {h.group(1)}:"):].split("\n")[2:40]
              if x.startswith("  ") and x.rstrip().endswith("FAIL") and "OVERALL" not in x]
        key = " ".join(f"{k}={v}" for k, v in sorted(flips.items()))
        in_live = all(k in ldefs for k in flips)
        shipped = in_live and all(num(ldefs[k][2]) == num(v) for k, v in flips.items())
        in_live = in_live and not shipped and flippable(lv, flips)
        if shipped:
            rows.pop(key, None)
            continue
        rows[key] = dict(bot=bot, tag=h.group(1), lane=h.group(5), point=float(m.group(1)), n=int(m.group(4)), flips=flips,
                         trunk=fl.get("TRUNK"), base=tb.group(1) if tb else h.group(3), kind="data" if in_live else "merge",
                         failed=",".join(fr)[:60] or "?", when=time.strftime("%m-%d %H:%M", time.gmtime(os.path.getmtime(f))))
    os.makedirs(FS, exist_ok=True)
    out = sorted(rows.values(), key=lambda r: -r["point"])
    with open(f"{FS}/pool.tsv", "w") as f:
        f.write("bot\ttag\tlane\tpoint\tn\tkind\ttrunk\tbase\tflips\twhen\tfailed\n")
        for r in out:
            f.write(f"{r['bot']}\t{r['tag']}\t{r['lane']}\t{r['point']:.4f}\t{r['n']}\t{r['kind']}\t{r['trunk']}\t{r['base']}\t"
                    f"{' '.join(f'{k}={v}' for k, v in r['flips'].items())}\t{r['when']}\t{r['failed']}\n")
    print(f"flagscreen pool: {len(out)} failed-but-above-{mn:.3f} ideas in {days:g} days (live {lv}); {FS}/pool.tsv")
    for r in out:
        print(f"  {r['point']:.4f} n{r['n']:5d} {r['lane'][:4]} {r['kind']:5s} {r['bot']:26s} {' '.join(f'{k}={v}' for k, v in r['flips'].items())[:40]:40s} failed: {r['failed']}")
    return out


# ------------------------------------------------------------------ failed-positive bank
BANK = f"{FS}/bank.json"
CAUSES = ("base-moved", "trunk-code", "kind-gate", "fuel", "sequential-stop", "power", "other")  # power (b1463, 7 Nov): a rule-verified fix
# whose pooled read (tools/lab/verdict.py) is UNRESOLVED: its effect is inside what one read can see; read with the others (bank power)


def have_bot(b):
    """A bot's folder, restored from the idea store if it was retired (owner 5 Nov: old bots are deleted, failed positives stay usable)."""
    p = os.path.join(REPO, "bots", b, "src")
    if not os.path.isdir(p):
        subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/ideastore.py"), "restore", b], capture_output=True)
    return os.path.isdir(p)


def bank_load():
    try:
        return json.load(open(BANK))
    except (OSError, ValueError):
        return {}


def bank_save(b):
    os.makedirs(FS, exist_ok=True)
    tmp = f"{BANK}.{os.getpid()}"
    json.dump(b, open(tmp, "w"), indent=1)
    os.replace(tmp, BANK)
    cols = ("id", "state", "point", "n", "base", "lane", "donor", "flips", "fail", "cause", "inter", "added", "screens", "note")
    with open(f"{FS}/bank.tsv", "w") as f:
        f.write("\t".join(cols) + "\n")
        for e in sorted(b.values(), key=lambda e: (e["state"] != "active", -e["point"])):
            f.write("\t".join(" ".join(f"{x['tag']}:{x['base']}:{x['res']}{x['z']:+.2f}" for x in e["screens"]) if c == "screens"
                              else str(e.get(c, "")) for c in cols) + "\n")


def clears_live_bits(flips, ldefs):
    """[(flag, live, flip, suggested)] for each *_BITS flag the flip sets to a value that CLEARS a bit live has set (Builder 5 Nov:
    g1r GPV_BITS=1 on a live 9 would switch the holefield gate off; g3 GPV_BITS=2 would switch G1 off)"""
    out = []
    for f, v in flips.items():
        if not f.endswith("_BITS") or f not in ldefs:
            continue
        lvv, fv = num(ldefs[f][2]), num(v)
        if lvv is not None and fv is not None and lvv & ~fv:
            out.append((f, lvv, fv, lvv | fv))
    return out


# ------------------------------------------------------------------ patch store (owner 5 Nov: "why do we not just store git diffs so we can
# merge the ideas easier"): tools/lab/bank/ID.diff (the idea's hunks) + ID.json (flags, flips, last base, source, date, status)
PATCHD = os.path.join(HERE, "bank")
SRC_EXT = (".h", ".hpp", ".cpp", ".cc", ".c")


def pack_load(eid):
    try:
        return json.load(open(f"{PATCHD}/{eid}.json"))
    except (OSError, ValueError):
        return {}


def pack_diff(eid):
    try:
        return open(f"{PATCHD}/{eid}.diff", encoding="utf-8", errors="surrogateescape").read()
    except OSError:
        return ""


def pack_save(eid, pk, diff=None):
    os.makedirs(PATCHD, exist_ok=True)
    if diff is not None:
        pth = f"{PATCHD}/{eid}.diff"
        if diff:
            open(f"{pth}.new.{os.getpid()}", "w", encoding="utf-8", errors="surrogateescape").write(diff)
            os.replace(f"{pth}.new.{os.getpid()}", pth)
        elif os.path.exists(pth):
            os.remove(pth)
        pk["kind"] = "code" if diff else "data"
        pk["hunks"] = len(re.findall(r"^@@ ", diff, re.M))
        pk["plus_minus"] = [len(re.findall(r"^\+(?!\+\+)", diff, re.M)), len(re.findall(r"^-(?!--)", diff, re.M))]
    pth = f"{PATCHD}/{eid}.json"
    json.dump(pk, open(f"{pth}.new.{os.getpid()}", "w"), indent=1)
    os.replace(f"{pth}.new.{os.getpid()}", pth)


def src_of(x):
    return (x if "/" in x else os.path.join(REPO, "bots", x)) + "/src"


def rd(p):
    return open(p, encoding="utf-8", errors="surrogateescape").read()


def wr(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", errors="surrogateescape").write(t)


def filter_values(dt, bt, flips, dropped):
    """donor text with every value-only `#define OTHER v` change put back to the base's (b1218: an old trunk's values for other flags would revert
    live's); the idea's own flags keep the base's value (the flip sets them), and a new *_BITS flag the donor left on goes to 0"""
    pat = re.compile(r"^#define[ \t]+(\w+)[ \t]+([^\s/]+)", re.M)
    names = lambda t: [m.group(1) for m in pat.finditer(t)]  # noqa: E731
    bn, dn = names(bt), names(dt)
    bl = {m.group(1): m for m in pat.finditer(bt)}

    def sub(m):
        nm, v = m.group(1), m.group(2)
        if nm not in bl:
            if nm in flips and nm.endswith("_BITS") and num(v) and num(v) == num(flips[nm]):
                return f"#define {nm} 0"
            return m.group(0)
        if bn.count(nm) != 1 or dn.count(nm) != 1 or bl[nm].group(2) == v:
            return m.group(0)
        if nm not in flips:
            dropped.append(f"{nm} {bl[nm].group(2)}->{v}")
        return bl[nm].group(0)
    return pat.sub(sub, dt)


def tree_diff(asrc, bsrc):
    """unified diff (a/src/F, b/src/F, 6 lines of context) of two src dirs over the given {file: text}; no index lines, nova_all.cpp is generated"""
    d = tempfile.mkdtemp(prefix="bkp")
    try:
        for tag, tree in (("a", asrc), ("b", bsrc)):
            os.makedirs(f"{d}/{tag}/src")
            for f, t in tree.items():
                wr(f"{d}/{tag}/src/{f}", t)
        r = subprocess.run(["git", "diff", "--no-index", "--no-color", "--no-prefix", "-U6", "a", "b"], cwd=d, capture_output=True)
        return "".join(ln for ln in r.stdout.decode("utf-8", "surrogateescape").splitlines(True) if not ln.startswith("index "))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def changed_trees(asrc_dir, bsrc_dir):
    aa, bb = {}, {}
    for f in sorted(os.listdir(bsrc_dir)):
        if not f.endswith(SRC_EXT) or f == "nova_all.cpp" or not os.path.isfile(f"{bsrc_dir}/{f}"):
            continue
        bt = rd(f"{bsrc_dir}/{f}")
        at = rd(f"{asrc_dir}/{f}") if os.path.exists(f"{asrc_dir}/{f}") else None
        if at != bt:
            bb[f] = bt
            if at is not None:
                aa[f] = at
    return aa, bb


def make_patch(dn, base, flips):
    dropped = []
    aa, bb = changed_trees(src_of(base), src_of(dn))
    bb = {f: filter_values(t, aa.get(f, ""), flips, dropped) for f, t in bb.items()}
    keep = [f for f in bb if bb[f] != aa.get(f)]
    return tree_diff({f: aa[f] for f in keep if f in aa}, {f: bb[f] for f in keep}), dropped


def pack_store(e, donor, source=None):
    """write ID.diff + ID.json from DONOR:BASE (a bot name or a path), or the sidecar alone for '-'"""
    pk = dict(id=e["id"], flags=sorted(e["flips"]), flips=e["flips"], source=source or donor, date=stamp_now(), status="new")
    if donor and ":" in donor and donor != "-":
        dn, base = donor.split(":", 1)
        if not (have_bot(dn) and have_bot(base)):  # 9 Nov: retired donors come back from the idea store (b1750 backfill)
            pk["note"] = f"donor {donor} not on this machine: no patch"
            pack_save(e["id"], pk)
            return "WARNING: " + pk["note"]
        diff, dropped = make_patch(dn, base, e["flips"])
        pk.update(last_base=os.path.basename(base), excluded=dropped)
        pack_save(e["id"], pk, diff)
        big = pk["plus_minus"][0] + pk["plus_minus"][1] > 400
        return (f"patch {pk['hunks']} hunks +{pk['plus_minus'][0]} -{pk['plus_minus'][1]}, excluded {len(dropped)} value-only defines"
                + (" WARNING: big; DONOR is a whole trunk? give the idea's own donor:parent" if big else ""))
    pk.update(last_base=None)
    pack_save(e["id"], pk, "")
    return "no code: sidecar only"


def split_patch(diff):
    out = []
    for part in re.split(r"(?m)^(?=diff --git )", diff):
        m = re.search(r"(?m)^\+\+\+ b/src/(\S+)", part)
        if part.strip() and m:
            out.append((m.group(1), part))
    return out


def merge_additive(pt, pb, pd):
    m = subprocess.run(["git", "merge-file", "-p", "--diff3", pt, pb, pd], capture_output=True)
    blocks = re.findall(rb"^\|{7}[^\n]*\n(.*?)^={7}$", m.stdout, re.M | re.S)
    return bool(blocks) and all(not x.strip() for x in blocks)


def apply_patch(diff, dest, base=None):
    """the patch onto src dir DEST: 3-way (git merge-file) when BASE, the src dir it was made on, still exists; else `patch` with fuzz.
    Writes nothing when any file conflicts. Returns (conflicting files, 'merge'|'fuzz')."""
    bad, out, how = [], {}, "merge" if base and os.path.isdir(base) else "fuzz"
    tmp = tempfile.mkdtemp(prefix="bka")
    try:
        for f, part in split_patch(diff):
            os.makedirs(f"{tmp}/w/src", exist_ok=True)
            pp = f"{tmp}/part"
            wr(pp, part)
            new_file = "--- /dev/null" in part.split("@@")[0]
            for x in (f"{tmp}/w/src/{f}", ):
                if os.path.exists(x):
                    os.remove(x)
            if how == "merge":
                if not new_file:
                    shutil.copyfile(f"{base}/{f}", f"{tmp}/w/src/{f}")
            elif os.path.exists(f"{dest}/{f}") and not new_file:
                shutil.copyfile(f"{dest}/{f}", f"{tmp}/w/src/{f}")
            r = subprocess.run(["patch", "-s", "-p1", "-d", f"{tmp}/w", "-F", "0" if how == "merge" else "2", "--no-backup-if-mismatch", "-r", "-", "-i", pp],
                               capture_output=True)
            if r.returncode != 0:
                bad.append(f + " (patch rejected)")
                continue
            if how == "fuzz" or new_file:
                if new_file and os.path.exists(f"{dest}/{f}") and rd(f"{dest}/{f}") != rd(f"{tmp}/w/src/{f}"):
                    bad.append(f + " (new file exists)")
                    continue
                out[f] = rd(f"{tmp}/w/src/{f}")
                continue
            m = subprocess.run(["git", "merge-file", "-p", f"{dest}/{f}", f"{base}/{f}", f"{tmp}/w/src/{f}"], capture_output=True)
            if m.returncode != 0:
                if merge_additive(f"{dest}/{f}", f"{base}/{f}", f"{tmp}/w/src/{f}"):
                    # 9 Nov (b1750, rgr_rare): --union interleaved two added functions that share closing lines; both sides only add here,
                    # so each conflict becomes live's block, then the donor's, whole
                    t = additive_concat(f"{dest}/{f}", f"{base}/{f}", f"{tmp}/w/src/{f}")
                    m = subprocess.CompletedProcess(m.args, 0, t.encode("utf-8", "surrogateescape"), b"")
                else:
                    bad.append(f"{f} ({m.returncode} conflicts)")
                    continue
            out[f] = m.stdout.decode("utf-8", "surrogateescape")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not bad:
        for f, t in out.items():
            wr(f"{dest}/{f}", t)
    return bad, how


def unbake(src, flips):
    """a baked table holding a flip's flag becomes runtime data (`inline constexpr int` -> `inline const volatile int`): what b1218 did by hand"""
    done = []
    for f in sorted(os.listdir(src)):
        if not f.endswith(SRC_EXT) or f == "nova_all.cpp":
            continue
        t = rd(f"{src}/{f}")

        def sub(m):
            if any(re.search(rf"\b{re.escape(k)}\b", m.group(0)) for k in flips):
                done.append(m.group(1))
                return m.group(0).replace("inline constexpr int", "inline const volatile int", 1)
            return m.group(0)
        n = re.sub(r"^inline constexpr int (\w+)\[\d*\]\s*=\s*\{[^;]*?\};", sub, t, flags=re.M)
        if n != t:
            wr(f"{src}/{f}", n)
    return done


def only_unbake(diff):
    """True when every changed line of the patch is a table going from `inline constexpr int` to `inline const volatile int`"""
    rm = [ln[1:] for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    ad = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    return bool(rm) and [x.replace("inline constexpr int", "inline const volatile int", 1) for x in rm] == ad


def unity(src):
    if os.path.isfile(f"{src}/nova_all.cpp"):
        return subprocess.run(["sh", os.path.join(REPO, "tools/lab/mkunity.sh"), src], capture_output=True).returncode == 0
    return True


def scratch_copy(base, name):
    r = subprocess.run(["sh", os.path.join(HERE, "newbot.sh"), base, name], capture_output=True, text=True,
                       env=dict(os.environ, NEWBOT_UNBAKED="1"))  # 10 Nov (TB rebase pass): newbot copied the baked diffbase, so every rebase diff carried base-v-live
    if r.returncode != 0:
        sys.exit(f"flagscreen: newbot.sh {base} {name}: {(r.stdout + r.stderr)[-200:]}")
    d = os.path.realpath(os.path.join(REPO, "bots", name))
    if any(os.path.islink(os.path.join(p, x)) for p, ds, fs in os.walk(d) for x in ds + fs):
        sys.exit(f"flagscreen: {d} holds symlinks")
    return d


def drop_copy(name):
    """remove a copy this process made with scratch_copy (bots/NAME link + its /data folder), never anything else"""
    ln = os.path.join(REPO, "bots", name)
    d = f"/data/zw4424/st/new/bots/{name}"
    if os.path.islink(ln) and os.path.realpath(ln) == d:
        os.remove(ln)
        shutil.rmtree(d, ignore_errors=True)


def entry_donor(e):
    """DONOR:BASE for trunkmerge: from the stored patch when the entry has one (a nova_bkp_ID_<sha> copy of its last base, reused while the patch is
    the same), else the bank's donor if both folders exist, else None"""
    pk = pack_load(e["id"])
    diff = pack_diff(e["id"])
    if pk.get("kind") == "code" and diff and pk.get("status") != "needs-hand-rebase":
        base = pk.get("last_base") or live()
        if not have_bot(base):
            base = live()
        nm = f"nova_bkp_{e['id']}_{hashlib.sha1((base + diff).encode('utf-8', 'surrogateescape')).hexdigest()[:6]}"
        if os.path.isdir(os.path.join(REPO, "bots", nm, "src")):
            return f"{nm}:{base}"
        d = scratch_copy(base, nm)
        bad, _ = apply_patch(diff, f"{d}/src", src_of(pk["last_base"]) if pk.get("last_base") else None)
        if bad or not unity(f"{d}/src"):
            drop_copy(nm)
            return None
        return f"{nm}:{base}"
    dn = e.get("donor")
    if dn and dn != "-" and ":" in dn and all(have_bot(x) for x in dn.split(":")):
        return dn
    return None


def wait_room(gate=3600):
    """local work waits while load > 24 or free RAM < 10 GB (at most GATE s)"""
    t0 = time.time()
    while time.time() - t0 < gate:
        la = float(open("/proc/loadavg").read().split()[0])
        fr = int(re.search(r"MemAvailable:\s+(\d+)", open("/proc/meminfo").read()).group(1)) / 1e6
        if la <= 24 and fr >= 10:
            return
        time.sleep(60)


def identity(old, new, log):
    """cxeident OLD NEW, 40 games at unlimited fuel; (ok, line with the fuel)"""
    wait_room()
    with open(log, "w") as f:
        r = subprocess.run(["nice", "-n", "10", "python3", "-I", os.path.join(REPO, "tools/cxe/cxeident.py"), old, new, "--maps", "20", "--jobs", "4"],
                           cwd=REPO, stdout=f, stderr=subprocess.STDOUT)
    tail = [ln for ln in rd(log).splitlines() if ln.strip()][-3:]
    return r.returncode == 0, " | ".join(tail)[:300]


def set_needs(eid, msg):
    b = bank_load()
    if eid in b:
        b[eid]["needs"] = msg
        bank_save(b)


def additive_concat(ours, base, theirs):
    """Both sides only ADD lines to base (merge_additive checked): each side's added blocks, whole, at their base position; where both add at
    the same spot, ours (live) first, then theirs (the donor). git's conflict hunk leaves shared closing lines outside, so pasting its two
    halves together (or --union) breaks functions apart."""
    import difflib
    rd_ = lambda p: open(p, encoding="utf-8", errors="surrogateescape").read().splitlines(keepends=True)  # noqa: E731
    b, o, t = rd_(base), rd_(ours), rd_(theirs)
    ins = {}
    for side, x in ((0, o), (1, t)):
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b, x, autojunk=False).get_opcodes():
            if op == "insert":
                ins.setdefault(i1, [[], []])[side] += x[j1:j2]
    out = []
    for i in range(len(b) + 1):
        if i in ins:
            a_, c_ = ins[i]
            out += a_ + (c_ if c_ != a_ else [])
        if i < len(b):
            out.append(b[i])
    return "".join(out)


def normalize_bits(dsrc, lsrc, flips):
    """11 Nov (RC: stored packs carried old bake states; rebases set live's FB6_BITS 56 -> 0 and un-baked R2B): in the merged copy DSRC,
    every `#define X_BITS v` and every X_TAB declaration whose value / constexpr-volatile state differs from live's (LSRC) is put back to
    live's line, unless the entry's own FLIPS name it (by flag or table stem; unbake() made those volatile on purpose). -> changed names"""
    names = (set(flips) if isinstance(flips, dict)  # 11 Nov (b1827): bank entries store flips as a dict {'TDV_BITS': '1'}
             else {kv.split("=", 1)[0] for kv in (flips or "").replace(",", " ").split() if "=" in kv})
    stems = {x.split("_")[0] for x in names}
    live_def, live_tab = {}, {}
    for f in os.listdir(lsrc):
        if f.endswith((".h", ".cpp", ".cc")):
            for ln in open(os.path.join(lsrc, f), errors="replace"):
                m = re.match(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*_BITS)\s+\S+", ln)
                if m:
                    live_def[m.group(1)] = ln
                m = re.search(r"\b(?:constexpr|const\s+volatile)\s+\w+\s+([A-Z][A-Z0-9_]*_TAB)\s*\[", ln)
                if m:
                    live_tab[m.group(1)] = ln
    done = []
    for f in os.listdir(dsrc):
        if not f.endswith((".h", ".cpp", ".cc")):
            continue
        p = os.path.join(dsrc, f)
        lines = open(p, errors="replace").readlines()
        ch = False
        for i, ln in enumerate(lines):
            m = re.match(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*_BITS)\s+\S+", ln)
            if m and m.group(1) in live_def and live_def[m.group(1)].split() != ln.split() and m.group(1) not in names \
                    and m.group(1).split("_")[0] not in stems:
                lines[i], ch = live_def[m.group(1)], True
                done.append(m.group(1))
                continue
            m = re.search(r"\b(?:constexpr|const\s+volatile)\s+\w+\s+([A-Z][A-Z0-9_]*_TAB)\s*\[", ln)
            if m and m.group(1) in live_tab and live_tab[m.group(1)] != ln and m.group(1)[:-4] not in stems \
                    and ("volatile" in ln) != ("volatile" in live_tab[m.group(1)]):
                lines[i], ch = live_tab[m.group(1)], True
                done.append(m.group(1))
        if ch:
            open(p + ".tmp", "w").write("".join(lines))
            os.replace(p + ".tmp", p)
    return done


def bank_rebase(a, b):
    """every active entry onto current live, one by one, each on its own scratch copy"""
    lv, vv = live(), live_version()
    dry, force = "--dry" in a, "--force" in a
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    rows = sorted((e for e in b.values() if e["state"] == "active" and (not only or e["id"] in only)), key=lambda e: -e["point"])
    logd = f"{FS}/rebase_{vv}"
    os.makedirs(logd, exist_ok=True)
    tally = dict(ok=0, data=0, current=0, conflict=0)
    for e in rows:
        eid = e["id"]
        pk = pack_load(eid)
        if not pk:  # first time: store from the bank's donor if it is there
            print(f"  {eid}: no pack; " + pack_store(e, e.get("donor") or "-"), flush=True)
            pk = pack_load(eid)
        if pk.get("last_base") == lv and pk.get("status") == "ok" and not force:
            tally["current"] += 1
            print(f"  {eid}: current on {vv}", flush=True)
            continue
        diff = pack_diff(eid)
        nm = f"nova_bkr_{eid}_{os.getpid()}"
        d = scratch_copy(lv, nm)
        try:
            base = src_of(pk["last_base"]) if pk.get("last_base") else None
            bad, how = apply_patch(diff, f"{d}/src", base) if diff else ([], "none")
            why = ""
            if bad:
                why = "conflict: " + ", ".join(bad)
            else:
                ub = unbake(f"{d}/src", e["flips"])
                nb = normalize_bits(f"{d}/src", src_of(lv), e["flips"])
                if nb:
                    print(f"  {eid}: reset to live's bake state: {', '.join(nb[:6])}", flush=True)
                if e["flips"] and not flippable(nm, e["flips"]):
                    why = "flip.py check refuses its flips on the merged copy"
                elif not unity(f"{d}/src"):
                    why = "mkunity failed"
            new = ""
            if not why:
                aa, bb = changed_trees(src_of(lv), f"{d}/src")
                new = tree_diff(aa, bb)
            if dry:
                print(f"  {eid}: {'NEEDS-HAND-REBASE ' + why if why else 'merges'} ({how}; {'data flip' if not new and not why else str(len(split_patch(new))) + ' files'})", flush=True)
                tally["conflict" if why else "data" if not new else "ok"] += 1
                continue
            res = ""
            if not why and new:
                r = subprocess.run(["python3", "-I", os.path.join(HERE, "mergecheck.py"), nm, lv, "--no-build", "--no-play", "--quiet"], cwd=REPO,
                                   capture_output=True, text=True)
                open(f"{logd}/{eid}.mc", "w").write(r.stdout + r.stderr)
                if r.returncode != 0:
                    why = "mergecheck static FAIL: " + next((ln for ln in (r.stdout + r.stderr).splitlines() if "FAIL" in ln), "")[:160]
            if not why and new and "--no-ident" not in a:  # --no-ident: a build and 40 games per entry take ~50 min in all; `bank combine` identity-checks them together
                ok, res = identity(lv, nm, f"{logd}/{eid}.ident")
                if not ok:
                    why = "flag-0 identity failed or no build: " + res[:160]
            pk = pack_load(eid)
            pk.update(date=stamp_now(), last_try=vv)
            if why:
                pk.update(status="needs-hand-rebase", note=why)
                pack_save(eid, pk)
                set_needs(eid, f"rebase by hand: {why[:160]} ({stamp_now()})")
                tally["conflict"] += 1
                print(f"  {eid}: NEEDS-HAND-REBASE {why}", flush=True)
                continue
            pk.update(status="ok", last_base=lv, last_base_version=vv, ident=("not run" if "--no-ident" in a else "40/40") if new else "no code", note=res)
            pack_save(eid, pk, new)
            set_needs(eid, "")
            tally["ok" if new else "data"] += 1
            print(f"  {eid}: ok on {vv} ({how}; {pk['hunks']} hunks +{pk['plus_minus'][0]} -{pk['plus_minus'][1]}; un-baked {','.join(ub) or '-'}; {pk['ident']})", flush=True)
        finally:
            drop_copy(nm)
    print(f"bank rebase on {vv} ({lv}){' --dry' if dry else ''}: {tally}", flush=True)


def bank_combine(a, b):
    """every entry that merges into one flag-0 trunk on live, best read first"""
    new = a[2]
    lv, vv = live(), live_version()
    ldefs = defs_of(lv)[1]
    dropl = set(a[a.index("--drop") + 1].split(",")) if "--drop" in a else set()
    d = scratch_copy(lv, new)
    inc, drop, conf = [], [], []
    owner = {}
    cause = a[a.index("--cause") + 1] if "--cause" in a else None
    for e in sorted((e for e in b.values() if e["state"] == "active" and (cause is None or e.get("cause") == cause)), key=lambda e: -e["point"]):
        eid = e["id"]
        pk = pack_load(eid)
        shared = [f for f in e["flips"] if f in owner]
        cl = clears_live_bits(e["flips"], ldefs)
        if eid in dropl:
            drop.append((eid, "--drop"))
        elif not e["flips"]:
            drop.append((eid, "no runtime flag: an all-on read cannot see it"))
        elif shared:
            drop.append((eid, f"sets {','.join(shared)} as {owner[shared[0]]} does (higher read)"))
        elif cl and not e.get("allow_clear"):
            drop.append((eid, "clears live bits: " + ", ".join(f"{f} {x}->{y}" for f, x, y, _ in cl)))
        elif all(f in ldefs and num(ldefs[f][2]) == num(v) for f, v in e["flips"].items()):
            drop.append((eid, "its values are live"))
        elif pk.get("status") != "ok":
            conf.append((eid, f"patch: {pk.get('status')} {pk.get('note', '')[:140]} (bank rebase)"))
        else:  # 3-way from the patch's own last base: live may have moved since the last rebase; the trunk's identity below decides
            # an un-bake-only patch is left to unbake() below: a merge calls that one-line edit a conflict with any code added on the next line (bk1: tdn1 v htd1)
            bad, _ = apply_patch(pack_diff(eid), f"{d}/src", src_of(pk["last_base"]) if pk.get("last_base") else None) if pack_diff(eid) and not only_unbake(pack_diff(eid)) else ([], "")
            if bad:
                conf.append((eid, "conflicts with the earlier entries: " + ", ".join(bad)))
                continue
            inc.append(eid)
            for f in e["flips"]:
                owner[f] = eid
    flips = {f: v for x in inc for f, v in b[x]["flips"].items()}
    unbake(f"{d}/src", flips)
    if not unity(f"{d}/src"):
        sys.exit("flagscreen: mkunity failed on " + new)
    r = subprocess.run(["python3", "-I", os.path.join(HERE, "flip.py"), "check", f"{d}/src", " ".join(f"{k}={v}" for k, v in flips.items())], capture_output=True, text=True)
    res = dict(new=new, live=lv, version=vv, included=inc, dropped=drop, conflicted=conf, flips=flips, per={x: b[x]["flips"] for x in inc}, flip_check=r.returncode,
               date=stamp_now())
    if "--no-ident" not in a:
        res["ident_ok"], res["ident"] = identity(lv, new, f"{FS}/combine_{new}.ident")
    json.dump(res, open(f"{FS}/combine_{new}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
    print(f'all on: sh tools/lab/flip.sh {new} {new}_on "' + " ".join(f"{k}={v}" for k, v in flips.items()) + '"')
    return res


def bank_power(a, b):
    """b1463 (7 Nov): the POWER entries as one bundle read, factorial in halves"""
    if len(a) < 3:
        sys.exit("flagscreen bank power NEW [--maps 10000] [--run]")
    new, maps = a[2], int(a[a.index("--maps") + 1]) if "--maps" in a else 10000
    pw = [e for e in b.values() if e["state"] == "active" and e.get("cause") == "power"]
    if len(pw) < 2:
        sys.exit(f"flagscreen bank power: {len(pw)} active entry with --cause power; a bundle in halves needs 2 or more")
    if maps < 10000:
        print(f"note: --maps {maps} < 10000: -.003 a member will not show (b1463)")
    res = bank_combine(["bank", "combine", new, "--cause", "power"] + (["--no-ident"] if "--no-ident" in a else []), b)
    inc = res["included"]
    if len(inc) < 2:
        sys.exit(f"flagscreen bank power: {len(inc)} entry merged ({res['dropped'] + res['conflicted']}); no halves to read")
    if "--no-ident" not in a and not res.get("ident_ok"):
        sys.exit(f"flagscreen bank power: {new} failed flag-0 identity v live ({FS}/combine_{new}.ident): not read")
    order = sorted(inc, key=lambda x: -b[x]["point"])
    half = [order[0::2], order[1::2]]
    fl = [" ".join(f"{k}={v}" for x in h for k, v in b[x]["flips"].items()) for h in half]
    tag = re.sub(r"[^a-z0-9]", "", f"pw{new.lower()}")[-20:]
    cmd = ["python3", "-I", os.path.join(HERE, "smokefarm.py"), "factorial", new, fl[0], fl[1], "--design", "full", "--maps", str(maps),
           "--vs", live(), "--tag", tag, "--json", f"{FS}/power_{new}.json"]
    print(f"half A ({len(half[0])}): {', '.join(half[0])}: {fl[0]}\nhalf B ({len(half[1])}): {', '.join(half[1])}: {fl[1]}")
    print("read: " + " ".join(f"'{x}'" if " " in x else x for x in cmd))
    print(f"then: the AB row is the bundle (ship on no-harm, BUGBAR=1); the A and B main effects say which half to drop")
    if "--run" in a:
        r = subprocess.run(["sh", "tools/lab/detach.sh", "-l", f"{FS}/power_{new}.out", "-d", REPO, "-n", "10", f"fs-power-{tag}"] + cmd,
                           cwd=REPO, capture_output=True, text=True)
        print(f"started: log {FS}/power_{new}.out" if r.returncode == 0 else f"detach.sh failed: {(r.stdout + r.stderr)[-300:]}")


def bank_entry_kind(e, lv):
    if not e["flips"]:
        return "code"  # no runtime flag: a factorial screen can't switch it (e.g. always_inline); read alone
    if pack_load(e["id"]).get("kind") == "code":  # a stored patch: the flags may be flippable on live while their code is not there (fbb9's bit 8 gate)
        return "merge"
    return "data" if flippable(lv, e["flips"]) else "merge"


def bank(a):
    sub = a[1] if len(a) > 1 else "list"
    b = bank_load()
    opt = lambda k, v=None: a[a.index(k) + 1] if k in a else v  # noqa: E731
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    if sub == "list":
        lv = live()
        rows = sorted(b.values(), key=lambda e: (e["state"] != "active", -e["point"]))
        print(f"failed-positive bank: {sum(e['state'] == 'active' for e in rows)} active / {len(rows)} entries (live {lv}); {FS}/bank.tsv")
        for e in rows:
            if e["state"] != "active" and "--all" not in a:
                continue
            sc = " ".join(f"{x['res']}{x['z']:+.1f}@{x['base']}" for x in e["screens"]) or "-"
            print(f"  {e['state'][:6]:6s} {e['id']:8s} {e['point']:.4f} n{e.get('n') or 0:6d} base {e.get('base') or '?':5s} {e['lane'][:4]:4s} "
                  f"{(e['donor'] or '-')[:34]:34s} {' '.join(f'{k}={v}' for k, v in e['flips'].items())[:34]:34s} {e.get('cause', '')[:12]:12s} screens {sc}"
                  f" patch {pack_load(e['id']).get('status', '-')}@{pack_load(e['id']).get('last_base_version', '?')}")
        return
    if sub in ("add", "store", "expire", "ship") and (len(a) < 3 or a[2].startswith("-")):  # 12 Nov (Planner: 'bank add --help' made an entry '--help')
        sys.exit(__doc__ if len(a) > 2 and a[2] in ("-h", "--help") else f"flagscreen bank {sub}: the first argument is the entry ID, not an option ({a[2] if len(a) > 2 else 'missing'})")
    if sub == "add":
        eid = a[2]
        bot = opt("--bot")
        flips = parse_flips(opt("--flips", "")) if opt("--flips") else {}
        if bot and not flips and have_bot(bot) and os.path.exists(os.path.join(REPO, "bots", bot, "FLIP")):
            fl = dict(re.findall(r"^(\w+)=(.*)$", open(os.path.join(REPO, "bots", bot, "FLIP")).read(), re.M))
            flips = parse_flips(fl.get("FLIPS", ""))
        cause = opt("--cause", "other")
        if cause not in CAUSES:
            sys.exit(f"flagscreen bank: --cause one of {', '.join(CAUSES)}")
        b[eid] = dict(id=eid, state="active", bot=bot, donor=opt("--donor", "-"), flips=flips, point=float(opt("--point", 0)),
                      n=int(opt("--n", 0)), base=opt("--base"), lane=opt("--lane", "behaviour"), fail=opt("--fail", ""), cause=cause,
                      inter=opt("--inter", ""), note=opt("--note", ""), added=stamp, screens=[], needs="", allow_clear="--allow-clear" in a)
        bank_save(b)
        print(f"banked {eid}: {b[eid]['flips']} donor {b[eid]['donor']} point {b[eid]['point']}")
        print("  " + pack_store(b[eid], b[eid]["donor"]))
        cl = clears_live_bits(flips, defs_of(live())[1])
        if cl and not b[eid]["allow_clear"]:
            print("  WARNING: clears bits live has set: " + ", ".join(f"{f} live {x} -> {y} (use {f}={c})" for f, x, y, c in cl)
                  + "; rescreen will skip it unless re-added with --allow-clear")
        return
    if sub in ("expire", "ship"):
        eid = a[2]
        if eid not in b:
            sys.exit(f"flagscreen bank: no entry {eid}")
        b[eid]["state"] = "expired" if sub == "expire" else "shipped"
        b[eid]["note"] = (b[eid].get("note", "") + f"; {sub} {stamp} {opt('--why', '') or opt('--version', '')}").strip("; ")
        bank_save(b)
        print(f"{eid}: {b[eid]['state']}")
        return
    if sub == "seed":
        n0 = len(b)
        try:
            lines = open(f"{FS}/pool.tsv").read().split("\n")[1:]
        except OSError:
            lines = []
        have = {" ".join(f"{k}={v}" for k, v in sorted(e["flips"].items())) for e in b.values()}
        for ln in lines:
            x = ln.split("\t")
            if len(x) < 11 or float(x[3]) <= 0.5:
                continue
            fl = parse_flips(x[8])
            if " ".join(f"{k}={v}" for k, v in sorted(fl.items())) in have:
                continue
            eid = re.sub(r"^nova_b\d+_", "", x[0])[:8]
            b[eid] = dict(id=eid, state="active", bot=x[0], donor="-" if x[5] == "data" else f"{x[6]}:{x[7]}", flips=fl, point=float(x[3]),
                          n=int(x[4]), base=None, lane=x[2], fail=x[10], cause="other", inter="", note=f"from pool {x[1]}", added=stamp, screens=[])
        bank_save(b)
        print(f"bank seed: {len(b) - n0} added from pool.tsv ({len(b)} entries)")
        return
    if sub == "stale":
        return bank_stale(b, int(a[2]) if len(a) > 2 and a[2].isdigit() else 690)
    if sub == "rescreen":
        return bank_rescreen(a, b)
    if sub == "store":
        if a[2] not in b:
            sys.exit(f"flagscreen bank: no entry {a[2]}")
        if "--donor" not in a and pack_load(a[2]):  # the bank's donor is often a whole old trunk: never overwrite a rebased patch with it by accident (bk1: g3)
            sys.exit(f"flagscreen bank store: {a[2]} has a pack ({pack_load(a[2]).get('status')}); name --donor DONOR:BASE or - to replace it")
        dn = opt("--donor", b[a[2]].get("donor") or "-")
        print(f"{a[2]}: " + pack_store(b[a[2]], dn, opt("--source")))
        if "--donor" in a and ":" in dn and b[a[2]].get("donor") in (None, "", "-"):  # 9 Nov (Builder, b1750): rescreen reads the entry's donor too
            b[a[2]]["donor"] = dn
            bank_save(b)
        return
    if sub == "rebase":
        return bank_rebase(a, b)
    if sub == "combine":
        bank_combine(a, b)
        return
    if sub == "power":
        return bank_power(a, b)
    if sub == "check":  # every active entry against the current live: bits cleared, values already live
        lv = live()
        ld = defs_of(lv)[1]
        for e in sorted(b.values(), key=lambda e: -e["point"]):
            if e["state"] != "active":
                continue
            cl = clears_live_bits(e["flips"], ld)
            same = e["flips"] and all(f in ld and num(ld[f][2]) == num(v) for f, v in e["flips"].items())
            print(f"  {e['id']:8s} {' '.join(f'{k}={v}' for k, v in e['flips'].items())[:50]:50s} "
                  + ("ALREADY LIVE" if same else ("CLEARS " + ", ".join(f"{f} {x}->{y} (use {c})" for f, x, y, c in cl)) if cl else "ok"))
        return
    sys.exit(__doc__)


def live_version():
    return open(f"{BQ}/live.txt").readline().split()[0]


def start_driver(tag, d):
    """in its own systemd unit (maple05: whatever a Claude session starts, setsid included, dies with the session's scope; bk524's driver did)"""
    r = subprocess.run(["sh", "tools/lab/detach.sh", "-l", f"{d}/drive.out", "-d", REPO, "-n", "10", f"fs-{tag}", "python3", "-I", os.path.abspath(__file__), "drive", tag],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"flagscreen: detach.sh failed for {tag}: {(r.stdout + r.stderr)[-300:]}")


def driver_alive(tag):
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cl = open(f"/proc/{pid}/cmdline").read().split("\0")
        except OSError:
            continue
        if ("drive" in cl or "run" in cl) and tag in cl and any(x.endswith("flagscreen.py") for x in cl):
            return True
    return False


RESCREEN_ALARM = "/data/zw4424/st/bq/bankrescreen.alarm"  # 10 Nov (Planner): a failed re-screen is an ALARM line (healthwatch shows it)


def build_fail_files(tag):
    """the source files a failed integration build names (src/FILE:LINE:COL: error), from trunkmerge.out and the build log it names"""
    try:
        txt = open(f"{FS}/{tag}/trunkmerge.out", errors="replace").read()
    except OSError:
        return set()
    m = re.search(r"full log (\S+?)\)", txt)
    if m:
        try:
            txt += open(m.group(1), errors="replace").read()
        except OSError:
            pass
    return set(re.findall(r"/src/([\w.]+):\d+:\d+: error", txt))


def donor_touches(dn, files):
    """files (basenames) whose content differs between DONOR and BASE src (a DONOR:BASE string)"""
    try:
        d, bs = (src_of(x) for x in dn.split(":", 1))
    except (ValueError, OSError):
        return set()
    out = set()
    for f in files:
        try:
            if open(os.path.join(d, f), "rb").read() != open(os.path.join(bs, f), "rb").read():
                out.add(f)
        except OSError:
            out.add(f)  # a file only one side has counts as touched
    return out


def bank_rescreen(a, b, _retry=0):
    top = int(a[a.index("--top") + 1]) if "--top" in a else 8
    n = a[a.index("--n") + 1] if "--n" in a else "1200"
    dry = "--dry" in a
    lv, vv = live(), live_version()
    for d in sorted(glob.glob(f"{FS}/bk*/")):
        tag_ = os.path.basename(d.rstrip("/"))
        # running = its run or driver process is alive (Builder 5 Nov: bk521 lost its driver in the machine move and read 'running' for 2 days)
        if not os.path.exists(os.path.join(d, "result.txt")) and driver_alive(tag_) and "--only" not in a:  # --only: an explicit pick runs alongside
            print(f"bank rescreen: {tag_} is still running; nothing started")
            return
    cand = [e for e in b.values() if e["state"] == "active" and not any(x["base"] == vv for x in e["screens"])]
    cand.sort(key=lambda e: -e["point"])
    if "--by-z" in a:  # 10 Nov (owner via Builder: "sort it based on results first"): evidence z = (point - .5) * 2 * sqrt(n), not the raw point
        cand.sort(key=lambda e: -(e["point"] - 0.5) * 2 * (e.get("n") or 0) ** 0.5)
    if "--only" in a:  # 10 Nov: an explicit pick list (ids, comma-separated), in the order given
        want = a[a.index("--only") + 1].split(",")
        cand = sorted([e for e in cand if e["id"] in want], key=lambda e: want.index(e["id"]))
    picked, skipped = [], []
    _, ldefs = defs_of(lv)
    for e in cand:
        if e.get("buildfail_donor") and e.get("buildfail_donor") == (entry_donor(e) or e.get("donor")):  # 10 Nov: rebase it first
            skipped.append(f"{e['id']} ({e.get('needs', 'integration build failed')})")
            continue
        k = bank_entry_kind(e, lv)
        if k == "code":
            skipped.append(f"{e['id']} (no runtime flag)")
            continue
        if all(f in ldefs and num(ldefs[f][2]) == num(v) for f, v in e["flips"].items()):
            e["state"], e["note"] = "shipped", (e.get("note", "") + f"; its values are live in {vv}").strip("; ")
            skipped.append(f"{e['id']} (already live: marked shipped)")
            continue
        cl = clears_live_bits(e["flips"], ldefs)
        if cl and not e.get("allow_clear"):
            e["needs"] = "flip clears live bits: " + ", ".join(f"{f} live {a} -> {b} (keep live's bits: {f}={c})" for f, a, b, c in cl)
            skipped.append(f"{e['id']} ({e['needs']})")
            continue
        if any(f in {g for p in picked for g in p['flips']} for f in e["flips"]):
            skipped.append(f"{e['id']} (sets a flag another picked entry sets)")
            continue
        if k == "merge":
            if pack_load(e["id"]).get("status") == "needs-hand-rebase":
                e["needs"] = f"rebase: its patch conflicts ({pack_load(e['id']).get('note', '')[:120]})"
                skipped.append(f"{e['id']} ({e['needs']})")
                continue
            dn_ = entry_donor(e)
            if not dn_:
                if not e["donor"] or e["donor"] == "-" or ":" not in e["donor"]:
                    skipped.append(f"{e['id']} (not a flip of live and no donor)")
                    continue
                # Builder 5 Nov: nova_trunk19t was not copied to maple05 and card.load_index crashed
                e["needs"] = f"rebase: {e['donor']} not on this machine and no stored patch ({stamp_now()})"
                skipped.append(f"{e['id']} ({e['needs']})")
                continue
            e["_donor"] = dn_
            e["_kind_m"] = dn_
            # cumulative: this donor on top of the donors already picked (two donors can each merge alone and conflict together)
            mg = [p for p in picked if p.get("_kind") == "merge"] + [e]
            off = {}
            for q in mg:  # the ideas' flags at their own donors' off values, as run() sets them (flip.py checks every define)
                qd = defs_of(q["_donor"].split(":")[0])[1]
                off.update({f: num(qd[f][2]) if f in qd else 0 for f in q["flips"]})
            rc, out = tm_dry([q["_donor"] for q in mg] + [lv, f"nova_fsbkchk_{e['id']}", "--set", " ".join(f"{k}={v}" for k, v in off.items()),
                              "--live", lv, "--union-auto"])
            if rc != 0:
                alone = len(mg) == 1
                e["needs"] = f"rebase onto {lv} ({stamp_now()})" if alone else f"conflicts with {', '.join(p['id'] for p in picked if p.get('_kind') == 'merge')} on {lv}"
                skipped.append(f"{e['id']} ({'needs rebase: donor no longer merges onto live' if alone else e['needs']})")
                continue
        e["_kind"] = k
        picked.append(e)
        if len(picked) >= top:
            break
    keep_m = {e["id"]: e.get("_kind_m") for e in picked}
    for e in b.values():
        e.pop("_kind", None)
        e.pop("_donor", None)
        e.pop("_kind_m", None)
    bank_save(b)
    for e in picked:
        if keep_m.get(e["id"]):
            e["_kind_m"] = keep_m[e["id"]]
    print(f"bank rescreen on {vv} ({lv}): {len(picked)} picked: {', '.join(e['id'] for e in picked) or '-'}"
          + (f"; left out: {'; '.join(skipped)}" if skipped else ""))
    if len(picked) < 2:
        print("bank rescreen: fewer than 2 screenable entries; nothing started")
        return
    tag = ("bk" + re.sub(r"\D", "", vv))[:8]
    # 13 Nov (TB, bk887: the retry without a needs-rebase donor re-used the failed attempt's tag, and newbot.sh refused the existing trunk
    # nova_fsbk887t, so the retry 'failed on an unparsed error'): a tag whose design OR trunk bot already exists takes the next letter
    for suf in ("", "b", "c", "d", "e", "f"):
        t_ = (("bk" + re.sub(r"\D", "", vv))[:7] + suf) if suf else tag
        if not os.path.exists(f"{FS}/{t_}/design.json") and not os.path.lexists(os.path.join(REPO, "bots", f"nova_fs{t_}t")):
            tag = t_
            break
    cmd = ["python3", "-I", os.path.abspath(__file__), "run", tag] + [f"bank:{e['id']}" for e in picked] + ["--n", n] + (["--dry"] if dry else [])
    print("  " + " ".join(cmd[2:]))
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    print((r.stdout + r.stderr).strip()[-1200:])
    if dry:
        return
    if "trunkmerge failed" in (r.stdout + r.stderr):  # 10 Nov (Planner: bk698-bk702 all failed on one stale donor, silently, all afternoon)
        files = build_fail_files(tag)
        sus = [e for e in picked if e.get("_kind_m") and donor_touches(e["_kind_m"], files)] if files else []
        b2 = bank_load()
        for e in sus:
            x = b2[e["id"]]
            x["needs"] = f"rebase: integration build fails on {vv} ({', '.join(sorted(files))[:80]}) {stamp_now()}"
            x["buildfail_donor"] = e["_kind_m"]
        bank_save(b2)
        why = (f"integration build failed on {', '.join(sorted(files)) or 'an unparsed error'}; "
               + (f"marked needs-rebase: {', '.join(e['id'] for e in sus)}" if sus else "no picked donor touches those files"))
        print(f"bank rescreen: {why}")
        if sus and _retry < 1:
            print("bank rescreen: retrying without them")
            return bank_rescreen(a, bank_load(), _retry + 1)
        open(RESCREEN_ALARM, "w").write(f"ALARM bank rescreen {tag} on {vv} failed: {why[:200]} (flagscreen.py bank stale lists old donors)\n")
        return
    try:
        os.remove(RESCREEN_ALARM)  # a re-screen that started its arms clears the alarm
    except OSError:
        pass


def bank_stale(b, before=690):
    """10 Nov (Planner): active bank entries whose donor base is older than v<before> (rebase them in one batch)"""
    rows = []
    for e in b.values():
        if e["state"] != "active" or not e.get("donor") or ":" not in e["donor"]:
            continue
        m = re.search(r"_v(\d+)$", e["donor"].split(":", 1)[1]) or re.search(r"v(\d+)", str(e.get("base") or ""))
        v = int(m.group(1)) if m else 0
        if v < before:
            rows.append((v, e["id"], e["donor"], e.get("point", ""), (e.get("needs") or "")[:70]))
    rows.sort()
    print(f"bank: {len(rows)} active entries with a donor base older than v{before} (base v, id, donor, point, needs):")
    for r in rows:
        print("  v%-4s %-14s %-60s %s %s" % r)


def drop_dry(out):
    """remove the scratch copy a trunkmerge --dry we started made ('Remove it when done: rm bots/NAME and DIR')"""
    pairs = re.findall(r"rm bots/(\S+) and (\S+)", out) + [(m.group(2), m.group(1)) for m in
                                                          re.finditer(r"fix them in (/data/zw4424/st/new/bots/(tmdry_\d+))/src", out)]
    for nm, nd in pairs:
        nd = nd.rstrip(".")
        if not re.fullmatch(r"tmdry_\d+|nova_fsbkchk_\w+|nova_fs\w+t", nm):
            continue
        pth = os.path.join(REPO, "bots", nm)
        if os.path.islink(pth):
            os.remove(pth)
        elif os.path.isdir(pth):
            shutil.rmtree(pth)
        if os.path.basename(nd.rstrip("/")) == nm and nd.startswith("/data/zw4424/st/new/bots/") and os.path.isdir(nd):
            shutil.rmtree(nd)


def tm_dry(args):
    """trunkmerge.py ARGS --dry, then remove the scratch copy it makes (bots/tmdry_<its pid> and its /data dir): it is ours by pid"""
    pr = subprocess.Popen(["nice", "-n", "10", "python3", "-I", "tools/lab/trunkmerge.py"] + args + ["--dry"], cwd=REPO,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = pr.communicate()[0]
    nm = f"tmdry_{pr.pid}"
    ln = os.path.join(REPO, "bots", nm)
    if os.path.islink(ln) and os.readlink(ln) == f"/data/zw4424/st/new/bots/{nm}":
        os.remove(ln)
    if os.path.isdir(f"/data/zw4424/st/new/bots/{nm}"):
        shutil.rmtree(f"/data/zw4424/st/new/bots/{nm}")
    drop_dry(out)
    return pr.returncode, out


def stamp_now():
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())


def bank_record(tag, js, b_eff):
    """read() of a bank screen: each bank idea's z on this base; expire after two non-PICK screens on two different bases"""
    b = bank_load()
    vv = js.get("live_version") or js["live"]
    for i, idea in enumerate(js["ideas"]):
        eid = idea.get("bank")
        if not eid or eid not in b:
            continue
        z = b_eff[i]
        e = b[eid]
        e["screens"] = [x for x in e["screens"] if x["tag"] != tag] + [dict(tag=tag, base=vv, z=round(z, 2), res="PICK" if z > 1 else "flat" if z >= -1 else "neg")]
        bad = {x["base"] for x in e["screens"] if x["res"] != "PICK"}
        if len(bad) >= 2 and e["state"] == "active":
            e["state"] = "expired"
            e["note"] = (e.get("note", "") + f"; expired {stamp_now()}: non-PICK screens on {', '.join(sorted(bad))}").strip("; ")
    bank_save(b)


# ------------------------------------------------------------------ design
def hadamard(n):
    H = [[1]]
    while len(H) < n:
        H = [r + r for r in H] + [r + [-x for x in r] for r in H]
    return H


def design(k, tag):
    """0/1 rows (1 = idea on). <= 4 ideas: the full 2^k factorial; else a fold-over Hadamard (8 -> 16 rows for <= 7, 16 -> 32 for
    <= 15) with random columns and signs from TAG. Duplicate rows are dropped (an identical arm would replay identical games)."""
    if k <= 4:
        return [[(r >> i) & 1 for i in range(k)] for r in range(2 ** k)]
    n = 8 if k <= 7 else 16
    rng = random.Random(f"flagscreen:{tag}")
    cols = rng.sample(range(1, n), k)
    sg = [rng.choice((1, -1)) for _ in range(k)]
    H = hadamard(n)
    rows = [[H[i][c] * s for c, s in zip(cols, sg)] for i in range(n)]
    rows += [[-x for x in r] for r in rows]
    out = []
    for r in rows:
        r = [1 if x > 0 else 0 for x in r]
        if r not in out:
            out.append(r)
    return out


def sites(trunk, ideas):
    """per idea: the functions that read any of its flags directly, through a table whose initializer holds the flag, or through
    a macro over that table"""
    fns, _ = defs_of(trunk)
    src = os.path.join(REPO, "bots", trunk, "src")
    import card
    text = {f: open(os.path.join(src, f), errors="replace").read() for f in os.listdir(src) if f.endswith((".h", ".cpp", ".cc"))}
    tabs = {}
    for t in text.values():
        for m in re.finditer(r"\b(\w+_TAB)\s*\[[^\]]*\]\s*=\s*\{(.*?)\}", t, re.S):
            tabs.setdefault(m.group(1), set()).update(re.findall(r"\b[A-Z][A-Z0-9_]+\b", m.group(2)))
    macs = {}
    for t in text.values():
        for m in re.finditer(r"^\s*#define\s+(\w+)(?:\([^)]*\))?\s+(.*)$", t, re.M):
            macs[m.group(1)] = set(re.findall(r"\b\w+\b", m.group(2)))
    names = {}
    for i, idea in enumerate(ideas):
        nm = set(idea["flips"])
        tb = {t for t, v in tabs.items() if v & nm}
        mc = {k for k, v in macs.items() if v & (tb | nm) and k not in nm}
        names[i] = nm | tb | mc
    out = {i: set() for i in names}
    for fn in fns:
        ids = set(re.findall(r"\b[A-Za-z_]\w*\b", "\n".join(card.code(x) for x in card.body(src, fn))))
        for i, nm in names.items():
            if ids & nm:
                out[i].add(f"{fn[4]} ({fn[0]}:{fn[1]})")
    return out


# ------------------------------------------------------------------ run
def say(tag, msg):
    line = f"{time.strftime('%H:%M:%S', time.gmtime())} {msg}"
    print(line, flush=True)
    with open(f"{FS}/{tag}/log", "a") as f:
        f.write(line + "\n")


def run(a):
    tag = a[1]
    if not re.fullmatch(r"[a-z0-9]{1,8}", tag):
        sys.exit("flagscreen: TAG must be 1-8 of [a-z0-9]")
    d = f"{FS}/{tag}"
    if os.path.exists(f"{d}/design.json"):
        sys.exit(f"flagscreen: {d} exists (status/read it, or pick a new TAG)")
    opt = lambda k, v: a[a.index(k) + 1] if k in a else v  # noqa: E731
    n, par, prio, dry = int(opt("--n", 1200)), min(4, int(opt("--par", 2))), int(opt("--prio", -10)), "--dry" in a
    cls, wf = opt("--class", None), opt("--wfams", None)  # 11 Nov (owner: separate strategies by map class): a class screen draws only class maps
    mfrom = opt("--maps-from", None)  # 11 Nov (b1962): a prepared map set (DIR with otf.json + .map26a, e.g. a stylepanel --draft-changed --keep-maps dir)
    skip = {a.index(k) + 1 for k in ("--n", "--par", "--prio", "--class", "--wfams", "--maps-from") if k in a}
    items = [x for i, x in enumerate(a[2:], 2) if not x.startswith("--") and i not in skip]
    if not 2 <= len(items) <= 15:
        sys.exit("flagscreen: 2-15 ideas")
    pl = {}
    if os.path.exists(f"{FS}/pool.tsv"):
        for ln in open(f"{FS}/pool.tsv").read().split("\n")[1:]:
            x = ln.split("\t")
            if len(x) >= 10:
                pl[x[0]] = dict(bot=x[0], point=float(x[3]), kind=x[5], trunk=x[6], base=x[7], flips=parse_flips(x[8]))
    lv = live()
    _, ldefs = defs_of(lv)
    ideas = []
    for it in items:
        if it.startswith("bank:"):
            bk = bank_load().get(it[5:])
            if not bk:
                sys.exit(f"flagscreen: {it}: no such bank entry")
            k = bank_entry_kind(bk, lv)
            if k == "code":
                sys.exit(f"flagscreen: {it}: no runtime flag; read it alone")
            dn_ = entry_donor(bk) if k == "merge" else None
            if k == "merge" and not dn_:
                sys.exit(f"flagscreen: {it}: its donor {bk.get('donor')} is not on this machine and it has no usable patch (`bank rebase`)")
            dn, base = dn_.split(":", 1) if dn_ else (None, None)
            cl = clears_live_bits(bk["flips"], ldefs)
            if cl and not bk.get("allow_clear"):
                sys.exit(f"flagscreen: {it}: its flip clears bits live has set: " + ", ".join(f"{f} live {a} -> {b} (use {f}={c})" for f, a, b, c in cl)
                         + "; fix the entry (bank add ... --flips) or set --allow-clear on purpose")
            ideas.append(dict(label=it[5:], bank=it[5:], bot=dn, base=base, trunk=dn, kind=k, flips=bk["flips"], point=bk["point"]))
        elif it in pl:
            ideas.append(dict(pl[it], label=it))
        elif "=" in it:
            fl = parse_flips(it)
            if not flippable(lv, fl):
                sys.exit(f"flagscreen: {it}: not a data-only flip of live {lv} (give the pool bot name so its code is merged)")
            ideas.append(dict(label=it, bot=None, kind="data", flips=fl))
        else:
            sys.exit(f"flagscreen: {it}: not in {FS}/pool.tsv (run `pool` first) and not FLAG=V")
    allf = [f for i in ideas for f in i["flips"]]
    if len(allf) != len(set(allf)):
        sys.exit("flagscreen: two ideas set the same flag; merge them into one idea or drop one")
    os.makedirs(d, exist_ok=True)
    merge = [i for i in ideas if i["kind"] == "merge"]
    trunk = lv
    off = {}
    for i in ideas:  # off value: live's for data ideas, the idea's own base trunk's for merged ones
        src = ldefs if i["kind"] == "data" else defs_of(i["trunk"])[1]
        for f in i["flips"]:
            off[f] = num(src[f][2]) if f in src else 0
    if merge:
        trunk = f"nova_fs{tag}t"
        cmd = ["python3", "-I", "tools/lab/trunkmerge.py"] + [f"{i['bot']}:{i['base']}" for i in merge] + [lv, trunk, "--set",
               " ".join(f"{f}={off[f]}" for i in merge for f in i["flips"]), "--live", lv, "--union-auto"] + (["--dry"] if dry else [])
        say(tag, "integration trunk: " + " ".join(cmd[3:]))
        if dry:
            rc_, out_ = tm_dry(cmd[3:-1])
            r = subprocess.CompletedProcess(cmd, rc_, out_, "")
        else:
            r = subprocess.run(["nice", "-n", "10"] + cmd, cwd=REPO, capture_output=True, text=True)
        open(f"{d}/trunkmerge.out", "w").write(r.stdout + r.stderr)
        say(tag, f"trunkmerge rc {r.returncode}: {(r.stdout + r.stderr).strip().splitlines()[-1][:200] if (r.stdout + r.stderr).strip() else ''}")
        if r.returncode != 0 or dry:
            sys.exit(f"flagscreen: trunkmerge {'dry run done' if dry else 'failed'}; see {d}/trunkmerge.out")
    st = sites(trunk, ideas)
    pairs = [(i, j, sorted(st[i] & st[j])) for i in range(len(ideas)) for j in range(i + 1, len(ideas)) if st[i] & st[j]]
    X = design(len(ideas), tag)
    arms = []
    for r, row in enumerate(X):
        on = {f: v for i, idea in zip(row, ideas) if i for f, v in idea["flips"].items()}
        if not on:
            continue
        arms.append(dict(name=f"nova_fs{tag}a{r:02d}", row=row, flips=on, ptag=f"fs{tag}{r:02d}", state="new"))
    js = dict(tag=tag, cls=cls, wfams=wf, live=lv, live_version=open(f"{BQ}/live.txt").readline().split()[0], trunk=trunk, n=n, par=par, prio=prio, ideas=ideas, off=off, pairs=[[i, j, s[:4]] for i, j, s in pairs],
              sites={i: sorted(s)[:12] for i, s in st.items()}, design=X, arms=arms, made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    json.dump(js, open(f"{d}/design{'.dry' if dry else ''}.json", "w"), indent=1)
    say(tag, f"{len(ideas)} ideas, {len(arms)} arms ({len(X)}-row {'full factorial' if len(ideas) <= 4 else 'fold-over Hadamard'}), trunk {trunk}, {n} maps, priority {prio}; "
             "overlapping pairs: " + (", ".join(ideas[i]["label"] + "+" + ideas[j]["label"] for i, j, _ in pairs) or "none"))
    if dry:
        print(json.dumps(dict(arms=[(x["name"], x["flips"]) for x in arms]), indent=0)[:3000])
        return
    for x in arms:
        r = subprocess.run(["sh", "tools/lab/flip.sh", trunk, x["name"], " ".join(f"{k}={v}" for k, v in x["flips"].items())],
                           cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"flagscreen: flip.sh {x['name']} failed: {(r.stdout + r.stderr)[-400:]}")
    say(tag, f"arms built: {arms[0]['name']} .. {arms[-1]['name']}")
    md = f"{d}/maps"
    if mfrom:  # copy (hard link) the prepared set; its otf.json lists the maps
        os.makedirs(md, exist_ok=True)
        meta = json.load(open(os.path.join(mfrom, "otf.json")))
        keep = [m for m in meta["maps"] if os.path.exists(os.path.join(mfrom, m["name"] + ".map26a"))][:n]
        for m in keep:
            try:
                os.link(os.path.join(mfrom, m["name"] + ".map26a"), os.path.join(md, m["name"] + ".map26a"))
            except FileExistsError:
                pass
        json.dump(dict(meta, maps=keep), open(os.path.join(md, "otf.json"), "w"))
        say(tag, f"maps: {len(keep)} from {mfrom} (--maps-from)")
        start_driver(tag, d)
        say(tag, f"driver started (log {d}/log); `flagscreen.py status {tag}`, then `read {tag}`")
        return
    r = subprocess.run(["nice", "-n", "19", "python3", "-I", "tools/lab/stratmaps.py", md, "--n", str(n), "--take", "--light", "--who", f"flagscreen:{tag}"]
                       + (["--class", cls] if cls else []) + (["--wfams", wf] if wf else []),
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(f"{md}/otf.json"):
        sys.exit(f"flagscreen: stratmaps failed: {(r.stdout + r.stderr)[-400:]}")
    say(tag, (r.stdout + r.stderr).strip().split("\n")[0][:200])
    start_driver(tag, d)
    say(tag, f"driver started (log {d}/log); `flagscreen.py status {tag}`, then `read {tag}`")


def room(tag, said=[0]):
    """start another arm only while the machine and the pipeline have room (owner 5 Nov: 'do not slow down our pipeline', 'do not
    exceed the machine's limits'): 1-min load < 24, free RAM >= 10 GB, home < 49,000 files, and no normal-priority pilot item waiting"""
    why = []
    if os.environ.get("FS_ROOM_FORCE") == "1":  # 10 Nov (Builder: run the bank screen now, low priority): skip the idle-machine wait; the arms queue at their own low prio
        return True
    if os.getloadavg()[0] >= 24:
        why.append(f"load {os.getloadavg()[0]:.0f}")
    try:
        mem = int(re.search(r"MemAvailable:\s+(\d+)", open("/proc/meminfo").read()).group(1)) / 1e6
        if mem < 10:
            why.append(f"free RAM {mem:.0f} GB")
    except (OSError, AttributeError):
        pass
    try:
        r = subprocess.run(["python3", "-I", os.path.join(HERE, "homequota.py")], capture_output=True, text=True, timeout=60)
        files = int(r.stdout.split()[0])
        if files >= int(os.environ.get("FS_HOME_MAX", "55000")):  # 8 Nov: 49k -> 55k (home's baseline is ~51k since the move; condab slows at 58k, hard quota 61k)
            why.append(f"home {files} files")
    except (Exception,):  # noqa: BLE001
        pass
    q = "/homes/zw4424/condor-runs/pilotq/queue"
    try:
        normal = sum(1 for f in os.listdir(q) if f[:3].isdigit() and int(f[:3]) <= 500)
        if normal:
            why.append(f"{normal} normal pilot items queued")
    except OSError:
        pass
    if why and time.time() - said[0] > 1800:
        said[0] = time.time()
        say(tag, "waiting for room: " + ", ".join(why))
    return not why


def drive(a):
    tag = a[1]
    d = f"{FS}/{tag}"
    js = json.load(open(f"{d}/design.json"))
    md = f"{d}/maps"
    maps = [f for f in os.listdir(md) if f.endswith(".map26a")]
    env = dict(os.environ, SP_PRIO=str(js["prio"]), CONDAB_TIMEOUT=os.environ.get("CONDAB_TIMEOUT", "43200"))
    procs = {}
    todo = [x for x in js["arms"] if not os.path.exists(f"{BQ}/sp{x['ptag']}.txt")]
    while todo or procs:
        while todo and len(procs) < js["par"] and room(tag):
            x = todo.pop(0)
            pd = f"{PANEL}/{x['ptag']}"
            os.makedirs(pd, exist_ok=True)
            for f in maps:
                if not os.path.exists(f"{pd}/{f}"):
                    os.link(f"{md}/{f}", f"{pd}/{f}")
            shutil.copyfile(f"{md}/otf.json", f"{pd}/otf.json")
            cmd = ["nice", "-n", "10", "python3", "-I", "tools/lab/stylepanel.py", x["name"], js["trunk"], x["ptag"], "--n", str(js["n"]),
                   "--fresh-only", "--par", "1"]
            procs[x["ptag"]] = subprocess.Popen(cmd, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                                stdout=open(f"{d}/arm_{x['ptag']}.out", "a"), stderr=subprocess.STDOUT)
            say(tag, f"arm {x['ptag']} started ({len(todo)} waiting)")
        time.sleep(60)
        for k, p in list(procs.items()):
            if p.poll() is not None:
                say(tag, f"arm {k} ended rc {p.returncode}")
                del procs[k]
    say(tag, "all arms ended; `flagscreen.py read " + tag + "`")


def status(a):
    tag = a[1]
    js = json.load(open(f"{FS}/{tag}/design.json"))
    import stylepanel
    done = 0
    for x in js["arms"]:
        sc = stylepanel.map_score(f"fp{x['ptag']}", x["name"])
        done += len(sc) >= 0.9 * js["n"]
        print(f"  {x['ptag']}: {len(sc):5d}/{js['n']} maps  {' '.join(f'{k}={v}' for k, v in x['flips'].items())[:90]}")
    print(f"flagscreen {tag}: {done}/{len(js['arms'])} arms complete; log {FS}/{tag}/log")


# ------------------------------------------------------------------ read
def deaths_rows(js, lab, np):
    """Per-idea death effect: our deaths minus the trunk's in the same game, OLS on the design rows (main effects), se clustered by map.
    Use these rows for a death clause; never an arm-level on/off mean."""
    rows, maps = [], {}
    for x in js["arms"]:
        p = f"{PANEL}/{x['ptag']}/fp_games.jsonl"
        try:
            fh = open(p)
        except OSError:
            continue
        for ln in fh:
            try:
                g = json.loads(ln)
                me, op = (g["sa"], g["sb"]) if g["a"] == x["name"] else (g["sb"], g["sa"])
                rows.append((x["row"], maps.setdefault(g["map"], len(maps)), float(me["deaths"] - op["deaths"])))
            except (ValueError, KeyError, TypeError):
                continue
    if len(rows) < 50:
        return []
    K = len(lab)
    Xm = np.array([[1.0] + [r[0][i] for i in range(K)] for r in rows], float)
    y = np.array([r[2] for r in rows])
    gm = np.array([r[1] for r in rows])
    XtX = np.linalg.pinv(Xm.T @ Xm)  # 11 Nov (bk754: se ~4e7 for ideas the main-effects design can't separate): pinv, and such rows say so
    b = XtX @ Xm.T @ y
    e = y - Xm @ b
    meat = np.zeros((K + 1, K + 1))
    for m in range(len(maps)):
        sv = Xm[gm == m].T @ e[gm == m]
        meat += np.outer(sv, sv)
    se = np.sqrt(np.diag(XtX @ meat @ XtX))
    out = ["", f"deaths per game, ours minus the trunk's in the same game ({len(rows)} games; main effect, se clustered by map; FLAG = |z| >= 2):"]
    for i, nm in enumerate(lab):
        bb, ss = b[i + 1], se[i + 1]
        z = bb / ss if ss > 0 else 0.0
        if not np.isfinite(ss) or ss > 5:
            out.append(f"       {nm[:44]:44s} not separable in this design (shares its arms with other ideas; no death read)")
            continue
        out.append(f"  {'FLAG ' if abs(z) >= 2 else '     '}{nm[:44]:44s} {bb:+6.3f}/g  se {ss:.3f}  z {z:+5.2f}")
    return out


def read(a):
    import numpy as np
    import stylepanel
    tag = a[1]
    d = f"{FS}/{tag}"
    js = json.load(open(f"{d}/design.json"))
    ideas, K = js["ideas"], len(js["ideas"])
    lab = [i["label"] for i in ideas]
    rows, maps, armsum = [], {}, []
    for x in js["arms"]:
        sc = stylepanel.map_score(f"fp{x['ptag']}", x["name"])
        armsum.append((x["ptag"], len(sc), (sum(sc.values()) / len(sc)) if sc else float("nan")))
        for m, y in sc.items():
            rows.append((x["row"], maps.setdefault(m, len(maps)), y - 0.5))
    if not rows:
        sys.exit("flagscreen read: no results yet")
    cols = list(range(K))
    pairs = [(p[0], p[1]) for p in js["pairs"]]
    Xm = np.array([[r[0][i] for i in cols] for r in rows], float)
    terms = list(lab)
    kept = []
    for i, j in pairs:  # a pair term goes in only if the design separates it from everything already in
        col = np.array([r[0][i] * r[0][j] for r in rows], float)[:, None]
        if np.linalg.matrix_rank(np.hstack([Xm, col])) > Xm.shape[1]:
            Xm = np.hstack([Xm, col])
            terms.append(f"{lab[i]} x {lab[j]}")
            kept.append((i, j))
    y = np.array([r[2] for r in rows])
    g = np.array([r[1] for r in rows])
    XtX = np.linalg.inv(Xm.T @ Xm)
    b = XtX @ Xm.T @ y
    e = y - Xm @ b
    meat = np.zeros((Xm.shape[1], Xm.shape[1]))
    for m in range(len(maps)):  # clustered by map: the arms share maps
        s = Xm[g == m].T @ e[g == m]
        meat += np.outer(s, s)
    se = np.sqrt(np.diag(XtX @ meat @ XtX))
    L = [f"# FLAG SCREEN {tag}{(' CLASS ' + js['cls']) if js.get('cls') else ''}{(' WFAMS ' + js['wfams']) if js.get('wfams') else ''}: {K} ideas, {len(js['arms'])} arms v trunk {js['trunk']} (flag 0), {len(maps)} maps, live then {js['live']}",
         f"arms: {sum(n >= 0.9 * js['n'] for _, n, _ in armsum)}/{len(armsum)} complete; a row = an idea's own effect (map-pair score points over .500), "
         "se clustered by map", ""]
    pick = []
    for t, (nm, bb, ss) in enumerate(zip(terms, b, se)):
        z = bb / ss if ss > 0 else 0.0
        isidea = t < K
        if isidea and z > 1:
            pick.append(t)
        L.append(f"  {'PICK ' if isidea and z > 1 else '     '}{nm[:44]:44s} {bb * 100:+6.2f} pts  se {ss * 100:4.2f}  z {z:+5.2f}"
                 + (f"   (prior read {ideas[t]['point']:.4f})" if isidea and ideas[t].get('point') else ""))
    unsep = [(i, j) for i, j in pairs if (i, j) not in kept]
    if unsep:
        L.append("  pairs that touch the same code but are not separable in this design: " + ", ".join(f"{lab[i]}+{lab[j]}" for i, j in unsep))
    pred = sum(b[t] for t in pick) + sum(b[K + k] for k, (i, j) in enumerate(kept) if i in pick and j in pick)
    L.append("")
    if len(maps) < 600:
        L.append(f"BUNDLE: none: {len(maps)} maps is a smoke test (se of an idea ~{min(se[:K]) * 100:.1f}-{max(se[:K]) * 100:.1f} pts); read at >= 600 maps (default 1,200) before picking")
        pick = []
    elif pick:
        fl = " ".join(f"{k}={v}" for t in pick for k, v in ideas[t]["flips"].items())
        donor = "-" if js["trunk"] == js["live"] else f"{js['trunk']}:{js['live']}"
        L += [f"BUNDLE: {len(pick)} idea(s), predicted +{pred * 100:.2f} pts over flag 0 (before the confirm read; expect less: winner's curse)",
              f"  python3 -I tools/lab/armq.py add {donor} \"{fl}\" behaviour \"bundle(screen): {len(pick)} near-miss ideas ({tag})\"",
              "  (the Builder arms it; shipcheck decides on the usual bar. Live moved since the screen? Check `flagscreen.py pool` first.)"]
    elif not pick:
        L.append("BUNDLE: none (no idea at z > 1)")
    L += deaths_rows(js, lab, np)  # 11 Nov (Builder: fpb6's hand-made MPW death clause read +.42/g z 2.6; this method reads -.06, z -.55)
    L.append("")
    L.append("arms: " + "; ".join(f"{p} {n} maps {s:.3f}" for p, n, s in armsum))
    if any(i.get("bank") for i in ideas) and len(maps) >= 600:
        bank_record(tag, js, [b[t] / se[t] if se[t] > 0 else 0.0 for t in range(K)])
        L.append("bank: each entry's z recorded on this base (`flagscreen.py bank list`); two non-PICK screens on two bases expire it")
    txt = "\n".join(L) + "\n"
    open(f"{d}/result.txt", "w").write(txt)
    print(txt)


def restart(a):
    """flagscreen.py restart TAG: start the driver again for a screen whose driver died (arms and maps are kept; finished arms stay finished)"""
    tag = a[1]
    d = f"{FS}/{tag}"
    if not os.path.exists(f"{d}/design.json"):
        sys.exit(f"flagscreen: no {d}/design.json")
    if driver_alive(tag):
        sys.exit(f"flagscreen: {tag}'s driver is running")
    start_driver(tag, d)
    say(tag, "driver restarted")


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("pool", "run", "drive", "status", "read", "bank", "restart") or (a[0] not in ("pool", "bank") and len(a) < 2):
        sys.exit(__doc__)
    {"pool": pool, "run": run, "drive": drive, "status": status, "read": read, "bank": bank, "restart": restart}[a[0]](a)


if __name__ == "__main__":
    main()
