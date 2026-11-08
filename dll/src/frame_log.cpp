// See frame_log.h. The draw-call and resource counts come from the device's own
// vtable (the C view of IDirect3DDevice9, IDirect3DTexture9), patched only when the
// log is on, so every module's draws and uploads are counted without touching them.
#define CINTERFACE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include "frame_log.h"
#include "log.h"

#include <cstdio>
#include <cstdlib>

namespace gta2dx9 {
namespace {

int g_enabled = -1;
LARGE_INTEGER g_beginScene = {};
LARGE_INTEGER g_lastEnd = {};
double g_hookMs = 0.0;
int g_hookCalls = 0;
int g_hookDepth = 0;
FILE* g_file = nullptr;
LARGE_INTEGER g_t0 = {};
double g_toMs = 0.0;

struct Counts {
    int draws, prims, upDraws, texCreated, vbCreated, ibCreated, texUnlocks, updateTexture, vbLocks;
    int notes[kFcCount];
};
Counts g_c = {};

using DrawPrimitiveFn = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, UINT);
using DrawIndexedFn = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRIMITIVETYPE, INT, UINT, UINT, UINT, UINT);
using DrawUpFn = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, const void*, UINT);
using DrawIndexedUpFn = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, UINT, UINT, const void*, D3DFORMAT,
                                         const void*, UINT);
using CreateTextureFn = HRESULT(WINAPI*)(IDirect3DDevice9*, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                         IDirect3DTexture9**, HANDLE*);
using CreateVbFn = HRESULT(WINAPI*)(IDirect3DDevice9*, UINT, DWORD, DWORD, D3DPOOL, IDirect3DVertexBuffer9**, HANDLE*);
using CreateIbFn = HRESULT(WINAPI*)(IDirect3DDevice9*, UINT, DWORD, D3DFORMAT, D3DPOOL, IDirect3DIndexBuffer9**, HANDLE*);
using UpdateTextureFn = HRESULT(WINAPI*)(IDirect3DDevice9*, IDirect3DBaseTexture9*, IDirect3DBaseTexture9*);
using UnlockRectFn = HRESULT(WINAPI*)(IDirect3DTexture9*, UINT);

DrawPrimitiveFn o_draw = nullptr;
DrawIndexedFn o_drawIndexed = nullptr;
DrawUpFn o_drawUp = nullptr;
DrawIndexedUpFn o_drawIndexedUp = nullptr;
CreateTextureFn o_createTexture = nullptr;
CreateVbFn o_createVb = nullptr;
CreateIbFn o_createIb = nullptr;
UpdateTextureFn o_updateTexture = nullptr;
UnlockRectFn o_unlockRect = nullptr;
IDirect3DDevice9Vtbl* g_hookedVtbl = nullptr;

HRESULT WINAPI H_Draw(IDirect3DDevice9* d, D3DPRIMITIVETYPE t, UINT s, UINT n) {
    ++g_c.draws; g_c.prims += static_cast<int>(n);
    return o_draw(d, t, s, n);
}
HRESULT WINAPI H_DrawIndexed(IDirect3DDevice9* d, D3DPRIMITIVETYPE t, INT b, UINT mi, UINT nv, UINT si, UINT n) {
    ++g_c.draws; g_c.prims += static_cast<int>(n);
    return o_drawIndexed(d, t, b, mi, nv, si, n);
}
HRESULT WINAPI H_DrawUp(IDirect3DDevice9* d, D3DPRIMITIVETYPE t, UINT n, const void* v, UINT st) {
    ++g_c.draws; ++g_c.upDraws; g_c.prims += static_cast<int>(n);
    return o_drawUp(d, t, n, v, st);
}
HRESULT WINAPI H_DrawIndexedUp(IDirect3DDevice9* d, D3DPRIMITIVETYPE t, UINT mi, UINT nv, UINT n, const void* i,
                               D3DFORMAT f, const void* v, UINT st) {
    ++g_c.draws; ++g_c.upDraws; g_c.prims += static_cast<int>(n);
    return o_drawIndexedUp(d, t, mi, nv, n, i, f, v, st);
}
HRESULT WINAPI H_UnlockRect(IDirect3DTexture9* t, UINT level) {
    ++g_c.texUnlocks;
    return o_unlockRect(t, level);
}
void HookTextureVtbl(IDirect3DTexture9* texture) {
    if (o_unlockRect || !texture) return;
    IDirect3DTexture9Vtbl* v = texture->lpVtbl;
    DWORD old = 0;
    if (!VirtualProtect(v, sizeof *v, PAGE_EXECUTE_READWRITE, &old)) return;
    o_unlockRect = v->UnlockRect;
    v->UnlockRect = H_UnlockRect;
    VirtualProtect(v, sizeof *v, old, &old);
}
HRESULT WINAPI H_CreateTexture(IDirect3DDevice9* d, UINT w, UINT h, UINT l, DWORD u, D3DFORMAT f, D3DPOOL p,
                               IDirect3DTexture9** out, HANDLE* s) {
    ++g_c.texCreated;
    const HRESULT hr = o_createTexture(d, w, h, l, u, f, p, out, s);
    if (SUCCEEDED(hr) && out && *out && !o_unlockRect) HookTextureVtbl(*out);
    return hr;
}
HRESULT WINAPI H_CreateVb(IDirect3DDevice9* d, UINT len, DWORD u, DWORD fvf, D3DPOOL p, IDirect3DVertexBuffer9** out,
                          HANDLE* s) {
    ++g_c.vbCreated;
    return o_createVb(d, len, u, fvf, p, out, s);
}
HRESULT WINAPI H_CreateIb(IDirect3DDevice9* d, UINT len, DWORD u, D3DFORMAT f, D3DPOOL p, IDirect3DIndexBuffer9** out,
                          HANDLE* s) {
    ++g_c.ibCreated;
    return o_createIb(d, len, u, f, p, out, s);
}
HRESULT WINAPI H_UpdateTexture(IDirect3DDevice9* d, IDirect3DBaseTexture9* a, IDirect3DBaseTexture9* b) {
    ++g_c.updateTexture;
    return o_updateTexture(d, a, b);
}

}  // namespace

