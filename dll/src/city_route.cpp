// CITYMAP-1: surfaces, graphs, search, route lines and the map picture. See city_route.h.
#include "city_route.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <queue>

#include "../../src/gta2_map.h"

namespace gta2dx9 {
namespace citymap {
namespace {

// Edge order W, E, N, S; a cell step (dx, dy) -> its edge.
inline int EdgeOf(int dx, int dy) { return dx < 0 ? 0 : dx > 0 ? 1 : dy < 0 ? 2 : 3; }
inline int Opp(int e) { return e ^ 1; }
const int kDx[4] = {-1, 1, 0, 0}, kDy[4] = {0, 0, -1, 1};
// Arrow bits: 1 west, 2 east, 4 north (-y), 8 south; the red ones the same four bits up by 4.
const int kArrowDx[4] = {-1, 1, 0, 0}, kArrowDy[4] = {0, 0, -1, 1};
constexpr float kInf = 1e30f;

bool WaterTile(int t) { return t >= 608 && t <= 619; }

// Block z spans heights z..z+1. Slope pieces rise toward: up (north), down (south), left (west),
// right (east); 26-degree ramps in 2 pieces, 7-degree in 8, 45-degree in one.
bool EdgeHeights(int z, int slope, float eh[4], uint8_t* sideMask) {
    *sideMask = 0;
    if (slope == 0) { for (int i = 0; i < 4; ++i) eh[i] = z + 1.0f; return true; }
    int dir = -1; float lo = 0, hi = 1;
    if (slope >= 1 && slope <= 8) { dir = (slope - 1) / 2; const int k = (slope - 1) % 2; lo = k / 2.0f; hi = (k + 1) / 2.0f; }
    else if (slope >= 9 && slope <= 40) { dir = (slope - 9) / 8; const int k = (slope - 9) % 8; lo = k / 8.0f; hi = (k + 1) / 8.0f; }
    else if (slope >= 41 && slope <= 44) { dir = slope - 41; lo = 0; hi = 1; }
    else return false;   // diagonal and partial blocks: not a surface the route uses
    static const int kRiseEdge[4] = {2, 3, 0, 1};   // up -> N, down -> S, left -> W, right -> E
    const int e = kRiseEdge[dir];
    eh[e] = z + hi;
    eh[Opp(e)] = z + lo;
    for (int i = 0; i < 4; ++i)
        if (i != e && i != Opp(e)) { eh[i] = z + 0.5f * (lo + hi); *sideMask |= static_cast<uint8_t>(1 << i); }
    return true;
}

}  // namespace

void Csr::Build(int n, std::vector<std::pair<int, std::pair<int, float>>>& edges) {
    off.assign(static_cast<size_t>(n) + 1, 0);
    for (const auto& e : edges) ++off[static_cast<size_t>(e.first) + 1];
    for (int i = 0; i < n; ++i) off[i + 1] += off[i];
    to.assign(edges.size(), 0);
    cost.assign(edges.size(), 0.0f);
    std::vector<int> fill(off.begin(), off.end() - 1);
    for (const auto& e : edges) {
        const int k = fill[e.first]++;
        to[k] = e.second.first;
        cost[k] = e.second.second;
    }
}

void Cells::Load(const gta2::Map& map) {
    const size_t n = static_cast<size_t>(kLevels) * kW * kH;
    valid.assign(n, 0); ground.assign(n, 0); slope.assign(n, 0); arrows.assign(n, 0);
    wallMask.assign(n, 0); sideMask.assign(n, 0); lid.assign(n, 0);
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x) {
            const gta2::Column& col = map.ColumnAt(x, y);
            for (size_t i = 0; i < col.blocks.size(); ++i) {
                const int z = col.offset + static_cast<int>(i);
                if (z < 0 || z >= kLevels || col.blocks[i] >= map.BlockCount()) continue;
                const gta2::Block& b = map.BlockAt(col.blocks[i]);
                const size_t k = At(z, y, x);
                valid[k] = 1;
                lid[k] = static_cast<uint16_t>(b.lid.Tile());
                ground[k] = static_cast<uint8_t>(b.GroundType());
                slope[k] = static_cast<uint8_t>(b.SlopeType());
                arrows[k] = b.arrows;
                const gta2::Face* f[4] = {&b.left, &b.right, &b.top, &b.bottom};   // W, E, N, S
                for (int e = 0; e < 4; ++e) {
                    if (f[e]->IsWall()) wallMask[k] |= static_cast<uint8_t>(1 << e);
                    if (f[e]->Tile()) sideMask[k] |= static_cast<uint8_t>(1 << e);
                }
            }
        }
}

void Cells::Clear() {
    std::vector<uint8_t>().swap(valid); std::vector<uint8_t>().swap(ground); std::vector<uint8_t>().swap(slope);
    std::vector<uint8_t>().swap(arrows); std::vector<uint8_t>().swap(wallMask); std::vector<uint8_t>().swap(sideMask);
    std::vector<uint16_t>().swap(lid);
}

bool Level::Build(const gta2::Map& map, const std::vector<uint8_t>& zoneChunk) {
    ready_ = false;
    nodes_.clear();
    cells.Load(map);
    // zones
    zones_.clear();
    for (size_t p = 0; p + 6 <= zoneChunk.size();) {
        Zone z;
        z.type = zoneChunk[p]; z.x = zoneChunk[p + 1]; z.y = zoneChunk[p + 2]; z.w = zoneChunk[p + 3]; z.h = zoneChunk[p + 4];
        const int nl = zoneChunk[p + 5];
        if (p + 6 + nl > zoneChunk.size()) break;
        z.key.assign(reinterpret_cast<const char*>(&zoneChunk[p + 6]), nl);
        p += 6 + nl;
        zones_.push_back(z);
    }
    // surfaces, grouped by cell
    cellFirst_.assign(static_cast<size_t>(kW) * kH + 1, 0);
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x) {
            cellFirst_[static_cast<size_t>(y) * kW + x] = static_cast<int>(nodes_.size());
            for (int z = 0; z < kLevels; ++z) {
                const size_t k = cells.At(z, y, x);
                if (!cells.valid[k] || !cells.lid[k] || !cells.ground[k] || WaterTile(cells.lid[k])) continue;
                if (z + 1 < kLevels) {
                    const size_t u = cells.At(z + 1, y, x);
                    if (cells.valid[u] && cells.wallMask[u] && cells.lid[u] && cells.ground[u] == 0) continue;   // built over
                }
                Node n;
                n.x = static_cast<uint8_t>(x); n.y = static_cast<uint8_t>(y); n.z = static_cast<uint8_t>(z);
                n.ground = cells.ground[k]; n.slope = cells.slope[k]; n.arrows = cells.arrows[k];
                if (!EdgeHeights(z, n.slope, n.eh, &n.sideMask)) continue;
                nodes_.push_back(n);
            }
        }
    cellFirst_[static_cast<size_t>(kW) * kH] = static_cast<int>(nodes_.size());
    const int N = static_cast<int>(nodes_.size());
    std::vector<std::pair<int, std::pair<int, float>>> car, walk;
    car.reserve(static_cast<size_t>(N)); walk.reserve(static_cast<size_t>(N) * 4);
    roads_ = 0;
    static const float kWalkCost[4] = {1.0f, 1.35f, 1.0f, 1.15f};   // by ground: -, road, pavement, field
    for (int a = 0; a < N; ++a) {
        const Node& na = nodes_[a];
        for (int e = 0; e < 4; ++e) {
            const int b = MatchAcross(a, kDx[e], kDy[e]);
            if (b < 0 || Walled(a, kDx[e], kDy[e])) continue;
            walk.push_back({a, {b, 0.5f * (kWalkCost[na.ground] + kWalkCost[nodes_[b].ground])}});
        }
        if (na.ground != 1) continue;
        ++roads_;
        const int green = na.arrows & 15, red = (na.arrows >> 4) & 15;
        float move[4] = {-1, -1, -1, -1};
        for (int i = 0; i < 4; ++i) {
            if (green & (1 << i)) move[i] = 1.0f;
            else if (red & (1 << i)) move[i] = 1.0f;   // red arrows (bil's flyovers): roads like any other
        }
        if (!green && !red) for (int i = 0; i < 4; ++i) move[i] = 1.4f;   // car parks, yards: any way, dearer
        const size_t first = car.size();
        for (int i = 0; i < 4; ++i) {
            if (move[i] < 0) continue;
            const int b = MatchAcross(a, kArrowDx[i], kArrowDy[i]);
            if (b >= 0 && nodes_[b].ground == 1) car.push_back({a, {b, move[i]}});
        }
        // a lane change: sideways onto a lane that runs the same way
        for (int i = 0; i < 4; ++i) {
            if (!(green & (1 << i))) continue;
            const int px[2] = {kArrowDy[i], -kArrowDy[i]}, py[2] = {kArrowDx[i], -kArrowDx[i]};
            for (int s = 0; s < 2; ++s) {
                const int b = MatchAcross(a, px[s], py[s]);
                if (b < 0 || nodes_[b].ground != 1 || !(nodes_[b].arrows & (1 << i))) continue;
                bool have = false;
                for (size_t k = first; k < car.size(); ++k) have = have || car[k].second.first == b;
                if (!have) car.push_back({a, {b, 1.6f}});
            }
        }
    }
    adj_[kCar].Build(N, car);
    adj_[kWalk].Build(N, walk);
    for (auto& e : car) std::swap(e.first, e.second.first);
    rev_[kCar].Build(N, car);
    rev_[kWalk] = adj_[kWalk];   // symmetric costs
    Scc(kCar);
    Scc(kWalk);
    ready_ = true;
    return true;
}

