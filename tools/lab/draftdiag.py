#!/usr/bin/env python3
"""draftdiag: diag records from the DRAFT turn (and the first rounds) of a diag copy, on many maps, fast (Tool Builder, 9 Nov; Builder: b1748 and
b1767 could not see draft-turn values). dgkit's DG() buffers records and writes them at a play turn's end in debug builds only, so draft records
never came out. Use tools/lab/dglog.h instead: it writes each record at once, in release builds, and the native engine (cxe) keeps every instance
of a team, the draft one included, in that team's stdout (CXE_STDOUT=1). Each game stops after --rounds rounds (default 2), so a map costs seconds.

  1. sh tools/lab/newbot.sh BASE nova_bNNN_dg; cp tools/lab/dglog.h bots/nova_bNNN_dg/src/; in the draft code: #include "dglog.h", then
     DGLOG(-1000000, 1000000, TAG, a, b, c, d);   integers only (int(100 * x) for floats); round = the draft round (0, 1, ...) during the draft
  2. python3 -I tools/lab/draftdiag.py nova_bNNN_dg MAPS OUT [--opp BOT] [--rounds 2] [--par 6]
     MAPS: a directory of .map26a, or a file with one map path per line. --opp: the other team (default the same bot: one game gives both teams'
     drafts). With a different --opp, each map is played in both seats and only the diag bot's team is kept.
Out: OUT/records.tsv (map seat round tag a b c d), one row per DG record of the diag bot's team(s); OUT/games/ holds the raw stdout files.
Never arm or submit a diag copy; delete it with tools/lab/rmdata.sh when done."""
import concurrent.futures as cf
import glob
import os
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, os.path.join(REPO, "tools/cxe"))
import cxebuild  # noqa: E402


def maps_of(src):
    if os.path.isdir(src):
        return sorted(glob.glob(os.path.join(src, "*.map26a")))
    return [ln.strip() for ln in open(src) if ln.strip() and not ln.startswith("#")]


def wait_load(limit=None):
    if limit is None:  # 12 Nov ~21:5xZ (Builder): live from bq/load_limits like cxebuild (draftdiag_load, else cxe_build_load), was a fixed 40
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import loadlim
            limit = float(loadlim.get("draftdiag_load", loadlim.get("cxe_build_load", 40)))
        except Exception:  # noqa: BLE001
            limit = 40.0
    for _ in range(120):
        if os.getloadavg()[0] < limit:
            return
        time.sleep(15)


def main():
    a = sys.argv[1:]
    if len(a) < 3:
        sys.exit(__doc__)
    bot, src, out = a[0], a[1], a[2]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    opp, rounds, par = opt("--opp", bot), int(opt("--rounds", "2")), int(opt("--par", "6"))
    os.makedirs(os.path.join(out, "games"), exist_ok=True)
    host = cxebuild.build_host()
    so = lambda b: (lambda s: s if isinstance(s, str) else s[0])(cxebuild.build_bot(b))  # noqa: E731
    sb, so_ = so(bot), so(opp)
    maps = maps_of(src)
    # (map, seat of the diag bot: 'a' / 'b' / 'ab' when both teams are the diag bot)
    jobs = [(m, "ab") for m in maps] if opp == bot else [(m, s) for m in maps for s in "ab"]

    def play(job):
        m, seat = job
        nm = os.path.basename(m)[:-len(".map26a")]
        pre = os.path.join(out, "games", f"{nm}__{seat}")
        A, B = (sb, so_) if seat in ("a", "ab") else (so_, sb)
        wait_load()
        r = subprocess.run(["nice", "-n", "10", host, A, B, m, pre, "--rounds", str(rounds)], env=dict(os.environ, CXE_STDOUT="1"),
                           capture_output=True, text=True, timeout=1800)
        rows = []
        for t in "ab":
            if t not in seat:
                continue
            try:
                txt = open(f"{pre}.team-{t}.stdout", errors="replace").read()
            except OSError:
                continue
            for ln in txt.splitlines():
                p = ln.replace("\0", "").split()
                if len(p) == 7 and p[0] == "DG":
                    rows.append((nm, t, p[2], p[1], *p[3:7]))
        for f in glob.glob(pre + "*.repl26a"):
            os.remove(f)  # only the stdout is needed
        return r.returncode, rows

    # 12 Nov ~21:5xZ (Builder; owner: "why slow with free compute"): the games go to the PILOTS first (tools/cxe/pilotcxe.py, team
    # stdout kept), so the main machine only parses records; local play (the old path, load-gated) is the fallback. DRAFTDIAG_LOCAL=1: local.
    pre_played = False
    if os.environ.get("DRAFTDIAG_LOCAL") != "1":
        try:
            sys.path.insert(0, os.path.join(REPO, "tools/cxe"))
            import pilotcxe
            games = []
            for m, seat in jobs:
                nm = os.path.basename(m)[:-len(".map26a")]
                A, B = (sb, so_) if seat in ("a", "ab") else (so_, sb)
                games.append((A, B, m, os.path.join(out, "games", f"{nm}__{seat}"), f"--rounds {rounds}"))
            pre_played = pilotcxe.run(games, env={"CXE_STDOUT": "1"}, say=lambda x: print(f"draftdiag: {x}", flush=True))
        except Exception as e:  # noqa: BLE001  any pilot problem: play locally
            print(f"draftdiag: pilots failed ({type(e).__name__}: {str(e)[:120]}): playing locally", flush=True)
            pre_played = False
    n = bad = 0
    if pre_played:
        play_local = play

        def play(job):  # noqa: F811  the pilots played it: parse only
            m, seat = job
            nm = os.path.basename(m)[:-len(".map26a")]
            pre = os.path.join(out, "games", f"{nm}__{seat}")
            rows = []
            for t in "ab":
                if t not in seat:
                    continue
                try:
                    txt = open(f"{pre}.team-{t}.stdout", errors="replace").read()
                except OSError:
                    continue
                for ln in txt.splitlines():
                    p = ln.replace("\0", "").split()
                    if len(p) == 7 and p[0] == "DG":
                        rows.append((nm, t, p[2], p[1], *p[3:7]))
            for g in glob.glob(pre + "*.repl26a"):
                os.remove(g)
            return 0, rows
        del play_local
    with open(os.path.join(out, "records.tsv"), "w") as f, cf.ThreadPoolExecutor(par) as ex:
        f.write("map\tseat\tround\ttag\ta\tb\tc\td\n")
        for rc, rows in ex.map(play, jobs):
            n += 1
            bad += rc != 0
            f.writelines("\t".join(r) + "\n" for r in rows)
    print(f"draftdiag: {n} games ({bad} non-zero exits) -> {out}/records.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
