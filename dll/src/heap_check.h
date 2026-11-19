// FIX-HANG-1 diagnostics: [devtools] heap_check_ms=N validates every heap of the process every N ms from its own thread
// (HeapValidate), names the first one that fails and when, and with heap_check_abort=1 ends the process there with the
// fatal report and a minidump. Off by default. With the heap flags tail/free check on (GlobalFlag 0x70 in Image File
// Execution Options for gta2.exe) the heap manager also finds a block written past its end or after its free, and says
// which block (its DbgPrint text is caught by the vectored handler, crash_safe.h NoteDebugString).
#pragma once

namespace gta2dx9 {
void StartHeapCheck();
}
