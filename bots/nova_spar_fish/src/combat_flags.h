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
#define DPS_BITS 0

// Ratio flag RP, 0 = off. Bit 1: the foe discount takes a continuous shape, no cliff. Bit 2: no headcount tier on the engage bar.
// Bit 4: remembered foes in the engage-bar headcount fade by age, the bar moves smoothly (float exponent). Bit 8: that count uses
// the mates' own radius, not EF_FOE_R (needs bit 4). Hunt-race flag HDL, 0 = off. Bit 1: my turns to live in the hd race = the first
// T where sum over foes of share x dps_dmg x max(0, T - lag) >= margin x my eff HP, lag = turns before the foe can reach me; it
// replaces the rate, share and contact terms of inc in hdt_won together. The in-reach share is measured x100. Stun flag STP, 0 =
// off: a pending stun (b.stunned) costs the foe's whole next turn, not 'reach - 1'. Bit 1 foe_of: reach 0. Bit 2 foe_reach: reach 0.
// Bit 4 lethal_burst_damage_sum: no hit from a stunned foe whose only turn before mine is the lost one.
#define STP_BITS 0
inline constexpr int STP_TAB[2] = { 0x53545031, STP_BITS };
#define DPS_FS_ME 80
#define DPS_FS_M1 60
#define DPS_FS_M2 55
#define DPS_FS_F1 72
#define DPS_FS_F2 65
#define DPS_FS_F3 60
#define DPS_FS_F4 53
#define DPS_FS_F5 45
#define DPS_FS_F6 34
inline constexpr int TEAM_HELP_FIX_TAB[2] = { 0x42483634, TEAM_HELP_FIX_BITS }; // a HELP post the team memory carries

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
#define DASH_MIDDLE_BITS 0
inline constexpr int DASH_MIDDLE_TAB[2] = { 0x52433431, DASH_MIDDLE_BITS }; // slot 0 magic keeps it out of .bss
constexpr int DASH_MIDDLE_BIT_DNMID = 1, DASH_MIDDLE_BIT_GDMID = 2, DASH_MIDDLE_BIT_AGMID = 4, DASH_MIDDLE_BIT_TRZOK = 8, DASH_MIDDLE_BIT_SCSTUN = 16, DASH_MIDDLE_BIT_WARDFOE = 32;
#define DASH_MIDDLE_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; in release c is not evaluated

// Runtime data flag, 0 = off. Bit 1: foe_first_hit_turn prices a spell on cooldown c as ready on the foe's turn c + 1 (a slot ticks
// at its owner's turn end; foe_ready: cd <= k on 0-based turn k; GameRules:118). Runtime data flag FLEE_FIX_TAB[1], 0 = off. Bit 1:
// assess's 'stands next to an awake camp (busy farming)' x0.6 does not read a remembered foe's frozen last tile once that tile is in
// my sight (the foe is known not to be on it). Bit 2: flee(): after an exclusive parting stun a ranged body that stays may attack
// and cast (GameRules:116), as parting_stun does. Bit 4: spawn_refuge / retreat_to_spawn_to_heal price foe damage through
// mult_foe_hit_to_real_hp against real HP (spawn_siege_is_safe); the camp part stays real. Bit 8: gd_mem.until = round + left counts
// a foe that already took this round's turn (game_deny_slow), so game_deny_follow_channel does not stop a round early.
#define FLEE_FIX_BITS 0
inline constexpr int FLEE_FIX_TAB[2] = { 0x42483736, FLEE_FIX_BITS }; // slot 0 magic keeps it out of .bss
constexpr int FLEE_FIX_BIT_FCD = 1, FLEE_FIX_BIT_XPA = 2, FLEE_FIX_BIT_SRU = 4, FLEE_FIX_BIT_GFT = 8;
constexpr std::uint32_t FLEE_FIX_ST_ACTED = 32u; // champion state bit completed_turn

// Runtime data flag PFH_TAB[1], 0 = off. Bit 1: fight()'s walk-in step. Melee walking never spends the attack (GameRules.md:100), so
// a melee body with its attack unused, whose focus is out of reach even after a step (and a ready dash), hits the lowest eff HP
// non-spawn foe in reach before the step, not from the new tile.
#define PFH_BITS 0
inline constexpr int PFH_TAB[2] = { 0x50464831, PFH_BITS }; // slot 0 magic keeps it out of .bss
#define SPELL_READY_FIX_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c (answer differs from the other path); in release c is not evaluated

