// DISTRICTS streaming: the facade kit as chunks loaded around the eye, with a distance level of detail.
//
// gta2dx9_districts\<style>.kit2 (tools/districts/pack_kit.py) holds the kit cut into 16 x 16-cell chunks, each in two
// levels of detail (LOD0: everything; LOD1: the skin without openings, a two-course cornice and the roof silhouettes),
// with packed vertices (14 bytes: int16 position, int8 normal + pad, half-float uv). The whole packed file stays in memory
// (a district is ~15 MB); only the chunks near the eye are unpacked into vertex buffers: LOD0 within Radius0 of the
// chunk's box, LOD1 within Radius1, nothing beyond. A chunk that comes in (or changes level) fades in over FadeSeconds
// while the one it replaces fades out, so nothing pops; at most CreateBudget chunks are unpacked per update.
#pragma once

#include <d3d9.h>

#include <cstdint>
#include <string>
#include <vector>

namespace gta2 {

struct KitStreamStats {
    int entries = 0, resident = 0, lod0 = 0, lod1 = 0, fading = 0, triangles = 0, created = 0, released = 0, refused = 0;
    size_t gpuBytes = 0, fileBytes = 0;
};

class KitStream {
public:
    struct Group { int tile; uint32_t flags; uint32_t vstart, vcount; };   // vstart: in the pool
    struct Resident {
        int entry = -1;
        uint32_t poolStart = 0, poolCount = 0;    // its range of the shared vertex pool
        std::vector<Group> groups;
        float alpha = 0.0f;
        bool dying = false;
        double t0 = 0.0;
        int tris = 0;
        size_t bytes = 0;
    };
    // tileBase: KitTileIndex(style, 0), where the kit's own materials start.
    bool Load(const std::string& path, int tileBase);
    // the vertex pool, made right after the world's own buffers at level load (made later, mid-game, a 15 MB block
    // lands wherever the address space has room and can split its largest free block)
    bool CreatePool(IDirect3DDevice9* device);
    void Release();
    bool Loaded() const { return !data_.empty(); }
    void Update(IDirect3DDevice9* device, float eyeX, float eyeZ, double now);
    const std::vector<Resident>& Residents() const { return res_; }
    // One vertex buffer for every resident chunk, made once at the first update and sub-allocated (first fit): a
    // buffer per chunk, made and freed as the eye moves, split the process's largest free block (pilot run dkd_on2:
    // 1570 -> 553 MB). Unshared vertices, so no index buffer: DrawPrimitive on each group's range.
    IDirect3DVertexBuffer9* Pool() const { return pool_; }
    uint32_t PoolVertices = 480 * 1024;          // 15 MB of vertices: ~160k triangles resident at most
    KitStreamStats Stats() const;
    float Radius0 = 24.0f, Radius1 = 56.0f, FadeSeconds = 0.4f;
    int CreateBudget = 3;

private:
    struct Entry { int cx, cz, lod; float bb[6]; uint32_t groups, offset, bytes; };
    bool Create(IDirect3DDevice9* device, int e, Resident* r);
    std::vector<uint8_t> data_;
    std::vector<Entry> entries_;
    std::vector<Resident> res_;
    IDirect3DVertexBuffer9* pool_ = nullptr;
    std::vector<std::pair<uint32_t, uint32_t>> free_;   // (start, count), sorted by start
    bool Alloc(uint32_t n, uint32_t* at);
    void Free(uint32_t at, uint32_t n);
    int tileBase_ = 0;
    double lastPlan_ = -1.0;
    KitStreamStats st_;
};

}  // namespace gta2