int Level::MainCount(Mode m) const {
    int c = 0;
    for (uint8_t v : main_[m]) c += v;
    return c;
}

int Level::MatchAcross(int a, int dx, int dy) const {
    const Node& na = nodes_[a];
    const int nx = na.x + dx, ny = na.y + dy;
    if (nx < 0 || ny < 0 || nx >= kW || ny >= kH) return -1;
    const int ea = EdgeOf(dx, dy), eb = Opp(ea);
    const bool aSide = (na.sideMask >> ea) & 1;
    int best = -1;
    const size_t c = static_cast<size_t>(ny) * kW + nx;
    for (int b = cellFirst_[c]; b < cellFirst_[c + 1]; ++b) {
        const Node& nb = nodes_[b];
        const bool bSide = (nb.sideMask >> eb) & 1;
        if (aSide || bSide) {
            if (aSide && bSide && nb.slope == na.slope && nb.z == na.z) best = b;
            continue;
        }
        if (std::fabs(na.eh[ea] - nb.eh[eb]) < 0.06f) best = b;
    }
    return best;
}

bool Level::Walled(int a, int dx, int dy) const {
    const Node& n = nodes_[a];
    const int lv = n.z + 1;
    if (lv >= kLevels) return false;
    const int ea = EdgeOf(dx, dy);
    const size_t here = cells.At(lv, n.y, n.x), there = cells.At(lv, n.y + dy, n.x + dx);
    if (cells.valid[here] && ((cells.wallMask[here] >> ea) & 1)) return true;
    if (cells.valid[there] && ((cells.wallMask[there] >> Opp(ea)) & 1)) return true;
    return false;
}

