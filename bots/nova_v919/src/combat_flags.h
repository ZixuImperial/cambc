#pragma once
// combat_flags.h: combat flags and tunables.

// Runtime data flag, 0 = off. Bit 1 (brain turn(), before the FIGHT branch; econ::fbb_turn): a non-Prism carrier in the FIGHT stance
// with a large enough bag, within 1 of an altar without an enemy lock (no mate channelling there), starts the tribute when no known
// foe can stop it before it completes (combat::channel_safe(0, ticks, camp damage): no stun lands in time; known damage < BUS_PCT %
// of HP + shield). Re-decided every turn from what is visible now. Damage does not cancel a tribute (GameRules.md:226). Bit 2
// (lethal_burst_hit emblem pricing): a visible foe's next-turn damage on me carries its outgoing emblem bonuses (rs::families,
// cached per round): Skirmish's bonus v champions, Collectors +1 % per completed family (GameRules.md:316-318, they multiply). Bit
// 8: the same pricing as bit 2 (use 8 alone), the multiplier looked up per foe index per round. Bit 4: lethal_burst_zones (the
// LETHAL_BURST walk guard) counts a foe slot at cooldown 1 as ready (LB_CDH 0 -> 1 there only). FINISH HOLD (hunt_leash_assess),
// FH_TAB: a healthy body (>= 50% HP, bag < 60) in a non-lethal FLEE takes a short won race on a wounded foe (<= 70% HP) in its hit
// reach. Bit 1: past the race's FLEE ratio gate (ratio < 0.6). Bit 2: past the race's numbers bar. FH_KT10: longest race, in turns x
// 10. Not Prism, not linked C&I, not a lethal flee, not the lone 1v3 case.
#define FH_BITS 1
#define FH_KT10 69
inline constexpr int FH_TAB[3] = { 0x46483438, FH_BITS, FH_KT10 };

// Fight-value scaling, runtime table DPS_TAB (bits 1 walk, 2 value, 4 targets, 8 raw, 16 fight-share scaling of our side, 32 of the
// foes' side, 64 current-state passives in RAW, 128 passive counts camps, 256 rules-exact RAW, needs 8 and 64); the shares x100 are
// data (me, mate d1, mate d2+, foe d1..d6+).
// STRIPPED (FL6): DPS bits 1, 2, 4, 8, 64, 128 and 256 have no reader in this tree; deadstrip.py find DPS before arming one.
#define DPS_BITS 0

// Ratio flag RP, 0 = off. Bit 1: the foe discount takes a continuous shape, no cliff. Bit 2: no headcount tier on the engage bar.
// Bit 4: remembered foes in the engage-bar headcount fade by age, the bar moves smoothly (float exponent). Bit 8: that count uses
// the mates' own radius, not EF_FOE_R (needs bit 4). Hunt-race flag HDL, 0 = off. Bit 1: my turns to live in the hd race = the first
// T where sum over foes of share x dps_dmg x max(0, T - lag) >= margin x my eff HP, lag = turns before the foe can reach me; it
// replaces the rate, share and contact terms of inc in hdt_won together. The in-reach share is measured x100. Stun flag STP, 0 =
// off: a pending stun (b.stunned) costs the foe's whole next turn, not 'reach - 1'. Bit 1 foe_of: reach 0. Bit 2 foe_reach: reach 0.
// Bit 4 lethal_burst_damage_sum: no hit from a stunned foe whose only turn before mine is the lost one.
// STRIPPED (FL6): no reader of STP_TAB in this tree; deadstrip.py find STP before arming.
#define DPS_FS_ME 80
#define DPS_FS_M1 60
#define DPS_FS_M2 55
#define DPS_FS_F1 72
#define DPS_FS_F2 65
#define DPS_FS_F3 60
#define DPS_FS_F4 53
#define DPS_FS_F5 45
#define DPS_FS_F6 34

// Runtime data flag TARGETING_FIX_TAB[1], 0 = off. Bit 1: channel_target keeps a foe on its spawn beyond basic range when a stun
// from cc range reaches it (legal, and it cancels the channel). Bit 2: a recall counts any damage that cancels it
// (GameRules.md:385): a ready nuke, area spell or landing dash that fight() would cast. Bit 4: crystal channels are targets when a
// stun reaches (a stun cancels and consumes one, damage does not). Bit 8: the 'hit what is in reach' sites take the lowest eff HP
// off-spawn foe, then the list order, so no hit is lost. Bit 16: team_dps_on and team_focus's copy count a ready area spell (range +
// radius) and dash. Bit 32: unreachable() and team_focus's copy count the area spell, the dash and a melee walk + hit
// (GameRules.md:153): a foe on spawn with a legal tile in that reach counts. Bit 64: channel_threat, PEEL and the Prism guard skip
// foes that unreachable() rejects (:153). Bit 128: wake guards test camp kills with Heart's factor x mu::my_camp(OUT) instead of
// passive_mult (Skirmish counts, Monster does not). Bit 256: the stun counter does not spend a zero-damage stun on an immune or
// stunned foe; the next spell goes instead.
#define TARGETING_FIX_BITS 487
inline constexpr int TARGETING_FIX_TAB[2] = { 0x42483830, TARGETING_FIX_BITS }; // slot 0 magic keeps it out of .bss
constexpr int TARGETING_FIX_BIT_CTS = 1, TARGETING_FIX_BIT_CTR = 2, TARGETING_FIX_BIT_CTC = 4, TARGETING_FIX_BIT_HIT = 8, TARGETING_FIX_BIT_RCH = 16, TARGETING_FIX_BIT_URW = 32, TARGETING_FIX_BIT_NUF = 64, TARGETING_FIX_BIT_CKM = 128, TARGETING_FIX_BIT_SSC = 256;

// Runtime flag, 0 = off; each bit calls the engine-exact middle test combat::dash_legal_between or the stun model
// combat::channel_safe. Bit 1 (dashnav.cc try_dash_once, dash_ahead): the cast's middle is checked with dash_legal_between(me, u)
// instead of the static board. Bit 2 (game_deny_stun_channeler's stun dash): dash_legal_between. Bit 4 (AreaGrid::best landing,
// Heart's area dash on camps): dash_legal_between(from, t). Bit 8 (cast_via_sdk): a rc 32 dash refusal reserves the landing as a
// crystal tile for TRZ_AGE rounds only when dash_legal_between(me, p) passes (the middle was legal). Bit 16 (spawn_crystal_step, mid
// hop): a foe stun cancels a crystal channel even at timer 0; the channel test is !channel_safe(0, the crystal's channel rounds, 0)
// (per-kit stun landing); the landing tests stay. Bit 32 (dash_legal_between): a foe seen only through my ward blocks a dash middle
// (W.enemies_far too).
// STRIPPED (FL6): no reader of DASH_MIDDLE_TAB in this tree; deadstrip.py find DASH_MIDDLE before arming.
#define DASH_MIDDLE_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; in release c is not evaluated

// Runtime data flag, 0 = off. Bit 1: foe_first_hit_turn prices a spell on cooldown c as ready on the foe's turn c + 1 (a slot ticks
// at its owner's turn end; foe_ready: cd <= k on 0-based turn k; GameRules:118). Runtime data flag FLEE_FIX_TAB[1], 0 = off. Bit 1:
// assess's 'stands next to an awake camp (busy farming)' x0.6 does not read a remembered foe's frozen last tile once that tile is in
// my sight (the foe is known not to be on it). Bit 2: flee(): after an exclusive parting stun a ranged body that stays may attack
// and cast (GameRules:116), as parting_stun does. Bit 4: spawn_refuge / retreat_to_spawn_to_heal price foe damage through
// mult_foe_hit_to_real_hp against real HP (spawn_siege_is_safe); the camp part stays real. Bit 8: gd_mem.until = round + left counts
// a foe that already took this round's turn (game_deny_slow), so game_deny_follow_channel does not stop a round early.
// STRIPPED (FL6): no reader of FLEE_FIX_TAB in this tree; deadstrip.py find FLEE_FIX before arming.
constexpr std::uint32_t FLEE_FIX_ST_ACTED = 32u; // champion state bit completed_turn

// Runtime data flag PFH_TAB[1], 0 = off. Bit 1: fight()'s walk-in step. Melee walking never spends the attack (GameRules.md:100), so
// a melee body with its attack unused, whose focus is out of reach even after a step (and a ready dash), hits the lowest eff HP
// non-spawn foe in reach before the step, not from the new tile.
// STRIPPED (FL6): no reader of PFH_TAB in this tree; deadstrip.py find PFH before arming.
#define SPELL_READY_FIX_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c (answer differs from the other path); in release c is not evaluated

#define POWER_ENGAGE 0.0f
#define POWER_LEAVE 0.6f

// The leave on POWER_LEAVE reads the raw power product, while a.ratio (with its SYM discount) can read level or ahead on the same
// turn. Runtime data flag, 0 = off. Bit 1: the leave fires only at a.ratio < EVEN_RATIO.
// STRIPPED (FL6): no reader of S1R_TAB in this tree; deadstrip.py find S1R before arming.
#define FINISH_LOW_HP 0.3f
#define CAMP_FIRST_MIN 0.8f
#define PEEL_MIN (static_cast<float>(B467_PEEL_X100) / 100.0f)
#define DT2_MIN 0.7f
#define DT2_RATIO_X100 40 // ratio x100 floor
#define PEEL2 0.5f // PEEL also covers a team mate below PEEL2 HP with a visible foe in reach of it (the chase after the hit, not only the round of the hit), at fs^2 >= PEEL2_MIN es^2, when I reach that foe within 2 turns; 0 = off

#define PEEL2_MIN 0.5f
// b1761 FD1P (spec_fd1p_1109): runtime data flag, 0 = off. Bit 1: escape_toward first tries a priced A* (EP9) where each visible foe champion's
// zone costs its next-turn burst per tile (no nearest-body rule), on top of the camps: the cheapest way out from inside a zone.
// v658 FD1P: FD1P priced flee path across foe reach
#define STH_ROUNDS 5
#define STH_R 6

// Also require that I have stood on my own tile for >= STH_SELF rounds: only a real stand-off freeze qualifies (~1 in 200 games).
#define STH_SELF 30 // standing still 5 rounds is common at camps; 30 = a true freeze
#define CAUGHT_MIN (static_cast<float>(B467_CAUGHT_X100) / 100.0f) // caught by a melee chaser, fight back only at ratio_near >= CAUGHT_MIN; below it, flee

// CALM-side starts are pokes, reset doubles and basic hits with no mate near the target: spell_poke, kite_shot_after_move, hidden_fire and
// react_guard act only at near balance >= LOW_START_X100/100, unless a foe in my reach is in a kill window (stunned or channelling)
// or has a mate of ours within 3. 0 = off.
#define LOW_START_X100 80

