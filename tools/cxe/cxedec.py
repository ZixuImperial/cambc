"""cxedec: replay decoding on cxe, a native port of condor-work/tools/rdec.js (cxedec.cpp) with the same JSON out.
tools/lab/replay.py decodes through decode() first and falls back to rdec.js (node) when this returns None: a replay
from another engine than 2.0.0, no usable cxe binary, or an rdec.js newer than the one ported (RDEC_PORTED: the port
is only trusted while rdec.js is the file it was checked against, so a decoder fix there is never silently skipped).
The match/check part for games with a summary (live sets, kept statistics) is rdec.js's teamInfo/crossCheck, in Python.
usage:
  python3 -I tools/cxe/cxedec.py REPLAY OUT.json [--summary SUMMARY.json]
  python3 -I tools/cxe/cxedec.py --verify [N] [--jobs 8]   N live replays (with their summaries) decoded by both;
       every one must be identical apart from decoder.ms. Exit 0 identical, 1 not."""
import glob
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RDEC = "/homes/zw4424/condor-work/tools/rdec.js"
RDEC_PORTED = "50ca11ec850c"  # sha1[:12] of the rdec.js cxedec.cpp was ported from and verified against (4 Nov)
HOST = "/data/zw4424/st/cxe/host/cxe"
RT_HOME = "/homes/zw4424/condor-runs/cxe"  # the Condor runtime bundles (nodes can't read /data or run maple04's glibc)
PLAT = "/data/zw4424/plat"
DECODE_TIMEOUT = float(os.environ.get("REPLAY_DECODE_TIMEOUT", "120") or 120)  # 10 Nov (b1815: some replays never finish decoding): s per decode


class DecodeTimeout(RuntimeError):  # not TimeoutError: that is an OSError, which the callers below swallow
    """A decode subprocess ran past REPLAY_DECODE_TIMEOUT and was killed (replay.DecodeTimeout is raised from it)."""
_cmd = []


def exe():
    """The cxe command that can --decode here, or None: the local host, else the newest staged runtime that has it."""
    if not _cmd:
        c = None
        try:
            if hashlib.sha1(open(RDEC, "rb").read()).hexdigest()[:12] == RDEC_PORTED:
                if os.access(HOST, os.X_OK):
                    c = [HOST]
                else:
                    for rt in sorted(glob.glob(RT_HOME + "/rt-*[0-9a-f]"), key=os.path.getmtime, reverse=True):
                        if b"--record" in open(rt + "/cxe", "rb").read():
                            c = [rt + "/ld-linux-x86-64.so.2", "--library-path", rt, rt + "/cxe"]
                            break
        except OSError:
            c = None
        _cmd.append(c)
    return _cmd[0]


def _num(x):  # JS Number()
    if x is None:
        return 0.0
    if isinstance(x, (bool, int, float)):
        return float(x)
    try:
        return float(x.strip()) if x.strip() else 0.0
    except (ValueError, AttributeError):
        return math.nan


def _js(x):  # JS template-literal string of a value
    if isinstance(x, bool):
        return "true" if x else "false"
    if x is None:
        return "null"
    if isinstance(x, float):
        return "NaN" if x != x else (str(int(x)) if x == int(x) else repr(x))
    if isinstance(x, list):
        return ",".join("" if v is None else _js(v) for v in x)
    return str(x)


def team_info(summary):
    """rdec.js teamInfo(null, summary)."""
    out = {"matchId": None, "map": None, "createdAt": None, "endReason": None, "engineVersion": None, "teams": []}
    m = summary.get("match") if summary else None
    if m:
        out["engineVersion"] = m.get("engineVersion") or out["engineVersion"]
        out["platform"] = {k: m[k] for k in ("outcome", "roundsCompleted", "roundsStarted", "finalInput", "seed", "width", "height") if k in m}
        if isinstance(summary.get("teams"), list):
            sg = [_num(t.get("submittedGems")) for t in summary["teams"]]
            out["platform"]["submittedGems"] = [None if v != v else (int(v) if v == int(v) else v) for v in sg]
    return out


def cross_check(dec, summary):
    """rdec.js crossCheck(dec, summary)."""
    if not summary:
        return {"ok": None, "diffs": ["no summary"]}
    diffs = []
    m = summary.get("match") or {}
    sub = [_num(t.get("submittedGems")) for t in (summary.get("teams") or [])]
    fin = dec.get("final")
    if fin and len(sub) == 2 and (fin["submitted"][0] != sub[0] or fin["submitted"][1] != sub[1]):
        diffs.append(f"submitted {_js(fin['submitted'])} vs platform {_js(sub)}")
    oc = 1 if m.get("outcome") == "teamA" else 2 if m.get("outcome") == "teamB" else None
    if oc and fin and fin["outcome"] != oc:
        diffs.append(f"outcome {_js(fin['outcome'])} vs platform {_js(m.get('outcome'))}")
    rs = m.get("roundsStarted")
    if rs and fin and (fin["round"] != rs or type(rs) is str):
        diffs.append(f"round {_js(fin['round'])} vs platform roundsStarted {_js(rs)}")
    by_id = {b["id"]: b for b in (dec.get("stats") or {}).get("bodies") or []}
    for c in summary.get("champions") or []:
        b = by_id.get(c.get("id"))
        mt = c.get("metrics")
        if not b or not mt:
            continue
        for k, v in (("kills", b["kills"]), ("deaths", b["deaths"]), ("earnedGold", b["earnedGold"]),
                     ("submittedGems", b["gemsTributed"]), ("spentGold", b["goldSpent"])):
            if k in mt and _num(mt[k]) != v:
                diffs.append(f"body {_js(c['id'])} {k} {_js(v)} vs platform {_js(mt[k])}")
    return {"ok": len(diffs) == 0, "diffs": diffs}


