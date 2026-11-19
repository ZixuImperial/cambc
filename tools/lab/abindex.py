"""Index of every deterministic game this machine knows, for tools/lab/abstat.py and tools/lab/sprt.py.

Bots are deterministic: the same two bot sources on the same map with the same sides always play the same game
(checked game for game between local abl.sh runs and Condor screens). So a game is identified by
  (source hash of team A's bot, source hash of team B's bot, map file hash)
with the source hash of tools/lab/abl.sh (sha1 over `find src -type f | sort | xargs sha1sum`, 12 hex digits).

Sources, read on demand:
  - local A/B runs, /data/zw4424/abl/*/ (abl.sh outputs): manifest.txt line k names the cached bot dirs
    <bot>-<hash> of game k; games.jsonl holds its result. Runs older than the CLI binary are skipped, and so are
    games on a map file changed after the run.
  - the Condor screen cache, /homes/zw4424/condor-work/scrcache/results.jsonl (key hashA|hashB|maphash|cli).
A game found in both with different winners is counted in Index.conflicts (a determinism failure: report it).

    import abindex
    ix = abindex.Index({h1, h2})        # load only games between these source hashes (fast)
    pairs = ix.pairs(h1, h2)            # {maphash: (game with h1 as team A, game with h2 as team A)}
"""
import fcntl
import glob
import hashlib
import json
import os
import subprocess

REPO = "/homes/zw4424/cambc"
ABL = "/data/zw4424/abl"
MAP_DIRS = ["/data/zw4424/work301/maps", "/homes/zw4424/condor-work/proj301/maps"]
SCREEN_CACHE = "/homes/zw4424/condor-work/scrcache/results.jsonl"
# the CLI of abl.sh and screen.sh; ABL_CLI selects another engine's client, and then only runs made with it count
CLI = os.environ.get("ABL_CLI", "/data/zw4424/cambc500/bin/cambc500")  # engine 2.0.0 (27 Oct)
_cli_version = {}


def cli_version():
    """'3.0.4', '4.0.0', ... of CLI (abl.sh writes 'cambc <version>' into every run's cli.txt)."""
    if CLI not in _cli_version:
        out = subprocess.run([CLI, "--version"], capture_output=True, text=True).stdout.split()
        _cli_version[CLI] = out[1] if len(out) > 1 else "?"
    return _cli_version[CLI]
# Persistent dir -> bot-hash-pair cache (29 Oct: under load ~290 one Index load took 5 min). For an Index of a few hashes,
# a run dir whose manifest names no game between two of them is skipped unread; every other dir is read exactly as before,
# so the result is identical to a full scan. Each dir is keyed on (mtime_ns, size, inode) of manifest.txt, games.jsonl
# and cli.txt, taken BEFORE reading (a dir that grows mid-read is re-read next time); new dirs are read, removed or renamed
# ones dropped. Written atomically (tmp + rename) under a lock; a missing or corrupt cache means a full scan and a rewrite.
# ABINDEX_NOCACHE=1 turns it off.
PAIR_CACHE = os.environ.get("ABINDEX_CACHE", "/data/zw4424/st/abindex_cache/pairs.json")


def _dir_key(d):
    out = []
    for f in ("manifest.txt", "games.jsonl", "cli.txt"):
        try:
            st = os.stat(os.path.join(d, f))
            out.append([st.st_mtime_ns, st.st_size, st.st_ino])
        except OSError:
            out.append(None)
    return out


def _manifest_pairs(d):
    out = set()
    try:
        for line in open(os.path.join(d, "manifest.txt")):
            f = line.split()
            if len(f) >= 2:
                out.add(os.path.basename(f[0]).rsplit("-", 1)[-1] + "|" + os.path.basename(f[1]).rsplit("-", 1)[-1])
    except OSError:
        pass
    return out


def dir_pairs(dirs):
    """{dir: set('hashA|hashB')} for the given run dirs, from the cache where a dir's key is unchanged."""
    try:
        cache = json.load(open(PAIR_CACHE))
        if not isinstance(cache, dict):
            raise ValueError("not a dict")
    except (OSError, ValueError):
        cache = {}
    out, fresh, changed = {}, {}, False
    for d in dirs:
        key = _dir_key(d)
        c = cache.get(d)
        if c and c[0] == key:
            out[d] = set(c[1])
        else:
            out[d] = _manifest_pairs(d)  # read after the key: never older than the key
            changed = True
        fresh[d] = [key, sorted(out[d])]
    if changed or set(cache) != set(fresh):
        try:
            os.makedirs(os.path.dirname(PAIR_CACHE), exist_ok=True)
            with open(PAIR_CACHE + ".lock", "a") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                tmp = f"{PAIR_CACHE}.{os.getpid()}.tmp"
                with open(tmp, "w") as f:
                    json.dump(fresh, f, separators=(",", ":"))
                os.replace(tmp, PAIR_CACHE)
        except OSError:
            pass
    return out


