// probe 25 (5 Nov): host fuel charges that straddle a fuel slice boundary. The CLI gives a big turn (the 10M first draft turn,
// the 200k round-1 turn) its fuel in 100k slices; cxe v the CLI diverged from round 1 on fm_e84652_79 with cxe 197 fuel over.
// Draft turn 1: for slice boundaries k = 1..40 it burns down to `k * 3` fuel above the boundary, then makes one host call
// (Bitboard_Zero, 49 fuel; every 4th k a whole-map DrawChebyshev) and prints the call's measured cost. Champion turn 1 does
// the same at its one boundary (100,000 left). ehtest.py --probe probe25 compares every line with the CLI.
#include <cambc.h>
#include <cstdio>
#include <unistd.h>
#include "draft.h"
static volatile unsigned sink;
static void burn_to(long target) { unsigned s = sink; while ((long)cambc::fuel_remaining() > target) for (int i = 0; i < 2; i++) s = s * 1103515245u + 12345u; sink = s; }
static void one(const char* tag, int k, long boundary, long off, int big) {
    cambc::bitboard b;
    burn_to(boundary + off);
    long pre = (long)cambc::fuel_remaining();
    if (big) cambc::detail::sdk_Bitboard_DrawChebyshev(b.ptr(), 0, 0, 1000.0f);
    else cambc::detail::sdk_Bitboard_Zero(b.ptr());
    long post = (long)cambc::fuel_remaining();
    char out[128];
    int m = snprintf(out, sizeof out, "T %s k %d above %ld big %d cost %ld post_above %ld\n", tag, k, pre - boundary, big, pre - post, post - boundary);
    write(1, out, m);
}
int main() {
    int turn = 0, dturn = 0;
    while (true) {
        if (cambc::is_draft()) {
            if (++dturn == 1) {
                long f0 = (long)cambc::fuel_remaining(), top = f0 / 100000 * 100000;  // boundaries counted from the turn's budget
                for (int k = 1; k <= 40; k++) one("draft", k, top - (long)k * 100000, k * 3, k % 4 == 0);
            }
            play_draft();
            cambc::end_turn();
            continue;
        }
        if (++turn == 1)
            for (int k = 0; k < 1; k++) one("turn1", k, 100000, 20, 0);
        cambc::end_turn();
    }
}
