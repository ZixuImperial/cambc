#!/usr/bin/env python3
"""ideastore.py: ideas as patches + flips, applied to the current live on demand, instead of a copied bot dir per idea (owner 5 Nov).

An idea is NAME.diff (a plain `git diff --full-index`, against the idea's base) + NAME.json (base, flips). All source versions live in
one bare git store (one blob per distinct file version), so nothing but the patch is per-idea and a merge needs no working copy.
  ingest BOT...                     add bots' src to the store (refs/bots/BOT)
  add NAME DONOR BASE [--flips "F=V ..."] [--lane L] [--subject S]   make an idea from a donor built on BASE ("-" DONOR: flips only); prints the armq line
  add NAME --patch FILE BASE [--flips ...]   the same from a patch file (a/src/... paths)
  conflicts [DONOR:BASE ...]        which queued ideas conflict with the trunk or with each other, in memory (no list: armq.txt)
  sweep [--apply]                   retire every bot no work needs (rules in sweep()); dry unless --apply. healthwatch runs it hourly; touch bq/ideasweep_OFF stops it
  apply ONTO NAME [NAME...] [--flips "F=V ..."] [--name OUT]    merge ideas onto bot ONTO, in memory: prints the tree + source hash, or
                                    exit 3 with the real conflicts (add-only conflicts are kept on both sides, as trunkmerge --union-auto)
  materialize TREE|OUT DEST         write src/ to DEST (seconds); delete DEST when done
  verify [--merges N] [--flips N]   re-derive real pipeline results from the registry and FLIP files; every source hash must match
  stats                             store size v the copied dirs it replaces
  retire LIST OUT                   for each bot named in LIST: re-add it, keep its FLIP, check the store gives its exact source hash; OUT = the
                                    paths safe to delete with tools/lab/rmdata.sh. Backs the store up to /homes (BACKUP): /data is this machine's disk
  restore NAME...                   bring back a retired bot as a normal bot dir with its bots/ link (FLIP too; never its SHIPCHECK: that would re-arm it)
Store: /data/USER/st/ideastore (IDEASTORE overrides).
"""
import hashlib, json, os, re, subprocess, sys, tempfile, time
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.environ.get("IDEASTORE", "/data/USER/st/ideastore")
GD = os.path.join(ROOT, "store.git")
IDEAS = os.environ.get("IDEAS_DIR", "/homes/USER/condor-work/ideastore/ideas")  # plain patches + sidecars on the shared home; they outlive any machine
META = os.path.join(ROOT, "meta.jsonl")
STORE = "/data/USER/st/new/bots"
BACKUP = os.environ.get("IDEASTORE_BACKUP", "/homes/USER/condor-work/ideastore/store.bundle")  # one file on the shared home
ENV = dict(os.environ, GIT_DIR=GD, GIT_AUTHOR_NAME="s", GIT_AUTHOR_EMAIL="s@s", GIT_COMMITTER_NAME="s", GIT_COMMITTER_EMAIL="s@s")
ENV.pop("GIT_INDEX_FILE", None)


def git(*a, inp=None, env=None, check=True, text=True):
    r = subprocess.run(["git", *a], input=inp, capture_output=True, text=text, errors="surrogateescape" if text else None, env={**ENV, **(env or {})})
    if check and r.returncode:
        sys.exit(f"ideastore: git {' '.join(a[:3])}: {r.stderr[-800:]}")
    return r


def init():
    os.makedirs(IDEAS, exist_ok=True)
    if not os.path.isdir(GD):
        subprocess.run(["git", "init", "-q", "--bare", GD], check=True)
        subprocess.run(["git", "--git-dir", GD, "config", "gc.auto", "0"], check=True)
        subprocess.run(["git", "--git-dir", GD, "config", "core.compression", "1"], check=True)


def bot_dir(b):
    return b if os.path.isdir(b) else os.path.join(REPO, "bots", b)


def ingest(b):
    """-> tree id of b's src/ (same content, same id)."""
    name = os.path.basename(os.path.normpath(b))
    d = bot_dir(b)
    with tempfile.TemporaryDirectory(dir="/dev/shm") as t:
        e = {"GIT_WORK_TREE": os.path.realpath(d), "GIT_INDEX_FILE": t + "/i"}
        git("add", "-f", "--", "src", ":(exclude)src/*.orig", ":(exclude)src/*.rej", env=e)  # 6 Nov: patch leftovers are not source
        tree = git("write-tree", env=e).stdout.strip()
    git("update-ref", f"refs/bots/{name}", git("commit-tree", tree, "-m", name).stdout.strip())
    return tree


