# Rules gaps in the bot

Places where the bot's code disagrees with GameRules.md (GR) or docs/interactions.md (INT), found by a static audit of the live bot's source on 8 Nov (v625). **Fixed in v627:** C1, C2, C3, E1, E2, E3 and E7, along with the Heart of Ruin, stunned damage and map-features items below. Everything else here is still open.

Read each entry knowing three things:
- **Nothing was measured.** No firing counts and no games. "Live" means the path runs under current flag values. Size any fix before building it.
- **A fix is not automatically a gain.** Most entries had a fix bit that was off in v625; some of those may have been tested and failed. Check the idea history (`python3 -I tools/lab/ask.py "words"`) before re-building one.
- **The off-path code is gone from the live bot.** Recover it with `python3 -I tools/lab/deadstrip.py find FLAG nova_rf6_strip` (report in /data/USER/st/deadstrip/nova_rf6_strip) or from `nova_b2769_ems_glate`.

Locations are file and function in `bots/nova_b2782_rf6clean/src`. The flag in brackets is the off bit that held the fix.

## Wrong: a live decision uses a model the rules contradict

### Combat
| # | Where | The code assumes | The rule | Notes |
|---|---|---|---|---|
| C1 (FIXED in v904, RC C1352) | combat_burst.cc `my_burst_m` | A melee body at range + 1 can walk in, hit and also cast a walk-excluding spell | "Excludes walking" spells can't share a turn with a walk (GR:430, INT:27) | False `kill_now` for Marcella, Ren, Ryth. [B861 bit 16, RI bit 1] |
| C2 (FIXED in v904, RC C1352) | combat_burst.cc `my_burst_m` | A basic hit is always available | One attack; ranged walk or attack (GR:100-102, 118; INT:25) | The comment describes a guard the code lacks; `mba_hit` is unused. Callers after a body has acted were not traced. [BH63 bit 1] |
| C3 | combat_foes.cc `foe_of_calc`, combat_burst_reach.cc `foe_next_turn_reach` | A stunned foe has reach - 1 | It loses its next turn, or has a further full turn (INT:34, 36) | `f.burst` is not reduced at all, and `lethal_burst_damage_sum` does skip the lost turn, so the models disagree. Possibly a deliberate hedge. [STP, BH81 bit 1] |
| C4 | combat_cast.cc `attack_champion`, champ_willow.cc | The first hit deals raw Strength | Damage carries every modifier (INT:41, 67) | The reset can be spent on a target the first hit killed. Narrow. [BH74] |
| C5 | combat_camps.cc `prestep_hit_camp` | A free-hit camp kill needs camp HP <= raw Strength | Vendetta's kills refund, camps included (GR:626); Monster and Collectors raise damage | Her refund is missed for that turn. Narrow. [RI bit 2] |
| E-PR1 | champ_prism.cc:57-76 (prism_plan flags bit 2 -> Prospector first, prism_carrier_shop_build :1032) | An own-side group holding >= 1 gem cluster contributes its WHOLE gem count (clu += g.gems); Prospector goes first at clu >= 30 | Prospector adds 25% of the holder's share of the group's CLUSTER reward only (GR:295-297, INT:96): a 7-gem cluster beside a 36-gem golem counts 7, not 43 | RC C1244 (13 Nov). The shared kit path (econ_items.cc item_cluster_map :80-103, 7 x gem clusters, mixed groups capped) and EMD (emd_cgem :674-684) count cluster reward correctly. Issac buys Prospector-HP first unconditionally (champ_ci_plan.cc:363). Gold clusters also get the 25% (GR:295), and no test counts them for Prospector. |
| E-CE1 | econ_clear_estimate.cc ~:124-130 (estimate_cx; copy econ_rate.cc tfe_feasible) | Every living attacker hits the crew for the whole time until it dies (lowest HP first) | A monster attacks the nearest champion within its Chebyshev reach and does not chase (GR:192, GR:209; INT:109-110): attackers whose reach covers no crew body deal nothing | RC C1249 (13 Nov). Over-counts wide groups (48-wolf pack ~62k). Model-wide and play-changing: behaviour lane (SWG bit 1 is the first fix, wolf packs >= 12). |
| E-HM1 | econ_rate.cc:494 (tfe_feasible) + econ_clear_estimate.cc:143 (estimate_cx) | Crew heal and shield subtract 1:1 from RAW camp damage | The budget is effective HP (hp / camp_mult, econ_team_model.cc:165), so a healed HP on a mitigated tank absorbs 1/camp_mult raw damage: heal under-credited x1.43 (Jungle) to x1.59 (Jungle + Durability) | RC C1301 (13 Nov), VV spec_hmx_1113 (HMX bit 1). Also: a solo body's heal is never credited (heal_first, econ_rate.cc:416-421). Behaviour lane. |

### Turn order and movement
| # | Where | The code assumes | The rule | Notes |
|---|---|---|---|---|
| M1 | combat_burst.cc `EdRanks::foe_rank`, combat_burst_reach.cc `turn_order_ranks` | Rank = visible bodies with strictly higher priority | Ties break by draft order; dead and unseen bodies keep their place (GR:129; INT:9, 14, 16, 21) | The largest item. With equal foe priorities every foe gets rank 0, giving false two-turn foes and some undercounts. Feeds LETHAL_BURST, FLD, IRB, ED. `miss` also uses our body count, not the foe roster. [TOH, TOC] |
| M2 (FIXED in v904, RC C1352) | combat_geometry.cc `dash_middle_tile_ok` | An empty enemy-spawn tile or pending crystal landing can be a dash middle | Both block (INT:129) | Heart landings, escape_dash_turn, lethal escape. Rare |
| M3 | combat_geometry.cc `dash_legal_between` | A foe seen only through my ward does not block | It counts as visible (INT:129) | Rare. [RC4 bit 32] |
| M4 | combat_cast.cc `cast_via_sdk` | Any rc 32 on a dash is a crystal reservation; blocks the tile 2 rounds | rc 32 has several causes (INT:125, 129) | M2 and M3 produce false blocks. [RC4 bit 8] |

### Economy
| # | Where | The code assumes | The rule | Notes |
|---|---|---|---|---|
| E1 (FIXED in v904, RC C1351) | econ_value.cc `group_value`, econ_choose_target.cc (bound), econ_capture.cc `capture_recall` | Treasure adds nothing to a capture's gold | +10 points, adding with Vesper (GR:308, 335; INT:85) | A holder's gold is priced about 10 points low. Treasure is most bodies' first emblem. [MUL bit 16, RI bit 8] |
| E2 (FIXED in v904, RC C1351) | econ_value.cc, econ_choose_target.cc | Only a carrier Prism gets Prospector's bonus | Each holder gets 25% of their share (GR:297; INT:88) | Other holders' cluster groups are underpriced, though up to 6 bodies buy it. [BH82 bit 1] |
| E3 (FIXED in v904, RC C1349) | econ_value.cc, econ_choose_target.cc, planner.cc | Marcella's tribute gold is a flat 2 per gem | It takes gold bonuses (INT:87) | About 10% of this term. [RC5 bit 16] |
| E4 (FIXED in v904, RC C1349) | champ_prism.cc `tribute_start_allowed`, combat_recall.cc `channel_safe_check` | Only lethal damage can stop a stun-immune channel | A foe lock also cancels it (GR:226; INT:114) | Marcella only: others refuse with a foe near. [RC5 bit 1] |
| E5 (FIXED in v904, RC C1349) | combat_deny.cc `protect_tribute` | Our lock protects a channel from an enemy lock | It cannot; a foe can lock an altar we locked (INT:115) | Costs about 10 gold and the carried lock. [RC5 bit 4] |
| E6 (FIXED in v904, RC C1351) | econ_recall_heal.cc `finish_target_before_shop` | Capture pays in 6 for everyone | 4 for a Capture holder (GR:313, INT:106) | Hold refused more often than warranted. [MUL bit 16] |
| E7 (FIXED in v904, RC C1351) | econ_crystal_plan.cc `sc_hop` | A crystal hop costs 4 + dt | 3 + dt for dt >= 1 (GR:275, 329) | Conservative: fewer crystal routes than warranted. CPlan already uses 3 + dt. Derived from rule text. [BH74 bit 32] |

