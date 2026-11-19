#!/usr/bin/env python3
"""rmap: the website's fogged view as text, for any champion or team at any round (Tool builder 2, 4 Nov; owner: 'the replay like the
visualiser where we can see each champion's vision').

usage: python3 -I tools/lab/rmap.py GAME --us A|B --round R[-R2] [--who us|them|LABEL] [--around LABEL RAD | --box X0 Y0 X1 Y1] [--truth]
  GAME as replay.py takes it. --who: a team ('us' default, 'them'): the union of its living champions' views, each taken at that
  champion's own turn start in round R (what the team could have known); or one champion by label (1-6 for team A, K L N P R S for
  team B): exactly what that champion saw at its turn start in round R. --round R-R2 prints one frame per round (at most 30).
Vision tiles come from the engine itself (tools/lab/rvision.js --tiles: Game_Visualiser_GetVisionBuffer per champion, wards included),
cached in /data/zw4424/rvision_cache/tiles_<sha>_<r0>_<r1>.json.gz.
Drawing (replay.py show's characters): # wall, o hole, " bush, @ altar, _ spawn, w e g $ M G camps alive, , dead camp, + / x wards
of team A / B, digits team A, K L N P R S team B. In FOG (tiles the viewer did not see): ground is blank, terrain stays (it is
static), a camp shows ? (its state unknown), enemy champions and wards are hidden; the viewer's own team is always drawn.
--truth: hidden enemy champions are drawn in fog as * (so you can see what was there). Under the map: each enemy champion,
seen or hidden, with its tile and Chebyshev distance to the nearest viewing champion."""
import gzip
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay as RP  # noqa: E402

CACHE = os.path.exists("/data/zw4424/st/bq/live.txt") and '/data/zw4424/rvision_cache' or os.path.join(os.environ.get("_CONDOR_SCRATCH_DIR") or "/tmp", 'zw4424-rvision_cache')  # 10 Nov: /data only on the main machine (live.txt there); on Condor nodes the job's scratch dir, else /tmp (a lab user found our caches on their desktop's /data)


def tiles(spec, r0, r1):
    raw = RP.locate(spec)[0]
    if raw is None:
        sys.exit(f"rmap: no replay bytes for {spec}")
    h = hashlib.sha1(raw).hexdigest()
    out = f"{CACHE}/tiles_{h}_{r0}_{r1}.json.gz"
    if not os.path.exists(out):
        os.makedirs(CACHE, exist_ok=True)
        tmp = f"{CACHE}/.{h}.{os.getpid()}.repl26a"
        open(tmp, "wb").write(raw)
        try:
            try:  # 10 Nov: the shared decode timeout (REPLAY_DECODE_TIMEOUT, default 120 s)
                r = subprocess.run(["nice", "-n", "19", "node", os.path.join(HERE, "rvision.js"), tmp, out, "--tiles", str(r0), str(r1)],
                                   capture_output=True, text=True, timeout=RP.DECODE_TIMEOUT)
            except subprocess.TimeoutExpired:
                RP._note_timeout(spec, "rvision.js --tiles")
                raise RP.DecodeTimeout(f"rvision.js --tiles on {spec} ran over {RP.DECODE_TIMEOUT:.0f} s (REPLAY_DECODE_TIMEOUT)") from None
            if r.returncode:
                sys.exit(f"rvision.js failed: {(r.stdout + r.stderr).strip()[-400:]}")
        finally:
            os.remove(tmp)
    return json.load(gzip.open(out))


