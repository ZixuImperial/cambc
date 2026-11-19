"""MCP server exposing the Cambridge Battlecode `cambc` CLI to Claude.

Run with:  mcp/.venv/bin/python mcp/server.py   (stdio transport)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

PROJECT = Path(os.environ.get("CAMBC_PROJECT", Path(__file__).resolve().parent.parent))
CAMBC = os.environ.get("CAMBC_BIN", str(PROJECT / ".venv" / "bin" / "cambc"))
MAX_OUTPUT = 20_000  # chars of stdout/stderr returned to the model
STATS_DIR = PROJECT / "replays" / "stats"
# small sections of a statistics file returned inline; the rest is fetched with match_stats
SUMMARY_KEYS = ("match", "teams", "roster", "diagnostics", "champions")
PROGRESS = re.compile(r"^(drafting|running): round \d+/\d+\n", re.M)

server = MCPServer(
    name="cambc",
    instructions=(
        "Tools for the Cambridge Battlecode project at "
        f"{PROJECT}. Bots live in bots/<name>/, maps in maps/*.map26a. "
        "Use run_match to test bots locally, ladder/list_matches for the online platform. "
        "submit_bot uploads to the team's live submissions - only call it when the user asks."
    ),
)


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    half = MAX_OUTPUT // 2
    return f"{text[:half]}\n... [{len(text) - MAX_OUTPUT} chars truncated] ...\n{text[-half:]}"


async def _cambc(*args: str, timeout: float = 600, raw: bool = False) -> str:
    proc = await asyncio.create_subprocess_exec(
        CAMBC,
        *args,
        cwd=PROJECT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError(f"cambc {' '.join(args)} timed out after {timeout}s")
    result = out.decode(errors="replace")
    if raw and proc.returncode == 0:
        return result  # stdout only, unclipped: callers parse it (--json) and clip what they return
    if err:
        result += "\n[stderr]\n" + err.decode(errors="replace")
    if proc.returncode != 0:
        raise ToolError(f"cambc {' '.join(args)} exited {proc.returncode}:\n{_clip(result)}")
    return _clip(PROGRESS.sub("", result))


async def _cambc_json(*args: str) -> tuple[str, object]:
    """Run a --json command: (raw stdout, parsed JSON). The raw text is unclipped, so clip it before returning it."""
    out = await _cambc(*args, raw=True)
    try:
        return out, json.loads(out)
    except ValueError:
        raise ToolError(f"cambc {' '.join(args)}: output is not JSON:\n{_clip(out)}")


def _summarise(stats: Path) -> dict:
    if not stats.exists():
        return {"error": "no statistics written"}
    data = json.loads(stats.read_text())
    summary = {k: data[k] for k in SUMMARY_KEYS if k in data}
    summary["stats_file"] = stats.name
    summary["more_sections"] = sorted(set(data) - set(SUMMARY_KEYS) - {"formatVersion", "jsonFormatVersion"})
    return summary


# ---------- local project ----------


@server.tool()
def list_bots() -> list[str]:
    """List bot directories under bots/."""
    return sorted(p.name for p in (PROJECT / "bots").iterdir() if p.is_dir())


@server.tool()
def list_maps() -> list[str]:
    """List local map names (usable as the `map` argument of run_match)."""
    return sorted(p.stem for p in (PROJECT / "maps").glob("*.map26a"))


@server.tool()
async def build_bot(bot: str, release: bool = False) -> str:
    """Compile a bot (e.g. 'starter-python') and return compiler output. Use to check for build errors."""
    args = ["build", bot]
    if release:
        args.append("--release")
    return await _cambc(*args)


@server.tool()
async def run_match(
    bot_a: str,
    bot_b: str,
    map: str | None = None,
    rounds: int | None = None,
    release: bool = False,
) -> str:
    """Play a local match between two bots (names under bots/) and return the scoreboard plus a
    statistics summary (match, teams, roster, champions, diagnostics). The replay is saved under
    replays/ (view it with `cambc view`); timelines/events/heatmaps are available via match_stats."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    stats = STATS_DIR / f"{bot_a}-vs-{bot_b}-{map or 'default'}-{int(time.time())}.json"
    args = ["run", bot_a, bot_b, "--statistics", str(stats), "--json"]
    if map:
        args += ["--map", map]
    if rounds:
        args += ["--rounds", str(rounds)]
    if release:
        args.append("--release")
    log = await _cambc(*args, timeout=1800)
    return f"{log}\n[statistics]\n{json.dumps(_summarise(stats), indent=1)}"


@server.tool()
def match_stats(stats_file: str, section: str, filter: str | None = None) -> str:
    """Read one section (e.g. championTimelines, teamTimelines, events, heatmaps) of a statistics
    file returned by run_match or match_summary. `filter` keeps only list entries whose JSON
    contains that text (e.g. a metric name like "earnedGold" or a champion name)."""
    path = (STATS_DIR / stats_file).resolve()
    if path.parent != STATS_DIR.resolve() or not path.exists():
        raise ToolError(f"unknown stats file {stats_file!r}; available: {sorted(p.name for p in STATS_DIR.glob('*.json'))}")
    data = json.loads(path.read_text())
    if section not in data:
        raise ToolError(f"no section {section!r}; sections: {sorted(data)}")
    value = data[section]
    if filter and isinstance(value, list):
        value = [v for v in value if filter in json.dumps(v)]
    return _clip(json.dumps(value, separators=(",", ":")))


