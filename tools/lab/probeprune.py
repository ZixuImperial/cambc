#!/usr/bin/env python3
"""probeprune: clear what draft probes leave behind (5 Nov, owner: cut the bloat). DRY by default; --apply deletes.
usage: python3 -I tools/lab/probeprune.py [--apply] [--maps-hours H]
Under /data/zw4424/st/panel/*/probe/:
  1. 1-round replays (*.repl26a in bK/rep/ and verify/rep/): draftprobe reads each batch's lineups once, right after the batch, into
     probe.json; nothing reads the replays again. Removed when the probe is done (probe.json done) or its newest file is 6 h old
     (an abandoned probe). Since 5 Nov draftprobe removes them itself (DP_KEEP_REPLAYS=1 keeps them).
  2. probe maps (bK/*.map26a, verify/*.map26a): only probe reuse needs them (draftprobe.find_donor adopts the newest finished probe
     of the same draft key AND the same BASE). Removed when the probe's BASE is no longer the live bot nor its trunk, and probe.json
     is older than --maps-hours (default 24). probe.json, otf.json and the changed maps at the read's top level are kept, so every
     read stays re-runnable (its maps rebuild from the seeds in otf.json).
Skips any probe a running process names (its panel tag on a command line)."""
import glob
import json
import os
import subprocess
import sys
import time

PANEL = "/data/zw4424/st/panel"


def newest(d):
    t = 0.0
    for root, _, fs in os.walk(d):
        for f in fs:
            try:
                t = max(t, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return t


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    apply = "--apply" in a
    mh = float(a[a.index("--maps-hours") + 1]) if "--maps-hours" in a else 24.0
    live = open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    keep_base = {live}
    try:  # the trunks built on live (armq/trunk_registry) may still be a probe's BASE
        for ln in open("/homes/zw4424/condor-work/reports/trunk_registry.md"):
            if live in ln:
                keep_base.update(w for w in ln.replace("|", " ").split() if w.startswith("nova_trunk"))
    except OSError:
        pass
    cmd = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    now = time.time()
    rep_n = rep_b = map_n = map_b = skipped = 0
    for pd in sorted(glob.glob(f"{PANEL}/*/probe")):
        top = os.path.dirname(pd)
        tag = os.path.basename(top)
        if tag in cmd:
            skipped += 1
            continue
        try:
            st = json.load(open(f"{top}/probe.json"))
            pj_t = os.path.getmtime(f"{top}/probe.json")
        except (OSError, ValueError):
            st, pj_t = {}, 0.0
        old = now - newest(pd) > 6 * 3600
        drop_rep = st.get("done") or old
        drop_map = pj_t and now - pj_t > mh * 3600 and st.get("base") not in keep_base and (st.get("done") or old)
        for root, _, fs in os.walk(pd):
            for f in fs:
                p = os.path.join(root, f)
                is_rep, is_map = f.endswith(".repl26a"), f.endswith(".map26a")
                if not ((is_rep and drop_rep) or (is_map and drop_map)):
                    continue
                try:
                    sz = os.path.getsize(p)
                    if apply:
                        os.remove(p)
                except OSError:
                    continue
                if is_rep:
                    rep_n += 1
                    rep_b += sz
                else:
                    map_n += 1
                    map_b += sz
    verb = "removed" if apply else "would remove (DRY; --apply deletes)"
    print(f"probeprune: {verb} {rep_n} probe replays ({rep_b / 2**30:.1f} GB) and {map_n} old-base probe maps ({map_b / 2**30:.1f} GB);"
          f" {skipped} probes in use skipped; kept bases: {', '.join(sorted(keep_base))}")


if __name__ == "__main__":
    main()
