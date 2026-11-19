# Code map

Where code lives in the refactored bot (live since v626, `bots/nova_b2782_rf6clean`). Find a function: `python3 -I tools/lab/card.py NAME --bot nova_b2782_rf6clean`.

## How the source is organised

- **One purpose per file, named for it.** The prefix is the subsystem: `econ_`, `combat_`, `move_`, `brain_`, `draft_`, `plan_`, `ward_`, `champ_`, `strategy_`. To change how banking decides, open `econ_bank_decide.cc`.
- **No feature files.** New behaviour goes in the module that owns the decision, under a real function name. A bigger model that is its own subject gets its own named module (`econ_linear_score.cc`), not a ticket-named file.
- **One compiled file.** `src/nova_all.cpp` is the only `.cpp`. It includes every `.cc`, so the whole bot is one translation unit and `-O3` inlines across modules. The platform build compiles every `*.cpp` and has no LTO, which is why the parts are `.cc`.
- **Order in `nova_all.cpp` matters.** A file may use what an earlier file defined. A new `.cc` must be added there, after what it depends on. `brain_*` comes before `combat_*`, which comes before `econ_*`, so code using econ state goes in an `econ_` file or later.
- **`<module>_internal.h`** holds what every file of that module needs in scope. **`<module>_flags.h`** holds the flags and tunables only that module reads; `common_flags.h` holds those read by several.
- **Preprocessor conditionals:** only three remain, all `#ifdef __wasm__` (one in `common.h`, two in `board_views.h`), choosing a SIMD path that the native test engine (`tools/cxe`) cannot compile.
- **File size:** the largest file is about 1,130 lines; the longest function under 200.

## Champions

One pair per champion: `champ_NAME.h` holds the rule card (stats, slots, passive, with GameRules.md lines), the passive's formula and the hooks shared code asks; `champ_NAME.cc` holds rules of its own where it has any. Shared models call the champion's function instead of restating its passive: for example `heart_layer::damage_mult`, `ren_layer::retaliation_damage`, `vesper_layer::gold_pct`, `marcella_layer::tribute_gold`. Stellar has no passive and no rules of her own, so her file is the card alone. Champion draft scores stay in `draft_*.cc`, because a draft decision compares champions.

## Strategies

`strategy.h` documents the steps. A strategy is one `strategy_NAME.cc` defining a `Policy`, registered in `strategy_registry.cc` and listed in `nova_all.cpp`. Every field defaults to no change, and today every strategy has `select_score` unset, so real games play BASE. Decision points: draft selection and pick values, the item build, target gem and gold value, engage and flee bars. Selection may use draft-time map features only. To add a decision point, add a defaulted field to `Policy` and read it at the decision.

## Adding behaviour

1. Put the code in the module that owns the decision. Keep the flag read first: `if (FLAG_ON(1) && helper())`.
2. `python3 -I tools/lab/newfeat.py BASE NAME FLAG --module econ` copies the bot and adds the flag table to `econ_flags.h`. Other modules: combat, brain, move, draft, plan, common.
3. `firecount.py ... --base BASE` counts the functions the new bot has and BASE does not; `prearm.py` passes `--base` itself.

The lab tools accept both this layout and the old one (v625 and earlier).

## File list

### Turn loop (brain)

| File | Purpose |
|---|---|
| brain.h | Per-champion turn: perception, comms and the decision state machine. |
| brain_capture.cc | Capture holds and contests. |
| brain_claims.cc | Publishing claims and tasks to mates. |
| brain_flags.h | turn flags and tunables. |
| brain_help_fight.cc | Help calls and the fight layer. |
| brain_internal.h | what every brain_*.cc file needs in scope: the headers it uses and its file-local macros. |
| brain_low_hp.cc | Low health turns and holds near Willow. |
| brain_modes.cc | Mode loops and the spin at turn end. |
| brain_play.cc | play_turn: analysis, the turn, its tail and background work. |
| brain_setup.cc | First-turn setup. |
| brain_state.cc | Turn tunables and shared turn state. |
| brain_tie_shop.cc | Tie seek and shop recall. |
| brain_tribute_doom.cc | Whether a tribute channel dies before it completes. |
| brain_turn.cc | The turn: one function per stage; a stage that returns true used the turn. |
| brain_yields.cc | Giving up my tile for a stuck or hurt mate. |

### Economy: choosing targets

