#!/usr/bin/env python3
"""pilotbuild BOT OUT.wasm [--debug]: a release (--debug: the CLI's debug) build of bots/BOT on a pilot, off this machine, in ~30 s. Tool builder, 2 Nov (flip.sh and trunkmerge each compiled here: load 56).
Exit 0 with OUT written, else 1: the caller builds locally, which also shows any compile error."""
import os
import sys
import tarfile
import tempfile

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import mergecheck as M  # noqa: E402


def main():
    bot, out = sys.argv[1:3]
    debug = "--debug" in sys.argv[3:]  # 7 Nov: the CLI's debug build (dbgso's diag copies), not --release
    M.setup_ws()  # 10 Nov (Deep via Builder): a host move left mergecheck/ws missing; create or repair it before packing from it
    os.makedirs(os.path.join(M.ROOT, "builds"), exist_ok=True)
    run = tempfile.mkdtemp(prefix="pb_", dir=os.path.join(M.ROOT, "builds"))
    with tarfile.open(os.path.join(run, "in.tgz"), "w:gz") as tf:
        for x in ("cambc.toml", "sdk", "cmake"):
            tf.add(os.path.join(M.WS, x), arcname="proj/" + x)
        tf.add(os.path.join("/homes/zw4424/cambc/bots", bot, "src"), arcname=f"proj/bots/{bot}/src")
    # 11 Nov (Builder b1844: each diag copy built locally, 8 clangs, load 45-62): 240 s was short behind the ship legs, so the fallback built
    # here anyway. Wait up to PILOTBUILD_WAIT_HI (900 s) while the load is over PILOTBUILD_LOAD (30); else PILOTBUILD_WAIT (240).
    try:
        hi = os.getloadavg()[0] > float(os.environ.get("PILOTBUILD_LOAD", "30"))
    except OSError:
        hi = False
    wait = int(os.environ.get("PILOTBUILD_WAIT_HI", "900") if hi else os.environ.get("PILOTBUILD_WAIT", "240"))
    if not M.pilot_build(run, bot, wait=wait, debug=debug):
        return 1
    with tarfile.open(os.path.join(run, "out.tgz")) as tf:
        w = next((m for m in tf.getmembers() if m.name.endswith(bot + ".wasm")), None)
        if not w:
            return 1
        with open(out + ".tmp", "wb") as f:
            f.write(tf.extractfile(w).read())
    os.replace(out + ".tmp", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