// NOCHASE: their spawn heals them to full at their turn end, so damage there is wasted: a foe within NOCHASE_R of its own spawn is
// never the focus unless the kill lands this turn.
#define NOCHASE_R 2
#define CT_R 6
#define CT_HP_PCT 50
#define CT_MIN_X100 70
#define EF_A_X100 110
#define EF_B_X100 210
#define EF_FOE_R 12
#define LL_BAG 10
// STRIPPED (FL6): no reader of SBG_TAB in this tree; deadstrip.py find SBG before arming.
#define HOLD_MIN_X100 60 // a FLEE within 2 rounds of fighting is held as FIGHT only at ratio x 100 >= this

#define HUNT_MIN_BAG 40 // smallest enemy bag worth a lock or a detour

// The fight model in contested ground: the foes' kit values refit on live duels, in the ENGAGE decision only (applying it
// everywhere, or in 'close in when in reach', turns contact fights into flights).
#define FIGHTCAL_FOE_SHIFT 0.0f // added to every foe kit value (slot units; 4 = x e in foe damage)
#define FIGHTCAL_A_MASK 0x1FFF // kits (bit = champion_type) whose foe value is refit; 0x8FC = kits nova never drafts

// PASSIVE Cassi: the ranged caster whose damage spell excludes walking (a walk forfeits the spell). 0x08 is Cassi only (Stellar is not in it).
#define PO_CASTER_MASK 0x08u // champion_type bits of the caster passives: cassi 3

// Runtime data flag FREE_HIT_THREAT_TAB[1], 0 = off. Bit 1 FREE_HIT_THREAT_BIT_THREAT: a visible foe blocks prestep_hit_before_move's free hit only when it is a real
// threat: I could reach it this turn (foe_next_turn_reach of me from my tile, so the attack might be wanted for it), or its time to reach the
// step's end tile (1 + tiles beyond its next-turn reach foe_next_turn_reach) is under FREE_HIT_THREAT_ETA turns. Unknown kit: blocks.
#define FREE_HIT_THREAT_BITS 1
#define FREE_HIT_THREAT_ETA 2
inline constexpr int FREE_HIT_THREAT_TAB[3] = { 0x46485032, FREE_HIT_THREAT_BITS, FREE_HIT_THREAT_ETA };
constexpr int FREE_HIT_THREAT_BIT_THREAT = 1;

// NO_WAKE: a landing or area cast beside a sleeping group wakes it, and the group hits its nearest body. A fight area cast (Heart's
// landing dash in fight() and heart_dash_try, the area spell in fight(); area_tile_covering_all and the free casts through AreaGrid::wakes_other)
// never takes a landing or centre whose square covers any camp (clusters included) of a group with no visible awake member, when
// that group's visible attackers whose nearest champion (after the cast; ties count as ours) is one of OUR bodies sum >= NW_STR
// strength (elk, golem, monolith, 2+ wolves). The next-best tile is taken, else none (a plain attack). Exception: the cast kills a
// foe in its square. Runtime data flag NO_WAKE_TAB[1], 0 = off.
#define NW_STR 40
#define CU_WALK 0
#define CU_HOLD 1
#define CU_HOLD_D 6
#define CU_HOLD_AGE 2
inline constexpr int CAST_UPTIME_TAB[5] = { 0x43555054, CU_WALK, CU_HOLD, CU_HOLD_D, CU_HOLD_AGE }; // slot 0 magic keeps it out of .bss

// Landing dash (HRL): fight() runs Heart of Ruin's landing dash (walking-compatible, GameRules:826) before its walk-in step, and
// only at d <= dash + 1 (3); the walk-then-dash covers kills and plain dashers only. So a Heart at d 4 with the dash ready walks to
// d 3 and lands a round later. Runtime data flag, 0 = off. Bit 1: after the walk-in step, a landing dash still ready (no cast this
// turn) on a focus that started at d = dash + 2 runs the same landing search (the no-wake and landing gates). Bit 2 MATE: only when
// an ally stands within 2 of the focus. OCB (GameRules.md:116: one successful ability cast per turn across both slots). Runtime data
// flag, 0 = off. Bit 1: my_burst (kill_now and every kill test) counts the reset's second hit OR one spell, the larger, not both.
// Bit 2: foe_of's next-turn burst counts the basic hit plus the best ONE cast.
#define OCB_BITS 1
inline constexpr int OCB_TAB[2] = { 0x4F434231, OCB_BITS };
#define OCB_ON(b) ((OCB_TAB[1] & (b)) != 0 || (((b) & 2) != 0 && (::nova::mu::bits & 64) != 0)) // bit 2 also follows mu::bits & 64 at run time

// KQ: one kill check, kills(f, d, mode) / kill_dmg(f, d, mode), with kill_now's reach, the dash landing test and KRS inside, and one
// call point for the target's damage factor. Runtime data flag, 0 = off. Bit 1 ROUTE: kill_now, the next-focus loop, focus_still_killable and
// the NCR refocus call kills(f, d, 0). Bit 2 WALK: the walk guard's 'a kill from here goes first' counts my basic hit x passive_mult
// with the attack allowance. Bit 4 DASHD: Vendetta's / Vesper's dash gates price the dash-in (one basic + the dash's own damage, the
// turn's one cast) at the real distance (not my_burst at d 1 / range: a reset or a spell on top of the dash). Bit 8 LBZ: lethal_burst_zones
// leaves out a foe that kills(e, d, 0) says dies this turn (dash reach, landing test, KRS). Bit 16 LBS: lethal_burst_damage_sum skip_kill counts the
// basic only with the attack allowance and the dash's damage only within its landing radius.
#define KQ_BITS 31
inline constexpr int KQ_TAB[2] = { 0x4B514231, KQ_BITS }; // slot 0 magic keeps it out of .bss
#define KQ_ON(b) ((KQ_TAB[1] & (b)) != 0)

// FUL: runtime data flag, 0 = off. At the end of assess, a non-FIGHT body that is not low, healthy enough, with a small bag, not
// Prism, not linked, with little incoming damage (the FUL_* bars). Bit 1 ISO: one foe in the balance, visible within a set distance,
// no other known foe (own sight, age <= 8) within 5 of it, ratio_fc >= FUL_RMIN %, mates within 6 >= FUL_UM -> FIGHT on it. Bit 2
// LOW: a foe < FUL_LOWF % HP within my range + 1, ratio_fc >= FUL_LMIN % -> FIGHT on it. Neither takes a foe within NOCHASE_R of its
// spawn. BKC: chasing a foe that goes into a bush; runtime data flag, 0 = off. observe() remembers the lowest visible foe below
// BKC_HP% within 6 of me (off its spawn) with its tile and round. Bit 1 PROBE: while it is out of my sight for 1..BKC_K rounds and
// not dead, a CALM (or focus-less FIGHT) turn steps toward the nearest bush tile I do not see within (age + 1) of its last tile
// (standing in a bush cluster shows the whole cluster; a refused step into a hidden occupant reveals it and the bush hit hits it),
// only at my HP >= BKC_MYHP%, bag < 40, not capturing, not channelling, its last tile >= BKC_SPAWN from its spawn, and no visible
// foe within 6 (bit 2: or one, at assess ratio >= 1.3). Bit 4 HIT: after the step, re-read the view and fight a newly visible focus
// this turn. Bit 8 FOCUS: track only a foe that was my fight focus. No phantom foe enters any danger or strength sum. Bit 16
// BUSHMAP: on a map with no bush tile (M.bushes empty, read once after the group stage) the tracker, the target and the focus record
// do nothing.
#define BKC_BITS 29
#define BKC_HP 40
#define BKC_K 3
#define BKC_MYHP 50
#define BKC_SPAWN 3
inline constexpr int BKC_TAB[6] = { 0x424B4331, BKC_BITS, BKC_HP, BKC_K, BKC_MYHP, BKC_SPAWN };

// LETHAL_BURST: never STAY inside a ready lethal nuke (Marcella's 2xF), above all while trading hits. lethal_burst_hit: the most one foe deals
// me on its next turn at distance d (one cast a turn; walk-excluding spells from where it stands; walk + hit for melee, dash + hit),
// with its cooldowns read (unknown = ready). Bits: 1 assess: FIGHT -> FLEE when the visible foes' next-turn damage here >= LB_PCT%
// of my effective HP, I kill nothing now, and a tile I reach this turn (walk, else my dash) is not lethal; 8 the same for CALM; 4
// that flee takes that tile (melee/dash: hit first), toward the nearest healthy mate within 12, else home; 2 CALM / 16 FIGHT walks
// keep out of each single lethal foe's reach (+ LB_MARGIN; cooldown <= LB_CDH counts as ready); 32 no dash landing (any kind, travel
// included) on a lethal tile from a non-lethal one. 128 FLEE walks (flee(), retreats, go-home) keep out of a lethal foe's reach too.
// 64 recall_safe refuses when a visible foe, walking n-1 of its n channel turns, then has a lethal next turn. LB_CAST 1: the lethal
// sum of bits 1/8 must hold a ready damage cast (nuke, area, landing). Runtime data flags; 0 = off.
#define LETHAL_BURST 55
#define LB_PCT 90
#define LB_MARGIN 0
#define LB_CAST 1
#define LB_CDH 0
inline constexpr int LETHAL_BURST_TAB[6] = { 0x4C425354, LETHAL_BURST, LB_PCT, LB_MARGIN, LB_CAST, LB_CDH }; // slot 0 magic keeps it out of .bss

// Runtime data flag ELE_TAB[1], 0 = off. Bit 32, end of assess's stance chain (after lethal_burst_assess; hunt_leash_assess skips an
// ELE round): HP < ELE_HP %, pack (visible foes within 8 + foes in combat memory <= ELE_MEM rounds old last seen within 8) > our
// bodies within 3 (me included) + 1, no kill this turn, not channelling, not about to capture (econ::target_pays_within) -> FLEE,
// kept ELE_STK more rounds. Only for r <= ELE_R unless bit 64 (all game).
#define ELE_BITS 96
#define ELE_R 50
#define ELE_MEM 6
#define ELE_FIN 2
#define ELE_HP 30
#define ELE_STK 2
inline constexpr int ELE_TAB[7] = { 0x454C4531, ELE_BITS, ELE_R, ELE_MEM, ELE_FIN, ELE_HP, ELE_STK };

// Spawn pass (0 = off; retreat_to_spawn_to_heal, brain before LETHAL_BURST): my spawn heals me to full at my turn end and no foe can
// step on it, so a hurt body (< SP_HP % of max) ends its turn there when a free tile is one step away and the tile survives the
// foes' reach at full health. Bit 1: a foe within 8 (any stance; the refuge rule alone needs FLEE, ratio < .8). Bit 2: already on
// the spawn, any stance: stay and hit back (a recall that arrives and flees off the tile heals nothing). Bit 4: no foe within 8 (the
// walk past). Never off a capture that pays; a kill from here goes first.
#define SP_BITS 7
#define SP_HP 70
inline constexpr int SP_TAB[3] = { 0x53503733, SP_BITS, SP_HP };