void Level::Scc(Mode m) {
    // Kosaraju, iterative: the largest strongly connected set among the mode's grounds.
    const int N = static_cast<int>(nodes_.size());
    std::vector<uint8_t> inc(static_cast<size_t>(N), 0);
    for (int i = 0; i < N; ++i) inc[i] = WantGround(m, nodes_[i].ground) ? 1 : 0;
    const Csr& f = adj_[m];
    const Csr& r = rev_[m];
    std::vector<uint8_t> seen(static_cast<size_t>(N), 0);
    std::vector<int> order;
    order.reserve(static_cast<size_t>(N));
    std::vector<std::pair<int, int>> stack;
    for (int s = 0; s < N; ++s) {
        if (!inc[s] || seen[s]) continue;
        seen[s] = 1;
        stack.push_back({s, f.off[s]});
        while (!stack.empty()) {
            int u = stack.back().first, k = stack.back().second;
            while (k < f.off[u + 1] && (seen[f.to[k]] || !inc[f.to[k]])) ++k;
            if (k < f.off[u + 1]) {
                stack.back().second = k + 1;
                const int v = f.to[k];
                seen[v] = 1;
                stack.push_back({v, f.off[v]});
            } else {
                stack.pop_back();
                order.push_back(u);
            }
        }
    }
    std::vector<int> comp(static_cast<size_t>(N), -1);
    int best = -1, bestSize = 0, c = 0;
    std::vector<int> st;
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        if (comp[*it] >= 0) continue;
        st.push_back(*it);
        comp[*it] = c;
        int size = 0;
        while (!st.empty()) {
            const int u = st.back(); st.pop_back(); ++size;
            for (int k = r.off[u]; k < r.off[u + 1]; ++k) {
                const int v = r.to[k];
                if (inc[v] && comp[v] < 0) { comp[v] = c; st.push_back(v); }
            }
        }
        if (size > bestSize) { bestSize = size; best = c; }
        ++c;
    }
    main_[m].assign(static_cast<size_t>(N), 0);
    for (int i = 0; i < N; ++i) main_[m][i] = comp[i] == best && best >= 0 ? 1 : 0;
}

int Level::Snap(float fx, float fy, float zHint, Mode m, int radius, bool mainOnly) const {
    if (!ready_) return -1;
    int best = -1;
    float bd = kInf;
    const int cx = static_cast<int>(std::floor(fx)), cy = static_cast<int>(std::floor(fy));
    for (int r = 0; r <= radius; ++r) {
        for (int dy = -r; dy <= r; ++dy)
            for (int dx = -r; dx <= r; ++dx) {
                if ((std::max)(std::abs(dx), std::abs(dy)) != r) continue;
                const int x = cx + dx, y = cy + dy;
                if (x < 0 || y < 0 || x >= kW || y >= kH) continue;
                const size_t c = static_cast<size_t>(y) * kW + x;
                int pick = -1;
                for (int i = cellFirst_[c]; i < cellFirst_[c + 1]; ++i) {
                    if (!WantGround(m, nodes_[i].ground) || (mainOnly && !main_[m][i])) continue;
                    if (pick < 0) { pick = i; continue; }
                    if (zHint < 0 ? nodes_[i].z > nodes_[pick].z
                                  : std::fabs(nodes_[i].z + 1 - zHint) < std::fabs(nodes_[pick].z + 1 - zHint)) pick = i;
                }
                if (pick < 0) continue;
                float d = std::hypot(x + 0.5f - fx, y + 0.5f - fy);
                if (zHint >= 0) d += 2.0f * std::fabs(nodes_[pick].z + 1 - zHint);
                if (d < bd) { bd = d; best = pick; }
            }
        if (best >= 0 && r >= bd + 1) break;
    }
    return best;
}

void Level::CostTo(int goal, Mode m, std::vector<float>* dist, std::vector<int>* next) const {
    const int N = static_cast<int>(nodes_.size());
    dist->assign(static_cast<size_t>(N), kInf);
    next->assign(static_cast<size_t>(N), -1);
    if (goal < 0 || goal >= N) return;
    const Csr& r = rev_[m];
    typedef std::pair<float, int> Item;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> pq;
    (*dist)[goal] = 0.0f;
    pq.push({0.0f, goal});
    while (!pq.empty()) {
        const Item it = pq.top(); pq.pop();
        const int u = it.second;
        if (it.first > (*dist)[u]) continue;
        for (int k = r.off[u]; k < r.off[u + 1]; ++k) {
            const int v = r.to[k];
            const float nd = it.first + r.cost[k];
            if (nd < (*dist)[v]) { (*dist)[v] = nd; (*next)[v] = u; pq.push({nd, v}); }
        }
    }
}

int Level::StartNode(float px, float py, float pz, float heading, Mode m, const std::vector<float>& dist) const {
    const bool haveHeading = !std::isnan(heading);
    const float hx = haveHeading ? std::sin(heading) : 0.0f, hy = haveHeading ? -std::cos(heading) : 0.0f;
    int best = -1;
    float bc = kInf;
    for (int R = 4; best < 0 && R <= 24; R *= 2) {
        const int cx = static_cast<int>(std::floor(px)), cy = static_cast<int>(std::floor(py));
        for (int y = cy - R; y <= cy + R; ++y)
            for (int x = cx - R; x <= cx + R; ++x) {
                if (x < 0 || y < 0 || x >= kW || y >= kH) continue;
                const size_t c = static_cast<size_t>(y) * kW + x;
                for (int i = cellFirst_[c]; i < cellFirst_[c + 1]; ++i) {
                    const Node& n = nodes_[i];
                    if (!WantGround(m, n.ground) || dist[i] >= kInf) continue;
                    const float off = std::hypot(n.x + 0.5f - px, n.y + 0.5f - py) + 3.0f * std::fabs(n.z + 1 - pz);
                    float pen = 0.0f;
                    if (m == kCar && haveHeading && (n.arrows & 15)) {
                        float bestDot = -1.0f;
                        for (int b = 0; b < 4; ++b)
                            if (n.arrows & (1 << b)) bestDot = (std::max)(bestDot, kArrowDx[b] * hx + kArrowDy[b] * hy);
                        pen = (1.0f - bestDot) * 6.0f;   // the lane against him: about a block's loop to turn round
                    }
                    const float cst = dist[i] + off * 2.0f + pen;
                    if (cst < bc) { bc = cst; best = i; }
                }
            }
    }
    return best;
}