| File | Purpose |
|---|---|
| econ_choose_target.cc | Bounds, best group, choose_target, join and filler targets. |
| econ_late_picks.cc | Dominant commits, gated team, hoard and hold-group decisions. |
| econ_linear_score.cc | the linear target score. |
| econ_linear_score.h | the linear target score: flags and interface. Used by choose_target, retarget and rate. |
| econ_opening_finish.cc | The opening: leaving it, spawn step and start recall. |
| econ_opening_pick.cc | The opening: which group each body takes first. |
| econ_opening_walk.cc | The opening: prestep and start walks. |
| econ_rate.cc | Rate of a group, part 3: bag and foe limits and the final rate_for. |
| econ_rate_contest.cc | Rate of a group, part 2: contest, denial and hoard modifiers. |
| econ_rate_crew.cc | Rate of a group, part 1: crew timing and waiting modifiers. |
| econ_retarget.cc | refresh_target: when a body changes its target. |
| econ_ring.cc | Ring altar maps. |
| econ_value.cc | Reward of a group in gems: weights, game phase, need. |
| econ_value_helpers.cc | Small valuation helpers shared by value, rate and choice. |

### Economy: at the group

| File | Purpose |
|---|---|
| econ_approach.cc | Walking to the group: progress and crew present. |
| econ_camp_focus.cc | Which camp of a group to hit. |
| econ_capture.cc | Who captures, recall off a capture, leave or hold. |
| econ_idle.cc | Idle moves, side scouts, camp-out and capture pay-in. |
| econ_siege_state.cc | State of the team siege (SG3); the turn logic is econ_team_ops.cc. |
| econ_staging.cc | Near and respawn staging. |
| econ_tank_support.cc | Tank and support play at the group. |
| econ_target_turn.cc | One target turn: walk, wait, engage. |
| econ_team_ops.cc | Team siege operations (SG3). |

### Economy: banking, items, recall

| File | Purpose |
|---|---|
| econ_altar_hold.cc | Holding an altar against foes. |
| econ_bank_decide.cc | Whether to bank now (want_bank) and the distance helpers it uses. |
| econ_bank_race.cc | Race timing: bank-first and finish estimates. |
| econ_bank_walk.cc | Walking to an altar and starting the tribute channel. |
| econ_bank_win.cc | The game-winning bank and its escorts. |
| econ_items.cc | Build order and emblem ranking. |
| econ_locks.cc | Altar locks: hitting, reading and watching them. |
| econ_recall_heal.cc | Heal, shop and recall rules. |
| econ_shop.cc | Buying at the shop. |
| econ_tribute_gates.cc | What econ asks before starting a new channel: the foe that ended my last tribute, the restart hold and the |

### Economy: travel

| File | Purpose |
|---|---|
| econ_crystal_mid_hops.cc | Mid-map crystal hops and crystal trips to a bank. |
| econ_crystal_plan.cc | Whether and when to carry and use crystals. |
| econ_crystal_spawn_route.cc | The spawn crystal route: preparing, walking and landing it. |
| econ_shortcuts.cc | Dash shortcut fields across holes. |
| econ_travel.cc | Walk cost to groups: gated, recall and stored travel. |
| econ_travel_gates.cc | Gates on my way: dash routes and gate state. |

### Economy: knowledge and state

| File | Purpose |
|---|---|
| econ_clear_estimate.cc | Time and damage to clear a camp group. |
| econ_comms_fields.cc | Shared-memory initialisation and occupancy fields. |
| econ_comms_protocol.cc | Shared-memory protocol: reads, writes, foe and map posts. |
| econ_crews.cc | Which mates form a crew at a group, and crew clear estimates. |
| econ_flags.h | economy flags and tunables. |
| econ_forward.h | Forward declarations: economy functions used before their definition. |
| econ_group_helpers.cc | Geometry, crew-on-the-spot and fighting-a-group helpers. |
| econ_groups.cc | Camp and group status memory, ownership, quiet tracking, awake and living members. |
| econ_internal.h | what every econ_*.cc file needs in scope: the headers it uses and its file-local macros. |
| econ_observe.cc | Per-turn memory update and intel. |
| econ_state.cc | Economy tunables, shared types and per-game state; the cached list of items I own. |
| econ_team_model.cc | Kit damage, member stats, the team table, claims, crew size for a group. |
| econ_threat_sense.cc | What this body felt: threats and blacklists. |
| econ_ward_intel.cc | What our wards tell the economy about groups. |

