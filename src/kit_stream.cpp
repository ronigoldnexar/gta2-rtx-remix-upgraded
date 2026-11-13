// DISTRICTS streaming: see kit_stream.h.
#include "kit_stream.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>

#include "world_mesh.h"

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
    if (size < 16 || size > 128L * 1024 * 1024) { fclose(f); return false; }
    data_.resize(static_cast<size_t>(size));
    const bool ok = fread(data_.data(), 1, data_.size(), f) == data_.size();
    fclose(f);
    if (!ok || memcmp(data_.data(), "GDK2", 4) != 0 || Rd<uint32_t>(&data_[4]) != 2) { data_.clear(); return false; }
    const uint32_t n = Rd<uint32_t>(&data_[12]);
    const size_t rec = 2 + 2 + 4 + 24 + 12;
    if (16 + static_cast<size_t>(n) * rec > data_.size()) { data_.clear(); return false; }
    for (uint32_t i = 0; i < n; ++i) {
        const uint8_t* p = &data_[16 + i * rec];
        Entry e;
        e.cx = Rd<int16_t>(p); e.cz = Rd<int16_t>(p + 2); e.lod = p[4];
        for (int k = 0; k < 6; ++k) e.bb[k] = Rd<float>(p + 8 + 4 * k);
        e.groups = Rd<uint32_t>(p + 32); e.offset = Rd<uint32_t>(p + 36); e.bytes = Rd<uint32_t>(p + 40);
        if (static_cast<size_t>(e.offset) + e.bytes > data_.size()) { data_.clear(); entries_.clear(); return false; }
        entries_.push_back(e);
    }
    tileBase_ = tileBase;
    st_ = KitStreamStats{};
    st_.entries = static_cast<int>(entries_.size());
    st_.fileBytes = data_.size();
    lastPlan_ = -1.0;
    return true;
}

bool KitStream::Alloc(uint32_t n, uint32_t* at) {
    for (size_t i = 0; i < free_.size(); ++i) {
        if (free_[i].second < n) continue;
        *at = free_[i].first;
        free_[i].first += n; free_[i].second -= n;
        if (!free_[i].second) free_.erase(free_.begin() + static_cast<long>(i));
        return true;
    }
    return false;
}

void KitStream::Free(uint32_t at, uint32_t n) {
    auto it = std::lower_bound(free_.begin(), free_.end(), std::make_pair(at, 0u));
    it = free_.insert(it, {at, n});
    const size_t i = static_cast<size_t>(it - free_.begin());
    if (i + 1 < free_.size() && free_[i].first + free_[i].second == free_[i + 1].first) {
        free_[i].second += free_[i + 1].second; free_.erase(free_.begin() + static_cast<long>(i) + 1);
    }
    if (i > 0 && free_[i - 1].first + free_[i - 1].second == free_[i].first) {
        free_[i - 1].second += free_[i].second; free_.erase(free_.begin() + static_cast<long>(i));
    }
}

void KitStream::Release() {
    res_.clear();
    if (pool_) { pool_->Release(); pool_ = nullptr; }
    free_.clear();
    data_.clear();
    data_.shrink_to_fit();
    entries_.clear();
}

bool KitStream::CreatePool(IDirect3DDevice9* device) {
    if (pool_) return true;
    if (!device || FAILED(device->CreateVertexBuffer(PoolVertices * sizeof(Vertex), D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &pool_, nullptr))) return false;
    free_.assign(1, {0u, PoolVertices});
    return true;
}