def tree_of(x):
    """a bot name known to the store, a bot dir, or a tree id."""
    if re.fullmatch(r"[0-9a-f]{40}", x):
        return x
    r = git("rev-parse", "-q", "--verify", f"refs/bots/{x}^{{tree}}", check=False)
    return r.stdout.strip() if r.returncode == 0 else ingest(x)


def src_hash(tree):
    """srchash.py's value (sha1 of `sha1sum` lines over sorted files), from the store alone: the key every build cache uses."""
    lines = git("ls-tree", "-r", tree).stdout.splitlines()
    names = sorted(ln.split("\t", 1)[1] for ln in lines)
    ids = {ln.split("\t", 1)[1]: ln.split()[2] for ln in lines}
    blobs = subprocess.run(["git", "cat-file", "--batch"], input=("\n".join(ids[n] for n in names) + "\n").encode(), capture_output=True, env=ENV).stdout
    h, p = hashlib.sha1(), 0
    for n in names:
        nl = blobs.index(b"\n", p)
        size = int(blobs[p:nl].split()[2])
        h.update(f"{hashlib.sha1(blobs[nl + 1:nl + 1 + size]).hexdigest()}  {n}\n".encode())
        p = nl + 2 + size
    return h.hexdigest()[:12]


def flip_tree(tree, flips):
    """flips ("F=V ...") as operations: edit the one `#define F <int>` line, as flip.sh does. -> new tree."""
    if not flips.strip():
        return tree
    lines = git("ls-tree", "-r", tree).stdout.splitlines()
    want = dict(f.split("=", 1) for f in flips.split())
    with tempfile.TemporaryDirectory(dir="/dev/shm") as t:
        e = {"GIT_INDEX_FILE": t + "/i"}
        git("read-tree", tree, env=e)
        for ln in lines:
            meta, path = ln.split("\t", 1)
            if not path.endswith((".h", ".cpp", ".cc")) or not want:
                continue
            s = git("cat-file", "blob", meta.split()[2]).stdout
            s2 = s
            for f in list(want):
                s3, n = re.subn(rf"^([ \t]*#[ \t]*define[ \t]+{re.escape(f)}[ \t]+)-?\w+", lambda m, v=want[f]: m.group(1) + v, s2, flags=re.M)
                if n > 1:
                    sys.exit(f"ideastore: {f} is defined {n} times in {path}")
                if n == 1:
                    s2 = s3
                    del want[f]
            if s2 != s:
                b = git("hash-object", "-w", "--stdin", inp=s2).stdout.strip()
                git("update-index", "--add", "--cacheinfo", f"{meta.split()[0]},{b},{path}", env=e)
        if want:
            sys.exit(f"ideastore: no #define for {' '.join(want)}")
        return git("write-tree", env=e).stdout.strip()


def additive(ours, base, theirs):
    """git merge-file --union, only if every conflict block adds lines on both sides (trunkmerge's --union-auto rule). -> text or None."""
    with tempfile.TemporaryDirectory(dir="/dev/shm") as t:
        for n, b in (("o", ours), ("b", base), ("t", theirs)):
            with open(f"{t}/{n}", "wb") as f:
                f.write(git("cat-file", "blob", b, text=False).stdout)
        d3 = subprocess.run(["git", "merge-file", "-p", "--diff3", f"{t}/o", f"{t}/b", f"{t}/t"], capture_output=True, text=True, errors="replace").stdout
        for blk in re.findall(r"^\|\|\|\|\|\|\|.*?\n(.*?)^=======", d3, flags=re.M | re.S):
            if blk.strip():
                return None
        return subprocess.run(["git", "merge-file", "-p", "--union", f"{t}/o", f"{t}/b", f"{t}/t"], capture_output=True, text=True, errors="replace").stdout


def merge(onto, base, donor):
    """3-way merge of base->donor onto tree `onto`, in memory. -> (tree, conflicts)."""
    r = git("merge-tree", "--write-tree", "--name-only", "--no-messages", f"--merge-base={base}", onto, donor, check=False)
    out = r.stdout.splitlines()
    if r.returncode == 0:
        return out[0], []
    tree, bad, files = out[0], [], [x for x in out[1:] if x]
    with tempfile.TemporaryDirectory(dir="/dev/shm") as t:
        e = {"GIT_INDEX_FILE": t + "/i"}
        git("read-tree", tree, env=e)
        for f in files:
            g = lambda tr: git("rev-parse", "-q", "--verify", f"{tr}:{f}", check=False).stdout.strip()
            o, b, d = g(onto), g(base), g(donor)
            txt = additive(o, b, d) if o and b and d else None
            if txt is None:
                bad.append(f)
                continue
            git("update-index", "--add", "--cacheinfo", f"100644,{git('hash-object', '-w', '--stdin', inp=txt).stdout.strip()},{f}", env=e)
        return git("write-tree", env=e).stdout.strip(), bad