## Approximations: deliberate or small

| Where | Difference |
|---|---|
| common.cc `kit_dps`, econ_team_model.cc `kit_dps_pack1_and_3` | Area hits capped at 3 bodies; a radius-1 area covers a pack of 4 (GR:504, 574, 604). Live on packs of 4+ |
| econ_capture.cc `capture_recall`, rules.h | Capture-timed recall starts one round later than the rules allow; rules.h calls the +1 slack. Costs a round a trip |
| combat_recall.cc `recall_safe`, some econ literals | Recall fixed at 5 ticks; Home makes it 3 (GR:310, 387). Conservative |
| combat_dps.cc `body_dps` | A stunned body counts half; `horizon_fit` uses 0.8 |
| common.cc `kit_dps` | Heart of Ruin flat x1.12 where the rule is linear; shared models replace it, `count_contest_numbers` reads it directly |
| combat_camps.cc `area_before_cc` | Camp hits priced with champion modifiers (Skirmish) instead of Monster. Prism only; both sides of the comparison share the factor |
| rules.h `kill_gold` | NOT A BUG (10 Nov): 150 x 1.33 = 199.5 floors to 199, matching the engine table (BalanceChanges.md:1220; INT:89 corrected) |
| combat_deny.cc `protect_tribute` | A mate tributing out of sight can be cancelled by our own lock (INT:116). Rare |
| econ_crystal_plan.cc `crystal_ok` | Stun bar kept for Marcella, whose crystal stuns do not stop (INT:124). Conservative |
| econ_items.cc and strategies | A second emblem of a family is possible if the strategy changes after a purchase (GR:334). Cannot fire while every game plays BASE |
| brain_capture.cc `foe_acted_before_me`, combat_assess_contact.cc `build_acting_order_table` | Rank visible bodies only (INT:14, 16). Documented in the code |
| dashnav.cc, move_dash_blocks.cc | Dash middle checked on a static board; some conservative blocks of unseen camps (INT:129) |
| move_camp_threat.cc `takes_tie` | An enemy never takes a camp tie; overstates camp damage (INT:98). Deliberate |
| combat_fight_bush.cc `bush_watched` | Any foe on a bush within 8 counts as watching (GR:355). Conservative |
| move_awake_camps.cc | Awake memory lasts 3 rounds; the rule is 2 (GR:210). Conservative by a round |

## Found by the second audit (8 Nov, v627)

Assess, flee, zone, plan, intel, comms and the turn loop, checked against the code in `bots/nova_b2783_consistency/src`. Nothing measured on v627. Sent to the Builder.

| Where | The code assumes | The rule | Notes |
|---|---|---|---|
| planner.cc `capture_rank_fit` | Vesper's table value 344 already holds her +33%, and the multiplier adds it again | One +33% (GR:335, INT:85) | Regression from v627's E3 fix. Set the entry to 259 |
| econ_observe.cc `intel_taken`, `intel_cleared` | A channel event's round is the capture round | The channel carries parity only, and news waits up to NEWS_TTL (intel.cc:882; citation corrected 10 Nov, GR:202 is camp respawn) | Timer overwrites: 52/game when measured on 6 Nov. [BH78 bit 32] |
| combat_burst_reach.cc `foe_damage_over_turns` | A foe's damage over n turns is its best single turn | Both turns can hit (INT:21) | Escape dash skipped. Use `foe_two_turn_damage`, not a plain sum |
| combat_burst_reach.cc `foe_first_hit_turn` | Cooldown c is ready on turn max(1, c) | Turn c + 1 (INT:145) | Conservative; feeds the winning-bag check. [wth] |
| brain_capture.cc `foe_leaves_before_payout` | A recalling foe leaves before the payout | Ticks left are not read, and it can cancel and act (INT:119) | Optimistic. Rare |
| combat_flee.cc `react_kite` | A ranged foe that follows must walk | Not if my step leaves me in its range, or it has a reset or dash (INT:25) | Ranged bodies only |
| intel.cc `f.died` | Return = first sight of the death + 60 | D+60 or D+61 by turn order (GR:375) | One round off on each foe death |
| combat_flee.cc `flee_stun_and_stay` | Only melee can attack after a walk-excluding stun | Spell then basic works (INT:27) | Tavi only. [FLEE_FIX XPA] |
| combat_assess_rules.cc `kill_window` | A channelling foe cannot answer | It can cancel and act (INT:119) | KWT read .5005, closed |
| combat_assess_power.cc `assess_gather_visible` | A foe on its spawn out of my reach is no threat | It can still attack (GR:153) | UFT read .496, closed; the `if (ur)` block is dead |

| combat_team.cc `react_attacker_slow` | A foe that hit me is within its range + 1 | Ren, Marcella and Ryth hit from 4 (GR:506, 668, 756) | Hit-back skipped for a ranged body at distance 3. Rare |
| combat_team.cc `channel_target_b`, `damage_spell_reaches` | A damaging stun cannot stop an immune recall | Any damage cancels a recall (GR:387) | Tavi or Ren v Marcella. Rare, conservative |
| combat_assess_stance.cc `assess_carrier_cut` | The focus's own bag sets the bar | Both C&I bags are taken (GR:381) | Uses `hf.gems`, not `hunt_prize`. Rare |
| combat_team.cc `channel_threat` | A channelling foe is no threat to my channelling mate | It can cancel and act (INT:119) | Same model as `kill_window`. Rare |

Smaller: `lb_two` is never set, so escape tiles ignore double turns; `f.burst` counts basic + spell at any distance in reach (overstates); `kill_now` misses ranged kills through a dash or a walk + reset.

## Combat, brain and movement bugs (8 Nov hunt, v627-v628)

Sent to the Builder directly (b1692, b1693, b1694). Listed so later hunts do not repeat them.

- Stunned-foe zeros in `foe_of_calc` leak into the `seen` store and channel readers (v627 regression); `parting_foes` misses a stunned chaser (v627 regression).
- `fight_stun_nuke_other` has no range test. A reset is cast before `attack_champion` refuses a Ren-lethal target (`fight_hit_focus`, `fight_hit_nearby`, `kite_shot_after_move_slow`). The splash alternate in `attack_champion` has no `kills_me` guard and ignores `bh57_noreset`.
- `W.on_spawn` is stale after a step. `escape_dash_leave` writes retreat memory before `cast_at`. `heart_dash_try_budget` never reads `t_me`. `CRX_BUS_TICKS` is 4, the channel is 3.
- `game_deny_pick` compares with `t->gems`. `assess_rounds_on_tile` sits behind the no-foes return. `slot_gold`'s `sg_vv` is a bool.
- `read_enemies` loses the recall verdict on a re-perceive. The perceive at `brain_turn.cc:703` does not save the turn flags. The move mask is not invalidated after a perceive. `help_join` publishes "coming" before the step. `walk_cast_end` uses a stale round. `rx_wc_from` is set after the ring escape. `finish_first` ignores DOM mode. `strat::begin_turn` runs before perceive.

