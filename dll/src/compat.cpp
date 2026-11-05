#include "compat.h"

#ifndef _MSC_VER

namespace gta2dx9 {
namespace seh {

namespace {
thread_local Frame* t_top = nullptr;
bool g_installed = false;

// Runs before any frame-based handler. If the faulting thread is inside a
// guarded region, control goes back to the region's setjmp with a non-zero
// result; the dispatcher's own frames below it are simply abandoned, which is
// what longjmp out of a handler has always meant on Windows. A fault inside the
// handler block of a region that has already fired falls through to whatever
// would have caught it without us, as it would on MSVC.
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
    __builtin_longjmp(frame->jump, 1);
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
