#include "compat.h"
#include "frame_log.h"
#include "log.h"
#include <cstdio>

#ifndef _MSC_VER

// Saves the caller's callee-saved registers, its stack pointer as it will be
// once this returns, and the return address, then returns 0. cdecl: the one
// argument is the caller's to pop, so the saved esp is the one after `ret`.
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    ".globl _gta2_seh_mark\n"
    "_gta2_seh_mark:\n"
    "    mov eax, dword ptr [esp + 4]\n"
    "    mov dword ptr [eax + 0], ebx\n"
    "    mov dword ptr [eax + 4], esi\n"
    "    mov dword ptr [eax + 8], edi\n"
    "    mov dword ptr [eax + 12], ebp\n"
    "    lea ecx, [esp + 4]\n"
    "    mov dword ptr [eax + 16], ecx\n"
    "    mov ecx, dword ptr [esp]\n"
    "    mov dword ptr [eax + 20], ecx\n"
    "    xor eax, eax\n"
    "    ret\n"
    ".att_syntax prefix\n");

namespace gta2dx9 {
namespace seh {

namespace {
thread_local Frame* t_top = nullptr;
bool g_installed = false;

// Runs before any frame-based handler. If the faulting thread is inside a
// guarded region, the thread's context is set back to what gta2_seh_mark saw,
// with eax 1, and execution continues there: the mark returns a second time
// and the GTA2_EXCEPT block runs. A fault inside a region that has already
// fired falls through to whatever would have caught it without us, as it
// would on MSVC.
// For a fault nobody guards against: where it was, relative to this DLL, once.
HMODULE g_self = nullptr;
LONG g_faultsLogged = 0;

LONG CALLBACK Handler(EXCEPTION_POINTERS* info) {
    Frame* frame = t_top;
    if (!frame || frame->fired) {
        const DWORD code = info->ExceptionRecord->ExceptionCode;
        if ((code == EXCEPTION_ACCESS_VIOLATION || code == EXCEPTION_ILLEGAL_INSTRUCTION) &&
            InterlockedIncrement(&g_faultsLogged) <= 3) {
            const uintptr_t at = reinterpret_cast<uintptr_t>(info->ExceptionRecord->ExceptionAddress);
            const uintptr_t base = reinterpret_cast<uintptr_t>(g_self);
            HMODULE module = nullptr;
            GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               reinterpret_cast<LPCSTR>(at), &module);
            char name[MAX_PATH] = "?";
            if (module) GetModuleFileNameA(module, name, MAX_PATH);
            Log("FAULT: code %08lX at %08X (%s+0x%X; gta2dx9.dll is at %08X), reading %08X", code,
                static_cast<unsigned>(at), name,
                static_cast<unsigned>(at - reinterpret_cast<uintptr_t>(module)), static_cast<unsigned>(base),
                static_cast<unsigned>(info->ExceptionRecord->NumberParameters > 1
                                          ? info->ExceptionRecord->ExceptionInformation[1] : 0));
            // Where it came from: the registers, and every word on the stack
            // that points into this DLL (offsets for nm --numeric-sort).
            const CONTEXT* c = info->ContextRecord;
            Log("FAULT: eax %08X ebx %08X ecx %08X edx %08X esi %08X edi %08X ebp %08X esp %08X", c->Eax, c->Ebx,
                c->Ecx, c->Edx, c->Esi, c->Edi, c->Ebp, c->Esp);
            if (base) {
                const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
                const IMAGE_NT_HEADERS* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
                const uintptr_t end = base + nt->OptionalHeader.SizeOfImage;
                MEMORY_BASIC_INFORMATION mbi;
                uintptr_t top = c->Esp + 0x10000;
                if (VirtualQuery(reinterpret_cast<void*>(c->Esp), &mbi, sizeof(mbi)))
                    top = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
                char line[640];
                int n = snprintf(line, sizeof(line), "FAULT: stack words inside gta2dx9.dll:");
                int count = 0;
                for (uintptr_t p = c->Esp & ~static_cast<uintptr_t>(3); p + 4 <= top && count < 40; p += 4) {
                    const uintptr_t v = *reinterpret_cast<const uintptr_t*>(p);
                    if (v < base || v >= end) continue;
                    n += snprintf(line + n, sizeof(line) - n, " +0x%X", static_cast<unsigned>(v - base));
                    ++count;
                    if (n > 580) break;
                }
                Log("%s", line);
            }
        }
        return EXCEPTION_CONTINUE_SEARCH;
    }
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if (code != EXCEPTION_ACCESS_VIOLATION && code != EXCEPTION_IN_PAGE_ERROR &&
        code != EXCEPTION_DATATYPE_MISALIGNMENT && code != EXCEPTION_ILLEGAL_INSTRUCTION &&
        code != EXCEPTION_PRIV_INSTRUCTION && code != EXCEPTION_INT_DIVIDE_BY_ZERO) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    frame->fired = true;
    gta2dx9::FrameLogNote(gta2dx9::kFcGuardedFault);
    CONTEXT* c = info->ContextRecord;
    c->Ebx = frame->ebx;
    c->Esi = frame->esi;
    c->Edi = frame->edi;
    c->Ebp = frame->ebp;
    c->Esp = frame->esp;
    c->Eip = frame->eip;
    c->Eax = 1;
    return EXCEPTION_CONTINUE_EXECUTION;
}
}  // namespace

Frame*& Top() { return t_top; }

void Install() {
    if (g_installed) return;
    g_installed = true;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCSTR>(&Install), &g_self);
    AddVectoredExceptionHandler(1, Handler);
}

}  // namespace seh
}  // namespace gta2dx9

#endif
