#!/usr/bin/env python3
"""puppet: replay one side of a real game exactly, so our side of it can be re-run and traced. Tool builder, 2 Nov (from b835's mkpup.py).

usage: python3 -I tools/lab/puppet.py GAME [--us A|B] [--bot NAME] [--dir DIR] [--diag DIAGBOT]
  GAME  a match id (its first 8+ characters are enough; fetched through platlock if not on disk) or a .repl26a path.
  --us  our side. Default: the live set's record. Required for a bare replay file.
  --bot the bot to run against the puppet. Default: the version that was ACTIVE on the platform when the match was created (7 Nov:
        `submissions list` activation times; a submit takes minutes to go live, so games right after a ship played the previous
        version, b1462's r4 divergence), else the live set's name (rk_vNNN / unr_vNNN); a disagreement is printed. Give another bot to
        test one change on this exact game.
  --diag DIAGBOT (7 Nov; fuel replay 9 Nov): also play a diag copy of the bot on the same puppet and print its records. Make it with
        `sh tools/lab/newbot.sh BOT nova_dg_NAME`, copy tools/lab/dglog.h into its src/, and add DGP(tag, a, b, c, d) lines (integers,
        any turn, no window needed). Both games play locally on cxe (one game each, nice, own systemd unit): first the UNCHANGED bot with
        CXE_FUEL_REC (every fuel_remaining() value and every fuel cut-off of each turn), then the diag copy with CXE_FUEL_PLAY, which
        feeds it those readings and cuts, so code changes (instruction counts) no longer move its play. The report gives the first
        round each game differs from the real one, and the fuel-play mismatch count (0 = the diag copy made the same host calls).
        Records: DIR/diag_records.txt ("DP tag round champion a b c d" from DGP; "DG tag round a b c d" from DGLOG); the diag game:
        DIR/diag.repl26a. DGP costs no counted host call; DGLOG's round query is one, so in a turn cut for fuel it can move the cut.
Builds a bot that repeats the foe's recorded picks and actions round by round, rebuilds the map from the replay, plays one release game on Condor (cqbatch --fast), and
compares every body's position, HP, gems, gold and cooldowns with the real game. Prints the first round each team differs. Files: DIR (default /data/USER/puppet/ID):
  out.repl26a is the re-played game, for replay.py.

Limits:
- Our bot's source must be the one that played, or the game diverges for that reason. Old versions were pruned on 2 Nov, so this suits recent games; a missing bot stops here.
- It is exact only until the first change. The foe then keeps playing fixed actions at positions that no longer fit, so it tests one decision, and what follows that decision is not
  what the real foe would have done. Read the first rounds after the divergence only.
- Release builds only. A debug build diverges at once. --diag plays a RELEASE diag copy with dglog.h records. Before 9 Nov any code
  change diverged early on v650/v651 (01a1c085: r3), as the bot reads fuel_remaining(); the fuel replay (cxe CXE_FUEL_REC/PLAY)
  removes that. The diag copy must still play the same: a hook that changes a decision, or a host call it adds, shows as a divergence.
- A foe with two bodies of one champion type can't be told apart: this stops rather than guess.
- A consumable the decoder books with no item ('s', [], [], 10) is inferred from the body's next crystal/lock use (b1235, 5 Nov); one with no later use is bought when the body's consumable count rises by its next turn (11 Nov, 01a1cac3), else it stays unbought (its
  gold then runs a little high). Blocked attempts are replayed so bush tiles get revealed as in the real game (b1235: 01a1ab62 exact r1-861 on cxe, was r222).
  Buys play where the decoder lists them, and an adjacent blocked attempt replays as a move (Combat, 6 Nov: 01a1ae55 exact to r1961, was r17).
- Checked on two games: 17de41f7 (ours matched through r909 of 1198) and b908bb5a (r305, whole game, no difference). Exact replay is a fact to read from the output, never to assume."""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import zipfile

REPO = "/homes/USER/cambc"
sys.path.insert(0, REPO + "/tools/lab")
import replay as R  # noqa: E402

X = "/data/USER/puppet"
LIVE = "/data/USER/st/bq/live.txt"
CLI = "/data/USER/cambc500/bin/cambc500"
REPL2MAP = "/data/USER/st/b746/py/repl2map.py"
CMP = ("x", "y", "hp", "gems", "gold", "cd0", "cd1", "alive")

