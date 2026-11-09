// Shared logging to gta2dx9.log beside the game executable.
#pragma once

namespace gta2dx9 {

void OpenLog();
void CloseLog();
void Log(const char* format, ...);
// Writes every line logged so far to the file now (a writer thread does it every
// 15 ms otherwise; see log.cpp).
void LogFlush();

// What Log() cost the threads that called it since the last take.
struct LogCost {
    long calls;
    long bytes;
    double ms;
};
void LogCostTake(LogCost* out);

}  // namespace gta2dx9
