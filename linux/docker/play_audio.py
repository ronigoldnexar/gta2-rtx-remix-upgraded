#!/usr/bin/env python3
"""Game audio for the browser play page (play_game.sh starts both halves).

  play_audio.py serve      capture the PulseAudio null sink's monitor (parec), encode it
                           and hand it to whoever is connected on two local TCP ports:
                             5902  Opus (libopus through ctypes, CELT low delay, 48 kHz
                                   stereo, 10 ms frames, 96 kbit/s)
                             5903  PCM fallback (s16le, 24 kHz mono) for browsers without
                                   WebCodecs' AudioDecoder
                           parec runs only while somebody listens.
  play_audio.py web PORT   websockify on PORT (the page, noVNC and the audio on one port):
                           websocket path /audio -> 5902, /audio-pcm -> 5903,
                           every other path -> the VNC server (localhost:5900), so the old
                           noVNC links keep working.

Wire format on both audio ports (websockify relays the TCP bytes as binary websocket
messages, not aligned to packets, so the page reassembles them):
  u16 length of the rest | u32 sequence | f64 capture time (ms since the epoch) | payload
The capture time is the wall clock when the 10 ms block came out of parec; the page
uses it for the transit part of its latency readout.
"""
import ctypes, os, socket, struct, subprocess, sys, threading, time

RATE, CH, FRAME = 48000, 2, 480                 # 10 ms blocks
BLOCK = FRAME * CH * 2
OPUS_PORT, PCM_PORT = 5902, 5903
MAX_PENDING = 6000                              # bytes queued per client before blocks are dropped (~300 ms of Opus)
HDR = struct.Struct("<HId")


class Opus:
    def __init__(self, bitrate=96000, complexity=5):
        lib = ctypes.CDLL("libopus.so.0")
        lib.opus_encoder_create.restype = ctypes.c_void_p
        lib.opus_encoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.opus_encode.restype = ctypes.c_int32
        lib.opus_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int32]
        err = ctypes.c_int()
        self.enc = lib.opus_encoder_create(RATE, CH, 2051, ctypes.byref(err))   # OPUS_APPLICATION_RESTRICTED_LOWDELAY
        if err.value != 0 or not self.enc:
            raise RuntimeError("opus_encoder_create failed: %d" % err.value)
        lib.opus_encoder_ctl(ctypes.c_void_p(self.enc), 4002, ctypes.c_int32(bitrate))      # OPUS_SET_BITRATE
        lib.opus_encoder_ctl(ctypes.c_void_p(self.enc), 4010, ctypes.c_int32(complexity))   # OPUS_SET_COMPLEXITY
        self.lib, self.out = lib, ctypes.create_string_buffer(1500)

    def encode(self, pcm):
        n = self.lib.opus_encode(self.enc, pcm, FRAME, self.out, 1500)
        return self.out.raw[:n] if n > 0 else None


def to_pcm24_mono(pcm):
    # 48 kHz stereo s16 -> 24 kHz mono s16: the four samples of each output sample averaged.
    import array
    a = array.array("h"); a.frombytes(pcm)
    return array.array("h", [(a[i] + a[i + 1] + a[i + 2] + a[i + 3]) >> 2 for i in range(0, len(a), 4)]).tobytes()


class Server:
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = {}            # socket -> [kind, pending bytearray, dropped]
        self.wake = threading.Event()
        self.opus = Opus(int(os.environ.get("PLAY_AUDIO_BITRATE", "96000")))
        self.seq = 0

    def listen(self, port, kind):
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port)); s.listen(8)
        def loop():
            while True:
                c, _ = s.accept()
                c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                c.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)   # keep the backlog here, where it is bounded, not in the kernel
                c.setblocking(False)
                with self.lock:
                    self.clients[c] = [kind, bytearray(), 0]
                print("audio: %s client in (%d listening)" % (kind, len(self.clients)), flush=True)
                self.wake.set()
        threading.Thread(target=loop, daemon=True).start()

    def drop(self, c):
        with self.lock:
            st = self.clients.pop(c, None)
        try: c.close()
        except OSError: pass
        if st is not None:
            print("audio: %s client out (%d dropped blocks; %d listening)" % (st[0], st[2], len(self.clients)), flush=True)

    def send(self, msgs):
        with self.lock:
            items = list(self.clients.items())
        for c, st in items:
            kind, pend = st[0], st[1]
            m = msgs.get(kind)
            if m is not None:
                if len(pend) + len(m) <= MAX_PENDING: pend += m
                else: st[2] += 1          # the client is behind: drop the block rather than build latency
            if not pend: continue
            try:
                n = c.send(pend); del pend[:n]
            except BlockingIOError:
                pass
            except OSError:
                self.drop(c)

    def capture(self):
        dev = os.environ.get("PLAY_AUDIO_SOURCE", "null.monitor")
        while True:
            self.wake.wait(); self.wake.clear()
            with self.lock:
                if not self.clients: continue
            cmd = ["parec", "--device=" + dev, "--format=s16le", "--rate=%d" % RATE, "--channels=%d" % CH,
                   "--latency-msec=10", "--process-time-msec=5", "--raw"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            print("audio: capture on (%s)" % dev, flush=True)
            buf = bytearray()
            while True:
                d = p.stdout.read(BLOCK)
                if not d: break
                buf += d
                while len(buf) >= BLOCK:
                    pcm = bytes(buf[:BLOCK]); del buf[:BLOCK]
                    now = time.time() * 1000.0
                    with self.lock:
                        kinds = {st[0] for st in self.clients.values()}
                    if not kinds: break
                    self.seq = (self.seq + 1) & 0xFFFFFFFF
                    msgs = {}
                    if "opus" in kinds:
                        pkt = self.opus.encode(pcm)
                        if pkt: msgs["opus"] = HDR.pack(len(pkt) + 12, self.seq, now) + pkt
                    if "pcm" in kinds:
                        body = to_pcm24_mono(pcm)
                        msgs["pcm"] = HDR.pack(len(body) + 12, self.seq, now) + body
                    self.send(msgs)
                with self.lock:
                    if not self.clients: break
            p.kill(); p.wait()
            print("audio: capture off", flush=True)
            time.sleep(0.5)       # parec gone (no listener, or pulse not up yet): wait for the next client
            with self.lock:
                if self.clients: self.wake.set()


def serve():
    srv = Server()
    srv.listen(OPUS_PORT, "opus"); srv.listen(PCM_PORT, "pcm")
    print("audio: serving opus on %d, pcm on %d" % (OPUS_PORT, PCM_PORT), flush=True)
    srv.capture()


def web(port, webroot="/usr/share/novnc", vnc=("localhost", 5900)):
    from urllib.parse import urlparse
    from websockify import websocketproxy as wp
    routes = {"/audio": ("127.0.0.1", OPUS_PORT), "/audio-pcm": ("127.0.0.1", PCM_PORT)}
    def get_target(self, plugin):
        t = routes.get(urlparse(self.path).path.rstrip("/"))
        if t is None: return vnc
        try: self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError: pass
        return t
    wp.ProxyRequestHandler.get_target = get_target
    # A token plugin makes websockify ask get_target for every connection; BasePlugin itself is never consulted.
    sys.argv = ["websockify", "--token-plugin", "BasePlugin", "--token-source", "-", "--web", webroot, str(port)]
    wp.websockify_init()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve": serve()
    elif len(sys.argv) > 2 and sys.argv[1] == "web": web(int(sys.argv[2]))
    else: print(__doc__); sys.exit(2)