PATHO = {"boss_rush", "dash_test", "gatekeepers", "stanford_torus"}  # /data/zw4424/patho4.txt


def bot_hash(bot):
    """Source hash of bots/<bot> exactly as abl.sh and screen.sh compute it."""
    d = os.path.join(REPO, "bots", bot)
    if not os.path.isdir(os.path.join(d, "src")):
        return None
    import srchash  # 3 Nov: no spawn, byte-identical to the shell form (every exec on this machine costs /var/log/syslog ~2 KB)
    return srchash.src_hash(d) or None


def cli_id():
    st = os.stat(CLI)
    tag = "cambc304" if cli_version() == "3.0.4" else "cambc" + cli_version()
    return f"{tag}-{st.st_size}-{int(st.st_mtime)}"


def check_cli():
    """Local runs carry no engine or CLI id, so they are only comparable while abl.sh keeps using CLI."""
    import re
    try:
        m = re.search(r"CLI=\$\{ABL_CLI:-(\S+?)\}", open(os.path.join(REPO, "tools/lab/abl.sh")).read())
    except OSError:
        return
    if m and m.group(1) != os.environ.get("ABL_CLI", "/data/zw4424/cambc500/bin/cambc500") and "ABL_CLI" not in os.environ:
        import sys
        print(f"!! abl.sh now runs {m.group(1)}, but abindex assumes {CLI}: local results of the two CLIs would be "
              f"mixed. Update CLI and cli_id() in tools/lab/abindex.py first.", file=sys.stderr)


def map_set(name):
    """Map family: fresh (gen_s_*), genpatho (gen_p_*), custom (gen_c_*: tools/lab/genbig.py), dev (gen_dev_*),
    heldout (gen_NN only), unseen (gen_u_*, gen_up_*), gate (gen_g_*), gate2 (gen_g2_* .. gen_g9_*, the held-out twins
    of gate), ideology (gen_i_*), altar1 (gen_a_*: tools/lab/genaltar.py), gen (any other generated family), patho (the
    4 hand-made pathological maps), pool.
    Each generated family has its own label: lumping them into "heldout" mixed tuning maps (gate, ideology) and the
    unseen holdout into the gen_NN held-out check."""
    if name.startswith("gen_s_"):
        return "fresh"
    if name.startswith("gen_p_"):
        return "genpatho"
    if name.startswith("gen_c_"):
        return "custom"
    if name.startswith("gen_dev_"):
        return "dev"
    if name.startswith(("gen_u_", "gen_up_")):
        return "unseen"
    if name.startswith("gen_g_"):
        return "gate"
    if len(name) > 7 and name.startswith("gen_g") and name[5] in "23456789" and name[6] == "_":
        return "gate2"
    if name.startswith("gen_i_"):
        return "ideology"
    if name.startswith("gen_a_"):
        return "altar1"
    if name.startswith("gen_bk_"):
        return "bank"  # tools/lab/mapbank.py's frozen decision bank
    if name.startswith("gen_bh_"):
        return "bankho"  # its held-out bank: never for decisions
    if name.startswith("gen_bk2_"):
        return "bank2"  # tools/lab/mapbank2.py's ladder-matched decision bank (30 Oct)
    if name.startswith("gen_bh2_"):
        return "bankho2"  # its held-out bank: never for decisions
    if name.startswith("gen_"):
        return "heldout" if name[4:].isdigit() else "gen"
    return "patho" if name in PATHO else "pool"


_maps = None


MAPS_CACHE = "/data/zw4424/st/bq/abindex_maps_cache.json"  # {path: [mtime_ns, size, hash]}: 4 Nov, every condab leg re-hashed every map (3-4 s)


