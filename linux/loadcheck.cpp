// Loads gta2dx9.dll and gta2dx9_vid.dll the way gta2.exe does - LoadLibrary,
// then GetProcAddress for every name the game resolves - and reports what is
// missing. Run from the folder the DLLs are in, under Wine or Windows:
//
//     wine loadcheck.exe
//
// Exit code 0 when every export resolves and DllMain ran; a failure prints
// which name was not found. The renderer's own log, gta2dx9.log, is written
// beside the DLL as it would be beside the game.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdio>

#include "gbh_exports.h"

int main() {
    int missing = 0;

    HMODULE renderer = LoadLibraryA("gta2dx9.dll");
    if (!renderer) {
        printf("gta2dx9.dll: LoadLibrary failed, error %lu\n", GetLastError());
        return 2;
    }
    const char* names[] = {
        "gbh_InitDLL",
#define X(name) #name,
        GBH_EXPORT_LIST(X)
#undef X
        "gta2dx9_NoteScreenClear",
    };
    for (const char* name : names) {
        if (!GetProcAddress(renderer, name)) {
            printf("gta2dx9.dll: missing export %s\n", name);
            ++missing;
        }
    }
    printf("gta2dx9.dll: loaded at %p, %d of %d exports missing\n", static_cast<void*>(renderer),
           missing, static_cast<int>(sizeof(names) / sizeof(names[0])));

    // The reserved block for plugins has to cover base + 0x485E0 - see
    // dll/src/plugin_slot.S - and the block is zeros, so a code byte there is
    // the block having landed somewhere else.
    const unsigned char* base = reinterpret_cast<const unsigned char*>(renderer);
    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(base + 0x485E0, &mbi, sizeof(mbi)) && mbi.State == MEM_COMMIT) {
        printf("gta2dx9.dll: +0x485E0 is mapped (%s)\n",
               (mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE)) ? "code" : "data");
    } else {
        printf("gta2dx9.dll: +0x485E0 is NOT mapped\n");
        ++missing;
    }

    HMODULE vid = LoadLibraryA("gta2dx9_vid.dll");
    if (!vid) {
        printf("gta2dx9_vid.dll: LoadLibrary failed, error %lu\n", GetLastError());
        return 2;
    }
    const char* vidNames[] = {
        "Vid_GetVersion", "Vid_InitDLL", "Vid_Init_SYS", "Vid_ShutDown_SYS", "Vid_FindDevice",
        "Vid_SetDevice", "Vid_FindFirstMode", "Vid_FindNextMode", "Vid_CheckMode", "Vid_SetMode",
        "Vid_CloseScreen", "Vid_ClearScreen", "Vid_FlipBuffers", "Vid_GetSurface", "Vid_GrabSurface",
        "Vid_FreeSurface", "Vid_ReleaseSurface", "Vid_EnableWrites", "Vid_DisableWrites", "Vid_SetGamma",
        "Vid_WindowProc", "Vid_FindMode",
    };
    int vidMissing = 0;
    for (const char* name : vidNames) {
        if (!GetProcAddress(vid, name)) {
            printf("gta2dx9_vid.dll: missing export %s\n", name);
            ++vidMissing;
        }
    }
    printf("gta2dx9_vid.dll: loaded, %d of %d exports missing\n", vidMissing,
           static_cast<int>(sizeof(vidNames) / sizeof(vidNames[0])));
    using VersionFn = unsigned(__stdcall*)();
    if (auto version = reinterpret_cast<VersionFn>(GetProcAddress(vid, "Vid_GetVersion"))) {
        // A pointer to the version block in the original and the stand-in alike.
        printf("gta2dx9_vid.dll: Vid_GetVersion -> %p\n", reinterpret_cast<void*>(version()));
    }

    FreeLibrary(vid);
    FreeLibrary(renderer);
    return (missing || vidMissing) ? 1 : 0;
}
