#include "thread_watch.h"
#include "compat.h"
#include "crash_safe.h"
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
// FIX-HANG-1: the innermost guarded region of a thread lives in a TlsAlloc slot, not a thread_local. GCC's emulated
// thread_local takes a lock and mallocs on a thread's first access, and this handler runs for every exception of
// every thread (a C++ throw, OutputDebugString, SetThreadName, a heap fault): inside a heap routine that is a
// deadlock waiting for a bad day. TlsGetValue neither allocates nor locks; a thread that never set the slot reads null.
volatile LONG g_tlsSlot = -1;   // TLS_OUT_OF_INDEXES is -1 as a DWORD
bool g_installed = false;

DWORD TlsSlot() {
    LONG s = g_tlsSlot;
    if (s == -1) {
        const DWORD fresh = TlsAlloc();
        if (fresh == TLS_OUT_OF_INDEXES) return TLS_OUT_OF_INDEXES;
        s = InterlockedCompareExchange(&g_tlsSlot, static_cast<LONG>(fresh), -1);
        if (s != -1) TlsFree(fresh);   // another thread won
        else s = static_cast<LONG>(fresh);
    }
    return static_cast<DWORD>(s);
}

// Runs before any frame-based handler. If the faulting thread is inside a
// guarded region, the thread's context is set back to what gta2_seh_mark saw,
// with eax 1, and execution continues there: the mark returns a second time
// and the GTA2_EXCEPT block runs. A fault inside a region that has already
// fired falls through to whatever would have caught it without us, as it
// would on MSVC.
// For a fault nobody guards against: where it was, once (crash_safe.cpp: no allocation, no lock).
HMODULE g_self = nullptr;

LONG CALLBACK Handler(EXCEPTION_POINTERS* info) {
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    // The heap manager's DbgPrint ("HEAP[gta2.exe]: Heap block at ... modified at ...") arrives as one of these.
    if (code == 0x40010006 || code == 0x4001000A) {
        gta2dx9::crash::NoteDebugString(info);
        return EXCEPTION_CONTINUE_SEARCH;
    }
    const DWORD slot = g_tlsSlot == -1 ? TLS_OUT_OF_INDEXES : static_cast<DWORD>(g_tlsSlot);
    const DWORD lastError = GetLastError();   // TlsGetValue clears it; a handler must leave it as it was
    Frame* frame = slot == TLS_OUT_OF_INDEXES ? nullptr : static_cast<Frame*>(TlsGetValue(slot));
    SetLastError(lastError);
    if (!frame || frame->fired) {
        if (code == EXCEPTION_ACCESS_VIOLATION || code == EXCEPTION_ILLEGAL_INSTRUCTION) gta2dx9::crash::LogUnguardedFault(info);
        return EXCEPTION_CONTINUE_SEARCH;
    }
    if (code != EXCEPTION_ACCESS_VIOLATION && code != EXCEPTION_IN_PAGE_ERROR &&
        code != EXCEPTION_DATATYPE_MISALIGNMENT && code != EXCEPTION_ILLEGAL_INSTRUCTION &&
        code != EXCEPTION_PRIV_INSTRUCTION && code != EXCEPTION_INT_DIVIDE_BY_ZERO) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    frame->fired = true;
    gta2dx9::FrameLogNote(gta2dx9::kFcGuardedFault);
    // FIX-DEADLOCK-1: kept for the stall dump (a fault inside a lock's holder leaves the lock held).
    gta2dx9::NoteGuardedFault(code, reinterpret_cast<uintptr_t>(info->ExceptionRecord->ExceptionAddress),
                              info->ExceptionRecord->NumberParameters > 1 ? info->ExceptionRecord->ExceptionInformation[1] : 0);
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

Frame* Top() {
    const DWORD slot = g_tlsSlot == -1 ? TLS_OUT_OF_INDEXES : static_cast<DWORD>(g_tlsSlot);
    return slot == TLS_OUT_OF_INDEXES ? nullptr : static_cast<Frame*>(TlsGetValue(slot));
}

void SetTop(Frame* frame) {
    const DWORD slot = TlsSlot();
    if (slot != TLS_OUT_OF_INDEXES) TlsSetValue(slot, frame);
}

void Install() {
    if (g_installed) return;
    g_installed = true;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCSTR>(&Install), &g_self);
    TlsSlot();   // allocate the slot now, on a thread that may allocate
    AddVectoredExceptionHandler(1, Handler);
}

}  // namespace seh
}  // namespace gta2dx9

#endif
