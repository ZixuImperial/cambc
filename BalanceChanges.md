# CAMBC after the post-Sprint-1 balance patch

This is a reference for bot authors who know the rules from the 2.2.5 era. Everything below describes the new game: the handbook after the patch, plus the SDK and engine at cambc 3.0.1. Anything about the old game is marked "old". There is no strategy advice here. Compiled 2026-10-20.

## 1. Sources and versions

- **Rules:** `new_GameRules.md`, the published handbook ("CAMBC Game Rules", event cambc2026a) after the post-Sprint-1 balance patch. The old handbook is `old_GameRules.md` (2.2.5 era).
- **API reference:** `new_BotAPICpp.md` (C++, 3.0.1). The old reference is `old_BotAPIPython.md` (Python, 2.2.5).
- **SDK and engine:** cambc **3.0.1**, made up of:
  - `cambc.h` and `imports.h`;
  - the Python and Rust constants files;
  - the starter templates, which are byte-identical to 2.2.5.

  The old version is **2.2.5**. As of 2026-10-20 this repo is still on 2.2.5: `sdk/cpp/cambc.h`, `sdk/cpp/imports.h`, the `.venv` package, and `cambc.toml` (`sdk_version = "2.2.5"`).
- **Authority:** the new handbook together with the 3.0.1 SDK. Where the two disagree, §6 lists it.
- **Numeric engine settings are not fixed in the SDK.**
  - `cambc::constants::*` values (kill_gold, assist_gold, passive_gold, ward_cooldown, altar_lock_hits, capture_time, ...) are copied from the engine's `Game_Settings` record when the bot starts.
  - Champion, camp, item and consumable designs are queried from the engine at runtime.
  - The headers contain no literal values for any of these, so the numbers in this document come from the handbook.
  - The only compile-time literals are `constants::passive_abilities::*`.
- **Engine cross-check:** the verification pass read the settings and design tables in the 3.0.1 engine binary. They match the handbook for:
  - kill_gold 100, ward_cooldown 10 (ward_lifetime −1) and altar_lock_hits 5;
  - capture 5, camp sleep 2, respawn 60, recall 5, and tribute at 0.1 per gem (base 0, minimum 1, range 1);
  - ward vision 6 and placement 2, 1 active ward, tile reveal 1, TP crystal 3, and spawn healing 1.0;
  - the full camp table including the Golem (clusters have design range 3, see §6);
  - all 13 champion rows (base and growth for Health, Strength and Focus, attack range, every ability multiplier, range, shield and the Heart of Ruin dash data), and Marcella's tribute-gold hook;
  - assist_gold 0 and passive_gold 0 (no per-round income).

  The same read of the old 2.2.5 engine shows that exactly three runtime settings changed: kill_gold 50 → 100, ward_cooldown 1 → 10 and altar_lock_hits 3 → 5.
- **Confirm at runtime once a bot exists** (log them once at init):
  - **Game settings:** every `constants::*` value, especially `kill_gold`, `assist_gold`, `passive_gold`, `ward_cooldown`, `altar_lock_hits`, `camp_sleep_time` and `spawn_healing`.
  - **Champion designs** (all available during the draft):
    - `champion_designs[t].base_stats()`: base and growth for Health, Strength and Focus, plus attack range.
    - `.abilities()`: kind, modifier, range, radius, duration, `max_cooldown`, `valid_targets` and `exclusive_with_movement`, including Heart of Ruin's dash fields.
    - `.passive()`.
  - **Camp designs:** `camp::base_stats()` and `attack_range()` for each type; `camp_group::gold_value()`, `gem_value()` and `max_respawn_timer()`.
  - **Item info:** `item_type::info()` (cost, combine_count, stat points, passive, passive_magnitude, purchasable) and `consumable_type::info()` (cost, carry_limit).
  - **Draft:** Heart of Ruin is accepted on the platform (picked in ranked games since the patch).

## 2. Biggest changes