int g_frameLogActive = 0;

long long FrameLogNow() {
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return t.QuadPart;
}
void FrameLogMarkBeginScene() {
    if (g_enabled == 1) QueryPerformanceCounter(&g_beginScene);
}
FrameLogHookScope::FrameLogHookScope() {
    if (!g_frameLogActive) return;
    counted = true;
    if (g_hookDepth++ == 0) t0 = FrameLogNow();
}
FrameLogHookScope::~FrameLogHookScope() {
    if (!counted) return;
    --g_hookDepth;
    if (t0) FrameLogAddHook(t0);
}
void FrameLogAddHook(long long start) {
    g_hookMs += static_cast<double>(FrameLogNow() - start) * g_toMs;
    ++g_hookCalls;
}

bool FrameLogEnabled() {
    if (g_enabled < 0) {
        char path[MAX_PATH] = {};
        g_enabled = 0;
        if (GetEnvironmentVariableA("GTA2DX9_FRAME_LOG", path, sizeof path) && path[0]) {
            g_file = fopen(path, "w");
            if (g_file) {
                setvbuf(g_file, nullptr, _IOFBF, 1 << 18);
                g_enabled = 1;
                g_frameLogActive = 1;
                LARGE_INTEGER f;
                QueryPerformanceFrequency(&f);
                g_toMs = 1000.0 / static_cast<double>(f.QuadPart);
                QueryPerformanceCounter(&g_t0);
                fprintf(g_file,
                        "frame\tt_ms\twhole\tgame\tpre\tlights\tsky\tworld\tspr_setup\tspr_loop\tspr_skid\tspr_issue\t"
                        "cars\tprops\tobjects\tpeds\teffects\tui\tlightsdraw\tpresent\twait\t"
                        "draws\tup_draws\tprims\ttex_created\tvb_created\tib_created\ttex_uploads\tupdate_tex\t"
                        "model_tex\tmodel_buffers\tnew_poses\tskin_buffers\tcar_bodies\t"
                        "model_draws\tskinned\tposing\tfills\tcar_measured\tcar_built\t"
                        "view\tdriving\tpx\tpy\tpz\tcx\tcy\tcz\tsprite_quads\tpre_load\tpre_anim\tpre_input\tpre_camera\tpre_menu\tpre_tod\tsim\tgame_draw\thooks\thook_calls\tguarded_faults\tsolver\tcam_locate\tcam_probes\n");
                Log("frame log: one line per frame to %s", path);
            } else {
                Log("frame log: could not open %s", path);
            }
        }
    }
    return g_enabled == 1;
}

