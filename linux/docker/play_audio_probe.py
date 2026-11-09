#!/usr/bin/env python3
"""Headless check of the play page's audio, for hosts without a browser (no playwright/Chromium).

  docker cp play_audio_probe.py <play container>:/tmp/ && docker exec <play container> python3 /tmp/play_audio_probe.py [port] [seconds]

Runs inside the play container (python3 + libopus are there). Takes the same route a browser does:
GET the page, then a websocket on the page's port at path /audio (the websockify router in
play_audio.py), reassembles the u16 length | u32 seq | f64 capture-ms | payload packets across the
binary messages, decodes each Opus payload with libopus and reports packets/s, sequence gaps, transit
time (capture clock -> arrival, same machine) and the decoded level. A second, shorter connection to
/audio-pcm checks the fallback. Exit 0 when packets flowed at >= 90 % of 100/s with no decode error.
(The full client-side test with a real sound server and the mute button is play_audio_test.py.)
"""
import base64, ctypes, json, math, os, socket, struct, sys, time, urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PLAY_PORT", "6080"))
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
HDR = struct.Struct("<HId")


def ws_open(path):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: localhost:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n\r\n" % (path, PORT, key)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        d = s.recv(1)
        if not d: raise RuntimeError("closed during handshake")
        head += d
    if b" 101 " not in head.split(b"\r\n")[0]: raise RuntimeError("no upgrade: %r" % head.split(b"\r\n")[0])
    return s


def recv_exact(s, n):
    b = bytearray()
    while len(b) < n:
        d = s.recv(n - len(b))
        if not d: raise EOFError
        b += d
    return bytes(b)


def ws_frames(s):
    while True:
        h = recv_exact(s, 2); op, n = h[0] & 15, h[1] & 127
        if n == 126: n = struct.unpack(">H", recv_exact(s, 2))[0]
        elif n == 127: n = struct.unpack(">Q", recv_exact(s, 8))[0]
        if h[1] & 128: recv_exact(s, 4)          # servers do not mask, but be lenient
        body = recv_exact(s, n)
        if op == 8: return
        if op in (1, 2, 0):
            yield base64.b64decode(body) if op == 1 else body


def measure(path, secs, dec=None):
    s = ws_open(path); s.settimeout(3)
    buf = bytearray(); pk = 0; gaps = 0; last = None; transit = []; errs = 0; sq = 0.0; ns = 0; peak = 0
    t0 = time.time(); first = None
    pcm = (ctypes.c_int16 * (5760 * 2))()
    try:
        for m in ws_frames(s):
            buf += m
            while len(buf) >= 2:
                n = struct.unpack_from("<H", buf)[0]
                if len(buf) < 2 + n: break
                _, seq, cap = HDR.unpack_from(buf); body = bytes(buf[14:2 + n]); del buf[:2 + n]
                now = time.time() * 1000.0
                if first is None: first = now
                pk += 1; transit.append(now - cap)
                if last is not None and seq != (last + 1) & 0xFFFFFFFF: gaps += 1
                last = seq
                if dec is not None:
                    k = dec.opus_decode(dec.h, body, len(body), pcm, 5760, 0)
                    if k <= 0: errs += 1; continue
                    vals = pcm[:k * 2]
                else:
                    vals = struct.unpack("<%dh" % (len(body) // 2), body)
                for v in vals: sq += v * v; peak = max(peak, abs(v))
                ns += len(vals)
            if time.time() - t0 > secs: break
    finally:
        s.close()
    dur = max(1e-3, (time.time() * 1000.0 - first) / 1000.0) if first else secs
    transit.sort()
    q = lambda f: round(transit[min(len(transit) - 1, int(f * len(transit)))], 1) if transit else None
    rms = math.sqrt(sq / ns) if ns else 0.0
    return {"path": path, "packets": pk, "packets_per_s": round(pk / dur, 1), "seq_gaps": gaps, "decode_errors": errs,
            "transit_ms_p50": q(0.5), "transit_ms_p95": q(0.95),
            "rms_dbfs": round(20 * math.log10(max(1.0, rms) / 32768), 1), "peak": peak}


def opus_decoder():
    lib = ctypes.CDLL("libopus.so.0")
    lib.opus_decoder_create.restype = ctypes.c_void_p
    lib.opus_decoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.c_int]
    err = ctypes.c_int(); lib.h = lib.opus_decoder_create(48000, 2, ctypes.byref(err))
    if err.value or not lib.h: raise RuntimeError("opus_decoder_create %d" % err.value)
    return lib


page = urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=5).read()
cfg = {}
try: cfg = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/play_mode.json" % PORT, timeout=5).read())
except Exception: pass
res = {"page_bytes": len(page), "page_has_audio_bar": b'id="abar"' in page, "config": cfg}
res["opus"] = measure("/audio", SECS, opus_decoder())
res["pcm"] = measure("/audio-pcm", min(3.0, SECS))
print(json.dumps(res, indent=1))
ok = res["page_has_audio_bar"] and res["opus"]["packets_per_s"] >= 90 and not res["opus"]["decode_errors"] and res["pcm"]["packets"] > 0
sys.exit(0 if ok else 1)