### Combat

| File | Purpose |
|---|---|
| combat.h | Threat model, engage/retreat decisions, focus targets and ability use (generic, from kit metadata), and the |
| combat_act_first.cc | The act-first fallback. |
| combat_assess_contact.cc | Assess, part 1: first contact and hidden-damage tracking. |
| combat_assess_power.cc | Assess, part 2: summing the power of both sides. |
| combat_assess_rules.cc | Assess, part 4: the override rules and assess itself. |
| combat_assess_stance.cc | Assess, part 3: ratios, focus and the base stance. |
| combat_burst.cc | One-turn kill estimates. |
| combat_burst_reach.cc | Stun reach, burst timing and the zones built from it. |
| combat_calm.cc | Casts on a calm turn. |
| combat_camps.cc | Camps and camp casts. |
| combat_cast.cc | Spells and raw attacks in a fight. |
| combat_deny.cc | Altars, locks and tribute denial. |
| combat_dps.cc | Damage over a horizon and kit strength. |
| combat_fight_actions.cc | The actions of a FIGHT turn. |
| combat_fight_bush.cc | Bush tiles in a fight. |
| combat_fight_turn.cc | FIGHT turn variants and the fight entry point. |
| combat_flags.h | combat flags and tunables. |
| combat_flee.cc | The FLEE stance, retreat and refuge. |
| combat_foes.cc | The Foe record, its memo and unreachable foes. |
| combat_forward.h | Forward declarations: combat functions used before their definition. |
| combat_geometry.cc | Tiles, reach, dash legality and danger zones. |
| combat_internal.h | what every combat_*.cc file needs in scope: the headers it uses and its file-local macros. |
| combat_lethal_burst.cc | The lethal-burst model: incoming nukes and escape tiles. |
| combat_memory.cc | Observe and the per-round combat trackers. |
| combat_recall.cc | Whether a recall is safe. |
| combat_rules.cc | Kit values and rule numbers for damage. |
| combat_state.cc | Combat tunables and the shared types and state of the fight modules. |
| combat_team.cc | Mates, focus choice and help. |

### Champions

| File | Purpose |
|---|---|
| champ_ci.cc | C&I LAYER, Cassi & Issac's rules (hooks and flags: champ_ci.h). Holds the pair link (linked_slot, linked_bag, |
| champ_ci.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Cassi and Issac |
| champ_heart.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Heart of Ruin |
| champ_marcella.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Marcella |
| champ_prism.cc | The Prism map plan (draft side), its decoding (play side) and the carrier's shared helpers. The banking, capture and shopping |
| champ_prism.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Prism |
| champ_ren.cc | REN LAYER, Ren's functions (hooks: champ_ren.h). Holds his retaliation per hit (ren_ret_on), the retaliation a cast |
| champ_ren.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Ren |
| champ_ryth.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Ryth |
| champ_stellar.h | this champion's rule card. Stellar has no passive and no rule of her own, so there are no hooks: every Stellar |
| champ_tavi.cc | TAVI LAYER, Tavi's rules (hooks and flags: champ_tavi.h). Holds TVG (rent then Greed: on spawn he sells his latest |
| champ_tavi.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Tavi |
| champ_varg.cc | VARG LAYER, Varg's own functions (hooks and flags: champ_varg.h). Unity build: one translation unit, so combat's |
| champ_varg.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Varg |
| champ_vendetta.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Vendetta |
| champ_vesper.cc | VESPER LAYER, Vesper Vale's rules (hooks and flags: champ_vesper.h). Holds the dash into range |
| champ_vesper.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Vesper Vale |
| champ_willow.cc | WILLOW LAYER, Willow's rules (hooks: champ_willow.h; flags: champ_willow.h). The team's healer: her partner pick |
| champ_willow.h | this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Willow |
| champions.h | one file pair per champion: champ_NAME.h (rule card, passive, hooks and flags) and, when it has rules of its own, |

### Strategies