// ---- keep denying after a game-ending tribute is cancelled. After a foe's game-ending tribute is cancelled, keep denying it:
// otherwise a lock placed on the ending channel is broken once nobody stays, and the foe re-tributes. Flag GEB_BITS, 0 = off. Bits:
// 1 MEM a seen ending bag stays live in game_deny's memory GEB_N rounds after its channel's end, and a body with a cancel tool in
// time walks back to the altar's lock ring; 2 HOLD while it is live and the bag sits near the altar, a body in the lock ring places
// our lock if none of ours stands (a carried one), else holds there (hold_lethal survival test). Hooks: game_deny_slow (note on an
// ending pick; act when no channel is picked).
#define GEB_BITS 1
#define GEB_N 15
#define GEB_NEAR 3
inline constexpr int GEB_TAB[3] = { 0x47454231, GEB_BITS, GEB_N }; // slot 0 magic keeps it out of .bss
constexpr int GEB_BIT_MEM = 1;
constexpr int GEB_BIT_HOLD = 2;
// ---- DMK (Combat spec DMF 11 Nov): deny_memory::act. Flag DMK_BITS, 0 = off. Bits: 1 LOCK (before the FLEE test) in lock range, a carried lock, no
// lock of ours / mate tribute there, place it; 2 FLEE a survivable FLEE turn (dlf_flee_pass) keeps the ending-memory walk; 4 FLEE never refuses it.
// 8 FCL1 game_deny_follow_channel (ending or lock-only memory): a lock carrier in lock range of the memory's altar locks blind, else walks to the altar's 2-ring and locks on
// arrival; 16 FCL2 follow_channel's FLEE refusal passes a lock-only memory on dlf_flee_pass (as :729).
// v760 DMK: follow_channel locks at the altar (FCL1)
#define DMK_BITS 8
inline constexpr int DMK_TAB[2] = { 0x444D4B31, DMK_BITS };
#define DMK_ON(b) ((DMK_TAB[1] & (b)) != 0)

// ---- big-tribute deny constants. Deny big foe tributes by lock or stun. Flag GDB_BITS, 0 = off. Bits: 1 PICK_BIG game_deny also
// takes a non-ending channel of GDB_BAG+ with GDB_T+ turns left (after end and flip); 2 WAYS_SAFE on a big pick: bag < GDB_FREE_BAG,
// HP share >= .5, and each way's goal tile and next step burst < GDB_SAFE_PCT %; 4 LOCK_EARLY game_deny_lock_wanted buys a lock on a seen foe
// bag of GDB_BAG (not GD_LOCKBAG): an early lock when a 150+ foe bag is seen; bit 8 is reserved. Hooks: game_deny_slow (pick, ways),
// game_deny_lock_wanted (bag).
#define GDB_BITS 4
inline constexpr int GDB_TAB[2] = { 0x47444231, GDB_BITS }; // slot 0 magic keeps it out of .bss
#define GDB_BAG 150     // a big tribute: a channel started with this bag

// RGF (b1681, docs/rules-gaps.md): 0 = nova_b2783_consistency. Bits: 1 M2 dash middle (enemy spawn, pending crystal),
// 8 E4 foe lock v stun-immune tribute (reach includes a ready dash), 16 E5 no pre-lock off a shared altar, 32 C4 reset only if the first hit left it alive, 64 C5 a Vendetta prestep kill above raw Strength refreshes her cooldowns, 128 C&I partner bag in the hunt target score, 256 WRS the race exemption of winning_tribute_start_blocked for any kit whose bag wins.
// v629 RGF: dash, lock, reset, refund, race consistency

// RGS (rules-gaps 8 Nov). Bits: 4 fight_hit_focus resets and hits the next foe in reach after a kill; 8 a channel race counts a body that already acted this round; 16 carry_recall prices foe damage with passive_mult and Durability. 0 = base.
// v633 RGS: retarget after kill, acted races, recall units
#define RGS_BITS 28
inline constexpr int RGS_TAB[2] = { 0x52475331, RGS_BITS }; // slot 0 magic keeps it out of .bss
#define RGS_ON(b) ((RGS_TAB[1] & (b)) != 0)

// CB3 (b1736, Bundle 3 combat fixes): one bit per line. 0 = nova_b10035_pbk2s. Bits: 1 DTB visible_foes_lethal_next_turn prices a foe's
// turns before mine (two-turn hit; a stun that takes its only turn = 0). 2 MCW ally_commit_weight: no x.6 for a mate engaged on my
// claimed group (CAMP_DRAIN 2/3 read no better than 4). 4 SHX stunned turn: only observation, priority, claim and HELP (INT:38). 8 KWS kill_window:
// a recall only when my hit lands, a tribute only with a stun, lock or kill. 16 RAB mates' buffs read in fights; foe health weighted
// as in the power sum. 32 R1 the seen store and channel_safe read a stunned foe unstunned (+1 turn). 64 R2 parting_foes sees a stunned
// chaser. 128 PTF protect_tribute: no lock off a shared altar (INT:115). 256 KDP area hits on packs of 4. 1024 KNR kills(): ranged walk
// + reset and Vesper's dash. 2048 VDR Vendetta gap dash after a walk from 4 to 3. 4096 LTT lock wanted at CB3_LOCKTT (500, sweep 500/600/700) foe tributed.
// 8192 VFD Vendetta's follow-kill dash after a walk.
// 16384 PGW the Prism guard's stalled step_to gives way to her group's walk field, or to the later team stages.
#define CB3_BITS 32255
// v638 CB3: Bundle 3, 14 combat bug fixes
#define CB3_LOCKTT 500
inline constexpr int CB3_TAB[3] = { 0x43423331, CB3_BITS, CB3_LOCKTT }; // slot 0 magic keeps it out of .bss

// BB13 (b1741, Rule Checker's own-spawn audit, docs/bot_errors.md "Own spawn area"; GR:153, 161, INT:134): one bit per line, read first,
// 0 = off. 1 a melee foe's reach onto my spawn tile counts only if it can stand on a free non-spawn tile within its range of me this
// turn; 2 the spawn heal hold no longer needs a.nearest > 4; 4 spawn_refuge's ratio gate only off spawn; 8 on spawn the lethal-landing
// "staying" test uses the healed (full) cap; 16 refresh_self after a buy, the spawn-siege cleared-group step waits on spawn below .97,
// the on-spawn refuge tries a spell kill first.
// v652 BB13: spawn shield counts ready spells
// (BB13 note, b1779: only bit 1 shipped; bits 2/4/8 were lost with the v650 restore and its BB18 carrier, bit 16 never shipped; FLR re-lands 2/4/8.)
// FLR (b1779, Rule Checker re-land, docs/bot_errors.md own-spawn rows; GR:153, 161): runtime data flag, read first; 0 = off. 2 the spawn
// heal hold no longer needs a.nearest > 4 (brain_turn.cc); 4 spawn_refuge's ratio gate only off spawn (combat_flee.cc); 8 on spawn
// the lethal-landing 'staying' test uses the healed (full) cap (combat_lethal_burst.cc); 16 FLD1 (Combat): step_out_of_reach and the
// post-dash retreat take flee_rally's rally (home near my spawn), not rally_ally's.
// v680 FLR: 4 fixes msy7,fac,flr,lck
#define FLR_BITS 30
inline constexpr int FLR_TAB[2] = { 0x464C5231, FLR_BITS }; // slot 0 magic keeps it out of .bss
// BB12 (b1762, Bug Bundle 12, docs/bot_errors.md "Area spells on champions"): one bit per fix, read first. 1 CALMSP (not shipped) the calm area poke
// counts a foe on its own spawn only when the area kills it (it heals at its turn end: GR:153, 385; INT:93). 2 KPAIR the wake guard's
// champion-kill exception (fight_area_try, heart landing) and hold_area_stun price a champion as spell_base() x pair(me, e) (INT:66-70),
// not camp_damage_factor. 4 AKILL when the area kills the focus, the nuke / damaging stun on another foe does not take the turn's one
// cast (GR:262). 8 FOGW the wake guards also count fogged sleeping attacker groups near the centre (memory, as lw_bad). 16 RENT the
// area selectors and the Heart landing skip tiles whose Ren retaliation kills me (a rejected best tile lost the cast). 0 = off.
// v654 BB12: area-spell fixes (BB12)
inline bool bb12_akill = false; // BB12 bit 4: this fight turn's area kills the focus

// PFC (b1777, pra2f fuel: the flee dash-escape path that PRA2 a1's later-acting low-HP bodies run). Removed work only, play-identical.
// Read first; 0 = off. Bit 1: dash_away returns before the landing search when staying is already outside every zone (danger 0: no
// landing can beat it). Bit 2: dash_path_ok runs dash_legal_between once (a 2-step dash with BGX bit 2 tested it twice).
// v672 PFC: escape-40 off + flee-path fuel cuts (PRA2F)

// KTB: kill-test bugs (Rule Checker, bot_errors.md "Kill tests", v669). Runtime data flag KTB_TAB[1], read first; 0 = off. Bits: 1 KTB1
// spell_alone_kills counts ranged kits (a ranged area kill at range + radius, GR:576/606); 2 KTB2 after a first-hit kill the reset hits
// a living foe that is not the dead focus's linked C&I partner (GR:442); 4 KTB4 hit-back's kill test is kills(e, d, 0), not KQ_RAW;
// 8 KTB8 lb_zones skips a C&I body whose visible partner passes kills(..., 0); 16 KTB16 Heart's landing and Varg's no-wake price
// champion kills as champion damage (-dash_mod: BB12 KPAIR; str x passive_mult); 32 KTB32 the pair spell-kill picker keeps a spawn foe
// the spell kills (INT:97) and ranks by hunt_prize (both C&I bags, GR:381); 64 KTB64 Vesper's dash kill needs a dash landing tile with
// at most VV_LANDING_CROWD other enemies; 128 KTB128 kills(..., 0) is false when Ren's retaliation kills me.
// v675 KTB: 3 fixes ssgrev,bb41,ktb64r

// KFX (b1782, Rule Checker's v675 review). Runtime data flag, read first; 0 = v675. Bit 1: kills_ranged_knr runs Vesper's dash landing search
// (ktb_vesper_landing_ok) only after the cheap tests (no walk reset, the hit kills): play-identical, fuel only. Bit 4 (BTL): btl_too_late
// reads "too late" when neither an altar walk nor a home altar exists (bd and ha both UNREACH). Bit 2 (WBQ scope) not built: it changes when
// a Prism carrier starts a tribute (owner rule).
// v677 KFX: 4 fixes hvb56c,drs,kfx,sjb1
// FAC (Rule Checker fight-actions pass, fac_rulecheck_1110.md; b1780; bug bar, one bit per row). Runtime data flag FAC_TAB[1], read
// first; 0 = off. Bit 1 FAC1: fight_threat_stun keeps the one cast (GR:262) for the area kill on the focus (bb12_akill), as
// fight_stun_nuke_other does. Bit 2 FAC2: fight_stun_nuke_other leaves a stun-immune focus's threat to fight_threat_stun
// (stun_threat_instead_of_focus). Bit 4 FAC4: a ranged body skips the bush perch step when the shot-before-walk gate passes (walk and
// attack share one allowance, GR:100). Bit 8 FAC8: fight_hold_outlasted counts a focus once a round (a second fight() reset it to 1).
// Bit 16 NL1 (asx_rulecheck_1110.md): no_lone_fight's allies4 leaves out channelling mates (recall, tribute).
// Bit 32 KHK (fac_rulecheck_1110.md): the lethal-burst flee dash skips Heart landings that wake another group's sleeping camp.
// Bit 64 KIT1: fight_area_try counts a foe on its own spawn only when the area kills it (it heals to full, GR:153; a stun kit keeps
// counting it). Bit 128 KIT2: fight_vesper_dash keeps the dash when Ren's retaliation would kill me (attack_champion refuses).
// Bit 64 also VMR4: an area stun weighs a foe Marcella as a stunned body (a stun on her is wasted, GR:658). Bit 256 VMR1: Varg's reset
// re-target skips a camp whose splash wakes a sleeping attacker group, even the last camp. Bit 512 VMR2: the spare claimed-camp hit
// (econ_locks) runs prestep_splash_ok for Varg.
// v680 FAC: 4 fixes msy7,fac,flr,lck
#define FAC_BITS 1023
inline constexpr int FAC_TAB[2] = { 0x46414331, FAC_BITS }; // slot 0 magic keeps it out of .bss

