// probe 24 (5 Nov): fuel_remaining across a turn's fuel slices. On the draft turns and the first 3 champion turns (the
// double-fuel round 1 and two normal turns) it burns fuel in fixed chunks and prints fuel_remaining after every chunk until
// little is left; ehtest.py --probe probe24 compares every line with the CLI. Written after cxe v the CLI diverged from round 1
// on fm_e84652_79 (cxeverify: 'multi-slice first turn' fuel gaps that changed play).
#include <cambc.h>
#include <cstdio>
#include <unistd.h>
#include "draft.h"
static volatile unsigned sink;
static void burn(int n) { unsigned s = sink; for (int i = 0; i < n; i++) s = s * 1103515245u + 12345u; sink = s; }
static void trace(const char* tag, int turn, long stop_at, int chunk) {
    char out[96];
    long prev = (long)cambc::fuel_remaining();
    int m = snprintf(out, sizeof out, "T %s %d start %ld\n", tag, turn, prev);
    write(1, out, m);
    for (int k = 0; k < 400; k++) {
        burn(chunk);
        long f = (long)cambc::fuel_remaining();
        m = snprintf(out, sizeof out, "T %s %d k %d f %ld d %ld\n", tag, turn, k, f, prev - f);
        write(1, out, m);
        prev = f;
        if (f < stop_at) break;
    }
}
int main() {
    int turn = 0, dturn = 0;
    while (true) {
        if (cambc::is_draft()) {
            ++dturn;
            if (dturn <= 2) trace("draft", dturn, dturn == 1 ? 9700000 : 30000, dturn == 1 ? 20000 : 2000);
            play_draft();
            cambc::end_turn();
            continue;
        }
        ++turn;
        if (turn <= 3) trace("turn", turn, 15000, 2000);
        cambc::end_turn();
    }
}