| File | Purpose |
|---|---|
| strategy.cc | works out the active strategy each turn and carries the plan through draft memory. |
| strategy.h | whole-game strategies. A strategy is a Policy: a small struct of knobs and optional functions, read by the shared code |
| strategy_altar.cc | the ALTAR strategy. Altar control: locks, banking behind them, denying theirs. |
| strategy_base.cc | the BASE strategy. The default play: every decision as the shared code makes it. |
| strategy_center.cc | the CENTER strategy. Take and hold the middle's heavy groups with a crew or pack. |
| strategy_econ.cc | the ECON strategy. Farm our side, bank on tempo, contest only what is free. |
| strategy_raid.cc | the RAID strategy. Pressure in their half: pick-offs and denial. |
| strategy_registry.cc | every strategy, in Mode order. Adding a strategy: see strategy.h. |
| strategy_siege.cc | the SIEGE strategy. Team sieges of bosses and the heaviest groups. |

### Movement

| File | Purpose |
|---|---|
| dashnav.cc | Dash routes (pathological-map fix): goal-directed travel for champions with a dash, over ground that walking |
| dashnav.h | Dash routes (pathological-map fix): goal-directed travel for champions with a dash, over ground that walking |
| move.h | Pathing with SDK distance fields (cached per target), safe stepping and short dynamic searches. |
| move_awake_camps.cc | Camps that may still hit me out of sight. |
| move_camp_threat.cc | The awake camps that would hit a tile. |
| move_dash_blocks.cc | Launch tiles and corridors blocked for dashes. |
| move_escape.cc | Escapes: out of reach, priced, nearest safe tile, ring, toward a rally. |
| move_fields.cc | Walk fields per group and home. |
| move_flags.h | movement flags and tunables. |
| move_internal.h | what every move_*.cc file needs in scope: the headers it uses and its file-local macros. |
| move_retreat.cc | Step away, camp lists, reach guards and retreat. |
| move_state.cc | Move tunables, shared state and board helpers. |
| move_step.cc | One step, travel dashes and stepping down a field. |
| move_thin_holes.cc | Thin-hole skips: walk then dash. |
| move_turn_order.cc | Tie priorities and this round's and next round's turn order. |
| move_walls.cc | The turn's move mask and tiles that refused me. |

### Draft and plan

| File | Purpose |
|---|---|
| draft.h | Draft v3: map analysis and the replicated map features on the first (10x fuel) turn, lineup values from the fitted |
| draft_fit_features.cc | Map features for the draft, computed at runtime from MapInfo (mapinfo.h) plus a forward dash closure that uses dashnav's dash |
| draft_fit_features.h | Map features for the draft, computed at runtime from MapInfo (mapinfo.h) plus a forward dash closure that uses dashnav's dash |
| draft_flags.h | draft flags and tunables. |
| draft_internal.h | what every draft_*.cc file needs in scope: the headers it uses and its file-local macros. Draft design: maps |
| draft_lineup_search.cc | Exact lineup search and its fuel estimates. |
| draft_map_features.cc | Map features computed on the first draft turn. |
| draft_memory.cc | What the draft stores for the game. |
| draft_prism.cc | Prism's carry plan from the map's layout, for the draft. Map features only (groups, camps, altars and their walks from M); no |
| draft_state.cc | Draft tunables and state. |
| draft_turn.cc | play_draft: the draft turn. |
| draft_value_table.h | GENERATED table. Do not edit. Draft phase-0 table: per-team-size champion values (REPL-88, m1 play) + EB-shrunk m3d play shift, |
| draft_values.cc | Champion and lineup values. |
| mapfeat.cc | Draft map features. The nine features of the REPL table, computed once on the first draft turn from MapInfo plus fitfeat's |
| mapfeat.h | Draft map features. The nine features of the REPL table, computed once on the first draft turn from MapInfo plus fitfeat's |
| mapinfo.cc | Static map analysis shared by the draft and the champions. Computed once per bot instance, in fuel-bounded, |
| mapinfo.h | Static map analysis shared by the draft and the champions. Computed once per bot instance, in fuel-bounded, |
| plan.h | Draft-memory encoding/decoding and the team plan: body slots, roles and parties. |
| plan_exact_travel.cc | Exact travel tables built during the draft. |
| plan_flags.h | plan flags and tunables. |
| plan_internal.h | what every plan_*.cc file needs in scope: the headers it uses and its file-local macros. |
| plan_map_classes.cc | Map classes, decided from draft-time map features. |
| plan_memory_encode.cc | Draft memory: tunables and encoding. |
| plan_memory_packed.cc | Packed draft memory: layout and readers. |
| plan_roster.cc | The plan: roster, tank order, carriers and capture order. |
| planner.cc | Planner: a camp-state model for every group, route planning over sequences of groups with spare fuel, and capture routing to the |
| planner.h | Planner: a camp-state model for every group, route planning over sequences of groups with spare fuel, and capture routing to the |

