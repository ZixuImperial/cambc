// champ_ci.cc: C&I LAYER, Cassi & Issac's rules (hooks and flags: champ_ci.h). Holds the pair link (linked_slot, linked_bag,
// cassi_issac_partner_slot, cassi_issac_map_link_wanted, cassi_issac_link_on), adoption (cassi_adopt_issac_group, with econ's CI_SHARED), the linked step, the linked stun
// (fight_linked_stun), CI_SAFE (the stance rule, and cassi_issac_pair_holds for the contested hold) and the linked ranged body's melee gap.
// Unity build: one translation unit, so combat's helpers are in scope.
#include "combat.h"
#include "champions.h"
// C&I layer: Cassi and Issac
namespace nova::combat {
namespace stance {
namespace {
// ---- STANCE: CI_SAFE, the pair fights only together, healthy and ahead CI_SAFE (owner rule): one death takes both bodies and both
// bags, and the pair died apart (median 10 tiles at death) about 4 times a game in local games. The pair fights only together,
// healthy and clearly ahead; otherwise it leaves (the REACT retreat rallies on the nearest ally, the partner when it is close). A
// kill this turn still goes ahead.
static __attribute__((always_inline)) inline void assess_rule_ci_safe(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FLEE || a.nearest > CI_SAFE_NEAR || c.kill_now)
		return;
	const int ls = linked_slot();
	if (ls < 0)
		return;
	const Body* pb = W.ally_by_slot(ls);
	const int gap = pb ? cheb(pb->pos, c.me) : 99;
	const float lo = std::min(W.me.frac(), pb ? pb->frac() : W.me.frac());
	const bool apart = gap > CI_SAFE_GAP; // CIR bit 512, read first
	const bool hurt = lo < ((gap <= CI_GAP) ? static_cast<float>(CI_SAFE_LHP_X100) / 100.0f : CI_SAFE_HP); // linked bodies use the lower-HP bar
	const bool unsure = a.stance == FIGHT && assess_worst_ratio(a) < CI_SAFE_RATIO;
	if (apart || hurt || unsure)
		a.stance = FLEE;
}
// ---- STANCE: a linked ranged body keeps CI_MELEE_GAP from melee while its stun is down
static __attribute__((always_inline)) inline void assess_rule_ci_melee_gap(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FLEE || c.kill_now || !W.me.kit->ranged || linked_slot() < 0 || (W.me.kit->slot_cc >= 0 && ready(W.me.kit->slot_cc)))
		return;
	for (const auto& e : W.enemies)
		if (e.kit && !e.kit->ranged && cheb(e.pos, c.me) <= ci_layer::CI_MELEE_GAP)
		{
			a.stance = FLEE;
			break;
		}
}
} // namespace
} // namespace stance
} // namespace nova::combat
namespace nova::combat {
namespace fight_turn {
namespace {
// ---- FIGHT: the linked stun (CI_COMBO) A linked Cassi stuns the stunnable foe nearest Issac (within his dash reach) so his dash
// and reset land on a body that cannot answer. It is the focus when it qualifies.
static __attribute__((always_inline)) inline const Body* fight_linked_stun(const FightCtx& c)
{
	if (!ci_layer::me_cassi() || !cassi_issac_link_on())
		return nullptr;
	const int ls = cassi_issac_partner_slot();
	const Body* pb = ls >= 0 ? W.ally_by_slot(ls) : nullptr;
	if (!pb || cheb(pb->pos, W.me.pos) > CI_LINK_R)
		return nullptr;
	const Body* st = nullptr;
	int bd = tune::LINK_STUN_BOUND;
	for (const auto& e : W.enemies)
	{
		if (!fight_stunnable(e) || cheb(e.pos, W.me.pos) > c.cc_r)
			continue;
		const int de = cheb(e.pos, pb->pos) - (e.h == c.f.h ? 1 : 0);
		if (de < bd)
		{
			bd = de;
			st = &e;
		}
	}
	return st;
}
} // namespace
} // namespace fight_turn
} // namespace nova::combat
namespace nova::combat {
// ---- LINK: my linked body
int linked_slot()
{
	static int cached = -2;
	if (cached != -2)
		return cached;
	if (P.n <= 0 || P.my_slot < 0)
		return -1;
	using C = cambc::champion_type;
	const C mine = P.type[static_cast<std::size_t>(P.my_slot)];
	cached = -1;
	if (mine != C::cassi && mine != C::issac)
		return cached;
	const C want = mine == C::cassi ? C::issac : C::cassi;
	for (int i = 0; i < P.n; ++i)
		if (P.type[static_cast<std::size_t>(i)] == want)
			cached = i;
	return cached;
}
// ---- LINK: the pair bag
int linked_bag()
{
	int g = static_cast<int>(W.me.gems);
	const int s = linked_slot();
	if (s < 0)
		return g;
	std::uint32_t pg = 0;
	if (cambc::detail::sdk_champion_gems(P.handle[static_cast<std::size_t>(s)], &pg) == 0)
		g += static_cast<int>(pg);
	return g;
}
// ---- LINK: the partner while it lives
int cassi_issac_partner_slot()
{
	static int r = -1, v = -1;
	if (r == W.round)
		return v;
	r = W.round;
	v = -1;
	const int s = linked_slot();
	if (s < 0 || s >= P.n || s >= 8 || !W.alive)
		return v;
	if (W.ally_by_slot(s))
		return v = s;
	std::int32_t alive = 0;
	if (cambc::detail::sdk_champion_is_alive(P.handle[static_cast<std::size_t>(s)], &alive) == 0 && alive != 0)
		v = s;
	return v;
}
// ---- LINK: the link state this round
bool cassi_issac_link_on()
{
	return false;
}
// ---- TARGETS: CI_SHARED, Cassi adopts Issac's group
int cassi_adopt_issac_group()
{
	return -1; // CI2 farms the pair itself (CI2_FARM_ON)
}
// ---- LINK: the linked step, off since CI2 (the link is off: cassi_issac_link_on)
__attribute__((always_inline)) bool cassi_issac_link_step(const Assessment&)
{
	return false;
}
} // namespace nova::combat
namespace nova::combat {
// ---- CI_SAFE in a contested hold (mates::contested_gem_hold): the linked pair holds only together and healthy
__attribute__((always_inline)) bool cassi_issac_pair_holds()
{
	const int ls = linked_slot();
	if (ls >= 0)
	{
		const Body* pb = W.ally_by_slot(ls);
		const float hp_bar = (pb && cheb(pb->pos, W.me.pos) <= CI_GAP) ? static_cast<float>(CI_SAFE_LHP_X100) / 100.0f : CI_SAFE_HP; // a close pair uses the lower-HP bar
		if (!pb || cheb(pb->pos, W.me.pos) > CI_SAFE_GAP || std::min(W.me.frac(), pb->frac()) < hp_bar)
			return false;
	}
	return true;
}
} // namespace nova::combat

