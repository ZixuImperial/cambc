# nova: BattleCats' Cambridge Battlecode 2026 bot

C++ compiled to WASM (client cambc 5.0.0, engine 3.0.0).

**Final submission:** `bots/nova_b16468_fbk1bz9`, platform version v919, live at the 00:00Z 14 Nov 2026 deadline.

## Layout

| Path | What |
|---|---|
| `bots/nova_b16468_fbk1bz9/` | The final bot (v919) |
| `bots/nova_b14207_dcg1r/` | Baseline bot (v859) used for drift checks |
| `bots/nova_spar_*/` | Sparring opponents used by the test panel |
| `sdk/`, `cmake/`, `cambc.toml` | SDK and build setup |
| `tools/lab/` | Testing pipeline (shipcheck, armq, condab, gate, readers) |
| `tools/cxe/`, `tools/condor/` | Native engine runner and Condor scripts |
| `maps/` | Map files |
| `docs/` | Design notes, code map, rules gaps, interactions |
| `GameRules.md`, `BotAPICpp.md`, `BalanceChanges.md` | Competition rules and API |
| `CLAUDE.md`, `.claude/` | Agent instructions used during development |

The tools assume the lab machines' paths (`/data/zw4424`, `/homes/zw4424`) and Condor setup.
