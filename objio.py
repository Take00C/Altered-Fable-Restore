"""Read objects from the AF/PM archives and convert AF objects to PM storage format.

AF: header at 2*(enc-K) = decoded_off - 3. Header (UnivUI FUN_1000a9c0): b0,b1,b2 [+1 if b1>>6 in (2,3)]
    [+2 if b0&3==2] [+4 if b0&3==3]; schema = f(b1>>6, b2[, b3]).
PM: header at 4*(enc-K): [flags][schema] (+ extra byte if flags & 0x80; schema word if flags&4 ...).
Raw size (dec_size()+3) covers header + body in both."""
import os, struct, threading

AF_RIO = os.environ.get("AFR_AF_RIO") or r"C:/age/マブラヴオルタードフェイブル/altfable.rio"
PM_RIO = os.environ.get("AFR_PM_RIO") or r"C:/Program Files (x86)/Steam/steamapps/common/Muv-Luv photonmelodies/photonmelodies11.rio"
K = 0xA2FB6AD1
KS = 0xE7B5D9F8
M = 0xFFFFFFFF


def sibling(path, suffix):
    """path + suffix; on case-sensitive file systems also accepts a name that differs only in case
    (ALTFABLE.RIO.002 next to altfable.rio, e.g. copied from a CD or a FAT stick)."""
    p = path + suffix
    if os.name == 'nt' or os.path.exists(p): return p
    d, b = os.path.split(p); low = b.lower()
    try:
        for e in os.listdir(d or '.'):
            if e.lower() == low: return os.path.join(d, e)
    except OSError:
        pass
    return p


_parts = {}       # archive path -> its part files; looked up once per process (a build never adds or removes parts)


def parts(path):
    """[path, path.002, path.003, ...] as far as they exist. Cached per path: read_at() asks for every read, and on
    case-sensitive file systems each lookup of the missing last part would cost an os.listdir (sibling)."""
    ps = _parts.get(path)
    if ps is None:
        ps = [path]; i = 2
        while True:
            p = sibling(path, '.%03d' % i)
            if not os.path.exists(p): break
            ps.append(p); i += 1
        _parts[path] = ps
    return list(ps)


_sizes = {}


_patch_map = {}   # archive path -> (patch file, virtual base)


def map_patch(path, patch_path, vbase):
    """Positions >= vbase of `path` resolve into `patch_path`. rUGP maps AF's .ruo1 at 0xD0000000: scripts of the
    official patch reference objects that exist only in the patch file by such positions."""
    _patch_map[path] = (patch_path, vbase)


_keep = [False]       # keep_open(True): read_at keeps one handle per file (a build: ~15,000 reads)
_handles = {}
_hlock = threading.Lock()


def keep_open(on):
    """While on, read_at keeps each file it reads open (one handle per file, reads under a lock: threads may share
    it); off closes them. A build turns it on for its run (build_all, app.do_build); off by default, so a long-running
    process (the window) never holds a game file open."""
    with _hlock:
        _keep[0] = bool(on)
        if not on:
            for f in _handles.values():
                try: f.close()
                except OSError: pass
            _handles.clear()


def _read(p, pos, n):
    if _keep[0]:
        with _hlock:
            if _keep[0]:
                f = _handles.get(p)
                if f is None: f = _handles[p] = open(p, 'rb')
                f.seek(pos); return f.read(n)
    with open(p, 'rb') as f:
        f.seek(pos); return f.read(n)


def read_at(path, pos, n):
    pm_ = _patch_map.get(path)
    if pm_ and pos >= pm_[1]:
        return _read(pm_[0], pos - pm_[1], n)
    ps = _parts.get(path) or parts(path)         # (the cached list itself: read_at only iterates it)
    out = b''
    for p in ps:
        sz = _sizes.get(p)
        if sz is None: sz = _sizes[p] = os.path.getsize(p)
        if pos < sz:
            chunk = _read(p, pos, min(n, sz - pos))
            out += chunk; n -= len(chunk); pos = 0
            if n <= 0: break
        else:
            pos -= sz
    return out


def enc_size(x):
    return ((((x >> 19) & 0xfff) + (x & 0xfff) | (x << 13)) + KS) & M


def dec_size_raw(v):
    a = (v - KS) & M; c = a >> 13; d = c & 0xFFF; a2 = (a - d) & M
    return ((a2 << 19) & M) | c


def af_header(raw):
    """Return (header_len, schema, mode, extra_word) per UnivUI FUN_1000a9c0."""
    b0, b1, b2 = raw[0], raw[1], raw[2]
    mode = b0 & 3; case = b1 >> 6; n = 3
    if case == 0: schema = b2 >> 6
    elif case == 1: schema = b2 >> 2
    elif case == 2: b3 = raw[3]; n = 4; schema = ((b2 & 0xfe) * 2) | ((b3 & 0xc0) * 2)
    else: b3 = raw[3]; n = 4; schema = ((b2 & 0xfe) * 2) | ((b3 & 0xfe) << 6)
    extra = None
    if mode == 2:
        extra = struct.unpack_from('<H', raw, n)[0]; n += 2
    elif mode == 3:
        schema = struct.unpack_from('<H', raw, n)[0]; extra = struct.unpack_from('<H', raw, n + 2)[0]; n += 4
    return n, schema, mode, extra


def af_object(dec_off, dec_size):
    """dec_off/dec_size as produced by rsaparse (AF formulas). Returns (schema, body, raw)."""
    pos = dec_off - 3; rawsize = dec_size + 3
    raw = read_at(AF_RIO, pos, rawsize)
    n, schema, mode, extra = af_header(raw)
    return schema, raw[n:], raw, (n, mode, extra)


def pm_object_pos(af_style_dec_off):
    """PM refs decoded by rsaparse with the AF formula -> PM byte position of the header."""
    return 4 * ((af_style_dec_off - 3) // 2)


def pm_object(af_style_dec_off, dec_size):
    pos = pm_object_pos(af_style_dec_off); rawsize = dec_size + 3
    return read_at(PM_RIO, pos, rawsize)


def pm_wrap(schema, body, flags=0x00, extra=None):
    hdr = bytes([flags, schema & 0xff])
    if flags & 0x80:
        hdr += bytes([extra or 0])
    return hdr + body


if __name__ == '__main__':
    import sys, collections
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from rsaparse import Heap
    h = Heap(open(os.path.join(os.path.dirname(__file__), '..', 'out', 'af_rsa', '000045d98b.bin'), 'rb').read(), 2); h.parse()
    seen = collections.Counter(); bad = 0
    for (pos, cls, off, size) in h.refs:
        if size < 0 or seen[cls[0]] >= 3: continue
        seen[cls[0]] += 1
        schema, body, raw, (n, mode, extra) = af_object(off, size)
        ok = schema == cls[1]
        bad += not ok
        print(cls, 'hdr', raw[:n].hex(' '), 'n', n, 'mode', mode, 'schema', schema, 'OK' if ok else 'MISMATCH', 'body', body[:6].hex(' '))
    print('mismatches', bad)
    # size codec roundtrip
    for x in [3, 716, 54513, 1474223, 123456789]:
        assert dec_size_raw(enc_size(x)) == x, x
    print('size codec ok')