## Second pass: fuel cuts and module contracts (8 Nov, v630)

Each was re-read against `bots/nova_b9976_rgb29/src`. Nothing measured. A separate check of the refactor found v626 equal to v625 in logic: all 233 flag tables, all 315 stripped branches, 2,295 of 2,373 functions token-identical and the other 78 read by hand.

**After a fuel cut** (GR:401: the turn resumes where it stopped, next round, on the old `W`)

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| brain_play.cc:187, main.cc:48 | Play has no re-entry after a cut; the draft does (main.cc:33-40) | A cut after the action: next round runs the leftover background work and yields, so that round has no move, attack or cast | Stop background when `round_number_nc() != W.round`, then re-run `play_turn_body` in a bounded loop |
| brain_turn.cc `turn()`, combat_cast.cc `cast_via_sdk`, move_step.cc, econ_bank_race.cc | Nothing checks the round before acting | A cut before the action: a ground spell lands where the foe stood, with the cooldown spent; a tribute starts on stale safety checks | Detect the new round and restart from `perceive` |
| brain_turn.cc:76-97, world.cc:380, brain_tribute_doom.cc:21, combat_assess_rules.cc:220 | Tests of `== W.round - 1` fail when the last turn was two rounds ago | The turn after a cut: a real foe recall reads as not real, the ring escape is off, and a cancelled tribute is missed | Compare with the previous perceived round |
| move_walls.cc:81 `note_teleport_reservation` | Uses the stale occupancy | A unit that stepped there since reads as a crystal reservation | Add a round check |
| brain_turn.cc:312, econ_idle.cc:227 `spawn_siege_find_groups` | No fuel check before a scan of up to about 45k (likely) | A heavy round-40 turn cuts before acting | `fuel() > 60000`; `ss_pending` stays set | FIXED on v868 (FGD SSF guard, brain_turn.cc:386; b2364 count 2026-11-13: 0 exhaustions, max 26.4k/scan) |
| brain_tie_shop.cc:37 | Bar of 40k for a field costing 34k on 100x100, then a step (likely) | A tie walk runs out | Raise to `3wh + 4000 + 30000` | COUNTED ~0 (b2364 2026-11-13: .007/g, 0 refusals, 0 exhaustions) |
| comms.cc:524 `spare_get` -> :531 `spare_put` (RC X505 SGL1, measured b2074 12 Nov on v787) | The team-memory read-modify-write uses the turn-start cache, so a resumed write can revert a mate's post | Measured on 200 release games (w_manygrp + w_checker_big, 0.98 cuts/g): 1 stale write, 1 real erasure (.005/g); the resumed tail rarely reaches a spare_put before a write refreshes the cache | Closed on rate (prereg KILL < .02/g); fix ready in nova_b2074_rsm SGL bit 1 (logic-identical 40/40) |
| dashnav.cc:532/:650, econ_group_helpers.cc:34, econ_tank_support.cc:686/:995, econ_threat_sense.cc:56 (RC X505 RPR1, b2074) | `== W.round - 1` streak tests reset across a cut | Same 200 games: 0 changed answers at the dashnav, hsc_held and tank sites; 17 at threat_sense:56 (3 engaged and hurt), all after a cut. There the loss spans 2 rounds against a 1-round camp prediction, so keying on the previous perceive would be wrong | Closed: no firing where the fix is right |

**Units and timing between modules** (under MUL FULL, hits and `eff_hp` are pre-Durability; hp + shield and `camp_threat` are real)

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_recall_heal.cc:918-962 `foe_dmg`, `carry_recall::ok` | Raw Strength and Focus: no `passive_mult`, no Durability, against real HP | Heart at 10% HP or a Skirmish foe under-priced: a bag recall judged safe and dies | `mult_foe_hit_to_real_hp(dmg * passive_mult(e))` |
| champ_prism.cc:343, :551-554, econ_bank_win.cc:148, :158 | A channel timer ignores that the body has already acted (GR:232) | Foe acted, left 3, my ticks 3: I land first, but it reads "foe first", so my winning channel is refused. For mates the error is reversed | Add 1 when `state & FLEE_FIX_ST_ACTED` |
| combat_deny.cc:418 v :429 | `L` adds the acted turn, `gd_mem.until` does not | An out-of-sight winning tribute is followed one round too few | Add it at :418 |
| combat_calm.cc:230-236 `visible_foes_lethal_next_turn` | `lethal_burst_hit` is pre-Durability, compared with real HP; counts a foe whose next turn is the stunned one | A Durability holder at 300 HP facing 320 (288 real) reads lethal | Compare with `eff_hp(W.me)`, skip `foe_stunned_next_turn` |
| econ_tank_support.cc:137 | `camp_threat * jf` applies the camp factor twice under CTH | A tile is accepted that the bail test then rejects | Drop `* jf` under CTH, as econ_threat_sense.cc:100 |
| combat_geometry.cc:410, :421 `danger_at`, `danger_veto` | Real `camp_threat` is added to pre-Durability burst, then compared with `eff_hp` | Durability counts twice on the camp part: about 10 HP per 100 camp damage | `mult_camp_hit_to_eff_hp` on the camp term |
| combat_flee.cc:294 `sru_in` | Identity function, though the comment says real HP; pre-Durability incoming v a real cap | Small, conservative | Restore FLEE_FIX bit 4's conversion |

**Refused actions in real games** (census on v630, 246 games v v627, every action call logged)

Refusals cost nothing in the engine, but the bot's bookkeeping after them can be wrong.

| Action and site | Per game | Cause | Note |
|---|---|---|---|
| Recall, `spin_on_turn_end` | 20.0 | rc 44: the body is stunned | Fuel only; add a stun test |
| Ward, `bush_place` | 7.6 | Returned false: a mate's ward holds the tile (INT:141) | Bans the tile 40 rounds; a stunned refusal is banned the same way |
| Move, `try_move` | 1.8 | Hidden occupant | Expected |
| Attack, `attack_via_sdk` | 0.9 | rc 42. Traced: 74% hit a foe the body's own spell just killed with no other foe in reach; the rest a dead camp or a target out of sight | Not a bug: `attack_champion` skips the alive read on purpose to save fuel, and the refusal costs nothing |
| Tribute, `bank_open_tribute_at` | 0.8 | rc 45: stunned | Harmless, but the turn's logic still ran |
| Ward, stunned (several sites) | 0.8 | rc 63 | Confirms the tile-ban bug's size |
| Everything else | Under 0.4 each | | Move refusals 0.08%, attacks 0.09%, casts 0.07% of attempts |

Pattern: the turn loop has no exit for a stunned turn, so a turn the engine has already taken still runs the full decision logic and records side effects of actions that cannot happen. Fix: at the start of a stunned turn, run only comms, priority and observation (probe p87: `set_priority` is the one action that still works).

## Combat walkthroughs (8 Nov, v630)

Whole turns traced kit by kit, and stance followed across rounds. Each was re-read against `bots/nova_b9976_rgb29/src`. No traced turn produces an illegal action; these waste a cast, an attack or a walk, or misjudge a state. Nothing measured. All change play, so they go on the behaviour lane.

**Melee**

