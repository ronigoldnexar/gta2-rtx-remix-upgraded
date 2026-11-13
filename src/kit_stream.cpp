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
    uint8_t head[16];
    if (size < 16 || fread(head, 1, 16, f) != 16 || memcmp(head, "GDK2", 4) != 0 || Rd<uint32_t>(head + 4) != 2) { fclose(f); return false; }
    const uint32_t n = Rd<uint32_t>(head + 12);
    const size_t rec = 2 + 2 + 4 + 24 + 12;
    if (16 + static_cast<size_t>(n) * rec > static_cast<size_t>(size)) { fclose(f); return false; }
    std::vector<uint8_t> table(static_cast<size_t>(n) * rec);
    if (fread(table.data(), 1, table.size(), f) != table.size()) { fclose(f); return false; }
    size_t largest = 0;
    for (uint32_t i = 0; i < n; ++i) {
        const uint8_t* p = &table[i * rec];
        Entry e;
        e.cx = Rd<int16_t>(p); e.cz = Rd<int16_t>(p + 2); e.lod = p[4];
        for (int k = 0; k < 6; ++k) e.bb[k] = Rd<float>(p + 8 + 4 * k);
        e.groups = Rd<uint32_t>(p + 32); e.offset = Rd<uint32_t>(p + 36); e.bytes = Rd<uint32_t>(p + 40);
        if (static_cast<size_t>(e.offset) + e.bytes > static_cast<size_t>(size)) { fclose(f); entries_.clear(); return false; }
        largest = (std::max)(largest, static_cast<size_t>(e.bytes));
        entries_.push_back(e);
    }
    file_ = f;
    path_ = path;
    buf_.reserve(largest);
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
    res_.clear();
    for (PageBuf& p : pages_) if (p.vb) p.vb->Release();
    pages_.clear();
    if (file_) { fclose(file_); file_ = nullptr; }
    buf_.clear();
    buf_.shrink_to_fit();
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
    buf_.resize(e.bytes);
    if (fseek(file_, static_cast<long>(e.offset), SEEK_SET) != 0 || fread(buf_.data(), 1, e.bytes, file_) != e.bytes) return false;
    const std::vector<uint8_t>& data_ = buf_;
    uint32_t nv = 0;
    size_t at = 0;
    for (uint32_t g = 0; g < e.groups; ++g) {
        const uint32_t v = Rd<uint32_t>(&data_[at + 8]), i = Rd<uint32_t>(&data_[at + 12]);
        nv += v;
        at += 16 + 20 + static_cast<size_t>(v) * 14 + static_cast<size_t>(i) * 2 + ((i % 2) ? 2 : 0);
    }
    if (!nv) return false;
    if (pages_.empty() && !CreatePool(device)) return false;
    at = 0;
    for (uint32_t g = 0; g < e.groups; ++g) {
        const uint8_t* p = &data_[at];
        Group gr;
        gr.tile = Rd<int32_t>(p);
        gr.flags = Rd<uint32_t>(p + 4);
        const uint32_t v = Rd<uint32_t>(p + 8), i = Rd<uint32_t>(p + 12);
        const float ox = Rd<float>(p + 16), oy = Rd<float>(p + 20), oz = Rd<float>(p + 24), ub = Rd<float>(p + 28), vb = Rd<float>(p + 32);
        at += 16 + 20 + static_cast<size_t>(v) * 14 + static_cast<size_t>(i) * 2 + ((i % 2) ? 2 : 0);
        int page = -1;
        uint32_t base = 0;
        Vertex* vd = nullptr;
        if (!Alloc(v, &page, &base)) {
            // all or nothing: a chunk with some of its groups missing would stay resident with walls missing (the
            // round-4 ste frames); give back what it took and let a later plan try again
            ++st_.refused;
            for (const Group& q : r->groups) Free(q.page, q.vstart, q.vcount);
            r->groups.clear(); r->tris = 0; r->bytes = 0;
            return false;
        }
        if (FAILED(pages_[static_cast<size_t>(page)].vb->Lock(base * sizeof(Vertex), v * sizeof(Vertex), reinterpret_cast<void**>(&vd), 0))) {
            Free(page, base, v); break;
        }
        const uint8_t* vp = p + 36;
        for (uint32_t k = 0; k < v; ++k, vp += 14) {
            Vertex& o = vd[k];
            o.x = ox + Rd<int16_t>(vp) / 1024.0f;
            o.y = oy + Rd<int16_t>(vp + 2) / 1024.0f;
            o.z = oz + Rd<int16_t>(vp + 4) / 1024.0f;
            o.nx = static_cast<int8_t>(vp[6]) / 127.0f;
            o.ny = static_cast<int8_t>(vp[7]) / 127.0f;
            o.nz = static_cast<int8_t>(vp[8]) / 127.0f;
            o.u = ub + Half(Rd<uint16_t>(vp + 10));
            o.v = vb + Half(Rd<uint16_t>(vp + 12));
        }
        pages_[static_cast<size_t>(page)].vb->Unlock();
        gr.tile = gr.tile >= 0 ? gr.tile : tileBase_ + (-1 - gr.tile);
        gr.page = page; gr.vstart = base; gr.vcount = v;
        r->groups.push_back(gr);
        r->tris += static_cast<int>(v / 3);
        r->bytes += v * sizeof(Vertex);
    }
    if (r->groups.empty()) return false;
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
            for (const Group& g : res_[i].groups) Free(g.page, g.vstart, g.vcount);
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