def bits(hexs, W, H):
    v = int(hexs, 16) if hexs else 0
    n = len(hexs) * 4
    return {(i % W, i // W) for i in range(W * H) if (v >> (n - 1 - i)) & 1}


def frame(g, v, r, who, box, around, truth):
    W, H = g.W, g.H
    rows = [x for x in v["tiles"] if x[0] == r]
    if not rows:
        print(f"round {r}: no turn starts recorded (game over or outside the tiles range)")
        return
    lab = lambda b: g.label.get(b, str(b))  # noqa: E731
    inv = {lab(b): b for b in g.bodies}
    if who in ("us", "them"):
        team = g.us if who == "us" else 1 - g.us
        viewers = [b for b in g.bodies if g.team_of[b] == team]
    else:
        if who not in inv:
            sys.exit(f"rmap: no body {who!r} (labels: {' '.join(sorted(inv))})")
        viewers = [inv[who]]
        team = g.team_of[inv[who]]
    seen = set()
    used = []
    for b in viewers:
        own = next((x for x in rows if x[1] == b and str(b) in x[2]), None) or next((x for x in rows if str(b) in x[2]), None)
        if own:
            seen |= bits(own[2][str(b)], W, H)
            used.append(lab(b))
    pos = g.positions_at(r)
    hp, _ = g.camp_state_at(r)
    grid = [list(row) for row in g.rows]
    for y in range(H):
        for x in range(W):
            ch = {"A": "@", "a": "_", "b": "_"}.get(grid[y][x], grid[y][x])
            if (x, y) not in seen and ch in ".":
                ch = " "
            grid[y][x] = ch
    for c in g.camps.values():
        grid[c["y"]][c["x"]] = (RP.CAMP_CH[c["type"]] if hp.get(c["id"], 0) > 0 else ",") if (c["x"], c["y"]) in seen else "?"
    for c, (x, y) in RP.wards_at(g, r).items():
        if 0 <= x < W and 0 <= y < H and (g.team_of[c] == team or (x, y) in seen):
            grid[y][x] = "+" if g.team_of[c] == 0 else "x"
    alive = {c: (t[2], t[3]) for c, t in pos.items() if t[g.ci["alive"]] and 0 <= t[2] < W and 0 <= t[3] < H}
    for c, (x, y) in alive.items():
        if g.team_of[c] == team or (x, y) in seen:
            grid[y][x] = lab(c)
        elif truth:
            grid[y][x] = "*"
    x0, y0, x1, y1 = 0, 0, W - 1, H - 1
    if box:
        x0, y0, x1, y1 = box
    elif around:
        c = inv.get(around[0])
        if c in alive:
            x0, y0 = alive[c][0] - around[1], alive[c][1] - around[1]
            x1, y1 = alive[c][0] + around[1], alive[c][1] + around[1]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W - 1, x1), min(H - 1, y1)
    print(f"round {r}: view of {who} ({', '.join(used) or 'nobody alive'}), team {'AB'[team]}; {len(seen)} of {W * H} tiles in view; "
          f"x {x0}-{x1}, y {y0}-{y1}")
    print("    " + "".join(str((x // 10) % 10) if x % 10 == 0 else " " for x in range(x0, x1 + 1)))
    print("    " + "".join(str(x % 10) for x in range(x0, x1 + 1)))
    for y in range(y0, y1 + 1):
        print(f"{y:3d} " + "".join(grid[y][x0:x1 + 1]))
    vp = [alive[b] for b in viewers if b in alive]
    out = []
    for c, (x, y) in sorted(alive.items()):
        if g.team_of[c] == team:
            continue
        d = min((max(abs(x - a), abs(y - b)) for a, b in vp), default=-1)
        out.append(f"{lab(c)}:{g.bodies[c]['name']} ({x},{y}) d{d} {'SEEN' if (x, y) in seen else 'hidden'}")
    print("  enemies: " + ("; ".join(out) or "none alive"))


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-") or "--round" not in a or "--us" not in a:
        sys.exit(__doc__)
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    rr = opt("--round").split("-")
    r0, r1 = int(rr[0]), int(rr[-1])
    if r1 - r0 >= 30:
        sys.exit("rmap: at most 30 rounds per call")
    g = RP.load(a[0], us=opt("--us"))
    v = tiles(a[0], r0, r1)
    box = [int(x) for x in a[a.index("--box") + 1:a.index("--box") + 5]] if "--box" in a else None
    around = (opt("--around"), int(a[a.index("--around") + 2])) if "--around" in a else None
    for r in range(r0, r1 + 1):
        frame(g, v, r, opt("--who", "us"), box, around, "--truth" in a)


if __name__ == "__main__":
    main()
