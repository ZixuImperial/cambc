#!/usr/bin/env python3
"""pilotcxe: a cxerun-style list of cxe games on the Condor pilots (Tool builder 2, 6 Nov; owner: "make condor do more work that you
can offload"). A thin adapter over tools/cxe/cxefarm.py (the Tool builder's pilot game farm: same runtime and libraries, byte-identical
games), so cxeident, mergecheck's null identity and cxeab can hand it cxerun's manifest rows. Outputs land where a local run puts them:
OUT.repl26a, OUT.fuel.tsv, OUT.json (an arg @STATS@ = this game's --statistics path), OUT.team-a/b.stdout (env CXE_STDOUT=1).

API:  run(games, say=print, env=None) -> True when every game came back, else False (the caller plays locally).
        games: [(so_a, so_b, map_path, out_prefix, extra_args_str)]; digest=True: OUT.sha1 (the replay's sha1, made on the node) comes back instead of OUT.repl26a
CLI:  python3 -I tools/cxe/pilotcxe.py MANIFEST     (cxerun.py's manifest format: SO_A SO_B MAP OUT_PREFIX [args...])
Off switch: PILOTCXE=0 (or CXE_LOCAL=1). On by default even for small runs (callers ask for the pilots: local is the fallback);
PILOTCXE=auto leaves the choice to cxefarm (pilots at >= CXEFARM_MIN games or load >= CXEFARM_LOAD)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FILES = ("repl26a", "fuel.tsv", "json", "team-a.stdout", "team-b.stdout")


def enabled():
    return os.environ.get("PILOTCXE", "1") not in ("", "0") and not os.environ.get("CXE_LOCAL")


def run(games, say=print, env=None, digest=False, **_):
    if not enabled() or not games:
        return False
    try:
        import cxefarm
    except ImportError as e:
        say(f"pilotcxe: no cxefarm ({e}): local")
        return False
    fg = []
    for k, (a, b, mp, out, extra) in enumerate(games):
        args = [x.replace("@STATS@", "@D@/g.json") for x in extra.split()]
        want = ["sha1" if digest else "repl26a"] + (["fuel.tsv"] if "--fuel-log" in args else []) + (["json"] if "@D@/g.json" in args else []) \
            + (["team-a.stdout", "team-b.stdout"] if (env or {}).get("CXE_STDOUT") else [])  # only files this game writes
        opt = {"g.cphase.tsv": f"{out}.cphase.tsv"} if "--fuel-log" in args else {}  # 12 Nov (PCQ): a marker bot's cut-phase log, when it has one
        fg.append(dict(id=k, a=a, b=b, map=mp, env=dict(env or {}), args=args, digest=digest, files={f"g.{e}": f"{out}.{e}" for e in want}, optfiles=opt))
    old = os.environ.get("CXEFARM")
    if os.environ.get("PILOTCXE") != "auto":
        os.environ["CXEFARM"] = "1"
    try:
        got = cxefarm.run(fg, say=lambda m: say(f"pilotcxe: {m}"), per=int(os.environ.get("PILOTCXE_PER", 20)),
                          cpus=int(os.environ.get("PILOTCXE_CPUS", 8)), prio=int(os.environ.get("PILOTCXE_PRIO") or os.environ.get("READ_PRIO") or 12))  # identity games: mergecheck waits on them. 20 games an item: 160 games in ~38 s (6 an item: 60 s)
    except Exception as e:  # noqa: BLE001  never break the caller: it plays locally
        say(f"pilotcxe: cxefarm failed ({str(e)[:120]}): local")
        return False
    finally:
        if old is None:
            os.environ.pop("CXEFARM", None)
        else:
            os.environ["CXEFARM"] = old
    if got is None or got < len(games) or not all(os.path.exists(f"{g[3]}.{'sha1' if digest else 'repl26a'}") for g in games):
        say(f"pilotcxe: {got if got is not None else 'no'} of {len(games)} games back: local")
        return False
    return True


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    games = [(p[0], p[1], p[2], p[3], " ".join(p[4:])) for p in (ln.split() for ln in open(sys.argv[1]) if not ln.startswith("#"))
             if len(p) >= 4]
    ok = run(games)
    print("pilotcxe:", "OK" if ok else "FALLBACK (play locally)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
