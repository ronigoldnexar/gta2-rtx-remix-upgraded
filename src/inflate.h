// DISTRICTS round 6: a small raw DEFLATE (RFC 1951) decoder for the compressed facade-kit chunks (pack_kit.py writes
// them with Python's zlib, wbits -15). Written for this project; no external code.
#pragma once
#include <cstddef>
#include <cstdint>

namespace gta2 {
// Decodes src (n bytes of raw deflate) into dst (exactly cap bytes expected). True when the stream decodes
// completely and fills exactly cap bytes.
bool Inflate(const uint8_t* src, size_t n, uint8_t* dst, size_t cap);
}