HOSTS = {2: "/data/zw4424/st/cxe/host/cxe-v2_0_0", 3: "/data/zw4424/st/cxe/host/cxe-v3_0_0"}  # replay header version word (bytes 8-11) -> the host of that engine


def replay_version(replay):
    """The engine major version a raw .repl26a was written by (2 = engine 2.0.0, 3 = 3.0.0), or 0."""
    try:
        with open(replay, "rb") as f:
            h = f.read(12)
        return int.from_bytes(h[8:12], "little") if h[:6] == b"a62per" else 0
    except OSError:
        return 0


class _slot:
    """One of CXE_DEC_SLOTS (default 4) machine-wide decode slots (flock), held around a native decode (Builder 6 Nov: ~30 decodes from
    estcheck/estscore at once took maple02 to load 36; VS Code crashed at 48). Waiters sleep; a slot frees when its holder exits."""
    def __enter__(self):
        import fcntl
        d = os.path.exists("/data/zw4424/st/bq/live.txt") and '/data/zw4424/st/cxe/decslots' or os.path.join(os.environ.get("_CONDOR_SCRATCH_DIR") or "/tmp", 'zw4424-decslots')  # 10 Nov: /data only on the main machine (live.txt there); on Condor nodes the job's scratch dir, else /tmp (a lab user found our caches on their desktop's /data)
        n = int(os.environ.get("CXE_DEC_SLOTS", "4"))
        self.f = None
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return self
        import time
        while True:
            for k in range(n):
                f = open(os.path.join(d, f"slot{k}.lock"), "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.f = f
                    return self
                except OSError:
                    f.close()
            time.sleep(0.3)

    def __exit__(self, *a):
        if self.f:
            self.f.close()


REMOTE_BIN = "/homes/zw4424/condor-work/bin/cxe-v3_0_0"  # a copy of HOSTS[3] on the shared home, runnable on any maple
REMOTE_HOSTS = "/data/zw4424/st/bq/decode_hosts.txt"  # one host a line (e.g. maple09); empty or missing: decode here as before


def _remote_decode(replay, tmp, timeout):
    """10 Nov (owner: lighten the main machine, offload replay decoding to the shared test machines): on the main machine only, decode a 3.0.0
    replay on one of bq/decode_hosts.txt over ssh (replay in on stdin, json back on stdout; nothing written to the remote's /data, only its
    /tmp), at most CXE_REMOTE_SLOTS (6) at once per host (flock slots in /data/zw4424/st/cxe/decslots_remote). Identical output to a local
    decode except the decoder's own timing field. -> True when tmp now holds the json; False: decode here as before."""
    # 11 Nov 09:5xZ (TB 6ad907): OFF by default. Each remote decode is one ssh login (~5 KB of maple20's root syslog, plus the remote host's /var):
    # draftstock's ~12 ssh/s doubled syslog growth while /var sat at 1.1 GB. Opt in per caller with CXE_DEC_REMOTE=1.
    if os.environ.get("CXE_DEC_REMOTE") != "1" or os.environ.get("CXE_DEC_LOCAL") == "1" or not os.path.exists("/data/zw4424/st/bq/live.txt") or not os.access(REMOTE_BIN, os.X_OK):
        return False
    try:
        hosts = [h.split()[0] for h in open(REMOTE_HOSTS) if h.strip() and not h.startswith("#")]
    except OSError:
        return False
    if not hosts:
        return False
    import fcntl
    import random
    d = "/data/zw4424/st/cxe/decslots_remote"
    os.makedirs(d, exist_ok=True)
    n = int(os.environ.get("CXE_REMOTE_SLOTS", "6"))
    random.shuffle(hosts)
    for h in hosts:
        for k in range(n):
            lf = open(os.path.join(d, f"{h}_{k}.lock"), "w")
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lf.close()
                continue
            try:
                cmd = ("f=$(mktemp /tmp/zw4424dec.XXXXXX); trap 'rm -f $f $f.r $f.j' EXIT; cat > $f.r && "
                       f"nice -n 15 {REMOTE_BIN} --decode $f.r $f.j >/dev/null 2>&1 && cat $f.j")
                with open(replay, "rb") as fin, open(tmp + ".part", "wb") as fout:
                    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", h, cmd], stdin=fin, stdout=fout,
                                       stderr=subprocess.DEVNULL, timeout=timeout)
                if r.returncode == 0 and os.path.getsize(tmp + ".part") > 2:
                    os.replace(tmp + ".part", tmp)
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                lf.close()
                try:
                    os.remove(tmp + ".part")
                except OSError:
                    pass
            break  # this host failed: try the next host
    return False


