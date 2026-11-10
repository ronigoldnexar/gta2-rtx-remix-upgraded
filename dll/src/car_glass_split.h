// VEHICLE-GLASS-3: under Remix the car hull is cut by geometry (the path tracer ignores the plain renderer's
// mask stage). Whole-triangle voting gave a sawtooth on dense meshes and left large baked triangles on
// coarse ones (000). Here a triangle straddling the pane boundary is subdivided down to about 1.5 mask
// texels in UV and each leaf is clipped along the 0.5 iso-line of the box-blurred pane mask (bilinear,
// the same contour the plain renderer's alpha test cuts), so the hull and the pane get complementary
// pieces whose shared edge follows the window's outline. No D3D here: tools/glass_split_test.cpp runs it
// natively on the model files.
#pragma once

#include <cmath>
#include <cstdint>
#include <vector>

#include "model_store.h"

namespace gta2dx9 {

struct GlassSplit {
    std::vector<ModelVertex> hullV;   // the mesh's own vertices, then the new ones
    std::vector<uint32_t> hullI;
    std::vector<ModelVertex> paneV;   // compacted
    std::vector<uint32_t> paneI;
    int straddling = 0;
    int paneWhole = 0;
};

namespace glass_split {

// The pane mask (255 = pane, kr x kr) as a field in [0,1]: a 3x3 box blur, sampled bilinearly (wrapping).
struct Field {
    int kr = 0;
    std::vector<float> f;
    explicit Field(const std::vector<uint8_t>& g, int r) : kr(r), f(static_cast<size_t>(r) * r) {
        for (int y = 0; y < kr; ++y)
            for (int x = 0; x < kr; ++x) {
                int s = 0;
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int yy = (y + dy + kr) % kr, xx = (x + dx + kr) % kr;
                        s += g[static_cast<size_t>(yy) * kr + xx] ? 1 : 0;
                    }
                f[static_cast<size_t>(y) * kr + x] = s / 9.0f;
            }
    }
    float At(float u, float v) const {
        // texel centres at (i + 0.5) / kr
        float x = u * kr - 0.5f, y = v * kr - 0.5f;
        const float fx = std::floor(x), fy = std::floor(y);
        const float ax = x - fx, ay = y - fy;
        auto t = [&](int xi, int yi) {
            xi = ((xi % kr) + kr) % kr; yi = ((yi % kr) + kr) % kr;
            return f[static_cast<size_t>(yi) * kr + xi];
        };
        const int x0 = static_cast<int>(fx), y0 = static_cast<int>(fy);
        return (t(x0, y0) * (1 - ax) + t(x0 + 1, y0) * ax) * (1 - ay) + (t(x0, y0 + 1) * (1 - ax) + t(x0 + 1, y0 + 1) * ax) * ay;
    }
};

inline ModelVertex Lerp(const ModelVertex& a, const ModelVertex& b, float t) {
    ModelVertex o;
    o.x = a.x + (b.x - a.x) * t; o.y = a.y + (b.y - a.y) * t; o.z = a.z + (b.z - a.z) * t;
    o.nx = a.nx + (b.nx - a.nx) * t; o.ny = a.ny + (b.ny - a.ny) * t; o.nz = a.nz + (b.nz - a.nz) * t;
    const float l = std::sqrt(o.nx * o.nx + o.ny * o.ny + o.nz * o.nz);
    if (l > 1e-8f) { o.nx /= l; o.ny /= l; o.nz /= l; }
    o.u = a.u + (b.u - a.u) * t; o.v = a.v + (b.v - a.v) * t;
    return o;
}

struct Builder {
    const Field& field;
    GlassSplit& out;
    float maxEdge;   // leaf size in UV units
    void Emit(std::vector<ModelVertex>& V, std::vector<uint32_t>& I, const ModelVertex* p, int n) {
        if (n < 3) return;
        const uint32_t base = static_cast<uint32_t>(V.size());
        for (int k = 0; k < n; ++k) V.push_back(p[k]);
        for (int k = 1; k + 1 < n; ++k) I.insert(I.end(), {base, base + k, base + k + 1});
    }
    // Clip a leaf along the linear iso-line of its corner values: f >= 0.5 is pane.
    void Clip(const ModelVertex* t, const float* s) {
        ModelVertex in[5], outp[5];
        int ni = 0, no = 0;
        for (int k = 0; k < 3; ++k) {
            const int j = (k + 1) % 3;
            const bool a = s[k] >= 0.5f, b = s[j] >= 0.5f;
            if (a) in[ni++] = t[k]; else outp[no++] = t[k];
            if (a != b) {
                const float r = (0.5f - s[k]) / (s[j] - s[k]);
                const ModelVertex m = Lerp(t[k], t[j], r);
                in[ni++] = m; outp[no++] = m;
            }
        }
        Emit(out.paneV, out.paneI, in, ni);
        Emit(out.hullV, out.hullI, outp, no);
    }
    // 0: every sample under 0.5 (hull), 1: every sample at or over (pane), 2: mixed. About one sample a
    // texel over the UV footprint, at least the corners and 12 inner points.
    int Classify(const ModelVertex& a, const ModelVertex& b, const ModelVertex& c) const {
        const float du = (std::max)((std::max)(a.u, b.u), c.u) - (std::min)((std::min)(a.u, b.u), c.u);
        const float dv = (std::max)((std::max)(a.v, b.v), c.v) - (std::min)((std::min)(a.v, b.v), c.v);
        int n = static_cast<int>(std::ceil((std::max)(du, dv) * field.kr));
        n = (std::max)(4, (std::min)(n, 64));
        int over = 0, total = 0;
        for (int i = 0; i <= n; ++i)
            for (int j = 0; i + j <= n; ++j) {
                const float l0 = static_cast<float>(i) / n, l1 = static_cast<float>(j) / n, l2 = 1.0f - l0 - l1;
                over += field.At(l0 * a.u + l1 * b.u + l2 * c.u, l0 * a.v + l1 * b.v + l2 * c.v) >= 0.5f ? 1 : 0;
                ++total;
            }
        return over == 0 ? 0 : over == total ? 1 : 2;
    }
    void Whole(const ModelVertex& a, const ModelVertex& b, const ModelVertex& c, bool pane) {
        const ModelVertex t[3] = {a, b, c};
        if (pane) Emit(out.paneV, out.paneI, t, 3); else Emit(out.hullV, out.hullI, t, 3);
    }
    void Split(const ModelVertex& a, const ModelVertex& b, const ModelVertex& c, int depth) {
        auto len = [](const ModelVertex& p, const ModelVertex& q) { return std::hypot(p.u - q.u, p.v - q.v); };
        const float e = (std::max)((std::max)(len(a, b), len(b, c)), len(c, a));
        if (e <= maxEdge || depth >= 8) {
            const float s[3] = {field.At(a.u, a.v), field.At(b.u, b.v), field.At(c.u, c.v)};
            const ModelVertex t[3] = {a, b, c};
            Clip(t, s);
            return;
        }
        const ModelVertex ab = Lerp(a, b, 0.5f), bc = Lerp(b, c, 0.5f), ca = Lerp(c, a, 0.5f);
        const ModelVertex* sub[4][3] = {{&a, &ab, &ca}, {&ab, &b, &bc}, {&ca, &bc, &c}, {&ab, &bc, &ca}};
        for (auto& t : sub) {
            const int k = Classify(*t[0], *t[1], *t[2]);
            if (k == 2) Split(*t[0], *t[1], *t[2], depth + 1); else Whole(*t[0], *t[1], *t[2], k == 1);
        }
    }
};

}  // namespace glass_split

