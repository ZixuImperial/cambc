// combat_team.cc: Mates, focus choice and help.
#include "combat_internal.h"
namespace nova::combat {
namespace mates
{
// Fight strength of one of our bodies: effective health (shield ready counts) and kit-weighted damage.
void add_friend(const Body& b, float& hp, float& dps)
{
	const Kit* kp = b.kit;
	float h = eff_hp(b);
	float d = 50.0f;
	if (kp && kp->valid)
	{
		const Kit& k = *kp;
		d = horizon_dps(b, b.ally && b.h == W.me.h);
		if (k.slot_shield >= 0 && kit_rules::slot_ready(b, k.slot_shield) && b.shield <= 0)
			h += mu::mult_shield_to_eff_hp(b, k.shield_mod * b.foc);
		// Heals enter through support_heal_pool(), not as the healer's own health.
	}
	hp += h;
	dps += d;
}
namespace {
// Damage per turn our bodies near enemy e can put on it (me and visible allies that reach it within a step or two).
// hd[k] = horizon_dps1 of body k (0 me, 1.. W.allies), computed at most once per team_focus (negative: not yet). It depends on
// the body and W only, and nothing changes W inside team_focus.
float team_dps_on(const Body& e, std::array<float, 8>& hd)
{
	float d = 0;
	auto add = [&](const Body& b, bool me, std::size_t k)
	{
		if (b.channeling())
			return;
		const int reach = std::max(b.range, b.kit ? static_cast<int>(std::max(b.kit->dmg_range, b.kit->cc_range)) : 1);
		if (cheb(b.pos, e.pos) > reach + 2)
			return;
		if (k >= hd.size())
		{
			d += (dmg::horizon_dps1(b, me));
			return;
		}
		float& m = hd[k];
		if (m < 0.0f)
			m = dmg::horizon_dps1(b, me);
		d += m; // damage on e alone
	};
	add(W.me, true, 0);
	std::size_t k = 1;
	for (const auto& al : W.allies)
		add(al, false, k++);
	return std::max(10.0f, d);
}
} // namespace
static inline bool ofs_want(int bit) { return (OFS_TAB[1] & bit) != 0; }
namespace {
static float focus_share_of(const Body& m, bool me, const Body& e)
{
	const int eh = static_cast<int>(e.h);
	if (me && ((focus_share.round == W.round && eh == focus_share.focus_handle) || (hold_state.lock_handle == eh && W.round - hold_state.lock_seen <= 3)))
		return static_cast<float>(OFS_TAB[5]) / 100.0f;
	const int reach = std::max(m.range, m.kit ? static_cast<int>(std::max(m.kit->dmg_range, m.kit->cc_range)) : 1); // team_dps_on's reach
	const int de = cheb(m.pos, e.pos);
	if (de <= reach)
	{
		bool only = true;
		for (const auto& o : W.enemies)
			only = only && (o.h == e.h || cheb(o.pos, m.pos) > reach);
		if (only)
			return static_cast<float>(OFS_TAB[5]) / 100.0f;
	}
	return static_cast<float>(OFS_TAB[me ? 2 : de <= 1 ? 3 : 4]) / 100.0f;
}
} // namespace
static const Body* nearest_foe_to(vec2 p)
{
	const Body* b = nullptr;
	int bd = BIG;
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, p);
		if (d < bd)
		{
			bd = d;
			b = &e;
		}
	}
	return b;
}
static inline void scale_by_focus_share(int bit, const Body& m, bool me, const Body* e, float& d, float w)
{
	(void)w; // the site's own weight on this body
	if ((OFS_TAB[1] & bit) != 0 && e)
		d *= focus_share_of(m, me, *e);
}
namespace {
// A ready damage spell that fight() casts on its focus reaches distance d this turn.
static bool damage_spell_reaches(const Kit& k, int d)
{
	if (k.slot_dmg >= 0 && k.dmg_mod > 0 && ready(k.slot_dmg) && d <= static_cast<int>(k.dmg_range) && (!k.dmg_excl || !W.moved))
		return true;
	if (k.slot_aoe >= 0 && k.aoe_mod > 0 && ready(k.slot_aoe) && d <= static_cast<int>(k.aoe_range + k.aoe_radius) && (!k.aoe_excl || !W.moved))
		return true;
	return k.slot_dash >= 0 && k.dash_mod > 0 && ready(k.slot_dash) && d <= static_cast<int>(k.dash_range + k.dash_radius);
}
static int channel_target_b(const int b8)
{
	if (!W.me.kit)
		return -1;
	const Kit& k = *W.me.kit;
	const bool cc = k.slot_cc >= 0 && ready(k.slot_cc);
	const std::uint32_t chan = (b8 & TARGETING_FIX_BIT_CTC) != 0 ? (ST_RECALL | ST_TRIBUTE | ST_TELEPORT) : (ST_RECALL | ST_TRIBUTE);
	int best_i = -1;
	float best = -1;
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		if (!(e.state & chan))
			continue;
		if (foe_model::fresh_recall(e))
			continue;
		const int d = cheb(e.pos, W.me.pos);
		// Reach this turn: a basic attack (melee may step first), or a stun on a tribute (damage does not stop one).
		const bool hit = (d <= W.me.range || (!k.ranged && W.can_move() && d <= W.me.range + 1) || ((b8 & TARGETING_FIX_BIT_CTR) != 0 && (e.state & ST_RECALL) && damage_spell_reaches(k, d))) &&
			((b8 & TARGETING_FIX_BIT_CTC) == 0 || (e.state & (ST_RECALL | ST_TRIBUTE))); // only a stun stops a crystal
		const bool stun = (cc && d <= static_cast<int>(k.cc_range) + (0) && // step + stun
			marcella_layer::fight_stun_holds(e));
		if (!hit && !stun)
			continue;
		if (bbget(M.enemy_spawn, e.pos) && d > W.me.range && !((b8 & TARGETING_FIX_BIT_CTS) != 0 && stun))
			continue;
		// A recall is cancelled by any hit; a tribute only by a stun or a kill, but hits on it come free.
		float v = (e.state & ST_RECALL) ? 2.0f : (stun ? 2.0f + static_cast<float>(e.gems) / 20.0f : 1.0f);
		v += 1.0f - e.frac();
		if (v > best)
		{
			best = v;
			best_i = static_cast<int>(i);
		}
	}
	return best_i;
}
__attribute__((noinline)) int react_attacker_slow()
{
	const vec2 me = W.me.pos;
	const int hit_r = (!W.me.kit->ranged && W.can_move()) ? W.me.range + 1 : W.me.range;
	int best = -1;
	float best_h = 1e9f;
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const Body& e = W.enemies[i];
		const int d = cheb(e.pos, me);
		if (d > e.range + 1 || d > hit_r || foe_model::unreachable(e))
			continue;
		if (ren_layer::kills_me(e))
			continue; // its retaliation would kill me
		const float h = eff_hp(e);
		if (h < best_h)
		{
			best_h = h;
			best = static_cast<int>(i);
		}
	}
	return best;
}
} // namespace
// How much of an ally's strength my fight can count on (0..1). An ally already next to a foe or to me is in the
// fight; one further away, busy tanking its camp, low on health (it leaves below 45% with enemies near) or carrying a
// big bag (it is careful) may not come.
float ally_commit_weight(const Body& al, const Assessment& a)
{
	int dn = BIG;
	const bool xic_acw = XIC_ON(8); // v723 XIC bit 8 ACW1: dn is read only as dn <= 3, so the first foe within 3 settles it
	for (const auto& f : a.foes)
		if (!f.remembered)
		{
			dn = std::min(dn, cheb(f.pos, al.pos));
			if (xic_acw && dn <= 3)
				break;
		}
	const int dm = cheb(al.pos, W.me.pos);
	float w = dn <= 3 ? 1.0f : (dm <= 3 ? 0.9f : 0.7f);
	if (dn <= 3)
		w = 0.01f * static_cast<float>(SQM_TAB[2]);
	else if (dm <= 3)
		w = 0.01f * static_cast<float>(SQM_TAB[3]);
	if (al.frac() < 0.45f)
		w *= (0.01f * static_cast<float>(SQM_TAB[4]));
	if (dn > 3 && al.slot >= 0 && al.slot < static_cast<int>(comms::CLAIM_SLOTS) && comms::cengaged(al.slot) &&
		!(comms::cgroup(al.slot) >= 0 && comms::cgroup(al.slot) == econ::claim_target())) // CB3 bit 2 MCW: engaged on my group is my fight
		w *= 0.6f;
	if (al.gems >= 40)
		w *= 0.8f;
	return w;
}
// An ally within r (5) of me has a visible foe within 2 of it (a fight is on next to me), or a foe a team mate
// reported there this round or last (join side only).
bool ally_in_contact_within(const Assessment& a, int r)
{
	for (const auto& al : W.allies)
	{
		if (al.channeling() || cheb(al.pos, W.me.pos) > r)
			continue;
		for (const auto& f : a.foes)
			if (!f.remembered && cheb(f.pos, al.pos) <= 2)
				return true;
	}
	return false;
}
// strength of the awake attacking camps in sight that hit body b (an ally: ours; an enemy: !ours) this round:
// b in the camp's reach and no other body nearer. A tie between two of ours goes to the one that acts first (higher
// priority, then lower slot: mv::takes_tie); a tie between sides counts against us (our body is hit, theirs is not).
// mv::camp_threat answers this for my own tile only (it never counts me as the nearer body).
float camp_hit_strength_on_body(const Body& b, bool ours)
{
	AF_CHECK();
	float total = 0;
	const int bs = ours ? b.slot : -1;
	const std::vector<int>& al_k = memory::awake_slots();
	const std::size_t al_n = al_k.size();
	struct ChfM
	{
		int st, mn, cnt;
	};
	static std::vector<ChfM> chf_memo;
	static int chf_st = 0, chf_p = -1;
	static vec2 chf_me{ -1, -1 };
	if ((chf_p != fg::pstamp || chf_me != W.me.pos))
	{
		chf_p = fg::pstamp;
		chf_me = W.me.pos;
		++chf_st;
	}
	const bool rtv_m = ours; // fuel: one answer per ally per stamp
	const int rtv_tp = rtv_m ? mv::tie_prio(P.my_slot) : 0;
	if (rtv_m && nova::combat::retreating_mates::retreat_value_cache_get(chf_st, b, rtv_tp, total))
		return total;
	for (std::size_t q = 0; q < al_n; ++q)
	{
		const auto& vc = W.camps[(static_cast<std::size_t>(al_k[q]))];
		if (!vc.awake)
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (!c.attacks())
			continue;
		const int d = cheb(b.pos, c.pos);
		if (d > c.reach)
			continue;
		bool other = false;
		// The nearest distance and how many bodies stand there, per camp, once. Nearer than me: someone else is hit. Alone at it: me.
		const std::size_t ck = static_cast<std::size_t>(al_k[q]);
		if (ck >= chf_memo.size())
			chf_memo.resize(W.camps.size() + 1);
		ChfM& cm = chf_memo[ck];
		if (cm.st != chf_st)
		{
			int mn = BIG, cnt = 0;
			auto see = [&](const Body& o)
			{
				const int dd = cheb(o.pos, c.pos);
				if (dd < mn)
				{
					mn = dd;
					cnt = 1;
				}
				else if (dd == mn)
					++cnt;
			};
			see(W.me);
			for (const auto& al : W.allies)
				see(al);
			for (const auto& e : W.enemies)
				see(e);
			cm = { chf_st, mn, cnt };
		}
		if (d > cm.mn)
			continue;
		if (d == cm.mn && cm.cnt == 1)
		{
			total += c.str;
			continue;
		}
		auto check = [&](const Body& o, bool o_ours, int os)
		{
			if (other || o.h == b.h)
				return;
			const int dd = cheb(o.pos, c.pos);
			if (dd < d)
				other = true;
			else if (dd == d)
			{
				if (!ours)
					other = true;
				else if (o_ours && os >= 0 && os < 8 && bs >= 0 && bs < 8)
				{
					{
						const int po = mv::tie_prio(os), pb = mv::tie_prio(bs);
						other = po > pb || (po == pb && os < bs);
					}
				}
			}
		};
		check(W.me, true, P.my_slot);
		for (const auto& al : W.allies)
			if (!other)
				check(al, true, al.slot);
		for (const auto& e : W.enemies)
			if (!other)
				check(e, false, -1);
		if (!other)
			total += c.str;
	}
	if (rtv_m)
		nova::combat::retreating_mates::retreat_value_cache_put(chf_st, b, rtv_tp, total);
	return total;
}
// The fight power idle team mates could bring to `at`: farther than `inner` (counted already), within
// EN_HELP_R, not channelling, half health or more, not engaged on their claim (claim byte bit 7): the bodies help_join sends.
float idle_mate_help_power(vec2 at, int inner)
{
	float p = 0;
	const Body* oe = ofs_want(OFS_BIT_HELP) ? nearest_foe_to(at) : nullptr;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, at);
		if (d <= inner || d > EN_HELP_R || al.channeling() || al.frac() < 0.5f || al.slot < 0 || al.slot >= comms::CLAIM_SLOTS ||
			comms::cengaged(al.slot))
			continue;
		float h = 0, dd = 0;
		add_friend(al, h, dd);
		scale_by_focus_share(OFS_BIT_HELP, al, false, oe, dd, 1.0f);
		p += std::sqrt(std::max(1.0f, h) * std::max(1.0f, dd));
	}
	return p;
}
// a fight next to a worked group: a camp hits me, or my claim target's nearest camp is within EN_NEAR.
bool fight_beside_worked_group()
{
	if (mv::camp_threat(W.me.pos) > 0)
		return true;
	const int gi = econ::claim_target();
	if (gi < 0 || gi >= M.ng)
		return false;
	for (const int ci : M.groups[static_cast<std::size_t>(gi)].members)
		if (cheb(M.camps[static_cast<std::size_t>(ci)].pos, W.me.pos) <= EN_NEAR)
			return true;
	return false;
}
// my target is a contested gem group I stand at, and the bodies at it favour us (counts and plain power).
bool contested_gem_hold()
{
	const int gi = econ::claim_target();
	if (gi < 0 || gi >= M.ng)
		return false;
	const auto& G = M.groups[static_cast<std::size_t>(gi)];
	const auto& gm = econ::memory();
	if (G.gems < CTH_GEMS || (static_cast<std::size_t>(gi) < gm.size() && gm[static_cast<std::size_t>(gi)].status == econ::GS_RESPAWN))
		return false;
	const vec2 an = G.anchor;
	if (cheb(an, W.me.pos) > CTH_NEAR)
		return false;
	if (!CI2_FIGHT() && !cassi_issac_pair_holds())
		return false;
	int n_us = 0, enemies_at_zone = 0;
	float p_us = 0, p_them = 0;
	const Body* oe = ofs_want(OFS_BIT_HOLD) ? nearest_foe_to(an) : nullptr;
	auto add_us = [&](const Body& b)
	{
		float h = 0, d = 0;
		add_friend(b, h, d);
		scale_by_focus_share(OFS_BIT_HOLD, b, b.h == W.me.h, oe, d, 1.0f);
		++n_us;
		p_us += std::sqrt(std::max(1.0f, h) * std::max(1.0f, d));
	};
	add_us(W.me);
	for (const auto& al : W.allies)
		if (!al.channeling() && al.frac() >= CTH_HP && cheb(al.pos, an) <= CTH_R)
			add_us(al);
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		if (cheb(e.pos, an) > CTH_R)
			continue;
		const Foe f = foe_of(e, static_cast<int>(i));
		++enemies_at_zone;
		p_them += std::sqrt(std::max(1.0f, f.ehp) * std::max(1.0f, f.dps_fc));
	}
	const int now = W.round;
	for (const auto& s : seen)
	{
		if (s.round == now || now - s.round > 4 || cheb(s.foe.pos, an) > CTH_R)
			continue;
		bool visible = false;
		for (const auto& e : W.enemies)
			if (e.h == s.h)
			{
				visible = true;
				break;
			}
		if (visible)
			continue;
		++enemies_at_zone;
		p_them += std::sqrt(std::max(1.0f, s.foe.ehp) * std::max(1.0f, s.foe.dps_fc));
	}
	return enemies_at_zone > 0 && n_us >= enemies_at_zone + CTH_EDGE && p_us * p_us >= CTH_MIN * p_them * p_them;
}
// FAC bit 16 NL1, caller read the flag: my channelling mates within 4 (a recall or tribute can't fight).
static int fac_nl1_channelling(vec2 me)
{
	int n = 0;
	for (const auto& al : W.allies)
		n += (al.channeling() && cheb(al.pos, me) <= 4) ? 1 : 0;
	return n;
}
EfCounts lone_fight_counts(const Assessment& a)
{
	EfCounts c;
	const vec2 me = W.me.pos;
	const int now = W.round;
	for (const auto& e : W.enemies)
		c.foes12 += cheb(e.pos, me) <= EF_FOE_R ? 1 : 0;
	c.fade5 = 5 * c.foes12;
	for (const auto& s : seen)
	{
		if (s.round == now || now - s.round > 4 || cheb(s.foe.pos, me) > EF_FOE_R)
			continue;
		bool visible = false;
		for (const auto& e : W.enemies)
			if (e.h == s.h)
			{
				visible = true;
				break;
			}
		c.foes12 += visible ? 0 : 1;
		c.fade5 += visible ? 0 : 5 - (now - s.round);
	}
	for (const auto& f : a.foes)
		if (cheb(f.pos, me) <= 5)
		{
			++c.near5;
			c.burst5 += (f.burst);
		}
	for (const auto& al : W.allies)
		c.allies4 += cheb(al.pos, me) <= 4 ? 1 : 0;
	const int fac_ch = fac_nl1_channelling(me);
	if (fac_ch > 0)
		c.allies4 -= fac_ch; // FAC bit 16 NL1: a recalling or tributing mate is no help in the fight
	return c;
}
// is a tile of the enemy spawn within Chebyshev r of c? The same answer as testing the (2r + 1)^2 tiles, by whole 8x8 chunks.
static bool enemy_spawn_near(vec2 c0, int r)
{
	if (XIC_ON(1) && r == 2 && inb(c0)) // v723 XIC bit 1 ESN1: the spawn board grown by Chebyshev 2 (in-board tiles), built on first use
	{
		static bitboard esn2;
		static bool esn2_ok = false;
		if (!esn2_ok)
		{
			bbforeach(M.enemy_spawn, [&](vec2 p) {
				if (p.x >= G.w || p.y >= G.h)
					return;
				for (int dx = -2; dx <= 2; ++dx)
					for (int dy = -2; dy <= 2; ++dy)
					{
						const vec2 t{ p.x + dx, p.y + dy };
						if (inb(t))
							bbset(esn2, t);
					}
			});
			esn2_ok = true;
		}
		return bbget(esn2, c0);
	}
	if (!NOVA_GDIRECT)
	{
		for (int dx = -r; dx <= r; ++dx)
			for (int dy = -r; dy <= r; ++dy)
			{
				const vec2 t{ c0.x + dx, c0.y + dy };
				if (inb(t) && bbget(M.enemy_spawn, t))
					return true;
			}
		return false;
	}
	const std::uint64_t* w = M.enemy_spawn.ptr();
	const int cx0 = std::max(0, c0.x - r) >> 3, cx1 = std::min(G.w - 1, c0.x + r) >> 3;
	const int cy0 = std::max(0, c0.y - r) >> 3, cy1 = std::min(G.h - 1, c0.y + r) >> 3;
	for (int cy = cy0; cy <= cy1; ++cy)
		for (int cx = cx0; cx <= cx1; ++cx)
		{
			std::uint64_t word = w[cy * G.stride + cx];
			while (word)
			{
				const int bit = __builtin_ctzll(word);
				word &= word - 1;
				const vec2 p{ cx * 8 + (bit & 7), cy * 8 + (bit >> 3) };
				if (p.x < G.w && p.y < G.h && cheb(p, c0) <= r)
					return true;
			}
		}
	return false;
}
} // namespace mates
bool team_fight_mode(vec2 at)
{
	if (W.me.kit && willow_layer::team_fight_self())
	{
		for (const auto& al : W.allies)
			if (!al.channeling() && cheb(al.pos, at) <= 6)
				return true; // I am the support and I have someone to heal
		return false;
	}
	for (const auto& al : W.allies)
		if (willow_layer::team_fight_near(al) && !al.channeling() && al.frac() > 0.25f && cheb(al.pos, at) <= 6)
			return true;
	return false;
}
int team_focus(int max_dist)
{
	AF_CHECK();
	const vec2 me = W.me.pos;
	int best_i = -1;
	float best = 1e9f;
	std::array<float, 8> hd; // team_dps_on's memo
	hd.fill(-1.0f);
	const bool hd_foc = fuel() >= HUNT_TAB[2];
	std::array<int, 8> hd_ne;
	bool hd_ne_ok = false;
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		const int d = cheb(e.pos, me);
		if (d > max_dist)
			continue;
		AF_CHECK();
		const int reach = std::max(W.me.range, W.me.kit ? static_cast<int>(std::max(W.me.kit->dmg_range, W.me.kit->cc_range)) : 0);
		if (bbget(M.enemy_spawn, e.pos) && d > reach && !(foe_model::can_get_to_foe(e)))
			continue; // on its own spawn and out of my reach: we cannot follow it there
		// Turns for the team to kill it, a small walking cost for me, and the prize: 100 gold and its whole bag.
		float s = eff_hp(e) / mates::team_dps_on(e, hd);
		s += static_cast<float>(std::max(0, d - W.me.range)) * 1.5f;
		s -= hunt_prize(e) * (PSV_HPRIZE / 100.0f); // the prize (a Prism's bag counts twice: it is also its Focus)
		if (hd_foc) // HUNT focus: lone bodies, bags and my lock first
		{
			int ne = 0;
			if (i < hd_ne.size() && W.enemies.size() <= hd_ne.size())
			{
				if (!hd_ne_ok) // near-foe counts per enemy, once per call
				{
					hd_ne_ok = true;
					hd_ne.fill(0);
					for (std::size_t p = 0; p < W.enemies.size(); ++p)
						for (std::size_t q = p + 1; q < W.enemies.size(); ++q)
							if (cheb(W.enemies[p].pos, W.enemies[q].pos) <= 4)
							{
								++hd_ne[p];
								++hd_ne[q];
							}
				}
				ne = hd_ne[i];
			}
			else
				for (const auto& o : W.enemies)
					ne += o.h != e.h && cheb(o.pos, e.pos) <= 4;
			s += ne == 0 ? -(PSV_HFLONE / 100.0f) : 1.5f * static_cast<float>(ne);
			s -= (PSV_HFBAG / 1000.0f) * static_cast<float>(std::min<int>(80, static_cast<int>(e.gems)));
			if (hold_state.lock_handle == static_cast<int>(e.h) && W.round - hold_state.lock_seen <= 3)
				s -= 5.0f;
		}
		if (e.channeling() && !foe_model::fresh_recall(e))
			s -= 6.0f;
		if (e.stunned)
			// A stunned foe I reach this turn outweighs a walk elsewhere, so the team piles on it (stunned turns otherwise go unused).
			s -= (d <= W.me.range + ((W.me.kit && !W.me.kit->ranged) ? 1 : 0)) ? 4.0f : 2.0f;
		// Cassi and Issac die together: one kill takes two bodies and both bags.
		if (ci_layer::type(e.type))
		{
			s -= 3.0f;
		}
		// Peel: a foe on top of a hurt, loaded or channelling ally of mine goes first.
		for (const auto& al : W.allies)
		{
			const bool chan = al.channeling() && cheb(al.pos, e.pos) <= 4;
			if (chan || (cheb(al.pos, e.pos) <= 2 && (al.frac() < 0.5f || al.gems >= 30)))
			{
				s -= chan ? 5.0f : 4.0f;
				break;
			}
		}
		if (s < best)
		{
			best = s;
			best_i = static_cast<int>(i);
		}
	}
	hold_state.memo = hd;
	hold_state.memo_round = W.round;
	return best_i;
}
int channel_target() { return mates::channel_target_b(TARGETING_FIX_TAB[1]); }
int channel_threat()
{
	int best_i = -1;
	int best_d = BIG;
	for (const auto& al : W.allies)
	{
		if (!al.channeling() || cheb(al.pos, W.me.pos) > 7)
			continue;
		for (std::size_t i = 0; i < W.enemies.size(); ++i)
		{
			const auto& e = W.enemies[i];
			const int de = cheb(e.pos, al.pos);
			if (de > 4 || e.channeling())
				continue;
			if (foe_model::unreachable(e))
			{
				/*BH80F:64*/
				continue;
			}
			const int d = cheb(e.pos, W.me.pos);
			if (d < best_d)
			{
				best_d = d;
				best_i = static_cast<int>(i);
			}
		}
	}
	return best_i;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) int react_attacker()
{
	if (!took_damage(2) || !W.me.kit)
		return -1;
	return mates::react_attacker_slow();
}
// the nearest ally 2-12 tiles away that is staying (not channelling) and not about to leave (above 30%
// health), else home.
vec2 react_rally()
{
	vec2 rally = M.home_anchor;
	if (FARM_RICH_RICH_ON())
		return rally; // a rich carrier rallies on home
	if (mv::home_steps(W.me.pos) <= SR_HOME_D)
		return rally;
	int rd = 13;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, W.me.pos);
		if (d < rd && d >= 2 && !al.channeling() && al.frac() > 0.3f)
		{
			int nf = 0;
			for (const auto& e : W.enemies)
				nf += cheb(e.pos, al.pos) <= 4;
			if (nf >= 2)
				continue; // that ally stands in the enemy pack
			rd = d;
			rally = al.pos;
		}
	}
	return rally;
}
bool help_called_this_round()
{
	return turn_memory.help_round == W.round;
}
// The damage the known foes near me can deal over a channel of `ticks` own turns.
float channel_damage_threat(int max_age, int r, int ticks)
{
	float sum = 0.0f;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age < 0 || age > max_age)
			continue;
		if (std::max(0, cheb(s.foe.pos, W.me.pos) - age) <= r)
			sum += (s.foe.burst + dmg::foe_dmg_dps(s.foe) * static_cast<float>(std::max(1, ticks))) * (1.0f);
	}
	return sum;
}
} // namespace nova::combat

