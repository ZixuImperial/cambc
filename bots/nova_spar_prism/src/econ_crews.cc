// econ_crews.cc: Which mates form a crew at a group, and crew clear estimates.
#include "econ_internal.h"
namespace nova::econ {
namespace {


// Stuns per 8 rounds that land on camps (each cancels one monster hit).
float camp_stuns(const Kit& k)
{
	float n = 0;
	if (k.slot_cc >= 0 && k.cc_on_camps)
		n += 1;
	if (k.aoe_stun)
		n += 1;
	if (k.dash_stun)
		n += 1;
	if (k.reset_enhanced)
		n += 1;
	return n;
}
// Own-kit rule bits 2 and 4: the parts of camp_stuns(k) the crew soak reads apart (callers read the flag first). Area stun:
// champ_ryth.h; landing stun: champ_heart.h.
void stun_parts_of_member(Member& x, const Kit& k)
{
	x.ko1_area = ryth_layer::camp_area_stuns(k);
	x.ko1_land = heart_layer::camp_landing_stuns(k);
}
// The strength of group g's attackers inside the best radius-1 square: any centre (Ryth's area, ground target) and a centre off the
// group's camp tiles (Heart lands on a free tile). Static per group (camp tiles and strengths), kept per group.
struct Ko1Cover
{
	float any = -1;
	float xa = 0, xl = 0; // per cast past the strongest attacker: any - str_max (area), free - str_max (landing), >= 0
	long cost = -1;       // the cover's fuel, once its box is known (box origin bx, by and size bw x bh)
	int bx = 0, by = 0, bw = 0, bh = 0;
	int skip_r = -1000;   // the round a call found too little fuel for it
};
std::vector<Ko1Cover> ko1_cov;
std::vector<float> ko1_box;               // scratch: attacker strength within radius 1, over the group's box grown by 1
std::vector<std::uint8_t> ko1_boc;        // scratch: 1 = a member's tile, same box
constexpr long OWN_KIT_RULES_COVER_FUEL = 40000;    // fuel kept for the rest of the turn on top of the cover's own cost
const Ko1Cover& stun_cover_slow(const GroupI& g);
inline const Ko1Cover& stun_cover(const GroupI& g)
{
	const std::size_t i = static_cast<std::size_t>(g.idx);
	if (i < ko1_cov.size() && ko1_cov[i].any >= 0)
		return ko1_cov[i];
	static const Ko1Cover none{};
	if (g.idx < 0 || g.idx >= M.ng || &M.groups[i] != &g)
		return none; // not one of the map's groups (no kept entry): no extra
	return stun_cover_slow(g);
}
// Once per group: each attacker adds its strength to the 9 tiles around it on a scratch grid over the group's bounding box grown by
// 1 (O(box + 9n); a map-sized buffer costs a fuel a byte to fill, so a quadratic version would eat the champions' first turns on
// central-blob maps). It runs only when the turn has its cost + OWN_KIT_RULES_COVER_FUEL left; else no extra this call and a later call tries.
// The entry is written only when complete.
__attribute__((noinline)) const Ko1Cover& stun_cover_slow(const GroupI& g)
{
	static const Ko1Cover none{};
	if (ko1_cov.size() != static_cast<std::size_t>(M.ng))
		ko1_cov.assign(static_cast<std::size_t>(M.ng), Ko1Cover{});
	Ko1Cover& c = ko1_cov[static_cast<std::size_t>(g.idx)];
	if (c.cost < 0)
	{
		int ax = 1 << 20, ay = 1 << 20, zx = -(1 << 20), zy = -(1 << 20);
		for (int ci : g.members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			ax = std::min(ax, p.x);
			ay = std::min(ay, p.y);
			zx = std::max(zx, p.x);
			zy = std::max(zy, p.y);
		}
		ax = std::max(0, ax - 1);
		ay = std::max(0, ay - 1);
		zx = std::min(M.w - 1, zx + 1);
		zy = std::min(M.h - 1, zy + 1);
		c.bx = ax;
		c.by = ay;
		c.bw = std::max(0, zx - ax + 1);
		c.bh = std::max(0, zy - ay + 1);
		c.cost = 8L * c.bw * c.bh + 120L * static_cast<long>(g.members.size()); // fill + scan per tile, 9 adds per attacker
	}
	if (c.bw <= 0 || c.bh <= 0)
	{
		c.any = 0; // no tile: no extra, kept
		return c;
	}
	if (c.skip_r == now())
		return none; // Short of fuel earlier this turn: fuel only falls within a turn.
	if (fuel() < c.cost + OWN_KIT_RULES_COVER_FUEL)
	{
		c.skip_r = now();
		return none;
	}
	const int x0 = c.bx, y0 = c.by, bw = c.bw, bh = c.bh, x1 = x0 + bw - 1, y1 = y0 + bh - 1;
	const std::size_t nb = static_cast<std::size_t>(bw) * static_cast<std::size_t>(bh);
	ko1_box.assign(nb, 0.0f);
	ko1_boc.assign(nb, 0);
	for (int ci : g.members)
	{
		const auto& cm = M.camps[static_cast<std::size_t>(ci)];
		if (cm.pos.x >= x0 && cm.pos.x <= x1 && cm.pos.y >= y0 && cm.pos.y <= y1)
			ko1_boc[static_cast<std::size_t>((cm.pos.y - y0) * bw + (cm.pos.x - x0))] = 1;
		if (!cm.attacks())
			continue;
		for (int y = std::max(y0, cm.pos.y - 1); y <= std::min(y1, cm.pos.y + 1); ++y)
			for (int x = std::max(x0, cm.pos.x - 1); x <= std::min(x1, cm.pos.x + 1); ++x)
				ko1_box[static_cast<std::size_t>((y - y0) * bw + (x - x0))] += cm.str;
	}
	float any = 0, fre = 0;
	for (std::size_t t = 0; t < nb; ++t)
	{
		any = std::max(any, ko1_box[t]);
		if (ko1_boc[t] == 0) // v699 R2B bit 1024 KOW1
			fre = std::max(fre, ko1_box[t]);
	}
	c.xa = std::max(0.0f, any - g.str_max);
	c.xl = std::max(0.0f, fre - g.str_max);
	c.any = any; // last: the entry counts as kept from here
	return c;
}
// The crew soak's camp hits cancelled per round past the strongest attacker's (area and landing stuns cover the other attackers in
// their square), and the stuns the spell hold keeps off camps this turn (taken out of stuns8). Returns the extra strength cancelled
// per round; *st8 = the stuns per 8 rounds left for the strongest attacker. Callers test ko1_any(c) first (the soak runs on every
// clear estimate).
inline bool ko1_any(const Crew& c) { return c.ko1_area8 + c.ko1_land8 + c.ko1_cc8 + c.ko1_ccp8 > 0; }
inline float stun_soak_cancel(const Crew& c, const GroupI& g, float* st8)
{
	*st8 = c.stuns8;
	float extra = 0;
	if (c.ko1_cc8 + c.ko1_ccp8 > 0 && combat::camp_spell_hold_without_prism())
	{
		const float held = c.ko1_cc8 + (prism_layer::camp_stun_free_now() ? 0.0f : c.ko1_ccp8);
		OWN_KIT_RULES_CNT(4, held > 0);
		*st8 = std::max(0.0f, *st8 - held);
	}
	if (c.ko1_area8 + c.ko1_land8 > 0 && (g.n_att >= 2)) // KCV1: <= 1 attacker -> cover extra +0
	{
		constexpr float inv_cd = 1.0f / static_cast<float>(rs::slot_cooldown());
		const Ko1Cover& cv = stun_cover(g);
		const float ra = std::min(1.0f, c.ko1_area8 * inv_cd);
		const float rl = std::min(1.0f - ra, c.ko1_land8 * inv_cd);
		extra = ra * cv.xa + rl * cv.xl;
		OWN_KIT_RULES_CNT(2, extra > 0);
	}
	return extra;
}
} // namespace
} // namespace nova::econ
