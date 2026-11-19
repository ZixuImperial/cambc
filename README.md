# BattleCats' Cambridge Battlecode 2026 bot

Proper postmortem coming later, currently claude generated postmortem and strategy markdowns.

Final ladder: https://2026a.battlecode.co.uk/game/ladder

UK qualifiers: https://2026a.battlecode.co.uk/game/tournaments/f160945b-afb8-49f2-8b67-eab4574e94fd

Finals: https://2026a.battlecode.co.uk/game/tournaments/18df17b0-5c09-4af7-80e5-5a37a2857a7a

C++ compiled to WASM (client cambc 5.0.0, engine 3.0.0).

**Final submission:** `bots/nova_v919`

## Layout

| Path | What |
|---|---|
| `bots/nova_v919/` | The final bot (v919) |
| `bots/nova_spar_*/` | Sparring opponents used by the test panel |
| `sdk/`, `cmake/`, `cambc.toml` | SDK and build setup |
| `tools/lab/` | Testing pipeline (shipcheck, armq, condab, gate, readers) |
| `tools/cxe/`, `tools/condor/` | Native engine runner and Condor scripts |
| `maps/` | Map files |
| `docs/` | Design notes, code map, rules gaps, interactions |
| `GameRules.md`, `BotAPICpp.md`, `BalanceChanges.md` | Competition rules and API |
| `CLAUDE.md`, `.claude/` | Agent instructions used during development |

Currently the tools will not work on any machine as they require specific file system and Imperial Condor setup.