| Where | Bug | Actual v correct | Fix |
|---|---|---|---|
| combat_fight_actions.cc:336 `fight_hit_focus` | The reset is only spent on a focus still alive; no retarget after a kill. Vendetta, Issac, Ryth, Marcella, Varg; ranged resets too | Attack (kill), turn ends. Should be attack, reset, attack the next foe in reach | When the focus is dead, fall through to `fight_hit_nearby` |
| brain_turn.cc:724, combat_fight_turn.cc:319 `self_shield_after_hit_turn_slow` | Shield cast before the stages, with no kill test (Varg) | Shield, one hit, focus lives. Should be attack, reset, attack (kill), shield later | Skip in FIGHT when the kill needs the reset |
| combat_fight_turn.cc:455 area cast | The area stun is cast even when only walk + hit + reset + hit kills (Ryth, likely) | Stun, no walk, no hit, foe survives | Skip the area when only the walk route kills |
| combat_fight_actions.cc:94, :129 | At distance 4, Issac and Vendetta walk to 3 and never retry the dash; Heart has `fight_heart_after_walk` (likely; may be deliberate for Issac) | Walk, no hit. By the code's own rule at 3: walk, dash, hit | Call `fight_gap_dash` after the walk-in at distance 3 |
| combat_flee.cc:425 | In FLEE with reset and dash or shield ready, the reset is spent first, so the dash or shield fails. FKD read .487 for the dash; the Varg shield half is untested | Attack, reset, attack, one step in reach | Set `bh57_noreset`, under a different gate than FKD |
| combat_fight_actions.cc:226 `fight_volley_veto` | `hit_after` ignores walk + landing + hit for Heart (likely) | Holds and idles the turn | Set it for a ready landing at `dash_r + 2` |
| combat_fight_actions.cc:283 `fight_hit_before_walk` | Bare `return`; the comment says a melee body hits what stands in reach before a long walk (dead before the strip too) | Walk, no hit | Restore or delete, after finding why it was off |

**Ranged**

| Where | Bug | Actual v correct | Fix |
|---|---|---|---|
| combat_fight_actions.cc:70, combat_fight_turn.cc:466 | `fight_stun` runs before the walk and is not retried (Cassi) | Focus at 5: walks to 4, no stun. Should be walk, then stun | Re-run after `fight_walk_in` if walk-compatible and unused |
| combat_fight_actions.cc:81 `fight_stun` | Spends the cast on the stun when nuke + basic kills (Cassi, no-damage stun) | Stun + 30. Should be nuke, then basic (kill) | Skip when `kills(f, d, KQ_RAW)` and `cc_mod <= 0` |
| combat_flee.cc:367, combat_fight_turn.cc:31 | Refuge paths call `free_aoe` only | Cassi, Tavi: no cast on a foe in range. Should try the nuke or stun | Use `free_cast` |
| combat_flee.cc:329, `lethal_burst_flee_turn` | Early returns skip `kite_shot_after_move` (likely) | Walk and end. Should be walk, reset, shot | Call it at the end of those paths |
| combat_cast.cc:758 from combat_flee.cc:138, :529, :586 | The reset is spent before `free_cast`, which then does nothing (Tavi, likely) | Attack, reset, attack (90). Should be attack, 1.6 x Focus stun | Set `bh57_noreset` when a damaging stun is available |
| combat_fight_actions.cc:341 `fight_hit_nearby` | First listed foe, spawn not filtered | Should be the weakest in reach | Use `fight_weakest_in_reach` |
| brain_turn.cc:215, econ_shop.cc | A field shop has no `refresh_self` (Tavi) | Assess that turn uses old stats | Refresh after a buy |
| combat_flee.cc `flee_nuke` | Comment says "or the area on 2+"; the code never casts the area (Stellar, likely) | Walks with no area cast | Add it, or fix the comment |

**Across rounds**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| combat_fight_actions.cc:310 `fight_walk_in` | `c.f` is a turn-start copy with no alive check | The spell kills the focus at distance 4; the body walks to its empty tile and the turn ends | After the casts, if the focus is dead, run `fight_hit_nearby` and skip the walk |
| combat_flee.cc:546 `continue_retreat_slow` | Any foe in `a.foes` ends it, including remembered ones, and `a.nearest` comes from visible foes only | The chaser leaves sight within 4 rounds: the retreat lapses and the body farms inside the threat zone | Return false only if some foe is not remembered |
| combat_foes.cc:267 `fresh_recall`, world.cc:381 | The world mask already hides a fresh recall, so the second layer treats the first real round as fresh | A foe's recall gets no target or hunt bonus until a round late; first seen at left <= 1, it is skipped on the last chance | Drop the first-round test for masked bodies |
| combat_flee.cc:556 | A renewed retreat assigns `retreat_until` without max | A crystal jump's r+8 shortens to r+6 | `std::max` |
| combat_team.cc:419, combat_assess_power.cc:37 | Channelling mates count as present (likely) | A lone body keeps a 1v3 or starts a hunt into 2 | Add `!al.channeling()` |
| combat_assess_power.cc:156 | The hunt lock is never released (known, audit 97; HUNT_TTL read flat) | The lock outlives its reason | Bundle only |

## Lifecycle walkthroughs: economy, wards, pathing (8 Nov, v632)

Bodies followed round by round through a whole job. Each was re-read against `bots/nova_b9979_sgvcache/src`. Nothing measured unless stated. All change play. "Likely" means the intent or engine needs checking.

**Bank trips**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_bank_decide.cc:335, econ_target_turn.cc:188, econ_team_ops.cc:841 | `T.bank_until` is never cleared | A wait of 50 rounds: a tribute lands, then a 6-gem capture bag still makes the altar trip, skipping every bar, until the 50 is up | Clear when `gems <= 0` and on a target change |
| champ_prism.cc:603 `channel_start_ok`, :640 `channel_doomed`, econ_bank_win.cc:243 | No end-of-game exit | r1985, 80 gems, foe known at 7: the channel is refused and cancelled until the bag is too late, and it is worthless at r2000. Non-Prism `tribute_start_allowed` too. WB2_LASTCALL read flat before, so size first | Owner approved the Prism part on 8 Nov as an exception to the 3 Nov banking rule. When waiting another round would land the channel after round 2000, allow it and do not doom it, Prism and non-Prism |
| brain_tribute_doom.cc:57 | The low-HP return has no `!td_win` (likely intent) | Winning channel, 30% HP, a camp chipping 10 a round: cancelled 4 rounds from winning | Add `!td_win &&` |
| econ_bank_walk.cc:198-201 | The refusal never sets `pcf_ref` | Refused at the altar, `farm_turn` walks off, `want_bank` walks back: up to 20 rounds of nothing | Set `pcf_ref = W.round` on those returns |
| econ_bank_walk.cc:375, :409, :476 | Twin-altar walk loses to the bank field | One lock hit per 2 rounds, and the free twin is never reached | Latch the twin until arrival |

**Farming cycle**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_capture.cc:561, brain_turn.cc:211-216 | A gold-only capture paid during a recall is compared after the shop spends the gold. Found independently twice; about 1 such recall a game in 12 live games | Walks back up to 9-16 rounds, and mates never learn the respawn | At the top of `capture()`, if the engine says state 3, mark it respawning |
| econ_target_turn.cc:390, econ_retarget.cc:135 | `T.wait_since` keeps running while the body is away | Back from a 10-round fight: `waited` 13 gives `drop_target(30)` and a crew ban, or a non-tank starts the group at once | Restart if the body was not at the group last round |
| econ_capture.cc:430 | `held = on & ~0u`; `cl_prev` unused, though the comment needs "stood on it last turn too" | A better-ranked mate passing over the region takes the capture, then leaves: the region empties and the timer resets (INT:107) | `held = on & cl_prev`, and require a claim |
| econ_retarget.cc:98-122, :248 | A squad partner flips between its best group and the seed's (likely) | Every ~6 rounds, in a band of about 1.18-1.43x | Reject non-leash picks while partnered |
| econ_capture.cc:635, :232 | `T.cap_on` goes stale after an unseen contest (likely) | The recall starts early and the reward is lost | Recompute from the engine timer on the region |
| econ_target_turn.cc:64 | `st_n` never resets with time | Looks at r100 and r300 add up, so the group is failed for 60 rounds | Reset after a gap of more than 2 rounds |

