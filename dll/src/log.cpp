#include "log.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <atomic>
#include <string>

namespace gta2dx9 {
namespace {
FILE* g_log = nullptr;

// FIX-PERF-2 (owner blocker "gameplay is jerky"): Log() used to fflush every line
// on the calling thread, which is the render thread for nearly every line. The
// scripted runners log the player's state and the peds/cars around him every 3
// frames, so the render thread made a write() system call (through wine's
// NtWriteFile) several times a frame, and a write that met the host's dirty-page
// throttling (eight games, recorders and builds writing to the same disk) stalled
// the frame with it. Now a line is formatted into memory under a short lock and a
// writer thread puts it on disk every kFlushMs; a FAULT line, a call stack and
// LogFlush() write at once on the caller's thread, so a crash still leaves its
// last words in the file. The runners read the file within kFlushMs of the line.
constexpr DWORD kFlushMs = 15;
CRITICAL_SECTION g_pendingLock;   // guards g_pending
CRITICAL_SECTION g_fileLock;      // guards g_log and the order of writes
std::string g_pending;
HANDLE g_wake = nullptr;
HANDLE g_writer = nullptr;        // kept open: CloseLog waits on it
volatile LONG g_writerRunning = 0;
volatile LONG g_stop = 0;
bool g_locksMade = false;

// The cost on the threads that log (log.h LogCostTake).
std::atomic<long> g_calls{0};
std::atomic<long> g_bytes{0};
std::atomic<long long> g_ticks{0};   // QPC ticks spent inside Log(), summed

void WritePending() {
    std::string out;
    EnterCriticalSection(&g_pendingLock);
    out.swap(g_pending);
    LeaveCriticalSection(&g_pendingLock);
    if (out.empty()) return;
    EnterCriticalSection(&g_fileLock);
    if (g_log) {
        fwrite(out.data(), 1, out.size(), g_log);
        fflush(g_log);
    }
    LeaveCriticalSection(&g_fileLock);
}

DWORD WINAPI Writer(LPVOID) {
    while (!g_stop) {
        WaitForSingleObject(g_wake, kFlushMs);
        WritePending();
    }
    InterlockedExchange(&g_writerRunning, 0);
    return 0;
}
}  // namespace

void OpenLog() {
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (slash) strcpy(slash + 1, "gta2dx9.log");
    else strcpy(path, "gta2dx9.log");

    // The game is free to load and unload the renderer more than once in a run,
    // and every load lands here. Truncating each time would throw away the
    // earlier pass, which is the interesting one, so only the first open in a
    // process starts a fresh file. The marker lives in the environment because
    // it has to outlive our own globals across an unload.
    static const char kOpened[] = "GTA2DX9_LOG_OPENED";
    const bool first = GetEnvironmentVariableA(kOpened, nullptr, 0) == 0;
    if (!g_locksMade) {
        InitializeCriticalSection(&g_pendingLock);
        InitializeCriticalSection(&g_fileLock);
        g_locksMade = true;
    }
    EnterCriticalSection(&g_fileLock);
    g_log = fopen(path, first ? "w" : "a");
    LeaveCriticalSection(&g_fileLock);
    SetEnvironmentVariableA(kOpened, "1");
    g_pending.reserve(1 << 16);
    // GTA2DX9_LOG_SYNC=1: the old behaviour, every line written and flushed by the
    // thread that logs it (for an A/B of the cost, or a debugger session).
    char buf[8] = {};
    const bool sync = GetEnvironmentVariableA("GTA2DX9_LOG_SYNC", buf, sizeof buf) && buf[0] == '1';
    if (!sync && g_log) {
        if (!g_wake) g_wake = CreateEventA(nullptr, FALSE, FALSE, nullptr);
        g_stop = 0;
        InterlockedExchange(&g_writerRunning, 1);
        g_writer = CreateThread(nullptr, 64 * 1024, Writer, nullptr, 0, nullptr);
        if (!g_writer) InterlockedExchange(&g_writerRunning, 0);
    }
}

void CloseLog() {
    if (!g_locksMade) return;
    // At process exit the loader has ended the writer already (its handle is
    // signalled). At a FreeLibrary it is alive and must leave this module's code
    // before the module goes: it clears g_writerRunning as its last act. Its own
    // exit then waits for the loader lock we hold, outside our code, so this
    // waits for the flag (at most ~100 ms), never for the thread to end.
    g_stop = 1;
    if (g_wake) SetEvent(g_wake);
    if (g_writer) {
        for (int i = 0; i < 100 && g_writerRunning; ++i) {
            if (WaitForSingleObject(g_writer, 0) == WAIT_OBJECT_0) break;
            Sleep(1);
        }
        CloseHandle(g_writer);
        g_writer = nullptr;
    }
    WritePending();
    EnterCriticalSection(&g_fileLock);
    if (g_log) {
        fclose(g_log);
        g_log = nullptr;
    }
    LeaveCriticalSection(&g_fileLock);
}

void LogFlush() {
    if (g_locksMade) WritePending();
}

void LogCostTake(LogCost* out) {
    out->calls = g_calls.exchange(0);
    out->bytes = g_bytes.exchange(0);
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    const long long t = g_ticks.exchange(0);
    out->ms = f.QuadPart ? static_cast<double>(t) * 1000.0 / static_cast<double>(f.QuadPart) : 0.0;
}

// Wall-clock stamped, because the only way to tell our own D3D9 calls apart from
// anyone else's in RTX Remix's bridge logs is to line the timestamps up.
void Log(const char* format, ...) {
    if (!g_log) return;
    LARGE_INTEGER t0;
    QueryPerformanceCounter(&t0);
    SYSTEMTIME now;
    GetLocalTime(&now);
    char small[2048];
    int head = snprintf(small, sizeof small, "[%02u:%02u:%02u.%03u] ", now.wHour, now.wMinute, now.wSecond,
                        now.wMilliseconds);
    va_list args;
    va_start(args, format);
    va_list again;
    va_copy(again, args);
    const int body = vsnprintf(small + head, sizeof small - head - 1, format, args);
    va_end(args);
    std::string big;
    const char* text = small;
    int length = 0;
    if (body < 0) {
        length = head;
    } else if (head + body + 1 < static_cast<int>(sizeof small)) {
        length = head + body;
    } else {
        big.assign(small, head);
        big.resize(head + body + 1);
        vsnprintf(&big[head], body + 1, format, again);
        big.resize(head + body);
        text = big.data();
        length = static_cast<int>(big.size());
    }
    va_end(again);
    // A crash's last words go out at once, on this thread.
    const bool urgent = strncmp(format, "FAULT", 5) == 0 || strstr(format, "call stack") != nullptr;
    if (!g_writerRunning) {
        EnterCriticalSection(&g_fileLock);
        if (g_log) {
            fwrite(text, 1, length, g_log);
            fputc('\n', g_log);
            fflush(g_log);
        }
        LeaveCriticalSection(&g_fileLock);
    } else {
        EnterCriticalSection(&g_pendingLock);
        g_pending.append(text, length);
        g_pending.push_back('\n');
        LeaveCriticalSection(&g_pendingLock);
        if (urgent) WritePending();
    }
    LARGE_INTEGER t1;
    QueryPerformanceCounter(&t1);
    g_calls.fetch_add(1);
    g_bytes.fetch_add(length + 1);
    g_ticks.fetch_add(t1.QuadPart - t0.QuadPart);
}

}  // namespace gta2dx9