// LCK (b1782, Rule Checker's altar-lock audit lck_rulecheck_1110.md). Runtime data flag, read first; 0 = v679. Bit 1: game_deny's ranking
// (game_deny_can_cancel_channel) gives a mate no lock option at an altar where a mate already channels (a lock there cancels our own
// tribute, INT:121), as game_deny_lock_way does for me. Bit 2: walk_to_free_twin_altar does not walk when the enemy lock in reach clears
// in hits_remaining <= steps - 1 hits (5 hits clear a lock, GR:238; the last hit can share a turn with the tribute, INT:122). Bit 4
// (Marcella, never the Prism): channel_safe_check<STUN> counts a recent sighting within 5 + the channel's span as a possible lock carrier
// (a lock needs no sight, INT:123; dash reach, INT:30). Bit 8 (CRY, cry_rulecheck_1110.md): spawn_crystal_prebuy and recall_hop_prebuy keep
// 10 gold for a wanted lock: no crystal under 20 gold while I carry no lock and want one (bag >= LL_BAG or game_deny_lock_wanted).
// v680 LCK: 4 fixes msy7,fac,flr,lck
#define LCK_BITS 7
inline constexpr int LCK_TAB[2] = { 0x4C434B31, LCK_BITS }; // slot 0 magic keeps it out of .bss
// CIB: C&I bug rows (CI Analyser + Rule Checker srf/tie_rulecheck_1110). Runtime data flag CIB_TAB[1], read first; one bit per row.
// 1 Cassi's camp nuke held while a foe is within STUN_HOLD_R (seen now or by the team within 2 rounds), unless it finishes the camp;
// 2 the camp stun hold also counts a foe the team saw within STUN_HOLD_R in the last 2 rounds; 4 pair_bag reads the partner's bag as 0
// once she/he was last seen tributing within 1 of an altar; 8 issac_order tests the camp tie with the partner directly (camp_threat
// already drops the ties I lose, SRF1: a tie with the partner also passes the gate); 32 issac_order's tank cap uses the bodies' tie_prio,
// not the static P.prio (TIE2); 64 the hunt lock expires once its foe was unseen for over 3 rounds (Rule Checker srf possible, as combat_team.cc:59).
// v682 CIB: 7 fixes fb10c,cpt29c,cpt29c,grd3c,cib47,cpw1,cis7
#define CIB_BITS 47
inline constexpr int CIB_TAB[2] = { 0x43494231, CIB_BITS };
// CPW (b1794, Rule Checker CPW1, bug bar). Runtime data flag CPW_TAB[1], read first; 0 = v681. Bit 1: pair_work_share counts a body's
// Focus term only when its kit has a Focus-scaled damage, stun, area or dash spell (dmg+cc+aoe+dash mods > 0), as Issac's is left out.
// v682 CPW: 7 fixes fb10c,cpt29c,cpt29c,grd3c,cib47,cpw1,cis7
#define CPW_BITS 1
inline constexpr int CPW_TAB[2] = { 0x43505731, CPW_BITS };
// CIS (b1794, small C&I/combat bug rows, bug bar). Runtime data flag CIS_TAB[1], read first; 0 = v681. Bit 1 (ftc, pvb_rulecheck_1110):
// foe_turn_counts_fill gives a foe that acted an extra turn only while some live foe is unseen (W.enemies < enemies_alive), not < 6.
// Bit 2 (HDV1, Heart dash_stun): a dash landing refused by lethal_burst_landing_bad passes when it does not without the foes the landing
// stuns (within dash_radius, not stun-immune, acting at most once before). Bit 4 (CAP (a), cap_rulecheck_1110): WL2 decision 7 and CI2
// yield_capture leave a group only for a mate on its spawn tile that claims it (a mate crossing the region does not take it, GR:196).
// v682 CIS: 7 fixes fb10c,cpt29c,cpt29c,grd3c,cib47,cpw1,cis7
#define CIS_BITS 5
inline constexpr int CIS_TAB[2] = { 0x43495331, CIS_BITS };
// PHY (CI analyser item 13, Rule Checker + Combat; b1760): R3's lethal test counts the foes' turns from my own next-round value, the value I
// hold. Holding 40 reads "not lethal", 40 drops, the foe doubles me, 40 comes back. Bit 1 (adaptation, cheap): while I hold 40, the test
// runs with my next-round rank taken at the value I would write; the turn table is reused with only my rank swapped (no new priority
// reads), once a round. 0 = v677.
// v685 PHY: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define PHY_BITS 1
inline constexpr int PHY_TAB[2] = { 0x50485932, PHY_BITS };
// CIA (b1794, CI Analyser C&I follow-ups to v682, bug bar). Runtime data flag CIA_TAB[1], read first; 0 = v682. Bit 1 (CIA1): assist_cast_slow
// keeps Cassi's camp nuke while CIB bit 1 holds it (a foe the team saw within STUN_HOLD_R in the last 2 rounds). Bit 2 (CIA3): CIB bit 4 zeroes
// the unseen partner's bag only once his tribute could have landed (over max(1, ceil(bag / 10)) + 1 rounds since he was seen tributing).
// v685 CIA: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define CIA_BITS 3
inline constexpr int CIA_TAB[2] = { 0x43494131, CIA_BITS };
// HLD (b1786, Rule Checker mct_hld_spec_rulecheck_1110.md, HLD1 + deny-force + EG4c). Runtime data flag, read first; 0 = v682.
// Bit 1: hold_lethal skips the tributing target (it hits only by cancelling its tribute, GR:275, INT:125) and never vetoes an ending
// deny (GR:29). Bit 2: hold_lethal sums the basic hit each turn the foe reaches (d closing 1 a turn) plus its best spell surplus once
// (a cast starts an 8-turn cooldown, GR:262), not the best hit wait+1 times. Bit 4: a game-ending deny stun skips cast_via_sdk's
// self-preservation vetoes (Ren retaliation, foe guard, landing burst). Bit 8 (EG4c): winning_bag_flipflop_clear's race test lands at
// round + walk + ticks - 1 when walk > 0 (the walk's last step and the first tick share a round).
// v685 HLD: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define HLD_BITS 1
inline constexpr int HLD_TAB[2] = { 0x484C4431, HLD_BITS }; // slot 0 magic keeps it out of .bss
inline bool hld_force = false; // HLD bit 4: set only around a game-ending deny stun
// TIS (Combat ruling 10 Nov, turns_if_still; b1760): the turns a still-to-act foe gets before my next turn. Today every one counts 2. Bit 1 (A):
// the exact count, 1 + (it acts before me next round). Bit 2 (B, Combat's pick): A, or 2 when this body saw the foe change its priority
// within the last 10 rounds (64% of killer doubles come from the foe's own change, INT:24). 0 = v685.
// v687 TIS: 5 fixes tisbd,ip3rsgb,soi,ip3rsgs,bef32
#define TIS_BITS 2
inline constexpr int TIS_TAB[2] = { 0x54495331, TIS_BITS };

// BEF (b1789, Rule Checker bot_errors triage v682/v684): open rows, one bit each. Runtime data flag BEF_TAB[1], read first; 0 = off.
// Bit 4 (row 553): recall_loop_guard never refuses a walled-in body (no walk home: the recall is its only way out).
// Bit 16 (row 157): fight_hit_nearby hits the weakest foe in range first, not the first listed (their spawn excluded).
// Bit 32 (row 824): gold_weight_in_gems counts gold as a full gem only when no bank is possible (bankable(), not just no walk altar).
// Bit 64 (row 685): a foe that can reach me soon counts in full even alone (no symmetric-fight discount without a pack).
// Bit 256 (row 554): the carry recall starts only when no seen foe can hit me before it lands (any damage cancels it, GameRules:275).
// v687 BEF: 5 fixes tisbd,ip3rsgb,soi,ip3rsgs,bef32
#define BEF_BITS 32
inline constexpr int BEF_TAB[2] = { 0x42454631, BEF_BITS }; // slot 0 magic keeps it out of .bss
// HCP (b1809, HCP1). Runtime data flag, read first; 0 = v685. heal_of counted heal_mod x Focus per cast whatever the targets lack. A heal
// restores UP TO 3 x Focus to ANOTHER allied champion (GR:724). Bit 1: each cast is capped at min(3 x Focus, the largest missing HP among the
// healer's other allies within its heal range + 1). Bit 2: a stunned healer's next cast is one turn later (the stun takes its turn).
// Owner's Prism rule: off while I am the Prism, so her assessments (tribute readers) keep v685's values.
// v688 HCP: 3 fixes bkg1ff,hcp3,pho1
#define HCP_BITS 3
inline constexpr int HCP_TAB[2] = { 0x48435031, HCP_BITS }; // slot 0 magic keeps it out of .bss
// BHW (b1808, X68 BSW1). Runtime data flag BHW_TAB[1], read first; 0 = v693. A hidden-occupant refusal (GR:169: false, no cost, try another
// tile) holds every later step that turn; bush_hold_turn's low-fuel exit (and a CALM read) then ended the walk. Bit 1: once the hold is
// released there, a body that can still move retries the refused direction turned 45 degrees each way (first free tile).
// v695 BHW: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define BHW_BITS 1
inline constexpr int BHW_TAB[2] = { 0x42485731, BHW_BITS }; // slot 0 magic keeps it out of .bss
// b1802 CFH (Combat, owner_01a1c4c8_72a2_1110 "Spec CFH"): runtime data flag, 0 = off. Cassi only (ci_layer::me_cassi()).
// Bit 1 RANGE 4: fight_walk_in steps her to range CFH_R (not W.me.range) while her damage or stun slot is ready (reopen of b915 bit 1).
// Bit 2 FRONT HOLD: fight_choose_hold gives her support_hold_back outside kill_window, only while a seen foe's one-turn burst >= her eff
// HP (the glass test). Bit 4: bit 2 without the glass test.
#define CFH_BITS 1
// v697 CFH: CFH, Cassi steps to range 4 when slot ready
#define CFH_R 4
inline constexpr int CFH_TAB[3] = { 0x43464831, CFH_BITS, CFH_R }; // slot 0 magic keeps it out of .bss
// PDZ (b1791, Deep spec_pdz_1110.md). Runtime data flag, read first; 0 = v698. Bit 1 (rules bug): foe_two_turn_reach counts a foe dash
// at cooldown 1 as ready (cooldowns tick at the owner's turn end, GR:118/124, so it is ready on the foe's second turn). Bit 2: for a
// Prism body, the flee zones and danger_veto (foe_two_turn_reach) take the TIS turn count; her tribute start/keep keeps today's count.
// v708 PDZ: baked at its shipped value
#define PDZ_BITS 1
inline constexpr int PDZ_TAB[2] = { 0x50445A31, PDZ_BITS }; // slot 0 magic keeps it out of .bss
// b1816 CKF (Deep, spec_ckf_1110.md): runtime data flag, 0 = off. Bit 1: Cassi's kite FLEE (kite_now: melee foe within CI2_KITE_G, her
// stun down) is re-applied after peel and the hunt leash, which turned it back to FIGHT (a code-order bug); reach_burst still runs after.
// Bit 2 (b1820): the same override only while a melee foe's one-turn burst on Cassi is >= 25% of her HP + shield (ckf_burst_heavy).
// v708 CKF: baked at its shipped value
#define CKF_BITS 2
inline constexpr int CKF_TAB[2] = { 0x434B4631, CKF_BITS }; // slot 0 magic keeps it out of .bss
// HPR (b1789, Deep spec_hpr_1110, owner replay 01a1c59f). Runtime data flag HPR_TAB[1], read first; 0 = v698. Foe memory (seen) kept a foe's
// health from my turn start, never lowered by my own hits that turn: a foe that then left sight stayed at its pre-hit HP (stance ratio,
// BKC's low-HP chase test). Bit 1: at turn end, re-read the champions my attacks and casts hit (and those within 1 of a hit / an area
// point) and overwrite their sighting's eff HP; arm BKC on my focus when the fresh fraction is under BKC_HP.
// v699 HPR: refresh foe HP memory after own hits
#define HPR_BITS 1
inline constexpr int HPR_TAB[2] = { 0x48505231, HPR_BITS }; // slot 0 magic keeps it out of .bss