MAIN = r'''// Puppet of one side of a real game (tools/lab/puppet.py). A test opponent: never submit.
#include <cambc.h>
#include "tab.h"
using namespace cambc;
static int body_index()
{
	const auto t = self().champion_name();
@BODIES@
	return -1;
}
static void act(const int* a)
{
	const vec2 p{ a[3], a[4] };
	std::int32_t ok = 0;
	switch (a[2])
	{
	case 1: self().move_absolute(p); break;
	case 2:
	{
		std::uint32_t h = 0;
		if (a[5] == 2) { detail::sdk_camp_at(p.x, p.y, &h); detail::sdk_attack(2, h); }
		else if (a[5] == 6) // an altar-lock hit (b1243, 5 Nov: 01a1abee's r585-587 lock clears were dropped, so the foe's 965 tribute never started)
		{
			detail::altar_lock_info li{};
			if (detail::sdk_altar_lock(p.x, p.y, detail::absolute_team(team::enemy), &li) == 0) detail::sdk_attack(6, li.handle);
		}
		else { detail::sdk_champion_at(p.x, p.y, &h); detail::sdk_attack(1, h); }
		break;
	}
	case 3:
	{
		std::uint32_t h = 0;
		if (a[5] == 2) { detail::sdk_camp_at(p.x, p.y, &h); detail::sdk_cast(a[6], 2, h, -1, -1, &ok); }
		else if (a[5] == 1) { detail::sdk_champion_at(p.x, p.y, &h); detail::sdk_cast(a[6], 1, h, -1, -1, &ok); }
		else if (a[7] == 7) detail::sdk_cast(a[6], 0, 0, -1, -1, &ok);
		else detail::sdk_cast(a[6], 0, 0, p.x, p.y, &ok);
		break;
	}
	case 4: self().recall(); break;
	case 5: try { self().cancel_recall(); } catch (...) { self().cancel_submit_gems(); } break;
	case 6: self().submit_gems(p); break;
	case 7: self().place_ward(p); break;
	case 8: self().set_priority(a[3]); break;
	case 9: detail::sdk_buy_item(a[3], a[4]); break;
	case 10: detail::sdk_buy_consumable(a[3]); break;
	case 11: detail::sdk_use_consumable(0, p.x, p.y, &ok); break;
	case 12: detail::sdk_use_consumable(2, p.x, p.y, &ok); break; 
	case 15: try { self().move_absolute(p); } catch (...) {} break; // b1739 (8 Nov, 01a1bd3f r372): an adjacent blocked attempt on a tile a body holds at that turn: the move fails and reveals it, as in the real game (the attack after it needs the reveal)
	case 14: try { self().place_ward(p); } catch (...) {} break; // a ward attempt on a mate's ward tile: a move there would land (Combat, 8 Nov, 01a1bc05 r23)
	case 13: // a blocked attempt (b1235): a crystal at range >= 3, else a ward, else a move, so the engine reveals the tile again
	{
		const vec2 me = self().position();
		const int dx = me.x > p.x ? me.x - p.x : p.x - me.x, dy = me.y > p.y ? me.y - p.y : p.y - me.y, d = dx > dy ? dx : dy;
		if (d >= 3) { detail::sdk_use_consumable(0, p.x, p.y, &ok); break; }
		if (d <= 2) break; // an adjacent blocked attempt does nothing: a move or a ward there can land (8 Nov, 11 games with such attempts: never worse, 01a1bb07 r83 -> r925); 9 Nov (Combat, 01a1c165 00swirl v SBG): d2 too: replayed as a ward it LANDED (moved Vesper's ward r201, broke exactness r205); skipped: exact through r727
		bool thrown = false;
		try { self().place_ward(p); } catch (...) { thrown = true; }
		if (thrown) { try { self().move_absolute(p); } catch (...) {} }
		break;
	}
	}
}
int main()
{
	static const int PICKS[] = { @PICKS@ };
	while (true)
	{
		try
		{
			if (is_draft())
			{
				const auto n = draft::current_draft(team::ally).size();
				if (n < sizeof(PICKS) / sizeof(PICKS[0])) detail::sdk_draft_champion(PICKS[n]);
			}
			else
			{
				const int r = static_cast<int>(round_number());
				const int b = body_index();
				if (r >= 0 && r < NR)
					for (int i = IDX[r]; i < IDX[r + 1]; ++i)
						if (TAB[i][1] == b)
						{
							try { act(TAB[i]); } catch (...) {}
						}
			}
		}
		catch (...) {}
		end_turn();
	}
}
'''


