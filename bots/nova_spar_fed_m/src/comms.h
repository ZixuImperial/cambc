// The 8-byte team shared-memory protocol. bytes 0..5: one claim byte per body slot: bits 0-6 = target group index + 1 (0 = none),
// bit 7 = engaged (the body is fighting the group's camps or capturing it). Writers: brain publish (every body), and champ_willow.cc
// for the healer: while Willow follows her partner, her byte MIRRORS the partner's claim (same group, same engaged bit). That is the
// whole "Willow partner state": partner_slot() is computed identically on every body from the plan and allies' liveness, so it needs
// no byte of its own, and econ (claimants, crews, captures), the planner and the fights' ally-commitment weighting all skip or
// discount support_slot() where a second claimant would be wrong. Readers: econ (claims, busy), planner (stacking, camp model),
// combat (r3 commitment, peel), support. byte 6: team event subject + 1 (0 = none). Types 0-3 (ward/intel news): a camp group index,
// or (group count + altar index). Types 4-7 (HELP, owned by the backup module): its own location code. byte 7: team event: bits 5-7
// = type, bits 0-4 = round stamp (round & 31). 0 EV_ENEMY, 1 EV_ENEMIES, 2 EV_TAKEN, 3 EV_CLEARED (intel::EventType); 4-7 reserved
// for HELP calls. A HELP younger than intel's HELP_HOLD rounds is never overwritten by intel news, and intel ignores types 4-7 when
// reading. The readers of the enemy alarm (econ banking, the r3 altar-lock check in combat code) use intel::latest_sighting(), which
// covers own sight, wards and teammates' EV_ENEMY/EV_ENEMIES events. The event slot carries one message at a time; intel.cc decides
// what to post and when it may be overwritten. Event type registry: 0-3 intel news (intel.cc); 4 HELP (brain FLEE_WISE help_post /
// help_join); 5 SG3 crew call (econ SG_CALL_EV, subject = group); 6 TEAM INTEL EV_SIGHT with TI_SIGHT (free otherwise); 7 zone plan
// (contest_play.cc EV_CONTEST). Writers of types 4-7 leave a fresh event of another 4-7 type standing.
#pragma once
#include "common.h"

// TEAM INTEL: per-enemy sightings in the event slot, type 6 (EV_SIGHT), and their readers. Integer switches only; all 0 = off.
// EV_SIGHT payload (13 bits; byte 6 never 0, so the slot never reads empty): P = ((cell x NE) + e) x 2 + toggle, with byte 6 = 1 + P
// % 255 and byte 7 = 6 << 5 | P / 255. e = the enemy's index in roster(team::enemy) (same order on every body), cell = a fixed-size
// square of tiles, toggle = flipped when the same (e, cell) is posted again, so a re-post still changes the slot. No round stamp: a
// reader takes a changed slot as news of the last round.
#define TI_SIGHT 0 // 1: bodies post EV_SIGHT and keep a team table of enemy positions.

// TEAM MEMORY VIEW. Runtime data flag TM_TAB[1], read first. Bit 1: read() decodes the team word once per turn into the cached
// struct V below (claim group / engaged per slot, the event, the host word for spare fields); own writes refresh it in place; the
// header's inline readers (cgroup, cengaged, ev) read V without a call. The decoded values are the ones
// claim()/claim_group()/event() give. 0 = every reader decodes the 8-byte image per call.
#define TM_BITS 1
inline constexpr int TM_TAB[2] = { 0x544D3031, TM_BITS }; // slot 0 magic keeps it out of .bss
#define TMEM_ON true

namespace nova::comms {
}
namespace nova::comms {
}
namespace nova::comms {
int slim_saved(); // claim bits freed against the full layout (0 off)
bool slim_layout(); // the slim claim layout is in force (the bucket is not sent)
}
// FL: TM2 FIGHT LAYER (needs TM2 bits 1+8, CMP bit 1). Runtime data flag FL_TAB[1], read first; 0 = off. Bit 1 (FL1): near a foe
// (within 6, FIGHT/FLEE, not engaged on a camp) my claim says in-fight stance (commit/hold/retreat) x HP band instead of my group; a
// body walking to a call says coming (ETA x octant x HP). Bit 2 (FL2): the lead body (no visible lower slot mate near) posts FIGHT
// cell x call (1 commit, 2 hold, 3 retreat; rally 0 = HELP when it fights and is not winning) on change, refreshed every 3 rounds.
// Bit 4 (FL3a): assess() counts unseen 'coming' mates of ETA <= 2 placed at the call + octant, inside join_r only, weight FL_W_X100
// / 100, healthy only, not in n_friends. Bit 8 (FL3b): follow a mate's fresh call near me (retreat: FIGHT -> FLEE unless winning;
// commit: FLEE -> FIGHT at HP >= FL_COMMIT_HP %, focus, not lethal). Bit 16 (FL3c): joiners only on rally/commit within FL_JOINETA,
// never on hold/retreat.
#define FL_BITS 23
#define FL_AGE 4
#define FL_JOINETA 8
#define FL_COMMIT_HP 35
#define FL_W_X100 50
#define FL_ETAB 1 // FL3a: largest coming ETA bucket counted (0: ETA <= 2 placed 2 from the call; 1: also ETA 3-5 placed 4 from it)
namespace nova::comms {
inline constexpr int FL_TAB[7] = { 0x464C3031, FL_BITS, FL_AGE, FL_JOINETA, FL_COMMIT_HP, FL_W_X100, FL_ETAB }; // FL table: stance publish, lead fight call, coming-mates ETA <= 5
struct FightCall
{
	int cell = -1, call = -1, r = -1000; // newest FIGHT call decoded or posted: 6x6 cell, call (0 rally, 1 commit, 2 hold, 3 retreat), round
	bool mine = false;
};
inline FightCall fl_call;
}