@server.tool()
def read_last_match_logs() -> dict[str, str]:
    """Return the stdout / debug / CLI logs of each team from the most recent local match
    (from .cambc/match-*). Useful for seeing your bot's prints and crashes."""
    dirs = sorted((PROJECT / ".cambc").glob("match-*"), key=lambda p: p.stat().st_mtime)
    if not dirs:
        return {}
    return {f.name: _clip(f.read_text(errors="replace")) for f in sorted(dirs[-1].iterdir())
            if f.suffix in {".stdout", ".debug", ".log"}}


# ---------- online platform (needs `cambc login` first) ----------


@server.tool()
async def ladder(page: int = 1, limit: int = 25, full: bool = False) -> str:
    """Current ranked ladder: one line per team (rank, rating, matches, name, team id). full=True: the raw JSON."""
    out, d = await _cambc_json("ladder", "--page", str(page), "--limit", str(limit), "--json")
    if full:
        return _clip(out)
    lines = [f"total {d.get('total')} page {d.get('page')}  (rank rating matches name teamId)"]
    lines += [f"{t.get('rank')} {t.get('rating') or 0:.0f} {t.get('matches')} {t.get('name')} {t.get('teamId')}" for t in d.get("teams", [])]
    return _clip("\n".join(lines))


@server.tool()
async def list_matches(
    team: str | None = None,
    kind: str | None = None,
    map: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
    full: bool = False,
) -> str:
    """List platform matches, one line each: id, created, kind, map, status/end, then side A and B (name, result, draft).
    kind: ranked | unranked | tournament. full=True: the raw JSON (characters, engine, group ids)."""
    args = ["matches", "list", "--limit", str(limit), "--json"]
    for flag, val in (("--team", team), ("--kind", kind), ("--map", map), ("--cursor", cursor)):
        if val:
            args += [flag, val]
    out, d = await _cambc_json(*args)
    if full:
        return _clip(out)
    lines = []
    for m in d.get("matches", []):
        ts = sorted(m.get("teams") or [], key=lambda t: t.get("side") or "")
        side = " | ".join(f"{(t.get('side') or '?').upper()} {t.get('name')} {t.get('result') or '-'} [{','.join(str(p) for p in t.get('draftPicks') or [])}]" for t in ts)
        lines.append(f"{m.get('matchId')} {(m.get('createdAt') or '')[:19]} {m.get('kind')} {m.get('map')} {m.get('status')}/{m.get('endReason') or '-'} | {side}")
    lines.append(f"nextCursor {d.get('nextCursor')}")
    return _clip("\n".join(lines))


@server.tool()
async def show_match(match_id: str) -> str:
    """Details of one platform match (JSON)."""
    return await _cambc("matches", "show", match_id, "--json")


@server.tool()
async def match_summary(match_id: str) -> str:
    """Download a platform match's statistics and return the summary sections (like run_match);
    use match_stats on the returned stats_file for timelines/events/heatmaps."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    out = STATS_DIR / f"match-{match_id}.json"
    await _cambc("matches", "summary", match_id, "-o", str(out), "--json")
    return json.dumps(_summarise(out), indent=1)


@server.tool()
async def match_group_quota(full: bool = False) -> str:
    """Remaining unranked match-group quota shared by the team (JSON: quota, ready, our rank, max rank gap, map count).
    full=True: the raw JSON, which adds all maps and every team's rank (~39 KB)."""
    out, d = await _cambc_json("match-groups", "quota", "--json")
    if full:
        return _clip(out)
    return json.dumps({k: d.get(k) for k in ("quota", "ready", "requesterRank", "maxRankGap", "team")} | {"maps": len(d.get("maps") or [])})


@server.tool()
async def create_match_group(opponent_team_id: str, maps: list[str] | None = None) -> str:
    """Queue five unranked platform matches of the team's current submission against an opponent
    team (IDs from ladder). Uses the team's shared quota - only on explicit user request.
    `maps`: exactly five map names/IDs, or omit for the platform's choice."""
    args = ["match-groups", "create", opponent_team_id, "--json"]
    if maps:
        if len(maps) != 5:
            raise ToolError("maps must list exactly five maps")
        args += ["--maps", ",".join(maps)]
    return await _cambc(*args)


@server.tool()
async def show_match_group(group_id: str) -> str:
    """Status and results of a queued match group (JSON); its match IDs work with match_summary."""
    return await _cambc("match-groups", "show", group_id, "--json")


@server.tool()
async def download_match_group(group_id: str) -> str:
    """Download a finished match group's five replays into replays/groups/<id>/."""
    out = PROJECT / "replays" / "groups" / group_id
    out.mkdir(parents=True, exist_ok=True)
    return await _cambc("match-groups", "download", group_id, "-o", str(out))


@server.tool()
async def submit_bot(bot: str) -> str:
    """Upload a bot's source to the team's platform submissions. Outward-facing: only on explicit user request."""
    return await _cambc("submit", bot)


if __name__ == "__main__":
    server.run()
