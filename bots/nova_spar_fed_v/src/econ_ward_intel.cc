// econ_ward_intel.cc: What our wards tell the economy about groups.
#include "econ_internal.h"
namespace nova::econ {
namespace {

// A capture or clear at this group is probably ours: our target, a teammate's claim, or a visible ally next to it.
bool capture_or_clear_is_ours(int gi)
{
	if (gi == T.target)
		return true;
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
		if (s != P.my_slot && comms::cgroup(s) == gi)
			return true;
	const vec2 a = M.groups[static_cast<std::size_t>(gi)].anchor;
	for (const auto& al : W.allies)
		if (cheb(al.pos, a) <= 4)
			return true;
	return false;
}
// My own engagement with a group outranks a teammate's report about it.
bool busy_with_group(int gi)
{
	return gi == T.target &&
		(T.capturing || T.engaged || cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor) <= 8);
}
std::vector<Attacker> living_attackers(int gi, bool assume_all)
{
	std::vector<Attacker> out;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (!c.attacks())
			continue;
		const bool visible = bbget(W.vis, c.pos);
		const bool alive = visible ? bbget(W.occ_camps, c.pos) : assume_all;
		if (alive)
			out.push_back({ c.pos, c.reach, c.str, ci });
	}
	return out;
}
// living_attackers(gi, assume_all) written into `out` in place. The attacking members of each group (static camp data, member order)
// are listed once; the visibility / alive test per member is living_attackers' own.
void living_attackers_fill(std::vector<Attacker>& out, int gi, bool assume_all)
{
	static std::vector<std::vector<Attacker>> sa;
	static std::vector<char> sa_ok;
	if (sa.size() != static_cast<std::size_t>(M.ng))
	{
		sa.assign(static_cast<std::size_t>(M.ng), {});
		sa_ok.assign(static_cast<std::size_t>(M.ng), 0);
	}
	const std::size_t g = static_cast<std::size_t>(gi);
	if (!sa_ok[g])
	{
		for (int ci : M.groups[g].members)
		{
			const auto& c = M.camps[static_cast<std::size_t>(ci)];
			if (c.attacks())
				sa[g].push_back({ c.pos, c.reach, c.str, ci });
		}
		sa_ok[g] = 1;
	}
	const auto& src = sa[g];
	// Written through a raw pointer into storage at least src.size() long, then cut to the count (no per-element push_back).
	if (out.size() < src.size())
		out.resize(src.size());
	Attacker* w = out.data();
	std::size_t n = 0;
	for (const auto& a : src)
	{
		const bool visible = bbget(W.vis, a.pos);
		const bool alive = visible ? bbget(W.occ_camps, a.pos) : assume_all;
		if (alive)
			w[n++] = a;
	}
	out.resize(n);
}
// living_attackers is computed once per (group, assume_all) and perceive (it reads static camp data, W.vis and W.occ_camps, all set
// in perceive). The storage is sized once and a slot is rewritten only on a new perceive, so a reference held within the turn stays
// valid. When the cache is off, the caller's own copy is used.
const std::vector<Attacker>& living_attackers_cached(int gi, bool assume_all, std::vector<Attacker>& tmp)
{
	static std::vector<std::vector<Attacker>> la;
	static std::vector<int> la_st;
	const std::size_t n2 = 2 * static_cast<std::size_t>(M.ng);
	if (la.size() != n2)
	{
		la.assign(n2, {});
		la_st.assign(n2, -1);
	}
	const std::size_t k = 2 * static_cast<std::size_t>(gi) + (assume_all ? 1 : 0);
	if (k >= n2)
	{
		tmp = living_attackers(gi, assume_all);
		return tmp;
	}
	if (la_st[k] != fg::pstamp)
	{
		living_attackers_fill(la[k], gi, assume_all);
		la_st[k] = fg::pstamp;
	}
	return la[k];
}
// The first early-out test is inline at the call site (saves a call and frame per turn); the rest is out of line.
__attribute__((always_inline)) bool group_awake(int gi)
{
	if (M.groups[static_cast<std::size_t>(gi)].n_att == 0)
		return false;
	return group_awake_slow(gi);
}
__attribute__((noinline)) bool group_awake_slow(int gi)
{
	// no attacking member -> never awake; else once per (group, perceive).
	if (M.groups[static_cast<std::size_t>(gi)].n_att == 0)
		return false;
	static std::vector<int> ga_st;
	static std::vector<std::uint8_t> ga_v;
	if (ga_st.size() != static_cast<std::size_t>(M.ng))
	{
		ga_st.assign(static_cast<std::size_t>(M.ng), -1);
		ga_v.assign(static_cast<std::size_t>(M.ng), 0);
	}
	const std::size_t k = static_cast<std::size_t>(gi);
	if (ga_st[k] != fg::pstamp)
	{
		ga_v[k] = group_awake_raw(gi) ? 1 : 0;
		ga_st[k] = fg::pstamp;
	}
	return ga_v[k] != 0;
}
bool group_awake_raw(int gi)
{
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const VisCamp* vc = visible_camp(ci);
		if (vc && vc->awake && M.camps[static_cast<std::size_t>(ci)].attacks())
			return true;
	}
	return false;
}
// A big group (hoards, dominant groups: 100+ members, 3-6k a call) is counted with word popcounts over a member-tile mask built once
// per group: the members' tiles are distinct, so the counts equal the member loop's.
bool living_members_popcount(int gi, int& alive, int& inv)
{
	const auto& mem = M.groups[static_cast<std::size_t>(gi)].members;
	if (!NOVA_GDIRECT || mem.size() < 48)
		return false;
	static std::vector<std::vector<std::uint64_t>> mask;
	static std::vector<signed char> ok; // 0 unbuilt, 1 usable, -1 not (a member off the board)
	if (mask.size() != static_cast<std::size_t>(M.ng))
	{
		mask.assign(static_cast<std::size_t>(M.ng), {});
		ok.assign(static_cast<std::size_t>(M.ng), 0);
	}
	const std::size_t g = static_cast<std::size_t>(gi);
	const int n = G.ch * G.stride;
	if (n <= 0)
		return false;
	if (ok[g] == 0)
	{
		ok[g] = 1;
		mask[g].assign(static_cast<std::size_t>(n), 0);
		for (int ci : mem)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			const int k = (p.y >> 3) * G.stride + (p.x >> 3);
			if (!inb(p) || k < 0 || k >= n)
			{
				ok[g] = -1;
				break;
			}
			mask[g][static_cast<std::size_t>(k)] |= std::uint64_t{ 1 } << (((p.y & 7) << 3) | (p.x & 7));
		}
	}
	if (ok[g] < 0 || static_cast<int>(mask[g].size()) != n)
		return false;
	const std::uint64_t* v = W.vis.ptr();
	const std::uint64_t* o = W.occ_camps.ptr();
	const std::uint64_t* m = mask[g].data();
	int seen = 0, al = 0;
	// only the mask's nonzero words (the same counts; hoard maps have many 48+ member groups x the board).
	static std::vector<std::vector<int>> nz;
	static std::vector<signed char> nz_ok;
	if (nz.size() != static_cast<std::size_t>(M.ng))
	{
		nz.assign(static_cast<std::size_t>(M.ng), {});
		nz_ok.assign(static_cast<std::size_t>(M.ng), 0);
	}
	if (!nz_ok[g])
	{
		nz_ok[g] = 1;
		for (int i = 0; i < n; ++i)
			if (m[i])
				nz[g].push_back(i);
	}
	for (int i : nz[g])
	{
		if (i < 0 || i >= n)
			continue;
		const std::uint64_t vm = v[i] & m[i];
		if (vm)
		{
			seen += __builtin_popcountll(vm);
			al += __builtin_popcountll(vm & o[i]);
		}
	}
	alive = al;
	inv = static_cast<int>(mem.size()) - seen;
	return true;
}
// once per (group, perceive): W.vis and W.occ_camps change only in perceive.
int living_members_visible(int gi, int* invisible)
{
	if (gi >= 0 && static_cast<std::size_t>(gi) < hf_st.size() && hf_st[static_cast<std::size_t>(gi)] == fg::pstamp)
	{
		if (invisible)
			*invisible = hf_inv[static_cast<std::size_t>(gi)];
		return hf_alive[static_cast<std::size_t>(gi)];
	}
	struct Memo
	{
		int st, gi, alive, inv;
	};
	static std::array<Memo, 8> memo{};
	static int nm = 0, st_cur = -1;
	if (st_cur != fg::pstamp)
	{
		st_cur = fg::pstamp;
		nm = 0;
	}
	for (int k = 0; k < nm; ++k)
	{
		const Memo& m = memo[static_cast<std::size_t>(k)];
		if (m.gi == gi)
		{
			if (invisible)
				*invisible = m.inv;
			return m.alive;
		}
	}
	int inv = 0;
	int alive = 0;
	if (!living_members_popcount(gi, alive, inv))
		alive = living_members_visible_raw(gi, &inv);
	if (nm < 8)
		memo[static_cast<std::size_t>(nm++)] = { fg::pstamp, gi, alive, inv };
	if (invisible)
		*invisible = inv;
	return alive;
}
int living_members_visible_raw(int gi, int* invisible)
{
	int alive = 0, inv = 0;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (!bbget(W.vis, p))
			++inv;
		else if (bbget(W.occ_camps, p))
			++alive;
	}
	if (invisible)
		*invisible = inv;
	return alive;
}
// Engine state of a group while any member tile is in vision: 1 alive, 2 reward available, 3 respawning, 0 unknown.
int group_state_now(int gi)
{
	std::uint32_t st = 0;
	if (cambc::detail::sdk_camp_group_state(M.groups[static_cast<std::size_t>(gi)].handle, &st) != 0)
		return 0;
	return st <= 3 ? static_cast<int>(st) : 0;
}
const std::vector<FbAw>& awake_attacking_camps()
{
	static std::vector<FbAw> aw;
	static int st = -1;
	if (st != fg::pstamp)
	{
		st = fg::pstamp;
		aw.clear();
		for (const auto& vc : W.camps)
		{
			if (vc.ci < 0 || vc.ci >= M.nc)
				continue;
			const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
			if (vc.awake && c.attacks())
				aw.push_back({ c.pos, c.reach, c.str, c.group });
		}
	}
	return aw;
}
// Camp damage I would take at the next round start, and the attackers in reach of me.
float incoming_at(vec2 p, std::vector<mv::Threat>* th)
{
	float incoming = 0;
	if (th)
		for (const auto& c : awake_attacking_camps())
			if (cheb(p, c.pos) <= c.reach)
				th->push_back({ c.pos, c.reach });
	incoming = mv::camp_threat(p);
	refresh_owned();
	if (mu::on(mu::B_CTH)) // camp_threat already carries it
		;
	else if (mu::on(mu::B_CAMP)) // Durability x Jungle
		incoming *= mu::my_camp(mu::IN);
	else if (own.jungle)
		incoming *= mu::rule(mu::own_fam(true, false, false), mu::CAMP, mu::IN);
	return incoming;
}
// damage per round my crew puts on the awake attackers in reach of me (th), counting the passives: Varg's splash over those
// attackers weighted by their health, Ren's retaliation from each one that hits him; Heart of Ruin's bonus at its current health is
// in its member numbers. *hp_left receives their health.
float threat_kill_dps(const Crew& crew, const std::vector<mv::Threat>& th, float* hp_left, bool mem_hp = false)
{
	float left = 0, mx = 1.0f;
	int hits_me = 0;
	for (const auto& t : th)
	{
		const int ci = M.camp_index(t.pos);
		const VisCamp* vc = ci >= 0 ? visible_camp(ci) : nullptr;
		float h = vc ? vc->hp : 1000.0f;
		if (mem_hp && !vc && ci >= 0) // an unseen camp at its group's remembered living health, at most its own
		{
			const auto& c = M.camps[static_cast<std::size_t>(ci)];
			const float gl = mem[static_cast<std::size_t>(c.group)].hp_left;
			h = gl >= 0 ? std::min(c.hp, gl) : c.hp;
		}
		left += h;
		mx = std::max(mx, h);
		bool nearer = false; // a camp hits its nearest champion
		for (const auto& al : W.allies)
			nearer |= cheb(al.pos, t.pos) < cheb(W.me.pos, t.pos);
		hits_me += nearer ? 0 : 1;
	}
	*hp_left = left;
	float dps = crew.dps(1);
	if (W.me.kit->splash && th.size() >= 2)
		dps = crew.dpsf(std::min(static_cast<float>(th.size()), left / mx));
	if (W.me.kit->retaliation)
		dps += ren_layer::retaliation_damage(W.me.foc) * ((mu::on(mu::B_CAMP)) ? mu::my_camp(mu::OUT) : mu::rule(mu::own_fam(false, false, own.monster), mu::CAMP, mu::OUT)) * static_cast<float>(hits_me);
	(void)hits_me;
	return std::max(30.0f, dps);
}
} // namespace
bool mate_claims_group_recently(int gi, int round)
{
	if (now() - round > CNW_TAB[2])
		return false;
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
		if (s != P.my_slot && comms::cgroup(s) == gi)
			return true;
	return false;
}
bool group_is_ours_to_post(int gi)
{
	return gi == T.target || mate_claims_group_recently(gi, now());
}
} // namespace nova::econ
