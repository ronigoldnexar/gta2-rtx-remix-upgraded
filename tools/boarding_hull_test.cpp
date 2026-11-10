// Build: g++ -std=c++17 -I dll/src -include cstdint tools/boarding_hull_test.cpp dll/src/boarding.cpp <a Log stub> -o /tmp/hull_test
// FIX-ACTIONS-3 offline check: a boarding ped the game walks straight through a parked car's body
// (pfl15's path, car frame) must be drawn round its end, never inside the hull.
#include <cmath>
#include <cstdio>
#include "boarding.h"
using namespace gta2dx9;
int main() {
    gta2::Mat4 m{}; // car facing -x (west), at (164.26, 0, 105.10): rows x across, y up, z forward
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) m.m[i][j] = 0;
    // forward (z row) = (-1,0,0); across (x row) = (0,0,1)... right-handed enough for the test
    m.m[0][0] = 0; m.m[0][2] = 1; m.m[1][1] = 1; m.m[2][0] = -1; m.m[2][2] = 0;
    m.m[3][0] = 164.26f; m.m[3][1] = 2.0f; m.m[3][2] = 105.10f; m.m[3][3] = 1;
    const float halfW = 0.21f, zf = 0.15f, zr = zf - 0.27f;   // a 1-block body
    int bad = 0, detoured = 0;
    // pfl15: (164.80,150.13) -> (164.25,150.70) in game x,y; renderer z = 255.55 - y
    const int N = 40;
    // path 0: pfl15 (rear quarter to the far side); path 1: fix3 (at the nose, to the far side's door)
    const float P[2][4] = {{164.80f, 150.13f, 164.25f, 150.70f}, {163.62f, 150.43f, 164.06f, 150.84f}};
    for (int path = 0; path < 2; ++path)
    for (int f = 0; f <= N; ++f) {
        const uint32_t now = 100 + path * 200 + f;
        BoardingPublishCar(1, m, halfW, zf, zr, 0.35f, 1, 0.0f, now);
        const float k = static_cast<float>(f) / N;
        const float gx = P[path][0] + (P[path][2] - P[path][0]) * k, gy = P[path][1] + (P[path][3] - P[path][1]) * k;
        BoardingIn in; in.ped = 7 + path; in.state = 3; in.sub = 4; in.frame = 12; in.gameX = gx; in.gameZ = 255.55f - gy; in.groundY = 2.0f;
        in.drawnX = in.gameX; in.drawnZ = in.gameZ; in.heading = 0; in.now = now; in.dt = 1.0f / 30.0f; in.jacking = true; in.driverIn = true;
        BoardingOut out;
        const bool on = BoardingUpdate(in, &out);
        const float px = on ? out.x : in.drawnX, pz = on ? out.z : in.drawnZ;
        // car frame
        const float dx = px - 164.26f, dz = pz - 105.10f;
        const float u = dz, along = -dx;   // x row (0,0,1), z row (-1,0,0)
        const bool inside = std::fabs(u) < halfW && std::fabs(along) < 0.5f * (zf - zr) / 0.27f;
        if (on) ++detoured;
        if (inside) ++bad;
        printf("p%d f%02d game u=%+.3f along=%+.3f -> drawn u=%+.3f along=%+.3f %s%s\n", path, f, (in.gameZ - 105.10f), -(in.gameX - 164.26f), u, along,
               on ? "detour" : "", inside ? " INSIDE THE HULL" : "");
    }
    printf("frames inside the hull: %d, detoured: %d\n", bad, detoured);
    return bad ? 1 : 0;
}