def fresh_tree(x):
    """A bot's tree as it is on disk now (an agent may still be changing it); from the store when its folder is gone."""
    return ingest(x) if os.path.isdir(bot_dir(x) + "/src") else tree_of(x)


def set_ref(name, tree):
    git("update-ref", f"refs/bots/{name}", git("commit-tree", tree, "-m", name).stdout.strip())


def idea_add(name, donor, base, flips="", patch=None, lane="", subject=""):
    """An idea: its patch and sidecar on the home, and two names the store can always restore: nova_idea_NAME (base + patch) and nova_ideab_HASH
    (the base). An armq line carries those names, so merge, mergecheck, identity, requeue and the registry treat it like any donor."""
    if not re.fullmatch(r"[a-z0-9_]+", name):
        sys.exit(f"ideastore: idea names are lower case letters, digits and _: {name}")
    bt = fresh_tree(base)
    if patch:
        with tempfile.TemporaryDirectory(dir="/dev/shm") as t:
            e = {"GIT_INDEX_FILE": t + "/i"}
            git("read-tree", bt, env=e)
            r = git("apply", "--cached", patch, env=e, check=False)
            if r.returncode:
                sys.exit(f"ideastore: {patch} does not apply to {base}: {r.stderr[-400:]}")
            dt = git("write-tree", env=e).stdout.strip()
    else:
        dt = bt if donor == "-" else fresh_tree(donor)
    text = git("diff", "--full-index", bt, dt).stdout
    with open(f"{IDEAS}/{name}.diff", "w", errors="surrogateescape") as f:
        f.write(text)
    dn, bn = f"nova_idea_{name}", f"nova_ideab_{bt[:12]}"
    set_ref(dn, dt)
    set_ref(bn, bt)
    tables = sorted(set(re.findall(r"^\+\s*#\s*define\s+([A-Z][A-Z0-9_]*)\s", text, re.M)))
    json.dump({"name": name, "base": bt, "donor": dt, "base_bot": base, "donor_bot": donor if not patch else "-", "flips": flips, "lane": lane, "subject": subject,
               "armq_donor": "-" if bt == dt else f"{dn}:{bn}", "defines": tables, "lines": len(text.splitlines()), "at": time.time()}, open(f"{IDEAS}/{name}.json", "w"))
    return f"{name}: {len(text.splitlines())} patch lines. Arm: python3 -I tools/lab/armq.py add idea:{name} \"{flips}\" {lane or 'LANE'} \"{subject or 'SUBJECT'}\""


def resolve(name):
    """-> (armq donor string, flips, lane, subject) of an idea."""
    try:
        m = json.load(open(f"{IDEAS}/{name}.json"))
    except OSError:
        sys.exit(f"ideastore: no idea {name} in {IDEAS}")
    return m.get("armq_donor", "-"), m.get("flips", ""), m.get("lane", ""), m.get("subject", "")


def batchable(onto, donors):
    """Queue order, in memory: the donors that merge together onto bot `onto`, and {donor: files} for those that do not."""
    tree, good, bad = fresh_tree(onto), [], {}
    for d in donors:
        dn, bn = d.split(":")
        t, cf = merge(tree, fresh_tree(bn), fresh_tree(dn))
        if cf:
            bad[d] = cf
        else:
            tree = t
            good.append(d)
    return good, bad


def conflicts(onto, donors):
    """Lines saying which donors conflict with the trunk or with each other (a pair: both merge alone, not together)."""
    alone, out = {}, []
    for d in donors:
        dn, bn = d.split(":")
        t, cf = merge(fresh_tree(onto), fresh_tree(bn), fresh_tree(dn))
        alone[d] = t
        if cf:
            out.append(f"{d}: conflicts with the trunk in {', '.join(cf)}")
    for i, a in enumerate(donors):
        for b in donors[i + 1:]:
            if alone[a] and alone[b] and not any(a in x or b in x for x in out):
                _, cf = merge(alone[a], fresh_tree(b.split(":")[1]), fresh_tree(b.split(":")[0]))
                if cf:
                    out.append(f"{a} + {b}: conflict in {', '.join(cf)}")
    return out