#define POWER_ENGAGE 0.0f
#define POWER_LEAVE 0.6f

// The leave on POWER_LEAVE reads the raw power product, while a.ratio (with its SYM discount) can read level or ahead on the same
// turn. Runtime data flag, 0 = off. Bit 1: the leave fires only at a.ratio < EVEN_RATIO.
#define S1R_BITS 0
inline constexpr int S1R_TAB[2] = { 0x53315231, S1R_BITS }; // slot 0 magic keeps it out of .bss
constexpr int S1R_BIT_RATIO = 1;
#define FINISH_LOW_HP 0.3f
#define CAMP_FIRST_MIN 0.8f
#define PEEL_MIN (static_cast<float>(B467_PEEL_X100) / 100.0f)
#define DT2_MIN 0.7f
#define DT2_RATIO_X100 40 // ratio x100 floor
#define PEEL2 0.5f // PEEL also covers a team mate below PEEL2 HP with a visible foe in reach of it (the chase after the hit, not only the round of the hit), at fs^2 >= PEEL2_MIN es^2, when I reach that foe within 2 turns; 0 = off

#define PEEL2_MIN 0.5f
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
#define NOCHASE_R 5
#define CT_R 6
#define CT_HP_PCT 50
#define CT_MIN_X100 70
#define EF_A_X100 110
#define EF_B_X100 210
#define EF_FOE_R 12
#define LL_BAG 10
#define SBG_BITS 0 // bit 1 = while I carry >= SBG_BAG gems, no symmetric-power discount; bit 2 = no discount v a foe of >= SBG_OUT % of my eff HP
#define SBG_BAG 50
#define SBG_OUT 200
inline constexpr int SBG_TAB[4] = { 0x53424731, SBG_BITS, SBG_BAG, SBG_OUT }; // slot 0 magic keeps it out of .bss
#define HOLD_MIN_X100 60 // a FLEE within 2 rounds of fighting is held as FIGHT only at ratio x 100 >= this

#define HUNT_MIN_BAG 40 // smallest enemy bag worth a lock or a detour

// The fight model in contested ground: the foes' kit values refit on live duels, in the ENGAGE decision only (applying it
// everywhere, or in 'close in when in reach', turns contact fights into flights).
#define FIGHTCAL_FOE_SHIFT 0.0f // added to every foe kit value (slot units; 4 = x e in foe damage)
#define FIGHTCAL_A_MASK 0x1FFF // kits (bit = champion_type) whose foe value is refit; 0x8FC = kits nova never drafts

// PASSIVE Stellar / Cassi: the ranged casters whose damage spells exclude walking (a walk forfeits the spell).
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
#define NO_WAKE 1
inline constexpr int NO_WAKE_TAB[2] = { 0x4E4F574B, NO_WAKE }; // slot 0 magic keeps it out of .bss
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
// basic only with the attack allowance and the dash's damage only within its landing radius. Bit 32 OWN: kill_damage_pair_factor, the one
// pair-factor point of kill_dmg's own sums: my Skirmish / Collectors.
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

// ---- big-tribute deny constants. Deny big foe tributes by lock or stun. Flag GDB_BITS, 0 = off. Bits: 1 PICK_BIG game_deny also
// takes a non-ending channel of GDB_BAG+ with GDB_T+ turns left (after end and flip); 2 WAYS_SAFE on a big pick: bag < GDB_FREE_BAG,
// HP share >= .5, and each way's goal tile and next step burst < GDB_SAFE_PCT %; 4 LOCK_EARLY game_deny_lock_wanted buys a lock on a seen foe
// bag of GDB_BAG (not GD_LOCKBAG): an early lock when a 150+ foe bag is seen; bit 8 is reserved. Hooks: game_deny_slow (pick, ways),
// game_deny_lock_wanted (bag).
#define GDB_BITS 4
inline constexpr int GDB_TAB[2] = { 0x47444231, GDB_BITS }; // slot 0 magic keeps it out of .bss
#define GDB_BAG 150     // a big tribute: a channel started with this bag
