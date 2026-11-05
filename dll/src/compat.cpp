#include "compat.h"

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
LONG CALLBACK Handler(EXCEPTION_POINTERS* info) {
    Frame* frame = t_top;
    if (!frame || frame->fired) return EXCEPTION_CONTINUE_SEARCH;
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if (code != EXCEPTION_ACCESS_VIOLATION && code != EXCEPTION_IN_PAGE_ERROR &&
        code != EXCEPTION_DATATYPE_MISALIGNMENT && code != EXCEPTION_ILLEGAL_INSTRUCTION &&
        code != EXCEPTION_PRIV_INSTRUCTION && code != EXCEPTION_INT_DIVIDE_BY_ZERO) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    frame->fired = true;
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
    AddVectoredExceptionHandler(1, Handler);
}

}  // namespace seh
}  // namespace gta2dx9

#endif