def maps():
    """{map name: (hash, path, mtime)} over the map dirs (the first dir that has a name wins). Hashes come from MAPS_CACHE when a
    file's path, mtime and size match; only new or changed maps are read."""
    global _maps
    if _maps is None:
        import json
        try:
            cache = json.load(open(MAPS_CACHE))
        except (OSError, ValueError):
            cache = {}
        _maps, changed, seen = {}, False, set()
        for d in MAP_DIRS:
            try:
                ents = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            for e in ents:
                if not e.name.endswith(".map26a"):
                    continue
                n, p = e.name[:-7], e.path
                if n in _maps:
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                c = cache.get(p)
                if c and c[0] == st.st_mtime_ns and c[1] == st.st_size:
                    h = c[2]
                else:
                    h = hashlib.sha1(open(p, "rb").read()).hexdigest()[:12]
                    cache[p] = [st.st_mtime_ns, st.st_size, h]
                    changed = True
                seen.add(p)
                _maps[n] = (h, p, st.st_mtime)
        if changed or len(cache) > 1.5 * max(1, len(seen)):
            cache = {k: v for k, v in cache.items() if k in seen}
            try:
                tmp = f"{MAPS_CACHE}.{os.getpid()}.tmp"
                json.dump(cache, open(tmp, "w"))
                os.replace(tmp, MAPS_CACHE)
            except OSError:
                pass
    return _maps


def map_names():
    """{map hash: map name}."""
    return {h: n for n, (h, _, _) in sorted(maps().items(), reverse=True)}


def recorded(name):
    """{source hash: newest run time} of every version of bots/<name> that local abl.sh runs played."""
    seen = {}
    for d in glob.glob(os.path.join(ABL, "*", "manifest.txt")):
        t = os.path.getmtime(d)
        for line in open(d):
            for p in line.split()[:2]:
                n, _, hh = os.path.basename(p).rpartition("-")
                if n == name:
                    seen[hh] = max(seen.get(hh, 0), t)
    return seen


def resolve(spec):
    """Bot spec -> (name, hash): 'nova_x' (current source in bots/), 'nova_x@<hash>' or a bare 12-hex hash.
    A name whose bots/ dir is gone (archived) resolves to the newest source hash local runs recorded for it."""
    if "@" in spec:
        n, h = spec.split("@", 1)
        return n, h
    if len(spec) == 12 and all(c in "0123456789abcdef" for c in spec):
        return spec, spec
    h = bot_hash(spec)
    if h:
        return spec, h
    seen = recorded(spec)
    if not seen:
        return spec, None
    h = max(seen, key=seen.get)
    import sys
    print(f"note: bots/{spec} is gone; using its newest recorded source {spec}@{h}"
          + (f" (other versions: {', '.join(sorted(set(seen) - {h}))})" if len(seen) > 1 else ""), file=sys.stderr)
    return spec, h