**Trips home**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_idle.cc:736 `about_to_capture` | `T.capturing` alone returns true, even far from the region (likely) | 25% HP, fled 8 tiles: `handle_low_hp` lets it walk back to the contested region for up to 16-30 rounds | Also require `cheb(pos, anchor) <= 4` |
| econ_recall_heal.cc:196, :429, econ_threat_sense.cc:157 | A cancelled recall still sets `S.recall_round` | Shop trip blocked for 20-30 rounds though the body never got home | Restore the previous value on a cancel |

**Wards**

Measured on 246 games v v627 (v630): the team's first ward at a median of round 14, a body's first at round 21; 94.3% of teams have one by r50, 99.2% by r100. Slowest: `04gem-caverns` about r130, `04comb` r80-85, `03riverbed` r65-70. Use those maps to test the fuel gate and choke fixes.

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| ward_act.cc:313, :462, :576 | `ready_since` survives death | First live turn at spawn: `waited` is 60+, the bar drops, and a scout ward lands 2 from our spawn, replacing a useful ward | `if (!W.alive) { ready_since = -1; return; }` |
| ward_act.cc:579 | The 55k `ACT_FUEL` gate sits ahead of the bush and pin paths, which cost about 10k | Any turn building fields skips the ward | Gate only the coverage path |
| world.cc:394 | `if (hidden) continue;` skips gems and cooldowns for ward-only foes, though they are readable (INT:146) | End-of-game score test counts a ward-seen 200-gem foe as 0; cooldown -1 reads as ready and blocks a safe channel | Read them before the `continue` |
| econ_observe.cc:214 | The `far` test (12) does not match the camp read radius (9) | Walking off a part-cleared group inside my ward's view reads it full, then freezes that value | Keep `hp_left` if a visible living member has no read |
| brain_turn.cc:67-83 dead_turn, world.cc:262-279 read_dead_turn (v868; foes go to W.enemies_far, not W.enemies) | A dead body's ward feeds foe sightings but not camps (INT:142) | Foes take a ward-watched group during the 60 rounds and mates are not told | `observe_group` on ward-watched groups on dead turns |
| combat_fight_turn.cc:409 `vanished_foe_last_tile` | Checks `W.enemies` only | A foe my ward still shows counts as vanished, and the ward moves away from it | Also loop `W.enemies_far` |
| brain_turn.cc:702-705 | The ward's reveal feeds no fight code (likely; bit 8 off) | A foe it reveals is in `enemies_far`, legal to hit, and is not hit | Retest bit 8, or add just that foe |
| ward_act.cc:71-81 | `react(true)` has no caller (likely; may be deliberate) | Hit from a bush by a never-seen foe: no ward | Call it before `assess`, behind a flag |

**Pathing**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| move_thin_holes.cc:328, econ_shortcuts.cc:605-607, econ_approach.cc:120-126 | A blocked plan step falls through to a step away, and the plan rebuilds | P0, P-1, P0, P-1 while a mate holds P1; a ready dash can be spent on the walk away. `mate_yield` never fires, because the body moves | If the next tile holds a visible mate, return true as a counted hold |
| move_thin_holes.cc:113, :298-303 | `free_tile` is tested only when already on the launch tile | A mate parked on the landing: about a 6-round loop, because the failed pair is not remembered | Remember the failed pair about 10 rounds |
| move_thin_holes.cc:554-583 `step_to_set` | Fuel 30-65k: a goal beyond the radius returns false with no greedy fallback; below 30k the body does step | Less fuel moves and more does not, and callers mostly have no fallback | Call `step_greedy_set` when `cur == UNREACH` and the radius was cut |
| move_retreat.cc:156, :199 | `f_home` passes camps, candidates must be free, ties are rejected (likely) | A camp column on the home line: no candidate, and the flee stands still | Use `M.f_home_cb`, accept ties |

## Prism carrier (8 Nov, v632)

Followed through a whole game. Each was re-read against `bots/nova_b9979_sgvcache/src`. Nothing measured.

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| champ_prism.cc:962-982, econ_bank_walk.cc:233-243, :409, econ_bank_win.cc:100-113, :256 | Bank timing uses the nearest altar, but she walks to the safe altar, up to 25 tiles farther. **Owner approved a fix, 8 Nov** | Bag 100, nearest 3, safe 25, foe at 16: budget 13 rounds, real 35. A winning bag 3 from an open altar can walk 25 more | Pass the distance she will walk into the timing tests (`prism_holds_bank`, `foe_finishes_before_bank`, `prism_can_win_race`); use the nearest altar for a winning bag and for why 2, 5, 6 |
| econ_bank_walk.cc:108-145, :191 `bank_channel_camp_move` | No end-of-game exit. **Owner approved, 8 Nov** | r1975, 200 gems, a camp reaches the altar tile: she waits up to 8 rounds and the channel cannot finish | Skip when `now() + ticks + CC_WAIT >= GAME_END` |
| combat_assess_rules.cc:397-408 `assess_finish_sure` | Counts the reset and `slot_dmg`, not a damaging stun, though the stun is cast first. Every kit with a damaging stun | Prism with 40 gems (stun 225), foe at 150 HP at distance 3: no fight override | Add `cc_mod * foc` when the stun is ready and in range |
| champ_prism.cc:189-211, brain_turn.cc:590-603 guard post | The comment says a threatened rich Prism; there is no threat test. Mates out of sight read -1, and `W.allies` is visible allies only | With a 60+ bag and no foe, a mate tethers to within 2; a threatened Prism out of sight gets no guard; two mates can both guard | Require a known foe within `PG_THREAT`; use comms for the out-of-sight case. May change play a lot: read it |
| champ_prism.cc:145-177, :449-462, :775-785, :855-864 | `prism_alive`, `pos_of_prism` and `bag_of_prism` mean "in my sight" (likely) | She claims a group from 10 tiles; a mate reads her as dead, captures and splits her reward. Out-of-sight mates' bags are left out of the race sum | Decide from the claim and comms; add the band bound |
| econ_bank_walk.cc:65, :76, champ_prism.cc:985 | `pc_hold_why` is stale when `want_bank` returns early | After a mate's bank makes her bag win, the value 6 blocks the recall routes | Clear it at the top of `want_bank` |

Not a bug: `cr_rich()` counts a 0-gem Prism as rich, but its comment says that is intended. Her bag cap is lifted to 1<<20, so the cap paths are no-ops.

## Every-area pass (8 Nov, v632-v633)

Each was re-read against the live source. Nothing measured. Most change play. "Likely" means the intent or engine needs checking.