def decode(replay, out=None, summary=None, timeout=None):
    """Decode a replay file natively. -> the rdec.js dict (also written to out when given), or None (use rdec.js).
    A 3.0.0 replay goes to the 3.0.0 host (4 Nov: a 2.0.0 host refuses it with exit 3).
    10 Nov: a decode running past timeout (default REPLAY_DECODE_TIMEOUT, 120 s) is killed and raises DecodeTimeout (its slot frees)."""
    timeout = timeout or DECODE_TIMEOUT
    v = replay_version(replay)
    c = [HOSTS[v]] if v in HOSTS and os.access(HOSTS[v], os.X_OK) else exe()
    if not c:
        return None
    tmp = out or tempfile.mktemp(suffix=".json", dir=os.path.dirname(os.path.abspath(replay)))
    if v == 3 and _remote_decode(replay, tmp, timeout):  # 10 Nov (owner: "lighten the main machine ... offload"): shared test machines first
        c = None
    try:
        if c is None:
            pass
        else:
          with _slot():
            try:
                r = subprocess.run(["nice", "-n", "19"] + c + ["--decode", replay, tmp], capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise DecodeTimeout(f"native decode of {replay} ran over {timeout:.0f} s (REPLAY_DECODE_TIMEOUT)") from None
          if r.returncode != 0:
            return None
        if not os.path.exists(tmp):
            return None
        d = json.load(open(tmp))
    except (OSError, ValueError):
        return None
    finally:
        if not out and os.path.exists(tmp):
            os.remove(tmp)
    sm = None
    if summary and os.path.exists(summary):
        try:
            sm = json.load(open(summary, encoding="utf-8"))
        except (OSError, ValueError):
            return None  # rdec.js would fail the same way: let it report
    if sm is not None:
        d["match"] = team_info(sm)
        d["check"] = cross_check(d, sm)
        if out:
            json.dump(d, open(out, "w"), separators=(",", ":"))
    return d


def _verify_one(job):
    rp, sm, wd = job
    j, n = os.path.join(wd, "j.json"), os.path.join(wd, "n.json")
    try:
        subprocess.run(["node", RDEC, rp, j] + (["--summary", sm] if sm else []), capture_output=True, timeout=DECODE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return rp, "rdec.js timed out"
    try:
        d = decode(rp, n, sm)
    except DecodeTimeout:
        return rp, "cxe timed out"
    try:
        a = json.load(open(j))
    except (OSError, ValueError):
        return rp, "rdec.js failed" if d else "both failed"
    if d is None:
        return rp, "cxe failed"
    for x in (a, d):
        x["decoder"].pop("ms", None)
    if a == d:
        return rp, None
    bad = next(k for k in a if a.get(k) != d.get(k))
    return rp, f"differs in {bad}"


def verify(n, jobs):
    import concurrent.futures as cf
    games = []
    for d in sorted(glob.glob(PLAT + "/*")):
        for x in glob.glob(d + "/x_*/replay.repl26a"):
            sm = os.path.join(d, os.path.basename(os.path.dirname(x))[2:] + ".json")
            games.append((x, sm if os.path.exists(sm) else None))
    games = [g for g in games if open(g[0], "rb").read(4)]  # keep everything; old-engine replays must fall back
    random.Random(len(games)).shuffle(games)
    games = games[:n]
    root = tempfile.mkdtemp(prefix="cxedec_verify_", dir="/data/zw4424/st/cxe")
    jobs_ = [(rp, sm, tempfile.mkdtemp(dir=root)) for rp, sm in games]
    same, bad, fall = 0, [], 0
    with cf.ThreadPoolExecutor(jobs) as ex:
        for rp, why in ex.map(_verify_one, jobs_):
            if why is None:
                same += 1
            elif why == "cxe failed":
                fall += 1
            else:
                bad.append(f"{rp}: {why}")
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    print(f"cxedec --verify: {same}/{len(games)} identical to rdec.js (with summaries {sum(1 for g in games if g[1])}), "
          f"{fall} fell back to rdec.js, {len(bad)} differ")
    for b in bad[:10]:
        print("  " + b)
    return 0 if not bad else 1


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "--verify":
        n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 100
        return verify(n, int(a[a.index("--jobs") + 1]) if "--jobs" in a else 8)
    sm = a[a.index("--summary") + 1] if "--summary" in a else None
    d = decode(a[0], a[1], sm)
    if d is None:
        sys.exit("cxedec: not decoded natively (other engine or no cxe binary): use rdec.js")
    print(f"{a[1]}: {d['decoder']['steps']} steps, {len(d['turns'])} turns, {len(d['events'])} events, final {json.dumps(d['final'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