// ---------------------------------------------------------------- Cassi and Issac fight weights The three C&I fight weights
// (champ_ci.h). Unity build: combat_*.cc and champ_ci.cc come first, so their helpers are in scope. Only reached when CIF_ON(...) is
// true at the hook.
namespace nova::ci::fight_weights
{
namespace
{
using nova::combat::eff_hp;
// Her Focus share of shard-bought stats (GameRules: Cassi 600/65 HP, 30/3 Str, 100/13 Focus), at least 8 shards counted, so
// it is small early and near 1 for a late Focus build.
float focus_share()
{
	const float fs = std::max(0.0f, (W.me.foc - 100.0f) / 13.0f);
	const float hs = std::max(0.0f, (W.me.maxhp - 600.0f) / 65.0f);
	const float ss = std::max(0.0f, (W.me.str - 30.0f) / 3.0f);
	return fs / std::max(8.0f, fs + hs + ss);
}
bool ranged_body(const Body& e) { return e.kit ? e.kit->ranged : e.range > 1; }
// Expected hits on tile t next round from ranged foes whose basic range covers t (GameRules.md:254, ranged range 3).
float ranged_loss(vec2 t)
{
	float s = 0;
	for (const auto& e : W.enemies)
	{
		if (!ranged_body(e) || e.stunned)
			continue;
		const int de = cheb(e.pos, t);
		if (de <= e.range)
			s += nova::combat::burst::lethal_burst_hit(e, de, 0, nullptr);
	}
	return s;
}
// A1: Cassi's walk-in. 0 = walk as before, 1 = hold, 2 = stepped to spell range.
int cassi_walk_in(const Body& f, int d)
{
	bool any = false;
	for (const auto& e : W.enemies)
		any = any || (ranged_body(e) && cheb(e.pos, W.me.pos) <= e.range + 3);
	if (!any)
		return 0;
	// the walk-in's own step: the free neighbour nearest the focus, least exposed on a tie
	vec2 tin{ -1, -1 };
	int tin_d = d;
	float tin_l = 0;
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (!inb(t) || !mv::free_tile(t))
			continue;
		const int nd = cheb(t, f.pos);
		if (nd > tin_d)
			continue;
		const float l = ranged_loss(t);
		if (nd < tin_d || (tin.x >= 0 && l < tin_l))
		{
			tin = t;
			tin_d = nd;
			tin_l = l;
		}
	}
	if (tin.x < 0 || tin_l <= 0)
		return 0; // no step, or the step enters no ranged reach
	const float cost = static_cast<float>(CIF_TAB[3]) / 100.0f * tin_l / std::max(1.0f, eff_hp(W.me));
	const float gain = tin_d <= W.me.range ? W.me.str / std::max(1.0f, eff_hp(f)) : 0.0f;
	if (gain >= cost && tin_d <= W.me.range)
		return 0;
	if (tin_d > W.me.range && tin_d >= 4)
		return 0; // the step still ends at or beyond spell range: no hit at stake yet, walk on
	// hold at spell range: step to a free tile at 4 from the focus outside every ranged reach, if one is a step away
	const int sr = 4;
	vec2 best{ -1, -1 };
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (!inb(t) || !mv::free_tile(t) || cheb(t, f.pos) != sr || ranged_loss(t) > 0)
			continue;
		best = t;
		break;
	}
	if (d > sr && best.x >= 0 && mv::try_move(best))
		return 2;
	return 1;
}
// P2: Issac between Cassi and her threat. 0 = no change, 1 = hold, 2 = stepped.
int issac_guard_step(const Body& f, int d)
{
	const int ls = nova::combat::cassi_issac_partner_slot();
	const Body* cb = ls >= 0 ? W.ally_by_slot(ls) : nullptr;
	if (!cb || cheb(cb->pos, W.me.pos) > CI_LINK_R)
		return 0;
	const float hpw = std::min(1.0f, std::max(0.0f, (W.me.frac() - 0.35f) / 0.30f)); // low HP: no guard weight (the flee dashes)
	if (hpw <= 0)
		return 0;
	const Body* th = nullptr;
	int thd = 99;
	for (const auto& e : W.enemies)
	{
		const int de = cheb(e.pos, cb->pos);
		if (de <= std::max(1, e.range) + 2 && de < thd)
		{
			thd = de;
			th = &e;
		}
	}
	if (!th || thd <= 1)
		return 0; // nothing near her, or it already stands at her side: the walk-in goes at it
	const vec2 g{ cb->pos.x + (th->pos.x > cb->pos.x) - (th->pos.x < cb->pos.x), cb->pos.y + (th->pos.y > cb->pos.y) - (th->pos.y < cb->pos.y) };
	const float wg = static_cast<float>(CIF_TAB[4]) / 100.0f * hpw;
	auto score = [&](vec2 t) { return static_cast<float>(std::max(0, cheb(t, f.pos) - W.me.range)) + wg * static_cast<float>(cheb(t, g)); };
	const float here = score(W.me.pos);
	vec2 best{ -1, -1 };
	float bs = here;
	float bwalk = 1e9f; // the plain walk-in's best progress score, to see whether the guard changed the choice
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (!inb(t) || !mv::free_tile(t))
			continue;
		const float s = score(t);
		bwalk = std::min(bwalk, static_cast<float>(std::max(0, cheb(t, f.pos) - W.me.range)));
		if (s < bs)
		{
			bs = s;
			best = t;
		}
	}
	(void)d;
	if (best.x >= 0)
	{
		if (static_cast<float>(std::max(0, cheb(best, f.pos) - W.me.range)) <= bwalk)
			return 0; // the guard step is also a best walk-in step: leave the walk to the walk-in
		return mv::try_move(best) ? 2 : 0;
	}
	return bwalk < static_cast<float>(std::max(0, d - W.me.range)) ? 1 : 0; // staying guards better than any walk-in step
}
} // namespace
int walk(const nova::combat::Assessment& a, const Body& f, int d)
{
	(void)a;
	if (nova::ci_layer::me_cassi())
		return cassi_walk_in(f, d);
	if (nova::ci_layer::me_issac())
		return issac_guard_step(f, d);
	return 0;
}
} // namespace nova::ci::fight_weights

