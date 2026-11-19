// Threat model, engage/retreat decisions, focus targets and ability use (generic, from kit metadata), and the
// survival memory behind safe recalls (damage taken, cancelled recalls, recent enemy sightings).
#pragma once
#include "common.h"
#include "world.h"






// Runtime flag, 0 = off. Bit 1: on an attacker-free group the cc fallback onto the focus yields to the area spell when the area
// removes more HP (camp_abilities).
#include "champ_ci.h" // Cassi & Issac layer.

namespace nova::combat {

enum Stance
{
	CALM,
	FIGHT,
	FLEE,
};

// A visible (or just seen) enemy as a threat to me.
struct Foe
{
	int idx = -1;      // index into W.enemies (-1: remembered, not visible now)
	vec2 pos{};
	float ehp = 0;     // health + shield
	float dps = 0;     // sustained damage per turn, scaled by its kit's fight value
	float burst = 0;   // damage it can deal on its next turn once in reach
	int reach = 2;     // it can damage a tile at this distance or closer on its next turn
	bool melee = true;
	bool remembered = false;
	int gems = 0;
	float dps_fc = 0; // dps with the live-duel refit of its kit (the initiation decisions use it)
};

struct Assessment
{
	Stance stance = CALM;
	int focus = -1;            // index into W.enemies
	float ratio = 99.0f;       // our local fight power / theirs (Lanchester, kit-weighted), foes within 8
	float ratio_near = 99.0f;  // the same against the foes that can join within two turns
	float ratio_fc = 99.0f;    // ratio with the refit foe kits and unseen reinforcements (initiation decisions)
	int nearest = BIG;         // distance to the nearest visible enemy
	int n_foes = 0, n_friends = 1;
	bool in_reach = false;     // some foe can damage me next turn if I stay
	bool caught = false;       // some melee foe can damage me next turn even if I step away
	float incoming = 0;        // champion damage expected next turn if I stay
	std::vector<Foe> foes;
	std::vector<vec2> threats; // positions of foes within 6
	vec2 converge{ -1, -1 };    // an ally in contact to join instead of fleeing (-1: none)
};

// Per-turn survival memory (call once per turn after perceive, also while dead).
void observe();
Assessment assess();
extern vec2 hd_lock_pos;
// Remember this turn's stance and focus (the fallback of a later bailed turn uses them).
void act_first_note_assessment(const Assessment& a);
// The cheap action of a bailed fight turn: hit the champion in range with the lowest eff HP (the recent focus first), then a step
// away (FLEE, low HP, or no hit outside FIGHT / CALM) or toward the recent focus, else the nearest foe (a recent FIGHT with no hit).
// attack_only: no step.
void act_first_fallback(bool attack_only);
// background step (spare fuel, once): the walk field from the enemy spawn behind the zone of a tile.
void fc_background(long reserve);
// Fight the focus target this turn. True if something was done.
bool fight(const Assessment& a);
// Retreat from threats toward safety (committed for a few turns). True if moved or acted.
bool flee(const Assessment& a);
inline std::vector<std::pair<vec2, int>> flz_z; // FLZ: this turn's flee foe zones that don't contain me
inline int flz_r = -1;                           // FLZ: the round flz_z was set
bool lethal_burst_flee_turn(const Assessment& a); // the lethal flee's escape step (brain, before hold_capture)
bool escape_dash_turn(const Assessment& a);
bool retreat_to_spawn_to_heal(const Assessment& a);
void lethal_burst_zones(const Assessment& a, std::vector<std::pair<vec2, int>>& out);
float ren_ret_on(const Body& e); // Ren's retaliation per instance (the retaliation value times his outgoing factor)
bool ren_kills_me(const Body& e); // that retaliation takes my effective HP
int foe_next_turn_reach(const Body& e, bool no_dash = false); // foe_of's next-turn reach only
// Keep retreating after the threats left vision (hysteresis against flip-flopping). True if acted.
bool continue_retreat(const Assessment& a);
extern int pra_raw, pra_last, pra_msg_turn, pra_walk_r;
extern vec2 pra_walk_to;
extern std::array<int, 6> pra_n;


namespace memory { extern int dmg_round; }
bool took_damage(int rounds);            // my health+shield dropped within the last `rounds` rounds (1 = this round)
bool hit_explained_by_camp();                       // no loss since my last turn, or camps reach me and explain it (call only with the bit set)
extern int sf_latched; // the round apply_flee_latch_and_history last latched a raw FLEE to CALM
void apply_flee_latch_and_history(Assessment& a);            // stance history and the soft-flee latch, right after assess
bool lw_bad(vec2 L, int rad, int skip_g); // a landing of radius rad at L wakes a sleeping attacker group
// Index in W.enemies of a visible enemy that could have hit me (hit within 2 rounds, within its range + 1) and
// that I can hit this turn (melee: a step then a hit); -1 if none. Lowest effective health first.
int react_attacker();
// An idle turn while being hit: hit back if I can, else one step toward allies (or home). True if acted.
bool react_guard(const Assessment& a);
// Where a retreat goes: the nearest ally 2-12 tiles away (not channelling, above 30% health), else home.
vec2 react_rally();
bool recall_bush_threat(); // a foe last seen 1-2 rounds ago next to a bush, within its reach + 1 of me
bool recall_doomed(const Assessment& a); // channelling a recall that damage will cancel before it completes
void bush_hold_turn(); // after the turn branch of a refused step that revealed a foe
vec2 bush_chase_target(const Assessment& a); // the bush tile to probe for a chased low foe that vanished; {-1,-1} none
void bush_chase_note_focus(int h);                 // this turn's fight focus (engine handle)
bool bush_chase_active();                     // false on a bushless map (nothing to do)
void hpr_note(std::uint32_t h, vec2 p); // HPR bit 1: a champion handle (0 none) or area point ({-1,-1} none) my action hit this turn
bool hpr_pending(); // HPR bit 1: something noted this round
void hpr_refresh(); // HPR bit 1: turn end, re-read the noted foes and lower their sighting's HP
vec2 vanished_foe_last_tile(); // last tile of a foe that just vanished next to an unlit bush; {-1,-1} none
bool hidden_fire();                      // damage with no visible source: stepped out of the reach of hidden camps
bool visible_foes_lethal_next_turn(); // visible foes' next-turn sum >= my HP + shield
bool phy_lethal_at(int v); // PHY: the same test with my next-round rank taken at value v

// Low-level actions (self only). They return false instead of throwing and keep W flags up to date.
bool attack_champion(const Body& b);
bool attack_camp(int ci);
bool cast_on_champion(int slot, const Body& b);
bool cast_on_camp(int slot, int ci);
bool cast_at(int slot, vec2 p);
bool cast_self(int slot);
namespace burst {  } // my next-round value is decided (brain set_dynamic_turn_priority)
bool ready(int slot);
// The kit has this slot and it can cast now.
__attribute__((always_inline)) inline bool slot_up(int slot) { return slot >= 0 && ready(slot); }
bool dash_legal_between(vec2 a, vec2 t); // the engine's dash path from a to t
bool camp_hit_plain(int ci); // one basic hit on a camp, no landing or reset
// A basic attack left unused next to camps that hit anyway. Runtime data flag (0 = off). Bit 1: a melee body with no foe seen hits
// an awake camp before a step that leaves every camp's reach (mv::try_move: prestep_hit_before_move; melee walk + hit is legal,
// GameRules.md:100). Bit 8: hit_claimed_camp_in_range takes any awake camp (no claim; a splash kit when no sleeping neighbour). Bit
// 2: a ranged body with no foe seen, target respawning with time to spare (respawn_at - now - walk within range >= 1), a mate's
// awake camp in range and no awake attacker aiming at me, hits instead of walking.
void prestep_hit_before_move(vec2 dest);
bool prestep_hit_camp(int ci);
bool mfb_free_attack();
bool prestep_splash_ok(int ci);
bool prestep_hit_wakes_group(int ci);

// Opportunistic ability use while farming a camp group (stuns on the strongest awake attacker, area hits, heals,
// shields, resets). `focus_ci` is the camp being attacked.
void camp_abilities(int focus_ci, bool tanking);
void heart_dash_arm(bool on);  // brain, after assess: the hook runs this turn only when on (stance is not FLEE)
void hd_hold(bool h);  // brain, true around the retreat / low-HP branches
bool heart_dash_try(vec2 keep); // the landing dash (keep: a tile that must stay in basic-attack range, x < 0 none); true if cast
bool heart_dash_end();          // a calm turn's end: the dash with no target to keep, then the basic attack it allows
// PASSIVE Stellar / Cassi: my kit is one of PO_CASTER_MASK's casters.
bool is_caster_champion();
// PASSIVE Stellar / Cassi: on a turn I neither walked nor cast, a ready walk-excluding damage spell goes on
// an awake attacker an ally holds (area if it covers 2+ of its group). No enemy within 6. True if cast.
bool assist_cast();
// PASSIVE Cassi & Issac: the ally slot of my linked body (Cassi <-> Issac), or -1.
int linked_slot();
// my linked partner's slot while it lives (-1 otherwise); the link state this round; Cassi's adopted group
// (Issac's claim while linked, -1 none); Cassi's calm step to within CI_GAP / CI_BEHIND of Issac (true if moved).
int cassi_issac_partner_slot();
bool cassi_issac_link_on();
int cassi_adopt_issac_group();
bool cassi_issac_link_step(const Assessment& a);
__attribute__((always_inline)) bool cassi_issac_pair_holds(); // safe-pair rule in a contested hold
bool kite_shot_after_move(); // a ranged body that walked: reset + shot at an enemy champion in range (true if it shot)
bool spell_poke(const Assessment& a); // true if a spell was cast
bool cast_damage_spell_on_foe(int gi = -1); // a ready damage spell on a foe in range, or with gi >= 0 only on a foe standing on group gi; a cast does not stop a capture; true if cast
// PASSIVE Cassi & Issac: the gems my death would cost: my bag plus my linked body's (read from the host).
int linked_bag();
// PASSIVE Stellar / Cassi: a walk-excluding damage spell of mine is ready and reaches camp ci (or a
// living camp of its group, for the area) from where I stand.
bool caster_spell_reaches(int ci);
bool cast_uptime_walk_in_free();
bool camp_spell_hold_without_prism(); // camp_abilities' spell hold keeps a (non-Prism) cc stun off camps this turn
int nearest_foe_distance_seen(int max_age); // usable outside carry mode too
// Heal the visible ally that needs it most (Willow). True if cast.
// Healer support: walk toward a hurt ally that is in a fight (enemy or awake camp near it) to get it in heal range.
// True if moved.
bool support_move(const Assessment& a);
bool try_heal();
// Basic attack (plus attack reset and second attack) on a camp in range. True if attacked.
bool hit_camp(int ci);
bool spawn_siege_is_safe(vec2 t, int wake_group); // worst damage on tile t before my next turn end stays under SS_SAFE_PCT of max HP

// Rough damage per round of a visible body.
float body_dps(const Body& b);

// ---------------------------------------------------------------- fights (team fights, focus, channels, locks)
// Expected healing our supports put into a fight around `at` over the next `horizon` turns: Willow's heal (heal_mod x
// Focus, 360 at base) on an ally within heal_range, every 8 turns. This is the one place a support's healing enters
// the fight evaluation (the support micro may refine it, e.g. with its partner and heal timing).
float support_heal_pool(vec2 at, int horizon);
// The same for the visible enemy supports near `at` (their heals lengthen the fight for them).
float enemy_heal_pool(vec2 at, int horizon);
// A support (healer) of ours is alive and close to `at`: the team takes more fights there.
bool team_fight_mode(vec2 at);
// Team focus: the visible enemy our bodies around it kill soonest (time to kill by the summed damage of the allies
// that reach it), with the kill bounty (100 gold + bag), channels and peel. Same answer for allies that see the same
// fight. Index into W.enemies, or -1.
int team_focus(int max_dist);
// A visible enemy channelling a recall (any damage cancels it) or a tribute (a stun cancels it; it cannot answer)
// that I can hit or stun this turn. Index into W.enemies, or -1.
int channel_target();
// An enemy threatening one of our channelling allies (tribute or recall) near me. Index into W.enemies, or -1.
int channel_threat();
// Altar locks (10 gold, carry one): buy one on spawn or while dead with spare gold. Placing one cancels every tribute
// channel at that altar (both teams), so it goes on an altar where an enemy tributes and no ally does. Free action.
void buy_altar_lock();
bool egl_foe_bag_ends_game(); // v757 MBB bit 8 EGL: a known foe bag ends the game
bool deny_tribute();
bool end_stun();
bool linked_pair_cast(int site);
int alh_locks(); // locks I carry
bool game_deny(const Assessment& a); // walk in and lock / stun / kill a game-ending channel; true if acted
// FB5 TRG1: a foe in sight is tributing (deny_tribute, end_stun and game_deny's pick act only on one).
inline bool foe_tributing()
{
	for (const auto& e : W.enemies)
		if (e.state & ST_TRIBUTE)
			return true;
	return false;
}
bool game_deny_memory_live(); // FB5 TRG1: game_deny's no-pick paths (follow the channel, deny memory) can act
// Fight-prone map from its features (short spawn-to-spawn walk, gems in contested central groups): the team moves
// as a pack there. Computed once.
bool fight_map();
// Balance of a fight: ratio > 1: we are stronger; ratio >= ~1.3 is a fight worth taking.
struct Balance
{
	float ratio = 99.0f;
	float ours = 0, theirs = 0; // side strengths
	int n_ours = 0, n_theirs = 0;
};
// Protect our own tribute: place our altar lock on the altar before tributing a big bag at a shared altar or with
// enemies about (an enemy lock would cancel the channel; ours blocks theirs). Free action. True if placed.
bool protect_tribute(vec2 altar, int gems);
// what killing enemy e is worth in gems beyond the bounty: its bag, twice for a Prism.
float hunt_prize(const Body& e);
bool rf2_stun_reach(const Body& e, int d); // a ready stun of e reaches distance d this turn
// Per-turn carrier tracks (tribute channel start and bag, last positions); call once per turn after perceive.
void hunt_observe();
// Pack cohesion on fight maps: multiplier (>= 1) on the farming rate of group gi for me, from how many of the team's
// other bodies are (or are heading) near it, so allies farm next to each other and fights find us together.
float group_pack_factor(int gi);

int nearest_foe_distance_seen(int max_age); // nearest remembered enemy (combat memory, <= max_age rounds old; distance - age)
bool self_shield_after_hit_turn(); // cast Varg's ready self-shield when a champion hit him; true if cast
float channel_damage_threat(int max_age, int r, int ticks); // summed burst + dps x ticks of the foes remembered within r (distance - age)
// Runtime data flags (the tribute-bank flag and CRX_TAB[1]), 0 = off. Bank: damage never stops a tribute; a stun, death or a lock
// does (GameRules:224). Bit 1: bank_first's 'any foe can HIT before walk + channel' veto becomes an interrupt test (channel_safe).
// Bit 2: bank_first also takes 1-9 gem bags when the walk is <= 1 (a 1-tick channel). Bit 4: prism::tribute_start_allowed uses
// channel_safe instead of 'a known foe within TG_R' for non-Prism carriers (Prism keeps her owner rules and channel_start_ok). CRX:
// a crystal channel survives damage (GameRules.md:273; only an enemy stun or death stops it, and a recall does not survive damage).
// In flee(): a hurt non-Prism body below CRX_HP % with a foe within 3 and a crystal, when channel_safe(0, 4 turns) passes (no stun
// lands in time; burst + 3 x dps + camp damage < 90% of HP + shield), reserves a free tile within 3 that the nearest foes must walk
// >= CRX_WALK tiles farther to reach (a foe with a dash ready in time crosses holes). Bit 1: only when no single step leaves every
// reach (before dash_away). Bit 2: before that step too. crystal_escape_turn reads no fields until the cheap tests pass.
#define CRX_BITS 2
#define CRX_HP 60
#define CRX_WALK 4
inline constexpr int CRX_TAB[4] = { 0x43525831, CRX_BITS, CRX_HP, CRX_WALK }; // crystal escape
#define HFC_BITS 1 // unexplained hits with no visible foe or camp: step out of reach of the unlit bushes near me; bit 1 on the 2nd hit within 2 r, bit 2 on the first; 0 = off
#define HFC_R 5 // bush scan radius
#define HFC_REACH 5 // a hidden champion's reach (range 3 + dash 2)
inline constexpr int HFC_TAB[5] = { 0x48464331, HFC_BITS, HFC_R, HFC_REACH, 0x31434648 };
int foe_channel_act_delay(const Body& e); // rounds a channelling foe cannot act (teleport ticks left; recall/tribute 0)
// Runtime data flag WBR_TAB[1], 0 = off. With it the foe's first hit turn is foe_first_hit_turn (its real options and cooldowns).
// Without it channel_survives_known_foes gives every foe a one-turn reach of at least 4 ('a spell') and ignores its cooldowns, so a
// melee foe with its dash spent at d5 vetoes a safe finish bank. Bit 1: bank_first's finish-mode call only. Bit 2: the other
// channel_survives_known_foes callers (winning_bag_altar_walk_turn and two other hold checks).
#define WBR_BITS 1
inline constexpr int WBR_TAB[2] = { 0x57425231, WBR_BITS }; // exact timers via rs:: helpers
constexpr int WBR_BIT_FINF = 1;
constexpr int WBR_BIT_ALL = 2;
#define WBR_ON(b) ((::nova::combat::WBR_TAB[1] & (b)) != 0)
// The earliest of foe e's turns (1 = its next) on which it can damage a body `dist` Chebyshev tiles away, walking a tile a turn
// until an option is ready: per option max(ready turn, 1 + max(0, dist - reach)). Reaches as foe_next_turn_reach (basic: melee 2, ranged range;
// reset ranged +1; dash melee 4, ranged range + 2; spells range + radius, +1 walking-compatible). Ready turn max(1, cd) (one turn
// early, a margin; unknown cd = now). Unknown kit: max(4, range). Caller reads the flag.
int foe_first_hit_turn(const Body& e, int dist);
#define BUS_PCT 90 // the known damage over walk + channel must stay below this % of HP + shield
bool channel_safe(int walk, int ticks, float camp_dmg, bool crystal = false); // crystal: a crystal channel
bool rgf_crystal_at(vec2 p);                       // RGF: a pending crystal landing on p (INT:125)
bool rgf_foe_lock_in_time(int ticks);              // RGF bit 8: a visible foe carrying a lock can reach the altar during a channel of ticks turns (GR:226; INT:114)
inline bool rgf_alive(std::uint32_t h)             // RGF bit 32: the engine's answer after the first hit (INT:41, 67); a failed read keeps the reset as before
{
	std::int32_t al = 1;
	return cambc::detail::sdk_champion_is_alive(h, &al) != 0 || al != 0;
}
float foe_damage_over_ticks(int max_age, int ticks); // damage every known foe can land over a channel of ticks, after walking in
float foe_damage_over_ticks_deliver(int max_age, int ticks); // v629 WDV: a foe I see is charged the hits it can land in its two turns

} // namespace nova::combat

namespace nova::combat::deny_hold
{
bool hld_hold_lethal(int t, decltype(Body::h) tgt_h, bool ending); // v683 HLD bits 1/2 (called with the flag read first)
} // namespace nova::combat::deny_hold

namespace nova::combat { struct Assessment; }
namespace nova::combat::deny_memory
{
// an ending channel by t at altar alt, running until round 'until': remember its body and bag
void note(const Body& t, vec2 alt, int until);
// no channel picked this turn: walk back to / hold at a remembered ending bag's altar. True = the turn's move is taken.
bool act(const nova::combat::Assessment& a);
} // namespace nova::combat::deny_memory

namespace nova
{
struct Body;
}
namespace nova::combat::retreating_mates
{
bool retreating(const Body& al); // the mate's posted stance is retreat
// Fuel: camp_hit_strength_on_body(ally, true) is answered once per (perceive stamp + my tile, the ally's id and tile, my tie priority) in a turn:
// assess runs up to 3 times a turn and asks for every ally each time.
bool retreat_value_cache_get(int st, const Body& b, int tp, float& v);
void retreat_value_cache_put(int st, const Body& b, int tp, float v);
} // namespace nova::combat::retreating_mates

namespace nova::feat::gdb
{
} // namespace nova::feat::gdb