LOG_LIMIT = "8000000"  # team stdout kept in the replay; 3 Nov (b961): "0" now drops it, so a diag copy recorded nothing. A release bot prints nothing, so no cost

def die(msg):
    sys.exit(f"puppet: {msg}")


def full_id(short):
    """The full match id of our match whose id starts with SHORT (dashes ignored), from the platform's list of our recent matches."""
    want = re.sub(r"[^0-9a-f]", "", short.lower())
    ms, cur, hits = [], None, []
    for _ in range(10):  # pages of 100 (the CLI's limit), newest first: our last 1,000 matches
        r = subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", CLI, "matches", "list", "--team", "me", "--limit", "100", "--json"]
                           + (["--cursor", cur] if cur else []), capture_output=True, text=True)
        try:
            j = json.loads(r.stdout)
        except ValueError:
            die(f"cannot look up {short}: {(r.stdout + r.stderr).strip()[-200:]}")
        ms += j.get("matches", [])
        hits = sorted({m["matchId"] for m in ms if m.get("matchId", "").replace("-", "").startswith(want)})
        cur = j.get("nextCursor")
        if hits or not cur:
            break
    if len(hits) != 1:
        maps = {m["matchId"]: m.get("map", "?") for m in ms}
        die(f"{short}: {'no match' if not hits else str(len(hits)) + ' matches'} among our last {len(ms)} matches; give the full id"
            + "".join(f"\n  {h}  {maps[h]}" for h in hits))
    print(f"puppet: {short} = {hits[0]}", flush=True)
    return hits[0]


def fetch(gid, d):
    """A replay file for GAME: a path, one on disk, or a download through platlock."""
    if os.path.exists(gid):
        return gid
    hit = glob.glob(f"/data/USER/plat/*/x_{gid}*/replay.repl26a")
    ids = sorted({os.path.basename(os.path.dirname(h))[2:] for h in hit})
    if len(ids) > 1:  # 9 Nov (b1749): a short prefix shared by several games replayed the first one silently
        die(f"{gid} matches {len(ids)} games: " + ", ".join(ids[:8]) + (" ..." if len(ids) > 8 else "") + "; give the full match id")
    if hit:
        return sorted(hit)[0]  # one game (copies of it in several sets are the same replay)
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", gid):
        gid = full_id(gid)  # 6 Nov: a short id failed ('expected a UUID') unless the game was already on disk
    zp = f"{d}/r.zip"
    if os.path.exists(f"{d}/game.repl26a"):  # a re-run reuses the replay it fetched
        return f"{d}/game.repl26a"
    if os.path.exists(zp) and not zipfile.is_zipfile(zp):
        os.remove(zp)  # a partial download
    if not os.path.exists(zp):
        r = subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", CLI, "matches", "download", gid, "-o", zp], capture_output=True, text=True, cwd=d)
        if r.returncode or not zipfile.is_zipfile(zp):
            die(f"cannot fetch {gid}: {(r.stdout + r.stderr).strip()[-200:]}")
    with zipfile.ZipFile(zp) as z:
        name = next((n for n in z.namelist() if n.endswith(".repl26a")), None)
        if not name:
            die(f"{zp} holds no replay")
        open(f"{d}/game.repl26a", "wb").write(z.read(name))
    return f"{d}/game.repl26a"


def side_and_version(path):
    """(our side or None, version or None) from the live set a replay sits in."""
    m = re.search(r"/plat/([^/]+)/x_([^/]+)/", os.path.abspath(path))
    if not m:
        return None, None
    side = None
    try:
        for ln in open(f"/data/USER/plat/{m.group(1)}/matches.txt"):
            p = ln.split()
            if len(p) >= 3 and p[0] == m.group(2):
                side = p[2].upper()[0]
    except OSError:
        pass
    v = re.search(r"_(v\d+)", m.group(1))
    return side, v.group(1) if v else None


def bot_of(version):
    for ln in open(LIVE):
        p = ln.split()
        if len(p) >= 2 and p[0] == version:
            return p[1]
    return None