// g: the pane mask (kr x kr, nonzero = pane). A triangle is classified by the field on a grid over its UV
// footprint (about one sample per texel, at least the corners and 15 inner points): all under 0.5 = hull,
// all at or over = pane, otherwise it is split. UVs are taken as the triangle's own (unwrapped).
inline void SplitGlass(const std::vector<ModelVertex>& verts, const std::vector<uint32_t>& idx, const std::vector<uint8_t>& g, int kr,
                       GlassSplit* out) {
    glass_split::Field field(g, kr);
    out->hullV = verts;
    out->hullI.clear(); out->paneV.clear(); out->paneI.clear();
    glass_split::Builder b{field, *out, 1.5f / kr};
    std::vector<int> paneMap(verts.size(), -1);
    for (size_t k = 0; k + 2 < idx.size(); k += 3) {
        const ModelVertex& a = verts[idx[k]];
        const ModelVertex& bb = verts[idx[k + 1]];
        const ModelVertex& c = verts[idx[k + 2]];
        // A triangle across a UV seam (its footprint over half the atlas; Build skips those too) stays hull.
        const float du = (std::max)((std::max)(a.u, bb.u), c.u) - (std::min)((std::min)(a.u, bb.u), c.u);
        const float dv = (std::max)((std::max)(a.v, bb.v), c.v) - (std::min)((std::min)(a.v, bb.v), c.v);
        const int kind = (du > 0.5f || dv > 0.5f) ? 0 : b.Classify(a, bb, c);
        if (kind == 0) {
            out->hullI.insert(out->hullI.end(), {idx[k], idx[k + 1], idx[k + 2]});
        } else if (kind == 1) {
            ++out->paneWhole;
            for (int q = 0; q < 3; ++q) {
                const uint32_t vi = idx[k + q];
                if (paneMap[vi] < 0) { paneMap[vi] = static_cast<int>(out->paneV.size()); out->paneV.push_back(verts[vi]); }
                out->paneI.push_back(static_cast<uint32_t>(paneMap[vi]));
            }
        } else {
            ++out->straddling;
            b.Split(a, bb, c, 0);
        }
    }
}

}  // namespace gta2dx9