namespace nova::comms {

constexpr int CLAIM_SLOTS = 6;
constexpr std::uint8_t ENGAGED = 0x80;

void read();                       // refresh the local copy (one host call)
std::uint8_t claim(int slot);      // cached claim byte of a slot
int claim_group(std::uint8_t c);   // target group index or -1
inline bool claim_engaged(std::uint8_t c) { return (c & ENGAGED) != 0; }
void write_claim(int slot, int group, bool engaged); // writes only when the value changes

// Team event slot (bytes 6-7).
struct Event
{
	int subject = -1; // -1: empty
	int type = 0;
	int stamp = 0;    // round & 31
	std::uint16_t raw = 0;
};
Event event();                                 // cached event from the last read()
// TEAM MEMORY VIEW (TM_TAB bit 1): the per-turn decoded struct. Filled by decode() at read() and by own writes; valid only with
// TMEM_ON.
struct View
{
	std::array<std::int8_t, CLAIM_SLOTS> cg{ -1, -1, -1, -1, -1, -1 }; // claim group per slot, -1 none (= claim_group(claim(s)))
	std::array<std::uint8_t, CLAIM_SLOTS> ce{};                          // 1 = engaged (= claim_engaged(claim(s)))
	Event ev;                                                            // = event()
	// the CAMP entries standing in the word this turn, decoded once by econ::camp_news_read (CMP_TAB bit 1; camp_n 0 when off). camp_r = the
	// respawn round the entry says (exact-R arm: 'no earlier than'; log arm: the bucket's lower edge).
	int camp_n = 0;
	std::array<std::int16_t, 2> camp_g{ -1, -1 };
	std::array<std::int32_t, 2> camp_r{ 0, 0 };
	std::uint64_t touched = 0; // TM2 bit 4: groups (index < 64) whose team belief moved in this turn's decode
	std::array<std::uint8_t, CLAIM_SLOTS> ck{}; // TM2 bit 8: claim kind per slot: 0 idle, 1 dead, 2 heading, 3 engaged, 4 in a fight, 5 coming
	std::array<std::uint8_t, CLAIM_SLOTS> cv{}; // its value: dead bucket 1-3, ETA or forecast bucket 0-3, stance x 4 + HP band, ETA x 16 + octant x 2 + HP
};
extern View V;
// Readers: from V when TM bit 1 is on (inline, no call), else through the 8-byte-image functions.
std::uint8_t claim(int slot);
int claim_group(std::uint8_t c);
inline int cgroup(int s)
{
	return (s >= 0 && s < CLAIM_SLOTS) ? V.cg[static_cast<std::size_t>(s)] : -1;
}
inline bool cengaged(int s)
{
	return (s >= 0 && s < CLAIM_SLOTS) && V.ce[static_cast<std::size_t>(s)] != 0;
}
inline int ckind(int s) { return (s >= 0 && s < CLAIM_SLOTS) ? V.ck[static_cast<std::size_t>(s)] : 0; } // TM2 bit 8
inline int cval(int s) { return (s >= 0 && s < CLAIM_SLOTS) ? V.cv[static_cast<std::size_t>(s)] : 0; }
void claim_x(int x); // TM2 bit 8: for the next write_claim. With a group: bucket 0-3. Without: 0 idle, 1-3 dead, 100 + k in a fight, 200 + k coming
extern bool bh64_help_dropped; // The last HELP write_event was dropped by the channel.
int team_mem_code_count(int ng); // the channel's code count on this map
int help_c(); // the HELP cell size
void legacy_in(int subject, int type, int round); // TM2 bit 16: an event decoded from the channel
struct LegacyQ // TMF bit 1 (econ.h): the 8-byte-layout events decoded in one read
{
	int n = 0, r = -1000;
	std::array<Event, 4> e{};
};
extern LegacyQ lq;
inline Event ev()
{
	return V.ev;
}
// PACK spare bits (bit 1 of the packing flag): free bits of the 64, top down. To add a field: at init, the same order on every body,
// f = comms::spare_alloc(12); then comms::spare_put(f, v); v = comms::spare_get(f). Not ok() when packing is off or no room is left
// (a body must then do without the field). Reads see the last read() and my own puts.
struct Spare
{
	int off = -1, w = 0;
	bool ok() const { return off >= 0; }
};
int spare_bits();                                   // free bits left on this map and team
Spare spare_alloc(int width);                       // width 1-32
std::uint32_t spare_get(Spare f);
void spare_put(Spare f, std::uint32_t v);
void write_event(int subject, int type, int round); // type 0-7, subject 0-254
constexpr int EV_TYPE_HELP = 4; // first type reserved for HELP calls
constexpr int STAMP_MASK = 31;
constexpr int EV_SIGHT = 6; // TEAM INTEL: a per-enemy sighting (payload instead of subject and stamp)
inline bool is_sight(const Event& e) { return TI_SIGHT && e.subject >= 0 && e.type == EV_SIGHT; }
// First-seen tracking of the slot's bytes (for the ghost-image and hold readers). Call note_seen(round) after read() each turn.
void note_seen(int round);
int rounds_since_event_slot_changed(int now);                     // rounds since this body first saw the slot's current bytes (own posts: since written)
int event_age_rounds(const Event& e, int now);       // the stamp's age unwrapped: the smallest value >= rounds_since_event_slot_changed that matches the stamp

} // namespace nova::comms