int Level::NearestReaching(float px, float py, float pz, const std::vector<float>& dist, float* hop) const {
    int best = -1;
    float bd = kInf;
    for (int i = 0; i < static_cast<int>(nodes_.size()); ++i) {
        if (dist[i] >= kInf) continue;
        const Node& n = nodes_[i];
        const float d = std::hypot(n.x + 0.5f - px, n.y + 0.5f - py) + 3.0f * std::fabs(n.z + 1 - pz);
        if (d < bd) { bd = d; best = i; }
    }
    if (hop) *hop = bd;
    return best;
}

std::vector<int> Level::Path(int start, const std::vector<int>& next) const {
    std::vector<int> out;
    if (start < 0) return out;
    out.push_back(start);
    while (next[out.back()] >= 0 && out.size() < 100000) out.push_back(next[out.back()]);
    return out;
}

float Level::CrossOffset(int x, int y, int z, int dx, int dy, Mode m) const {
    const int px = -dy, py = dx;
    auto ok = [&](int cx, int cy) {
        if (cx < 0 || cy < 0 || cx >= kW || cy >= kH) return false;
        const size_t c = static_cast<size_t>(cy) * kW + cx;
        for (int i = cellFirst_[c]; i < cellFirst_[c + 1]; ++i)
            if (WantGround(m, nodes_[i].ground) && std::abs(nodes_[i].z - z) <= 1) return true;
        return false;
    };
    int a = 0, b = 0;
    while (a < 8 && ok(x + px * (a + 1), y + py * (a + 1))) ++a;
    while (b < 8 && ok(x - px * (b + 1), y - py * (b + 1))) ++b;
    return (a - b) / 2.0f;
}

void Level::Polyline(const std::vector<int>& path, bool centre, Mode m, std::vector<float>* xs, std::vector<float>* ys,
                     std::vector<float>* zs) const {
    xs->clear(); ys->clear(); if (zs) zs->clear();
    if (path.empty()) return;
    struct P { int x, y, z; float h; };
    std::vector<P> pts;
    for (int i : path) {
        const Node& n = nodes_[i];
        pts.push_back({n.x, n.y, n.z, 0.25f * (n.eh[0] + n.eh[1] + n.eh[2] + n.eh[3])});
    }
    if (pts.size() < 2) {
        xs->push_back(pts[0].x + 0.5f); ys->push_back(pts[0].y + 0.5f); if (zs) zs->push_back(pts[0].h);
        return;
    }
    struct Run { int dx, dy; std::vector<P> cells; float ax, ay; };
    std::vector<Run> runs;
    for (size_t k = 1; k < pts.size(); ++k) {
        const int dx = pts[k].x - pts[k - 1].x, dy = pts[k].y - pts[k - 1].y;
        if (!runs.empty() && runs.back().dx == dx && runs.back().dy == dy) runs.back().cells.push_back(pts[k]);
        else runs.push_back({dx, dy, {pts[k - 1], pts[k]}, 0, 0});
    }
    for (Run& r : runs) {
        float o = 0.0f;
        if (centre) {
            std::vector<float> offs;
            const size_t lo = r.cells.size() > 2 ? 1 : 0, hi = r.cells.size() > 2 ? r.cells.size() - 1 : r.cells.size();
            for (size_t i = lo; i < hi; ++i) offs.push_back(CrossOffset(r.cells[i].x, r.cells[i].y, r.cells[i].z, r.dx, r.dy, m));
            std::sort(offs.begin(), offs.end());
            o = offs[offs.size() / 2];
        }
        const float px = static_cast<float>(-r.dy), py = static_cast<float>(r.dx);
        r.ax = r.cells[0].x + 0.5f + px * o;
        r.ay = r.cells[0].y + 0.5f + py * o;
    }
    // fold short sideways jogs (lane changes) whose neighbours line up
    for (size_t k = 1; k + 1 < runs.size();) {
        Run &r0 = runs[k - 1], &r1 = runs[k], &r2 = runs[k + 1];
        if (r0.dx == r2.dx && r0.dy == r2.dy && r1.cells.size() <= 3 && (r1.dx != r0.dx || r1.dy != r0.dy) &&
            r1.dx * r0.dx + r1.dy * r0.dy == 0) {
            const float px = static_cast<float>(-r0.dy), py = static_cast<float>(r0.dx);
            const float lat0 = r0.ax * px + r0.ay * py, lat2 = r2.ax * px + r2.ay * py;
            if (std::fabs(lat0 - lat2) < 0.75f || centre) {
                r0.cells.insert(r0.cells.end(), r1.cells.begin() + 1, r1.cells.end());
                r0.cells.insert(r0.cells.end(), r2.cells.begin() + 1, r2.cells.end());
                runs.erase(runs.begin() + k, runs.begin() + k + 2);
                continue;
            }
        }
        ++k;
    }
    auto push = [&](float x, float y, float h) { xs->push_back(x); ys->push_back(y); if (zs) zs->push_back(h); };
    auto onLine = [](const Run& r, float cx, float cy, float* ox, float* oy) {
        const float px = static_cast<float>(-r.dy), py = static_cast<float>(r.dx);
        const float lat = r.ax * px + r.ay * py, c = cx * px + cy * py;
        *ox = cx + px * (lat - c); *oy = cy + py * (lat - c);
    };
    float x, y;
    onLine(runs[0], runs[0].cells[0].x + 0.5f, runs[0].cells[0].y + 0.5f, &x, &y);
    push(x, y, runs[0].cells[0].h);
    for (size_t k = 1; k < runs.size(); ++k) {
        const Run &a = runs[k - 1], &b = runs[k];
        const float h = b.cells[0].h;
        if (a.dx * b.dx + a.dy * b.dy == 0) {
            if (a.dx == 0) push(a.ax, b.ay, h);
            else push(b.ax, a.ay, h);
        } else {
            const float cx = b.cells[0].x + 0.5f, cy = b.cells[0].y + 0.5f;
            onLine(a, cx, cy, &x, &y); push(x, y, h);
            onLine(b, cx, cy, &x, &y); push(x, y, h);
        }
    }
    const Run& last = runs.back();
    onLine(last, last.cells.back().x + 0.5f, last.cells.back().y + 0.5f, &x, &y);
    push(x, y, last.cells.back().h);
}