// ---- mates posting a retreat count for less. Only reached when its flag bit 1 is set.
namespace nova::combat::retreating_mates
{
// The retreat stance a mate posts (FLEE = 8 + HP band) is decoded by comms as kind 4, value stance x 4 + band.
bool retreating(const Body& al) { return comms::ckind(al.slot) == 4 && comms::cval(al.slot) / 4 == 2; }
namespace
{
struct EchM
{
	int st = -1, tp = 0, rd = -1;
	std::uint32_t h = 0;
	vec2 p{ -1, -1 };
	float v = 0;
};
EchM ech[8];
} // namespace
bool retreat_value_cache_get(int st, const Body& b, int tp, float& v)
{
	if (b.slot < 0 || b.slot >= 8)
		return false;
	const EchM& m = ech[b.slot];
	if (m.st != st || m.rd != W.round || m.h != b.h || m.p != b.pos || m.tp != tp)
		return false;
	v = m.v;
	return true;
}
void retreat_value_cache_put(int st, const Body& b, int tp, float v)
{
	if (b.slot < 0 || b.slot >= 8)
		return;
	EchM& m = ech[b.slot];
	m.st = st;
	m.rd = W.round;
	m.h = b.h;
	m.p = b.pos;
	m.tp = tp;
	m.v = v;
}
} // namespace nova::combat::retreating_mates
