# cxe: native test engine (engine 2.0.0 rules, ~3.3x less CPU / ~4.5x faster wall than the CLI, verified)

cxe plays Cambridge Battlecode 2026 matches natively. It is not a re-implementation of the rules: it runs the real
engine 2.0.0 (`condor-work/engine/v2_0_0.wasm`, the visualiser build) translated to C by our own translator
(`w2c.py`), and each bot's own release WebAssembly translated the same way with fuel metering. `cxe.cpp` re-implements
the official CLI host around them: bot instances as coroutines, the 91 env imports (spec from the CLI's own host code:
/data/zw4424/st/cxe/importmap.md), per-turn fuel budgets and the runner loop. Bots keep wasm32 semantics (32-bit
`long` etc.) because their WebAssembly, not their C++, is what gets translated.

## Use
```
python3 -I tools/cxe/cxeab.py BOT_A BOT_B NAME [--maps N | --pool | --maplist F] [--jobs J] [--pgo]
        # local A/B, abl.sh-style summary (ablsum); 200 games in ~4 s on 8 cores; refuses while STATUS is FAIL
python3 -I tools/cxe/fuelprof.py BOT [--opp BOT2] [--maps 12] [--top 40]
        # where a bot's fuel goes: per function and per C++ area, plus where turns run out of fuel
python3 -I tools/cxe/cxebuild.py BOT [BOT...]        # -> /data/zw4424/st/cxe/so/<wasm sha>.so (cached; ~1 min new code)
/data/zw4424/st/cxe/host/cxe A.so B.so MAP.map26a OUT [--fuel N] [--rounds N] [--statistics OUT.json]
python3 -I tools/cxe/cxerun.py MANIFEST [--jobs N] [--statistics]   # lines: SO_A SO_B MAP OUT_PREFIX
python3 -I tools/cxe/cxeverify.py BOT_A BOT_B [--maps N] [--seed S] [--jobs J]   # CLI v cxe, game by game
```
Outputs per game: `OUT.repl26a` (the engine's own replay: readable by tools/lab/replay.py and the visualiser),
`OUT.fuel.tsv` (per-turn fuel, the CLI's .fuel-log convention), `OUT.json` (with `--statistics`: the CLI's
`--statistics --json` fields that tools/lab/ablsum.py / condab.py read: outcome, rounds, per-champion kills, deaths,
earned gold, collected gems, items, ward placements, fuel exhaustions, bot faults). `CXE_STDOUT=1` writes each team's
bot stdout to `OUT.team-a.stdout` / `OUT.team-b.stdout`.

## Speed (4 Nov, same 12 games, one core): CLI 5.32 s wall / 3.64 s CPU; cxe ~1.1 s. Engine and bots are -O3
-march=x86-64-v3; the engine is profile-guided (stored profile), bots optionally (--pgo, ~6-8%). Time split per game:
engine ~50%, bots ~40%. Per-game start-up is negligible.

## Regular check
(cxewatch.py was removed on 8 Nov: its opponents were deleted. It is in git history; the note below is the old description.)
`tools/cxe/cxewatch.py --loop` (daemon; pid /data/zw4424/st/cxe/cxewatch.pid): 20 games (live v rotating opponent, 5
fixed + 5 fresh maps x 2 seats) whenever live changes and every 6 h; /data/zw4424/st/cxe/STATUS = OK | WARN | FAIL.

## Verification (4 Nov 2026)
| Check | Result |
|---|---|
| translated engine v original wasm (node), scripted full games, 00anvil + 02the-pack | replay bytes identical |
| live v live, unlimited fuel (1e9), 00anvil | replay identical to the CLI |
| per-turn fuel, 7,991 turns of that game | 7,991 / 7,991 equal to the CLI's .fuel log |
| live v live at the real 100k budget, 00anvil and 02the-pack (fuel cut-offs included) | replays identical to the CLI |
| fuel probe bot (fuel_remaining across out-of-fuel suspensions) | all 98 output lines identical |
| `cxeverify` live v previous live, 50 sampled maps x 2 seats | 100 / 100 replays and metrics identical; CLI 22.6 s, cxe 6.6 s |
| `cxeverify` live v nova_spar_mite (C&I lineup), 100 maps x 2 seats | 199 / 200 identical (game 68: open item below) |
| `optest.py`: every instruction (349 incl. all SIMD) v V8, random + edge inputs | 0 differences in 130,200 cases |
| 19 probe bots (fuel across cuts, host charges, slices, bulk copies, WASI, printf, recall, static tables) | all identical |

Re-run `cxeverify.py` after any change to cxe, the engine version or the CLI.

## Fuel model (fitted on the CLI's own per-turn fuel log, exact)
wasmtime fuel: every instruction 1, except nop, drop, block, loop, else, end, return, unreachable and memory.grow (0);
checks at function entry and loop headers (out when consumed >= budget); plus what the CLI adds: **1 per function
entry** and **1 per byte moved by memory.copy / memory.fill**. Host imports charge as in importmap.md (whole-board ops
= chunk count, lists/memory 1 per 8 bytes, distance fields min(40000, (expansions+16) x chunks)). Budgets: 100k per
turn, x100 on the first draft turn, x2 on each champion's first turn; out of fuel suspends the bot mid-instruction and
it resumes next turn.

## Known differences
- FIXED 7 Nov: turns with several fuel slices (a bot's first draft turn, 100x; its first champion turn, 2x). The CLI meters them slice by slice, and cxe ran one straight budget. Compare every
  fuel() a diag bot reads: 953 of 5,988 bot-games differed. The model now in cxe.cpp: a wasm fuel check starts the next slice and keeps any overshoot; until then a reading stops at the slice end;
  a host charge works on that reading, so an overshoot is forgiven, and a charge reaching the slice end starts the next slice. After it: 360 full games and 2,936,984 turns exact, 0 of 1,795
  one-round games differ (1 before). 'Clamp the charge at the slice end' (T17) and 'a bulk op check does not refill' both made it worse.
- OPEN: about .75% of bot-games still read a slice end where cxe reads past it, in the first draft turn, for one or two readings, after a large jump in fuel. Cause unknown. The fuel is equal again at
  the next reading, so it can only flip a decision that compares that one reading: a diag bot differed on 2 maps, the real bot on none of 1,795. Spot-check mismatches keep evidence in
  /data/zw4424/st/cxe/spotbad/. A bot that writes to stdout: the CLI's team-X.stdout is not reliable (zero bytes, lost lines), so diag reads need care.
- FIXED 6 Nov (conf): the CLI also checks fuel at memory.copy / memory.fill (after charging their bytes), so a turn can be
  cut there; cxe checked only at function entries and loop headers and cut later, so the resumed turn's fuel (which bots
  read) differed by 9-196 units (1 game in 40 of a cut-heavy fuzz bot diverged). w2c.py now checks after every bulk op.
- WASI is answered exactly as the CLI does (probes 6-12): fd_write writes only the first non-empty iovec; stdio fdstat
  = UNKNOWN filetype with read/write rights; lseek on stdio ESPIPE; unknown fds EBADF; stdin EOF.
- FIXED 11 Nov: a draft bot that ends its turn without a pick (e.g. its 10M draft turn runs out of fuel, common for the
  spars on 100+-group maps): the CLI picks at random; cxe used to take the first legal pick, so 3 spot-checks on
  many-group maps diverged from the draft on. cxe now reproduces runner::Game::default_draft: RNG state = FNV-1a 64 of
  the map bytes (the CLI's statistics 'seed'), shared by both teams; per pick a Fisher-Yates shuffle of 0..11 from the
  end with splitmix64 steps, the first champion Game_Action_Draft accepts; the pick happens before EndTurn (reason 1 if
  cut, else 2). After: the 3 spotbad games and 3 both-teams-random games byte-identical to the CLI, 20/20 ordinary games
  identical to the old host.
- Bot traps (crash) end that bot (reason 2 to the engine); the CLI's restart policy after a crash is not reproduced.
  No live bot has crashed in testing.

## Files
`wasmparse.py` (decoder), `w2c.py` + `w2c_rt.h` / `w2c_rt.c` (translator and runtime; `--fuel`, `--profile`,
`--split N`), `cxe.cpp` (host), `cxe_wasi.c`, `cxe_imports.h` (generated import prototypes), `eng.js` (node loader
of the original engine for protocol checks), `test_engine.c` (engine translation check).

## Replay decoding (cxedec)
`cxe --decode REPLAY OUT.json` is rdec.js (condor-work/tools/rdec.js) ported to C++ (cxedec.cpp): the same JSON byte for
byte apart from decoder.ms, about 4x faster (00anvil-size game 0.39 s v 1.6 s). `cxe A.so B.so MAP OUT --record` also writes
OUT.rdec.json for the game just played. tools/lab/replay.py decodes through tools/cxe/cxedec.py first and falls back to
rdec.js for other engines, missing binaries, or an rdec.js newer than the ported one (RDEC_PORTED). Check:
`python3 -I tools/cxe/cxedec.py --verify 150` (4 Nov: 150/150 live games identical, 145 with summaries; plus 24 local
cxe games incl. fuel cuts).

## Local cxe v cxe on Condor
`CONDAB_ENGINE=cxe` (inforead --engine cxe) plays on maple04's CXE_SLOTS (8 of 16 cores). Once CXE_LOCAL_MAX (default 3) local
batches are already playing, a new batch plays cxe on Condor nodes instead (condab_engine cxecondor path: same spot-check), so
parallel reads no longer queue on maple04 (4 Nov 17:30Z: 58 batches, ~35k games were queued on 8 slots). Round-capped
on-the-fly games (OTF_ROUNDS) are capped on cxe too; their spot-check compares replays (the CLI writes no statistics for them).

## Build cache for flips
The translator writes data segments, init and exports to their own part (OUT.data.c) and cxebuild caches every compiled part
by its C text, flags and compiler (/data/zw4424/st/cxe/obj, 3 days). A data-only flip (flip.sh) changes only the data part, so
its build takes ~3 s (nova_b1378_dltg after nova_trunk20g: 2.8 s v ~20 s; cxeverify 40/40 identical, every turn's fuel equal).
A flip (bots/NAME/FLIP with an existing WASM= and no source newer than FLIP) is also translated from flip.sh's own wasm, which
is byte-identical to the CLI build of its source; the CLI build (2-3 min under load) then runs in the background (log
st/cxe/cli_bg.log) and cli_bot_dir/wasm_of wait for it. nova_b1371_tdn4: 2.75 s from nothing built (cxeverify 30/30 identical).
Compile flags were measured on 00anvil (500M instructions a game): -O1/-O2/-O3, no-plt and one compile unit all within 0.6%:
the translated bot code is at its limit on instruction count; PGO (cxebuild --pgo) changes layout only.

## Exceptions (try_table) and ehtest
(ehtest.py was removed on 8 Nov and is in git history; the description below is the old one.)
try_table frames use w2c_rt.c's own setjmp/longjmp (callee-saved registers, stack pointer, return address; returns_twice):
~1.2% fewer instructions a game than glibc's _setjmp. __builtin_setjmp was tried and broke catches without changing a replay,
so `python3 -I tools/cxe/ehtest.py` plays probes/probe21 (throw across frames, catch by type, rethrow, nested try, catch(...))
on cxe and the CLI and compares the replay AND every printed result; cxewatch runs it in every regular check (FAIL if it differs).

## What the bots asked for: --record action log and actlog.py
`cxe A.so B.so MAP OUT --record` writes OUT.rdec.json: the rdec.js decode plus a "cxe" part with every action call (round,
champion, action, return code, arguments, the result word of move/cast/consumable/ward) and every turn's budget, fuel used and
stop reason; host-side only, the replay is unchanged. `tools/cxe/actlog.py play A B --maps 20` plays both seats with it and
reports, per team, each action's calls and failures per game by error name (BotAPICpp.md error_code); `actlog.py show FILE
--champ C --rounds R1-R2 [--action move] [--fails]` lists the calls. 4 Nov, live v496 v nochase2 (40 games): 3.65 moves/game
fail is_recalling (a SPIN_SELF recall not cancelled before a move), 5.05 attacks/game bad_target, 2.25 casts/game bad_destination.

## Debug-build libraries and local close-reads
`python3 -I tools/cxe/dbgso.py BOT` builds a cxe library from the CLI's debug build (diag DG records; primer RULE CXE-DIAG) with
dbgshim.c for its fuel_pause/resume/adjust imports; run with CXE_STDOUT=1. `tools/lab/closeread.py run TAG CAND BASE --engine cxe`
plays the close-read's games locally with --record and reads the decodes in place (no Condor batch, no readmany passes): 4 Nov,
irb1139_04164852 --max 20: 99 games, every rebuilt result matched the original read (66/66), 7.7 min of which ~4 min map rebuilds.
The bot object cache key covers w2c_rt.h (a reverted header's objects were reused once: undefined w2c_eh_jump).

## Fork: rollouts from one game state (`--fork-at`, cxefork.py)
`cxe A.so B.so MAP OUT --fork-at R [--fork-k K] [--alt-team A|B] --alt ALT.so [--alt ALT2.so ...]` plays to the first turn of
round R (0 = before the draft), then forks one child per ALT, one at a time. In the child, every instance of the ALT team gets
the bytes where ALT's initial memory differs from that team's module (a data flip changes only its flag tables), and later
instances get them at creation. Each branch plays on to round R+K-1 (or the end) and writes OUT.altN.repl26a (plus
OUT.altN.rdec.json with --record, PATH.altN with --statistics, OUT.altN.fuel.tsv and stdout logs from R). The parent is the
base branch. cxe refuses an ALT whose function/import/type counts, memory size, table or globals differ; the wrapper also
compares the wasm code sections.
Checked on 3 maps (4 Nov): fork at 0 = the straight ALT game byte for byte (both seats); an identity fork (ALT = base) at
150 = the straight base game; the parent is unchanged by forking; a flip that fires late (PWL) shares every action before R and
first diverges at r613; normal games are byte-identical to the previous host.
`python3 -I tools/cxe/cxefork.py BASE OPP --at R [--k K] --alt FLIP ... [--maps N | --maplist FILE] [--seats AB] [--jobs 4]
[--record]` does the rest: checks each ALT is a data flip of BASE, builds the libraries, plays both seats through cxerun's
slots, and prints per ALT the paired change in V(us - them) (V = tributed + carried gems + .35 earned gold, read from each
branch's replay because the engine's statistics are empty for a game stopped early), wins, and how many games the ALT changed
at all. Rows per game x branch: OUT/branches.tsv. The engine statistics (`--statistics`) are only filled for games that end.

## Engine versions (4 Nov: the finals patch, engine 3.0.0 / cambc 5.0.0)
cxe plays engine 2.0.0 (default) or 3.0.0. `CXE_ENGINE_VER=v3_0_0` picks v3 for one process; writing `v3_0_0` into
/data/zw4424/st/bq/cxe_engine.txt moves every tool (host/cxe then points at the v3 host after the next build). Each engine is
paired with its CLI for builds and spot-checks (v2_0_0: cambc400, v3_0_0: /data/zw4424/cambc500/bin/cambc500); a bot's release
wasm is byte-identical from both CLIs, so every cached bot library is reused. Hosts: host/cxe-v2_0_0 / host/cxe-v3_0_0 (host/cxe =
the default). Decoding picks the host by the replay's header version word (bytes 8-11: 2 or 3); a 2.0.0 host refuses a 3.0.0
replay with exit 3. Checked: cxeverify (CXE_ENGINE_VER=v3_0_0) v the 5.0.0 CLI, 40/40 replays and metrics identical, fuel equal
on all but the 9 known bookkeeping turns; the 5.0.0 `__run-match` runner = cxe v3 byte for byte; v2 and v3 games differ.

## ORACLE: test-only perfect team channel (5 Nov)
For ceiling reads ("what if every mate knew X?"). A per-team blackboard in the debug shim (dbgshim.c: nova_oracle_put/get), no
bandwidth, encoding or fuel cost, one store per game (cxe runs one game per process; entries keyed by team and ally slot).
- Bot side: `NOVA_ORACLE_PUT(slot, round, ptr, len)` (len <= 1024) and `NOVA_ORACLE_GET(slot, ptr, len)` -> round written or -1,
  from tools/lab/checks/nova_check.h. Write at your turn end, read at turn start; filter mates yourself (e.g. `W.ally_by_slot(s)`
  for an in-sight arm). Works only in cxe debug builds (chkbuild/dbgso); platlock refuses to submit such a bot.
- Pattern: tools/lab/checks/probe_pmora.py (feeds b1240's consumers; env PMORA_ALL picks the arm), round-trip test probe_oracle.py.
- Build: `python3 -I tools/lab/chkbuild.py BOT --spec SPEC.py` (prints the .so); read: `python3 -I tools/cxe/cxeab.py SO BASE NAME
  --maplist FRESH_MAPS.txt` (cxeab takes a .so; maps by path from tools/lab/stratmaps.py --take).
- First use: pm_oracle_ceiling_1105.md (in-sight .499, all mates .507: closed).

## Pilot compile (tools/cxe/pilotcc.py, sc1 6 Nov)
- `cxebuild` compiles a wave of >= 2 parts on an idle Condor pilot with this machine's own clang, staged at /homes/zw4424/condor-runs/cxe/cc-HASH. Objects are byte-identical to local ones; every batch compares one part with a local compile.
- Off: `CXE_CC_LOCAL=1`. Any failure, or no pilot in 25 s, goes local with a `pilotcc:` line on stderr. Log: /data/zw4424/st/cxe/pilotcc.log. Test: `python3 -I tools/cxe/pilotcc.py --selftest N DIR`.

## Fuel record / replay (9 Nov, puppet --diag)
`CXE_FUEL_REC=PATH cxe A.so B.so MAP OUT` writes, per bot turn (phase, round, team, champion), every value fuel_remaining() returned
and how the turn ended (stop code; counted host calls before a yield or an out-of-fuel cut). `CXE_FUEL_PLAY=PATH` plays each recorded
turn with no fuel limit: fuel_remaining() returns the recorded values in order and a turn recorded as cut after k calls is suspended at
its (k+1)-th, before it runs. A diag copy (different code, so different instruction counts) then sees the real game's fuel and cuts.
Counted calls: env imports with TI() and yield (pure ones, bitboard algebra, cxe_probe and WASI, are not). Mismatches print on stderr
(`cxe: fuel-play mismatch ...`) and a summary line at exit; a turn with no record plays with normal metering. Unset: no change (9 Nov
check, host v the previous host, live v 3 spars + mirror, 20 maps x 2 seats at 100k: 80/80 replays, fuel logs and statistics
byte-identical, also with CXE_FUEL_REC set; record -> play of the same bots: 13/13 replays identical, incl. budgets 3k/8k with 84/24
cuts). Not supported with --fork-at.