std::string Level::DistrictKeyAt(int x, int y) const {
    std::string best;
    int ba = 1 << 30;
    for (const Zone& z : zones_) {
        const bool district = z.type == 1 || (z.type == 15 && !z.key.empty() && (z.key[0] == 'm' || z.key[0] == 'M'));
        if (!district || x < z.x || y < z.y || x >= z.x + z.w || y >= z.y + z.h) continue;
        if (z.w * z.h < ba) { ba = z.w * z.h; best = z.key; }
    }
    return best;
}

// ---- lines ---------------------------------------------------------------------------------

void Fillet(const std::vector<float>& xs, const std::vector<float>& ys, float r, int seg, std::vector<float>* ox, std::vector<float>* oy) {
    ox->clear(); oy->clear();
    const size_t n = xs.size();
    if (n < 3) { *ox = xs; *oy = ys; return; }
    ox->push_back(xs[0]); oy->push_back(ys[0]);
    for (size_t k = 1; k + 1 < n; ++k) {
        const float ax = xs[k - 1], ay = ys[k - 1], bx = xs[k], by = ys[k], cx = xs[k + 1], cy = ys[k + 1];
        const float la = std::hypot(bx - ax, by - ay), lc = std::hypot(cx - bx, cy - by);
        if (la < 1e-6f || lc < 1e-6f) continue;
        const float rr = (std::min)(r, (std::min)(la / 2, lc / 2));
        const float p0x = bx + (ax - bx) / la * rr, p0y = by + (ay - by) / la * rr;
        const float p2x = bx + (cx - bx) / lc * rr, p2y = by + (cy - by) / lc * rr;
        for (int i = 0; i <= seg; ++i) {
            const float t = static_cast<float>(i) / seg;
            ox->push_back((1 - t) * (1 - t) * p0x + 2 * (1 - t) * t * bx + t * t * p2x);
            oy->push_back((1 - t) * (1 - t) * p0y + 2 * (1 - t) * t * by + t * t * p2y);
        }
    }
    ox->push_back(xs[n - 1]); oy->push_back(ys[n - 1]);
}

float Length(const std::vector<float>& xs, const std::vector<float>& ys) {
    float s = 0;
    for (size_t k = 1; k < xs.size(); ++k) s += std::hypot(xs[k] - xs[k - 1], ys[k] - ys[k - 1]);
    return s;
}

bool NextTurn(const std::vector<float>& xs, const std::vector<float>& ys, float* dist, int* dir) {
    float acc = 0;
    for (size_t k = 1; k + 1 < xs.size(); ++k) {
        const float v1x = xs[k] - xs[k - 1], v1y = ys[k] - ys[k - 1], v2x = xs[k + 1] - xs[k], v2y = ys[k + 1] - ys[k];
        acc += std::hypot(v1x, v1y);
        const float n1 = std::hypot(v1x, v1y), n2 = std::hypot(v2x, v2y);
        if (n1 < 1e-6f || n2 < 1e-6f) continue;
        const float cr = (v1x * v2y - v1y * v2x) / (n1 * n2), dt = (v1x * v2x + v1y * v2y) / (n1 * n2);
        const float ang = std::atan2(cr, dt) * 57.29578f;
        if (std::fabs(ang) > 35.0f && n2 > 1.5f && acc > 1.0f) {
            *dist = acc;
            *dir = ang > 0 ? 1 : -1;   // y down: clockwise = right
            return true;
        }
    }
    return false;
}

void CutAt(const std::vector<float>& xs, const std::vector<float>& ys, const std::vector<float>* zs, float px, float py, int window,
           std::vector<float>* ox, std::vector<float>* oy, std::vector<float>* oz, float* offLine) {
    ox->clear(); oy->clear(); if (oz) oz->clear();
    if (xs.empty()) { if (offLine) *offLine = 1e9f; return; }
    if (xs.size() == 1) { *ox = xs; *oy = ys; if (oz && zs) *oz = *zs; if (offLine) *offLine = std::hypot(xs[0] - px, ys[0] - py); return; }
    size_t bk = 1; float bt = 0, bd = 1e30f;
    const size_t lim = (std::min)(xs.size(), static_cast<size_t>(window) + 1);
    for (size_t k = 1; k < lim; ++k) {
        const float ax = xs[k - 1], ay = ys[k - 1], dx = xs[k] - ax, dy = ys[k] - ay;
        const float L2 = dx * dx + dy * dy;
        float t = L2 > 1e-9f ? ((px - ax) * dx + (py - ay) * dy) / L2 : 0.0f;
        t = (std::max)(0.0f, (std::min)(1.0f, t));
        const float d = std::hypot(ax + dx * t - px, ay + dy * t - py);
        if (d < bd) { bd = d; bk = k; bt = t; }
    }
    ox->push_back(xs[bk - 1] + (xs[bk] - xs[bk - 1]) * bt);
    oy->push_back(ys[bk - 1] + (ys[bk] - ys[bk - 1]) * bt);
    if (oz && zs) oz->push_back((*zs)[bk - 1] + ((*zs)[bk] - (*zs)[bk - 1]) * bt);
    for (size_t k = bk; k < xs.size(); ++k) { ox->push_back(xs[k]); oy->push_back(ys[k]); if (oz && zs) oz->push_back((*zs)[k]); }
    if (offLine) *offLine = bd;
}

