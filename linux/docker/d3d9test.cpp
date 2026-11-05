// Minimal Direct3D 9 fixed-function scene: a lit, textured, spinning cube over
// a floor, perspective projection, untransformed vertices - exactly the kind
// of draw RTX Remix path traces. Prints the adapter it got and runs N frames.
//   d3d9test.exe [frames=300] [width=640] [height=480] [ms per frame=33]
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>

struct Vtx { float x, y, z, nx, ny, nz; DWORD color; float u, v; };
#define FVF (D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_DIFFUSE | D3DFVF_TEX1)

static void Persp(D3DMATRIX* m, float fov, float aspect, float zn, float zf) {
    float h = 1.0f / tanf(fov * 0.5f), w = h / aspect, q = zf / (zf - zn);
    ZeroMemory(m, sizeof(*m));
    m->_11 = w; m->_22 = h; m->_33 = q; m->_34 = 1.0f; m->_43 = -q * zn;
}
static void LookAt(D3DMATRIX* m, float ex, float ey, float ez, float tx, float ty, float tz) {
    float zx = tx - ex, zy = ty - ey, zz = tz - ez; float l = sqrtf(zx*zx+zy*zy+zz*zz); zx/=l; zy/=l; zz/=l;
    float ux = 0, uy = 1, uz = 0;
    float xx = uy*zz - uz*zy, xy = uz*zx - ux*zz, xz = ux*zy - uy*zx; l = sqrtf(xx*xx+xy*xy+xz*xz); xx/=l; xy/=l; xz/=l;
    float yx = zy*xz - zz*xy, yy = zz*xx - zx*xz, yz = zx*xy - zy*xx;
    m->_11 = xx; m->_12 = yx; m->_13 = zx; m->_14 = 0;
    m->_21 = xy; m->_22 = yy; m->_23 = zy; m->_24 = 0;
    m->_31 = xz; m->_32 = yz; m->_33 = zz; m->_34 = 0;
    m->_41 = -(xx*ex + xy*ey + xz*ez); m->_42 = -(yx*ex + yy*ey + yz*ez); m->_43 = -(zx*ex + zy*ey + zz*ez); m->_44 = 1;
}
static void RotY(D3DMATRIX* m, float a, float tx, float ty, float tz) {
    ZeroMemory(m, sizeof(*m));
    m->_11 = cosf(a); m->_13 = sinf(a); m->_22 = 1; m->_31 = -sinf(a); m->_33 = cosf(a); m->_44 = 1;
    m->_41 = tx; m->_42 = ty; m->_43 = tz;
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcA(h, m, w, l);
}