def queued_donors():
    out = []
    for ln in open("/data/USER/st/bq/armq.txt"):
        for d in json.loads(ln)["donors"].split(","):
            if d != "-" and d not in out:
                out.append(d)
    return out


def sweep(apply):
    """Retire what no work needs; every bot stays restorable. KEPT: live.txt's last 20, best_model, baseline, spars and other non-nova_b names the tools use (closedprune's
    'tools', 'prefix', 'not nova'), anything running or open, an unfinished marker, a folder touched in SWEEP_AGE_H (3) hours, names in the last 400 lines of
    builder_queue/board, armq.txt, the failed-positive bank (bank.json and tools/lab/bank), idea_queue, failure_chains, waiting pending_reads, the current trunk line,
    and the TRUNK parents of all of those. Also removes old sanitizer and CLI build copies (24 h): they rebuild on demand."""
    env = dict(os.environ, CB_AGE_H=os.environ.get("SWEEP_AGE_H", "3"))
    r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/closedprune.py")], capture_output=True, text=True, env=env)
    if r.returncode:
        sys.exit(f"ideastore sweep: closedprune: {r.stderr[-300:]}")
    d = json.load(open("/data/USER/st/tb2/closedbots.json"))
    keep, closed = d["keep"], set(d["closed"])
    BQ, R = "/data/USER/st/bq", "/homes/USER/condor-work/reports"
    tok = re.compile(r"nova_[A-Za-z0-9_]+")

    def names(p, n=None):
        try:
            with open(p, errors="ignore") as f:
                return set(tok.findall("".join(f.readlines()[:n] if n else f.readlines())))
        except OSError:
            return set()
    # 'current' = named in CLAUDE.md, the primer, idea_queue, failure_chains, armq, pending_reads, .claude/ or memory (closedprune). 5 Nov: left
    # out, so the sweep retired nova_ft_pantheon523, a standard opponent the primer names.
    k = {b for b, v in keep.items() if v in ("tools", "prefix", "not nova", "running", "marker", "open", "recent", "latest", "current")}
    k |= names(BQ + "/live.txt", 20) | names(BQ + "/best_model.txt", 3) | names(BQ + "/baseline.txt", 3) | names(BQ + "/armq.txt") | names(R + "/idea_queue.md")
    k |= names(BQ + "/failure_chains.md") | names("/data/USER/st/fs/bank.json") | names(BQ + "/fuelbank.tsv")
    k |= names("/data/USER/st/draftstock/want_bots.txt")  # 9 Nov: bots whose draft lineups the stock keeps current
    for f in os.listdir(os.path.join(REPO, "tools/lab/bank")):
        if f.endswith(".json"):
            k |= names(os.path.join(REPO, "tools/lab/bank", f))
    try:
        for ln in open(BQ + "/pending_reads.txt", errors="ignore"):
            if ln.startswith("PENDING"):
                k |= set(tok.findall(ln))
    except OSError:
        pass
    reg = open(R + "/trunk_registry.md", errors="ignore").read()
    cut = [m.start() for m in re.finditer(r"^- nova_trunk\w+ REBUILT", reg, re.M)]
    k |= set(tok.findall(reg[cut[-1]:] if cut else reg))
    grew = True
    while grew:
        grew = False
        for b in list(k):
            p = os.path.realpath(os.path.join(REPO, "bots", b))
            for f in ("FLIP", "SHIPCHECK"):
                try:
                    for q in re.findall(r"TRUNK[=: ]+(\S+)", open(f"{p}/{f}", errors="ignore").read()):
                        if q not in k:
                            k.add(q)
                            grew = True
                except OSError:
                    pass
    allb = set(keep) | closed
    go = sorted(allb - k)
    tmp = os.path.join(ROOT, "sweep")
    os.makedirs(tmp, exist_ok=True)
    now = time.time()
    old = []
    for c in ("/data/USER/st/audit/ubproj/bots", "/data/USER/st/cxe/proj/bots"):
        if not os.path.isdir(c):  # 8 Nov: a build cache that is not there (a machine move) must not stop the whole sweep
            continue
        with os.scandir(c) as it:
            old += [e.path for e in it if e.is_dir() and now - e.stat().st_mtime > 86400]
    bots = os.path.join(REPO, "bots")
    for n in os.listdir(bots):  # trunkmerge --dry scratch copies whose process is gone
        m = re.fullmatch(r"tmdry_(\d+)", n)
        if m and not os.path.exists(f"/proc/{m.group(1)}"):
            old += [os.path.join(bots, n)] + ([os.path.join(STORE, n)] if os.path.isdir(os.path.join(STORE, n)) else [])
    print(f"sweep: {len(allb)} bots, keep {len(allb & k)}, retire {len(go)}; old copies {len(old)}")
    if not apply or not (go or old):
        return
    open(tmp + "/list.txt", "w").write("\n".join(go) + "\n")
    paths = tmp + "/paths.txt"
    if go:
        retire(tmp + "/list.txt", paths)
    else:
        open(paths, "w").write("")
    with open(paths, "a") as f:
        f.write("".join(p + "\n" for p in old))
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/rmdata.sh"), paths], capture_output=True, text=True)
    print(r.stdout.strip()[-200:])


