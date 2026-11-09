/* gang_respect.exe: a developer aid for scripted job runs (SKILL-GUNFIGHT, Wave M).
 *
 * The yellow and red phone jobs want a gang's respect at 2 or 4 bars before the phone
 * offers them (DO_PHONE_TEMPLATE (..., gang, 2) in the district scripts); a fresh game
 * has every gang at 0. This reads, and on request sets, the player's respect with each
 * gang in the running gta2.exe, so a job of the yellow tier can be played in a fresh
 * session. The game is not changed otherwise; the run's log says when it was used.
 *
 * Where it is (GTA2 9.6, read from the HUD's respect bars, FUN_004C74F0):
 *   [0x5EB898]                 the gang pool: 10 gangs, 0x144 bytes each
 *   gang + 0x000 (byte != 0)   the slot is in use (the gang's name starts there)
 *   gang + 0x11C + player      the player's respect, a signed byte -100..100; a bar is 20
 *   gang + 0x138               the gang's arrow colour / HUD order byte
 * Built with i686-w64-mingw32-gcc -O2 -o gang_respect.exe gang_respect.c
 *
 *   wine gang_respect.exe                list the gangs: index, name, respect
 *   wine gang_respect.exe <name> <value> set the respect with the gang whose name
 *                                        contains <name> (case-insensitive), e.g. loon 60
 */
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

#define GANG_POOL 0x5EB898u
#define GANG_SIZE 0x144u
#define RESPECT   0x11Cu

static DWORD find_game(void)
{
    PROCESSENTRY32 pe; HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    DWORD pid = 0;
    if (snap == INVALID_HANDLE_VALUE) return 0;
    pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) do {
        if (_stricmp(pe.szExeFile, "gta2.exe") == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32Next(snap, &pe));
    CloseHandle(snap);
    return pid;
}

static int contains_ci(const char *hay, const char *needle)
{
    size_t n = strlen(needle), i, j;
    for (i = 0; hay[i]; i++) {
        for (j = 0; j < n && hay[i + j] && tolower((unsigned char)hay[i + j]) == tolower((unsigned char)needle[j]); j++);
        if (j == n) return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    DWORD pid = find_game(), pool = 0; SIZE_T got = 0; HANDLE h; int i, done = 0;
    if (!pid) { printf("gang_respect: gta2.exe not running\n"); return 2; }
    h = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (!h) { printf("gang_respect: OpenProcess failed (%lu)\n", GetLastError()); return 3; }
    if (!ReadProcessMemory(h, (LPCVOID)GANG_POOL, &pool, 4, &got) || !pool) {
        printf("gang_respect: no gang pool yet (%lu)\n", GetLastError()); return 4;
    }
    for (i = 0; i < 10; i++) {
        unsigned char g[GANG_SIZE]; char name[17];
        if (!ReadProcessMemory(h, (LPCVOID)(pool + i * GANG_SIZE), g, GANG_SIZE, &got)) {
            printf("gang_respect: read failed (%lu)\n", GetLastError()); return 5;
        }
        if (!g[0]) continue;
        memcpy(name, g, 16); name[16] = 0;
        { int k; for (k = 0; k < 16; k++) if (name[k] && !isprint((unsigned char)name[k])) name[k] = '?'; }
        if (argc >= 3 && contains_ci(name, argv[1])) {
            signed char v = (signed char)atoi(argv[2]);
            if (!WriteProcessMemory(h, (LPVOID)(pool + i * GANG_SIZE + RESPECT), &v, 1, &got)) {
                printf("gang_respect: write failed (%lu)\n", GetLastError()); return 6;
            }
            g[RESPECT] = (unsigned char)v; done++;
        }
        printf("gang %d name=%s respect=%d,%d,%d,%d colour=%d\n", i, name,
               (signed char)g[RESPECT], (signed char)g[RESPECT + 1], (signed char)g[RESPECT + 2],
               (signed char)g[RESPECT + 3], g[0x138]);
    }
    if (argc >= 3) printf("gang_respect: set %d gang(s) matching '%s' to %s\n", done, argv[1], argv[2]);
    CloseHandle(h);
    return (argc >= 3 && !done) ? 7 : 0;
}
