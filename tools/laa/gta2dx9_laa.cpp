// gta2dx9_laa.exe: the large-address-aware step for a player's gta2.exe, as an installer would run it
// (FIX-PERF-6; PREPARED, NOT SHIPPED: whether the release carries it is the owner's decision, see
// docs/stability.md "Large-address-aware gta2.exe").
//
//   gta2dx9_laa.exe status [<gta2.exe>]   says whether the bit is set
//   gta2dx9_laa.exe on     [<gta2.exe>]   keeps gta2.exe.no-laa (once, never overwritten), then sets the bit
//   gta2dx9_laa.exe off    [<gta2.exe>]   puts gta2.exe.no-laa back (or clears the bit if there is no backup)
//
// Without a path it works on gta2.exe beside itself. The one byte written is the low byte of
// IMAGE_FILE_HEADER.Characteristics (bit 0x0020, IMAGE_FILE_LARGE_ADDRESS_AWARE): for GTA2 9.6
// offset 0x11E, 0x0F -> 0x2F, the same file tools/set_laa.py and linux/laa.sh write (the PE checksum is
// left alone: the loader does not check it for an executable). A 32-bit process with the bit gets 4 GB of
// address space on 64-bit Windows instead of 2 GB (docs/performance.md, FIX-PERF-5 and FIX-PERF-6).
// Build: make laa-tool (MinGW), or cl /O2 gta2dx9_laa.cpp. Exit code 0 on success.
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {
const WORD kLaa = 0x0020;

bool ReadAll(const std::string& path, std::vector<unsigned char>* out) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    out->clear();
    unsigned char buf[65536];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) out->insert(out->end(), buf, buf + n);
    fclose(f);
    return true;
}

// Offset of IMAGE_FILE_HEADER.Characteristics in a 32-bit x86 PE, or 0.
size_t CharacteristicsOffset(const std::vector<unsigned char>& d) {
    if (d.size() < 0x40 || d[0] != 'M' || d[1] != 'Z') return 0;
    DWORD pe;
    memcpy(&pe, &d[0x3C], 4);
    if (pe + 24 > d.size() || memcmp(&d[pe], "PE\0\0", 4) != 0) return 0;
    WORD machine;
    memcpy(&machine, &d[pe + 4], 2);
    if (machine != 0x014C) return 0;
    return pe + 4 + 18;
}

bool WriteByte(const std::string& path, size_t at, unsigned char value) {
    FILE* f = fopen(path.c_str(), "r+b");
    if (!f) return false;
    const bool ok = fseek(f, static_cast<long>(at), SEEK_SET) == 0 && fputc(value, f) != EOF && fflush(f) == 0;
    fclose(f);
    return ok;
}
}  // namespace

int main(int argc, char** argv) {
    const std::string verb = argc > 1 ? argv[1] : "status";
    std::string exe;
    if (argc > 2) {
        exe = argv[2];
    } else {
        char self[MAX_PATH] = {};
        GetModuleFileNameA(nullptr, self, MAX_PATH);
        std::string dir(self);
        const size_t slash = dir.find_last_of("\\/");
        exe = (slash == std::string::npos ? std::string() : dir.substr(0, slash + 1)) + "gta2.exe";
    }
    const std::string backup = exe + ".no-laa";
    std::vector<unsigned char> d;
    if (!ReadAll(exe, &d)) { printf("cannot read %s\n", exe.c_str()); return 2; }
    const size_t at = CharacteristicsOffset(d);
    if (!at) { printf("%s is not a 32-bit x86 executable\n", exe.c_str()); return 2; }
    WORD ch;
    memcpy(&ch, &d[at], 2);
    const bool laa = (ch & kLaa) != 0;
    if (verb == "status") {
        printf("%s: Characteristics 0x%04X, large-address-aware: %s%s\n", exe.c_str(), ch, laa ? "yes" : "no",
               GetFileAttributesA(backup.c_str()) != INVALID_FILE_ATTRIBUTES ? " (backup gta2.exe.no-laa present)" : "");
        return 0;
    }
    if (verb == "on") {
        if (laa) { printf("%s is already large-address-aware (0x%04X); nothing written\n", exe.c_str(), ch); return 0; }
        if (GetFileAttributesA(backup.c_str()) == INVALID_FILE_ATTRIBUTES && !CopyFileA(exe.c_str(), backup.c_str(), TRUE)) {
            printf("cannot write the backup %s (error %lu); nothing changed\n", backup.c_str(), GetLastError());
            return 3;
        }
        if (!WriteByte(exe, at, static_cast<unsigned char>((ch | kLaa) & 0xFF))) {
            printf("cannot write %s (is the game running, or the folder read-only?)\n", exe.c_str());
            return 3;
        }
        printf("%s: Characteristics 0x%04X -> 0x%04X (large-address-aware); the original is %s\n", exe.c_str(), ch,
               ch | kLaa, backup.c_str());
        return 0;
    }
    if (verb == "off") {
        if (GetFileAttributesA(backup.c_str()) != INVALID_FILE_ATTRIBUTES) {
            if (!CopyFileA(backup.c_str(), exe.c_str(), FALSE)) { printf("cannot restore %s\n", exe.c_str()); return 3; }
            DeleteFileA(backup.c_str());
            printf("%s restored from %s\n", exe.c_str(), backup.c_str());
            return 0;
        }
        if (!laa) { printf("%s is not large-address-aware; nothing written\n", exe.c_str()); return 0; }
        if (!WriteByte(exe, at, static_cast<unsigned char>((ch & ~kLaa) & 0xFF))) { printf("cannot write %s\n", exe.c_str()); return 3; }
        printf("%s: Characteristics 0x%04X -> 0x%04X (no backup was found; the bit is cleared)\n", exe.c_str(), ch, ch & ~kLaa);
        return 0;
    }
    printf("usage: gta2dx9_laa.exe status|on|off [<path to gta2.exe>]\n");
    return 2;
}