void FrameLogAttachDevice(void* device) {
    if (!FrameLogEnabled() || !device) return;
    IDirect3DDevice9* d = static_cast<IDirect3DDevice9*>(device);
    IDirect3DDevice9Vtbl* v = d->lpVtbl;
    if (v == g_hookedVtbl) return;
    DWORD old = 0;
    if (!VirtualProtect(v, sizeof *v, PAGE_EXECUTE_READWRITE, &old)) {
        Log("frame log: the device's vtable could not be made writable; no draw counts");
        g_hookedVtbl = v;
        return;
    }
    // A second device (after a reset) can share the vtable already patched: keep the originals.
    if (v->DrawPrimitive != H_Draw) { o_draw = v->DrawPrimitive; v->DrawPrimitive = H_Draw; }
    if (v->DrawIndexedPrimitive != H_DrawIndexed) { o_drawIndexed = v->DrawIndexedPrimitive; v->DrawIndexedPrimitive = H_DrawIndexed; }
    if (v->DrawPrimitiveUP != H_DrawUp) { o_drawUp = v->DrawPrimitiveUP; v->DrawPrimitiveUP = H_DrawUp; }
    if (v->DrawIndexedPrimitiveUP != H_DrawIndexedUp) { o_drawIndexedUp = v->DrawIndexedPrimitiveUP; v->DrawIndexedPrimitiveUP = H_DrawIndexedUp; }
    if (v->CreateTexture != H_CreateTexture) { o_createTexture = v->CreateTexture; v->CreateTexture = H_CreateTexture; }
    if (v->CreateVertexBuffer != H_CreateVb) { o_createVb = v->CreateVertexBuffer; v->CreateVertexBuffer = H_CreateVb; }
    if (v->CreateIndexBuffer != H_CreateIb) { o_createIb = v->CreateIndexBuffer; v->CreateIndexBuffer = H_CreateIb; }
    if (v->UpdateTexture != H_UpdateTexture) { o_updateTexture = v->UpdateTexture; v->UpdateTexture = H_UpdateTexture; }
    VirtualProtect(v, sizeof *v, old, &old);
    g_hookedVtbl = v;
    Log("frame log: counting draws and resource creations on device %p", device);
}

void FrameLogNote(FrameCounter counter, int n) {
    if (g_enabled != 1 || counter < 0 || counter >= kFcCount) return;
    g_c.notes[counter] += n;
}

void FrameLogEndFrame(uint32_t frame, const FrameLogRecord& r) {
    if (g_enabled != 1 || !g_file) return;
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    const double t = static_cast<double>(now.QuadPart - g_t0.QuadPart) * g_toMs;
    // The game's simulation (previous frame's end to gbh_BeginScene) and its draw stream
    // (gbh_BeginScene to RenderFrame), when gbh_BeginScene came in between.
    double sim = 0.0, gameDraw = 0.0;
    if (g_lastEnd.QuadPart && g_beginScene.QuadPart > g_lastEnd.QuadPart && r.entryQpc > g_beginScene.QuadPart) {
        sim = static_cast<double>(g_beginScene.QuadPart - g_lastEnd.QuadPart) * g_toMs;
        gameDraw = static_cast<double>(r.entryQpc - g_beginScene.QuadPart) * g_toMs;
    }
    fprintf(g_file,
            "%u\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t"
            "%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%.2f\t%.2f\t%d\t%d\t%d\t%d\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%d\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%d\t%d\t%.2f\t%.2f\t%.2f\n",
            frame, t, r.whole, r.game, r.pre, r.lights, r.sky, r.world, r.sprites[0], r.sprites[1], r.sprites[2],
            r.sprites[3], r.sprites[4], r.sprites[5], r.sprites[6], r.sprites[7], r.sprites[8], r.ui, r.lightsDraw,
            r.present, r.wait, g_c.draws, g_c.upDraws, g_c.prims, g_c.texCreated, g_c.vbCreated, g_c.ibCreated,
            g_c.texUnlocks, g_c.updateTexture, g_c.notes[kFcModelTexture], g_c.notes[kFcModelBuffers],
            g_c.notes[kFcNewPose], g_c.notes[kFcSkinBuffer], g_c.notes[kFcCarBody], r.modelDraws, r.skinned, r.posing,
            r.fills, r.carMeasured, r.carBuilt, r.view, r.driving, r.px, r.py, r.pz, r.cx, r.cy, r.cz, r.spriteQuads, r.preParts[0], r.preParts[1], r.preParts[2], r.preParts[3],
            r.preParts[4], r.preParts[5], sim, gameDraw, g_hookMs, g_hookCalls, g_c.notes[kFcGuardedFault], r.solver, r.camLocate, r.camProbes);
    if ((frame % 120) == 0) fflush(g_file);
    g_c = Counts{};
    g_hookMs = 0.0;
    g_hookCalls = 0;
    QueryPerformanceCounter(&g_lastEnd);
}

}  // namespace gta2dx9
