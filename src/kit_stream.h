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
    int entries = 0, resident = 0, lod0 = 0, lod1 = 0, fading = 0, triangles = 0, created = 0, released = 0, refused = 0;
    size_t gpuBytes = 0, fileBytes = 0;
};

class KitStream {
public:
    struct Group { int tile; uint32_t flags; int page; uint32_t vstart, vcount; };   // vstart: in its page
    struct Resident {
        int entry = -1;
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
    bool Loaded() const { return !entries_.empty(); }
    void Update(IDirect3DDevice9* device, float eyeX, float eyeZ, double now);
    const std::vector<Resident>& Residents() const { return res_; }
    // The vertices of every resident chunk live in a fixed set of 2 MB pages made once at level load and sub-allocated
    // first fit (a group never spans pages). A buffer per chunk, made and freed as the eye moves, fragmented the
    // address space (pilot run dkd_on2); one 15 MB pool was placed by the heap in the middle of the 2 GB free block and
    // cut it to 1543 MB (dkd_on6); 2 MB pieces go into the holes the address space already has. Unshared vertices, so
    // no index buffer: DrawPrimitive on each group's range.
    IDirect3DVertexBuffer9* Page(int i) const { return i >= 0 && i < static_cast<int>(pages_.size()) ? pages_[static_cast<size_t>(i)].vb : nullptr; }
    static constexpr uint32_t kPageVertices = 65536;   // 2 MB
    int Pages = 8;                                      // 16 MB: ~170k triangles resident at most
    KitStreamStats Stats() const;
    float Radius0 = 24.0f, Radius1 = 56.0f, FadeSeconds = 0.4f;
    int CreateBudget = 3;

private:
    struct Entry { int cx, cz, lod; float bb[6]; uint32_t groups, offset, bytes; };
    bool Create(IDirect3DDevice9* device, int e, Resident* r);
    std::string path_;
    FILE* file_ = nullptr;
    std::vector<uint8_t> buf_;          // one chunk entry's bytes, reused (the largest entry's size)
    size_t fileBytes_ = 0;
    std::vector<Entry> entries_;
    std::vector<Resident> res_;
    struct PageBuf { IDirect3DVertexBuffer9* vb = nullptr; std::vector<std::pair<uint32_t, uint32_t>> free; };
    std::vector<PageBuf> pages_;
    bool Alloc(uint32_t n, int* page, uint32_t* at);
    void Free(int page, uint32_t at, uint32_t n);
    int tileBase_ = 0;
    double lastPlan_ = -1.0;
    KitStreamStats st_;
};

}  // namespace gta2
