// econ_groups.cc: Camp and group status memory, ownership, quiet tracking, awake and living members.
#include "econ_internal.h"
namespace nova::econ {
bool qk_q = false;
bool qk_wasq = false;
int qk_plast = -1000;
namespace {
// Rounds from `start` (the capture timer's start, cap_on) to the round after the reward of group g's capture. Mine:
// capture_pay(holder). Else an allied Capture holder seen on a member camp tile from round J caps it: min(start + 6, max(J, start) +
// 4) (a holder arriving later caps the remaining time at 3, never raises it). J is the first round I saw one there.
struct CbnCap
{
	int key = -1, start = -1, j = -1, used = -1000;
};
} // namespace
void team_quiet_track()
{
	const int t = W.round;
	if (!W.enemies.empty() || !W.enemies_far.empty())
		qk_own = t;
	else if (W.alive && combat::took_damage(1) && !combat::hit_explained_by_camp())
	{
		qk_hit = t; // a loss no visible foe or camp explains
		qk_own = t;
	}
	qk_wasq = t >= QKW_TAB[2] && t - 1 - qk_plast >= QKW_TAB[2];
	qk_plast = qk_last();
}
int qk_last() { return std::max(std::max(intel::latest_sighting(), qk_hit), std::max(qk_own, qk_mate)); }
bool team_quiet()
{
	const int t = W.round;
	if (qk_r == t)
		return qk_q;
	qk_r = t;
	const int qr = QKW_TAB[2];
	qk_q = W.alive && t >= qr && t - qk_last() >= qr;
	return qk_q;
}
namespace {
int now() { return W.round; }
// the camp lives right now (this turn's hits included; W.camps is the turn-start view). Out of sight: as seen.
bool camp_alive_now(int ci)
{
	if (ci < 0 || ci >= M.nc)
		return false;
	std::uint32_t v = 1;
	if (cambc::detail::sdk_camp_state(M.camps[static_cast<std::size_t>(ci)].handle, &v) != 0)
		return true;
	return v != 0;
}
const std::vector<CampBit>& camp_bits()
{
	static std::vector<CampBit> cb;
	if (cb.size() != static_cast<std::size_t>(M.nc))
	{
		cb.resize(static_cast<std::size_t>(M.nc));
		for (std::size_t i = 0; i < static_cast<std::size_t>(M.nc); ++i)
		{
			const vec2 p = M.camps[i].pos;
			cb[i].k = (p.y >> 3) * G.stride + (p.x >> 3);
			cb[i].m = std::uint64_t{ 1 } << (((p.y & 7) << 3) | (p.x & 7));
			cb[i].hp = M.camps[i].hp;
		}
	}
	return cb;
}
const VisCamp* visible_camp(int ci)
{
	// FW: perceive keeps W.camp_slot (camp index -> position in W.camps) for this turn's camps: the same lookup without
	// this function's per-round index (rebuilt over every camp of the map) and its checks.
	const VisCamp* r = W.camp_by_index(ci);
	return r;
}
int my_slot() { return P.my_slot; }
// ---------------------------------------------------------------- CBN (common.h): rule-correct helpers, called only with a CBN bit
// on R10: channel ticks of n gems for a holder or not; 0 for an empty group (the rule's max(1, .) floor must not add a tick). CBN
// recall (bits 1, 16, 32): a recall decided now: pre-fired when my kept spin from the last turn end still runs (sps_pending,
// common.h SPIN_SELF; cancelled by the turn's first action, kept by a recall).
static int cbn_recall_t() { return rs::recall_rounds(prism::has_family(rs::F_HOME), static_cast<bool>(sps_pending)); }
static int cbn_tt(int n, bool holder) { return rs::tribute_rounds(n, holder); }
// does body slot `self` hold the Tribute emblem (mine from my items; a mate's read through the SDK, cached per slot and round)
static bool slot_holds_tribute(int self)
{
	static int at[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };
	static bool val[8] = {};
	if (self == P.my_slot)
		return prism::has_family(rs::F_TRIBUTE);
	if (self < 0 || self >= 8 || self >= P.n)
		return false;
	const auto s = static_cast<std::size_t>(self);
	if (at[s] != now())
	{
		at[s] = now();
		val[s] = rs::has(rs::families(P.handle[s], now()), rs::F_TRIBUTE);
	}
	return val[s];
}
// lower bounds near 2000: body h's family from its read items; `unknown` when they were never read.
static bool body_family_or_default(std::uint32_t h, int fam, bool unknown)
{
	const std::uint16_t b = rs::families(h, now());
	for (const auto& c : rs::fam_cache)
		if (c.used && c.h == h)
			return rs::has(b, fam);
	return unknown;
}
static bool capture_holder_on_group(const GroupI& g)
{
	for (const auto& al : W.allies)
	{
		bool on = false;
		for (int ci : g.members)
			on |= M.camps[static_cast<std::size_t>(ci)].pos == al.pos;
		if (on && rs::has(rs::families(al.h, now()), rs::F_CAPTURE))
			return true;
	}
	return false;
}
// start < 0: a step that starts the timer now (a holder there now is on from the start).
static int group_capture_pay_rounds(const GroupI& g, int start)
{
	if (prism::has_family(rs::F_CAPTURE))
		return rs::capture_pay(true);
	const int slow = rs::capture_pay(false);
	if (start < 0)
		return capture_holder_on_group(g) ? rs::capture_pay(true) : slow;
	static CbnCap slot[4];
	const int key = g.members.empty() ? -1 : g.members.front();
	CbnCap* c = nullptr;
	for (auto& x : slot)
		if (x.key == key && x.start == start)
			c = &x;
	if (!c)
	{
		c = &slot[0];
		for (auto& x : slot)
			if (x.used < c->used)
				c = &x;
		c->key = key;
		c->start = start;
		c->j = -1;
	}
	c->used = now();
	if (c->j < 0 && capture_holder_on_group(g))
		c->j = now();
	if (c->j < 0)
		return slow;
	const int el = std::max(0, c->j - start); // timer rounds run before a holder was on the region
	return rs::capture_join_pay(el + 1); // Join offset from the step-on round = el + 1 (start = step-on + 1); one shared source for the join timing.
}
// The first early-out test is inline at the call site (saves a call and frame a turn); the rest stay out of line.
__attribute__((always_inline)) void refresh_owned()
{
	if (now() - own.checked < 10)
		return;
	refresh_owned_slow();
}
__attribute__((noinline)) void refresh_owned_slow()
{
	if (now() - own.checked < 10)
		return;
	own.checked = now();
	try
	{
		const std::uint32_t* const counts = my_items_raw(); // Reads the counts in place: no zero-filled copy.
		own.jungle = own.monster = own.home = false;
		own.treasure = false;
		own.shards = 0;
		// The read ends at ITEM_N (enum_map::operator[] throws out_of_range past it, and the catch below would end the read); four zero
		// counts at a time are skipped with one v128 test (the body does nothing for a count <= 0).
		const std::uint32_t lim = std::min<std::uint32_t>(84u, static_cast<std::uint32_t>(ITEM_N)); // the 2.0.0 families (ids 42-83) add shards too
		for (std::uint32_t i = 0; i < lim; ++i)
		{
			if ((i & 3u) == 0 && i + 4 <= lim && !wasm_v128_any_true(wasm_v128_load(counts + i)))
			{
				i += 3;
				continue;
			}
			const int n = static_cast<int>(counts[i]);
			if (n <= 0)
				continue;
			const std::uint32_t family = i / 6;
			const bool emblem = (i & 1u) != 0;
			own.shards += emblem ? 5 * n : n;
			if (emblem && family == 0)
				own.monster = true;
			if (emblem && family == 4)
				own.jungle = true;
			if (emblem && family == 5)
				own.home = true;
			if (emblem && family == 3)
				own.treasure = true;
		}
	}
	catch (...)
	{
	}
}
} // namespace
} // namespace nova::econ
