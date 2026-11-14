// DISTRICTS round 6: raw DEFLATE decoder (RFC 1951); see inflate.h.
#include "inflate.h"

#include <cstring>

namespace gta2 {
namespace {

struct Bits {
    const uint8_t* p; const uint8_t* end;
    uint32_t buf = 0; int cnt = 0; bool bad = false;
    uint32_t Get(int n) {
        while (cnt < n) {
            if (p >= end) { bad = true; return 0; }
            buf |= static_cast<uint32_t>(*p++) << cnt;
            cnt += 8;
        }
        const uint32_t v = buf & ((1u << n) - 1u);
        buf >>= n; cnt -= n;
        return v;
    }
};

// canonical Huffman table: counts per length, symbols in code order
struct Huff {
    uint16_t count[16];
    uint16_t symbol[320];
};

bool Build(Huff* h, const uint8_t* lengths, int n) {
    memset(h->count, 0, sizeof h->count);
    for (int i = 0; i < n; ++i) h->count[lengths[i]]++;
    h->count[0] = 0;
    int left = 1;
    for (int len = 1; len < 16; ++len) { left <<= 1; left -= h->count[len]; if (left < 0) return false; }
    uint16_t offs[16];
    offs[1] = 0;
    for (int len = 1; len < 15; ++len) offs[len + 1] = static_cast<uint16_t>(offs[len] + h->count[len]);
    for (int i = 0; i < n; ++i) if (lengths[i]) h->symbol[offs[lengths[i]]++] = static_cast<uint16_t>(i);
    return true;
}

int Decode(Bits* b, const Huff* h) {
    int code = 0, first = 0, index = 0;
    for (int len = 1; len < 16; ++len) {
        code |= static_cast<int>(b->Get(1));
        const int count = h->count[len];
        if (code - count < first) return h->symbol[index + (code - first)];
        index += count; first += count; first <<= 1; code <<= 1;
        if (b->bad) return -1;
    }
    return -1;
}

const uint16_t kLenBase[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
const uint8_t kLenExtra[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
const uint16_t kDistBase[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073,
                                4097, 6145, 8193, 12289, 16385, 24577};
const uint8_t kDistExtra[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

bool Codes(Bits* b, uint8_t* dst, size_t cap, size_t* out, const Huff* lit, const Huff* dist) {
    for (;;) {
        const int sym = Decode(b, lit);
        if (sym < 0 || b->bad) return false;
        if (sym < 256) {
            if (*out >= cap) return false;
            dst[(*out)++] = static_cast<uint8_t>(sym);
        } else if (sym == 256) {
            return true;
        } else {
            const int li = sym - 257;
            if (li >= 29) return false;
            const size_t len = kLenBase[li] + b->Get(kLenExtra[li]);
            const int ds = Decode(b, dist);
            if (ds < 0 || ds >= 30 || b->bad) return false;
            const size_t d = kDistBase[ds] + b->Get(kDistExtra[ds]);
            if (d > *out || *out + len > cap) return false;
            for (size_t k = 0; k < len; ++k, ++*out) dst[*out] = dst[*out - d];
        }
    }
}

}  // namespace

bool Inflate(const uint8_t* src, size_t n, uint8_t* dst, size_t cap) {
    Bits b{src, src + n};
    size_t out = 0;
    static Huff fixedLit, fixedDist;
    static bool fixedReady = false;
    if (!fixedReady) {
        uint8_t l[288];
        for (int i = 0; i < 144; ++i) l[i] = 8;
        for (int i = 144; i < 256; ++i) l[i] = 9;
        for (int i = 256; i < 280; ++i) l[i] = 7;
        for (int i = 280; i < 288; ++i) l[i] = 8;
        Build(&fixedLit, l, 288);
        uint8_t d[30];
        for (int i = 0; i < 30; ++i) d[i] = 5;
        Build(&fixedDist, d, 30);
        fixedReady = true;
    }
    int last = 0;
    do {
        last = static_cast<int>(b.Get(1));
        const uint32_t type = b.Get(2);
        if (b.bad) return false;
        if (type == 0) {
            b.buf = 0; b.cnt = 0;                     // to a byte boundary
            if (b.end - b.p < 4) return false;
            const uint32_t len = b.p[0] | (b.p[1] << 8), nlen = b.p[2] | (b.p[3] << 8);
            b.p += 4;
            if ((len ^ 0xFFFFu) != nlen || static_cast<size_t>(b.end - b.p) < len || out + len > cap) return false;
            memcpy(dst + out, b.p, len); b.p += len; out += len;
        } else if (type == 1) {
            if (!Codes(&b, dst, cap, &out, &fixedLit, &fixedDist)) return false;
        } else if (type == 2) {
            const int nlen = static_cast<int>(b.Get(5)) + 257, ndist = static_cast<int>(b.Get(5)) + 1, ncode = static_cast<int>(b.Get(4)) + 4;
            static const uint8_t order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
            uint8_t lengths[320] = {};
            for (int i = 0; i < ncode; ++i) lengths[order[i]] = static_cast<uint8_t>(b.Get(3));
            Huff lencode;
            if (b.bad || !Build(&lencode, lengths, 19)) return false;
            int i = 0;
            while (i < nlen + ndist) {
                const int sym = Decode(&b, &lencode);
                if (sym < 0) return false;
                if (sym < 16) { lengths[i++] = static_cast<uint8_t>(sym); continue; }
                int rep = 0; uint8_t val = 0;
                if (sym == 16) { if (!i) return false; val = lengths[i - 1]; rep = 3 + static_cast<int>(b.Get(2)); }
                else if (sym == 17) rep = 3 + static_cast<int>(b.Get(3));
                else rep = 11 + static_cast<int>(b.Get(7));
                if (i + rep > nlen + ndist) return false;
                while (rep--) lengths[i++] = val;
            }
            Huff lit, dist;
            if (b.bad || !Build(&lit, lengths, nlen) || !Build(&dist, lengths + nlen, ndist)) return false;
            if (!Codes(&b, dst, cap, &out, &lit, &dist)) return false;
        } else {
            return false;
        }
    } while (!last);
    return out == cap;
}

}  // namespace gta2
