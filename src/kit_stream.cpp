// DISTRICTS streaming: see kit_stream.h.
#include "kit_stream.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>

#include "world_mesh.h"
#include "inflate.h"

namespace gta2 {
namespace {
float Half(uint16_t h) {
    const uint32_t s = (h >> 15) & 1, e = (h >> 10) & 31, m = h & 1023;
    float v;
    if (e == 0) v = std::ldexp(static_cast<float>(m), -24);
    else if (e == 31) v = m ? 0.0f : 65504.0f;
    else v = std::ldexp(static_cast<float>(m | 1024), static_cast<int>(e) - 25);
    return s ? -v : v;
}
template <typename T> T Rd(const uint8_t* p) { T v; memcpy(&v, p, sizeof(T)); return v; }
}  // namespace

bool KitStream::Load(const std::string& path, int tileBase) {
    Release();
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t head[16];
    const uint32_t ver = size >= 16 && fread(head, 1, 16, f) == 16 && memcmp(head, "GDK2", 4) == 0 ? Rd<uint32_t>(head + 4) : 0;
    if (ver != 2 && ver != 3) { fclose(f); return false; }    // 3 (round 6): each entry raw-deflated, its raw size after it
    const uint32_t n = Rd<uint32_t>(head + 12);
    const size_t rec = 2 + 2 + 4 + 24 + (ver == 3 ? 16 : 12);
    if (16 + static_cast<size_t>(n) * rec > static_cast<size_t>(size)) { fclose(f); return false; }
    std::vector<uint8_t> table(static_cast<size_t>(n) * rec);
    if (fread(table.data(), 1, table.size(), f) != table.size()) { fclose(f); return false; }
    size_t largest = 0, largestPacked = 0;
    hasMid_ = false;
    for (uint32_t i = 0; i < n; ++i) {
        const uint8_t* p = &table[i * rec];
        Entry e;
        e.cx = Rd<int16_t>(p); e.cz = Rd<int16_t>(p + 2); e.lod = p[4];
        for (int k = 0; k < 6; ++k) e.bb[k] = Rd<float>(p + 8 + 4 * k);
        e.groups = Rd<uint32_t>(p + 32); e.offset = Rd<uint32_t>(p + 36); e.bytes = Rd<uint32_t>(p + 40);
        e.raw = ver == 3 ? Rd<uint32_t>(p + 44) : 0;
        if (static_cast<size_t>(e.offset) + e.bytes > static_cast<size_t>(size)) { fclose(f); entries_.clear(); return false; }
        largest = (std::max)(largest, static_cast<size_t>((std::max)(e.bytes, e.raw)));
        largestPacked = (std::max)(largestPacked, static_cast<size_t>(e.raw ? e.bytes : 0));
        if (e.lod == 2) hasMid_ = true;
        entries_.push_back(e);
    }
    file_ = f;
    path_ = path;
    buf_.reserve(largest);
    zbuf_.reserve(largestPacked);
    tileBase_ = tileBase;
    st_ = KitStreamStats{};
    st_.entries = static_cast<int>(entries_.size());
    fileBytes_ = static_cast<size_t>(size);
    st_.fileBytes = fileBytes_;
    lastPlan_ = -1.0;
    return true;
}

bool KitStream::Alloc(uint32_t n, int* page, uint32_t* at) {
    for (size_t p = 0; p < pages_.size(); ++p) {
        auto& fl = pages_[p].free;
        for (size_t i = 0; i < fl.size(); ++i) {
            if (fl[i].second < n) continue;
            *page = static_cast<int>(p); *at = fl[i].first;
            fl[i].first += n; fl[i].second -= n;
            if (!fl[i].second) fl.erase(fl.begin() + static_cast<long>(i));
            return true;
        }
    }
    return false;
}

void KitStream::Free(int page, uint32_t at, uint32_t n) {
    if (page < 0 || page >= static_cast<int>(pages_.size())) return;
    auto& fl = pages_[static_cast<size_t>(page)].free;
    auto it = std::lower_bound(fl.begin(), fl.end(), std::make_pair(at, 0u));
    it = fl.insert(it, {at, n});
    const size_t i = static_cast<size_t>(it - fl.begin());
    if (i + 1 < fl.size() && fl[i].first + fl[i].second == fl[i + 1].first) { fl[i].second += fl[i + 1].second; fl.erase(fl.begin() + static_cast<long>(i) + 1); }
    if (i > 0 && fl[i - 1].first + fl[i - 1].second == fl[i].first) { fl[i - 1].second += fl[i].second; fl.erase(fl.begin() + static_cast<long>(i)); }
}

void KitStream::Release() {
    for (Resident& r : res_) if (r.vb) r.vb->Release();
    res_.clear();
    for (PageBuf& p : pages_) if (p.vb) p.vb->Release();
    pages_.clear();
    if (file_) { fclose(file_); file_ = nullptr; }
    buf_.clear();
    buf_.shrink_to_fit();
    zbuf_.clear();
    zbuf_.shrink_to_fit();
    entries_.clear();
}

bool KitStream::CreatePool(IDirect3DDevice9* device) {
    if (!pages_.empty()) return true;
    if (!device) return false;
    for (int i = 0; i < Pages; ++i) {
        PageBuf p;
        if (FAILED(device->CreateVertexBuffer(kPageVertices * sizeof(Vertex), D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &p.vb, nullptr))) break;
        p.free.assign(1, {0u, kPageVertices});
        pages_.push_back(std::move(p));
    }
    return !pages_.empty();
}

bool KitStream::Create(IDirect3DDevice9* device, int ei, Resident* r) {
    const Entry& e = entries_[static_cast<size_t>(ei)];
    if (!file_) return false;
    if (e.raw) {     // version 3: inflate the entry
        zbuf_.resize(e.bytes);
        buf_.resize(e.raw);
        if (fseek(file_, static_cast<long>(e.offset), SEEK_SET) != 0 || fread(zbuf_.data(), 1, e.bytes, file_) != e.bytes) return false;
        if (!Inflate(zbuf_.data(), zbuf_.size(), buf_.data(), buf_.size())) { ++st_.badEntries; return false; }
    } else {
        buf_.resize(e.bytes);
        if (fseek(file_, static_cast<long>(e.offset), SEEK_SET) != 0 || fread(buf_.data(), 1, e.bytes, file_) != e.bytes) return false;
    }
    struct Src { int tile; uint32_t flags, v; const uint8_t* p; };
    std::vector<Src> src;
    src.reserve(e.groups);
    uint32_t nv = 0;
    size_t at = 0;
    for (uint32_t g = 0; g < e.groups; ++g) {
        const uint8_t* p = &buf_[at];
        const int32_t tile = Rd<int32_t>(p);
        const uint32_t v = Rd<uint32_t>(p + 8), i = Rd<uint32_t>(p + 12);
        if (v) src.push_back({tile >= 0 ? tile : tileBase_ + (-1 - tile), Rd<uint32_t>(p + 4), v, p});
        nv += v;
        at += 16 + 20 + static_cast<size_t>(v) * 14 + static_cast<size_t>(i) * 2 + ((i % 2) ? 2 : 0);
    }
    if (!nv) return false;
    // one material's groups together (the switch-on bucket last, so a material's emissive groups stay one range)
    std::stable_sort(src.begin(), src.end(), [](const Src& x, const Src& y) {
        const uint32_t fx = x.flags & ~0x1F00u, fy = y.flags & ~0x1F00u;
        if (x.tile != y.tile) return x.tile < y.tile;
        if (fx != fy) return fx < fy;
        return (x.flags & 0x1F00u) < (y.flags & 0x1F00u);
    });
    // where the vertices go: its own buffer (OwnBuffers), else one range of a page, else a range a group (all or none)
    std::vector<std::pair<int, uint32_t>> place(src.size(), {-1, 0u});
    if (OwnBuffers) {
        if (FAILED(device->CreateVertexBuffer(nv * sizeof(Vertex), D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &r->vb, nullptr))) { ++st_.refused; return false; }
        uint32_t o = 0;
        for (size_t k = 0; k < src.size(); ++k) { place[k] = {-1, o}; o += src[k].v; }
    } else {
        if (pages_.empty() && !CreatePool(device)) return false;
        int page = -1;
        uint32_t base = 0;
        if (nv <= kPageVertices && Alloc(nv, &page, &base)) {
            r->allocs.push_back({0, 0u, page, base, nv});
            uint32_t o = base;
            for (size_t k = 0; k < src.size(); ++k) { place[k] = {page, o}; o += src[k].v; }
        } else {
            for (size_t k = 0; k < src.size(); ++k) {
                if (!Alloc(src[k].v, &page, &base)) {
                    // all or nothing: a chunk with some groups missing stayed resident with walls missing (round 4)
                    ++st_.refused;
                    for (const Group& q : r->allocs) Free(q.page, q.vstart, q.vcount);
                    r->allocs.clear();
                    return false;
                }
                r->allocs.push_back({0, 0u, page, base, src[k].v});
                place[k] = {page, base};
            }
        }
    }
    // unpack
    for (size_t k = 0; k < src.size(); ++k) {
        const uint8_t* p = src[k].p;
        const uint32_t v = src[k].v;
        const float ox = Rd<float>(p + 16), oy = Rd<float>(p + 20), oz = Rd<float>(p + 24), ub = Rd<float>(p + 28), vb = Rd<float>(p + 32);
        IDirect3DVertexBuffer9* target = place[k].first >= 0 ? pages_[static_cast<size_t>(place[k].first)].vb : r->vb;
        Vertex* vd = nullptr;
        if (!target || FAILED(target->Lock(place[k].second * sizeof(Vertex), v * sizeof(Vertex), reinterpret_cast<void**>(&vd), 0))) {
            for (const Group& q : r->allocs) Free(q.page, q.vstart, q.vcount);
            r->allocs.clear();
            if (r->vb) { r->vb->Release(); r->vb = nullptr; }
            r->groups.clear(); r->lit.clear();
            return false;
        }
        const uint8_t* vp = p + 36;
        for (uint32_t q = 0; q < v; ++q, vp += 14) {
            Vertex& o = vd[q];
            o.x = ox + Rd<int16_t>(vp) / 1024.0f;
            o.y = oy + Rd<int16_t>(vp + 2) / 1024.0f;
            o.z = oz + Rd<int16_t>(vp + 4) / 1024.0f;
            o.nx = static_cast<int8_t>(vp[6]) / 127.0f;
            o.ny = static_cast<int8_t>(vp[7]) / 127.0f;
            o.nz = static_cast<int8_t>(vp[8]) / 127.0f;
            o.u = ub + Half(Rd<uint16_t>(vp + 10));
            o.v = vb + Half(Rd<uint16_t>(vp + 12));
        }
        target->Unlock();
        // draws: a material's consecutive ranges merge into one (main pass); emissive ranges also go to the night list
        const Group g{src[k].tile, src[k].flags, place[k].first, place[k].second, v};
        if (!r->groups.empty()) {
            Group& last = r->groups.back();
            if (last.tile == g.tile && (last.flags & ~0x1F00u) == (g.flags & ~0x1F00u) && last.page == g.page && last.vstart + last.vcount == g.vstart) {
                last.vcount += v;
            } else {
                r->groups.push_back(g);
            }
        } else {
            r->groups.push_back(g);
        }
        if (g.flags & 16) r->lit.push_back(g);
        r->tris += static_cast<int>(v / 3);
        r->bytes += v * sizeof(Vertex);
    }
    r->entry = ei;
    return true;
}

void KitStream::Update(IDirect3DDevice9* device, float eyeX, float eyeZ, double now) {
    if (entries_.empty() || !device) return;
    // fades
    for (Resident& r : res_) {
        const float t = FadeSeconds > 0.0f ? static_cast<float>((now - r.t0) / FadeSeconds) : 1.0f;
        r.alpha = r.dying ? (std::max)(0.0f, 1.0f - t) : (std::min)(1.0f, t);
    }
    for (size_t i = 0; i < res_.size();) {
        if (res_[i].dying && res_[i].alpha <= 0.0f) {
            for (const Group& g : res_[i].allocs) Free(g.page, g.vstart, g.vcount);
            if (res_[i].vb) res_[i].vb->Release();
            res_.erase(res_.begin() + static_cast<long>(i));
            ++st_.released;
        } else {
            ++i;
        }
    }
    if (lastPlan_ >= 0.0 && now - lastPlan_ < 0.2) return;
    lastPlan_ = now;
    // the wanted entry per chunk: LOD0 near, LOD1 further, none beyond (2 blocks of hysteresis on the current one)
    std::map<std::pair<int, int>, int> current;
    for (const Resident& r : res_)
        if (!r.dying) current[{entries_[static_cast<size_t>(r.entry)].cx, entries_[static_cast<size_t>(r.entry)].cz}] = entries_[static_cast<size_t>(r.entry)].lod;
    std::map<std::pair<int, int>, int> want;     // chunk -> entry index
    std::vector<std::pair<float, int>> order;
    for (size_t i = 0; i < entries_.size(); ++i) {
        const Entry& e = entries_[i];
        const float dx = (std::max)({0.0f, e.bb[0] - eyeX, eyeX - e.bb[3]});
        const float dz = (std::max)({0.0f, e.bb[2] - eyeZ, eyeZ - e.bb[5]});
        const float d = std::sqrt(dx * dx + dz * dz);
        const auto cur = current.find({e.cx, e.cz});
        const float hy0 = (cur != current.end() && cur->second == 0) ? Hysteresis : 0.0f;
        const float hy1 = (cur != current.end()) ? Hysteresis : 0.0f;
        // round 6: with a middle level (lod 2, the lean kit) LOD0 is kept to MidRadius0, the middle level to RadiusMid
        const float r0 = hasMid_ ? MidRadius0 : Radius0;
        const float hym = (cur != current.end() && (cur->second == 0 || cur->second == 2)) ? Hysteresis : 0.0f;
        const int lod = d < r0 + hy0 ? 0 : (hasMid_ && d < RadiusMid + hym ? 2 : (d < Radius1 + hy1 ? 1 : -1));
        if (lod == e.lod) { want[{e.cx, e.cz}] = static_cast<int>(i); order.push_back({d, static_cast<int>(i)}); }
    }
    // retire what is no longer wanted (fade out), bring in what is missing (fade in), nearest first
    for (Resident& r : res_) {
        if (r.dying) continue;
        const Entry& e = entries_[static_cast<size_t>(r.entry)];
        const auto w = want.find({e.cx, e.cz});
        if (w == want.end() || w->second != r.entry) {
            // keep it until its replacement is in (no hole while the new level of detail is unpacked)
            bool replacementIn = w == want.end();
            for (const Resident& q : res_) if (w != want.end() && q.entry == w->second) replacementIn = true;
            if (replacementIn) { r.dying = true; r.t0 = now - (1.0f - r.alpha) * FadeSeconds; }
        }
    }
    std::sort(order.begin(), order.end());
    int budget = CreateBudget;
    for (const auto& [d, ei] : order) {
        bool have = false;
        for (const Resident& r : res_) if (r.entry == ei && !r.dying) { have = true; break; }
        if (have) continue;
        if (budget-- <= 0) break;
        Resident r;
        if (!Create(device, ei, &r)) continue;
        r.t0 = now;
        r.alpha = 0.0f;
        res_.push_back(std::move(r));
        ++st_.created;
    }
}

KitStreamStats KitStream::Stats() const {
    KitStreamStats s = st_;
    s.resident = static_cast<int>(res_.size());
    s.lod0 = s.lod1 = s.fading = s.triangles = 0;
    s.gpuBytes = 0;
    for (const Resident& r : res_) {
        if (entries_[static_cast<size_t>(r.entry)].lod == 1) ++s.lod1; else ++s.lod0;   // LOD0 and the middle level
        if (r.dying || r.alpha < 1.0f) ++s.fading;
        s.triangles += r.tris;
        s.gpuBytes += r.bytes;
    }
    return s;
}

}  // namespace gta2