// ---------------------------------------------------------------- Cassi and Issac builds and roles C&I builds, camp roles and
// escort. Unity build: compiled only through nova_all.cpp, after econ_*.cc, combat_*.cc and champ_ci.cc, whose helpers are in scope.
// Only reached when CIR_ON(...) is true at the hook.
namespace nova::ci::builds
{
namespace
{
constexpr int CIR_ST = 0, CIR_FO = 1, CIR_HP = 2;
constexpr float CIR_S1 = 1.2f;     // S1: Cassi's bar scale
} // namespace
void build_pass()
{
	namespace E = nova::econ;
	auto& b = E::build;
	if (ci_layer::me_issac() ? !true : !false)
		return;
	// Loose shards already held keep their entry (no stranded shards): taken out here, put back first, pinned with mine.
	std::vector<cambc::item_type> part;
	{
		FxmItems counts;
		my_item_counts(counts);
		for (std::size_t i = 0; i < b.size();)
		{
			const std::uint32_t id = static_cast<std::uint32_t>(b[i]);
			const std::uint32_t n = id < counts.v.size() ? counts.v[id] : 0u;
			if (n > 0u && n < 5u && std::find(part.begin(), part.end(), b[i]) == part.end())
			{
				part.push_back(b[i]);
				b.erase(b.begin() + static_cast<std::ptrdiff_t>(i));
			}
			else
				++i;
		}
	}
	int pin = 0;
	struct Fin
	{
		std::vector<cambc::item_type>& b;
		std::vector<cambc::item_type>& part;
		int& pin;
		~Fin()
		{
			b.insert(b.begin(), part.begin(), part.end());
			nova::econ::kbd_pin = pin + static_cast<int>(part.size()); // emblem_rank leaves the pinned front alone
		}
	} fin{ b, part, pin };
	auto drop = [&b](int fam) {
		for (std::size_t i = 0; i < b.size();)
			if (E::itm_family(b[i]) == fam)
				b.erase(b.begin() + static_cast<std::ptrdiff_t>(i));
			else
				++i;
	};
	if (ci_layer::me_issac())
	{
		// Bit 32: Issac's spells use no Focus and a shard adds 80 Health against 3 Strength, so he builds all Health, Durability first.
		for (auto& t : b)
			t = E::itm_shard(E::itm_family(t), CIR_HP);
		drop(E::I_DURABILITY);
		b.insert(b.begin(), E::itm_shard(E::I_DURABILITY, CIR_HP));
		pin = 1;
		return;
	}
	if (!ci_layer::me_cassi())
		return;
}
int issac_tie(int want)
{
	const int ls = combat::cassi_issac_partner_slot();
	const Body* pb = ls >= 0 ? W.ally_by_slot(ls) : nullptr;
	if (!pb || cheb(pb->pos, W.me.pos) > 4 || W.me.frac() < 0.3f)
		return want;
	if (mv::camp_threat(W.me.pos) <= 0 && mv::camp_threat(pb->pos) <= 0)
		return want;
	return std::max(want, mv::tie_prio(ls) + 1);
}
void bars(float& engage, float& flee)
{
	float m = 1.0f;
	if (ci_layer::me_cassi())
		m = CIR_S1;
	engage *= m;
	flee *= m;
}
} // namespace nova::ci::builds

