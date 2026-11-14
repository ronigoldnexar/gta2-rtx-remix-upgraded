// DISTRICTS streaming: the facade kit as chunks loaded around the eye, with a distance level of detail.
//
// gta2dx9_districts\<style>.kit2 (tools/districts/pack_kit.py) holds the kit cut into 16 x 16-cell chunks, each in two
// levels of detail (LOD0: everything; LOD1: the skin without openings, a two-course cornice and the roof silhouettes),
// with packed vertices (14 bytes: int16 position, int8 normal + pad, half-float uv). Only the chunk table stays in
// memory; a chunk's bytes are read from the file when it streams in (holding the 15 MB district file as one block cut
// the process's largest free block from 2047 to 1333 MB at level load, run dkd_on5), and unpacked into the pool: LOD0 within Radius0 of the
// chunk's box, LOD1 within Radius1, nothing beyond. A chunk that comes in (or changes level) fades in over FadeSeconds
// while the one it replaces fades out, so nothing pops; at most CreateBudget chunks are unpacked per update.
#pragma once

#include <d3d9.h>

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace gta2 {

struct KitStreamStats {
    int entries = 0, resident = 0, lod0 = 0, lod1 = 0, fading = 0, triangles = 0, created = 0, released = 0, refused = 0, badEntries = 0;
    size_t gpuBytes = 0, fileBytes = 0;
};

class KitStream {
public:
    // vstart: in its page, or (page -1) in the resident's own buffer. groups: one draw per material (a chunk's
    // groups of one material are laid out together and drawn as one range); lit: the emissive sub-ranges, each with
    // its switch-on bucket in flags (the renderer's night pass)
    struct Group { int tile; uint32_t flags; int page; uint32_t vstart, vcount; };
    struct Resident {
        int entry = -1;
        std::vector<Group> groups;
        std::vector<Group> lit;
        std::vector<Group> allocs;               // what it holds in the pages (freed when it goes)
        IDirect3DVertexBuffer9* vb = nullptr;    // OwnBuffers: its own buffer, written once, never locked again
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
    bool Loaded() const { return !entries_.empty(); }
    void Update(IDirect3DDevice9* device, float eyeX, float eyeZ, double now);
    const std::vector<Resident>& Residents() const { return res_; }
    // an entry's box (lo x y z, hi x y z), for the shadow pass's cascade test
    const float* Bounds(int entry) const { return entry >= 0 && entry < static_cast<int>(entries_.size()) ? entries_[static_cast<size_t>(entry)].bb : nullptr; }
    // The vertices of every resident chunk live in a fixed set of 2 MB pages made once at level load and sub-allocated
    // first fit (a group never spans pages). A buffer per chunk, made and freed as the eye moves, fragmented the
    // address space (pilot run dkd_on2); one 15 MB pool was placed by the heap in the middle of the 2 GB free block and
    // cut it to 1543 MB (dkd_on6); 2 MB pieces go into the holes the address space already has. Unshared vertices, so
    // no index buffer: DrawPrimitive on each group's range.
    IDirect3DVertexBuffer9* Page(int i) const { return i >= 0 && i < static_cast<int>(pages_.size()) ? pages_[static_cast<size_t>(i)].vb : nullptr; }
    IDirect3DVertexBuffer9* BufferOf(const Resident& r, const Group& g) const { return g.page >= 0 ? Page(g.page) : r.vb; }
    // Under RTX Remix (round 6): each resident chunk in a buffer of its own, written once at creation and never
    // touched again (a write into a shared page made the bridge re-hash and rebuild every chunk drawn from that page),
    // no crossfade (blended chunks take Remix's translucent path) and a wider hysteresis (fewer new meshes to build).
    // The address space is no constraint there: the bridge holds the GPU side.
    bool OwnBuffers = false;
    float Hysteresis = 2.0f;
    static constexpr uint32_t kPageVertices = 65536;   // 2 MB
    int Pages = 24;                                     // 48 MB: ~500k triangles resident at most (round 6: 32 MB refused
                                                        // chunks on the wil drive, dkc6_wil; round 5: the whole city
                                                        // streams; a dense Downtown chunk is 17k triangles at LOD0)
    KitStreamStats Stats() const;
    float Radius0 = 20.0f, Radius1 = 56.0f, FadeSeconds = 0.4f;
    float MidRadius0 = 12.0f, RadiusMid = 28.0f;   // round 6: when the file has a middle level (lod 2)
    float DetailRadius = 13.0f;   // round 6: groups flagged fine detail (32: dentils, sills, hoods, rails) drawn only this near
    int CreateBudget = 3;

private:
    struct Entry { int cx, cz, lod; float bb[6]; uint32_t groups, offset, bytes, raw = 0; };   // raw: inflated size (version 3)
    bool Create(IDirect3DDevice9* device, int e, Resident* r);
    std::string path_;
    FILE* file_ = nullptr;
    std::vector<uint8_t> buf_;          // one chunk entry's bytes, reused (the largest entry's size)
    std::vector<uint8_t> zbuf_;         // its deflated bytes (version 3)
    size_t fileBytes_ = 0;
    std::vector<Entry> entries_;
    std::vector<Resident> res_;
    struct PageBuf { IDirect3DVertexBuffer9* vb = nullptr; std::vector<std::pair<uint32_t, uint32_t>> free; };
    std::vector<PageBuf> pages_;
    bool Alloc(uint32_t n, int* page, uint32_t* at);
    void Free(int page, uint32_t at, uint32_t n);
    int tileBase_ = 0;
    bool hasMid_ = false;
    double lastPlan_ = -1.0;
    KitStreamStats st_;
};

}  // namespace gta2