def table(g, foe):
    """The foe's picks, bodies and actions as rows (round, body, kind, x, y, a, b, c), as they were played. b1235 (5 Nov, 01a1ab62:
    exact r1-861 instead of r222): each turn's buys come before its actions; consumable buys the decoder books as ['s', [], [], 10]
    (or a net -1) are inferred from the body's next teleport ('tp', crystal 0) or lock ('l', 2) use; the engine's blocked attempts
    ('b', movement_blocked) are replayed (kind 13: a crystal use at range >= 3, nothing when adjacent, else a ward, else a move) so the tile is revealed as
    in the real game (an attack on a camp in a bush needs that reveal)."""
    ci = g.ci
    bodies = [b for b in sorted(g.team_of) if g.team_of[b] == foe]
    names = [g.bodies[b]["name"] for b in bodies]
    if len(set(names)) != len(names):
        die(f"foe has two bodies of one type ({names}): this tool can't tell them apart")
    uses = {}
    for t in g.turns:
        b = t[ci["c"]]
        if g.team_of[b] != foe:
            continue
        for a in t[-1]:
            if a[0] in ("tp", "l"):
                uses.setdefault(b, []).append((t[ci["r"]], 0 if a[0] == "tp" else 2))
    nxt = {}  # each foe turn -> the same body's next turn (its consumable counts at that turn's start)
    for b, ts in g.by_champ.items():
        for a, c in zip(ts, ts[1:]):
            nxt[id(a)] = c
    rows, skipped, inferred, late = [], 0, 0, 0
    kinds = {"m": 1, "rc": 4, "x": 5, "t": 6, "w": 7, "tp": 11, "l": 12, "b": 13}
    for t in g.turns:
        b = t[ci["c"]]
        if g.team_of[b] != foe:
            continue
        r, i = t[ci["r"]], bodies.index(b)
        buys, acts = [], []
        have = {it for a in t[-1] if a[0] == "s" for it, n in a[2] if n > 0}  # the turn's explicit consumable buys, all 's' entries (01a1cac3 r82: an unbooked buy inferred as the lock bought later that turn, so the crystal never came)
        for a in t[-1]:
            k = a[0]
            if k == "s":
                buys += [(r, i, 9, it, n, 0, 0, 0) for it, n in a[1]]
                buys += [(r, i, 10, it, 0, 0, 0, 0) for it, n in a[2] for _ in range(max(n, 0))]
                res = (a[3] - 30 * sum(n for _, n in a[1]) - 10 * sum(max(n, 0) for _, n in a[2])) // 10  # gold not explained, in consumables
                for ur, typ in uses.get(b, []):
                    if res <= 0:
                        break
                    if ur >= r and typ not in have and t[ci["crystals" if typ == 0 else "locks"]] < 1:  # 11 Nov (Deep tk757, 01a1cb4d r682): a body carrying one cannot buy another (GameRules:114, 322)
                        buys.append((r, i, 10, typ, 0, 0, 0, 0))
                        have.add(typ)
                        res -= 1
                        inferred += 1
                nx = nxt.get(id(t))
                for typ, col in ((0, "crystals"), (2, "locks")):  # no later use (01a1cac3 r560: a crystal bought dead, game over before use): the next turn's count rose
                    if res > 0 and nx is not None and typ not in have and nx[ci[col]] > t[ci[col]]:
                        buys.append((r, i, 10, typ, 0, 0, 0, 0))
                        have.add(typ)
                        res -= 1
                        inferred += 1
            elif k == "a":
                acts.append((r, i, 2, a[3], a[4], a[1], 0, 0))
            elif k == "c":
                acts.append((r, i, 3, a[3], a[4], a[5], a[1], a[2]))
            elif k == "b" and any(g.team_of[o] == foe and q == (a[1], a[2]) for o, q in R.wards_at(g, r).items()) and not any(u[g.ci["alive"]] and (x, y) == (a[1], a[2]) for o, (x, y, u) in g.positions_before(t).items()):
                acts.append((r, i, 14, a[1], a[2], 0, 0, 0))  # blocked on a mate's ward tile with nobody on it: it was a ward attempt, not a move
                # b1739 (8 Nov, 01a1bd3f r372): occupancy at this turn's start (positions_before), not the round's: a foe that moved onto the tile earlier in the round made it a real blocked move
            elif k == "b" and max(abs(a[1] - t[2]), abs(a[2] - t[3])) <= 1 and any(o != b and u[g.ci["alive"]] and (x, y) == (a[1], a[2]) for o, (x, y, u) in g.positions_before(t).items()):
                acts.append((r, i, 15, a[1], a[2], 0, 0, 0))  # adjacent, and a body stands there at this turn: replay the move so the engine reveals it
            elif k == "p":
                acts.append((r, i, 8, a[1], 0, 0, 0, 0))
            elif k in ("rc", "x"):
                acts.append((r, i, kinds[k], 0, 0, 0, 0, 0))
            elif k in kinds:
                acts.append((r, i, kinds[k], a[1], a[2], 0, 0, 0))
            else:
                skipped += 1
        if buys:  # buys play at the decoder's position (Combat, 6 Nov): a buy after a recall cancel, a shop move or a paying kill fails if played first
            seq = [q[0] for q in t[-1]]
            j = sum(1 for q in seq[:seq.index("s")] if q in kinds or q in ("a", "c", "p"))
            late += j > 0
            acts = acts[:j] + buys + acts[j:]
        rows += acts
    if late:
        print(f"puppet: {late} foe turns buy after an action, played in the decoder's order", flush=True)
    if inferred:
        print(f"puppet: {inferred} consumable buys inferred from later crystal/lock uses", flush=True)
    return names, rows, skipped