**Team knowledge**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| comms.cc:423 `legacy_in`, econ_comms_protocol.cc:228-234, intel.cc:817 | Two channel entries feed one event image; `LegacyQ lq` is unused | A HELP and a sighting read in one turn: one is lost. Likely several per game in fights | Queue types 0-3 in `lq`, have intel drain it, keep HELP in the image |
| econ_comms_protocol.cc:171, :680 | Entry = parity + code, so a repost at an even offset changes nothing and readers skip it | A sustained rally ages out at mates after 5 rounds | If `cmp_ent(all,e) == v`, treat as dropped and retry; make REPOST 9 |
| intel.cc:940-951, econ_comms_protocol.cc:670 | A dropped post is treated as sent | A TAKEN or CLEARED is lost for good, and a sighting is blocked 8 rounds | If `bhf_lp == 0`, restore the image and skip the erase and `last_ev` |
| intel.cc:458, :504 | Dead foes stay in mates' reports (likely) | `danger` stays 2 for up to 30 rounds; a dead foe's report blocks recall | Cap `team_n` at `foes_alive`, subtract deaths |
| econ_observe.cc:84, econ_clear_estimate.cc:67 | GS_CLEARED never expires; the fix (BLF bit 2) is banked | Zero clear cost on a group that has respawned | Retest BLF bit 2 alone |
| comms.cc:51 | The retreat fit test is left over from slim 2 | On maps with 7, 39 or 103 groups a retreat encodes as "in fight" | Drop the test under slim 4 |
| econ_comms_protocol.cc:613, :680, :723 | After a fuel cut, `all` is last round's word (likely) | A mate's newer entry reverts | Re-read the host word inside `spare_put` |
| econ_comms_protocol.cc:113 | `m.seen >= p-1` discards a mate's newer post (likely) | News lost if I left vision that round | `m.seen >= p`, or check visibility now |
| econ_observe.cc:217 | Ward sight of a group that respawned unseen keeps the old low `hp_left` (likely) | Clear time underestimated | Correct on a ward read |