// HPU (b1789, docs/bot_errors.md SHIP v699 HPRU1/HPRT1): v699 HPR fixes. 0 = v699. Bit 1 HPRU1: hpr_refresh reads the foe's HP in
// eff_hp's units ((hp + shield) x mi_inv, Durability-scaled under B_FULL) like every other memory writer. Bit 2 HPRT1: the refresh
// also runs after turn_tail, whose champion hits it never saw.
// v701 HPU: HPR refresh uses Durability-scaled HP
#define HPU_BITS 3
inline constexpr int HPU_TAB[2] = { 0x48505531, HPU_BITS }; // slot 0 magic keeps it out of .bss
// THR (b1802, Rule Checker THR1, bot_errors.md Pass 6 X144). Runtime data flag THR_TAB[1], read first; 0 = v702. Bit 1: the threat-stun
// tests (fight_threat_stun, combat_cast.cc stunnable_foe_has_ally_in_reach) count a melee foe's step + hit (GR:161: reach range + 1);
// a ranged foe keeps its basic range. Before, a melee foe 2 tiles from a mate was no threat and the stun went elsewhere.
// v708 THR: baked at its shipped value
#define THR_BITS 1
inline constexpr int THR_TAB[2] = { 0x54485231, THR_BITS }; // slot 0 magic keeps it out of .bss
// VLS (b1816, Rule Checker VLS1, owner replay 01a1c5d6 r781-786: Vesper shot instead of stepping in FLEE). Runtime data flag, read first;
// 0 = v700. Bit 1: react_kite's `forced` (the shot replaces the escape step) is also cleared when a foe that is not adjacent melee has me
// within its next-turn reach (foe_next_turn_reach(e, false), as the flee zones count it), not only within its basic range.
// v703 VLS: kite shot only if all reachers adj melee VLS1
#define VLS_BITS 1
inline constexpr int VLS_TAB[2] = { 0x564C5331, VLS_BITS }; // slot 0 magic keeps it out of .bss

// AFR (afr, AFR42 build_b1818_bughunt.md, Rule Checker confirmed 10 Nov): bit 1: attack_champion retries once on the weakest other live
// foe in reach after ANY refused hit, not only after my own cast (a refused attack spends nothing, GameRules.md:118; interactions.md:32).
// 0 = nova_base_v703.
// v711 AFR: baked at its shipped value
#define AFR_BITS 1
inline constexpr int AFR_TAB[2] = { 0x41465231, AFR_BITS }; // slot 0 magic keeps it out of .bss

// VLC (b1816, Rule Checker X144/C35: the complete VLS1 form, owner replay 01a1c5d6). Runtime data flag, read first; 0 = v703. Bit 1:
// react_kite's `forced` (the shot replaces the escape step) holds only when an adjacent melee foe exists AND no other foe has me within
// foe_next_turn_reach; with no adjacent melee foe the shot never replaces the step (one-turn reach misses a two-turn threat).
// v704 VLC: kite shot needs an adjacent melee foe (VLS2)
#define VLC_BITS 1
inline constexpr int VLC_TAB[2] = { 0x564C4331, VLC_BITS }; // slot 0 magic keeps it out of .bss

// GDN (b1789, spec_rcp4_1110 P1; docs/bot_errors.md GDV1, X25 GDL1/GDS1): game-ending deny rule fixes. 0 = v702.
// Bit 1 GDV1: a game-ending deny cast skips cast_via_sdk's survival and spawn-landing vetoes. Bit 2 GDL1: the deny lock counts a
// ready dash (dash, step, lock: reach dash + 3). Bit 4 GDS1: can_cancel books walk + 1 turns for a walk-excluding stun (INT:28).
// Bit 8 EGS: game_deny_pick sums concurrent foe channels (spec_egs_1110). GDD1 shipped in v702 (R2B bit 1);
// IRS1 (count .03/g < .1) is not here.
// v711 GDN: baked at its shipped value
#define GDN_BITS 15
inline constexpr int GDN_TAB[2] = { 0x47444E31, GDN_BITS }; // slot 0 magic keeps it out of .bss
namespace nova::combat {
inline bool gdn_end_cast = false; // GDN bit 1: set only around game_deny_slow's two cancel calls when the channel ends the game
} // namespace nova::combat
// GDM (b1802, Rule Checker C38 /data/zw4424/rulecheck/p6/c38_gdn_fhx.md: GDL1 completion). Runtime data flag GDM_TAB[1], read first; 0 = off.
// Bit 1 GDL1a: gdn_dash_lock_go's dash runs with gdn_end_cast = ending (GDV1 then skips the dash-landing vetoes for a game-ending
// channel), and for any other pick gdn_dash_lock_landing skips landings those vetoes refuse (Ren retaliation, latch guard, lethal
// landing, spawn pin), so t_lock = 1 is booked only for a dash that goes. Bit 2 GDL1b: deny_memory::act keeps the walk-only gate
// (its path never casts the dash, and an unseen channeler is not game_deny_slow's to take over).
// v711 GDM: baked at its shipped value
#define GDM_BITS 3
inline constexpr int GDM_TAB[2] = { 0x47444D31, GDM_BITS }; // slot 0 magic keeps it out of .bss
namespace nova::combat {
inline bool gdm_ending = false; // GDM bit 1: game_deny_slow's pick ends the game (set before its lock way, read by the landing search)
} // namespace nova::combat

// DLK (b1816, Deep spec_dlk_1110, crit 01a1c679 r741). Runtime data flag, read first; 0 = v706. Bit 1: on the game-ending lock path
// (combat_deny.cc game_deny_slow) with more than DLK_T ticks left and every lock tile lethal to me (danger_veto >= my effective HP:
// the channeller cancels and kills, as N did), I do not place the lock: I hold on the least dangerous tile. Locking resumes at ticks
// <= DLK_T, when a non-lethal lock tile exists, or when no mate can deny in time and the ticks left are within my walk + 2.
#define DLK_BITS 1
// v709 DLK: no early game-end lock that kills placer (DLK)
#define DLK_T 8
inline constexpr int DLK_TAB[3] = { 0x444C4B31, DLK_BITS, DLK_T }; // slot 0 magic keeps it out of .bss
// HFX (b1831, Combat spec_hfx_1110; 02the_pond 01a1c6d2 r604-611). 0 = v708. hidden_fire_slow (combat_calm.cc) on a turn whose damage
// exceeded the visible awake camps' strength (cex_round == now): bit 1 adds the unlit bush tiles within HFC_TAB[2] as threats beside the
// camps that explain part of it (live adds them only when no camp explains anything, so the escape left the camp and kept the bush
// shooter's range); bit 2 skips the capture-pay hold then (the excess source is not a camp: the capture does not end it).
// Bit 4 HFB1 (RC X199): the bush scan fills its 24 entries nearest ring first, not row by row (hfb_bush_scan). Bit 8 TRH1 (RC X199):
// tribute_restart_hold counts an excess hit (cex_round) as hidden and escapes with the same 5/5 nearest-first scan, not bushes within 2
// at reach 1.
// v710 HFX: 3 fixes sir1gt,hfx2s,cbh58
#define HFX_BITS 13
inline constexpr int HFX_TAB[2] = { 0x48465831, HFX_BITS }; // slot 0 magic keeps it out of .bss

// FWB (b1831, Deep spec_fwb_1110; bug bar). 0 = v714. Bit 1 FWB1: bush_watched's foe-ward branch tests whether the ward actually sees the
// bush tile (cambc::ward::visible_tiles_from_into: sight 6, shadowcast, and no sight into another bush cluster, GR:106, :353-355,
// BalanceChanges:24), not any foe ward on a bush within BUSH_SEE_R (8). The foe-body branch (a guess: bodies move) is unchanged.
// v718 FWB: 2 fixes csw1si,fwb1si
#define FWB_BITS 1
inline constexpr int FWB_TAB[2] = { 0x46574231, FWB_BITS }; // slot 0 magic keeps it out of .bss