def write_bot(d, names, picks, rows):
    os.makedirs(d + "/src", exist_ok=True)
    nr = max((x[0] for x in rows), default=0) + 2
    idx = [0] * (nr + 1)
    for r in range(nr, -1, -1):
        idx[r] = next((i for i, x in enumerate(rows) if x[0] >= r), len(rows))
    with open(d + "/src/tab.h", "w") as f:
        f.write(f"static const int TAB[{max(1, len(rows))}][8]={{\n")
        f.writelines("{" + ",".join(map(str, x)) + "},\n" for x in rows)
        f.write(("" if rows else "{0,0,0,0,0,0,0,0}\n") + f"}};\nstatic const int NR={nr};\nstatic const int IDX[]={{{','.join(map(str, idx))}}};\n")
    bodies = "\n".join(f"\tif (t == champion_type::{n}) return {i};" for i, n in enumerate(names))
    open(d + "/src/main.cpp", "w").write(MAIN.replace("@BODIES@", bodies).replace("@PICKS@", ", ".join(map(str, picks))))


def compare(real, redo):
    """First round each team differs, and on which body and column."""
    ci = real.ci
    cols = [c for c in CMP if c in ci]
    a = {(t[0], t[1]): t for t in real.turns}
    first = {}
    last = 0
    for t in redo.turns:
        k = (t[0], t[1])
        o = a.get(k)
        if o is None:
            continue
        last = max(last, t[0])
        team = real.team_of[t[1]]
        if team in first:
            continue
        bad = [c for c in cols if t[ci[c]] != o[ci[c]]]
        if bad:
            first[team] = (t[0], real.who(t[1]), {c: (o[ci[c]], t[ci[c]]) for c in bad})
    return first, last


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("game")
    ap.add_argument("--us", choices=("A", "B"))
    ap.add_argument("--bot")
    ap.add_argument("--dir")
    ap.add_argument("--diag")
    a = ap.parse_args()
    gid = re.sub(r"[^A-Za-z0-9]", "", os.path.basename(a.game).split(".")[0])[:8] if not os.path.exists(a.game) else re.sub(r"[^A-Za-z0-9]", "", os.path.basename(os.path.dirname(os.path.abspath(a.game))))[-8:]
    # 10 Nov (Deep: games of one match group share their first 8 characters, e.g. 01a1c3b9-..., so parallel puppets wrote one dir): the
    # full match id names the dir when there is one
    _mid = match_id(a.game, a.game)
    if _mid:
        gid = _mid.replace("-", "")
    d = os.path.abspath(a.dir or f"{X}/{gid}")
    os.makedirs(d, exist_ok=True)
    path = fetch(a.game, d)
    side, version = side_and_version(path)
    if not a.bot:
        tv = timed_version(match_id(a.game, path))
        if tv and version and tv != version:
            print(f"puppet: the set says {version}, but {tv} was active when the match was created: using {tv}", flush=True)
        version = tv or version
    us = a.us or side
    if not us:
        die("our side is unknown: give --us A or --us B")
    bot = a.bot or (bot_of(version) if version else None)
    if not bot:
        die(f"which bot played is unknown (version {version}): give --bot NAME")
    if not os.path.isdir(f"{REPO}/bots/{bot}/src"):
        die(f"bots/{bot} is gone (old versions were pruned): this game can't be re-played exactly")
    real = R.load(path, us)
    foe = 1 if us == "A" else 0
    names, rows, skipped = table(real, foe)
    picks = real.d["draft"][foe]
    pup = f"{d}/nova_pup_{gid}"
    write_bot(pup, names, picks, rows)
    mp = f"{d}/{gid}.map26a"
    r = subprocess.run(["python3", "-I", REPL2MAP, path, mp], capture_output=True, text=True)
    if r.returncode:
        die(f"map rebuild failed: {(r.stdout + r.stderr).strip()[-200:]}")
    b = f"{REPO}/bots/{bot}"
    x, y = (b, pup) if us == "A" else (pup, b)
    open(f"{d}/man.txt", "w").write(f"{x} {y} {mp} out.repl26a\n")
    print(f"puppet: {len(rows)} foe actions ({skipped} not replayable), foe {names}, picks {picks}; {bot} as team {us}; playing on Condor", flush=True)
    r = subprocess.run(["nice", "-n", "10", "python3", "-I", f"{REPO}/tools/lab/cqbatch.py", "man.txt", "--fast", "--release", "--log-limit", LOG_LIMIT, "--per-job", "1", "--cpus", "4", "--wait-max", "1500"],
                       cwd=d, capture_output=True, text=True, env=dict(os.environ, PATH="/usr/local/condor/release/bin:" + os.environ.get("PATH", "")))
    if not os.path.exists(f"{d}/out.repl26a"):
        die(f"the game did not come back: {(r.stdout + r.stderr).strip()[-300:]}")
    redo = R.load(f"{d}/out.repl26a", us)
    first, last = compare(real, redo)
    rl, ol = real.last_round, redo.last_round
    print(f"real game ended r{rl}; re-play ended r{ol}; compared through r{last}")
    for team, name in ((1 - foe, "ours"), (foe, "foe")):
        if team in first:
            rn, who, what = first[team]
            print(f"  {name}: first differs at r{rn}, {who}: " + ", ".join(f"{k} real {v[0]} re-play {v[1]}" for k, v in list(what.items())[:4]))
        else:
            print(f"  {name}: no difference")
    print(f"re-played game: {d}/out.repl26a  (read with replay.py, --us {us})")
    if a.diag:
        diag(a.diag, pup, mp, d, us, real, bot)
    return 0


