// DISTRICTS-POC: see district_kit.h.
#include "district_kit.h"

#include <cstdio>
#include <cstring>
#include <vector>

namespace gta2 {
namespace {
bool g_kitOn = false;
std::string g_kitDir;
}  // namespace

void SetDistrictKit(bool on, const char* dir) {
    g_kitOn = on;
    g_kitDir = dir ? dir : "";
}
bool DistrictKitEnabled() { return g_kitOn; }
const std::string& DistrictKitDir() { return g_kitDir; }

bool AppendDistrictKit(const Style& style, const std::string& styleName, WorldMesh* mesh, DistrictKitStats* stats) {
    DistrictKitStats st;
    if (!g_kitOn || g_kitDir.empty() || !mesh) { if (stats) *stats = st; return false; }
    const std::string path = g_kitDir + "\\" + styleName + ".kit";
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) { if (stats) *stats = st; return false; }
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    // A kit is a few MB at most for a whole level; refuse anything absurd (the 32-bit address space is tight).
    if (size < 12 || size > 64L * 1024 * 1024) { fclose(f); if (stats) *stats = st; return false; }
    std::vector<uint8_t> data(static_cast<size_t>(size));
    const bool read = fread(data.data(), 1, data.size(), f) == data.size();
    fclose(f);
    if (!read || memcmp(data.data(), "GDK1", 4) != 0) { if (stats) *stats = st; return false; }
    auto u32 = [&](size_t at) { uint32_t v; memcpy(&v, &data[at], 4); return v; };
    const uint32_t version = u32(4), groups = u32(8);
    if (version != 1) { if (stats) *stats = st; return false; }
    // Validate the whole file before touching the mesh.
    size_t p = 12;
    for (uint32_t g = 0; g < groups; ++g) {
        if (p + 16 > data.size()) { if (stats) *stats = st; return false; }
        const uint64_t nv = u32(p + 8), ni = u32(p + 12);
        p += 16 + nv * 32 + ni * 4;
        if (p > data.size()) { if (stats) *stats = st; return false; }
    }
    p = 12;
    st.bytes = data.size();
    for (uint32_t g = 0; g < groups; ++g) {
        int32_t tile;
        memcpy(&tile, &data[p], 4);
        const uint32_t flags = u32(p + 4), nv = u32(p + 8), ni = u32(p + 12);
        p += 16;
        const uint8_t* verts = &data[p];
        p += static_cast<size_t>(nv) * 32;
        const uint8_t* idx = &data[p];
        p += static_cast<size_t>(ni) * 4;
        ++st.groups;
        const int resolved = tile >= 0 ? tile : (-1 - tile < kKitMaterials ? KitTileIndex(style, -1 - tile) : -1);
        if (resolved < 0 || (tile >= 0 && tile >= style.TileCount()) || nv == 0 || ni < 3) { ++st.skipped; continue; }
        TileBatch b;
        b.tile = resolved;
        b.streetOnly = true;
        b.kit = true;
        b.needsAlphaTest = (flags & 1) != 0;
        b.doubleSided = (flags & 2) != 0;
        b.wrapUv = (flags & 4) != 0;
        b.vertexStart = static_cast<uint32_t>(mesh->vertices.size());
        b.vertexCount = nv;
        b.indexStart = static_cast<uint32_t>(mesh->indices.size());
        mesh->vertices.resize(mesh->vertices.size() + nv);
        memcpy(&mesh->vertices[b.vertexStart], verts, static_cast<size_t>(nv) * sizeof(Vertex));
        mesh->indices.reserve(mesh->indices.size() + ni);
        for (uint32_t i = 0; i < ni; ++i) {
            uint32_t v;
            memcpy(&v, idx + static_cast<size_t>(i) * 4, 4);
            if (v >= nv) v = 0;
            mesh->indices.push_back(b.vertexStart + v);
        }
        b.indexCount = ni - ni % 3;
        mesh->indices.resize(b.indexStart + b.indexCount);
        mesh->batches.push_back(b);
        ++st.batches;
        st.triangles += static_cast<int>(b.indexCount / 3);
        st.vertices += static_cast<int>(nv);
    }
    st.loaded = st.batches > 0;
    if (stats) *stats = st;
    return st.loaded;
}

}  // namespace gta2