// DTA (b1832; Deep sbg_v717_1111, 04plaza 01a1c7db-62fa-762f r554-571; donor nova_dp_dta1). 0 = nova_b12061_pfb253srs. Bit 1: game_deny_slow's
// deny altar skips one that our own lock already holds when another altar is as near the channeller (a foe channel cannot run on our lock,
// GR:240/244; place_lock refuses it, BBL): the first tie altar without our lock instead.
// v724 DTA: lock the tie altar our own lock doesn't hold (DTA)
#define DTA_BITS 1
inline constexpr int DTA_TAB[2] = { 0x44544131, DTA_BITS }; // slot 0 magic keeps it out of .bss
// DLF (dlf, spec_dlf_1110, Combat; 03membrane v Fish r251-272, gemcombat4): deny a seen big non-ending tribute with a lock. 0 =
// nova_base_v717. Bit 1 PICK: game_deny_pick also takes a SEEN non-ending foe tribute with bag >= DLF_BAG when I carry a lock, no ally
// channels at that altar and the walk to the lock ring fits its ticks; the lock way only. Bit 2 FLEE PASS (with 1): such a pick is
// not dropped by FLEE when my HP >= 80% (dlf3c: the pre-stated adaptation, 60 -> 80), no visible foe's next-turn sum kills me and I carry no winning bag.
#define DLF_BAG 40
// v725 DLF: lock seen tribute, FLEE pass at 80% (DLF adapt)
#define DLF_BITS 3
inline constexpr int DLF_TAB[2] = { 0x444C4631, DLF_BITS }; // slot 0 magic keeps it out of .bss
// BSF (b1816, Rule Checker BPP1, owner replay 03contours 01a1c784 r603-612: carrier stance flicker). Runtime data flag, read first;
// 0 = v717. Bit 1: in assess_rule_local_power, a carrier (bag >= FLC_BAG) that fled within HYST_ROUNDS and is now in FIGHT at local
// power < POWER_LEAVE (not a kill, not caught) goes back to FLEE (a foe near its reach) or CALM: the base stance's inflated ratio no
// longer pulls a fleeing bag back into a fight the local power calls a leave. Bit 2 (pre-stated adaptation after bsf1 failed rare .4952
// n420; BPP1's adaptation 'bag floor 20, scaled by the stake'): the same rule from a bag of BSF_TAB[2] (20) instead of FLC_BAG, at a
// power bar of POWER_LEAVE x stake (stake_bars' share: max(min(1, bag / WFF_STK_MIN 80), min(1, bag / need))): a bag of 80+ or a
// bag that wins the game keeps bit 1's bar; a bag of 20 leaves only at a quarter of it (arm BSF_BITS=3).
#define BSF_BITS 3
// v732 BSF: stake-scaled BSF (bsf2, adaptation)
#define BSF_BAG2 20
inline constexpr int BSF_TAB[3] = { 0x42534631, BSF_BITS, BSF_BAG2 }; // slot 0 magic keeps it out of .bss

// BFP (b1853, Rule Checker ship_v732 BSF-P1): BSF pulled a carrier out on 'fled recently' alone; assess_hysteresis also needs the flee to be the
// latest action when both timers are recent (tie = flee). Runtime data flag BFP_TAB[1], read first; 0 = off. Bit 1: BSF does not fire when I
// fought within HYST_ROUNDS after my last flee.
// v734 BFP: BSF-P1 flee must come last
#define BFP_BITS 1
inline constexpr int BFP_TAB[2] = { 0x42465031, BFP_BITS }; // slot 0 magic keeps it out of .bss

// XIC (b1848; RC X294/X296/X298/X303/X306 identical fuel cuts, second bundle beside XIB). 0 = v722. Each bit gives the same play with less
// fuel (cxeident identical per bit): 1 ESN1 enemy_spawn_near at r 2 reads one bit of the spawn board grown by 2 (built once); 2 UNR1
// unreachable() tests the spawn bit before the reach; 4 FLR1 finish_low tests the HP share before unreachable(); 8 ACW1 ally_commit_weight
// stops at the first foe within 3; 32 FA3 pick_focus skips the focus whose kill test just failed; 64 TBT1 build_team rebuilds TM.by_tank
// only when the tank order or TM.n changed; 128 CTO1 compute_travel always takes the one-read path; 256 PKD1 read_packed_team_word's
// packed loop drops the dead shifts; 1024 BCT1 bush_chase_track tests the focus match first; 4096 EVW1 best_group's ev vector becomes a
// bool; 16384 HCX1 he_group only in the multi-trip test; 131072 SRT3 best_within partial_sort to SQ_WITHIN_MAX; 262144 SRT4 of_build
// counting sort above 48 members. Dropped at the per-bit fuel table (not fuel-negative): FDR1, SAL1, CLM1, CUF1, SRT2, WAC1.
// v738 XIC: X294-X306 identical fuel cuts (XIC)
#define XIC_BITS 415215
inline constexpr int XIC_TAB[2] = { 0x58494331, XIC_BITS }; // slot 0 magic keeps it out of .bss
namespace nova {
inline constexpr int xic_bits = XIC_TAB[1]; // v740 baked: copy of the baked flag word
inline int xic_tbt_ver = 0; // XIC bit 64: bumped by plan_tank_order
}
#define XIC_ON(b) ((::nova::xic_bits & (b)) != 0)

// PTW (b1836, spec_ptw_1111 Prism Improver; RC C148; gemcombat3 01a1c91f r145): PTS1's two-turn-foe refusal of the parting stun is lifted
// when no neighbour tile leaves the flee zones (the step stays inside its reach anyway, so the stun is never worse). Runtime data flag
// PTW_TAB[1], read first; 0 = v741. Bits: 1 NO EXIT; 2 DUEL ONLY (bit 1 only when that foe is the only one within its reach + 1 of me);
// 4 MIRROR ONLY (bit 1 only for our Prism v a foe Prism). Arm ptw3 = 1 + 2.
// v743 PTW: parting stun when no step leaves a duel reach
#define PTW_BITS 3
inline constexpr int PTW_TAB[2] = { 0x50545731, PTW_BITS }; // slot 0 magic keeps it out of .bss
// CMK (cmk, RC X337 CMK1): no hit on a camp already dead this turn (engine refuses rc 42 / rc 30, INT:32). 0 = nova_base_v741. Bit 1:
// prestep_hit_camp and camp_hit_plain read the engine alive state first and hand a dead target's hit to the next living camp in basic
// reach (next_camp_after_kill); cast_on_camp skips a dead camp.
// v744 CMK: no hit on a camp dead this turn (CMK1)
#define CMK_BITS 1
// bk5 KWC (b1429; bank bk5b hand rebase onto v708): bit 1, kill_window drops a tributing/teleporting foe (not stunned) whose channel
// completes before my next turn (it answers then; GameRules.md:232, :275). Runtime data flag, read first; 0 = off.
// v745 KWC: fpb5 bank bundle bk5b+ehc3s+rts
#define KWC_BITS 1
inline constexpr int KWC_TAB[2] = { 0x4B574331, KWC_BITS }; // slot 0 magic keeps it out of .bss
inline constexpr int CMK_TAB[2] = { 0x434D4B31, CMK_BITS }; // slot 0 magic keeps it out of .bss
// ATR (b1821, RC C158): camp attacks after a walk or dash on a camp out of my current vision (engine rc 42; the camp-state read gives
// rc 97 api_not_in_vision; W.camps was read at perceive). Bit 1: attack_camp and camp_hit_plain skip that refused call (the spin cancel
// still runs). Bit 2: hit_camp, before the walk reset, retargets to a camp in basic reach in current vision; none: no reset, no hit.
// v746 ATR: no camp hit out of current vision
#define ATR_BITS 3
inline constexpr int ATR_TAB[2] = { 0x41545231, ATR_BITS }; // slot 0 magic keeps it out of .bss

// GDW (b1836, spec_gdw_1111 Deep / RC MF3, and RC X318 DLS1; reopen on v746, 04keyhole 01a1c9ee r906-931): the game-ending deny walks run
// outside the foe walk guard (the BBM bake left SuspendFoeGuard(false) at the three walks, so step_to_set fails while the lock way says the
// lock fits; 01corridors 01a1c894 r1320-1325). Runtime data flag GDW_TAB[1], read first; 0 = v746. Bits: 1 GDW1 game_deny_slow's walk when
// ending; 2 GDW2 game_deny_follow_channel's walk on a game-ending memory and deny_memory's walk; 4 DLS1 the step after a game-ending
// dash-lock landing (gdn_dash_lock_go).
// v749 GDW: game-ending deny walks ignore the foe guard
#define GDW_BITS 7
inline constexpr int GDW_TAB[2] = { 0x47445731, GDW_BITS }; // slot 0 magic keeps it out of .bss
// ACX (b1831, Planner spec_acx_1110, RC X249). 0 = v715. Map classes from map data (acx_classes, computed once; MCL class bits from
// Shared Mem pending): CLUSTER = attacker groups hold < 10% of the walkable gems; GOLDFREE = walkable gold per champion < 60 (the draft's
// F_GOLD_RATE test). Bit 1 ACC (CLUSTER): contest_capture_turn_slow's gem gate also passes a group of >= max(21, half the largest walkable
// gem group). Bits 2 / 4 / 8 ACE (GOLDFREE, one dose): engage -.20 / -.30 / -.10, flee threshold -.08 / -.12 / -.04.
// v752 ACX: cluster-class contest gate (ACX ACC)
#define ACX_BITS 1
inline constexpr int ACX_TAB[2] = { 0x41435831, ACX_BITS }; // slot 0 magic keeps it out of .bss
// v716 ACX: class bits (1 CLUSTER, 2 GOLDFREE) and the largest walkable gem group, from map data once M is built.
struct AcxMap
{
	int bits = -1, big = 0;
};
inline AcxMap acx_map;