def match_id(game, path):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", os.path.abspath(path) + " " + game)
    return m.group(1) if m else None


def timed_version(mid):
    """vNNN that was active on the platform when match MID was created: each version is active from its predecessor's statusAt
    (when it went inactive) to its own (submissions list; cached in X/submissions.json, refreshed when the match is newer)."""
    if not mid:
        return None
    try:
        t = json.loads(subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", CLI, "matches", "show", mid, "--json"], capture_output=True,
                                      text=True, timeout=120).stdout)["matches"][0]["createdAt"]
    except (ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return None
    cache = f"{X}/submissions.json"
    try:
        subs = json.load(open(cache))
    except (OSError, ValueError):
        subs = {}
    # 9 Nov (Deep, owner replay 01a1c27e re-played v652 instead of v674): only 'inactive' is final. A cached 'active'/'queued' entry is a
    # snapshot that later pages never overwrote, and the scan below returned the first stale 'active' one. Drop them; the newest page
    # (fetched whenever no cached deactivation is after the match) supplies the current active version.
    subs = {k: x for k, x in subs.items() if x.get("status") == "inactive"}
    import time as _time
    recent = _time.time() - _time.mktime(_time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")) + _time.timezone < 86400  # 12 Nov: a newer upload may be active
    if recent or not subs or max(x["statusAt"] for x in subs.values()) < t or min(x["createdAt"] for x in subs.values()) > t:
        before = None
        for _ in range(30):
            try:
                j = json.loads(subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", CLI, "submissions", "list", "--json"]
                                              + (["--before", str(before)] if before else []), capture_output=True, text=True, timeout=120).stdout)
            except (ValueError, subprocess.SubprocessError):
                break
            for x in j.get("submissions", []):
                subs[str(x["version"])] = dict(status=x["status"], createdAt=x["createdAt"], statusAt=x.get("statusAt", ""))
            vs = [x["version"] for x in j.get("submissions", [])]
            if not j.get("more") or not vs or min(x["createdAt"] for x in subs.values()) < t:
                break
            before = min(vs)
        os.makedirs(X, exist_ok=True)
        json.dump(subs, open(cache, "w"))
    if sum(x["status"] == "active" for x in subs.values()) > 1:
        return None  # two versions listed active: unsure, the caller falls back to the set's name or refuses
    # 12 Nov (Aggression, 01a1cfc5 at 12:40:02Z: v824 uploaded 12:35, v823's statusAt 12:41:31): the platform marks the old version inactive
    # minutes after the new one starts playing ('follow newest ready'). The newest version uploaded >= PUPPET_READY_S (120 s) before the
    # match was compiled and playing: prefer it
    ready = int(os.environ.get("PUPPET_READY_S", "120"))
    try:
        import datetime as _dt
        tt = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        up = [int(v) for v, x in subs.items() if x.get("createdAt") and
              (tt - _dt.datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00"))).total_seconds() >= ready]
        newest = max(up) if up else None
    except (ValueError, TypeError):
        newest = None
    for v in sorted(subs, key=int):
        x = subs[v]
        if x["status"] == "active" or (x["status"] == "inactive" and x["statusAt"] > t):
            prev = subs.get(str(int(v) - 1))
            if prev and prev["statusAt"] > t:
                continue  # its predecessor was still active then
            if newest and newest > int(v):
                return f"v{newest}"
            return f"v{v}"
    return f"v{newest}" if newest else None


def fuel_host(cxebuild):
    """A cxe host with the fuel record/replay (CXE_FUEL_REC / CXE_FUEL_PLAY): the default one, else a CXE_DEV build of the working copy."""
    exe = cxebuild.build_host()
    if b"CXE_FUEL_PLAY" in open(exe, "rb").read():
        return exe
    old = os.environ.get("CXE_DEV")
    os.environ["CXE_DEV"] = "1"
    try:
        exe = cxebuild.build_host()
    finally:
        if old is None:
            os.environ.pop("CXE_DEV", None)
        else:
            os.environ["CXE_DEV"] = old
    return exe if b"CXE_FUEL_PLAY" in open(exe, "rb").read() else None


def cxe_local(exe, a, b, mp, out, env, tag):
    """One local cxe game in its own systemd unit (CLAUDE.md: heavy local jobs capped); stderr -> OUT.err."""
    unit = f"nova-puppet-{os.getpid()}-{tag}"
    # 11 Nov (Path Finding: CXE_MAX_PAGES / CXE_PAGES_LOG never reached the local cxe games): pass the caller's CXE_* tuning through
    env = dict({k: v for k, v in os.environ.items() if k in ("CXE_MAX_PAGES", "CXE_PAGES_LOG")}, **env)
    sets = [f"--setenv={k}={v}" for k, v in env.items()]
    cmd = ["systemd-run", "--user", "--unit", unit, "-p", "MemoryMax=8G", "--wait", "--collect", "-q", f"--working-directory={os.path.dirname(out)}"] + sets \
        + ["nice", "-n", "10", "sh", "-c", 'exec "$0" "$1" "$2" "$3" "$4" > "$4.out" 2> "$4.err"', exe, a, b, mp, out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    return r.returncode == 0 and os.path.exists(out + ".repl26a")


def diag(dbot, pup, mp, d, us, real, bot=None):
    """--diag: the unchanged BOT v the puppet with the fuel recorded, then DBOT v the puppet replaying that fuel (local cxe); first
    divergence of each from the real game, and the records. Without BOT (callers before 9 Nov): the old way, no fuel replay (pilots)."""
    sys.path.insert(0, f"{REPO}/tools/cxe")
    import cxebuild
    if bot is None:
        print("puppet --diag: no base bot given: the diag copy plays WITHOUT the fuel replay (pass bot=BASE to diag())", flush=True)
        return _diag_pilots(dbot, pup, mp, d, us, real)
    if not os.path.isdir(f"{REPO}/bots/{dbot}/src"):
        die(f"--diag: bots/{dbot} has no src/")
    print(f"puppet --diag: building {dbot}, {bot} and the puppet for cxe", flush=True)
    sd, sb, sp = cxebuild.build_bot(dbot), cxebuild.build_bot(bot), cxebuild.build_bot(pup)
    exe = fuel_host(cxebuild)
    if not exe:
        die("--diag: no cxe host with the fuel replay (CXE_FUEL_PLAY) could be built")
    ours = 0 if us == "A" else 1
    rec = f"{d}/fuel.rec"
    base = f"{d}/diagbase"
    for f in glob.glob(f"{d}/diag.*") + glob.glob(f"{base}.*") + [rec, f"{d}/diag_probe.tsv"]:
        if os.path.exists(f):
            os.remove(f)
    x, y = (sb, sp) if us == "A" else (sp, sb)
    if not cxe_local(exe, x, y, mp, base, {"CXE_FUEL_REC": rec}, "rec"):
        die(f"--diag: the fuel-record game ({bot}) did not play: {open(base + '.err').read()[-300:] if os.path.exists(base + '.err') else ''}")
    fb, _ = compare(real, R.load(f"{base}.repl26a", us))
    out = f"{d}/diag"
    x, y = (sd, sp) if us == "A" else (sp, sd)
    if not cxe_local(exe, x, y, mp, out, {"CXE_FUEL_PLAY": rec, "CXE_STDOUT": "1", "CXE_PROBE": f"{d}/diag_probe.tsv"}, "play"):
        die(f"--diag: the diag game did not play: {open(out + '.err').read()[-300:] if os.path.exists(out + '.err') else ''}")
    redo = R.load(f"{out}.repl26a", us)
    first, last = compare(real, redo)
    lines = [ln for ln in open(f"{out}.team-{us.lower()}.stdout", errors="replace") if ln.startswith("DG ")] if os.path.exists(f"{out}.team-{us.lower()}.stdout") else []
    probe = []
    if os.path.exists(f"{d}/diag_probe.tsv"):  # "round team champion kind a b c v" -> "DP tag round champion a b c d"
        for ln in open(f"{d}/diag_probe.tsv"):
            v = ln.split()
            if len(v) == 8 and v[1] == str(ours):
                probe.append(f"DP {v[3]} {v[0]} {v[2]} {v[4]} {v[5]} {v[6]} {v[7]}\n")
    open(f"{d}/diag_records.txt", "w").write("".join(probe + lines))
    err = open(out + ".err", errors="replace").read().splitlines()
    summ = next((ln[5:] for ln in err if ln.startswith("cxe: fuel-play:")), "fuel-play: no summary")
    mism = [ln[5:] for ln in err if ln.startswith("cxe: fuel-play mismatch")]
    fr = first.get(ours, (None,))[0]
    fo = first.get(1 - ours, (None,))[0]
    rb = fb.get(ours, (None,))[0]
    print(f"fuel record game ({bot}, unchanged): ours first differs {'at r' + str(rb) if rb else 'never'}" + ("  (the record itself is not exact from there)" if rb else ""))
    print(f"diag game ({dbot}, fuel replayed): ours first differs {'at r' + str(fr) if fr else 'never'} (foe {'r' + str(fo) if fo else 'never'}), compared through r{last}; "
          f"{len(probe)} DP + {len(lines)} DG records -> {d}/diag_records.txt" + (f"; records from r{fr} on are past the exact part" if fr else ""))
    print(f"  {summ}" + (f"; first: {mism[0]}" if mism else ""))


def _diag_pilots(dbot, pup, mp, d, us, real):
    """The pre-9-Nov --diag: DBOT v the puppet on cxe (pilots), team stdout kept, no fuel replay."""
    import cxebuild
    import pilotcxe
    if not os.path.isdir(f"{REPO}/bots/{dbot}/src"):
        die(f"--diag: bots/{dbot} has no src/")
    sd, sp = cxebuild.build_bot(dbot), cxebuild.build_bot(pup)
    x, y = (sd, sp) if us == "A" else (sp, sd)
    out = f"{d}/diag"
    if not pilotcxe.run([(x, y, mp, out, "")], say=lambda m: None, env={"CXE_STDOUT": "1"}):
        die("--diag: the pilots did not play the diag game")
    redo = R.load(f"{out}.repl26a", us)
    first, last = compare(real, redo)
    ours = 0 if us == "A" else 1
    lines = [ln for ln in open(f"{out}.team-{us.lower()}.stdout", errors="replace") if ln.startswith("DG ")] if os.path.exists(f"{out}.team-{us.lower()}.stdout") else []
    open(f"{d}/diag_records.txt", "w").write("".join(lines))
    fr = first.get(ours, (None,))[0]
    fo = first.get(1 - ours, (None,))[0]
    print(f"diag game: ours first differs {'at r' + str(fr) if fr else 'never'} (foe {'r' + str(fo) if fo else 'never'}), compared through r{last}; "
          f"{len(lines)} DG records -> {d}/diag_records.txt" + (f"; records from r{fr} on are past the exact part" if fr else ""))

if __name__ == "__main__":
    sys.exit(main())
