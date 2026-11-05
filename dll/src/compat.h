// What Visual C++ has and GCC (MinGW-w64, the Linux build) does not, under one
// set of names, so the same source builds on both.
//
//   GTA2_TRY { ... } GTA2_EXCEPT { ... }
//       Structured exception handling: catches an access violation in the
//       block. __try/__except on MSVC. On GCC, which has no SEH syntax for
//       32-bit code, a vectored exception handler that resumes the thread at
//       the start of the block with the registers it had there - see
//       compat.cpp. Both forms catch the fault and run the second block; neither
//       runs destructors of objects inside the first.
//
//   ASM_NAME("_symbol")
//       After a declaration: the assembler-level name of a variable or function
//       so the file-scope assembly of a GCC-built thunk can reach it. Nothing on
//       MSVC, whose inline assembler resolves C++ names itself.
//
//   ASM_USED
//       Before a definition only the assembly uses, so GCC keeps it.
//
// The naked thunks themselves are written twice, MSVC inline assembly and GAS
// Intel syntax, side by side in each file; the instructions are the same.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#ifdef _MSC_VER

#define GTA2_TRY __try
#define GTA2_EXCEPT __except (EXCEPTION_EXECUTE_HANDLER)
#define ASM_NAME(name)
#define ASM_USED

namespace gta2dx9 {
inline void SehCompatInstall() {}
}

#else

namespace gta2dx9 {
namespace seh {

// One guarded region on the current thread's stack: the registers at the point
// GTA2_TRY was entered, taken by gta2_seh_mark below. When a fault lands inside
// the region the vectored handler puts exactly these back into the thread's
// context, with eax set to 1, and lets the thread continue - so gta2_seh_mark
// appears to return a second time, with 1, the way setjmp does. Nothing is
// jumped over from inside the handler; the dispatcher returns normally.
struct Frame {
    unsigned ebx, esi, edi, ebp, esp, eip;
    Frame* prev;
    bool fired;
};
Frame*& Top();
void Install();

struct Scope {
    Frame frame;
    bool done = false;
    Scope() {
        frame.prev = Top();
        frame.fired = false;
        Top() = &frame;
    }
    ~Scope() { Top() = frame.prev; }
    bool Once() {
        if (done) return false;
        done = true;
        return true;
    }
};

}  // namespace seh

inline void SehCompatInstall() { seh::Install(); }
}  // namespace gta2dx9

// Records the caller's registers and return address; 0 the first time, 1 when
// the handler brings the thread back here. returns_twice keeps the compiler
// from caching anything in registers across it.
extern "C" int gta2_seh_mark(::gta2dx9::seh::Frame* frame) __attribute__((returns_twice));

#define GTA2_TRY \
    for (::gta2dx9::seh::Scope _sehScope; _sehScope.Once();) \
        if (gta2_seh_mark(&_sehScope.frame) == 0)
#define GTA2_EXCEPT else
#define ASM_NAME(name) __asm__(name)
// MinGW's intrin.h declares _ReturnAddress but ships no body for it.
#ifdef _ReturnAddress
#undef _ReturnAddress
#endif
#define _ReturnAddress() __builtin_return_address(0)
// On a variable or function only the assembly reaches: keeps the optimiser from
// dropping it as unused.
#define ASM_USED __attribute__((used))

#endif