class Index:
    def __init__(self, hashes=None, local=True, screen=True, rich=False):
        """rich=True also attaches each local game's tools/lab/gamefeat.py features (games_rich.jsonl) as rec['rich']."""
        global _maps
        self.want_rich = rich
        _maps = None  # re-hash the map files: a long run (sprt.py) must see maps that changed since it started
        check_cli()
        self.only = set(hashes) if hashes else None
        self.games = {}           # (hashA, hashB, maphash) -> {win, rounds, sa, sb, src}
        self.names = {}           # hash -> set of bot names seen with it
        self.conflicts = []       # keys whose sources disagree on the winner
        self.runs = set()
        if local:
            self._local()
        if screen:
            self._screen()

    def _add(self, k, rec):
        old = self.games.get(k)
        if old is None:
            self.games[k] = rec
            return
        old.setdefault("also", []).append(rec["src"])  # every other source of the same game (sprt.py names them)
        if old["win"] != rec["win"]:
            self.conflicts.append((k, old["src"], rec["src"]))
        elif "rich" in rec and "rich" not in old:
            old["rich"] = rec["rich"]  # the same deterministic game, with tools/lab/gamefeat.py features

    def _local(self):
        mp = maps()
        cli_t = os.path.getmtime(CLI)
        want = "cambc " + cli_version()
        dirs = sorted(glob.glob(os.path.join(ABL, "*", "")))
        dp = dir_pairs(dirs) if self.only and os.environ.get("ABINDEX_NOCACHE") != "1" else None
        for d in dirs:
            if dp is not None and not any(a in self.only and b in self.only for a, b in (x.split("|") for x in dp[d])):
                continue  # no game between two of the wanted hashes in this run
            man, gj = os.path.join(d, "manifest.txt"), os.path.join(d, "games.jsonl")
            if not (os.path.exists(man) and os.path.exists(gj)):
                continue
            t = os.path.getmtime(gj)
            if t < cli_t:
                continue
            try:  # runs without cli.txt predate it and used cambc 3.0.4
                cv = open(os.path.join(d, "cli.txt")).read().strip() or "cambc 3.0.4"
            except OSError:
                cv = "cambc 3.0.4"
            if cv != want:
                continue
            lines = open(man).read().split("\n")
            run = os.path.basename(d.rstrip("/"))
            rich = None  # this run's features, parsed only if one of its games is wanted
            rp = os.path.join(d, "games_rich.jsonl")
            for line in open(gj):
                try:
                    g = json.loads(line)
                    f = lines[int(g["id"]) - 1].split()
                    na, ha = os.path.basename(f[0]).rsplit("-", 1)
                    nb, hb = os.path.basename(f[1]).rsplit("-", 1)
                    m = os.path.basename(f[2])[:-7]
                except (ValueError, IndexError, KeyError):
                    break  # not an abl.sh run of this format
                if (na, nb, m) != (g["a"], g["b"], g["map"]):
                    break
                if not g.get("ok") or g.get("win") not in ("A", "B") or m not in mp or mp[m][2] > t:
                    continue
                if self.only and (ha not in self.only or hb not in self.only):
                    continue
                self.names.setdefault(ha, set()).add(na)
                self.names.setdefault(hb, set()).add(nb)
                self.runs.add(run)
                rec = dict(win=g["win"], rounds=g.get("rounds", 0), sa=g["sa"], sb=g["sb"], src="abl:" + run)
                if rich is None:
                    rich = {}
                    if self.want_rich and os.path.exists(rp):
                        for ln in open(rp):
                            try:
                                x = json.loads(ln)
                                if "error" not in x:
                                    rich[x["id"]] = x
                            except ValueError:
                                pass
                if g["id"] in rich:
                    rec["rich"] = rich[g["id"]]
                self._add((ha, hb, mp[m][0]), rec)

    def _screen(self):
        if not os.path.exists(SCREEN_CACHE):
            return
        cid = cli_id()
        with open(SCREEN_CACHE) as f:
            for line in f:
                if self.only and (line[6:18] not in self.only or line[19:31] not in self.only):
                    continue
                try:
                    x = json.loads(line)
                    ha, hb, mh, c = x["k"].split("|")
                except (ValueError, KeyError):
                    continue
                if c != cid or x.get("win") not in ("A", "B"):
                    continue
                self._add((ha, hb, mh), dict(win=x["win"], rounds=x.get("rounds", 0), sa=x["sa"], sb=x["sb"],
                                             src="screen"))

    def pairs(self, hx, hy):
        """{maphash: (game with hx as team A or None, game with hy as team A or None)}"""
        out = {}
        for (ha, hb, mh), g in self.games.items():
            if (ha, hb) == (hx, hy):
                out.setdefault(mh, [None, None])[0] = g
            elif (ha, hb) == (hy, hx):
                out.setdefault(mh, [None, None])[1] = g
        return {k: tuple(v) for k, v in out.items()}


def map_pairs(ix, hx, hy):
    """Complete map pairs (both sides played) for bot hx against hy, as abstat rows:
    [(map name, map set, score of hx in {0, 0.5, 1}, hx gems over both games, hy gems over both games)].
    Returns (rows, number of maps with only one side played)."""
    names = map_names()
    rows, half = [], 0
    for mh, (g1, g2) in ix.pairs(hx, hy).items():
        if g1 is None or g2 is None:
            half += 1
            continue
        m = names.get(mh)
        fam = map_set(m) if m else "other"  # a map file no longer installed: known only by its hash
        m = m or mh
        s = ((g1["win"] == "A") + (g2["win"] == "B")) / 2
        gx = g1["sa"].get("gems", 0) + g2["sb"].get("gems", 0)
        gy = g1["sb"].get("gems", 0) + g2["sa"].get("gems", 0)
        rows.append((m, fam, s, gx, gy))
    rows.sort()
    return rows, half


if __name__ == "__main__":
    ix = Index(screen=False)
    n = sum(1 for _ in open(SCREEN_CACHE)) if os.path.exists(SCREEN_CACHE) else 0
    print(f"local runs: {len(ix.games)} distinct games, {len(ix.names)} bot versions, {len(ix.runs)} runs; "
          f"{len(ix.conflicts)} determinism conflicts; screen cache: {n} games")
    for k, a, b in ix.conflicts[:10]:
        print("  CONFLICT", k, a, b)