bool KitStream::Create(IDirect3DDevice9* device, int ei, Resident* r) {
    const Entry& e = entries_[static_cast<size_t>(ei)];
    uint32_t nv = 0;
    size_t at = e.offset;
    for (uint32_t g = 0; g < e.groups; ++g) {
        const uint32_t v = Rd<uint32_t>(&data_[at + 8]), i = Rd<uint32_t>(&data_[at + 12]);
        nv += v;
        at += 16 + 20 + static_cast<size_t>(v) * 14 + static_cast<size_t>(i) * 2 + ((i % 2) ? 2 : 0);
    }
    if (!nv) return false;
    if (!pool_ && !CreatePool(device)) return false;
    uint32_t base = 0;
    if (!Alloc(nv, &base)) { ++st_.refused; return false; }
    Vertex* vd = nullptr;
    if (FAILED(pool_->Lock(base * sizeof(Vertex), nv * sizeof(Vertex), reinterpret_cast<void**>(&vd), 0))) { Free(base, nv); return false; }
    at = e.offset;
    uint32_t local = 0;
    for (uint32_t g = 0; g < e.groups; ++g) {
        const uint8_t* p = &data_[at];
        Group gr;
        gr.tile = Rd<int32_t>(p);
        gr.flags = Rd<uint32_t>(p + 4);
        const uint32_t v = Rd<uint32_t>(p + 8), i = Rd<uint32_t>(p + 12);
        const float ox = Rd<float>(p + 16), oy = Rd<float>(p + 20), oz = Rd<float>(p + 24), ub = Rd<float>(p + 28), vb = Rd<float>(p + 32);
        const uint8_t* vp = p + 36;
        for (uint32_t k = 0; k < v; ++k, vp += 14) {
            Vertex& o = vd[local + k];
            o.x = ox + Rd<int16_t>(vp) / 1024.0f;
            o.y = oy + Rd<int16_t>(vp + 2) / 1024.0f;
            o.z = oz + Rd<int16_t>(vp + 4) / 1024.0f;
            o.nx = static_cast<int8_t>(vp[6]) / 127.0f;
            o.ny = static_cast<int8_t>(vp[7]) / 127.0f;
            o.nz = static_cast<int8_t>(vp[8]) / 127.0f;
            o.u = ub + Half(Rd<uint16_t>(vp + 10));
            o.v = vb + Half(Rd<uint16_t>(vp + 12));
        }
        gr.tile = gr.tile >= 0 ? gr.tile : tileBase_ + (-1 - gr.tile);
        gr.vstart = base + local; gr.vcount = v;
        r->groups.push_back(gr);
        local += v;
        at += 16 + 20 + static_cast<size_t>(v) * 14 + static_cast<size_t>(i) * 2 + ((i % 2) ? 2 : 0);
    }
    pool_->Unlock();
    r->poolStart = base; r->poolCount = nv;
    r->tris = static_cast<int>(nv / 3);
    r->bytes = nv * sizeof(Vertex);
    r->entry = ei;
    return true;
}

void KitStream::Update(IDirect3DDevice9* device, float eyeX, float eyeZ, double now) {
    if (data_.empty() || !device) return;
    // fades
    for (Resident& r : res_) {
        const float t = FadeSeconds > 0.0f ? static_cast<float>((now - r.t0) / FadeSeconds) : 1.0f;
        r.alpha = r.dying ? (std::max)(0.0f, 1.0f - t) : (std::min)(1.0f, t);
    }
    for (size_t i = 0; i < res_.size();) {
        if (res_[i].dying && res_[i].alpha <= 0.0f) {
            Free(res_[i].poolStart, res_[i].poolCount);
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
        const float hy0 = (cur != current.end() && cur->second == 0) ? 2.0f : 0.0f;
        const float hy1 = (cur != current.end()) ? 2.0f : 0.0f;
        const int lod = d < Radius0 + hy0 ? 0 : (d < Radius1 + hy1 ? 1 : -1);
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
        if (entries_[static_cast<size_t>(r.entry)].lod == 0) ++s.lod0; else ++s.lod1;
        if (r.dying || r.alpha < 1.0f) ++s.fading;
        s.triangles += r.tris;
        s.gpuBytes += r.bytes;
    }
    return s;
}

}  // namespace gta2