> **Version note (27 Oct):** §2-§4 describe the 3.0.1 docs (engine 1.0.0). Engine 1.0.2/1.0.3 and 2.0.0 changed several numbers; current values: §12 and /data/USER/cambc400x/designs84_v2_0_0.json.
>
> **Stale values (engine 3.0.0 probe, 5 Nov, docs/rules/20_interactions.md Q23/Q37):** Treasure is **+10%** (Vesper + Treasure = **43%**; a Vesper kill pays 133, 143 with Treasure). The "+20% / 53% / Treasure still +20%" text at lines 55, 160 and 193 is 1.0.0-era. Vesper base Strength is **35** on 3.0.0 (line 194's 50 is 1.0.0). For current base stats use GameRules.md or §13. The 13 engine design rows match GameRules.md exactly.

1. **Wolf reward:** 90 gold / 22 gems → 40 gold / 4 gems (gems −82%).
2. **Elk:** 160 gold / 36 gems → 90 gold / 15 gems. Attack range 3 → 4.
3. **Gem and gold clusters:** 500 HP → 120 HP. A gem cluster gives 24 → 7 gems; a gold cluster gives 35 → 20 gold.
4. **Monolith:** attack range 3 → 5, which outranges every champion attack and spell. Its rewards (300 gold, 200 gems, 150-round respawn) are the only camp rewards left unchanged.
5. **New monster, the Golem:** none → 5,000 HP, Strength 120, range 4, 160 gold, 36 gems, respawn 80.
6. **Kill gold:** 50 → 100 base. Assists still pay 0, and Cassi & Issac still give a single reward. 100 gold is 2.5 wolves or 1.1 elk.
7. **Ward recharge:** 1 round → 10 owner turn ends. A champion can now place or move its ward only once every 10 of its own turns.
8. **Altar lock:** 3 → 5 basic attacks to remove.
9. **Heart of Ruin:** none → a 12th draft choice (index 11). Melee; up to +50% damage when wounded; a 1.5 × Focus self-shield; a 2-tile dash whose landing deals 1.75 × Focus and stuns in radius 1. (2.0.0: the landing deals 1.5 × Focus.)
10. **Prism:** passive 0.2 → 1.5 Focus per carried gem (corrected 27 Oct: every 4.0.0 SDK has `prism_focus_per_gem = 1.5` and a local probe confirmed it; earlier text said 1). Growths cut: Health 75 → 60, Strength 3.5 → 2.5, Focus 10 → 8.
11. **Marcella:** her passive now also gives 2 gold per gem she tributes. Focus 50 / +10 → 60 / +15.
12. **Vesper Vale:** gold bonus +20% → +33% (53% with Treasure). Strength 45 → 50. (2.0.0: 43% with Treasure; Strength 45.)
13. **Tavi:** slot-1 nuke 2.2 → 1.4 × Focus (220 → 140 at base). Strength 35 → 45. (2.0.0: 1.6 × Focus, 176 at base.)
14. **Stellar:** Strength 35 → 30. Focus 100 / +10 → 85 / +9, so slot 0 at base drops 200 → 170. (2.0.0: Focus 70 / +8.5, so slot 0 deals 140.)
15. **Other stat shifts:**
    - Base Strength: Varg 50 → 40, Ryth 50 → 45, Ren 40 → 35, Willow 45 → 55.
    - Ren Focus growth 10 → 9. Willow Focus 105 → 120. Vendetta Strength growth 5 → 6.
    - Cassi Health 700 → 600, plus growth cuts. Issac growth cuts: Health 95 → 80, Strength 4.75 → 3.

**Unchanged:**
- Win condition and tiebreaks.
- Draft procedure, selection rules and team size (3–5).
- Turn order and the per-turn action economy.
- Movement and hidden-occupant rules.
- Capture (5 rounds, reward split, integer remainder) and group respawn rules.
- Tribute formula, recall (5, or 3 with Home) and respawn (60).
- Champion vision 8, ward vision 6, ward placement 2, one permanent ward.
- Shard and emblem system and prices, and consumable prices.
- Fuel, shared memory and draft memory.
- Every ability's range, targeting, Walking tag and 8-turn cooldown. Every ability multiplier except Tavi's slot 1.

**Bot-facing:**
- SDK 3.0.1 breaks the host ABI, so every bot must be rebuilt against it.
- It adds the Heart of Ruin and Golem enums, awake and asleep camp bitboards, `vision::in_vision`, `ward::owner()` and dash landing metadata.
- `move_towards` now walks toward a blocked target and throws on the final step into it (§5).

## 3. Full change log

> **Version note (27 Oct):** §2-§4 describe the 3.0.1 docs (engine 1.0.0). Engine 1.0.2/1.0.3 and 2.0.0 changed several numbers; current values: §12 and /data/USER/cambc400x/designs84_v2_0_0.json.

Each row reads old → new. "Doc-only" means the wording changed but the rule did not. Derived numbers are at base stats with no items unless stated.

### General

| Change | Old | New | Notes |
|---|---|---|---|
| "Overview" section added under "The game" | absent | Describes the game: camps carry gems and gold; tributing gems at altars scores; the most gems tributed wins; gold buys damage or health | Doc-only. "How to win", tiebreak notes and "Obtaining Resources" are unchanged. |
| Turn sections merged | "Understand a turn", "Rounds & turn order", plus the boxes "Your code controls all your actions" and "Game time ≠ compute time" | One section, "A champion turn": new intro, "Everything you can do", "The exact turn order" | Doc-only. No turn-order rule changed. The content of the removed boxes is still stated under Shared memory and Fuel. |

### Economy and camps

| Change | Old | New | Notes |
|---|---|---|---|
| Wolf gold | 90 | 40 | −56%. HP 1,350, Str 20, range 3 and respawn 40 are unchanged. |
| Wolf gems | 22 | 4 | −82%. 3.0 gems per 1,000 HP (was 16.3). |
| Elk gold | 160 | 90 | −44%. HP 2,400, Str 60 and respawn 60 are unchanged. |
| Elk gems | 36 | 15 | −58%. 6.25 gems per 1,000 HP (was 15). A two-elk group now gives 30 gems (was 72). |
| Elk attack range | 3 | 4 | Confirmed in the engine. Single-target spells (range 4) now cast from inside its reach. Radius-1 ground spells cast at range 4 reach 5 and stay outside. A champion within 4 keeps an awake elk awake. |
| Golem (new monster) | — | HP 5,000, Str 120, range 4, 160 gold, 36 gems, respawn 80, vision 8 | Same reward as the old Elk for 2.1× the HP and 2× the Strength. 7.2 gems per 1,000 HP. A group containing a Golem respawns after 80 rounds, or 150 if it also has a Monolith. SDK doc: "Golem: 5,000 health, 120 strength and attack range 4; drops gold and gems." |
| Monolith attack range | 3 | 5 | Confirmed in the engine; the SDK doc now says "attack range 5". It outranges basic attacks (3) and spells (4); radius-1 area spells reach exactly 5. HP 20,000, Str 200, 300 gold, 200 gems and respawn 150 are unchanged. It is now the most gem-dense camp that fights back (10 gems per 1,000 HP). |
| Gem cluster HP | 500 | 120 | SDK doc updated. |
| Gem cluster gems | 24 | 7 | Per cluster. 58 gems per 1,000 HP (was 48). 0 gold and respawn 50 are unchanged. |
| Gold cluster HP | 500 | 120 | SDK doc updated. |
| Gold cluster gold | 35 | 20 | 0 gems and respawn 50 are unchanged. |
| Per-type Range column | One rule: "All monsters have attack range 3 and vision 8" | Wolf 3, Elk 4, Golem 4, Monolith 5; clusters listed as 0 | `camp::attack_range()` returns the engine's design range. Code that hard-codes 3 is wrong for Elk, Golem and Monolith. |
| Cluster range shown as 0 | 3 (blanket rule) | Table shows 0; the engine design is still range 3 with Str 0 | Clusters never attack: the engine rejects attacks from strength-0 camps. The range-3 design only keeps an awake cluster awake while a champion is within 3 (§6). |
| Camp targeting documented | not stated | "it will awaken attacking the nearest champion every turn" | Engine behaviour is unchanged. Once per round, at round start, each awake camp hits the champion at the smallest Chebyshev distance, from either team, if that champion is within its range. |
| Monster Strength defined | not defined | "strength (damage dealt per turn)" | Each camp hit deals its Strength (Wolf 20, Elk 60, Golem 120, Monolith 200), once per round, before Jungle (−30%) and Durability (−10%). |
| Sleep rule restated, now contradictory | "Damage wakes the group; two rounds without an in-range champion let it sleep." | That bullet is kept. A new intro adds that the monster attacks "until it either dies or does not take damage for 2 turns." | The engine and the SDK's `camp_sleep_time` doc follow the bullet (§6). |
| Table caption dropped | "Base values per monster, before champion bonuses." | removed | Doc-only. The values are still base values; Vesper Vale and Treasure bonuses apply on top. |

### Capture and tribute

| Change | Old | New | Notes |
|---|---|---|---|
| When a group's respawn timer starts | "After a camp is defeated, its respawn timer begins." This contradicted the caption "Respawn timers begin after the reward is claimed." | "After a camp reward is captured, its respawn timer begins." | Doc fix; the engine is unchanged. A cleared group that nobody captures never starts its timer. |
| Tribute duration in the turn summary | Only the exact formula | "a number of turns, equal to the number of gems being tributed divided by 10" | Simplified wording. The exact rule is unchanged: max(1, ceil(gems at start / 10)) owner turn ends. |

Marcella's tribute gold is listed under Champions.

### Altar locks

| Change | Old | New | Notes |
|---|---|---|---|
| Basic attacks to remove a lock | 3 | 5 | Changed in all three handbook mentions (Altar locks twice, the Consumables table once); engine `altar_lock_hits` 3 → 5. A tribute attempt against a lock counts as one attack. One champion needs 5 turns (4 with an attack reset); two need 3; three need 2. Unchanged: cost 10 gold, placement within 2 tiles, blocking only enemy tributes, cancelling channels. Read `constants::altar_lock_hits` and `altar_lock::hits_remaining()`. |

### Combat and turn

| Change | Old | New | Notes |
|---|---|---|---|
| Ranged move/attack rule restated | "Movement and attacks share an allowance for ranged champions", "ranged champions ordinarily choose one", plus a Walking tag on each ability | "If you are a ranged champion, you may NOT move, and basic attack on the same turn. This same rule applies for damaging abilities that are ranged as well." | No mechanical change: every old Walking tag is identical. Every range-4 damaging spell excludes walking, melee casters included (Cassi 0, Ryth 0, Prism 0/1, Stellar 0/1, Marcella 1, Tavi 1, Ren 0). Walk-compatible: attack resets, dashes (including Heart of Ruin's damaging dash), shields, Cassi's stun, Willow's heal. This does not forbid a basic attack and a spell in the same turn: that was common in 2.2.5, and there is no error code for it. |
| Attack resets restore the attack allowance | Implied only; the SDK doc for attack_reset says "Restores the basic attack allowance." | "Attack-reset abilities can restore the attack allowance." | A ranged champion can walk, cast a walk-compatible reset (Vesper Vale 0, Tavi 0, Willow 1), then basic attack. Seen in 2.2.5 replays (Tavi 141 times); not yet re-tested on 3.0.1 (§6). |
| Worked Focus example | none | "Stellar starts with 85 focus ... a burst of 170 damage, starting its 8 turn cooldown" | Matches the Stellar nerf (the old base burst was 200). |
| Spell charges rule | "Zero maximum charges means the spell is not charge-limited." (heading "Targets and charges") | removed; heading is now "Targets" | No effect, because no ability has charges. The ABI still carries `max_charges` and error 29 `invalid_action_spell_cast_no_charges`; the C++ API has never exposed charges. |

### Wards and vision

| Change | Old | New | Notes |
|---|---|---|---|
| Ward charge recharge | 1 round: "One charge, recharging one round after use"; "You may freely replace it, once per round" | 10 owner turn ends: "Its charge recharges over 10 owner turn ends." | Real engine change (`ward_cooldown` 1 → 10). Stated in Wards, in the "A champion turn" intro and in "Everything you can do". A ward placed on own turn T can next be placed or moved on turn T+10. Read `constants::ward_cooldown` and `champion::ward_cooldown()`. |
| Ward bullets moved; line-of-sight wording dropped | "Within 2 tiles: It sees 6 tiles, with the same line-of-sight rules."; heading "Vision is not shared" | The 6-tile vision and 2-tile placement are now stated only in the "A champion turn" intro, without "with the same line-of-sight rules". Heading is now "Vision is not shared among allies". | Doc-only. Nothing says wards ignore walls or bushes, and `ward::visible_tiles_from()` is unchanged, so assume line of sight still applies (§6). |

### Death and kills

| Change | Old | New | Notes |
|---|---|---|---|
| Kill gold | 50 base | 100 base | Changed in all three statements, including "Cassi and Issac die together, awarding the killer 100 gold" (still one reward for both bodies, plus both bags). Assists still get 0. Engine `kill_gold` is 100. The handbook calls it "base" gold, so Treasure (+20%) and Vesper Vale (+33%) presumably apply (§6). |
| Recall in the turn summary | — | "This cancellable action takes 5 turns, and will teleport the champion straight to their spawn tiles." | Doc-only. The Recalling section is unchanged: 5 owner turn ends, 3 with Home. |
| Assist gold (discrepancy older than the patch) | Handbook: "assists award no gold". SDK `assist_gold`: "Base gold pool split among champions credited with an assist". | both unchanged | They agree only if the runtime value is 0 (§6). |

### Items and consumables

| Change | Old | New | Notes |
|---|---|---|---|
| Consumable use | "Carry at most one of each." | Adds "you can use consumable items without limit (though you can only carry one of each at once)" | No use cap per turn or per game, and no error code for one. After each use you rebuy on spawn. |
| Shopping per turn | "Shop on your spawn or while dead" | Adds "On the spawn tiles, they may shop for items using gold an unlimited amount." | No purchase cap per turn. This was already true in 2.2.5 (up to 6+ purchases in one round in replays). |
| Gold bonuses add | "Treasure with Vesper Vale: 20% + 20% = 40%." | "Treasure with Vesper Vale: 33% + 20% = 53%." | Follows the Vesper Vale passive change; Treasure is still +20% for everyone. The heading "You should know:" became "Extra item rules"; the other bullets are identical. |
| Shard value per champion (derived) | — | Growth cut for Cassi, Issac, Prism, Stellar and Ren; Vendetta Strength and Marcella Focus up | The shard rule is unchanged: 30 gold adds the champion's growth. Power emblem (worth 6 shards): Stellar Focus +54 (was +60), Prism Focus +48 (was +60), Issac Strength +18 (was +28.5), Marcella Focus +90 (was +60), Vendetta Strength +36 (was +30). Health bought on spawn now heals less on Cassi, Issac and Prism. Per-champion values are in the Champions table. |
| Teleport crystal row reworded | "Range: 3 tiles, including diagonals. Channel for three of your turn ends, including this turn. Reserves a legal free destination, then flashes there at your next turn start ..." | "access otherwise unreachable areas by teleporting you 3 tiles, ignoring terrain. However, the teleport only activates after a channel of 3 turns." | Doc-only. "Ways to move" and "Channels" still state range 3 including diagonals and 3 owner turn ends: an enemy stun or death stops it, and it cannot be cancelled. The SDK still reserves the destination (`vision::teleport_tiles()`). |

The altar lock change is listed under Altar locks.

### Draft

| Change | Old | New | Notes |
|---|---|---|---|
| Heart of Ruin added | 11 choices (indices 0–10), 12 bodies | 12 choices: `heart_of_ruin` is draft index 11; 13 bodies | Indices 0–10 are unchanged, so stored lineups and draft-memory encodings stay valid. Opponents can pick it, and the random fill after a missed pick can draw it. The starter templates never pick it (§6). |
| Draft text rewritten | "First, Team A submits one pick, then Team B ... B selects without seeing A's pick ... revealed simultaneously"; "Note SDK draft-round indices start at 0."; the draft bot "can see ... what champions the opponent has drafted so far" | "both teams select champions simultaneously, revealing their picks as they go". The index note and the "separate instance" and opponent-picks sentences are gone. | No rule change: still one blind pick per team per round, revealed together. The SDK `draft` namespace is identical: `current_draft(team)` works for either side, and rounds are numbered from 0. |

### Map features

| Change | Old | New | Notes |
|---|---|---|---|
| "Map features" table | none; tile rules were spread over "Ways to move" and "Vision" | Five tile types: wall, hole, bush, altar, spawn tile | Consolidation. Consistent with the old rules except the teleport-crystal wall note. |
| Map size | not stated | "between 30*30 to 100*100" | Doc-only; old maps already ranged from about 30×30 to 98×97. Per-map buffers need up to 10,000 tiles. |
| Walls vs dashes | "Dashes use a legal path of up to 2 steps and may cross holes" | Wall: "cannot be moved onto nor can it be dashed over". Holes: "can be dashed over". | Makes explicit what "legal dash path" already implied. |
| Teleport crystal vs walls | "Landing cannot be on a wall, hole, altar, enemy spawn or occupied tile." | The wall row adds "TP Crystal can reach walls."; the landing sentence is kept | Ambiguous. The most consistent reading: the crystal passes over walls but cannot land on one (§6). |

### Champions (existing roster)

| Champion | Stat / kit | Old | New | Notes |
|---|---|---|---|---|
| Cassi | Health base | 700 | 600 | If either body dies, both die. |
| Cassi | Health growth | 71.25 | 65 | Health emblem gives +325 (was +356.25). |
| Cassi | Strength growth | 3.5 | 3 | |
| Cassi | Focus growth | 15 | 13 | With a Focus emblem: 135 Focus, slot 0 deals 270 (was 145 and 290). Base Focus 70 is unchanged. |
| Issac | Health growth | 95 | 80 | Health emblem gives +400 (was +475). Base 900 is unchanged. |
| Issac | Strength growth | 4.75 | 3 | 5 shards give +15 (was +23.75). |
| Ryth | Strength base | 50 | 45 | The passive (1% of bonus health) needs +500 HP to get back to 50. |
| Vesper Vale | Passive gold bonus | +20% (40% with Treasure) | +33% (53% with Treasure) | The passive tag reads "Extra gold from every gold gain". (2.0.0: 43% with Treasure.) |
| Vesper Vale | Strength base | 45 | 50 | Ryth and Vesper Vale swapped base Strength. |
| Prism | Passive | 0.2 Focus per carried gem | 1.5 Focus per carried gem | 7.5× stronger. With 50 gems: Focus 155, slot 0 deals 232.5 (was 135). The bonus is lost on tribute or death. |
| Prism | Health growth | 75 | 60 | |
| Prism | Strength growth | 3.5 | 2.5 | |
| Prism | Focus growth | 10 | 8 | One 30-gold Focus shard now equals 8 carried gems. |
| Stellar | Strength base | 35 | 30 | |
| Stellar | Focus base | 100 | 85 | Slot 0: 200 → 170. Slot 1: 140 → 119. |
| Stellar | Focus growth | 10 | 9 | With Power Focus, slot 0 deals 278 (was 320). |
| Vendetta | Strength growth | 5 | 6 | With Power Strength, 106 per hit (was 100). This is Vendetta's only change. |
| Marcella | Passive | "Immune to stuns" | "Immune to stuns. Gains 2 gold per gem tributed." | Paid only for gems she tributes herself: 2 × her bag when the tribute completes. The engine applies Treasure (2.4 per gem) and counts this as earned gold for the tiebreak. Her summary line now reads "A stun-immune melee champion who earns gold from tributes ...". |
| Marcella | Focus base | 50 | 60 | Slot 1: 100 → 120. |
| Marcella | Focus growth | 10 | 15 | With Power Focus, slot 1 deals 300 (was 220). |
| Tavi | Slot 1 (damage and stun) | 2.2 × Focus + 1-round stun | 1.4 × Focus + 1-round stun | 220 → 140 at base. Range 4, enemy or camp, excludes walking and cooldown 8 are unchanged. |
| Tavi | Strength base | 35 | 45 | Over 8 stationary turns at base (9 hits plus the nuke): 535 → 545 total damage. |
| Willow | Strength base | 45 | 55 | Now the highest base Strength among ranged champions. |
| Willow | Focus base | 105 | 120 | Heal: 315 → 360. |
| Ren | Strength base | 40 | 35 | |
| Ren | Focus growth | 10 | 9 | At base, slot 0 (125) and retaliation (20) are unchanged. With 5 Focus shards: 181.25 and 29 (was 187.5 and 30). |
| Varg | Strength base | 50 | 40 | Splash equals Strength, so a base hit is 40 + 40 splash (was 50 + 50). |

### New champion: Heart of Ruin

| Item | Value | Notes |
|---|---|---|
| Identity | Melee bruiser: "damage grows as health falls, with a self-shield and a stunning dash landing" | Draft index 11, champion type 12. |
| Attack | Melee, basic attack range 1 | Can walk, dash and basic attack in the same turn. |
| Health | 1000 base, +100 per shard | Same as Varg. |
| Strength | 40 base, +5 per shard | Same as Varg, without splash. A basic hit deals 40–60 depending on missing health. |
| Focus | 100 base, +15 per shard | Highest Focus growth, tied with Marcella. With Power Focus: 190. |
| Passive | Up to +50% to all damage it deals, linear in missing health: damage × (1 + 0.5 × (1 − HP / max HP)). 0% at full health, 25% at half, about 50% near zero. | Applies to basic attacks and the dash landing. Shields do not count as health. |
| Slot 0: Self-shield | 1.5 × Focus shield (150 at base) lasting five turns. Self, walking compatible, cooldown 8. | Varg's shield is 2.5 × Focus and sits in slot 1, so don't assume a fixed shield slot. Damage absorbed by the shield does not lower health, so it does not raise the passive. |
| Slot 1: Dash | Dash to a tile within 2 along a legal dash path. On arrival: 1.75 × Focus (175 at base, scaled by the passive) to enemies and camps within Chebyshev radius 1 of the landing tile, plus a 1-turn stun. Ground · 2, walking compatible, cooldown 8. | The only dash with a landing effect. Reach is about 4 tiles per turn (walk 1 + dash 2 + radius 1). The stun interrupts recall, tribute and teleport channels; Marcella is immune. Landing effects happen only after a successful dash and never hit allies. With 5 Focus shards: 306.25, about 459 near zero HP. (2.0.0: 1.5 × Focus, 150 at base; Focus growth 10, so with 5 Focus shards 225, about 337 near zero HP.) |

### SDK / API (3.0.1 vs 2.2.5)

| Change | Old | New | Notes |
|---|---|---|---|
| `champion::move_towards(target)` | Returned false at once if the target tile was blocked | Treats the target as free for pathfinding; the final step into a known-blocked target throws | §5. |
| `ability_dash` metadata | `range` only | `range`, `radius`, `modifier`, `duration` (landing damage and stun) | Expected to be non-zero only for Heart of Ruin. Vendetta's engine row reads 0/0/0. §5. |
| `ability::damage_amount()` doc | "Query damage before absorption/health limits; includes caster items and passives." | "Query Focus-scaled damage, including dash landing damage and caster outgoing bonuses such as Heart of Ruin's passive. Excludes target-dependent modifiers, shields and health limits." | Same host call. §5. |
| `camp_type::golem = 5`, `camp::is_golem()` | camp_type 0–4 | Adds golem = 5 and `to_string` "golem". Python `CampType.GOLEM`, Rust `CampType::Golem`. | Tables indexed by camp type need 6 entries. |
| `vision::awake_camp_tiles()` and `asleep_camp_tiles()` (+ `_into`) | Only per-camp `state()`, `is_awake()`, `is_asleep()` | Bitboards of visible awake and visible asleep camps | Same information, one call. |
| `vision::in_vision(vec2)` | none | Single-tile test of own vision plus own ward | New `is_visible` import. |
| `ward::owner()` | A ward had position, team and remaining_time | Adds the owning champion | `operator==` now also compares owner. |
| Heart of Ruin enums | `champion_draft` 0–10, `champion_type` 0–11, `champion_designs` has 12 entries | `heart_of_ruin` = draft 11 / type 12; `champion_designs` has 13 entries; `to_string` supports it | |
| `passive_type::missing_health_damage = 10` | Last tag was `stun_immunity = 8` | Adds 10 | Value 9 is skipped: the 3.0.1 engine-contract test binds it to a reserved legacy "omnivamp" passive. |
| `constants::passive_abilities` | prism 0.2, vesper 20, varg 1.0, ryth 0.01, ren 0.2 | prism 1.5 (corrected 27 Oct), vesper 33; new `marcella_tribute_gold_per_gem = 2` and `heart_of_ruin_missing_health_damage_max_bonus = 0.5`; varg, ryth and ren unchanged | Python and Rust have identical values. |
| Enum doc comments | Marcella: "Cannot be stunned (Marcella)." | "Cannot be stunned, and gains gold per gem tributed (Marcella)."; Marcella and Heart of Ruin draft/type comments updated | Doc-only. Tribute gold has no tag of its own. |
| Raw ABI (`imports.h`) | Dash payload was `float dash_range`; `ward_info` had no owner | Dash payload is a struct `{range, radius, modifier, duration}`; `ward_info.owner` added (20 → 24 bytes); new imports `board_awake_camp_occupancy`, `board_asleep_camp_occupancy`, `is_visible` | ABI break: rebuild every bot. |
| Starter templates | Draft loop over indices 0–10 "Released champions only", which covered every choice in 2.2.5 | Byte-identical, so it now skips `heart_of_ruin`. C++ uses `i < 11`, Python `range(11)`, Rust `0..11`. OCaml uses `Champion_draft.all` and can pick it. | The 2.2.5 engine-contract test called Heart of Ruin "unreleased and hidden from the SDK"; the 3.0.1 test does not (§6). |
| Stellar enum comment (older than the patch) | "single-target damage with a stun" | unchanged | Stale: Stellar has no stun in either handbook. |
| `cambc::champions()` doc (clarification) | The old Python doc said "Visible champions of a team" | C++ in both 2.2.5 and 3.0.1: "including champions outside vision" | Not a behaviour change for C++. `vision::champions(team)` returns only visible champions. |
| Unchanged | | `Game_Settings` layout (24 bot-facing fields; Rust record 120 bytes); item and consumable docs; Wolf and Elk docs; error codes; `draft` namespace | The kill_gold, altar_lock_hits and ward_cooldown changes reach bots only through runtime `constants::*`. The Rust test host's mock values (e.g. ward_cooldown 4) are not real values. |

## 4. The current game (new rules) at a glance

> **Version note (27 Oct):** §2-§4 describe the 3.0.1 docs (engine 1.0.0). Engine 1.0.2/1.0.3 and 2.0.0 changed several numbers; current values: §12 and /data/USER/cambc400x/designs84_v2_0_0.json. On 27 Oct these §4 parts were updated to 2.0.0: the champion and kit tables, the item passives and gold bonuses, the fuel lines and the one-cast cluster kills.

### Objective and end
- The first team to have tributed 1,000 gems wins immediately.
- Otherwise the game ends after round 2,000 (a local runner may stop earlier). The winner is decided in this order:
  1. most tributed gems;
  2. most lifetime gold earned;
  3. most champion kills;
  4. Team B, the side that acted second in round 1.
- Gold earned counts every gold gain (captures, kills, Marcella's tribute gold), not unspent gold. Tavi's sale refunds are not earned gold.
- Carried gems never score. Tributed gems are permanent.

### Draft
- Each team drafts 3–5 champions, depending on the map (`draft::team_size()`).
- In each draft round both teams pick one champion blind and at the same time; both picks become public after the round. Rounds are numbered from 0.
- No duplicates within a team. Picking a champion the opponent has is allowed. Cassi & Issac is one pick that creates two bodies.
- 12 choices, by draft index: Ryth 0, Vesper Vale 1, Vendetta 2, Cassi & Issac 3, Stellar 4, Prism 5, Marcella 6, Willow 7, Ren 8, Varg 9, Tavi 10, Heart of Ruin 11.
- The draft bot is a separate instance:
  - It sees the whole map and the picks so far (`draft::current_draft(team::ally)` and `(team::enemy)`).
  - It gets 100× fuel on its first turn (9.98M measured on 27 Oct; 10× until cambc 3.0.5).
  - It writes the 1,024-byte draft memory.
- If the draft bot yields, runs out of fuel or crashes without picking, the remaining picks are random.
- Champions start on their own spawn tiles at full health.

### Round and turn order
1. **Round start:** camp respawns → spell and ward updates → captures → camp actions (each awake camp attacks once).
2. **Champion turns:**
   - Teams alternate, and the team that starts swaps every round.
   - Within a team, higher priority acts first, then draft order. `set_priority` takes effect the next round and persists.
   - Dead champions still get a turn, used only for shopping.
3. **Each turn start:** zero timers resolve in this order: respawn, ward recharge, buff and shield expiry, then channels (recall arrival, tribute completion, teleport flash).
4. **Each turn end:** the champion's timers decrement, including on the turn a channel starts. Then spawn healing applies.
- Consequences: a capture can add gems before a tribute completes, and camps attack before your next turn.

### Actions per turn
- Each turn allows:
  - one ordinary move: one tile in any of 8 directions;
  - one basic attack: Strength damage to a visible target within Chebyshev range (melee 1, ranged 3);
  - one successful ability cast, shared by both slots. Each slot has an 8-turn-end cooldown.
- Melee champions can move and attack in the same turn.
- For ranged champions, moving and basic attacking each use up the other's allowance. An attack reset can restore the attack allowance.
- An "excludes walking" ability and a walk cannot share a turn, in either order. Every range-4 damaging spell excludes walking; the errors are 126 `invalid_action_spell_cast_already_moved` and 127 `invalid_action_move_exclusive_spell_cast`.
- Walk-compatible abilities: attack resets, dashes, shields, Cassi's stun, Willow's heal.
- Other actions in a turn:
  - place the ward, if its charge is ready;
  - shop on own spawn tiles or while dead, with no limit per turn (Tavi buys shards anywhere);
  - use consumables, with no limit (but you can carry at most one of each);
  - start and cancel a recall (once each per turn);
  - start and cancel a tribute (once each per turn).
- Starting a channel blocks other actions until it finishes or is cancelled. Teleport channels cannot be cancelled.
- **Hidden occupants:** a move, dash or teleport onto an otherwise legal tile that holds an unseen unit returns `false`. The tile is revealed for the rest of the round, and nothing is consumed (allowance, cooldown or consumable). A destination already known to be blocked throws `cambc::error`.

### Map
- A grid from 30×30 to 100×100. All distances are Chebyshev: a diagonal step counts as 1.

| Tile | Walkable | Sight | Other |
|---|---|---|---|
| Wall | no | blocks | Cannot be dashed over. A teleport crystal ignores it in between but cannot land on it (§6). |
| Hole | no | does not block | Can be dashed over. |
| Bush | yes | Blocks sight from outside. From inside you see across your whole connected bush cluster and out of it, but not into other bushes. | Monsters see through bushes. |
| Altar | no | — | Tribute from within Chebyshev 1. |
| Spawn tile | own team only | — | Heals at turn end (to full; `spawn_healing` 1.0). Shopping happens here. |

- Movement:
  - A walk is 1 tile.
  - A dash is up to 2 steps along a legal path; it can cross holes but not walls.
  - A teleport crystal reaches up to 3 tiles (diagonals included) and ignores terrain in between.
- Nothing lands on a wall, hole, altar, enemy spawn tile or occupied tile. Teleport reservations also block. Use the SDK's movement masks, which account for visible units.

### Camps

| Monster | Health | Strength (damage per hit) | Attack range | Gold | Gems | Respawn (rounds) | Gems per 1,000 HP |
|---|---|---|---|---|---|---|---|
| Wolf | 1,350 | 20 | 3 | 40 | 4 | 40 | 3.0 |
| Elk | 2,400 | 60 | 4 | 90 | 15 | 60 | 6.25 |
| Golem | 5,000 | 120 | 4 | 160 | 36 | 80 | 7.2 |
| Gem cluster | 120 | 0 | never attacks (engine design range 3) | 0 | 7 | 50 | 58 |
| Gold cluster | 120 | 0 | never attacks (engine design range 3) | 20 | 0 | 50 | — |
| Monolith | 20,000 | 200 | 5 | 300 | 200 | 150 | 10 |

- **Groups:**
  - A group is a set of cardinally connected monsters. Its reward is the sum of its members' rewards.
  - Table values are base values; gold bonuses apply on top.
- **Behaviour:**
  - Monsters have vision 8, see through bushes and never move or chase.
  - A camp sleeps until damaged. Damage to any member wakes the whole group.
  - Once per round, at round start, each awake camp attacks the nearest champion of either team (by Chebyshev distance), but only if that champion is within its attack range. The hit deals its Strength, reduced by Jungle (−30%) and Durability (−10%).
  - Strength-0 clusters never attack.
- **Sleep:** each camp counts separately. After 2 consecutive rounds with no champion within its attack range, it falls asleep. A champion standing in range keeps it awake without hitting it. A new intro sentence in the handbook contradicts this (§6).
- **Reach comparison:**
  - Champion basic attacks reach 3, spells 4. Radius-1 ground spells cast at range 4 reach 5 (Ryth 0, Prism 1, Stellar 1).
  - Spells outrange wolves.
  - Only radius-1 ground spells outrange elks and golems.
  - Nothing outranges a Monolith.
- **One-cast cluster kills:** spells that deal at least 120 at base kill a cluster in one cast: Cassi 0 (200), Stellar 0 (140), Prism 0 (120), Marcella 1 (120), Tavi 1 (176), Heart of Ruin 1 (150). Ren 0 deals 110, Ryth 0 100, Stellar 1 98: no one-cast kill at base.

### Capture and respawn
- Once every member of a group is dead, occupy at least one of its spawn tiles (the region) with no enemy on the region.
- The capture timer:
  - It starts at 5 rounds at the next capture phase (round start) and counts down at later capture phases.
  - It resets if the region becomes empty or an enemy enters it.
  - More allies do not speed it up.
- When it completes:
  - The gold and gems are split evenly among the allies on the region; the lowest ID gets any integer remainder.
  - Champions off the region get nothing.
- Respawn:
  - The respawn timer starts only at capture; a group that is cleared but never captured never respawns.
  - The length is the longest member respawn (a group with a Golem: 80; with a Monolith: 150), and it ticks once per round.
  - All members respawn together, at full health, on their original tiles. Any occupied spawn tile delays the whole group.
- SDK group states: `camp_group_alive` → `camp_group_reward_available` → `camp_group_respawning{timer}`.

### Gems, tribute and altar locks
- **Carried gems:**
  - Come from captures and from kills: the killer takes the victim's whole bag.
  - Are lost to the killer on death, or destroyed if a camp kills you.
  - Never score.
- **Tribute:**
  - Stand within Chebyshev 1 of an altar with at least 1 gem.
  - The channel lasts max(1, ceil(gems at start / 10)) owner turn ends, counting the starting turn: 1–10 gems take 1 tick, 11–20 take 2.
  - It completes at your next turn start after the timer reaches 0 and tributes your whole current bag, including gems gained since it started.
  - Damage does not interrupt it. A stun, death, or an enemy altar lock placed there does.
- **Altar lock** (consumable, 10 gold, carry one):
  - Placed on an altar within 2 tiles. It blocks only the opposing team's tributes at that altar, and placing it cancels existing tribute channels there.
  - Removed by 5 basic attacks. An enemy's attempt to tribute at a locked altar becomes an attack on the lock.
  - `altar_lock::hits_remaining()` reports the hits left.

### Combat
- **Basic attack:** deals Strength before modifiers. It needs a visible target within Chebyshev range: melee 1, ranged 3.
- **Abilities:**
  - Effect = Focus × the ability's multiplier.
  - Two slots, at most one successful cast per turn, and an 8-owner-turn-end cooldown per slot.
  - Unit spells need a valid visible target. Ground spells hit an area (radius around the chosen tile). Self spells use self-cast.
- **Stuns:** every stun lasts 1 round or turn; Marcella is immune.
- **What interrupts channels:**
  - Recall: damage, stun or death.
  - Tribute: stun, death, or a newly placed enemy lock.
  - Teleport: an enemy stun or death.
- **Damage modifiers and effects:**
  - Monster emblem: +15% (2.0.0) damage to camps.
  - Durability: −10% incoming damage (live: 0.9× on 618/618 hits on holders).
  - Jungle: −30% damage from camps.
  - Heart of Ruin's passive: up to +50%.
  - Shields absorb damage before health: Varg 2.5 × Focus, Heart of Ruin 1.5 × Focus, both lasting 5 turns.
  - Ren retaliates for 0.2 × Focus whenever he is damaged.
  - Varg's basic attacks splash damage equal to his Strength within radius 1 of the target.
  - The order in which modifiers stack is not documented.
- **Vendetta:** any credited kill, including a camp monster, resets all her cooldowns.

### Items and gold
- **Gold sources:**
  - Capture gold, split among the allies on the region.
  - Kill gold: 100 base to the killer; assists get none.
  - Marcella's tributes: 2 gold per gem.
  - No passive income: the engine's `passive_gold` is 0.
- **Gold bonuses:** Vesper Vale +33% and Treasure +10% add up to 43% (2.0.0); Hunter's +50 is added before both.
- **Shopping:** on own spawn tiles or while dead, with no limit per turn.
  - Tavi buys shards anywhere, but consumables only on spawn or while dead.
  - Only Tavi can sell: on spawn, for full value. Refunds are not earned gold.
- **Shards:** 30 gold each; a shard adds the champion's growth for its stat (Strength, Health or Focus).
  - Five matching shards combine automatically into an emblem (150 gold total). Only a completed emblem gives the family passive.
  - Stats from every shard stack. A second emblem of the same family adds no second passive.
  - Health bought on spawn heals by the amount gained; Tavi's purchases away from spawn don't heal.

| Family | Counts as | Passive |
|---|---|---|
| Monster | 5 shards of the chosen stat | +15% (2.0.0) damage to camps |
| Power | 6 shards of the chosen stat | none |
| Durability | 5 | −10% incoming damage |
| Treasure | 5 | +10% gold gained |
| Jungle | 5 | −30% damage from camps |
| Home | 5 | Recall takes 3 turn ends instead of 5 |
| Bruiser | 5 of the chosen stat + 1 of each other stat | none |

- **New families in 2.0.0:** Tribute, Capture, Prospector, Hunter, Skirmish, Greed and Collectors; see §12.
- **Consumables:** 10 gold each, bought on spawn or while dead, at most one of each carried, no limit on use. SDK: `consumable_type::tp_crystal`, `consumable_type::altar_lock`.
  - **Altar lock:** see above.
  - **Teleport crystal:**
    - Reserves a free tile within 3 (diagonals included), ignoring terrain in between.
    - Channels for 3 owner turn ends, counting the use turn, then flashes at the next turn start.
    - Damage doesn't stop it; an enemy stun or death does. It cannot be cancelled.

### Vision and wards
- **Champion vision:** each champion sees up to 8 tiles, using symmetric shadowcasting (Albert Ford's algorithm).
  - Walls and bushes block sight; holes don't.
  - The connected bush cluster a champion stands in is transparent to it.
- **Vision is per champion.** Allies' views and allies' wards are not shared. The 8-byte shared memory is the only channel between them.
- **Ward:**
  - Each champion has one free ward. It is placed within Chebyshev 2 of the champion (`ward_placement_tiles()`) and has vision radius 6.
  - Wards are permanent: they don't expire and can't be damaged. Only one is active; placing a new ward replaces the old one.
  - The charge recharges over 10 owner turn ends, so a ward can be placed or moved once per 10 own turns (`champion::ward_cooldown()`; error 62 `invalid_action_place_ward_no_charges`).
- A tile revealed by a hidden-occupant collision stays revealed for the rest of the round (`tile_reveal_rounds` 1).

### Death, recall and respawn
- **On death:**
  - The killer takes all carried gems plus 100 base gold. Assists get nothing.
  - If a camp makes the kill, the gems are destroyed.
  - Cassi & Issac: if either dies, both die. The killer gets both bags and one 100-gold reward.
- **Respawn:**
  - After 60 owner turn-end ticks, at the next turn start once a spawn tile is free.
  - The champion returns at full health with ability cooldowns reset.
  - Dead champions can shop on their turns.
- **Recall:**
  - A channel of 5 owner turn ends (3 with Home), counting the starting turn. The champion arrives at the next turn start after the timer reaches 0.
  - Damage, a stun or death interrupts it. Carried gems are kept.
  - To heal to full, stay on spawn until the end of the arrival turn.
  - One start and one cancel per turn.

### Fuel
- C++ and Rust: 100,000 fuel per turn. OCaml gets 5× that, Python 25×.
- The first draft turn gets 100× fuel, and each champion's first play turn gets 2×.
- Unused fuel doesn't carry over. A bot that runs out is suspended, and resumes from the same point next round.

### Memory
- One bot instance runs per champion.
- Team shared memory: 8 bytes, readable and writable all match, hidden from the opponent.
- Draft memory: 1,024 bytes, written during the draft and read-only for champions during the match.

### Champions

Shared by every champion: vision 8; walk 1; both slots have an 8-owner-turn-end cooldown; one cast per turn. Growth is what one 30-gold shard of that stat adds.

| Champion | Attack | Health base / growth | Strength base / growth | Focus base / growth | Key values at base |
|---|---|---|---|---|---|
| Cassi | ranged 3 | 600 / 65 | 30 / 3 | 100 / 13 | slot 0: 200 |
| Issac | melee 1 | 900 / 80 | 45 / 3 | 100 / 10 | — |
| Ryth | melee 1 | 1200 / 100 | 45 / 4.5 | 100 / 10 | slot 0: 100 area |
| Vesper Vale | ranged 3 | 1000 / 100 | 45 / 5 | 100 / 10 | — |
| Prism | ranged 3 | 700 / 65 | 35 / 2.5 | 80 / 8, +1.5 per carried gem | slot 0: 120; slot 1: 80 area |
| Stellar | ranged 3 | 650 / 65 | 30 / 3.5 | 70 / 8.5 | slot 0: 140; slot 1: 98 area |
| Vendetta | melee 1 | 1000 / 100 | 70 / 6 | 100 / 10 | — |
| Marcella | melee 1 | 1200 / 100 | 45 / 4.5 | 60 / 14 | slot 1: 120 |
| Tavi | ranged 3 | 900 / 75 | 45 / 5 | 110 / 10 | slot 1: 176 |
| Willow | ranged 3 | 700 / 50 | 55 / 3 | 140 / 5 | heal: 420 |
| Ren | melee 1 | 900 / 100 | 35 / 5 | 100 / 9 | slot 0: 110; retaliation 20 |
| Varg | melee 1 | 1000 / 100 | 45 / 5 | 100 / 10 | splash 45; shield 250 |
| Heart of Ruin | melee 1 | 1000 / 100 | 30 / 3 | 100 / 10 | shield 150; dash 150 (up to ×1.5) |

Kits. Every cooldown is 8 owner turn ends. "W" means walking compatible; "X" means excludes walking. F = Focus.

| Champion | Passive | Slot 0 | Slot 1 |
|---|---|---|---|
| Cassi | Linked to Issac: if either dies, both die; both bags go to the killer, who gets one kill reward | Single-target damage 2 × F · enemy or camp · range 4 · X | Stun for 1 round, no damage · enemy or camp · 4 · W |
| Issac | Linked to Cassi (as above) | Attack reset · self · W | Dash up to 2 steps (diagonals allowed), no landing effect · ground 2 · W |
| Ryth | Gains Strength equal to 1% of bonus health | Area stun: 1 × F damage + 1-round stun in radius 1 · ground 4 · X | Attack reset · self · W |
| Vesper Vale | +33% gold ("from every gold gain"); 43% with Treasure | Attack reset · self · W | Dash up to 2 · ground 2 · W |
| Prism | +1.5 Focus per carried gem; the bonus goes when the gems are tributed or lost | 1.5 × F damage + 1-round stun · enemy or camp · 4 · X | Area 1 × F in radius 1 · ground 4 · X |
| Stellar | none | Single-target 2 × F · enemy or camp · 4 · X | Area 1.4 × F in radius 1 · ground 4 · X |
| Vendetta | Any credited kill (champion or camp monster) resets all her ability cooldowns | Attack reset · self · W | Dash up to 2 · ground 2 · W |
| Marcella | Immune to stuns; +2 gold per gem she tributes | Enhanced attack reset: resets the basic attack, and the next (enhanced) attack stuns for 1 round · self · W | Single-target 2 × F · enemy or camp · 4 · X |
| Tavi | Buys shards anywhere (consumables only on spawn or while dead); sells on spawn for full value; Health bought away from spawn doesn't heal | Attack reset · self · W | 1.6 × F damage + 1-round stun · enemy or camp · 4 · X |
| Willow | none | Ally heal: restores up to 3 × F to another allied champion · ally · 4 · W | Attack reset · self · W |
| Ren | Retaliates for 0.2 × F against an attacker whenever damaged, even as he dies | 1.1 × F damage + 1-round stun · enemy or camp · 4 · X | Dash up to 2 · ground 2 · W |
| Varg | Basic attacks splash damage equal to Strength onto other enemies and camps within radius 1 of the target; the primary target is not hit twice | Attack reset · self · W | Self-shield 2.5 × F lasting 5 turns · self · W |
| Heart of Ruin | All damage × (1 + 0.5 × missing-health fraction); shields are not health | Self-shield 1.5 × F lasting 5 turns · self · W | Dash up to 2; on landing, 1.5 × F + 1-turn stun to enemies and camps within radius 1 · ground 2 · W |

## 5. SDK / API changes in 3.0.1 (bot-facing)

### Build and ABI
- **The host ABI changed:**
  - `ward_info` gained `owner` and grew from 20 to 24 bytes.
  - The dash payload became a struct. The union size is unchanged, and `ability_props` is still 36 bytes.
  - There are three new imports: `board_awake_camp_occupancy`, `board_asleep_camp_occupancy` and `is_visible`.

  Rebuild every bot against the 3.0.1 headers. The repo's copies are still 2.2.5 (§1).
- **Everything else in the C++ API is the same as 2.2.5:**
  - the `draft` namespace, action methods and error codes;
  - item and consumable types;
  - map, vision, bitboard and distance-field helpers;
  - the `Game_Settings` layout and the ability property fields (`max_cooldown`, `valid_targets`, `exclusive_with_movement`).

### New enum values
- `champion_draft::heart_of_ruin = 11` and `champion_type::heart_of_ruin = 12`.
  - `champion_designs` is now `std::array<champion, 13>`, indexed by `champion_type`.
  - Type indices: ryth 0, vesper_vale 1, vendetta 2, cassi 3, issac 4, stellar 5, prism 6, marcella 7, willow 8, ren 9, varg 10, tavi 11, heart_of_ruin 12.
- `camp_type::golem = 5`. Full list: wolf 0, elk 1, gem_cluster 2, gold_cluster 3, monolith 4, golem 5.
- `passive_type::missing_health_damage = 10`. Value 9 is reserved, so arrays over this enum need 11 entries.
- `to_string` handles all the new values.
- Other languages: Python has `ChampionDraft.HEART_OF_RUIN = 11` and `CampType.GOLEM = 5`; Rust has `CampType::Golem = 5`; OCaml's `Champion_draft.all` includes `Heart_of_ruin`.

### New functions
```cpp
namespace cambc::vision {
  bool in_vision(vec2 position);       // own vision + own ward, occupied or not; hidden -> false; off-map throws api_bad_position
  bitboard awake_camp_tiles();         // visible awake camps, dead excluded; + awake_camp_tiles_into(bitboard&)
  bitboard asleep_camp_tiles();        // visible asleep camps, dead excluded; + asleep_camp_tiles_into(bitboard&)
}
cambc::champion cambc::ward::owner() const;  // champion that placed the ward, captured when the ward was visible;
                                             // the handle stays valid while the owner is hidden, live queries need vision
bool cambc::camp::is_golem() const noexcept;
```
- `in_vision`, the camp bitboards and `owner()` work only for champion bots during play, not in the draft.
- Awake clusters appear in `awake_camp_tiles()` even though they never attack.

### Changed metadata
```cpp
struct ability_dash : ability_properties {  // ability_kind::dash; read with ab.get<cambc::ability_dash>()
  float range;            // max travel; diagonals count 1; needs a legal dash path to a *different* tile
  float radius;           // NEW: Chebyshev landing radius for damage and stun (1 = all 8 neighbours)
  float modifier;         // NEW: landing damage = caster Focus * modifier, before bonuses and mitigation; 0 = none
  std::int32_t duration;  // NEW: landing stun in turns (not travel time); 0 = none
};
```
- Landing effects apply only after a successful dash, and only to enemies and camps.
- Expected values: Heart of Ruin slot 1 has range 2, radius 1, modifier 1.75, duration 1. Issac, Vesper Vale, Vendetta and Ren should read 0/0/0; Vendetta's engine row is confirmed.
- `float ability::damage_amount() const` returns Focus-scaled damage. It includes dash landing damage and caster outgoing bonuses such as Heart of Ruin's passive at its current health. It excludes target-dependent modifiers (for example Monster's +10% against camps, which you must add yourself), shields and health caps.
- `float ability::damage_amount(const champion& target) const` is unchanged: it predicts health lost after mitigation and shields, capped at current health, and only takes a visible champion.

### Behaviour change: `bool champion::move_towards(vec2 target) const`
- **2.2.5:** returned `false` immediately if the target tile was blocked (wall, hole, altar, enemy spawn, visible champion or camp, teleport reservation).
- **3.0.1:** the target is treated as free for pathfinding, while every other blocker is still avoided.
  - Once the champion is adjacent, the chosen step is the target itself. If the target is known to be blocked (camp, altar, wall, visible unit), `move_absolute` throws `cambc::error` (`invalid_action_move_bad_destination`).
  - It returns `false` when the champion is already there, cannot move, has no route, or reveals a hidden obstruction.
  - Callers must stop at the range they want, or catch the error. The API doc puts it this way: "Path towards a target even when its tile is blocked. Stop at the desired range: the engine still rejects landing on a known blocked tile."

### Compile-time constants (`cambc::constants::passive_abilities`)
| Constant | 3.0.1 | 2.2.5 |
|---|---|---|
| `prism_focus_per_gem` | 1.5f | 0.2f |
| `vesper_vale_bonus_gold_percent` | 33 | 20 |
| `marcella_tribute_gold_per_gem` | 2 (new) | — |
| `heart_of_ruin_missing_health_damage_max_bonus` | 0.5f (new) | — |
| `varg_splash_radius` / `ryth_health_strength_ratio` / `ren_retaliation_focus_ratio` | 1.0f / 0.01f / 0.2f | same |

Marcella's tribute gold sits under `passive_type::stun_immunity`; there is no separate tag for it. The Python and Rust values are identical.

### Runtime constants (`cambc::constants::*`, read from the engine; expected values)
| Setting | Expected | Source |
|---|---|---|
| `capture_time` | 5 | handbook, engine |
| `camp_sleep_time` | 2 (rounds with no champion in range) | handbook bullet, engine |
| `respawn_time` | 60 | handbook, engine |
| `recall_time` | 5 (3 with Home) | handbook, engine |
| `submit_gem_duration_multiplier` / `_base_duration` / `_minimum_duration` / `submit_gems_range` | 0.1 / 0 / 1 / 1 | handbook, engine |
| `max_rounds` / `winning_gems` | 2000 / 1000 | handbook, engine |
| `kill_gold` | 100 | handbook, engine |
| `assist_gold` | 0 | handbook, engine |
| `passive_gold` | 0 (no round income) | engine |
| `spawn_healing` | 1.0 (fraction of max health; full heal) | engine |
| `active_wards` | 1 | engine |
| `shared_memory_bytes` / `draft_memory_bytes` | 8 / 1024 | handbook, engine |
| `tile_reveal_rounds` | 1 | engine |
| `ward_cooldown` | 10 | handbook, engine |
| `ward_lifetime` | −1 (never expires) | engine |
| `ward_vision_radius` / `ward_placement_radius` | 6 / 2 | handbook, engine |
| `altar_lock_hits` | 5 | handbook, engine |
| `tp_crystal_time` | 3 | handbook, engine |

"Engine" means the verification pass's read of the 3.0.1 binary (§1).

## 6. Unclear or inconsistent

1. **What puts a camp to sleep.** (Resolved by engine runs: the in-range rule holds, §9.)
   - The new intro says a woken monster attacks "until it either dies or does not take damage for 2 turns".
   - Three sources say otherwise: the handbook's own bullet ("two rounds without an in-range champion let it sleep"), the SDK `camp_sleep_time` doc, and the engine's camp step (instruction-identical to 2.2.5). In all three, the counter resets every round a champion is within the camp's attack range, and damage plays no part in falling asleep.
   - Details: a camp woken from outside its range can stay awake one extra round. Damage wakes the whole group, not just "it".
   - To measure: wake a camp, then stand inside its range without attacking.
2. **Cluster range.**
   - The handbook table says 0; the engine design says 3 (with Strength 0), and `camp::attack_range()` returns 3 for clusters.
   - Clusters never attack, but an awake cluster stays awake, and stays in `awake_camp_tiles()`, while any champion is within 3.
   - For danger maps, key on Strength > 0, not on `attack_range()`.
3. **Teleport crystal and walls.**
   - The Map features table says "TP Crystal can reach walls."; the unchanged rule says "Landing cannot be on a wall, hole, altar, enemy spawn or occupied tile."
   - Most consistent reading: the crystal passes over walls but cannot land on one. Error 82 `invalid_action_champion_teleport_bad_destination` is unchanged.
   - To measure: test before relying on any teleport near walls.
4. **Ranged move plus attack.** (Resolved by engine runs, §9.)
   - The new text says "you may NOT move, and basic attack on the same turn", and also that "Attack-reset abilities can restore the attack allowance."
   - In 2.2.5, walk → reset → attack worked, and the reset's SDK doc is unchanged. Re-test on 3.0.1.
   - "The same rule applies for damaging abilities that are ranged" matches the per-ability excludes-walking tags. It does not forbid a basic attack and a spell in the same turn; the error codes are unchanged.
5. **Can Heart of Ruin be drafted? Yes (resolved).** Ranked platform games have included Heart of Ruin picks since the patch went live (2026-10-20 03:00 UTC). The notes below explain why it looked doubtful.
   - The handbook and all four 3.0.1 SDKs include it, with no "unreleased" note.
   - The C++, Python and Rust templates still loop over indices 0–10 with "Released champions only". The loop dates from 2.2.5, when Heart of Ruin existed but was hidden.
   - To measure: confirm that `draft::pick(champion_draft::heart_of_ruin)` is accepted, locally and on the platform.
6. **Ward line of sight.**
   - The new handbook no longer says ward vision follows line of sight, but nothing says it doesn't, and `ward::visible_tiles_from()` is unchanged.
   - Assume radius-6 shadowcasting; verify with `vision::in_vision`.
7. **Assist gold (resolved: 0 in the engine).**
   - The handbook says "assists award no gold"; the SDK describes `assist_gold` as "Base gold pool split among champions credited with an assist". Both texts predate the patch.
   - Read the runtime value.
8. **`passive_gold` (resolved: 0).** The engine has a per-round upkeep gold setting ("Base gold granted to each champion during round upkeep"), and its value is 0, so there is no passive income.
9. **Which gold the bonuses apply to, and rounding.**
   - Vesper Vale's passive tag says "Extra gold from every gold gain", so she presumably gets 133 per kill (153 with Treasure). Not verified in the engine.
   - The engine applies Treasure to Marcella's tribute gold (2.4 per gem); her passive has no bonus hook of its own.
   - How fractional gold rounds (e.g. 33% of 40 = 13.2) is not documented. Measure the gold deltas.
10. **Draft wording.** The new draft text dropped "and what champions the opponent has drafted so far". The SDK still provides `draft::current_draft(team::enemy)`. Picks are blind within a round and visible after it.
11. **Simplified restatements:** use the exact rules instead.
    - Tribute "divided by 10" means max(1, ceil(gems / 10)).
    - Monster "strength (damage dealt per turn)" means camps act once per round, at round start.
    - Teleport crystal "channel of 3 turns" means 3 owner turn ends, counting the use turn.
    - Ward recharge "10 owner turn ends" matches the SDK's "rounds", since each champion has one turn per round. Whether timers tick while a champion is dead is not stated; dead champions do still take turns.
12. **Altar locks (older than the patch).**
    - "Placing it cancels existing tribute channels at that altar" sits next to "cancelling enemy channels". It is unclear whether the owner's own team's channels are also cancelled.
    - The handbook says a tribute attempt at a locked altar becomes an attack, but the SDK also has error 125 `invalid_action_submit_gems_altar_locked` ("The altar is locked by the enemy"). When each one applies is undocumented.
13. **Heart of Ruin details to confirm:**
    - dash metadata (expected range 2, radius 1, modifier 1.75, duration 1);
    - shield metadata (expected 1.5, duration 5);
    - whether "missing % health" uses current max health including Health shards;
    - how the passive stacks with Monster, Durability and Jungle;
    - whether a landing stun on a camp suppresses that camp's next attack.
14. **Stale SDK comments.**
    - Stellar is described as "choosing between single-target damage with a stun and an area hit", but she has no stun in either handbook.
    - Tavi's slot 1 is still called a "strong" or "powerful stunning spell" after the cut to 1.4 × Focus.
    - Trust the ability metadata, not the comments.
15. **Only measurable in real games:**
    - How often games now reach round 2,000 now that gem income is cut. If they do, the winner is decided by tributed gems, then gold earned, then kills.
    - Actual kill and capture gold once bonuses apply.
    - Whether your code calls `move_towards` on camp, altar or unit tiles and now hits the new throw.

## 7. What the changes imply (hypotheses to test, not facts)

Everything in this section is a hypothesis derived from the new numbers. It was written by one agent and corrected by a skeptical reviewer (27 fixes). Each point carries a confidence level and a test.

**Camp economy at base values** (gems or gold per 1,000 HP of hitting; damage is per round to the nearest champion in range):

| Camp | Gems per 1,000 HP | Gold per 1,000 HP | Camps for 1,000 gems | Damage per round | Reach | Respawn |
|---|---|---|---|---|---|---|
| Wolf | 2.96 | 29.6 | 250 | 20 | 3 | 40 |
| Elk | 6.25 | 37.5 | 67 | 60 | 4 | 60 |
| Golem | 7.2 | 32 | 28 | 120 | 4 | 80 |
| Gem cluster | 58.3 | 0 | 143 | 0 | — | 50 |
| Gold cluster | 0 | 166.7 | — | 0 | — | 50 |
| Monolith | 10 | 15 | 5 | 200 | 5 | 150 |

Old values for comparison: wolf 16.3 gems per 1,000 HP, elk 15, gem cluster 48, monolith 10.

- **Kill rewards:** the killer takes the victim's whole bag and 100 gold (old 50); assists pay no gold, and a camp kill destroys the bag. A Cassi & Issac kill removes two bodies for 60 rounds and gives up both bags.
  - Vesper Vale as the killer gets 133 gold (153 with Treasure), if her bonus applies to kill gold (§6.9).

**Champion damage at base.** Each figure is one 8-turn cycle against one target, standing in range: 8 basic attacks, one more with an attack reset, and each damaging spell once. Heart of Ruin's dash has to land next to the target.

| Champion | Per 8 turns | Per round | Old per round |
|---|---|---|---|
| Vendetta | 9 × 70 = 630 | 78.8 | 78.8 |
| Tavi | 9 × 45 + 140 = 545 | 68.1 | 66.9 |
| Stellar | 8 × 30 + 170 + 119 = 529 | 66.1 | 77.5 |
| Marcella | 9 × 45 + 120 = 525 | 65.6 | 63.1 |
| Ryth | 9 × 45 + 100 = 505 | 63.1 | 68.8 |
| Willow | 9 × 55 = 495, plus a 360 heal | 61.9 | 50.6 |
| Heart of Ruin | 8 × 40 + 175 = 495 | 61.9 at full HP, 77.3 at half, 92.8 near 0 | new |
| Prism (no gems) | 8 × 35 + 120 + 80 = 480 | 60 | 60 |
| Vesper Vale | 9 × 50 = 450 | 56.3 | 50.6 |
| Ren | 8 × 35 + 125 = 405 | 50.6 | 55.6 |
| Cassi | 8 × 30 + 140 = 380 | 47.5 | 47.5 |
| Varg | 9 × 40 = 360, plus 40 splash on each other target in radius 1 | 45 | 56.3 |
| Issac | 9 × 40 = 360 | 45 | 45 |

**Prism by bag.** Focus = 80 + 1.5 × carried gems (corrected 27 Oct: every 4.0.0 SDK has `prism_focus_per_gem = 1.5` and a local probe confirmed it; earlier text said 1); one Focus shard adds 8.

| Carried gems | Focus | Slot 0 (1.5 × F, stun) | Slot 1 (1 × F, radius 1) | Per round (same method) | Focus shards for the same bonus (30 gold each) |
|---|---|---|---|---|---|
| 0 | 80 | 120 | 80 | 60 | — |
| 50 | 155 | 232.5 | 155 | 83.4 | 9.4 (281 gold) |
| 100 | 230 | 345 | 230 | 106.9 | 18.75 (562.5 gold) |
| 200 | 380 | 570 | 380 | 153.8 | 37.5 (1,125 gold) |

- **Against other casters:**
  - Base Focus is 140 for Willow; 110 for Tavi; 100 for Cassi, Ren, Ryth and Heart of Ruin; 70 for Stellar; 60 for Marcella. Prism matches Willow at 40 gems and passes her from 41.
  - Base spells: Cassi 200, Tavi 176, Heart of Ruin's landing 150, Stellar 140 and 98, Marcella 120, Ren 110, Ryth 100.
  - At 100 gems, Prism's slot 0 (345) beats Stellar's slot 0 with a Power Focus emblem: 2 × (85 + 54) = 278, for 150 gold.
  - A Power Focus emblem gives Prism +48 for 150 gold, about the bonus of 32 carried gems.
  - Old passive: 100 gems gave only +20 Focus.
- **Banking:** a tribute takes ceil(N ÷ 10) turns (5, 10 or 20 for the bags above) and banks the whole bag, so the whole bonus ends at once.
- **Death:**
  - Dying with N gems hands the killer N gems plus 100 gold. That swings the race by up to 2N: we lose N for good, and the enemy gains N once it banks them. A 200-gem bag can swing 400 gems, 40% of the target.
  - A base Prism has 700 HP. Four base champions that start their turns in position deal exactly that in one round: Stellar 170 + 30, Tavi 140 + 45, Vendetta 70 + 70 (the reset is her one cast, so she cannot also dash in), and Heart of Ruin's dash 175 (215 with a basic attack after landing).

**Gold passives**
- **Marcella** gains 2 gold per gem tributed. Neither the handbook nor the SDK says whether this counts only her own tributes or every allied tribute; the figures below assume her own. The rules list no way to pass gems to an ally.
  - Per 100 gems she banks: 200 gold, or 6.7 shards (240 gold if Treasure's 20% also applies to tribute gold, §3).
  - For comparison, the camp gold that comes with 100 gems is 1,000 from wolves, 600 from elks, 444 from golems, 150 from monoliths and 0 from gem clusters.
  - On the share she banks, her tribute gold adds 20% (wolves) to 133% (monoliths) on top of camp gold.
  - If every allied tribute counts instead, she earns up to about 2,000 gold in a game her team wins, wherever she is, and routing gems to her (E7) gains nothing.
- **Vesper Vale** gets +33% on her own gold gains: wolf 40 → 53.2, elk 90 → 119.7, golem 160 → 212.8, monolith 300 → 399, and kill 100 → 133 if the bonus covers kill gold.
  - How fractions round is undocumented (§6.9).
  - A capture is split among all allies on the region, so she gets the whole reward only when she captures alone.

**Wards, locks and reach**
- **Ward:** one placement per 10 own turns, so at most 200 per champion in 2,000 rounds (old: one per round).
  - Placement 2 + vision 6 = 8, which is the champion's own vision. A freshly placed ward reaches no farther than its owner already sees from that spot. It adds a second viewpoint with other lines of sight, and it stays when the owner leaves.
  - In the 10 turns before the charge returns, the owner can walk 10 tiles (more with a dash).
- **Altar lock** (10 gold): takes 5 basic attacks to remove (old 3).
  - One champion needs 5 turns (4 with an attack reset), two need 3 (2 with one reset), three need 2 (1 with two resets), five need 1.
  - Placing it cancels enemy tribute channels at that altar. A 100-gem tribute can lose all 10 of its channel turns: the lock can land after the 10th countdown tick, before completion at the owner's next turn start.

**Maximum reach** in one turn, from the tile where the turn starts (Chebyshev tiles).

| Reach | Champions | Camps |
|---|---|---|
| 1 | Melee basic attack | — |
| 2 | Melee basic attack after a walk | — |
| 3 | Ranged basic attack; dash + melee basic attack; Heart of Ruin's dash landing | Wolf |
| 4 | Unit spells, Willow's heal; walk + dash + melee basic attack or landing (Vendetta, Ren, Issac, Heart of Ruin); walk + attack reset + ranged basic attack (Tavi, Vesper Vale, Willow; the rules say a reset restores the attack allowance, untested) | Elk, Golem |
| 5 | Radius-1 ground spells cast at 4 (Ryth slot 0, Prism slot 1, Stellar slot 1); Cassi's stun or Willow's heal after a walk; Vesper Vale's dash + basic attack, if a dash leaves a ranged champion its attack (untested) | Monolith |

Every damaging spell except Heart of Ruin's dash excludes walking, and nothing deals damage from 6 tiles or more. A camp cannot hit a champion at distance 4+ (wolf), 5+ (elk, golem) or 6+ (monolith). Camps act at round start, so what counts is the tile where a champion ends its turn. Old: every camp had range 3, so every range-4 spell hit every camp from outside its reach.

### Economy and target priorities

- **E1. Games get longer, and some may reach round 2,000.**
  - Per gem, wolf and elk content needs 2.4–5.5× the camp HP it did, and finishing before the limit needs 0.5 gems per round.
  - If a game times out, tributed gems at round 2,000 decide it, then lifetime gold, then kills. Bags still carried at that point count for nothing. The gold tiebreak counts all gold earned (refunds excluded), so gold passives and kill gold presumably count there too.

  *Confidence: high* that games get longer on maps whose camps are mostly wolves and elks; *low* on how many reach round 2,000, which depends on the new maps. *Test:* in the draft, sum gems ÷ (respawn + 5) over every group on each map. Run mirrors on every map and log the final round and both teams' totals. Read game lengths in replays.

- **E2. Choosing a target trades hitting time against health.**
  - By gems per 1,000 HP the order is gem cluster 58.3, monolith 10, golem 7.2, elk 6.25, wolf 2.96. Among camps that fight back, damage taken per gem runs in exactly the reverse order: monolith 20,000 ÷ D, golem 16,667 ÷ D, elk 9,600 ÷ D, wolf 6,750 ÷ D (D = team damage per round, all camp damage on one body).
  - Elks are the balanced default. Golems and monoliths pay off only with a tank, sustain and high D. Wolves cost the least health but the most hitting time per gem (E3).
  - A target score should price hitting time, damage taken, and the recall trip needed to heal that damage.

  *Confidence: high* for the arithmetic, *medium* for the ranking. *Test:* mirror A/B of target-score weights. Compare tributed gems at rounds 500 and 1,000, recalls, and deaths to camps.

- **E3. Wolves give mostly gold now, but elks pay more per hit point.**
  - A wolf gives 10 gold per gem and costs the least damage per gold of the camps that fight back (675 ÷ D, against 1,600 ÷ D for an elk).
  - Per HP of hitting, though, an elk gives more gold (37.5 against 29.6 per 1,000 HP) and 2.1× the gems. Wolves come first only where damage taken is the limit. Gold clusters are the cheapest gold (166.7 per 1,000 HP, no damage), limited by the 5-round capture.
  - A wolf pack is cheap only with splash or area damage. Four wolves killed one at a time cost 84 damage per gem at D = 200, as much as a golem.

  *Confidence: medium.* *Test:* openings that farm wolves first versus elks first. Compare gold at rounds 100 and 200, and gems at round 500.

- **E4. Clusters are free but bound by captures.**
  - They deal no damage and die to one spell of 120 or more. But a gem cluster gives 7 gems per 5-round capture (an elk gives 15, a monolith 200), and a gold cluster 20 gold.
  - They pay off next to the route, or when several are cardinally connected, since a connected group needs only one capture.
  - One radius-1 area hit of 120+ kills every cluster within one tile of its centre (the 3×3 square, if the radius is Chebyshev like the dash's). Bigger patches need more hits. The hits that qualify:
    - Heart of Ruin's dash (150);
    - Stellar's slot 1 after two Focus shards (1.4 × 87 = 121.8);
    - Prism's slot 1 at 27+ gems;
    - Ryth's slot 0 after two Focus shards.
  - Vendetta kills a cluster in one turn (attack, reset, attack = 140), and the kill refunds her reset for the next turn.

  *Confidence: medium.* *Test:* log the time per cluster capture (detour plus 5 rounds) against its gems. Probe which tiles a radius-1 ground spell hits. Mirror A/B of the longest detour allowed for a cluster.

- **E5. The monolith is a mid- or late-game objective, and a trap early.**
  - It is the densest camp that fights back (10 gems per 1,000 HP). One capture is 20% of the target plus 300 gold.
  - But it deals 200 per round to the nearest champion, so a 1,200-HP tank lasts 6 rounds. A kill costs 4,000,000 ÷ D damage.
  - Nothing outranges it (R1). Killing it needs tank swaps (it hits only the nearest champion), Jungle, Willow and D well above 200.
  - A long siege gives the enemy time to arrive, kill the tank or take the capture (F5).

  *Confidence: medium* on its value, *low* on when it becomes worth it. *Test:* probe monolith clears with two tanks and Willow at several values of D; log damage taken and rounds. In replays, note when strong teams take monoliths and who captures them.

- **E6. Golems need Jungle or a healer early, on maps that have them.**
  - A golem gives the old elk's reward (160 gold, 36 gems).
  - A lone 1,200-HP tank survives the kill only at about D ≥ 500, or D ≥ 163 with a Strength or Focus Jungle emblem and Willow.
  - A Health Jungle emblem adds 500 HP on a tank with 100 Health growth (1,700 HP). The tank then needs D ≥ 248 alone, or D ≥ 115 with Willow.

  *Confidence: medium.* *Test:* probe golem clears with and without Jungle and Willow; log the tank's HP and the kill time.

- **E7. Captures can be routed by role.**
  - All champions on the region at capture split the gold and the gems together.
  - Send gold-heavy captures (gold clusters; wolves at 10 gold per gem) to Vesper Vale. Send gem-heavy ones (gem clusters; monoliths at 1.5 gold per gem) to Prism, or to Marcella if her tribute gold counts only her own tributes.
  - Keep tanks' bags empty, because a camp kill destroys the bag.

  *Confidence: low.* The split rule is certain; the payoff is not. *Test:* mirror A/B of capture routing. Log gold earned per champion, Prism's Focus over time, and gems destroyed by camps.

- **E8. Items arrive later, so base stats decide more.** One monster's capture gold now buys 1.3 shards (wolf), 3 (elk), 5.3 (golem) or 10 (monolith); one kill buys 3.3. There is no passive income (`passive_gold` is 0), so all gold comes from captures, kills and Marcella's tributes. *Confidence: medium.* *Test:* in mirrors, log each champion's gold over time.

### Fighting versus farming

- **F1. Fighting gained on farming.**
  - One kill's gold now equals the capture gold of 2,667 elk HP (1.1 elks), against 750 HP (0.3 elks) before: 3.6× as much. Each stolen gem is worth 2.4× as much elk HP.
  - The 60 rounds a victim sits out now cost it 2.4–5.5× fewer gems of farming.
  - Expect more ganks, above all on carriers walking to altars and on champions tanking camps.

  *Confidence: medium.* The direction is high; whether a given fight pays depends on who wins it. *Test:* mirror A/B of the engage threshold (expected kill value against risk). In replays, count kills per game and kill gold as a share of all gold.

- **F2. Bank small and often, except with a protected Prism.**
  - Tribute time grows with the bag (ceil(N ÷ 10)), so several small tributes cost extra walking and a little rounding (an elk's 15 gems take 2 turns).
  - A big bag is a larger prize relative to income, and a lock cancels a long channel (L1).

  *Confidence: medium.* *Test:* mirror A/B of banking at 15, 30 or 60 gems (one, two or four elks) against an opponent that fights. Compare gems lost on death, and tributed gems at rounds 500 and 1,000.

- **F3. Camps are weapons.**
  - At round start, an awake camp hits the nearest champion within its reach, for 20, 60, 120 or 200. The rules say just *the nearest champion*, which reads as either team.
  - Fighting next to an awake golem or monolith adds 120–200 damage per round to whichever side stands nearer.
  - A camp kill destroys the victim's bag, so nobody gets it.
  - So fight where the enemy is nearest to the camp, and keep carriers away from awake golems and monoliths.

  *Confidence: medium.* *Test:* probe the targeting rule and its tie-break with champions of both teams at different distances. Then mirror A/B a positioning term.

- **F4. Route the last hits.** The killer takes the bag and the gold. Prism gains 1 Focus per stolen gem at once, and Vesper Vale may get 133 gold instead of 100. *Confidence: low.* *Test:* probe who gets kill credit, and how much gold Vesper Vale gets for a kill.

- **F5. Long clears invite steals.**
  - At D = 200 a golem takes 25 rounds and a monolith 100.
  - A capture needs no enemy on the region, so a team that arrives late can take the last hits and the capture.
  - An awake camp (`vision::awake_camp_tiles()`) means someone damaged it and has been near it recently (R3). Vision is not shared, so it points to an enemy only when no ally has claimed that group in shared memory.

  *Confidence: low.* *Test:* in replays, count captures by the team that did not start the clear. In mirrors, A/B treating unclaimed awake camps as enemy sightings.

### Draft

| Champion | Change (old → new) | Net | Likely role now |
|---|---|---|---|
| Marcella | +2 gold per gem tributed (whether only her own tributes count is unclear); Focus 50 → 60, growth 10 → 15 | buff | Stun-immune tank (1,200 HP) and banker. Slot 1 deals 300 with Power Focus. |
| Vesper Vale | Gold bonus +20% → +33%; Strength 45 → 50 | buff | Gold capturer and kill-taker |
| Willow | Strength 45 → 55; Focus 105 → 120 (heal 315 → 360) | buff | Sustain for tanks: 45 per round more than offsets one elk's damage on a Jungle tank (42) |
| Prism | 0.2 → 1 Focus per gem; growths cut | conditional buff | Gem carrier and burst |
| Vendetta | Strength growth 5 → 6 | small buff | Highest sustained damage at base for a full-HP champion without gems (78.8); chains clusters |
| Heart of Ruin | new | — | Diver and channel breaker (H1) |
| Tavi | Nuke 2.2 → 1.4 × F (220 → 140); Strength 35 → 45 | burst nerf; sustained +2% | Sustained damage; buys shards in the field |
| Ryth | Strength 50 → 45 | small nerf (−8%) | Tank with an area stun |
| Ren | Strength 40 → 35; Focus growth 10 → 9 | small nerf (−9%) | Stun and dash |
| Stellar | Strength 35 → 30; Focus 100 → 85, growth 10 → 9 | nerf (−15%) | Burst of 170 and 119 |
| Varg | Strength 50 → 40 | nerf (−20%, splash included) | Tank with a 250 shield |
| Cassi & Issac | Cassi Health 700 → 600; growths cut on both | nerf | Two bodies (92.5 damage per round, two wards); either death kills both, and Cassi's 600 HP is the weak link |

- **D1. Winners and losers.** On paper the net winners are Marcella, Vesper Vale, Willow, Prism (given a carry plan) and Vendetta, and the net losers are Stellar, Varg, Cassi & Issac and Tavi's burst, with Ryth and Ren slightly worse. The first post-patch ranked data (§8) agrees except for Ryth, which does well (+2.1 points rating-adjusted) despite its small nerf, and Prism, which is neutral. *Confidence: high* for the direction of the stat changes; *medium* for how good each pick now is, because the economy changed under them. *Test:* per-map mirror gauntlets that swap one pick at a time.

- **D2. The draft should follow the map's camps.**
  - A tank-plus-sustain core (Marcella or Ryth, with Willow) suits golem and monolith maps. Fast clearers (Vendetta, Vesper Vale, champions with dashes) suit cluster and elk maps.
  - The draft bot sees the whole map, so it can count camp types and compute the gem-rate ceiling from E1.
  - Lineups to try first:
    - siege: Marcella, Ryth or Varg, Willow and Vendetta, plus Prism to carry big captures;
    - race: Vendetta, Vesper Vale, Stellar or Tavi, and Willow;
    - pick: Heart of Ruin, Prism, Tavi or Ren, and Willow.

  *Confidence: low.* *Test:* per-map lineup gauntlets in mirrors, then platform groups on the maps where the chosen lineups differ.

- **D3. Cassi & Issac are a liability in fights.**
  - One kill through Cassi's 600 HP removes both bodies for 60 rounds and gives up both bags, all for one 100-gold reward.
  - Their upside is two capture bodies, two wards and 92.5 damage per round for one pick. It counts most on quiet farming maps.

  *Confidence: medium.* *Test:* mirror A/B with and without the pair; count the pair's deaths and bag losses.

- **D4. Heart of Ruin is draftable (resolved).**
  - Ranked platform games have included Heart of Ruin since the patch went live at 03:00 UTC on 2026-10-20, even though the starter templates still loop over indices 0–10 (§6.5).
  - Its adoption is still rising. In the first post-patch data it has the best rating-adjusted result of any champion, but part of that comes from teams that updated their bots (§8).
  - A draft bot should still keep a fallback pick in the same turn, because a draft bot that yields without picking gets random picks for the rest of the draft.

### Prism stacking

- **P1. A loaded Prism out-casts every spell at base stats.**
  - At 100 gems it casts 345 single-target with a stun and 230 in an area. The best spell at base stats is Heart of Ruin's 175 landing (262.5 near zero HP).
  - Casters with items can match or pass it: Marcella's slot 1 with Power Focus deals 300, Stellar's slot 0 278.
  - From 27 gems its area spell one-shots clusters.

  *Confidence: high* for the arithmetic; how often a Prism can hold 100 gems is untested. *Test:* probe Focus and `ability::damage_amount()` against bag size.

- **P2. It is also the most valuable target in the game.**
  - Dying with N gems swings the race by up to 2N, and an enemy Prism that takes the bag gains N Focus.
  - Four base champions already in position can deal its 700 HP in one round.
  - Stacking therefore needs a tank or escort, a bag cap that drops when enemies are seen, and banking before contact.

  *Confidence: medium.* *Test:* mirror A/B of bag caps (0, 50, 100, 200) against an opponent that fights. Log Prism deaths with a bag, gems swung, and kills by Prism.

- **P3. Fast stacks** come from a solo monolith capture (+200), golem captures (+36), and last hits on enemy carriers with slot 0 (1.5 × F plus a stun, range 4). Wolves (+4 each) are too slow. *Confidence: low.* *Test:* over many games, log where Prism's Focus came from.

- **P4. The bag has a deadline.**
  - Carried gems never score.
  - A 200-gem tribute takes 20 turn ends and completes at the start of the 21st turn. A stun, death or newly placed lock cancels it, and a new tribute starts over with the full duration.
  - So bank in time before round 2,000, and bank at once when tributed gems plus the bag reach 1,000, which wins outright.

  *Confidence: high.* *Test:* scripted endgame probe.

- **P5. Against an enemy Prism,** focus it while its bag is big.
  - Stuns (Cassi, Prism, Tavi, Ren, Ryth, Heart of Ruin, Marcella's enhanced attack) and locks break its tribute.
  - A camp kill destroys its bag: we gain nothing, but they lose it all.

  *Confidence: medium.* *Test:* mirror against a Prism-stacking sparring bot, with A/B target priorities.

### Heart of Ruin

- **H1. It is a diver and a channel breaker more than a farmer.**
  - Its sustained damage at base is 61.9 per round, below Vendetta's 78.8.
  - Its value is the dash landing:
    - it hits from 4 tiles away in one turn (walk 1 + dash 2 + radius 1). Vendetta, Ren and Issac reach 4 too, but only with one basic attack on one target;
    - the landing deals 175 to every enemy and camp around it;
    - the landing stun breaks several enemies' tributes and teleports at once, and its damage breaks recalls. Marcella is immune to the stun.

  *Confidence: medium.* *Test:* probe it against enemies tributing at an altar. Mirror A/B with Heart of Ruin in place of Varg or Ryth on fight maps.

- **H2. It wants to fight hurt, so it should not carry gems.**
  - At half HP its basic attack deals 50 and its dash 218.75; near zero HP, 60 and 262.5 (459 with 5 Focus shards).
  - Its 150 shield does not count as health, so it protects without lowering the bonus.
  - As a camp tank it hits harder the longer it tanks.
  - Low HP near camps or enemies puts any bag it carries at risk.

  *Confidence: medium.* *Test:* log its HP fraction at each hit, its damage, its deaths and its bag at death.

- **H3. It may control camps.** If a stun cancels a camp's next attack, each dash cancels one golem hit (120) or monolith hit (200). So would the other stuns that can target camps: Cassi slot 1, Prism slot 0, Tavi slot 1, Ren slot 0, Ryth slot 0 and Marcella's enhanced attack. *Confidence: low* (untested). *Test:* probe: stun an awake camp and check whether the nearest champion takes damage at the next round start.

- **H4. Focus for the dash, Strength for sustained damage.**
  - Its Focus growth of 15 is the highest, tied with Marcella's.
  - 5 Focus shards raise the dash to 306.25, which adds 16.4 per round on each target it hits. 5 Strength shards add 25 per round on one target.
  - So Focus pays off when the dash regularly hits two or more targets (cluster patches, wolf packs, grouped enemies), and Strength otherwise. The missing-health bonus multiplies both.

  *Confidence: low.* *Test:* A/B of item builds.

### Altar locks

- **L1. Locks are the cheapest denial in the game.**
  - For 10 gold, a lock forces at least 5 enemy basic attacks and cancels any enemy tribute channel at that altar. A kill costs far more effort for 100 gold.
  - A lock blocks only the enemy, so the locked altar is ours until it is broken.
  - Expect locks on the altars an opponent relies on, above all when it is close to 1,000 or starting a long tribute.

  *Confidence: medium.* *Test:* mirror A/B "place a lock when an enemy carrier nears an altar we can reach". Log the enemy's tribute delay against the gold spent.

- **L2. Defend by escorting and splitting.**
  - Champions with an attack reset clear a lock fastest: melee Vendetta, Varg, Ryth, Marcella and Issac; ranged Tavi, Vesper Vale and Willow.
  - Small bags make a cancelled channel cheap, and a second altar in reach is insurance.
  - A bot that keeps trying to tribute at a locked altar hits the lock once per turn.

  *Confidence: medium.* *Test:* scripted probe: time from lock to completed tribute with 1, 2 and 3 escorts.

- **L3. A lock is the cheap counter to a Marcella banker.** Damage never interrupts a tribute, and she is immune to stuns. Only her death or a newly placed lock stops her tribute. *Confidence: high* (rules). *Test:* probe: stun and damage a tributing Marcella, then place a lock.

### Wards

- **W1. Wards become fixed watch posts, not scouting tools.** A ward can move at most once per 10 turns and reaches no farther than its owner saw from where it stood. Good posts:
  - altars, to see enemy tributes and locks;
  - groups the enemy may capture (a group's respawn timer can be read only with one of its spawn tiles in vision);
  - routes to our carriers.

  *Confidence: medium.* *Test:* mirror A/B of ward policies (fixed posts versus forward placement). Log late arrivals at respawns, and deaths with no prior sighting.

- **W2. Our own captures need no ward.** Their respawn round is about the capture round plus `max_respawn_timer()`, as long as the capturer writes it to shared memory. A champion standing on any of the group's spawn tiles delays the whole group, and the exact offset is unmeasured. *Confidence: medium.* *Test:* compare predicted and observed respawn rounds in logs.

- **W3. More bodies hold more posts.** Wards belong to one champion and are not shared, so 5-champion maps and Cassi & Issac (two wards for one pick) can hold more posts. Allies learn what a ward sees only through 8 bytes of shared memory. *Confidence: low.* *Test:* log how often a ward's sightings change its owner's decisions.

### Monster reach and tanking

- **R1. Free sieges are gone.**
  - In the old game every camp reached 3, so any range-4 spell hit any camp from safety. Now that works only on wolves.
  - Elks and golems can be hit from distance 5 only by the three radius-1 ground spells (Stellar 119, Ryth 100, Prism 80 and up). Each casts once per 8 turns, so each adds 10–15 damage per round.
  - Nothing hits a monolith from outside its reach.

  *Confidence: high* (rules). *Test:* probe each camp type from distances 3 to 6 and log damage taken. Confirm that area spells damage camps: the handbook says so explicitly only for Varg's splash and Heart of Ruin's landing.

- **R2. Clears are tank-first.**
  - A camp hits only the nearest champion within its reach, and each monster in a group picks its own target. The team takes damage on one body only while the tank stands strictly nearer than everyone else to every awake monster. The distance metric and the tie-break are undocumented.
  - Tanks swap by stepping the fresh tank nearer. The old tank can then recall in place, as long as no monster or enemy damages it during the 5 turns (3 with Home).

  *Confidence: medium.* *Test:* probe the tie-break, and a swap followed by a recall.

- **R3. Long reach keeps camps awake.**
  - By the handbook bullet and the SDK comment on `constants::camp_sleep_time`, an awake camp falls asleep after 2 rounds without an in-range champion. Neither says which range; attack reach is assumed here.
  - If so, a champion passing within 4 of an elk or golem, or within 5 of a monolith, keeps it awake and can become its target.
  - The new intro sentence says damage decides instead (§6.1). Which rule holds changes how teams disengage.

  *Confidence: medium.* *Test:* the §6.1 probe, also with a champion between reach and 8 tiles.

- **R4. Camps may not heal.** No rule mentions camps regenerating. If they don't, a golem or monolith can be worn down over several visits. *Confidence: low.* *Test:* probe: damage a golem, stay away longer than its sleep time, then read its HP.

### What the old meta relied on that no longer works

- **O1.** Wolves as a gem source: 22 → 4 gems, and 16.3 → 2.96 gems per 1,000 HP. *Confidence: high.*
- **O2.** Casting at elks, golems and monoliths from range 4 without being in their reach (R1). *Confidence: high.*
- **O3.** Gem clusters as solid stops: 24 gems at 500 HP became 7 gems at 120 HP, so capture time now dominates (E4). *Confidence: high.*
- **O4.** Re-placing the ward every round, as the old rules allowed (W1). *Confidence: high.*
- **O5.** Clearing a lock in 3 hits (L1). *Confidence: high.*
- **O6.** Pick-offs built on Tavi's 220 nuke and Stellar's 200 and 140, which are now 140, and 170 and 119. *Confidence: high* for the numbers, *medium* for how much fights change.
- **O7.** Varg's splash farming at 50 + 50, now 40 + 40. *Confidence: high.*
- **O8.** Prism's passive as negligible (0.2 Focus per gem), and kill gold as minor (50, now 100). *Confidence: high* for the numbers, *medium* for the consequences (P1, F1).
- **O9.** The monolith as a poor target. It is now the densest camp that fights back, though the most punishing (E5). *Confidence: medium.*
- **O10.** Code assumptions that are now wrong:
  - monster range 3;
  - five camp types;
  - 11 draft choices and 12 champion designs;
  - `move_towards()` returning false for a blocked target (it now paths to the target as if it were free, and throws when the last step would enter a known blocked tile);
  - the 2.2.5 ABI.

  *Confidence: high.*

*Tests:* for O1–O9, log the camp and champion designs at init (§1) and run the probes above. For O10, build against 3.0.1 and test `move_towards()` next to a camp and next to an altar.

### Measure these first

Each of these results could change several hypotheses at once:
1. ~~`constants::passive_gold`, `assist_gold` and `kill_gold`~~ Resolved from the engine: 0, 0 and 100 (E8, F1).
2. ~~Whether a stun cancels a camp's next attack~~ Resolved: yes, one attack per stunned monster (§9) (H3, E5, E6).
3. ~~The camp sleep rule and the nearest-champion tie-break~~ Resolved: the in-range rule holds and ties go to the lower id (§9) (R2, R3).
4. ~~Whether camps heal~~ Resolved: they do not regenerate (§9) (R4).
5. Whether Vesper Vale's bonus applies to kill gold, and how gold rounds (F4).
6. ~~Whether Heart of Ruin can be drafted~~ Resolved: yes (D4).
7. How long games last on the current map pool (E1).
8. Whether Marcella's tribute gold counts only her own tributes (Gold passives, E7).
9. ~~Whether area spells damage camps, and the shape of their radius~~ Resolved: they hit every monster in the 3×3 around the target tile (§9) (R1, E4).
10. Whether a ranged champion can attack after a dash. (Walk + attack reset + attack, and a standing basic attack plus a spell in one turn, both work: §9.)


## 8. Platform snapshot, 2026-10-20

- **Go-live:** the first ranked match on engine 1.0.0 was at 2026-10-20 03:00 UTC; every earlier ranked match ran engine 0.0.3. Heart of Ruin picks start with the 03:00 groups and keep rising during the day.
- **Map pool (21 maps):**
  - 00ambush, 00collision, 00contest, 00corners, 00eight, 00elkring, 00expanse, 00fragment, 00interlock, 00lanes, 00monolith;
  - 01big_world, 01boss_battle, 01broken_curve, 01concentrated_wealth, 01corridors, 01elk_arena, 01fracture, 01gold_rush, 01hooks, 01islands.
  - Gone from the pool: packs, pilgrimage, rows, rushbait-v2, stampede, swirl, and the Sprint 1 maps shortcut, starfish, starvation, the_farm and yellow_brick_road.
  - Picks per team: 3 on collision, fragment, broken_curve and gold_rush; 4 on interlock and hooks; 5 everywhere else.
- **First data**, 23,170 ranked matches from 03:00 to 12:45 UTC. Champion results are win rate above the rating expectation, counting only games where the opponent did not pick the same champion:

  | Champion | Points above expectation |
  |---|---|
  | Heart of Ruin | +4.4 |
  | Vesper Vale | +4.2 |
  | Marcella | +3.5 |
  | Ryth | +2.1 |
  | Vendetta | +1.7 |
  | Willow | +1.6 |
  | Ren | +1.0 |
  | Prism | −0.4 |
  | Varg | −1.3 |
  | Stellar | −2.3 |
  | Tavi | −3.1 |
  | Cassi & Issac | −3.5 |

  - Part of the lead of the new and buffed champions comes from teams that had already updated their bots.
  - No champion-vs-champion counter stands out beyond chance yet (43 of 1,069 matchup cells at |z| > 2, against about 49 expected).
  - 76% of teams play one fixed lineup per map.
  - Details: the draft study in `/data/USER/draft/out` on HOST (`data_stats.md`), and its report when it is done.
- **Our team:** the pre-patch bot (v31) is still live and went 130-160 after the patch. The team fell to rank 130 (rating 1675).

## 9. Resolved by engine experiments (2026-10-20)

The draft study's champion-model agent ran about 20 scripted scenarios in the patched engine: the `v1_0_0` module bundled with the 3.0.1 visualiser, driven from a script, not a bot. It also read the engine's settings and design tables. Details and scripts are in `/data/USER/draft/out/kits.md` §2 and `/data/USER/draft/scripts/kits/` on HOST. The results settle most of §6 and §7's "Measure these first":

| Topic | Engine behaviour |
|---|---|
| Camp sleep (§6.1) | A woken camp attacks every round while any champion stays within its attack range, even with no further damage. It sleeps after 2 rounds with nobody in range. The handbook's "does not take damage for 2 turns" is wrong. |
| Camp targeting | Nearest champion by Chebyshev distance within the camp's range. Ties go to the lower champion id (draft order). A melee champion adjacent to the camp absorbs every hit; casters at 3-4 tiles take nothing from a wolf. |
| Group wake | Hitting one monster wakes its whole cardinally connected group, and each member attacks its own nearest champion. A sleeping camp ignores champions standing next to it until it is hit. |
| Regeneration | None. Camp HP stays where it was while the camp sleeps, so a group can be chipped down over several trips. |
| Stuns on camps | A stun cancels exactly that monster's next attack. Area stuns (Ryth slot 0, Heart of Ruin's dash) cancel one attack of every monster hit. |
| Ranged attack + cast (§6.4) | A ranged champion that does not move can basic attack and cast a damage spell in the same turn (Stellar 30 + 170). An attack reset gives a second basic attack in the same turn, and a ranged champion can move, reset, then attack. Only one successful cast per turn. |
| Area spells | Stellar (1.4 × F), Prism (1 × F) and Ryth (1 × F) area spells hit every monster in the 3×3 around the target tile. Varg's splash deals full Strength to every other camp or enemy within radius 1 of the target. |
| Heart of Ruin | The landing deals 1.75 × F to everything within radius 1, plus the stun. The passive is linear: at 50% HP the landing does 218.7 and a basic attack 50. The 1.5 × F shield absorbs for 5 turns. (2.0.0: the landing is 1.5 × F, so at 50% HP it does 187.5 and a basic attack 37.5.) |
| Vendetta | A camp kill resets both cooldowns, but the one-cast-per-turn rule still applies, so the refreshed reset is usable next turn. |
| Ren | Every damage instance he takes, camps included, returns 0.2 × F (20 at base). |
| Gold bonuses (§6.9) | Vesper Vale's +33% applies to her share of a capture and is floored (60 → 79). Marcella's 2 gold per gem is paid when her tribute completes (50 gems → +100). Vesper Vale gets no tribute gold. Treasure is +20% on all gold for its wearer. |
| Emblems | Monster +10% on all damage to camps, spells and splash included. Durability −10% from all sources (golem 120 → 108). Jungle −30% from camps (golem 120 → 84). Power = 6 growth units for 5 shards. Home: recall in 3 turn ends. No champion has a hidden camp-damage multiplier. |
| Capture timing | About 6 rounds from stepping onto the region to the reward (the 5-round timer starts at the next capture phase). |
| Linked death | Killing Issac kills Cassi too, for one 100-gold reward. |
| Golems | The engine has them, but **none of the 21 pool maps contains a golem**. Golem numbers matter only for future or tournament maps. |

Map and game-length facts from the same study (same caveat: one day of data):
- The 00/01 map pool replaced the old ladder at 2026-10-19 22:00 UTC, before the engine patch.
- On the 11 00-maps the terrain is unchanged. Camps were only added (gem and gold clusters), 8 wolves were turned into clusters, and 2 gold clusters were removed on monolith.
- Expanse went from 3 to 5 picks.
- Monoliths hold 34-100% of the gems on 8 of 21 maps (contest 100%, gold_rush 75%).
- Sampled games between strong teams last about 900-2,000 rounds (median about 1,190), and 7 of 59 reached round 2,000. The tiebreak (tributed gems, then lifetime gold) matters, and on boss_battle both sampled games ended 0-0 and were decided by gold.


## 10. Update: cambc 3.0.4 / engine 1.0.2 (seen 2026-10-21)

- **Prism:** `prism_focus_per_gem` 1.0 → **1.5**. 100 carried gems add 150 Focus. Gem stacking on Prism is stronger still, and so is the prize for killing her.
- **New SDK functions:** `distance_field::copy_from(source)` and `copy_from(source, mask)`, plus the host imports `bc_DistanceField_Copy` and `bc_DistanceField_CopyWithMask`. They copy cached fields cheaply, which is useful for reusing static path fields instead of recomputing them every turn. Everything else in the headers is unchanged (additions only).
- **Ranked map pool: 36 maps.** The new map is `00gem_fields`. packs, pilgrimage, quadrants, reverse_spiral, rows, rushbait_v2, split, stampede and swirl are back in the pool.
- **Local testing:** `/homes/USER/condor-work/bin/cambc304`. The Condor game runner (`rungames.sh`) and the test projects (`/data/USER/work301`, `/homes/USER/condor-work/proj301`) use the 3.0.4 headers and the current maps.

## 11. Check: cambc 3.0.5 / engine 1.0.3 against 3.0.4 / engine 1.0.2 (2026-10-25)

cambc 3.0.5 has been on PyPI since 22 Oct. The ladder runs engine 1.0.3 (`match.engineVersion` in platform summaries);
local tests run 3.0.4 with engine 1.0.2.

**Method.** Nothing from the download was executed.
- Both wheels were fetched as binaries into /data/USER/cambc305. The CLI's embedded archive was extracted as data.
- The engine modules were then compared in node's WebAssembly sandbox:
  - the draft study's design dump (`dump_designs.js`);
  - its scripted duels (`duelsim.js`) and camp clears (`clearsim.js`).
- The 1.0.3 module is byte-identical to the one rdec.js already uses for live replays.

**Findings.**
- **Rules and numbers: unchanged.** These read identically from 1.0.2 and 1.0.3:
  - Game_Settings;
  - all 13 champion rows (stats, growth, abilities, passives);
  - the camp designs, item and consumable info;
  - the visualiser constants.

  The engine's data section is byte-identical.
- **Behaviour: unchanged where measured.** Both sets give byte-identical results in the two engines:
  - 264 scripted 1v1 duels: every pick pairing, with casts, dashes and items;
  - 96 camp clears: wolves, elks, golem, monolith and mixed groups; parties of 1-4; 0 and 600 gold.
- **Engine code: small edits.**
  - 51 of 907 functions differ once call targets are masked, and one function was added.
  - Most changes are same-size edits in the buff, cooldown, charge and restriction getters, which fits a field added to a
    unit record. Also changed: `Game_Action_Cast` (148 → 141 bytes) and the replay and visualiser readers.
  - 1.0.2 refuses 1.0.3 replays (a version check), so live replays still need `v1_0_3.wasm`.
- **SDK:**
  - `imports.h`, the Python constants and the starter templates are byte-identical.
  - `cambc.h` changes one comment: gameplay debug drawings now last until the start of the drawing champion's next turn,
    and draft drawings until the next draft round. Python's `debug.py` and the OCaml interface say the same.
  - The Rust SDK adds `bitflags`/`bytemuck` re-exports and trait impls. No function or type changed for C++ bots.
- **Handbook: not compared.** The published handbook is behind the platform login, and the CLI bundles no rules text.
  GameRules.md is still the 20 Oct export.

**Implication.** Moving local tests to 3.0.5 should change no game outcome in what was measured. What the duels and
clears do not exercise: debug-drawing lifetimes (visual only), replay saving, and whatever else changed in the cast
entry point. The cambc-lab skill also records 12 identical games between local 1.0.2 and the platform on 22 Oct.
Report: /homes/USER/condor-work/reports/cambc305_check_1025.md.

## 12. The Sprint-2 patch: engine 2.0.0 / cambc 4.0.0 (live 2026-10-25 22:52 UTC)

The ladder switched to engine 2.0.0 at about 22:52 UTC. cambc 4.0.0 (CLI and SDK) was published at 23:44, on PyPI and on
the platform's distribution endpoint.

**Sources** (nothing from the download executed for this section):
- the 4.0.0 linux-x64 binary, SHA-256 matching the platform's record `552056aa…`, downloaded by cambc-2f;
- its embedded archive, extracted as data into /data/USER/cambc400x;
- the engine module `v2_0_0`, also at /homes/USER/condor-work/engine/v2_0_0.wasm:
  - every setting and design table read with `dump_designs.js` (items 0-83);
  - camp behaviour checked with scripted clears;
- item passive semantics from the 4.0.0 visualiser's tooltips (rule set `sprint2`);
- SDK details from cambc-2f's header diff;
- item metadata confirmed in play by cambc-f8's probe bot.

### Champions (exact, from the engine)

| champion | change |
|---|---|
| Vesper Vale | base Strength 55 → **45** |
| Issac | base Strength 40 → **45** |
| Varg | base Strength 40 → **45** |
| Cassi | base Focus 70 → **100** |
| Willow | base Focus 120 → **140** |
| Ren | stun (slot 0) modifier 0.75 → **1.10** x Focus |
| Tavi | stun (slot 1) modifier 1.40 → **1.60** x Focus |
| Stellar | Focus growth 7 → **8.5** |
| Prism | Health growth 60 → **65** |
| Heart of Ruin | Strength growth 3.5 → **3**; Focus growth 12 → **10** |
| Marcella | Strength growth 5 → **4.5**; Focus growth 15 → **14** |
| Ryth | Strength growth 5 → **4.5** |

- No other champion field changed: ranges, cooldowns, other modifiers, and passives with their magnitudes.
- Heart of Ruin got weaker per item, not stronger. The large HoR totals seen in live play (cambc-2f) come from builds,
  items or meta, not from its design row.

### Items

- **Ids 0-41 are unchanged** except two passives:
  - **Monster** emblem camp damage +10% → **+15%**;
  - **Treasure** emblem gold +20% → **+10%**.
- **Seven new families, ids 42-83, laid out as family x 6 + stat x 2 + emblem.**
  - Shards cost 30 gold and give +1 of a stat.
  - Emblems combine 5 shards (150 gold) into +5 of that stat plus the passive.
  - Greed is the exception: 25 shards (750 gold) into +35 stat, no passive.

| family | emblem passive (`sprint2` tooltip) | magnitude |
|---|---|---|
| tribute | tribute channel time shorter by 33%, rounded up to at least one turn | 0.33 |
| capture | caps the team's remaining capture time at 3 turns, including when joining mid-capture; never lengthens a shorter timer; the reduction holds while an ally keeps capturing | 3 |
| prospector | +25% gold and gems on your share of gem- and gold-cluster rewards, rounded down; other camp rewards unchanged | 0.25 |
| hunter | +50 gold on champion kills | 50 |
| skirmish | +5% damage to champions | 0.05 |
| collectors | +1% damage per unique emblem family owned | 0.01 |
| greed | no passive: 35 stat points for 25 shards | - |

- The existing **bruiser** emblem gives five shards of its stat plus one of each other stat instead of a passive.
- **A new error code**, `invalid_action_buy_item_stats_overflow` (54), implies a cap on summed item stats. The value is
  not in the headers.
- **These three are now measured:** stacking, the stat cap, and hunter gold under Treasure or Vesper Vale. See *Items: measured in the engine* below.

### Items: measured in the engine (2026-10-26)

- **Method:** scripted states in the 2.0.0 sandbox (condor-work/sandbox/sim.js with engine/v2_0_0.wasm).
- **Sources:** probes in condor-work/reports/itm_tools/; the full table is condor-work/reports/update_items_1026.md §1.

**Stacking and the stat cap:**
- **No passive stacks.** A second emblem of a family adds its 5 shards of stat only (every family tested). Stats from shards always stack.
- **No stat cap in practice.**
  - Error 54 ("Item stats exceed supported range") is an overflow guard. It first trips between 1.2 x 10^8 and 1.1 x 10^9 points of one stat.
  - 6,000 shards of each stat buy without error.

**Hunter and kill gold:**
- **Hunter's +50 is added before the gold multipliers.** Treasure and VV add to each other, then multiply, floored.
- Kill gold by item set:

  | items | kill gold |
  |---|---|
  | none | 100 |
  | Hunter | 150 |
  | Treasure | 110 |
  | Treasure + Hunter | 165 |
  | VV | 133 |
  | VV + Hunter | 199 |
  | VV + Treasure + Hunter | 214 |

- Gem loot from a kill is unchanged.

**Capture emblem:**
- **Without it,** the reward lands at the 6th round start after stepping on (r+6). With the holder on the region from the start, it lands at r+4.
- **Joining mid-capture** caps the remaining time at 3 at the next capture phase:
  - joining at r+1 gives the reward at r+4;
  - at r+2 it gives r+5;
  - at r+3 or later it gains nothing.
- **The capped timer holds** while an ally stays after the holder leaves. An empty region resets.
- **An enemy on the region freezes the timer at 5.** On restart the timer is 5 without the emblem and 3 with it.
- The reward is still split evenly.

**Tribute emblem:**
- Channel time is ceil(0.67 x ceil(G/10)) turns. Without the emblem it is ceil(G/10), minimum 1.
- Turns saved: 0 for 1-30 gems, 1 for 31-60, 2 for 61-90, 4 at 150, 9 at 300.
- Holder only.

**The other passives:**
- **Prospector:** +25% (floored) of the holder's share of the cluster part of a reward only. A wolf plus gold cluster worth 60 gives 65.
  - It multiplies with Treasure and VV. A 40-gold cluster pair gives 50 with Prospector, 44 with Treasure, 55 with both.
- **Collectors:** +1% to all damage (champions and camps) per distinct completed emblem family, itself included.
  - Power and Bruiser count; a duplicate family counts once; loose shards don't count.
  - It multiplies with Skirmish and Monster.
- **Skirmish** is +5% against champions only.
- **Monster** is +15% against camps only.
- **Treasure** is +10%: a kill gives 110, a capture 44 of 40.
- **Greed:** 25 shards (750 gold) give 35 x the stat's growth. The 24 shards before completion give +1 growth each.

### Unchanged

- **Game_Settings, all values:** capture 5, tribute 0.1 turns per gem, altar lock 5 hits, kill gold 100, respawn 60,
  recall 5, ward and vision settings.
- **Camps:** every design, and behaviour. 36 of 36 control clears (champions with unchanged base stats, 0 gold) are
  identical between 1.0.3 and 2.0.0. The other 47 of 96 differ only where changed champions or items are involved.
- **Consumables, and the 70 published maps** (byte-identical, per cambc-2f).

### SDK / API (cambc 4.0.0; cambc-2f)

- **Item enum** grows from 42 to 84.
- **New enums:** `item_family` (14), `item_stat`, `camp_group_capture_type`. `item_passive` gains the six new passives.
- **Runtime item metadata** on `item_type`: cost (full refund on sale), combine count and result, stat points,
  passive and magnitude, purchasable.
- **About 522 changed lines** in `cambc.h`/`imports.h` together, including the SDK tests.
- **Old-SDK bots** ran on 2.0.0 without faults. v207 compiles against 4.0.0 and plays full 2.0.0 games with 0 faults.
- **Local A/B on 2.0.0:** `ABL_CLI=/data/USER/cambc400/bin/cambc400` (commit 4ae19f8).
- **Replays:** live 2.0.0 replays decode with `v2_0_0.wasm` (rdec.js picks it by `engineVersion`).

## 13. The finals patch: engine 3.0.0 / cambc 5.0.0 (published 4 Nov 2026; ladder still on 2.0.0 at 23:00 UTC)

**Sources:** cambc 5.0.0 from PyPI (the CLI's update notice points there; SHA-256 `38d475cf…`, at /data/USER/cambc500/bin/cambc500);
the engine module `v3_0_0` from its visualiser assets (/homes/USER/condor-work/engine/v3_0_0.wasm), read with
`dump_designs.js` and diffed byte for byte against v2_0_0; the owner's 5.0.0 GameRules.md. Same size, same 916 functions, imports
and exports; 4 function bodies change only the engine version constant 2 -> 3 (also the replay header's version word).

| change | 2.0.0 -> 3.0.0 |
|---|---|
| Vesper Vale | base Strength 45 -> **35** |
| Marcella | base Strength 45 -> **40**; Strength growth 4.5 -> **3.5**; Focus growth 14 -> **10** |
| Heart of Ruin | base Focus 100 -> **80**; Focus growth 10 -> **9** |
| Vendetta | base Health 1000 -> **900**; base Strength 70 -> **65** |
| Varg | base Strength 45 -> **50** |
| Prism | base Focus 80 -> **90** |
| Stellar | base Focus 70 -> **85** |
| Skirmish passive | +5% -> **+10%** damage to champions |
| Greed | combines to 35 -> **40** shards of stats |

- Unchanged: settings, camps, items 0-83 other than these two passives, consumables, maps, the replay/timeline layouts, the SDK API
  (cambc.h differs only in comments; a bot's release wasm from 5.0.0 is byte-identical to 4.0.0's).
- cxe plays either engine: `CXE_ENGINE_VER=v3_0_0` (or `v3_0_0` in /data/USER/st/bq/cxe_engine.txt for every tool).