### Wards

| File | Purpose |
|---|---|
| ward.h | Wards on hot spots, scored from map features at runtime (never from map identity): - camp groups, by value (monoliths dominate) |
| ward_act.cc | Placing a ward this turn: scout, react, hold and act. |
| ward_analyse.cc | Background analysis of where wards go. |
| ward_bush.cc | Placing wards on bushes. |
| ward_coverage.cc | Coverage, watches and known ally wards. |
| ward_internal.h | what every ward_*.cc file needs in scope: the headers it uses and its file-local macros. |
| ward_spots.cc | Candidate ward spots and their weights. |
| ward_state.cc | Ward tunables and background analysis state. |

### Shared

| File | Purpose |
|---|---|
| allocator.cc | Replaces global new and delete with size-class free lists (fuel). Why: every container growth, std::vector copy and |
| board_views.h | Fast views of engine buffers: grids, bitboards and distance fields. |
| calc_fixes.h | Corrections to damage and cost calculations. Integer switches only; every one at 0 leaves the uncorrected |
| common.cc | Shared helpers: the roster and the Kit table read from the engine's designs, and kit damage estimates. |
| common.h | shared includes, the flag headers, small helpers, fast readers for engine buffers and the Kit description. |
| common_flags.h | flags and tunables read by more than one module. |
| comms.cc | The 8-byte team shared-memory protocol. bytes 0..5: one claim byte per body slot: bits 0-6 = target group index + 1 (0 = none), |
| comms.h | The 8-byte team shared-memory protocol. bytes 0..5: one claim byte per body slot: bits 0-6 = target group index + 1 (0 = none), |
| contest_play.cc | Contested zone: how bodies play it. CONTEST: the zone plan, play side (see contest_play.h). |
| contest_play.h | Contested zone: how bodies play it. CONTEST: the play side of the zone plan. On maps whose drafted zone passes the |
| contest_zone.cc | Contested zone: computed in the draft from the map layout; memory block. CONTEST: contested zone, swing gate and |
| contest_zone.h | Contested zone: computed in the draft from the map layout; memory block. CONTEST: the contested zone of the map, |
| econ.h | Target valuation and selection, crews, capture, banking and tribute, recall safety and shopping, item builds. |
| engage.h | Engage decisions: when a body starts a fight it can win. Integer switches only (never #if on a float); every switch at 0 |
| fast_reads.h | Fast reads of positions and my items, and memory copy helpers. |
| fuel_meters.h | Fuel meters and guards: what a turn may still afford, spin and bail helpers. |
| intel.cc | Team intelligence: enemy sightings and camp-group news, from this champion's own vision (which includes its ward, also while the |
| intel.h | Team intelligence: enemy sightings and camp-group news, from this champion's own vision (which includes its ward, also while the |
| item_upgrades.h | Item plan constants and upgrade flags (Power or Bruiser, build plans per strategy). |
| kill_gold.h | Kill-gold rules: when a kill's gold changes what we buy or chase. Int switches only (never #if on a float). EMB_MAP |
| kit_data.h | The roster and Kit: a champion's stats, slots and passive flags, read from the engine's designs. |
| main.cc | Bot entry point: runs the draft or a champion turn, catching errors. |
| multipliers.h | Every emblem damage, gold and timer multiplier, in one place. One helper for every emblem damage / gold / time |
| nova_all.cpp | the only compiled file (one translation unit, so -O3 inlines across modules; the platform build has no LTO). Order |
| race_estimate.h | Estimate of when the race to the winning gem count ends. The foe team's finish predictor, pure (no game state). |
| rules.h | Game rule values, read from the engine where possible; gold, capture, tribute and recall formulas. The bot models four |
| runtime_switches.h | A behaviour switch read at run time from one data array, so a candidate that flips a slot differs from its |
| squad.cc | Squads per objective: which bodies work together, chosen each turn from their objectives (see squad.h). |
| squad.h | Squads per objective: which bodies work together, chosen each turn from their objectives. Top bots are alone about 48% of |
| world.cc | Per-turn perception snapshot shared by brain, econ, combat and move. |
| world.h | Per-turn perception snapshot shared by brain, econ, combat and move. |