// ---- the picture ---------------------------------------------------------------------------

namespace {
struct Rgb { float r, g, b; };
const Rgb kVoid = {7, 9, 13}, kWater = {14, 44, 66}, kWaterLine = {22, 60, 86}, kPave = {31, 36, 46}, kPark = {24, 50, 34};
const Rgb kBld[3] = {{45, 52, 67}, {54, 63, 81}, {64, 75, 96}};
const Rgb kRoad = {198, 203, 212}, kRoadEdge = {120, 126, 138}, kRail = {92, 74, 58};
}  // namespace

void Level::Bake(int S, bool gammaFix, std::vector<uint32_t>* out) const {
    const Cells& C = cells;
    // ---- classify each cell by its top surface
    std::vector<int8_t> top(static_cast<size_t>(kW) * kH, -1);
    auto has = [&](int z, int y, int x) {
        const size_t k = C.At(z, y, x);
        if (!C.lid[k] || C.lid[k] == 1023) return false;   // 1023: the overhead cables' tile
        // the wires: sideless air or 45-degree pieces up high with nothing under them
        if (z >= 3 && !C.sideMask[k]) {
            const size_t b = C.At(z - 1, y, x);
            const bool belowEmpty = !(C.lid[b] || C.sideMask[b]);
            if (belowEmpty && (C.slope[k] >= 41 || C.ground[k] == 0)) return false;
        }
        return true;
    };
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x)
            for (int z = kLevels - 1; z >= 0; --z)
                if (has(z, y, x)) { top[static_cast<size_t>(y) * kW + x] = static_cast<int8_t>(z); break; }
    std::vector<uint8_t> cls(static_cast<size_t>(kW) * kH, 0), hgt(static_cast<size_t>(kW) * kH, 0);
    std::vector<uint8_t> elevated(cls.size(), 0), cover(cls.size(), 0), rail(cls.size(), 0);
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x) {
            const size_t i = static_cast<size_t>(y) * kW + x;
            const int t = top[i], tz = (std::max)(0, t);
            const size_t k = C.At(tz, y, x);
            const int g = C.ground[k], lt = C.lid[k];
            const bool water = WaterTile(lt) || t <= 0;
            uint8_t c = 0;
            if ((g == 2 && t <= 2) || (g == 0 && t <= 1)) c = 2;
            if (g == 3 && t <= 2) c = 3;
            if ((g == 0 && t >= 2) || (g == 2 && t >= 3) || (g == 3 && t >= 3)) { c = 4; hgt[i] = static_cast<uint8_t>((std::min)(4, (std::max)(0, t - 2))); }
            if (g == 1) c = 5;
            if (water) c = 1;
            cls[i] = c;
            elevated[i] = c == 5 && t >= 2;
        }
    // one-cell speckle (a lamp, a pillar, a vent) merged into its surroundings
    for (int pass = 0; pass < 2; ++pass) {
        std::vector<uint8_t> c2 = cls;
        for (int y = 1; y + 1 < kH; ++y)
            for (int x = 1; x + 1 < kW; ++x) {
                const uint8_t t = cls[static_cast<size_t>(y) * kW + x];
                if (t == 5 || t == 1) continue;
                if (cls[static_cast<size_t>(y - 1) * kW + x] == t || cls[static_cast<size_t>(y + 1) * kW + x] == t ||
                    cls[static_cast<size_t>(y) * kW + x - 1] == t || cls[static_cast<size_t>(y) * kW + x + 1] == t) continue;
                int n[6] = {};
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx)
                        if (dx || dy) ++n[cls[static_cast<size_t>(y + dy) * kW + x + dx]];
                int best = 0;
                for (int k = 1; k < 6; ++k) if (n[k] > n[best]) best = k;
                if (n[best] >= 5 && best != 5) c2[static_cast<size_t>(y) * kW + x] = static_cast<uint8_t>(best);
            }
        cls.swap(c2);
    }
    // roads something passes over (a viaduct, a deck, a tunnel's roof): road under it
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x) {
            bool base = false;
            for (int z = 1; z < 7 && !base; ++z) {
                const size_t k = C.At(z, y, x);
                if (C.ground[k] != 1 || !C.lid[k]) continue;
                const size_t u = C.At(z + 1, y, x);
                const bool built = C.valid[u] && C.lid[u] && C.ground[u] == 0 && C.wallMask[u];
                if (!built) base = true;
            }
            const size_t i = static_cast<size_t>(y) * kW + x;
            cover[i] = base && cls[i] != 5;
        }
    {   // a lamp head or a sign over the kerb is not an overpass: covers of under 4 cells dropped
        std::vector<uint8_t> seen(cover.size(), 0);
        std::vector<int> comp, q;
        for (size_t s = 0; s < cover.size(); ++s) {
            if (!cover[s] || seen[s]) continue;
            comp.clear(); q.clear(); q.push_back(static_cast<int>(s)); seen[s] = 1;
            while (!q.empty()) {
                const int c = q.back(); q.pop_back(); comp.push_back(c);
                const int x = c % kW, y = c / kW;
                const int nb[4][2] = {{x + 1, y}, {x - 1, y}, {x, y + 1}, {x, y - 1}};
                for (auto& p : nb) {
                    if (p[0] < 0 || p[1] < 0 || p[0] >= kW || p[1] >= kH) continue;
                    const size_t j = static_cast<size_t>(p[1]) * kW + p[0];
                    if (cover[j] && !seen[j]) { seen[j] = 1; q.push_back(static_cast<int>(j)); }
                }
            }
            if (comp.size() < 4) for (int c : comp) { cover[c] = 0; cls[c] = 5; }
        }
    }
    {   // building heights in three steps, a 3x3 majority so a roof reads as one plate
        std::vector<uint8_t> hq(cls.size(), 0), h2(cls.size(), 0);
        for (size_t i = 0; i < cls.size(); ++i) hq[i] = cls[i] == 4 ? static_cast<uint8_t>((std::min)(static_cast<int>(hgt[i]), 4) / 2 + 1) : 0;
        for (int y = 0; y < kH; ++y)
            for (int x = 0; x < kW; ++x) {
                const size_t i = static_cast<size_t>(y) * kW + x;
                if (cls[i] != 4) continue;
                int n[4] = {};
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int xx = x + dx, yy = y + dy;
                        if (xx < 0 || yy < 0 || xx >= kW || yy >= kH) { ++n[0]; continue; }
                        ++n[hq[static_cast<size_t>(yy) * kW + xx]];
                    }
                int best = 1;
                for (int k = 2; k < 4; ++k) if (n[k] > n[best]) best = k;
                h2[i] = static_cast<uint8_t>((n[best] >= 5 ? best : hq[i]) - 1);
            }
        hgt.swap(h2);
    }
    {   // the railway: flood from the track zones over the track band of lid tiles (540..600)
        std::vector<uint8_t> seen(cls.size(), 0);
        std::vector<std::pair<int, int>> st;
        auto lidTop = [&](int x, int y) { const int t = top[static_cast<size_t>(y) * kW + x]; return static_cast<int>(C.lid[C.At((std::max)(0, t), y, x)]); };
        for (const Zone& z : zones_) {
            std::string k = z.key;
            for (char& ch : k) ch = static_cast<char>(tolower(static_cast<unsigned char>(ch)));
            if (k.compare(0, 4, "trak") != 0) continue;
            for (int y = z.y; y < z.y + z.h; ++y) for (int x = z.x; x < z.x + z.w; ++x) st.push_back({x, y});
        }
        while (!st.empty()) {
            const auto [x, y] = st.back(); st.pop_back();
            if (x < 0 || y < 0 || x >= kW || y >= kH) continue;
            const size_t i = static_cast<size_t>(y) * kW + x;
            if (seen[i]) continue;
            seen[i] = 1;
            const int t = lidTop(x, y);
            if (t < 540 || t > 600) continue;
            rail[i] = 1;
            const int nb[4][2] = {{x + 1, y}, {x - 1, y}, {x, y + 1}, {x, y - 1}};
            for (auto& p : nb) {
                if (p[0] < 0 || p[1] < 0 || p[0] >= kW || p[1] >= kH) continue;
                const int tt = lidTop(p[0], p[1]);
                if (tt >= 540 && tt <= 600 && std::abs(top[static_cast<size_t>(p[1]) * kW + p[0]] - top[i]) <= 1) st.push_back({p[0], p[1]});
            }
        }
        // road lids no car reaches and no arrow runs on, up in the air: the elevated railway's bed
        for (size_t n = 0; n < nodes_.size(); ++n) {
            const Node& nd = nodes_[n];
            const size_t i = static_cast<size_t>(nd.y) * kW + nd.x;
            if (nd.ground == 1 && nd.arrows == 0 && nd.z >= 3 && !main_[kCar][n] && top[i] == nd.z) { rail[i] = 1; cls[i] = 2; }
        }
    }
    // ---- paint at S pixels a cell, straight into the output (linear 0..255 ARGB; the LUT last)
    const int N = kW * S;
    out->assign(static_cast<size_t>(N) * N, 0xFF000000u);
    std::vector<uint32_t>& img = *out;
    auto pack = [](float r, float g, float b) {
        auto q = [](float v) { return static_cast<uint32_t>((std::max)(0.0f, (std::min)(255.0f, v)) + 0.5f); };
        return 0xFF000000u | (q(r) << 16) | (q(g) << 8) | q(b);
    };
    auto pk = [&](const Rgb& c) { return pack(c.r, c.g, c.b); };
    auto R_ = [](uint32_t v) { return static_cast<float>((v >> 16) & 255); };
    auto G_ = [](uint32_t v) { return static_cast<float>((v >> 8) & 255); };
    auto B_ = [](uint32_t v) { return static_cast<float>(v & 255); };
    auto cellOf = [&](int px, int py) { return static_cast<size_t>(py / S) * kW + px / S; };
    for (int py = 0; py < N; ++py)
        for (int px = 0; px < N; ++px) {
            const size_t p = static_cast<size_t>(py) * N + px;
            switch (cls[cellOf(px, py)]) {
                case 1: img[p] = pk(py % 6 == 0 ? kWaterLine : kWater); break;
                case 2: img[p] = pk(kPave); break;
                case 3: img[p] = pk(kPark); break;
                default: img[p] = pk(kVoid); break;
            }
        }
    auto isB = [&](int px, int py) { return px >= 0 && py >= 0 && px < N && py < N && cls[cellOf(px, py)] == 4; };
    auto isR = [&](int px, int py) {
        if (px < 0 || py < 0 || px >= N || py >= N) return false;
        const size_t c = cellOf(px, py);
        return cls[c] == 5 || cover[c];
    };
    {   // building shadow to the bottom right, longer for taller blocks, softened (two box passes)
        std::vector<uint8_t> sh(static_cast<size_t>(N) * N, 0), tmp(sh.size(), 0);
        for (int py = 0; py < N; ++py)
            for (int px = 0; px < N; ++px) {
                float v = 0;
                for (int h = 0; h < 3; ++h) {
                    const int off = static_cast<int>(S * (0.25f + 0.12f * h));
                    const int sx = px - off, sy = py - off;
                    if (isB(sx, sy) && hgt[cellOf(sx, sy)] == h) v = (std::max)(v, 0.55f + 0.06f * h);
                }
                sh[static_cast<size_t>(py) * N + px] = static_cast<uint8_t>(v * 255.0f);
            }
        const int r = (std::max)(1, S / 6);
        for (int pass = 0; pass < 2; ++pass) {
            for (int py = 0; py < N; ++py)
                for (int px = 0; px < N; ++px) {
                    int s = 0, n = 0;
                    for (int k = -r; k <= r; ++k) { const int xx = px + k; if (xx >= 0 && xx < N) { s += sh[static_cast<size_t>(py) * N + xx]; ++n; } }
                    tmp[static_cast<size_t>(py) * N + px] = static_cast<uint8_t>(s / n);
                }
            for (int py = 0; py < N; ++py)
                for (int px = 0; px < N; ++px) {
                    int s = 0, n = 0;
                    for (int k = -r; k <= r; ++k) { const int yy = py + k; if (yy >= 0 && yy < N) { s += tmp[static_cast<size_t>(yy) * N + px]; ++n; } }
                    sh[static_cast<size_t>(py) * N + px] = static_cast<uint8_t>(s / n);
                }
        }
        for (int py = 0; py < N; ++py)
            for (int px = 0; px < N; ++px) {
                if (isB(px, py) || isR(px, py)) continue;
                const size_t p = static_cast<size_t>(py) * N + px;
                const float k = 1.0f - 0.6f * sh[p] / 255.0f;
                img[p] = pack(R_(img[p]) * k, G_(img[p]) * k, B_(img[p]) * k);
            }
    }
    {   // buildings, a lighter rim on the lit (top/left) side, a darker one opposite
        auto key = [&](int px, int py) { return isB(px, py) ? 10 + hgt[cellOf(px, py)] : 0; };
        for (int py = 0; py < N; ++py)
            for (int px = 0; px < N; ++px) {
                if (!isB(px, py)) continue;
                Rgb c = kBld[hgt[cellOf(px, py)]];
                const int k0 = key(px, py);
                const bool lit = (py > 0 && k0 > key(px, py - 1)) || (px > 0 && k0 > key(px - 1, py));
                const bool dark = (py + 1 < N && k0 > key(px, py + 1)) || (px + 1 < N && k0 > key(px + 1, py));
                if (lit) c = {c.r * 1.28f + 6, c.g * 1.28f + 6, c.b * 1.28f + 6};
                else if (dark) c = {c.r * 0.78f, c.g * 0.78f, c.b * 0.78f};
                img[static_cast<size_t>(py) * N + px] = pk(c);
            }
    }
    {   // roads, a darker kerb line, what passes over them at half strength and rimmed; decks cased
        auto isCov = [&](int px, int py) { return px >= 0 && py >= 0 && px < N && py < N && cover[cellOf(px, py)]; };
        auto isE = [&](int px, int py) { return px >= 0 && py >= 0 && px < N && py < N && elevated[cellOf(px, py)]; };
        for (int py = 0; py < N; ++py)
            for (int px = 0; px < N; ++px) {
                const size_t p = static_cast<size_t>(py) * N + px;
                if (isR(px, py)) {
                    const bool kerb = !isR(px - 1, py) || !isR(px + 1, py) || !isR(px, py - 1) || !isR(px, py + 1);
                    Rgb c = kerb ? kRoadEdge : kRoad;
                    if (isCov(px, py)) {
                        const bool rim = !isCov(px - 1, py) || !isCov(px + 1, py) || !isCov(px, py - 1) || !isCov(px, py + 1);
                        if (rim) c = {24, 28, 36};
                        else c = {c.r * 0.42f + R_(img[p]) * 0.58f, c.g * 0.42f + G_(img[p]) * 0.58f, c.b * 0.42f + B_(img[p]) * 0.58f};
                    }
                    img[p] = pk(c);
                } else if (isE(px - 1, py) || isE(px + 1, py) || isE(px, py - 1) || isE(px, py + 1)) {
                    img[p] = pack(10, 12, 16);
                }
            }
    }
    {   // railway: a dark bed, a darker edge
        auto isL = [&](int px, int py) { return px >= 0 && py >= 0 && px < N && py < N && rail[cellOf(px, py)]; };
        for (int py = 0; py < N; ++py)
            for (int px = 0; px < N; ++px) {
                if (!isL(px, py)) continue;
                const size_t p = static_cast<size_t>(py) * N + px;
                if (!isL(px - 1, py) || !isL(px + 1, py) || !isL(px, py - 1) || !isL(px, py + 1)) img[p] = pack(16, 14, 14);
                else img[p] = pack(R_(img[p]) * 0.35f + kRail.r * 0.65f, G_(img[p]) * 0.35f + kRail.g * 0.65f, B_(img[p]) * 0.35f + kRail.b * 0.65f);
            }
    }
    if (gammaFix) {
        uint8_t lut[256];
        for (int i = 0; i < 256; ++i) lut[i] = static_cast<uint8_t>(std::lround(255.0 * std::pow(i / 255.0, 1.0 / 2.2)));
        for (uint32_t& v : img)
            v = 0xFF000000u | (static_cast<uint32_t>(lut[(v >> 16) & 255]) << 16) | (static_cast<uint32_t>(lut[(v >> 8) & 255]) << 8) | lut[v & 255];
    }
}

}  // namespace citymap
}  // namespace gta2dx9
