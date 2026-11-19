#pragma once
// fuel_meters.h: Fuel meters and guards: what a turn may still afford, spin and bail helpers.
#include "common_flags.h"
namespace nova {
namespace fg {
struct Cost
{
	long hi = 0; // decayed maximum of the measured cost
};
// Fuel used since (f0, r0): a turn the engine suspended in between resumed on a fresh budget.
inline long fuel_used_since(long f0, int r0)
{
	const long f = FXR_FUEL();
	return static_cast<int>(round_number_nc()) != r0 ? f0 + (100000 - f) : f0 - f;
}
inline void note(Cost& c, long used) { c.hi = std::max(used, c.hi - (c.hi >> 3)); }
inline int rnd() { return static_cast<int>(round_number_nc()); }
inline int pstamp = 0; // perceive() calls so far: per-turn caches of W-derived results key on it
} // namespace fg
// Same play with unlimited fuel. The groups a call touches come from the (2r+1)^2 tiles (M.camp_index / W.camp_slot), each group's
// sum is kept per me_after and perceive, a view of FFG_NWM_CAMPS+ camps skips the first call's direct scan (~12k), fight's area pick
// asks about f.pos once. This matters beside a sleeping ring of dozens of camps, where wakes_other_group_cached otherwise cost 30-80k a turn.
#define FFG_NWM_CAMPS 24
// Fewer fuel-cut turns on big maps. Flag read first; 0 = no work. Bit 1 GBSEL: the bounds list is ordered by (bound desc, group
// index asc) through 64-bit keys; best_group pops it lazily from a heap (a choice usually rates a few candidates), the other callers
// get the whole list. Same list except the order of exact ties. Bit 2 GBBUD: target-choice budget: the bounds loop checks fuel every
// 8 groups and, below TCF_GBFLOOR, keeps its place and resumes from it on the next turn on the same tile (travel kept), instead of
// running the turn out of fuel. Bit 4 EP9W: the escape-path search stops on a work count, pops x (TCF_EP9K + camps in the window) >
// TCF_EP9W, instead of 35k fuel used. Bit 8 DASHW: compute_travel's dash-only routes stop on a count of route lookups instead of 8k
// of fuel used.
#define TCF_BITS 14
#define TCF_GBFLOOR 30000
#define TCF_EP9W 1800
#define TCF_EP9K 117 // Work per pop = TCF_EP9K + camps in the window.
#define TCF_DASHN 12
inline constexpr int TCF_TAB[6] = { 0x54434631, TCF_BITS, TCF_GBFLOOR, TCF_EP9W, TCF_DASHN, TCF_EP9K }; // Resumable target-choice bounds under 30k fuel.
// The opening simulation's bounds pass (the opening choice) cannot resume on its own, and the defer check forces it after 3
// deferrals whatever it costs, so on many-group maps every body could run out of fuel at r8-9. Bit 1: the pass keeps its place when
// finishing could cut the turn (fuel < OPR_TAIL + OPR_PG x groups left, checked every 8 groups) and resumes next turn, keyed on the
// simulated slot; the sort waits below OPR_TAIL + OPR_SRT x groups when this turn ran the loop. Small maps never reach the stop: the
// opening's own gate needs 46k. Runtime data flag, read first; 0 = the plain pass.
#define OPR_BITS 1
#define OPR_TAIL 12000
#define OPR_PG 900
#define OPR_SRT 300
inline constexpr int OPR_TAB[5] = { 0x4F505231, OPR_BITS, OPR_TAIL, OPR_PG, OPR_SRT };
// TCF bit 2's bounds loop resumes only on the turn after it stopped (bounds_resume_ready: travel_round == gbr_round), so a list that needs 3+
// turns (100+ one-camp groups at ~1.4k each: stop at 24, resume to 96, then the third turn restarts from 0) would never complete and
// the body would never get a target. Bit 1: a resumed stop keeps the travel stamp of the first stop, so the chain goes on while the
// body stays on that tile and the travel is at most GBR_AGE rounds old. Runtime data flag GBR_TAB[1], read first; 0 = plain resume.
// At unlimited fuel the loop never stops: inert.
#define GBR_BITS 1
#define GBR_AGE 6
inline constexpr int GBR_TAB[3] = { 0x47425231, GBR_BITS, GBR_AGE }; // Resumable target-choice bounds.
// Emblem shop order. Flag read first; 0 = no work. shop(): the unstarted 'rankable' entries among the next a set number of
// incomplete build items (Monster, Jungle, Durability, Collectors, Bruiser, Power; Treasure with bit 4; Skirmish with bit 8) are
// re-ordered by value in main-shard units (Power's 6th shard = 1.0); every other entry (Prospector, Capture, Tribute, Hunter, Home,
// Greed, a part-bought emblem) keeps its slot. Prism carrier and healers untouched. Sg = main stat / growth; fc = champion share of
// my fighting, c = camp share of HP I lose. Monster .15(1-fc)Sg, Jungle .3c/(1-.3c)Sg, Durability .111Sg, Collectors .01(F+1)Sg only
// with F >= a set number of families owned, Skirmish .05 fc Sg, Bruiser a set weight, Power a set weight, Treasure .5 x a set factor
// x .0909 x gold rate x race rounds left / 30 (gold is spent as it comes: half its rounds); + .01Sg for a new family when Collectors
// is owned; + a per-family codebook bias. bit 1 RANK: measured rates (fight turns: foe within 4; HP lost with/without a foe within
// 5) blended n/(n+a set prior weight) with a pan-kit neutral prior (fc .177, c .505). bit 2 PRIOR: the prior is per kit and per map:
// fc = a_k + .0088 FIGHT, c = b_k - .0148 FIGHT, gold rate prior a set base x exp(.5(GOLDGEM-1.25)) (x1.33 Vesper). bit 4 Treasure
// ranked too. bit 8 Skirmish may replace the weakest stat-only entry in the window. bit 64 CODEBOOK: no rates; rankable entries
// ordered by the per-family biases alone (all 0 = the plain order).
#define EMB_BITS 15
#define EMB_PRN 120
#define EMB_KT 53
#define EMB_BRU 150
#define EMB_POW 100
#define EMB_COLLN 4
#define EMB_WIN 8
#define EMB_R0 0
#define EMB_G0 110
#define EMB_PMON 0
#define EMB_PPOW 0
#define EMB_PDUR 0
#define EMB_PTRE 0
#define EMB_PJUN 0
#define EMB_PHOM 0
#define EMB_PBRU 0
#define EMB_PTRI 0
#define EMB_PCAP 0
#define EMB_PPRO 0
#define EMB_PHUN 0
#define EMB_PSKI 0
#define EMB_PGRE 0
#define EMB_PCOL 0
inline constexpr int EMB_TAB[24] = { 0x454D4231, EMB_BITS, EMB_PRN, EMB_KT, EMB_BRU, EMB_POW, EMB_COLLN, EMB_WIN, EMB_R0, EMB_G0,
	EMB_PMON, EMB_PPOW, EMB_PDUR, EMB_PTRE, EMB_PJUN, EMB_PHOM, EMB_PBRU, EMB_PTRI, EMB_PCAP, EMB_PPRO, EMB_PHUN, EMB_PSKI, EMB_PGRE, EMB_PCOL };
// Skirmish passive value in emblem_rank, percent champion damage (3.0.0 value: 10).
#define SKV 10
inline constexpr int SKV_TAB[2] = { 0x534B5631, SKV };
// fight()'s hold (a hold that ends the turn: no hit after a step, safe here, every closer tile dangerous) has no end: two bodies
// that both hold (for example both Prisms, 6 apart, full HP) wait for each other forever. FSH counts consecutive held turns against
// the same focus; past FSH_N of them: bit 1 RELEASE: the turn falls through (fight() returns false: the farm step and the rest of
// the turn run as with no fight); bit 2 ENGAGE: the walk-in step is taken (hold off). Runtime data flag FSH_TAB[1], read first; 0 =
// off.
#define FSH_BITS 2
#define FSH_N 8
inline constexpr int FSH_TAB[3] = { 0x46534831, FSH_BITS, FSH_N }; // fight-hold standoff limit.

// Carrier survival (CRV) and the general in-reach flee test (IRB_BITS), both runtime data flags (0 = no work; the flag is read
// first). CRV bit 1: a carrier (carrying many gems, not a linked C&I body: the owner rule CI_SAFE keeps the pair) inside a foe's
// reach, not channelling and with no kill this turn, takes FLEE at the end of assess() when the visible foes' summed burst reaches a
// set percent of its eff HP: over the next foe turn, or over TWO foe turns when any of them has a ready stun that reaches it (cc,
// aoe stun, landing stun, enhanced-attack reset) and it is not stun-immune. One cast per foe turn (lethal_burst_hit's best option;
// turn 2 without turn 1's slot). IRB bit 1: any body in a foe's reach (not channelling, no kill this turn, not a linked C&I body)
// that is not fleeing takes FLEE at the end of assess() when the visible foes' summed burst over its escape window (CRV's model)
// reaches IRB_PCT % of eff_hp (hp + shield). It generalises CRV to every body. Bit 2: a caught FLEE body (bit 1's or the caught
// branch's) whose burst test fails takes the tile it reaches this turn (walk, or a dash within 2) that the fewest visible foes
// reach, when that is fewer than here (then walk, lower foe damage there, toward the nearest healthy mate / home); the tile must
// pass LETHAL_BURST (lethal_burst_damage_sum < lb_cap()). lethal_burst_flee_turn takes it. Bit 4: in the test a stunned foe whose
// next turn is the stunned one (reach_burst_turns: <= 1 turn before my next) adds nothing to the one-turn sum and one turn's burst
// to the two-turn sum. Bit 8: fuel guard: no test (and no flip) when less than IRB_FUEL fuel is left at assess. Bit 16 (double
// turn): the test also sums, for each foe with two turns before my next turn (reach_burst_turns, foe_turn_counts_fill's rule, once
// per turn), its two-turn burst (foe_two_turn_damage: turn 2 with cooldowns one turn on), including a foe whose one-turn hit is 0
// (it walks a tile, then hits). Fire tag irb_ed. Bit 16 without bit 1 (e.g. IRB_BITS=28): a non-fleeing body flips only on a
// double-turn fire (irb_ed), not on bit 1's own. Bit 32: dropped (the third-turn sum over-counted). Bit 64: bit 4's stunned-foe test
// only: a foe still to act gets its standing-order count (1 + it acts before me next round by its current next-round ordering value)
// unless its priority changed on >= .3 of its danger rounds (stunned or < 45% HP; prior .44 over 4 rounds). The walk guard,
// double-turn test and DTO keep the worst case.
#define IRB_BITS 29
#define IRB_PCT 100
#define IRB_FUEL 60000
inline constexpr int IRB_TAB[5] = { 0x49524231, IRB_BITS, IRB_PCT, IRB_FUEL, 0x31425249 }; // magic, bits, pct, fuel, end magic
namespace ffg {
inline fg::Cost cost[3]; // 0 FLEE branch, 1 FIGHT branch, 2 econ target_turn tank/support turn.
// Notes the branch's cost when its scope ends (early returns included). slot -1: off (flag read first).
struct Meter
{
	int slot;
	long f0;
	int r0;
	explicit Meter(int s) : slot(s), f0(s >= 0 ? fuel() : 0), r0(s >= 0 ? fg::rnd() : -1) {}
	~Meter()
	{
		if (slot >= 0)
			fg::note(cost[slot], fg::fuel_used_since(f0, r0));
	}
	Meter(const Meter&) = delete;
	Meter& operator=(const Meter&) = delete;
};
} // namespace ffg
namespace fsp {
inline fg::Cost retry; // Bit 1: farm_turn's second target_turn.
// Notes the scope's fuel into c when it ends (early returns included).
struct Meter
{
	fg::Cost& c;
	long f0;
	int r0;
	explicit Meter(fg::Cost& cc) : c(cc), f0(fuel()), r0(fg::rnd()) {}
	~Meter() { fg::note(c, fg::fuel_used_since(f0, r0)); }
	Meter(const Meter&) = delete;
	Meter& operator=(const Meter&) = delete;
};
} // namespace fsp
#define SF_OF_FLOOR 50000
#define SF_OF_PER 400
#define NCK_GEMS 100
#define NCK_LEFT_PCT 15
#define NCK_ROUNDS 25
#define SS_PREV_R 2
#define SR_MIN 3
#define SPS_FUEL 4000
inline bool sps_pending = false; // My spin from last turn still runs and no action has cancelled it yet.
void cancel_pending_spin(); // Cancel the pending spin now.
// Call right before any SDK action (move, attack, cast, ward, shop, consumable, tribute, lock).
NOVA_INLINE void cancel_spin_before_action()
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	if (sps_pending)
		cancel_pending_spin();
}
// Vesper dash-then-hit (champ_tavi.h): a ranged body with a dash (Vesper) farming with no foe threat dashes onto an attack tile and
// hits the same turn (a dash is a cast, not a walk, so the ranged attack allowance stays). The walk instead costs the attack (or the
// reset, walk + reset + hit), so the dash saves a reset (one extra hit later) or a whole turn. Bit 1 support_turn approach (attack
// tiles within the dash), 2 tank_turn approach (ranged tank, attack tiles within the dash), 4 skip when a goal tile is adjacent and
// the reset is ready (turn-saving dashes only), 8 after an in-place hit that killed the focus with no living member left in range:
// dash to a safe tile in range of the nearest living member (next turn opens with hit + reset + hit). [2] min HP %, [3] no visible
// foe within, [4] no remembered foe (age <= 8) within. 0 = off.
#define VDH_BITS 1
#define VDH_HP 50
#define VDH_FOE 10
#define VDH_MEM 8
inline constexpr int VDH_TAB[5] = { 0x56444831, VDH_BITS, VDH_HP, VDH_FOE, VDH_MEM };
// Runtime data flags, read first. DMC bit 1: build_team drops a DEAD mate's claim and busy flag (it still counts as a claimant until
// its own dead turn re-publishes -1, up to a round later; DCW bit 1 already drops dead mates from the free crew). RGF bit 1:
// filler_target skips one-camp ring gates (ring_gate_keep). rate_for rejects them and target_turn drops a cleared one uncaptured
// (fail_until +200), so a filler there would be priced at a reward it never takes. CTX_TAB[1], 0 = off. Bit 1 LKC (end-of-turn free
// attack): a foe champion in my attack range is hit before an altar lock, unless I carry >= 10 gems within 1 of that altar. Bit 2
// HCY (combat assess): the never-engage 'low' line rises to CTX_HI% when my walk home <= CTX_D0, falling linearly to 30% at CTX_D1:
// a hurt body near home heals instead of starting a fight. Bit 4 FSE (assess): the engage bar rises by up to CTX_K/100 when the
// focus foe's walk to ITS spawn is shorter than mine (it heals cheaper), full at a gap of CTX_AS tiles; initiation only. Bit 8 BSR
// (econ capture_recall): no capture-timed SHOP recall (heal and bank recalls unchanged) while the bag after the payout is >= 10
// gems, bankable, and the altar is <= CTX_BD walk from here and nearer than from home: the bag is banked first.
#define CTX_BITS 9
#define CTX_HI 59
#define CTX_D0 6
#define CTX_D1 16
#define CTX_K 40
#define CTX_AS 8
#define CTX_BD 6
inline constexpr int CTX_TAB[8] = { 0x43545831, CTX_BITS, CTX_HI, CTX_D0, CTX_D1, CTX_K, CTX_AS, CTX_BD };
// At a recall site: true = the pending spin is kept as the real recall (do not call recall()).
NOVA_INLINE bool pending_spin_becomes_recall()
{
	if (!sps_pending)
		return false;
	sps_pending = false;
	return true;
}
#define CC_GEMS 100
#define CC_D 3
#define DCH_HOLD 20
#define BC_HOLD 10
// Hidden-bush hits and ward use; runtime data flag, 0 = off. Bits 1 and 32 (the BUSH_GAP veto rules) are gone: bush_place
// (ward_bush.cc) applies the BUSH_GAP 6 Chebyshev veto always and reads no flag (v698 comment fix). bit 2: a turn that starts with champion damage and no visible source (no enemy within 4, no camp
// reach) wards the nearest unlit bush tile within reach before the assessment (then re-perceives); re-decided every turn. bit 4: a
// tribute channel the ENEMY cancelled (stun, lock, ...) is not restarted at that spot for BUSH_HIDDEN_HIT_EC_R rounds while I am hit
// (not by camps) or a known enemy is within 4, unless the new channel pays by the cancel round + BUSH_HIDDEN_HIT_EC_RACE (a stun
// cast at cancel - 1 is ready again at cancel + 7, 8-turn cooldown; re-decided each turn). The carrier wards first (bit 2's tile
// rule; a channelling body cannot, GameRules:116) and a hit carrier leaves unlit bushes' reach. bit 8: ward-only enemies within
// BUSH_HIDDEN_HIT_WNEAR of me count for the fight/flee/tribute logic (runtime WARD_NEAR). bit 16: a CALM turn (no capture paying)
// walks outside every known foe's reach (seen or ward-seen).
#define BUSH_HIDDEN_HIT_BITS 4
#define BUSH_HIDDEN_HIT_WNEAR 6 // Bit 8: ward-only enemies within this of me join W.enemies.
#define BUSH_HIDDEN_HIT_EC_R 20 // Bit 4: rounds after an enemy cancel during which that spot holds no restart.
#define BUSH_HIDDEN_HIT_EC_RACE 6 // Bit 4: a new channel paying by cancel round + this cannot be cancelled again by the same stun.
#define CWG_BITS 1
#define CWG_R100 100
inline constexpr int CWG_TAB[3] = { 0x43574731, CWG_BITS, CWG_R100 }; // CALM walks avoid a seen stronger foe's reach at CWG_R100 (percent).
inline constexpr int BUSH_HIDDEN_HIT_TAB[5] = { 0x42373831, BUSH_HIDDEN_HIT_BITS, BUSH_HIDDEN_HIT_WNEAR, BUSH_HIDDEN_HIT_EC_R, BUSH_HIDDEN_HIT_EC_RACE }; // slot 0 magic keeps it out of .bss
// Keep the ward charge for a bush. Runtime data flag, read first; 0 = off. the ward code's act(), after bush_place fails, on a map
// with bushes and with a ward of mine standing: bit 1 HOLD: keep the charge (return) when my ward stands on a bush within WKB_FAR of
// me (never swap a bush ward for an open one), or when my ward is within WKB_FAR, the charge has been ready < WKB_WAIT rounds and a
// bush lies within WKB_BR of me or of my claim target. Otherwise the coverage path runs as usual (no ward, a stale ward, a long wait
// or no bush near: the charge is used). bit 2: bush_place keeps tiles <= 8 from the enemy anchor when a contested group (contest
// .35-.65) is within 6. bit 4: the bush must lie within WKB_BR of me AND of the target. bit 8: a bush ward is released after
// WKB_WAIT too.
#define WKB_BITS 1
#define WKB_WAIT 0
#define WKB_FAR 12
#define WKB_BR 8
inline constexpr int WKB_TAB[5] = { 0x574B4231, WKB_BITS, WKB_WAIT, WKB_FAR, WKB_BR };
// Bushes. GameRules:163 a refused step reveals the tile for the round and keeps the move; :349-353 a body outside a bush cannot see
// into it, a body inside sees out; :252 a basic attack needs a visible target. Bit 1 REREAD: a refused step that reveals a foe holds
// further steps; after the turn branch the body re-reads what it sees, remembers the foe, takes the stance again and hits. Tile
// tie-breaks in fight(), no stance change: bit 2 a melee body that hits this turn stands on a bush tile with the focus still in
// range; bit 4 a ranged body's walk-in step lands on a bush tile that closes on the focus. Not with a seen foe or foe ward on a bush
// within 8 of the tile.
#define BSH_BITS 7
#define BSH_FUEL 40000
inline constexpr int BSH_TAB[3] = { 0x42534831, BSH_BITS, BSH_FUEL };
// Bush handling. Runtime data flag, 0 = off, flag read first. Bit 1: farming a camp (econ hold path) while a foe was seen within
// BSX_FOE_R in the last 8 rounds, step onto a free bush tile one step away that is one of the safe attack tiles (a melee body also
// from an in-place tile: it walks and hits in one turn). Camp hits from a bush are fewer, and the HP taken per farm turn is much
// lower in a bush than in the open. Not with a seen foe or foe ward on a bush within 8 of the tile. Bit 2: with the ward charge
// ready, a foe seen 1..BSX_AGE rounds ago within 8 that is out of sight now and stood next to an unlit bush: ward a tile of that
// bush cluster before the assessment (a ward inside a bush sees its whole cluster, GameRules:349-353), then re-perceive. A foe seen
// entering a bush tends to hit from it within 12 rounds.
#define BSX_BITS 2
#define BSX_AGE 3
#define BSX_FOE_R 10
#define BSX_FUEL 40000
inline constexpr int BSX_TAB[5] = { 0x42535831, BSX_BITS, BSX_AGE, BSX_FOE_R, BSX_FUEL };
// Bug bundle. Runtime data flag, 0 = off, flag read first. Bit 1: a stun buff counts only while its duration is > 0 (world.cc
// read_buffs; GameRules:122 buffs expire at the owner's turn start, so a served stun reads duration 0 until then and the body acts
// normally). Bit 2: dash landings (landing_from, dash_away, hd dash, VE dash, VV dash) test the engine's dash path (a middle next to
// both ends that is not a wall, a visible living camp or a visible enemy champion), not the integer middle for walls only. Bit 4:
// estimate() prices the living attackers of a chipped group at their own HP (per-camp HP from the same observation as hp_left), not
// every original attacker at the group's HP share. Bit 8: Ryth's area stun and Heart's landing stun reach an ordinary foe tribute in
// channel_target and fight() (game_deny_stun_channeler's branches), not slot_cc only. Bit 16: the BSX vanish-ward re-perceive keeps
// the turn's action flags (moved, attacked, cast, no_move), as the LNK path does. Bit 32: the BSX vanish-ward re-perceives only when
// a foe is readable now that this turn's read did not hold. Bit 64: chip_clear_share prices the living attackers at their own HP,
// from bit 4's note (either bit keeps the note).
#define BGX_BITS 1
inline constexpr int BGX_TAB[2] = { 0x42475831, BGX_BITS };
#define BGX_ON(b) ((BGX_TAB[1] & (b)) != 0 || (((b) & 2) != 0 && (::nova::mu::bits & 128) != 0)) // BGX bit 2 can also be switched on at run time through multipliers bit 128.
// A spawn sealed by a camp ring. Flag read first; 0 = no work. Bit 1: the background map analysis also resumes on a turn with
// SRB_RES + SRB_GAP fuel left (from round SRB_R0), so a turn whose own logic leaves < 50k (a target choice over unreachable groups
// every round) cannot stall M below ST_HOME forever (no f_home, so ring_breach would never run and the game ends 0-0). Bit 2:
// ring_breach skips its RING_START wait when no group outside the ring is walkable from my spawn (camps blocked).
#define SRB_BITS 3
#define SRB_RES 8000
#define SRB_GAP 14000
#define SRB_R0 20
inline constexpr int SRB_TAB[5] = { 0x53524231, SRB_BITS, SRB_RES, SRB_GAP, SRB_R0 };
#define GD_LATE 1500
#define GD_FLIP 150
#define GD_BODIES 2
#define GD_RAD 24
#define CCT_GIVE 6
#define PEF_STARVE 1
#define IR_FREE 2
inline constexpr int STARVE_CHOICE_TAB[3] = { 0x42373034, PEF_STARVE, IR_FREE }; // slot 0 magic keeps it out of .bss
#define IRF_MODE (STARVE_CHOICE_TAB[2])
#define PES_K 3
#define PES_FUEL 30000
#define PES_FLOOR 20000
#define PES_N 4
#define IRF_RMAX 2
#define CL_FOE 6
#define CS_BAG 40
#define CS_MYBAG 100
#define CS_HP_X100 40
#define FFX_ON true // the filler fix is read from slot 5 of the shared table
#define SD_TURNS 40
#define SD_FAIL 60
#define FLC_HOLD 12
#define FLC_BAG 100
#define AF_FLOOR 20000
#define AF_FLOOR_CALM 6000 // A CALM turn stays armed only with a champion in range (the fallback is that hit): bail late.
#define AF_MOVE_MIN 13000 // the fallback step only with this much left (a move costs 4-12.5k on 02the-pack)
#define AF_R 8
// Armed only on a heavy turn: my turn was suspended or bailed within AF_HEAVY_KEEP rounds, or less than AF_ARM_FUEL is left after
// econ::observe (costly perception), or AF_ARM_FOES+ enemies within AF_R with AF_ARM_CAMPS+ awake camps in sight.
#define AF_HEAVY_KEEP 3
#define AF_ARM_FUEL 65000
#define AF_ARM_FOES 3
#define AF_ARM_CAMPS 10
struct AfBail
{
};
inline bool af_armed = false; // Set once per turn after perception (alive, not channelling, an enemy within AF_R).
inline long af_floor = AF_FLOOR;
inline int af_heavy_round = -1000; // The last round whose turn bailed or was suspended.
inline int af_turn_round = -1;     // the round of this turn's perception (the free-slot suspension test)
[[noreturn]] void af_throw();
NOVA_INLINE void bail_if_fuel_low()
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	if (af_armed && fuel() < af_floor)
		af_throw();
}
#define AF_CHECK() bail_if_fuel_low()
#define AF_TICK(i) (((i) & 15) == 0 ? bail_if_fuel_low() : (void)0) // Every 16th pass of a long loop.

constexpr std::array<vec2, 8> DIRS{ vec2{ 0, 1 }, vec2{ 1, 1 }, vec2{ 1, 0 }, vec2{ 1, -1 },
	vec2{ 0, -1 }, vec2{ -1, -1 }, vec2{ -1, 0 }, vec2{ -1, 1 } };
} // namespace nova
