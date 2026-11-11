// FIX-COCKPIT-BODY: the cockpit / dashcam choice at the wheel in first person (see cockpit_mode.h).
#include "cockpit_mode.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cctype>
#include <cstdlib>
#include <cstring>

#include "log.h"

namespace gta2dx9 {
namespace {

int g_key = 'C';
bool g_chosen = false;
bool g_body = true;
bool g_cowl = true;   // FIX-COCKPIT-CAB-7: [camera] dashcam_cowl
float g_up = 0.012f, g_ahead = 0.035f, g_centre = 0.6f;
bool g_keyWasDown = false;
bool g_atWheelFirst = false;
// the blend: where it was at the last press, which way it goes, when
float g_from = 0.0f;
ULONGLONG g_pressAt = 0;
constexpr float kSwitchSeconds = 0.4f;

int ParseKey(const char* name, int fallback) {
    if (!name || !name[0]) return fallback;
    if (strlen(name) == 1) return toupper(static_cast<unsigned char>(name[0]));
    if ((name[0] == 'F' || name[0] == 'f') && isdigit(static_cast<unsigned char>(name[1]))) {
        const int n = atoi(name + 1);
        if (n >= 1 && n <= 24) return VK_F1 + n - 1;
    }
    if (strncmp(name, "0x", 2) == 0 || strncmp(name, "0X", 2) == 0) return static_cast<int>(strtol(name, nullptr, 16));
    if (isdigit(static_cast<unsigned char>(name[0]))) return atoi(name);
    return fallback;
}

// the chosen look's blend, eased (smoothstep) from where the last press found it
float ChosenBlend() {
    const float to = g_chosen ? 1.0f : 0.0f;
    if (!g_pressAt) return to;
    const float t = static_cast<float>(GetTickCount64() - g_pressAt) / (1000.0f * kSwitchSeconds);
    if (t >= 1.0f) return to;
    const float s = t * t * (3.0f - 2.0f * t);
    return g_from + (to - g_from) * s;
}

}  // namespace

void CockpitModeLoad(const char* ini) {
    char buf[32] = {};
    GetPrivateProfileStringA("camera", "dashcam_key", "C", buf, sizeof buf, ini);
    g_key = ParseKey(buf, 'C');
    if (g_key <= 0 || g_key >= 256) g_key = 'C';
    g_chosen = GetPrivateProfileIntA("camera", "dashcam", 0, ini) != 0;
    g_body = GetPrivateProfileIntA("camera", "fp_driver_body", 1, ini) != 0;
    g_cowl = GetPrivateProfileIntA("camera", "dashcam_cowl", 1, ini) != 0;
    g_up = static_cast<float>(GetPrivateProfileIntA("camera", "dashcam_up", 12, ini)) / 1000.0f;
    g_ahead = static_cast<float>(GetPrivateProfileIntA("camera", "dashcam_ahead", 35, ini)) / 1000.0f;
    const int c = GetPrivateProfileIntA("camera", "dashcam_centre", 60, ini);
    g_centre = static_cast<float>(c < 0 ? 0 : (c > 100 ? 100 : c)) / 100.0f;
    Log("cockpit: dashcam key 0x%02X, start %s, eye +%.3f up +%.3f ahead %.0f%% to the middle; driver body %s; dashcam cowl %s", g_key,
        g_chosen ? "dashcam" : "cockpit", g_up, g_ahead, g_centre * 100.0f, g_body ? "on" : "off", g_cowl ? "on" : "off");
}

void CockpitModePoll(bool allowed, bool atWheelFirst) {
    // Bit 15: down now; bit 0: pressed since the last call (a tap shorter than a frame).
    const SHORT state = GetAsyncKeyState(g_key);
    const bool down = (state & 0x8000) != 0;
    const bool tapped = (state & 0x0001) != 0;
    if (allowed && atWheelFirst && (tapped || (down && !g_keyWasDown))) {
        g_from = ChosenBlend();
        g_chosen = !g_chosen;
        g_pressAt = GetTickCount64();
        Log("cockpit: %s (key)", g_chosen ? "dashcam" : "cockpit");
    }
    g_keyWasDown = down;
    if (atWheelFirst != g_atWheelFirst) {
        // into or out of the seat view: the chosen look is there at once (the seat glide moves the eye)
        g_atWheelFirst = atWheelFirst;
        g_pressAt = 0;
    }
}

bool DashcamChosen() { return g_chosen; }
float DashcamBlend() { return g_atWheelFirst ? ChosenBlend() : 0.0f; }
bool DashcamHidesCockpit() { return DashcamBlend() >= 0.5f; }
void DashcamOffsets(float* up, float* ahead, float* centre) {
    if (up) *up = g_up;
    if (ahead) *ahead = g_ahead;
    if (centre) *centre = g_centre;
}
bool DriverBodyEnabled() { return g_body; }
bool DashcamCowl() { return g_cowl; }

}  // namespace gta2dx9