// DLA (dla, b1978, RC X427 DLA1): dlf_pick_ok's lock-only admission. 0 = live. Bits: 1 = left floor max(1, left), 2 = ready dash adds 2 reach.
// v771 DLA: DLA1 lock-only pick: 0-tick floor + dash reach
#define DLA_BITS 3
inline constexpr int DLA_TAB[2] = { 0x444C4131, DLA_BITS }; // slot 0 magic keeps it out of .bss
#define DLA_ON(b) ((DLA_TAB[1] & (b)) != 0)
// HSK (b2084, RC X521 CCE1/CCE2): a capture hold that only basic-attacks also casts my ready single-target damage spell on the weakest
// visible foe in its range (hold_shot, spell_poke_slow's damage branch). 0 = live. Bits: 1 the game-ending contest hold (capture_end::end_turn);
// 2 the contest hold (contest_capture_turn_slow); 32 the game_deny in-place hold and the dlk_hold
// stand (keep stun). Guards as free_cast: no foe on its own spawn, no Ren whose retaliation kills me.
// v805 HSK: HSK 1+32 confirm on v798 (passed v796)
#define HSK_BITS 33
inline constexpr int HSK_TAB[2] = { 0x48534B31, HSK_BITS }; // slot 0 magic keeps it out of .bss
// b2140 CGW1 (RC X545, owner: no round gates): bit 1 turns MUL bit 4 B_COMING on at its one read site (assess_coming_body): an unseen
// coming mate at its last-seen stats (econ::mul_mate_ls), and gf = 1 (no round growth on the fallback or the post-death floor). Ship form: MUL_BITS 974.
// v800 CGW: owner rule no round-gated term CGW1
#define CGW_BITS 1
inline constexpr int CGW_TAB[2] = { 0x43475731, CGW_BITS }; // slot 0 magic keeps it out of .bss
// b2140 RGL (RC X545, owner: no round gates): bit 1 A17 drops buy_altar_lock's W.round < 40 (the bag gate decides); bit 2 GD_LATE
// drops the W.round >= GD_LATE term of the game-deny flip test (deny_pick / the group pick): the tribute state alone decides.
// v802 RGL: owner rule drop GD_LATE round term
#define RGL_BITS 2
inline constexpr int RGL_TAB[2] = { 0x52474C31, RGL_BITS }; // slot 0 magic keeps it out of .bss
// DDL (b2145, RC X555 DDL1, INT:120): no lock/deny pick on a foe channel that cannot land by GAME_END (round + ticks left, +1 when
// the foe has acted this round). 0 = live. Bit 1: deny_tribute_slow and dlf_pick_ok.
#define DDL_BITS 1
// v803 DDL: end-game r2000 landing tests TDE1 DDL1 BFE1
#define DDL_END 2000 // the last round (GameRules; econ::GAME_END is not in scope here)
inline constexpr int DDL_TAB[2] = { 0x44444C31, DDL_BITS }; // slot 0 magic keeps it out of .bss
// IMH (b2145, spec_imh_1112, RC CW2 + HP4, C555): idle_mate_help_power counts only mates help_join would send. 0 = live. Bit 1 (HP4,
// bug bar): no mate in a fight state (claim kind 4), none farther than FL_JOINETA (FL_TAB[3]) from me, and none at all under a fresh
// hold/retreat fight call within 6 of me (help_join :109/:123). Bit 2 (CW2, behaviour): no mate whose bounded walk to me exceeds
// FL_JOINETA + 2 (one field from me per round; below IMH_FUEL no field and the mate stays).
#define IMH_BITS 1
// v804 IMH: IMH help power counts only mates help_join sends
#define IMH_FUEL 20000
inline constexpr int IMH_TAB[3] = { 0x494D4831, IMH_BITS, IMH_FUEL }; // slot 0 magic keeps it out of .bss
// HSKM bit 1 HSKM1 (b2158, RC ship_v805.md; minor bug bundle row): hold_shot keeps the turn's cast for the enhanced-reset stun only when the
// deny's channeller can be stunned (marcella_layer::fight_stun_holds; no channeller = live's rule, ch can be null at combat_deny.cc:778).
// 0 = v805.
// v810 HSKM: stun only when it can hold (HSKM)
#define HSKM_BITS 1
inline constexpr int HSKM_TAB[2] = { 0x48534B4D, HSKM_BITS }; // slot 0 magic keeps it out of .bss
// HYC (b2159, RC C582 HYC1 = FE6, bot_errors:1036): a hysteresis hold renews itself (a held FIGHT turn stamps last_fight_round,
// combat_fight_turn.cc fight()), so the HYST_ROUNDS damper never ends. Runtime data flag HYC_TAB[1], read first; 0 = v805.
// Bit 1: a hold chain lasts at most HYST_ROUNDS consecutive turns. Bit 2 (policy, separate read): the hold needs ratio >= HOLD_MIN + the
// bag's stake_bars flee raise.
// v811 HYC: hysteresis hold chain capped at 2 (HYC)
#define HYC_BITS 1
// b2164 LPR (Combat spec_lpr_1112, RC X591; stated reopen of S1R, behaviour lane): runtime data flag LPR_TAB[1], read first; 0 = v811.
// Bit 1: the CALM->FLEE local-power leave (combat_assess_rules.cc) fires only while a.ratio < tune::EVEN_RATIO.
// v824 LPR: local-power leave needs ratio below even (LPR1)
#define LPR_BITS 1
inline constexpr int LPR_TAB[2] = { 0x4C505231, LPR_BITS }; // slot 0 magic keeps it out of .bss
inline constexpr int HYC_TAB[2] = { 0x48594331, HYC_BITS }; // slot 0 magic keeps it out of .bss
// MPR (b2156, Combat spec_mpr_1112, RC X571 MPR1): the CI2 merged partner's damage while it posts FLEE. Runtime data flag MPR_TAB, read first;
// 0 = live. Bit 1 SKIP: a merged partner posting FLEE (retreating_mates::retreating) adds no damage and stays merged, so it counts 0
// (RC C609 MPR-F1). Bit 2 HALF: it adds half its damage and stays merged. Arms: 1, 2.
// v816 MPR: fleeing merged partner adds no power (MPR SKIP)
#define MPR_BITS 1
inline constexpr int MPR_TAB[2] = { 0x4D505231, MPR_BITS }; // slot 0 magic keeps it out of .bss

// b2189 CNK (bot_errors CN3): bit 1 bbl_our_lock_on, a read, keeps my recall spin (its action callers cancel for themselves).
// v820 CNK: LKB recall spin, flee stand-down, RGE bag/base
#define CNK_BITS 1
inline constexpr int CNK_TAB[2] = { 0x434E4B31, CNK_BITS }; // slot 0 magic keeps it out of .bss
// b2192 EHO (bot_errors 439: the local power rule sums our side as eff_hp (shield, Durability), as the foe side (f.ehp)). Bit 1. 0 = v819.
// v823 EHO: power rule uses effective HP (EHO)
#define EHO_BITS 1
inline constexpr int EHO_TAB[2] = { 0x45484F31, EHO_BITS }; // slot 0 magic keeps it out of .bss
// b2218 ESR (RC C658 KR1/KRH1): end_stun_slow casts only a slot_cc stun, so Ryth's area stun (bit 1) and Heart of Ruin's landing dash
// stun (bit 2) never stop an ordinary foe tribute. With the bit, a kit with no slot_cc picks the same target under the same guards
// (winning bag; else bag >= CS_BAG, my bag < CS_MYBAG, the HP gate) at its area / dash reach and casts through game_deny_stun_channeler.
// v829 ESR: area and dash stuns stop tribute channels
#define ESR_BITS 3
// b2319 SFS (Combat spec_sfs_1112, RC C761/C784): the symmetric-fight discount in assess_foe_weight measured my distance from the tile I
// just fled to, so a flee step d 3 -> 4 switched the discount on and the next turn read CALM. Runtime data flag SFS_TAB[1], read first; 0 = v831.
// Bit 1: each last_flee_round write stores sfs_from = W.me.pos (the tile left); within HYST_ROUNDS of it, dn = min(dn, cheb(foe, sfs_from)).
// v854 SFS: SFS flee-from distance hysteresis (follow-up)
#define SFS_BITS 1
inline constexpr int SFS_TAB[2] = { 0x53465331, SFS_BITS };
inline constexpr int ESR_TAB[2] = { 0x45535231, ESR_BITS };
// b2301 PDK (Prism Planner spec_pdk_1112 + CORRECTIONS, RC C702 / X706 / C769; owner "prism vs prism"): runtime data flag PDK_TAB[1], read
// first; 0 = v830. Prism only. Bit 1 TWO-SHOT DISTANCE: a seen (or <= 4 rounds remembered) foe Prism with nt >= 1 turns before my next
// (hedged count; a stunned one keeps one only with a double) whose stun is castable on one of them (cd <= nt - 1) and whose stun + area
// (area cd <= nt; else stun + her basic) takes my HP + shield gets a lethal walk-guard zone of 4, or 5 at nt >= 2 (not on a winning bag's
// or a capture's walk); inside it with no kill of mine this turn I step out after the early stages. Bit 2 PUNISH: she stands within the
// stun's range, my stun is ready, bit 1's state holds or my Focus / hers >= .67, and she has < 2 turns before my next or my stun + area
// kills her: stun her first. Bit 4 SOON: horizon_fit prices a Prism's spell at cooldown c in 2..4 at (H - c) / H, for my own term and a
// foe Prism's, when I am the Prism. Bit 16 POKE: the calm poke casts the stun on the weakest champion in range when my bag >= 100 and no
// foe of the assessment with a ready gap-closer or stun (remembered: always) has me in its two-turn reach.
// v837 PDK: PDK C graded own-cooldown weight (Prism)
#define PDK_BITS 4
inline constexpr int PDK_TAB[2] = { 0x50444B31, PDK_BITS }; // slot 0 magic keeps it out of .bss

// PTD (b2337, RC X779 PTDR1, behaviour): parting_foes' PTS1 guard and its soon list bound a foe at max(reach + 1, foe_two_turn_reach)
// (a dash at cd 1 reaches 5). Runtime data flag, read first; 0 = v845. Bit 1 only.
// v851 PTD: swept v851: 0 in live and nova_b13966_rrz1r, no line flips it
#define PTD_BITS 0
inline constexpr int PTD_TAB[2] = { 0x50544431, PTD_BITS }; // slot 0 magic keeps it out of .bss
// RRZ (b2337, RC X779 RRZN1, behaviour): flee's escape_toward rally (react_rally) skips an ally inside flee()'s zones, as rally_ally
// does. Runtime data flag, read first; 0 = v845. Bit 1 only.
// v850 RRZ: RRZN1 rally point zone test
#define RRZ_BITS 1
inline constexpr int RRZ_TAB[2] = { 0x52525A31, RRZ_BITS }; // slot 0 magic keeps it out of .bss
// CBGF (b2387; RC X870 CBG1, bug bar, bundle C). Runtime data flag CBGF_TAB[1], read first; 0 = v872. Bit 1: under CI2_FIGHT(), assess's
// bag stake (combat_assess_stance.cc assess_bars_bag_and_support) reads ci2::pair_bag() (an unseen partner's last-seen bag, aged; GR:381,
// GR:442 hand it over on my death) instead of linked_bag(), which reads an unseen partner's bag as 0 (INT:22).
// v881 CBGF: baked at its shipped value
#define CBGF_BITS 1
inline constexpr int CBGF_TAB[2] = { 0x43424746, CBGF_BITS }; // slot 0 magic keeps it out of .bss
// b2365 ADC (rules-gaps L304; count v868 150x2: the area cast on camps after my own hit picks a tile with fewer live camps than the best
// in reach .070/g, a killed camp counted 1.07/g). Runtime data flag, read first; 0 = v868. Bit 1: on a turn I already hit (W.attacked),
// camp_abilities_area's grid counts only camps the engine still has alive (camp_alive_in_engine), for the area cast and the dash rebuild.
// v874 ADC: small-fix bundle A (VTKW RAK1 VCS2 PKR FMH ADC CPT1)
#define ADC_BITS 1
inline constexpr int ADC_TAB[2] = { 0x41444331, ADC_BITS }; // magic, bits
// XFZ (b2368, RC X838 freeze/path fixes, bug bar): one bit each, flag read first, 0 = live v863. Bit 1 XFZ1: dlk_hold's side step skips a
// foe-guarded tile (the refused step left the body on the tile it judged deadlier). Bits 32/64/128 XFZ3a/b/c (spec_xfz3_1113): EOX
// aligned with the approach guard (5 rounds, awake target exempt); EOX released after 2 turns with no visible foe within 8; an
// EOX-refused tile joins the turn's avoid set. Bits 2 (XFZ2) and 16 (XFZ5) fired 0 times (200 maps x 2) and are not built; 4 / 8 reserved.
// v875 XFZ: XFZ freeze-cycle bundle incl XFZ3
#define XFZ_BITS 225
inline constexpr int XFZ_TAB[2] = { 0x58465A31, XFZ_BITS }; // slot 0 magic keeps it out of .bss
__attribute__((noinline)) inline void xfz_fc_1() { __asm__ volatile(""); }
__attribute__((noinline)) inline void xfz_fc_32() { __asm__ volatile(""); }
__attribute__((noinline)) inline void xfz_fc_64() { __asm__ volatile(""); }
__attribute__((noinline)) inline void xfz_fc_128() { __asm__ volatile(""); }