int main(int argc, char** argv) {
    const int frames = argc > 1 ? atoi(argv[1]) : 300;
    const int W = argc > 2 ? atoi(argv[2]) : 640, H = argc > 3 ? atoi(argv[3]) : 480;
    const int pace = argc > 4 ? atoi(argv[4]) : 33;
    WNDCLASSA wc = {}; wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandleA(nullptr); wc.lpszClassName = "d3d9test";
    RegisterClassA(&wc);
    HWND hwnd = CreateWindowA("d3d9test", "d3d9test", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, W, H, nullptr, nullptr, wc.hInstance, nullptr);

    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) { printf("Direct3DCreate9 failed\n"); return 2; }
    D3DADAPTER_IDENTIFIER9 id = {};
    d3d->GetAdapterIdentifier(0, 0, &id);
    printf("adapter: %s (driver %s)\n", id.Description, id.Driver); fflush(stdout);

    D3DPRESENT_PARAMETERS pp = {};
    pp.Windowed = TRUE; pp.SwapEffect = D3DSWAPEFFECT_DISCARD; pp.BackBufferWidth = W; pp.BackBufferHeight = H;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8; pp.EnableAutoDepthStencil = TRUE; pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.hDeviceWindow = hwnd; pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* dev = nullptr;
    HRESULT hr = d3d->CreateDevice(0, D3DDEVTYPE_HAL, hwnd, D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &dev);
    for (int tries = 0; FAILED(hr) && tries < 200; ++tries) {   // Remix's bridge hands back INVALIDCALL until its server is up
        MSG msg; while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageA(&msg); }
        Sleep(100);
        hr = d3d->CreateDevice(0, D3DDEVTYPE_HAL, hwnd, D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &dev);
    }
    if (FAILED(hr)) { printf("CreateDevice failed: 0x%08lX\n", hr); return 3; }
    printf("device created\n"); fflush(stdout);

    // A checkerboard texture.
    IDirect3DTexture9* tex = nullptr;
    dev->CreateTexture(64, 64, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr);
    D3DLOCKED_RECT lr; tex->LockRect(0, &lr, nullptr, 0);
    for (int y = 0; y < 64; ++y) for (int x = 0; x < 64; ++x)
        ((DWORD*)((char*)lr.pBits + y * lr.Pitch))[x] = (((x / 8) + (y / 8)) & 1) ? 0xFFE0E0E0 : 0xFF2040C0;
    tex->UnlockRect(0);

    // Cube (6 faces, 2 triangles each) and a floor quad.
    Vtx cube[36]; int n = 0;
    auto face = [&](float nx, float ny, float nz, float ax, float ay, float az, float bx, float by, float bz, DWORD c) {
        float cx = nx, cy = ny, cz = nz;   // face centre at the normal
        Vtx v[4];
        float ox[4] = {-1, 1, 1, -1}, oy[4] = {-1, -1, 1, 1};
        for (int i = 0; i < 4; ++i) {
            v[i] = {cx + ax * ox[i] + bx * oy[i], cy + ay * ox[i] + by * oy[i], cz + az * ox[i] + bz * oy[i], nx, ny, nz, c, (ox[i] + 1) * 0.5f, (oy[i] + 1) * 0.5f};
        }
        const int idx[6] = {0, 1, 2, 0, 2, 3};
        for (int i : idx) cube[n++] = v[i];
    };
    face(0, 0, -1, 1, 0, 0, 0, 1, 0, 0xFFFFFFFF); face(0, 0, 1, -1, 0, 0, 0, 1, 0, 0xFFFFFFFF);
    face(-1, 0, 0, 0, 0, -1, 0, 1, 0, 0xFFFFFFFF); face(1, 0, 0, 0, 0, 1, 0, 1, 0, 0xFFFFFFFF);
    face(0, 1, 0, 1, 0, 0, 0, 0, 1, 0xFFFFFFFF); face(0, -1, 0, 1, 0, 0, 0, 0, -1, 0xFFFFFFFF);
    Vtx floor_[6] = {
        {-8, -1, -8, 0, 1, 0, 0xFF808080, 0, 0}, {8, -1, -8, 0, 1, 0, 0xFF808080, 8, 0}, {8, -1, 8, 0, 1, 0, 0xFF808080, 8, 8},
        {-8, -1, -8, 0, 1, 0, 0xFF808080, 0, 0}, {8, -1, 8, 0, 1, 0, 0xFF808080, 8, 8}, {-8, -1, 8, 0, 1, 0, 0xFF808080, 0, 8},
    };

    D3DMATRIX proj, view, world;
    Persp(&proj, 1.0f, (float)W / H, 0.1f, 100.0f);
    LookAt(&view, 0, 2.5f, -6, 0, 0, 0);
    dev->SetTransform(D3DTS_PROJECTION, &proj);
    dev->SetTransform(D3DTS_VIEW, &view);
    dev->SetRenderState(D3DRS_LIGHTING, TRUE);
    dev->SetRenderState(D3DRS_ZENABLE, TRUE);
    dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    D3DLIGHT9 light = {}; light.Type = D3DLIGHT_POINT; light.Diffuse = {1, 0.9f, 0.7f, 1}; light.Position = {2, 4, -2};
    light.Range = 30; light.Attenuation0 = 0.2f; light.Attenuation1 = 0.1f;
    dev->SetLight(0, &light); dev->LightEnable(0, TRUE);
    dev->SetRenderState(D3DRS_AMBIENT, 0x00202020);
    D3DMATERIAL9 mat = {}; mat.Diffuse = {1, 1, 1, 1}; mat.Ambient = {1, 1, 1, 1}; dev->SetMaterial(&mat);
    dev->SetFVF(FVF);
    dev->SetTexture(0, tex);

    DWORD t0 = GetTickCount();
    for (int f = 0; f < frames; ++f) {
        MSG msg; while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageA(&msg); if (msg.message == WM_QUIT) f = frames; }
        dev->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xFF203040, 1.0f, 0);
        dev->BeginScene();
        RotY(&world, 0, 0, 0, 0); dev->SetTransform(D3DTS_WORLD, &world);
        dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 2, floor_, sizeof(Vtx));
        RotY(&world, f * 0.03f, 0, 0, 0); dev->SetTransform(D3DTS_WORLD, &world);
        dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 12, cube, sizeof(Vtx));
        RotY(&world, -f * 0.05f, 3.5f, 0, 2); dev->SetTransform(D3DTS_WORLD, &world);
        dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 12, cube, sizeof(Vtx));
        dev->EndScene();
        hr = dev->Present(nullptr, nullptr, nullptr, nullptr);
        if (pace > 0) Sleep(pace);
        if ((f % 30) == 0) { printf("frame %d (present 0x%08lX) %.1f ms/frame\n", f, hr, f ? (GetTickCount() - t0) / (float)f : 0.0f); fflush(stdout); }
    }
    printf("done: %d frames in %lu ms\n", frames, GetTickCount() - t0);
    tex->Release(); dev->Release(); d3d->Release();
    return 0;
}
