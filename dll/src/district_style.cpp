// DISTRICTS: per-district style rows at run time; see district_style.h.
#include "district_style.h"
#include "log.h"
#include "remix_api.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

using gta2dx9::Log;
using gta2dx9::RemixApiAvailable;
using gta2dx9::RemixSetConfig;

namespace districts {
namespace {

struct Row {
    std::string name;
    float fog[3] = {1, 1, 1};
    float ambient[3] = {1, 1, 1};
    float props[kPropKinds] = {1, 1, 1, 1, 1};
    std::vector<std::pair<std::string, std::string>> remix;
};

constexpr int kW = 256, kH = 256;
std::vector<Row> g_rows;
std::vector<uint8_t> g_grid;       // kW * kH row indices, map y major
float g_fog[3] = {1, 1, 1}, g_amb[3] = {1, 1, 1};
int g_row = -1, g_remixRow = -1;
double g_last = 0.0;

uint32_t Mix(uint32_t h) {
    h ^= h >> 16; h *= 0x7feb352du; h ^= h >> 15; h *= 0x846ca68bu; h ^= h >> 16;
    return h;
}

}  // namespace

void ClearStyles() {
    g_rows.clear(); g_grid.clear();
    for (int k = 0; k < 3; ++k) g_fog[k] = g_amb[k] = 1.0f;
    g_row = -1; g_remixRow = -1; g_last = 0.0;
}

bool StylesLoaded() { return !g_rows.empty() && g_grid.size() == static_cast<size_t>(kW * kH); }

// GDS1 text: "row <name> fog r g b ambient r g b props furniture trees meters roof containers",
// "remix <row> <key> <value to the end of the line>", then "grid <w> <h>" and run-length pairs "<count> <row>".
bool LoadStyles(const std::string& path) {
    ClearStyles();
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    char line[1024];
    bool ok = fgets(line, sizeof line, f) && strncmp(line, "GDS1", 4) == 0;
    while (ok && fgets(line, sizeof line, f)) {
        if (strncmp(line, "row ", 4) == 0) {
            Row r;
            char name[128] = {};
            const int n = sscanf(line + 4, "%127s fog %f %f %f ambient %f %f %f props %f %f %f %f %f", name, &r.fog[0], &r.fog[1], &r.fog[2],
                                 &r.ambient[0], &r.ambient[1], &r.ambient[2], &r.props[0], &r.props[1], &r.props[2], &r.props[3], &r.props[4]);
            if (n != 12 || g_rows.size() >= 255) { ok = false; break; }
            r.name = name;
            g_rows.push_back(r);
        } else if (strncmp(line, "remix ", 6) == 0) {
            int row = -1, at = 0;
            char key[160] = {};
            if (sscanf(line + 6, "%d %159s %n", &row, key, &at) < 2 || row < 0 || row >= static_cast<int>(g_rows.size())) { ok = false; break; }
            std::string value = line + 6 + at;
            while (!value.empty() && (value.back() == '\n' || value.back() == '\r' || value.back() == ' ')) value.pop_back();
            g_rows[static_cast<size_t>(row)].remix.emplace_back(key, value);
        } else if (strncmp(line, "grid ", 5) == 0) {
            int w = 0, h = 0;
            if (sscanf(line + 5, "%d %d", &w, &h) != 2 || w != kW || h != kH) { ok = false; break; }
            g_grid.reserve(kW * kH);
            int count = 0, row = 0;
            while (g_grid.size() < static_cast<size_t>(kW * kH) && fscanf(f, "%d %d", &count, &row) == 2) {
                if (count <= 0 || row < 0 || row >= static_cast<int>(g_rows.size())) { ok = false; break; }
                g_grid.insert(g_grid.end(), static_cast<size_t>((std::min)(count, kW * kH - static_cast<int>(g_grid.size()))), static_cast<uint8_t>(row));
            }
            break;
        }
    }
    fclose(f);
    if (!ok || !StylesLoaded()) {
        Log("districts: style table %s not loaded (bad or truncated file)", path.c_str());
        ClearStyles();
        return false;
    }
    std::vector<int> cells(g_rows.size(), 0);
    for (uint8_t r : g_grid) ++cells[r];
    std::string list;
    for (size_t k = 0; k < g_rows.size(); ++k) {
        char item[200];
        snprintf(item, sizeof item, "%s%s %d cells", k ? ", " : "", g_rows[k].name.c_str(), cells[k]);
        list += item;
    }
    Log("districts: style table %s: %u rows (%s)", path.c_str(), static_cast<unsigned>(g_rows.size()), list.c_str());
    return true;
}

int RowAt(int mapX, int mapY) {
    if (!StylesLoaded() || mapX < 0 || mapX >= kW || mapY < 0 || mapY >= kH) return 0;
    return g_grid[static_cast<size_t>(mapY) * kW + static_cast<size_t>(mapX)];
}

float PropScale(int mapX, int mapY, Prop p) {
    if (!StylesLoaded()) return 1.0f;
    return g_rows[static_cast<size_t>(RowAt(mapX, mapY))].props[p];
}

bool Keep(int mapX, int mapY, Prop p, uint32_t h, bool base, float rate) {
    const float m = PropScale(mapX, mapY, p);
    if (m == 1.0f) return base;
    const float roll = static_cast<float>(Mix(h ^ (0x9e3779b9u * (static_cast<uint32_t>(p) + 1u))) % 10000u) / 10000.0f;
    if (base) return m >= 1.0f || roll < m;
    if (m <= 1.0f || rate >= 1.0f) return false;
    return roll < (std::min)(1.0f, (m - 1.0f) * rate / (1.0f - rate));   // the extra cells bring the share to m * rate
}

void Update(float eyeX, float eyeZ, bool street, double now) {
    if (!StylesLoaded()) return;
    const int mapX = static_cast<int>(std::floor(eyeX)), mapY = kH - 1 - static_cast<int>(std::floor(eyeZ));
    const int row = RowAt(mapX, mapY);
    const Row& r = g_rows[static_cast<size_t>(row)];
    const double dt = g_last > 0.0 ? (std::min)(0.25, (std::max)(0.0, now - g_last)) : 1.0;
    g_last = now;
    const float k = static_cast<float>((std::min)(1.0, dt / 2.0));   // ~2 s to the new grade
    for (int c = 0; c < 3; ++c) {
        g_fog[c] += (r.fog[c] - g_fog[c]) * k;
        g_amb[c] += (r.ambient[c] - g_amb[c]) * k;
    }
    if (row != g_row) {
        Log("districts: camera in %s (cell %d,%d)", r.name.c_str(), mapX, mapY);
        g_row = row;
    }
    const int want = street ? row : 0;
    if (want != g_remixRow && RemixApiAvailable()) {
        int pushed = 0, refused = 0;
        for (const auto& kv : g_rows[static_cast<size_t>(want)].remix) (RemixSetConfig(kv.first.c_str(), kv.second.c_str()) ? pushed : refused)++;
        if (pushed || refused) Log("districts: Remix options of %s: %d set, %d refused", g_rows[static_cast<size_t>(want)].name.c_str(), pushed, refused);
        g_remixRow = want;
    }
}

gta2::Vec3 FogScale() { return gta2::Vec3{g_fog[0], g_fog[1], g_fog[2]}; }
gta2::Vec3 AmbientScale() { return gta2::Vec3{g_amb[0], g_amb[1], g_amb[2]}; }
const char* RowName(int row) { return row >= 0 && row < static_cast<int>(g_rows.size()) ? g_rows[static_cast<size_t>(row)].name.c_str() : "none"; }

}  // namespace districts
