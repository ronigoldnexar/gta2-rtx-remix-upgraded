// The visual regression harness's fixed camera: see regress_cam.h and
// docs/visual-regression.md. Off unless GTA2DX9_REGRESS_CAM names a file.
#include "regress_cam.h"

#include <windows.h>

#include <cmath>
#include <cstdio>
#include <cstring>

#include "../../src/camera.h"
#include "../../src/gta2_map.h"
#include "log.h"

namespace gta2dx9 {

bool RegressCameraOverride(gta2::Camera* camera) {
    static int checked = 0;
    static char path[MAX_PATH] = {};
    static DWORD lastRead = 0;
    static bool active = false;
    static float pose[7] = {};
    if (!checked) {
        checked = 1;
        if (!GetEnvironmentVariableA("GTA2DX9_REGRESS_CAM", path, sizeof path)) path[0] = 0;
        if (path[0]) Log("regress: fixed camera file %s", path);
    }
    if (!path[0] || !camera) return false;
    const DWORD now = GetTickCount();
    if (lastRead == 0 || now - lastRead >= 200) {
        lastRead = now;
        float p[7] = {0, 0, 0, 0, 0, 0, 0};
        bool on = false;
        if (FILE* f = fopen(path, "r")) {
            char line[256] = {};
            if (fgets(line, sizeof line, f)) {
                const int n = sscanf(line, "cam %f %f %f %f %f %f %f", &p[0], &p[1], &p[2], &p[3], &p[4], &p[5], &p[6]);
                on = n >= 6;
                if (n < 7) p[6] = 0.0f;
            }
            fclose(f);
        }
        if (on != active || (on && std::memcmp(p, pose, sizeof p) != 0)) {
            if (on) Log("regress: camera fixed at eye %.2f,%.2f,%.2f target %.2f,%.2f,%.2f fov %.1f", p[0], p[1], p[2], p[3], p[4], p[5], p[6]);
            else Log("regress: camera released");
        }
        active = on;
        if (on) std::memcpy(pose, p, sizeof p);
    }
    if (!active) return false;
    // Game (x east, y south, z level) to the renderer's (x east, y up, z north).
    const float H = static_cast<float>(gta2::kMapHeight);
    const gta2::Vec3 eye{pose[0], pose[2], H - pose[1]};
    const gta2::Vec3 at{pose[3], pose[5], H - pose[4]};
    const float dx = at.x - eye.x, dy = at.y - eye.y, dz = at.z - eye.z;
    const float flat = std::sqrt(dx * dx + dz * dz);
    camera->SetPosition(eye);
    camera->SetOrientation(std::atan2(dx, dz), std::atan2(dy, flat > 1e-4f ? flat : 1e-4f));
    camera->SetRoll(0.0f);
    if (pose[6] > 1.0f) camera->SetFovY(pose[6] * 3.14159265f / 180.0f);
    return true;
}

double RegressClock(double seconds) {
    static int frozen = -1;
    if (frozen < 0) {
        char buf[8];
        frozen = GetEnvironmentVariableA("GTA2DX9_REGRESS_CAM", buf, sizeof buf) ? 1 : 0;
        if (frozen) Log("regress: sky and water clock held at 1000 s");
    }
    return frozen ? 1000.0 : seconds;
}

}  // namespace gta2dx9
