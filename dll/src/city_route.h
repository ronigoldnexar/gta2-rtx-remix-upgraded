// CITYMAP-1: the level's surfaces, the drivable and walkable graphs, the route search and the map
// picture. The C++ port of tools/citymap/roadgraph.py and mapart.py (the offline reference and its
// route test); see docs/citymap.md.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace gta2 { class Map; }

namespace gta2dx9 {
namespace citymap {

constexpr int kW = 256, kH = 256, kLevels = 8;

enum Mode { kCar = 0, kWalk = 1 };

// One surface a car or a pedestrian can stand on: the lid of block (x, y, z), whose top is at
// height z + 1 when flat (block z spans z..z+1; the game's z of a man on it).
struct Node {
    uint8_t x = 0, y = 0, z = 0, ground = 0, slope = 0, arrows = 0;
    uint8_t sideMask = 0;      // edges (W, E, N, S bits) that run along a ramp, not across it
    float eh[4] = {};          // the surface's height at its W, E, N, S edges
};

struct Csr {
    std::vector<int> off, to;
    std::vector<float> cost;
    void Build(int n, std::vector<std::pair<int, std::pair<int, float>>>& edges);
};

// The per-cell, per-level facts of the map the graph and the picture are made from.
struct Cells {
    std::vector<uint8_t> valid, ground, slope, arrows, wallMask, sideMask;   // [z][y][x]
    std::vector<uint16_t> lid;
    size_t At(int z, int y, int x) const { return (static_cast<size_t>(z) * kH + y) * kW + x; }
    void Load(const gta2::Map& map);
    void Clear();
};

struct Zone { int type, x, y, w, h; std::string key; };

class Level {
public:
    bool Build(const gta2::Map& map, const std::vector<uint8_t>& zoneChunk);
    bool Ready() const { return ready_; }

    const std::vector<Node>& Nodes() const { return nodes_; }
    const std::vector<Zone>& Zones() const { return zones_; }
    bool InMain(Mode m, int node) const { return main_[m][node] != 0; }
    int RoadNodes() const { return roads_; }
    int Edges(Mode m) const { return static_cast<int>(adj_[m].to.size()); }
    int MainCount(Mode m) const;

    // The node of the wanted kind nearest the point (cells), within `radius`; `mainOnly` keeps it
    // to the main strongly connected network. zHint < 0: the topmost surface of each cell.
    int Snap(float fx, float fy, float zHint, Mode m, int radius, bool mainOnly) const;
    // The cost of every node to the goal and its next hop (the backward search).
    void CostTo(int goal, Mode m, std::vector<float>* dist, std::vector<int>* next) const;
    // The node to start from near the player: reaching the goal, lined up with his heading (radians,
    // 0 north; NaN unknown). -1 when nothing within 24 cells reaches it.
    int StartNode(float px, float py, float pz, float heading, Mode m, const std::vector<float>& dist) const;
    // ... and with nothing near reaching it (a closed yard, an island): the nearest node that does.
    int NearestReaching(float px, float py, float pz, const std::vector<float>& dist, float* hop) const;
    // The node list from `start` down the next hops.
    std::vector<int> Path(int start, const std::vector<int>& next) const;
    // The path as a line: centre=true the road's middle (runs of one direction moved onto the middle
    // of their cross-section, lane changes folded away), false the lane's own cells. z per point.
    void Polyline(const std::vector<int>& path, bool centre, Mode m, std::vector<float>* xs, std::vector<float>* ys,
                  std::vector<float>* zs) const;

    // The picture (ARGB, ppc pixels a cell, kW*ppc square), baked once a level off the render thread.
    void Bake(int ppc, bool gammaFix, std::vector<uint32_t>* out) const;

    // The district a cell is in (the smallest navigation zone holding it); "" none.
    std::string DistrictKeyAt(int x, int y) const;

    Cells cells;   // kept for the bake; cleared after it

private:
    int MatchAcross(int a, int dx, int dy) const;
    bool Walled(int a, int dx, int dy) const;
    void Scc(Mode m);
    float CrossOffset(int x, int y, int z, int dx, int dy, Mode m) const;
    bool WantGround(Mode m, int g) const { return m == kCar ? g == 1 : (g >= 1 && g <= 3); }

    bool ready_ = false;
    std::vector<Node> nodes_;
    std::vector<int> cellFirst_;   // kW*kH+1: the nodes of cell (x, y) are cellFirst_[c] .. cellFirst_[c+1]
    Csr adj_[2], rev_[2];
    std::vector<uint8_t> main_[2];
    std::vector<Zone> zones_;
    int roads_ = 0;
};

// Line helpers (cells).
void Fillet(const std::vector<float>& xs, const std::vector<float>& ys, float r, int seg, std::vector<float>* ox, std::vector<float>* oy);
float Length(const std::vector<float>& xs, const std::vector<float>& ys);
// The first corner of more than 35 degrees past 1 cell along the line: its distance and -1 left / 1 right.
bool NextTurn(const std::vector<float>& xs, const std::vector<float>& ys, float* dist, int* dir);
// The line from the point nearest (px, py) on its first `window` segments: the rest of it.
void CutAt(const std::vector<float>& xs, const std::vector<float>& ys, const std::vector<float>* zs, float px, float py, int window,
           std::vector<float>* ox, std::vector<float>* oy, std::vector<float>* oz, float* offLine);

}  // namespace citymap
}  // namespace gta2dx9