// ---- FIGHT: the linked pair in combat
namespace nova::combat {
namespace pair
{
// The foe a ready spell alone kills from here, the biggest bag first (the killer takes it), then the lowest effective
// HP; kill_now's guards (no foe on its spawn, free_cast's retaliation guard). Area tiles keep the no-wake test. site 4: only
// the area spell on a foe beyond its range. Returns the slot, or -1.
static int pick_spell_kill_foe(int site, const Body*& out, vec2& tile)
{
	const Kit& k = *W.me.kit;
	const vec2 me = W.me.pos;
	const float sb = burst::spell_base();
	const int rad = std::max(0, static_cast<int>(k.aoe_radius));
	int slot = -1;
	out = nullptr;
	tile = { -1, -1 };
	for (const auto& e : W.enemies)
	{
		if (bbget(M.enemy_spawn, e.pos) || (ren_layer::kills_me(e)))
			continue;
		const int d = cheb(e.pos, me);
		const float h = eff_hp(e);
		const float dmg = burst::spell_on(sb, e);
		if (out && (e.gems < out->gems || (e.gems == out->gems && h >= eff_hp(*out))))
			continue;
		if (site == 4 && !(k.ranged && d > static_cast<int>(k.aoe_range)))
			continue;
		if (site == 8 && d <= W.me.range && W.can_attack() && h <= W.me.str * kit_rules::passive_mult(W.me))
			continue; // the basic hit kills it: the spell stays for fight()
		if (site == 2 && W.tributed_us + static_cast<int>(W.me.gems) >= 1000)
		{
			// A channel that already wins keeps its length: the foe's bag joins the start bag (GameRules.md:226) only if it adds at most a
			// quarter.
			const bool cbh = prism::has_family(rs::F_TRIBUTE); // my own emblem
			const int t0 = rs::tribute_rounds(static_cast<int>(W.me.gems), cbh);
			if ((rs::tribute_rounds(static_cast<int>(W.me.gems + e.gems), cbh) - t0) * 4 > t0)
				continue;
		}
		if (site != 4 && k.slot_dmg >= 0 && k.dmg_mod > 0 && ready(k.slot_dmg) && d <= static_cast<int>(k.dmg_range) && h <= k.dmg_mod * dmg)
		{
			slot = k.slot_dmg;
			out = &e;
			continue;
		}
		if (site != 4 && k.slot_cc >= 0 && k.cc_mod > 0 && ready(k.slot_cc) && d <= static_cast<int>(k.cc_range) && h <= k.cc_mod * dmg)
		{
			slot = k.slot_cc;
			out = &e;
			continue;
		}
		if (k.slot_aoe < 0 || k.aoe_mod <= 0 || !ready(k.slot_aoe) || d > static_cast<int>(k.aoe_range) + rad || h > k.aoe_mod * dmg)
			continue;
		for (int dx = -rad; dx <= rad; ++dx)
			for (int dy = -rad; dy <= rad; ++dy)
			{
				const vec2 t{ e.pos.x + dx, e.pos.y + dy };
				if (inb(t) && cheb(t, me) <= static_cast<int>(k.aoe_range) && !AreaGrid::wakes_other(t, rad, -1) && (out != &e || (dx == 0 && dy == 0)))
				{
					slot = k.slot_aoe;
					out = &e;
					tile = t;
				}
			}
	}
	return slot;
}
namespace {
} // namespace
} // namespace pair
} // namespace nova::combat
