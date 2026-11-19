// econ_travel.cc: Walk cost to groups: gated, recall and stored travel.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// compute_travel's state for the stored walks (decided once per call, before the group loop)
struct XtTr
{
	int v = 0; // XT_V at the call (0 = off: nothing below runs)
	int cg = -1; // bit 1: the group whose camp tile I stand on
	int a[3] = { -1, -1, -1 }; // bit 2: the 3 nearest groups whose fields read my tile (nearest first)
	std::uint16_t av[3] = { UNREACH, UNREACH, UNREACH };
	int hd = -1; // bit 2: my home walk (camps passable), when <= XT_NEAR
	int nr = 8; // XT_NEAR at the call
	std::vector<int> pend; // bit 2: groups with no field value
	int fired_cg = 0, fired_near = 0; // diag counts (no output)
	int kind = 0;       // the last pending estimate's source (0 Chebyshev, 2 bound near an anchor, 4 clamped)
	const std::uint16_t* D = nullptr; // the dense tables (plan files), read directly: one load per pair
	const std::uint16_t* S = nullptr;
	const std::uint8_t* DER = nullptr;
	int n = 0;
	const std::uint16_t* row = nullptr; // bit 1: D's row of the camp-tile group
};
XtTr xtt;
bool travel_gdn = false; // the travel table was read from a camp tile's neighbours
// starved-map explore flag: its bits apply on a starved map with dash-only gems; 0 = no work.
static int stv_c = -1;
} // namespace
} // namespace nova::econ