// b2393 CRK (spec_crk_1113, Planner from Deep's carry-first deaths v Mite; aggression family): carry risk gate. Runtime data flag, read
// first; 0 = live. The roster lead carry = the lowest slot of the best carry type on the roster (Prism, then Vesper, then Marcella).
// Bit 1 BAG-SCALED IN-REACH BAR (RC: behaviour): for the carry with bag >= CRK_BAG1, the in-reach FIGHT bar (B467_INREACH_X100) gets the
// same stake rise stake_bars gives the flee bar. Bit 2 NO POST-BASE FIGHT BELOW PARITY: the post-base rules (converge .. no_lone_fight)
// do not turn the carry's CALM/FLEE into FIGHT while her own-view local power < 1.0, and team_stage's converge/defend walk is skipped
// for her then. Bit 4 PRISM LONE-BAG MID PICK: a Prism with bag >= CRK_BAG4 and no visible mate within 6 rates a target with contest
// > .5 at 0 (she re-rates; banking/recall stay live).
// Bit 8 CARRY WALK NO-STRIKE (Planner amendment): the carry on a walk to a camp target (econ claim, not capturing, not caught, not in
// a foe's reach (RC C1169b: the in-reach branch keeps deciding), no hit
// on her in the last 3 rounds) does not START a fight (nothing started yet) unless her focus dies to 2 of her bursts or her own-view
// power >= CRK_P8_X100 / 100; else CALM (she keeps walking). Flee and low-HP rules unchanged.
#define CRK_BITS 2
#define CRK_BAG1 40
#define CRK_BAG4 60
// v891 CRK: swept v891: shipped value with no ledger record
#define CRK_P8_X100 130
inline constexpr int CRK_TAB[5] = { 0x43524B31, CRK_BITS, CRK_BAG1, CRK_BAG4, CRK_P8_X100 }; // slot 0 magic keeps it out of .bss
#define CRK_ON(b) ((CRK_TAB[1] & (b)) != 0)
// TTCX (b2387; RC X896 TTC4/TTC5, fix lane). Runtime data flag TTCX_TAB[1], read first; 0 = v883. Bit 1 TTC4: a remembered foe keeps its
// sighting's Body (Seen.body); at use (assess_gather_remembered and the unseen legs of channel_safe_check / tribute_stop_possible) a slot whose
// cooldown was <= the sighting's age is treated as ready (cd - age), so burst and reach include it. Bit 2 TTC5: the visible damage leg of both
// channel checks counts the foe's exposure in its own turns (foe_turns_within_rounds minus the turns spent walking and the act delay), not in
// rounds, and adds once each damage spell that comes off cooldown inside that exposure, priced as f.burst (passive multiplier x the foe's
// emblem factor; RC C1190). Prefix TTCX (TTC is b2389's TTC1).
// v896 TTCX: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define TTCX_BITS 3
inline constexpr int TTCX_TAB[2] = { 0x54544331, TTCX_BITS }; // slot 0 magic keeps it out of .bss
// RFV (b2215, RC X641 row 2; was CBH bit 4 RFE1, b1816): a foe seen recalling is forgotten only once its recall could have landed
// (channel time left + 1; GR:274-275, INT:126); a recaller whose tile empties earlier cancelled and walked off. Runtime data flag, read
// first; 0 = v822.
// v896 RFV: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define RFV_BITS 1
inline constexpr int RFV_TAB[2] = { 0x52465631, RFV_BITS }; // slot 0 magic keeps it out of .bss
// TDP (b2362, RC X897 PTD1 + PSCL1; bug bar). Runtime data flag, read first; 0 = v882. Bit 1 PSCL1: tribute_stop_possible also counts the
// camps' hits on my tile over the remaining span (a camp kill stops a tribute, GR:379). Bit 2 PTD1: tribute_doomed keeps a channel with
// <= PKR_TAB[2] ticks left unless tribute_stop_possible says a stun, lock or death can still stop it (damage alone does not, GR:226/:275).
// v896 TDP: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define TDP_BITS 1
inline constexpr int TDP_TAB[2] = { 0x54445031, TDP_BITS }; // slot 0 magic keeps it out of .bss
// v7xx LDS (b2120; PF's LHS, postrecall_walkback_1112.md section 4; RC C550: any own spawn tile keeps the heal, GR:124/153/387): bit 1,
// on the spawn heal hold (retreat_to_spawn_to_heal_slow), after its hit-back and siege turn, step to the own spawn tile nearest my target
// (spawn_step's tiles) whose danger is no higher than here and under the refuge cap. Runtime data flag, read first; 0 = off.
// v904 LDS: LDS spawn-to-spawn landing step (fp)
#define LDS_BITS 1
inline constexpr int LDS_TAB[2] = { 0x4C445331, LDS_BITS }; // slot 0 magic keeps it out of .bss

// LCH (b2406, Prism Planner on owner replay 01a1d5f5: after Vendetta died our Prism chased a 98-HP Willow alone to the enemy's end for
// 30 rounds and lost 190 gems). Runtime data flag LCH_TAB[1], read first; 0 = v907. Bit 1: a body carrying >= LCH_BAG gems whose focus
// is out of range and moved away from her since last round does not walk in (fight() returns as on fight_stay_on_camp: she breaks
// off to her farm target) when all hold: (a) no living mate in W.allies within LCH_MR; (b) the step toward the focus lands nearer
// the enemy anchor than ours (d_enemy < d_home); (c) another enemy body of the team table, alive, was last seen 4..LCH_AGE rounds ago.
// RC C1399: only while nothing was cast or done this turn (a farm walk after a cast is refused) and not in stance::kill_window(f).
#define LCH_BITS 1
#define LCH_BAG 100 // slot 2
#define LCH_MR 8 // slot 3
// v909 LCH: LCH no lone deep chase with a big bag
#define LCH_AGE 60 // slot 4
inline constexpr int LCH_TAB[5] = { 0x4C434831, LCH_BITS, LCH_BAG, LCH_MR, LCH_AGE }; // slot 0 magic keeps it out of .bss

// b2453 PIR (Prism Planner spec PIR "Prism idle in reach": with a foe within 3 our Prism idles .175 of turns v the foe Prism's .107,
// the gap is idle turns with a spell ready; the dlk_hold stand (combat_deny.cc) returns true with no free hit, and its hold_shot needs a
// slot_dmg she has not). Runtime data flag PIR_TAB[1], read first; 0 = v911. Both bits act only at the end of our Prism's turn that did
// not move, hit or cast, not channelling, stance not FLEE, a visible foe within 3. Bit 2: s0 on the lowest eff_hp stunnable foe in its
// range (a tributing foe first; s0 is kept for a channeller while a deny memory is live or a tributing foe is seen out of its range), else s1 at free_aoe's tile (most foes, no
// wake, no Ren kill). Bit 1: a basic attack, game_deny_hit_after's pick (lowest eff_hp in reach, no unkillable foe on its spawn) minus a
// Ren whose retaliation kills me; a foe in its basic reach of an altar our lock holds first. No movement or stance change.
// v915 PIR: pir3r+ats32ah on v914
#define PIR_BITS 3
inline constexpr int PIR_TAB[2] = { 0x50495231, PIR_BITS }; // slot 0 magic keeps it out of .bss
// ATS (b2445, spec_ats_1113 Aggression + Planner; owner "Other teams tend to attack stronger teams sooner"). Runtime data flag
// ATS_TAB[1], read first; 0 = v910. Bit 1: the base stance's outnumbered first-sight FLEE gives CALM while my HP >= ATS_HP_X100%,
// no foe has me in reach and my bag is under BAG_MIN. Bit 4 (enemy Prism) / bit 1024 (enemy Vesper with shards <= mine): before the
// stronger branch, FIGHT when the focus is that carry, ratio_fc >= EVEN_RATIO and a squad mate covers the focus. Gate arms, each
// only while ratio_fc >= ATS_LIFT_X100/100 and a visible foe is within ATS_LIFT_R (ats_lift): bit 32 no stake rise of the engage
// bar; bit 64 ENGAGE_SIGHT_R + 2; bit 128 no squad-mate cover requirement; bit 256 fight_stay_on_camp does not keep the farm task;
// bit 512 no hysteresis turn-back of a FIGHT. Bit 2048 (approach a committed foe): before the stronger branch, FIGHT when the focus
// is committed (tributing, capturing a cleared group I can see whole, or in an awake attacking camp's reach), within ENGAGE_SIGHT_R + 4,
// ratio_fc >= EVEN_RATIO and a mate stands within 6 of me; not v a tributing focus while my bag >= BAG_MIN.
#define ATS_BITS 32
#define ATS_HP_X100 70 // slot 2
#define ATS_LIFT_X100 125 // slot 3
#define ATS_LIFT_R 8 // slot 4
#define ATS_SIGHT_ADD 2 // slot 5: bit 64's sight radius add
#define ATS_SIGHT_MATE 0 // slot 6: 1 = bit 64 also needs a mate within 6 of me
#define ATS_CMT_ADD 4 // slot 7: bit 2048's sight radius add
// v915 ATS: pir3r+ats32ah on v914
#define ATS_CMT_KIND 0 // slot 8: bit 2048 on 0 any focus, 1 a carry focus only (Prism / Vesper), 2 a non-carry focus only
inline constexpr int ATS_TAB[9] = { 0x41545331, ATS_BITS, ATS_HP_X100, ATS_LIFT_X100, ATS_LIFT_R, ATS_SIGHT_ADD, ATS_SIGHT_MATE, ATS_CMT_ADD, ATS_CMT_KIND }; // slot 0 magic keeps it out of .bss
// b2390 FBO (Aggression spec_ats2_1113 package B; owner "attack stronger sooner"): FARM BREAK at fight_stay_on_camp (the farm step kept
// over a fight we win: 12.5 FIGHT turns/g at ratio_fc >= 1.25 with a foe within 8). Runtime data flag FBO_TAB[1], read first; 0 = v910.
// fight_stay_on_camp returns false (the fight goes on) when: bit 1 (B1): ratio_fc >= FBO_R1/100, the focus within my range + 2, my own
// camp is not within two of my hits of dead, I am not channelling; bit 2 (B2): ratio_fc >= FBO_R2/100 and the focus is committed
// (channelling, or in the reach of an awake attacking camp: a monster hits it); bit 4 (B3): B1's test, only with a mate within 6 of me
// already in reach + 1 of that focus. Arms fbk1 / fbk2 / fbk4.
#define FBO_BITS 1
#define FBO_R1 150
#define FBO_R2 125
inline const volatile int FBO_TAB[4] = { 0x46424F31, FBO_BITS, FBO_R1, FBO_R2 }; // slot 0 magic keeps it out of .bss
#define FBO_ON(b) ((FBO_TAB[1] & (b)) != 0)