def materialize(tree, dest):
    os.makedirs(dest, exist_ok=True)
    p = subprocess.Popen(["git", "archive", tree], stdout=subprocess.PIPE, env=ENV)
    subprocess.run(["tar", "x", "-C", dest], stdin=p.stdout, check=True)
    p.wait()


def apply_ideas(onto, names, flips=""):
    tree = tree_of(onto)
    for n in names:
        m = json.load(open(f"{IDEAS}/{n}.json"))
        tree, bad = merge(tree, m["base"], m["donor"])
        if bad:
            return None, {n: bad}
        tree = flip_tree(tree, m["flips"])
    return flip_tree(tree, flips), {}


def retire(listf, outf):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import srchash
    out, bad = [], []
    with open(META, "a") as meta:
        for name in open(listf).read().split():
            link = os.path.join(REPO, "bots", name)
            d = os.path.realpath(link) if os.path.lexists(link) else os.path.join(STORE, name)
            if not os.path.isdir(d + "/src"):
                continue
            tree = ingest(d)
            if src_hash(tree) != srchash.src_hash(d):
                bad.append(name)
                continue
            fp = os.path.join(d, "FLIP")
            meta.write(json.dumps(dict(name=name, tree=tree, flip=open(fp, errors="surrogateescape").read() if os.path.exists(fp) else None)) + "\n")
            out += [d] + ([link] if os.path.lexists(link) and os.path.realpath(link) != link else [])
    git("gc", "-q", "--prune=1.hour.ago")  # 8 Nov: --prune=now deleted the objects of a bot being ingested at the same moment (v634's ref pointed at nothing)
    tmp = BACKUP + ".tmp"
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    git("bundle", "create", "-q", tmp, "--all")
    git("bundle", "verify", "-q", tmp)
    os.replace(tmp, BACKUP)
    import shutil
    shutil.copyfile(META, BACKUP + ".meta.jsonl")
    open(outf, "w").write("".join(p + "\n" for p in out))
    print(f"retire: {len(out)} paths safe to delete, written to {outf}; {len(bad)} refused (source hash differs): {bad[:6]}; backup {BACKUP} {os.path.getsize(BACKUP) // 2**20} MB")


def restore(name):
    link, d = os.path.join(REPO, "bots", name), os.path.join(STORE, name)
    if os.path.lexists(link) or os.path.exists(d):
        return print(f"{name}: already there")
    r = git("rev-parse", "-q", "--verify", f"refs/bots/{name}^{{tree}}", check=False)
    if r.returncode:
        sys.exit(f"ideastore: {name} is not in the store")
    materialize(r.stdout.strip(), d)
    flip = None
    if os.path.exists(META):
        for ln in open(META, errors="surrogateescape"):
            m = json.loads(ln)
            if m["name"] == name:
                flip = m.get("flip")
    if flip:
        open(os.path.join(d, "FLIP"), "w", errors="surrogateescape").write(flip)
    os.symlink(d, link)
    print(f"restored bots/{name}")