**Endgame and denial** (engine p88: a tribute landing in round 2000 counts; the bot's bound agrees)

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| brain_turn.cc:692, combat_deny.cc:562 | A channelling body never denies a game-ending channel | Them 900, foe channelling 150; my body on a recall or small tribute, holding a lock or stun: the foe lands. Cancel then act is legal (INT:121) | In `channel_holds`, cancel when a seen channel ends the game, lands before mine, and I can stop it this turn |
| combat_deny.cc:95-99, :348 | A mate's channel at the altar vetoes the lock | We lose the game to protect a 20-gem channel; its gems stay in the bag (INT:118) | Ignore the mate unless its own channel wins and lands first |
| brain_turn.cc:307-310 | The winning-bag walk runs before `game_deny` | Foe lands at r+2, I land at r+8, a step and a stun would have stopped it | Run `game_deny` first when the foe lands before my walk + ticks |
| combat_deny.cc:90, :326, combat_cast.cc:342, econ_bank_win.cc:232 | Each channel is tested alone v 1000; landing after r2000 is not tested (r2000 part likely) | Two 30-gem channels at them 960; an 80-gem channel at r1996 counted as ending | Sum by landing time, drop any landing after 2000 |

**Openings and unusual maps**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_opening_walk.cc:133-212, econ_opening_pick.cc:230 | Presteps walk to an estimated goal before the body's own simulation ends; the sim rates from spawn; the `om_v` veto is always false | Owner replay 01a1bb47: Vendetta north r2-5, back r6-8, south from r9, about 7 rounds lost. Common on 60x60+ | While the sim is pending, step only if not uphill for the top unheld candidates, or cap presteps at 2 |
| CORRECT, NEVER REACHED (10 Nov, b1808: 0 dashers without an altar route in 320 fresh + 96 targeted team-games) econ_value_helpers.cc:69 `nwc_map` | `!dn::dasher()` assumes a dash route exists; walls cannot be dashed | Wall-sealed altars: dashers never bank, and the draft forces 2+ dashers there | Allow a dasher whose altar route is finished and UNREACH |
| econ_crystal_plan.cc:250 `crystal_step` | Tests foes near me, not at the landing | The uncancellable channel lands next to a seen foe | Also skip when `cheb(e.pos, land) <= 4` |
| econ_crystal_plan.cc:131 | The launch can be a living camp's tile (likely) | Body oscillates, crystal unused | Test against `M.block_camps` |
| econ_ring.cc:48 | `ring_gap` stays true 60 rounds after a gap shuts (likely) | Body drifts at the ring | Clear `ring_signal` when the breach is seen shut |

**Draft** (memory writes and reads match field by field at every team size; no map identity)

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| draft_turn.cc:104-106, :126-129 | Two gates judge the plan without Prism held, though she is forced first (likely) | A pointless Vesper swap, or a missed C&I demotion | Compute `eff` as at :174-181 |
| brain_play.cc:33, mapinfo.cc:568, :579 | `M.lean` set in play even when the decode failed | Every `d_enemy` is UNREACH all game. About 0 today | Clear `lean` before the distance stages |
| draft_turn.cc:366, :372 | Reads enemy picks and discards them | Fuel only; the rule is no use of enemy picks | FIXED v698 (fxb18z removed the read; X187) |

**Fighting camps**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| combat_camps.cc:560-587 `camp_abilities_stun` | Two stunners pick the same camp; nothing reads `sdk_camp_buffs` | Stuns do not stack: one hit cancelled, both cooldowns then aligned, repeating every cycle | Skip a camp with a pending stun |
| combat_camps.cc:739-745 `next_camp_in_reach` | `W.camps` is turn-start, so a camp the splash killed still lists | Varg's reset spent, no second hit | Add `camp_alive_in_engine` before the cast |
| combat_camps.cc:372 | A sleeping neighbour of another group only costs score | Varg's reset hit wakes that group | `continue` for a sleeping neighbour with attackers |
| combat_camps.cc:627, combat_state.cc:294 | The area counts camps my own hit killed | Area hits 1 camp when 2 were available | When attacked, skip camps not alive |
| econ_tank_support.cc:704, econ_idle.cc:447, rotate `hit_from` | No splash guard (likely) | Varg support hit wakes a sleeping group | Apply the neighbour term |
| econ_team_ops.cc:841, :809 | A joiner's bank trip lapses mates' memory (likely) | The operation ends on a 60-round cooldown | Keep the memory or re-publish |
| econ_approach.cc:243-247 `crew_here` | A hurt best tank never hands over (likely) | Both run `tank_turn` | A yields below .35 when a healthy melee claimant is here |
| econ_clear_estimate.cc:124, :127 | Stun credit uses the static `str_max` | Too low on damage after the golem dies | Use the living maximum |
| combat_camps.cc:409 | Any visible camp near the destination cancels the free hit (likely) | No pre-step hit | Only camps of the target or awake |
| econ_locks.cc:48-51 | `n_att` is tested before Vendetta (likely) | The refunded second hit is lost | Test Vendetta first |

**Champions and core**

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| world.cc:425-458 `read_allies` | Mates' buffs are never read, so `shield`, `shield_turns` and `stunned` are 0 | A shielded Varg or Heart mate adds nothing to our health in the balance; a stunned mate counts at full damage; a shielded tank is priced as unshielded | Call `read_buffs(b)` at least inside the `enemy_near` block |
| world.cc:447-457 | Mates' bags read only with a foe in my sight within 9 | `join_worth` declines a call for an 80-gem Prism; heals get no bag bonus when calm | Read `sdk_champion_gems` at those sites |
| combat_cast.cc:735, :759 `kills_me_twice` | Runs after the first hit, when HP already includes that retaliation (p89) | HP 60, retaliation 20, 40 left: reset refused though it survives | Use `kills_me` |
| champ_vesper.cc:129 `vesper_open::rank` | "Her first capture" has no end test | -5000 applies all game; a hurt Vesper does not yield the capture | Add `now() <= VOP_TAB[7]` |
| combat_cast.cc:438-441 `try_heal_slow` | Lacks the my-spawn skip that `support::heal` has | Willow spends 8 rounds of cooldown on a mate the spawn heals anyway | Add `bbget(M.my_spawn, al.pos)` |

Shield asymmetry (a model choice, not a code fault): `add_friend` counts a mate's ready shield, but `foe_of_calc` counts only a foe's active one. Adding the foe side (SHB, b1518) read .499 alone and closed on v604; worth re-reading once `read_allies` reads mates' active shields, since both sides then change.

Engine fact from p90 for Vendetta plans: a basic kill with no cast yet refunds at once, and the dash or reset can be used the same turn.

## Asymmetry, rating and builds (8 Nov, v633-v634)

Each was re-read against the live source. Nothing measured unless stated.

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_items.cc:171-184, :363-364, :399-400 | `bruiser_to_power_emblems` runs before `upitm_post`, so "before the first Power emblem (the tail)" matches a converted head entry | Measured, 246 games: Vesper's emblems run Prospector, Treasure, Capture, Tribute, Monster in 44 of 62. The report's Vendetta case does not show in real orders | Record the head size before the tail loop and search for Power only from there |
| econ_items.cc:257-258, econ_flags.h:216-217 | The Greed pass protects only Bruiser's first entry, so a converted head Power becomes Greed | A 150-gold stat emblem becomes a 750-gold one (Vesper at index 4). Maybe linked to the owner's "Greed too early" | Use the same head bound |
| econ_bank_decide.cc:220, :241, brain_play.cc:33, mapinfo.cc:568 | `M.lean` skips `f_enemy`, so `has_enemy` is false in play and two bank-bar terms are dead | Every non-Prism bank bar gets `dn` .5 and no "foe in our half" term | Derive `dn` from the stored spawn walk minus `f_home`, and use data that exists in play |
| mapinfo.cc:97-98 | Spawn anchors floor the same way for both teams | 19 of 124 maps with an even spawn size: team A group 9 away, its mirror 8 away, so only one side gets the home bonus. Also moves zones, rally, ward spots and intel | Round .5 toward the map centre on a mirrored axis |
| combat_assess_power.cc:409 v `assess_gather_visible` | A channelling mate adds 0, a channelling foe full power (also brain_capture.cc:8-25, combat_assess_rules.cc:160) | No comment says why; both can cancel and act (INT:119) | One channel weight for both sides |
| combat_assess_contact.cc:37, :46-47 | Mates join within 6 (7 with a support), foes within 8 | A real 2v2 at distance 7 reads 1v2. Widening the join read .492, .487; narrowing the foe side is untested | Test `FIGHT_R == join_r` |
| econ_value.cc:469-470, econ_choose_target.cc:176-177 | Marcella's tribute gold counted when she cannot bank | A gem cluster reads 14.21, not 0.21 | Add `&& bankable()` |
| econ_choose_target.cc:657, econ_linear_score.h:6, :19-20 | LNR's "extended rating loop" flags are read by no code (likely) | B would win on S but is never rated | Add the relaxed stop, or delete the flags and comment |
| econ_rate_crew.cc:385-389 | `v2` skips the endgame gold-only branch | r1985: a pair taken for gems that cannot bank | Same time test |
| econ_value.cc:359 | The emblem-bonus test uses the whole group's gold | Share 45, needing 60, yet the bonus fires | Test `gold_raw / crew` |
| combat_assess_stance.cc:11-14 v `assess_add_power` | Heal shares use weighted v unweighted denominators | About 1.6% on the ratio with a healer near | Same weights on both |
| fuel_meters.h:347 and strict-`<` loops | Direction ties always take the first DIRS entry | Mirror twins can go different ways. Ties 3.8% of staircases; step_field tie read flat | Bundle only: tie-break toward the goal |

## Wasted behaviour in real games (8 Nov, 246 games, v630 v v627)

Measured from replays. Both teams show these, so they are code patterns. The games predate v631-v635. Causes are not established unless stated.

| Pattern | Rate | Sample | Cause |
|---|---|---|---|
| A winning-bag Prism starts, cancels and restarts | .13 cancels/g, 32 of 45 Prism cancels | `03colosseum__b` r520-532: bag 480, 93% HP, foes hover at 5-7, never hit her | Not established. `channel_start_ok` runs the same lethal test as the cancel (`start_gate`, champ_prism.cc:598), so a plain gate mismatch is ruled out. v631 changed that test: re-measure |
| Capture abandoned before payment | .26/g | `01yellow-brick-road__a` r519-523, 30 gems + 220 gold, no foe within 10 | The known `held = on & ~0u` (econ_capture.cc:430) |
| 8+ idle rounds beside a living group of 150+ gems, usually no attack | 1.05/g, 16 rounds/g | `04gap__a` r832-866; `02guardians__a` r17-51; `00monolith__a` r753-793 | Unexplained; siege gates (`siege_turn`, econ_team_ops.cc:735) suspected |
| A,B,A,B walking with no foe within 8 | 1.6/g per team, 9.5 rounds/g | `02geodes__a` r692-757, `02crossing__a` r425-460 | Unexplained |
| Under 25% HP stepping toward a foe's reach | .56/g, 72% die | `02treasure-box__a` r495-499 | Not traced; mostly walks home or to an altar |

Not bugs: ready spells unused while walking away (the spell excludes walking); engine refusals (0.1% of attempts).

## Economy code bugs (8 Nov hunt, v628-v629)

Code bugs, not rule-model faults. Each was re-read against `bots/nova_b9968_rgf3r/src` (v629). Nothing measured. All were already in v625, so none are refactor slips. Fixes below change play unless noted, so they go on the behaviour lane. "Likely" means the intent needs checking first.

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| econ_choose_target.cc `BoundsRun::run`, econ_rate_crew.cc `late_factors` | The target bound leaves out the ECL factor (`sqrt(ECL_CELL/1000)`, up to 1.57) that `rate_for` applies on FAR20 maps | Y's true rate 1.49 is never rated, because its bound 1.0 <= best_r 1.08, and a lower-rated X wins | Apply the same cell factor to `ub` |
| econ_choose_target.cc:305 | The bound drops every GB_SGB group "as rate_for", but `closed()` keeps a big group that is nearly dead | `best_group` can never pick one, so REM (OGS bit 8) almost never runs | Add `&& !big_group_nearly_dead(gi)` for GB_SGB |
| econ_opening_walk.cc:575 `start_prestep_i` | `hit` (the camp-reach guard) is computed and never read | A setup-wait step goes within reach + 1 of an attacking camp, against the comment | `if (hit) continue;`, or delete the guard, its scan and the comment |
| econ_crystal_plan.cc:89 `crystal_plan_trip_body` | `P.tank_order[0]` is slot 0's rank, not the rank-0 slot | No Prism or Marcella, slot 0 rank 2: slot 2 alone gets the trip | Find s with `P.tank_order[s] == 0` |
| econ_altar_hold.cc:55 `altar_hold_field` | Three cache slots, never evicted | Over 3 altars: later altars read nullptr and are skipped, and a pin that should fire does not | On a miss, overwrite a slot not in `order[]` |
| econ_altar_hold.cc:96, :133 `altar_hold_note` | The banked-since baseline is taken after the 300-gem early exit | A bag banked unseen before the note first runs still counts as a finishing bag | At first note, `alh_tt[i] = -1` for older sightings |
| econ_opening_pick.cc:289 | `choice` is lost across a fuel return in the join pass | Next turn returns -1, and `opened` is set with no target | If `choice < 0` use `cl[my_slot()]` after the loop |
| econ_opening_pick.cc:135, :173 | Hoard seed's rate and crew are lost on a resumed simulation (likely) | `set_target(best, 0, 1)` replaces rate 1.0 and the full crew | Keep them in `OP` |
| econ_rate_crew.cc:274 `time_and_value` | The endgame gold branch has no holder bonus or Prospector gold | Vesper with Treasure valued x1.00, not x1.43 | Multiply and add Prospector; `endgame_bound` to match |
| econ_locks.cc:56 `enemy_altar_lock_direct` | A read calls `cancel_spin_before_action` | A kept recall spin is cancelled with no action, so a hurt body lands a round late | Delete it; action sites cancel for themselves |
| econ_bank_decide.cc:216 `dynamic_bank_track_rate` | A gap of 15+ rounds with 0 gems counts as a lost bag, but a long tribute looks the same | 141+ gems banked by a non-Prism: `dbk_lost` rises for the rest of the game | Also require that no tribute of mine landed in the gap |
| econ_approach.cc:244 `crew_here` | The tank pick replaces on order alone (likely) | A ranged body with better order replaces a melee tank | Prefer melee, then order |
| econ_tank_support.cc:234, :265 `crew_mates_in_reach` | `rtk` is computed and unused; the comment says the mate must hold until the kill (likely) | A mate that can't hold 20 rounds still counts | Add `\|\| eff_now < inc_now * rtk + keep` |

Dead code: `partner_here` (econ_approach.cc:265-271); quick-news channel (`qk_rbase` never above 0); the old non-t2 comms path; `siege_crew_call_seen` (`false &&`); `big_group_crew_candidate` (always false); LNR's extended rating loop.

## Ward, champion, draft and comms bugs (8 Nov hunt, v629)

Same terms as the economy table. All were already in v625.

| Where | Bug | Wrong case | Fix |
|---|---|---|---|
| ward_spots.cc `build_chokes`, ward_analyse.cc `stage_chokes`, ward_act.cc `spot_cache_ready` | Chokes join `spots` at A_CHOKES, so the coverage cache no longer matches and `act()` returns until A_FINAL | A map with a narrow corridor and no bush route places no coverage ward until a late analysis step (about 79k fuel left). Rounds lost are unmeasured: check first-ward rounds | Reset the cache after `build_chokes`, or hold chokes in their own vector until A_FINAL |
| ward_bush.cc:176, ward_act.cc:55, :133, :234 | Any refused ward counts as a bad tile; only `place_chosen_ward` separates "I can't act". A stunned body gets rc 63 (probe p84) | A stunned turn bans the best tile for 40 rounds; a pin failure latches for the game (contest_play.cc:841) | Return early when stunned in `wait_for_ready_charge`, `react`, `ward_bush_by_vanished_foe` |
| champ_prism.cc:588 `winning_channel_doomed`, econ_bank_win.cc:304 `foe_burst_lethal_to_healer` | `foe_damage_over_ticks` (before Durability) is compared with real HP; `prism_channel_unsafe` converts | A Durability holder at 300 HP facing 320 raw (288 real) reads doomed and refuses the channel | Wrap in `mu::mult_foe_hit_to_real_hp_alt` |
| plan_exact_travel.cc:215-221 `travel_write` | Space is reserved for routes that are never stored (`blk[5] = 0`) | 34+ groups: fewer neighbours or a lost full table, with bytes left zero | Reserve 0 for routes while XT bit 4 is off |
| draft_memory.cc:14-25 `pack_and_submit_draft_memory` | `key` is computed before the blob clear, so `pk_key` is stale | Blob overflow forces a repack next turn; if fuel is short, V1 replaces a good V2 (likely) | Recompute `key` after the clear |
| comms.cc:624 `write_event`, intel.cc:818 | Early return compares with this body's last-seen image, not the slot | The same post 32 rounds later is dropped, and a mate's identical post is ignored | Skip the return under `L.ev2`; key the reader on the channel entry |

Comment disagrees with the value (intent unknown): `DSW_MASK 254` says cells 0-7 are on, but bit 0 is off; the C&I draft gate's comment describes a one-altar arm that `draft_gate` ignores.

Dead code: `bag_band_of_slot` (`pg9_*` are never set); `contest_zone`'s draft block is dropped by `pack`; compact-XT path; `qct_force`.

## Load-bearing model gaps (do not fix alone)

| Where | Gap | Why it stays | Evidence |
|---|---|---|---|
| combat reach_burst_turns_fill (+ phy_swap_table) feeding reach_burst_test, lethal zones, foe_two_turn_reach, danger_veto, walk guards | An acted foe counts 2 turns before my next turn; it acts once (INT:27) | Load-bearing safety margin in movement: capping it at 1 (HAT bits 1/4/16) raised rest-of-game deaths (+134 over 236 first divergences, b2365 v868 diag; hat1c). Escape-dash fill (F, HAT bit 8) has 0 divergences. Long-span consumers (channel_safe_check, rgf_foe_lock_within) use build_acting_order_table, not this table | RC C1127 (2026-11-13T05:47:55Z); fix only together with an explicit walk-guard margin |

## Not a rules gap, but found on the way

- **The draft computes the map features twice** (draft_map_features.cc `map_features`: `mapfeat::compute` runs, then `set_values`, then runs again). The same is in live. It spends draft fuel for nothing, unless the second run's fuel reading matters.

## Comments corrected in the refactor

- champ_tavi.h said a Greed emblem is worth 35 shards; GR:317 says 40.
- ward_bush.cc and ward_act.cc blamed a refused ward on a hidden unit; INT:140-141 says it is a mate's ward.

## Could not be verified statically

All three were settled on the engine on 8 Nov:

- The SDK's `focus` and `strength` include Prism's gems (INT:58) and Ryth's 1% bonus (probe p80: 45 to 50 after +500 HP).
- Team A has the lower handles, and handle order equals draft order (p80; INT:14).
- A camp group respawns at the pay round plus its timer, and an occupied spawn tile holds it until the round after the tile is free (probes p15, p23, p24; INT:110).

## Coverage

The second audit read `combat_foes`, `combat_burst*`, `combat_lethal_burst`, most of flee and the rule parts of assess, plus `planner`, `contest_*`, intel, comms, `brain_*` and draft rule facts. Read 9 Nov (v641): the converge and commit rules, `assess_coming_body`, the stance bars, `zones_of`, `mapinfo`, `draft_lineup_search` and `draft_values` (findings in bot_errors.md, sections "Combat converge..." and "Map parsing and draft"). `contest_play`'s zone plan and `planner`'s camp model are dead code.


Checked with no further finding: champion stats and slots (read from the engine), damage modifier stacking, shields, Ren retaliation, Varg splash, Heart of Ruin's formula, Vendetta's refund after normal hits, Willow's heal, capture timing and shares, tribute timing, locks, shard and emblem costs, consumables, Tavi's selling, walk and landing legality, crystal range and walls, cardinal bush clusters, ward placement, shared memory limits, draft picks and fuel, sight-gated reads. Assess and flee were read in part; `zone` and most of `plan` only searched.
| R1 (WITHDRAWN, RC C1405b: the S+4 arrivals were kept spins, prefired = 4 already) | rules.h:96-104 recall_rounds (6 callers: recall_safe, foe_turns_during_recall, capture_recall, ...) | A plain recall takes 5 rounds to arrive | Engine: a plain recall arrives at the S+4 turn start (INT Recall, b2433 diag 3508/3532); Home S+3 as coded | RC C1405 (13 Nov). Overstates the plain recall by 1 round in every consumer. Needs a flagged fix (play-changing) |