def verify(nm, nf):
    """Real results: registry lines (trunk = parent + donor (base)) and FLIP files (bot = trunk + flips)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import srchash
    ok = bad = skip = 0
    t0 = time.time()
    reg = open("/homes/USER/condor-work/reports/trunk_registry.md", errors="replace").read()
    rows = re.findall(r"^- (nova_trunk\w+) \(trunkmerge [^;]*; source (\w+)\): (nova_trunk\w+) \+ (nova_\w+) \(base (nova_\w+)\): took ([^;]*);.*?--set ([^.]*)\.", reg, flags=re.M)
    for new, sh, parent, donor, base, took, sets in rows[-nm:]:
        if not all(os.path.isdir(bot_dir(x)) for x in (new, parent, donor, base)) or sets.strip() not in ("-", ""):
            skip += 1
            continue
        tree, cf = merge(tree_of(parent), tree_of(base), tree_of(donor))
        if cf:
            print(f"  merge {new}: conflicts {cf}: pipeline merged it")
            bad += 1
            continue
        with tempfile.TemporaryDirectory(dir="/data/USER/st/ideastore") as t:
            materialize(tree, t)
            if os.path.exists(os.path.join(REPO, "tools/lab/mkunity.sh")) and os.path.exists(t + "/src/nova_all.cpp"):
                subprocess.run(["sh", os.path.join(REPO, "tools/lab/mkunity.sh"), t + "/src"], capture_output=True)
            got = srchash.src_hash(t)
        real = srchash.src_hash(bot_dir(new))
        if got == real:
            ok += 1
        else:
            bad += 1
            print(f"  merge {new}: {got} v real {real}")
    print(f"merges: {ok} identical, {bad} differ, {skip} skipped (dir gone or --set)  [{time.time() - t0:.0f} s]")
    ok = bad = skip = 0
    t0 = time.time()
    flips = sorted((f for f in os.listdir(os.path.join(REPO, "bots"))), key=lambda x: -os.path.getmtime(os.path.join(REPO, "bots", x)))
    seen = 0
    for b in flips:
        p = os.path.join(bot_dir(b), "FLIP")
        if not os.path.exists(p):
            continue
        kv = dict(ln.strip().split("=", 1) for ln in open(p) if "=" in ln)
        if not os.path.isdir(bot_dir(kv.get("TRUNK", "?"))):
            skip += 1
            continue
        seen += 1
        if seen > nf:
            break
        got = src_hash(flip_tree(tree_of(kv["TRUNK"]), kv.get("FLIPS", "")))
        real = srchash.src_hash(bot_dir(b))
        if got == real:
            ok += 1
        else:
            bad += 1
            print(f"  flip {b}: {got} v real {real} ({kv.get('FLIPS')})")
    print(f"flips: {ok} identical, {bad} differ, {skip} skipped  [{time.time() - t0:.0f} s]")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    init()
    opt = lambda k, d="": a[a.index(k) + 1] if k in a else d
    c = a[0]
    if c == "ingest":
        for b in a[1:]:
            print(b, ingest(b))
    elif c == "add":
        if a[2] == "--patch":
            print(idea_add(a[1], "-", a[4], opt("--flips"), patch=a[3], lane=opt("--lane"), subject=opt("--subject")))
        else:
            print(idea_add(a[1], a[2], a[3], opt("--flips"), lane=opt("--lane"), subject=opt("--subject")))
    elif c == "conflicts":
        live = open("/data/USER/st/bq/live.txt").readline().split()[1]
        print("\n".join(conflicts(opt("--onto", live), [x for x in a[1:] if ":" in x] or queued_donors())) or "no conflicts")
    elif c == "sweep":
        sweep("--apply" in a)
    elif c == "apply":
        names = [x for x in a[2:] if not x.startswith("--") and x not in (opt("--flips"), opt("--name"))]
        tree, bad = apply_ideas(a[1], names, opt("--flips"))  # names: ideas in IDEAS
        if bad:
            print("CONFLICT", bad)
            sys.exit(3)
        if opt("--name"):
            git("update-ref", f"refs/bots/{opt('--name')}", git("commit-tree", tree, "-m", opt("--name")).stdout.strip())
        print(tree, src_hash(tree))
    elif c == "materialize":
        materialize(tree_of(a[1]), a[2])
    elif c == "retire":
        retire(a[1], a[2])
    elif c == "restore":
        for n in a[1:]:
            restore(n)
    elif c == "verify":
        verify(int(opt("--merges", "40")), int(opt("--flips", "40")))
    elif c == "stats":
        sz = lambda p: int(subprocess.run(["du", "-s", "--block-size=1M", p], capture_output=True, text=True).stdout.split()[0])
        ino = lambda p: int(subprocess.run(["du", "-s", "--inodes", p], capture_output=True, text=True).stdout.split()[0])
        print(f"store {sz(GD)} MB, {ino(GD)} files; ideas {len(os.listdir(IDEAS)) // 2}; refs {len(git('for-each-ref', 'refs/bots').stdout.splitlines())}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
