"""Rebuild a cropped PM picture (Cr6Ti) from the player's own Altered Fable original.

PM ships some AF CGs only as crops or re-scaled copies of its edited versions (close-ups cut from the edited hot-spring
CG, the tall 45d98b CGs cut to 16:9). Overriding those objects with the AF body would change their size on screen, so
the build resamples the AF picture into PM's exact geometry (the crop window found by pixel statistics, see
lab-tools/out/research/asset-sweep) and re-encodes it with PM's own coder (Opaque1) under PM's own header. Everything
runs on the player's files at patch time; no picture data ships with the tool.

Cr6Ti body (after the 2-byte PM / 3-4 byte AF archive header): +0 u32 0x45, +4/+6 canvas w/h, +8 x/y offset,
+12/+14 stored w/h, +16 flag (low byte 2 = opaque), +20 depth (bit 2 set = Opaque1 coder), then a class slot,
u32 data_size, f32 scale, u32 0, data[(data_size + 1) & ~1], 2 trailing bytes.
Opaque1 = alterdec r6ti.cpp / afhook CImageWriter Opaque1: per row a predictive green delta with red/blue residuals,
'copy the pixel above' flags and runs; bits LSB first.
"""
import struct

__all__ = ['header', 'decode', 'encode', 'resample', 'rebuild']


def header(b):
    w0, h0 = struct.unpack_from('<HH', b, 4)
    w, h = struct.unpack_from('<HH', b, 12)
    flag, depth = struct.unpack_from('<II', b, 16)
    for p in range(26, min(len(b) - 11, 8192)):
        L = struct.unpack_from('<I', b, p)[0]
        if L <= len(b) and p + 12 + ((L + 1) & ~1) + 2 == len(b):
            return dict(w=w, h=h, w0=w0, h0=h0, flag=flag, depth=depth, size_pos=p, data_start=p + 12, data_size=L,
                        scale=struct.unpack_from('<f', b, p + 4)[0])
    raise ValueError('Cr6Ti: data start not found')


# ---------------------------------------------------------------- variable-length codes
def _signed_code(v):
    if v == 0: return 0, 1
    t = abs(v); bits = [1, 0 if v > 0 else 1]
    digits = bin(t)[3:]
    for d in digits: bits += [1, int(d)]
    if len(digits) < 6: bits.append(0)
    return sum(b << i for i, b in enumerate(bits)), len(bits)


def _unsigned_code(v):
    if v == 0: return 0, 1
    bits = [1]; digits = bin(v + 1)[3:]
    for i, d in enumerate(digits): bits += [int(d), 1 if i < len(digits) - 1 else 0]
    return sum(b << i for i, b in enumerate(bits)), len(bits)


SCODE = {v: _signed_code(v) for v in range(-127, 128)}
_UCODE = {}


def _ucode(v):
    c = _UCODE.get(v)
    if c is None: c = _UCODE[v] = _unsigned_code(v)
    return c


def _table(codes):
    t = [None] * 65536
    for v, (c, L) in codes:
        if L > 16: continue
        for k in range(1 << (16 - L)):
            t[c | (k << L)] = (v, L)
    return t


STAB = _table(SCODE.items())
UTAB = _table((v, _unsigned_code(v)) for v in range(255))


def _cl(v):
    return 0 if v < 0 else 255 if v > 255 else v


# ---------------------------------------------------------------- decoder (Opaque1)
def decode(body, rows=None):
    """-> (W, H, list of bytearray rows, 3 bytes per pixel in the coder's channel order). rows: stop after that many."""
    hd = header(body)
    if hd['flag'] & 0xff != 2 or not hd['depth'] & 4: raise ValueError('Cr6Ti: only Opaque1 is handled')
    W, H = hd['w'], hd['h']
    n_rows = H if rows is None else min(H, rows)
    data = body; ip = hd['data_start']; end = hd['data_start'] + hd['data_size']
    data = bytes(data[ip:end]) + b'\x00' * 16; ip = 0
    buf = 0; nb = 0
    pr = [0] * W; pg = [0] * W; pb = [0] * W
    out = []
    S = STAB; U = UTAB
    for y in range(n_rows):
        row = bytearray(3 * W)
        count = -1; r = g = b = 0; dg = 0; x = 0
        while x < W:
            if nb < 64:
                buf |= int.from_bytes(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
            if count == -1:
                e = U[buf & 0xFFFF]
                if e is None:
                    if buf & 1 == 0: count = 0; buf >>= 1; nb -= 1
                    else:
                        buf >>= 1; nb -= 1; t = 1
                        while True:
                            if nb < 8: buf |= int.from_bytes(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                            t = (t << 1) | (buf & 1); c = (buf >> 1) & 1; buf >>= 2; nb -= 2
                            if c == 0: break
                        count = t - 1
                    if nb < 48: buf |= int.from_bytes(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                else:
                    count = e[0]; buf >>= e[1]; nb -= e[1]
            if buf & 1:
                buf >>= 1; nb -= 1
                r = pr[x]; g = pg[x]; b = pb[x]; dg = 0
            else:
                buf >>= 1
                t = g + dg * 2; t = (0 if t < 0 else 255 if t > 255 else t) - g
                v, L = S[buf & 0xFFFF]; buf >>= L
                dg = v + (t // 2 if t >= 0 else -((-t) // 2))
                if dg < -128: dg = -128
                elif dg > 127: dg = 127
                d2 = dg * 2
                r += d2; g += d2; b += d2
                r = 0 if r < 0 else 255 if r > 255 else r
                g = 0 if g < 0 else 255 if g > 255 else g
                b = 0 if b < 0 else 255 if b > 255 else b
                v2, L2 = S[buf & 0xFFFF]; buf >>= L2
                r += v2 * 2; r = 0 if r < 0 else 255 if r > 255 else r
                v3, L3 = S[buf & 0xFFFF]; buf >>= L3
                b += v3 * 2; b = 0 if b < 0 else 255 if b > 255 else b
                nb -= 1 + L + L2 + L3
                pr[x] = r; pg[x] = g; pb[x] = b
            o = 3 * x; row[o] = r; row[o + 1] = g; row[o + 2] = b; x += 1
            c0 = count; count -= 1
            if c0 == 0 and x < W:
                if nb < 32: buf |= int.from_bytes(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                e = U[buf & 0xFFFF]
                if e is None:
                    buf >>= 1; nb -= 1; t = 1
                    while True:
                        if nb < 8: buf |= int.from_bytes(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                        t = (t << 1) | (buf & 1); c = (buf >> 1) & 1; buf >>= 2; nb -= 2
                        if c == 0: break
                    n = t
                else:
                    n = e[0] + 1; buf >>= e[1]; nb -= e[1]
                if n > W - x: n = W - x
                for xx in range(x, x + n):
                    pr[xx] = r; pg[xx] = g; pb[xx] = b
                row[3 * x:3 * (x + n)] = bytes((r, g, b)) * n
                x += n; dg = 0
        out.append(row)
    return W, H, out


# ---------------------------------------------------------------- encoder (Opaque1)
def _half(d, target):
    """Delta step k (value moves by 2k, clamped to 0..255) that lands closest to target."""
    k = d // 2 if d >= 0 else -((-d) // 2)
    if d & 1 and target in (0, 255): k += 1 if d > 0 else -1    # overshoot into the clamp: exact 0 / 255
    return k


def encode(W, H, rows, tol=2, rtol=0):
    """rows: H bytearrays of 3*W -> Opaque1 bit stream (bytes). Lossy by at most max(tol, rtol, 1) per channel:
    tol for 'copy the pixel above', rtol for a zero residual (smaller output; 0 = exact up to the coder's 2-steps)."""
    out = bytearray(); acc = 0; na = 0
    SC = SCODE
    pr = [0] * W; pg = [0] * W; pb = [0] * W
    for y in range(H):
        T = rows[y]
        # group plan: literal pixels up to the first pixel that repeats, then a run of the repeats
        x = 0; r = g = b = 0; dg = 0
        while x < W:
            j = x
            while j < W - 1 and T[3 * j:3 * j + 3] != T[3 * j + 3:3 * j + 6]: j += 1
            if j >= W - 1: j = W - 1; run = 0
            else:
                k = j + 1; p = T[3 * j:3 * j + 3]
                while k < W and T[3 * k:3 * k + 3] == p: k += 1
                run = k - j - 1
            c, L = _ucode(j - x); acc |= c << na; na += L
            for xx in range(x, j + 1):
                o = 3 * xx; R = T[o]; G = T[o + 1]; B = T[o + 2]
                ar = pr[xx]; ag = pg[xx]; ab = pb[xx]
                # never in row 0: PM's Opaque1 drawer (FUN_0057e490) reads an uninitialised line buffer there, and
                # age's encoder never copies in row 0 (0 of 1955 originals)
                if y and -tol <= ar - R <= tol and -tol <= ag - G <= tol and -tol <= ab - B <= tol:
                    acc |= 1 << na; na += 1
                    r = ar; g = ag; b = ab; dg = 0
                else:
                    na += 1                                       # flag bit 0
                    t = g + dg * 2; t = (0 if t < 0 else 255 if t > 255 else t) - g
                    base = t // 2 if t >= 0 else -((-t) // 2)
                    want = _half(G - g, G)
                    if rtol:
                        g0 = g + 2 * (-128 if base < -128 else 127 if base > 127 else base)
                        g0 = 0 if g0 < 0 else 255 if g0 > 255 else g0
                        if -rtol <= g0 - G <= rtol: want = base
                    if want < -128: want = -128
                    elif want > 127: want = 127
                    res = want - base
                    if res < -127: res = -127
                    elif res > 127: res = 127
                    dg = res + base
                    if dg < -128: dg = -128
                    elif dg > 127: dg = 127
                    d2 = dg * 2
                    r = _cl(r + d2); g = _cl(g + d2); b = _cl(b + d2)
                    sr = 0 if -rtol <= r - R <= rtol and rtol else _half(R - r, R)
                    sr = -127 if sr < -127 else 127 if sr > 127 else sr
                    sb = 0 if -rtol <= b - B <= rtol and rtol else _half(B - b, B)
                    sb = -127 if sb < -127 else 127 if sb > 127 else sb
                    r = _cl(r + sr * 2); b = _cl(b + sb * 2)
                    c, L = SC[res]; acc |= c << na; na += L
                    c, L = SC[sr]; acc |= c << na; na += L
                    c, L = SC[sb]; acc |= c << na; na += L
                    pr[xx] = r; pg[xx] = g; pb[xx] = b
                if na >= 64:
                    out += (acc & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'); acc >>= 64; na -= 64
            x = j + 1
            if run:
                c, L = _ucode(run - 1); acc |= c << na; na += L
                for xx in range(x, x + run):
                    pr[xx] = r; pg[xx] = g; pb[xx] = b
                x += run; dg = 0
            if na >= 64:
                out += (acc & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'); acc >>= 64; na -= 64
    while na > 0:
        out.append(acc & 0xFF); acc >>= 8; na -= 8
    return bytes(out)


# ---------------------------------------------------------------- resampling
def resample(rows, W, H, k, x0, y0, ow, oh):
    """Bilinear samples of a source picture for an ow x oh window: output pixel (u, v) centre maps to source
    (x0 + (u + 0.5) / k - 0.5, y0 + (v + 0.5) / k - 0.5), source pixel centres on integers (the crop search's
    convention). Edges clamp."""
    cols = []
    for u in range(ow):
        sx = x0 + (u + 0.5) / k - 0.5
        i0 = int(sx // 1); f = sx - i0
        if i0 < 0: i0, f = 0, 0.0
        if i0 >= W - 1: i0, f = W - 2, 1.0
        cols.append((3 * i0, int(f * 256 + 0.5)))
    cache = {}

    def hrow(j):
        h = cache.get(j)
        if h is None:
            s = rows[j]; h = [0] * (3 * ow); q = 0
            for (o, f) in cols:
                g = 256 - f
                h[q] = s[o] * g + s[o + 3] * f; h[q + 1] = s[o + 1] * g + s[o + 4] * f
                h[q + 2] = s[o + 2] * g + s[o + 5] * f; q += 3
            if len(cache) > 4: cache.clear()
            cache[j] = h
        return h

    out = []
    for v in range(oh):
        sy = y0 + (v + 0.5) / k - 0.5
        j0 = int(sy // 1); f = sy - j0
        if j0 < 0: j0, f = 0, 0.0
        if j0 >= H - 1: j0, f = H - 2, 1.0
        f = int(f * 256 + 0.5); g = 256 - f
        a = hrow(j0); b = hrow(j0 + 1)
        out.append(bytearray((a[i] * g + b[i] * f + 32768) >> 16 for i in range(3 * ow)))
    return out


def rows_needed(H_src, k, y0, oh):
    return min(H_src, int(y0 + oh / k) + 3)


def rebuild(pm_body, src, crop):
    """PM body (header kept) whose pixels are a decoded AF picture src = (W, H, rows) resampled into PM's crop window
    crop = (k, x, y). Returns (new body, target rows)."""
    hp = header(pm_body)
    if hp['flag'] & 0xff != 2 or not hp['depth'] & 4 or hp['w'] != hp['w0'] or hp['h'] != hp['h0']:
        raise ValueError('PM picture is not a plain Opaque1 picture')
    W, H, rows = src
    k, x0, y0 = crop
    if rows_needed(H, k, y0, hp['h']) > len(rows): raise ValueError('source rows missing')
    tgt = resample(rows, W, len(rows), k, x0, y0, hp['w'], hp['h'])
    data = encode(hp['w'], hp['h'], tgt)
    p = hp['size_pos']
    body = (pm_body[:p] + struct.pack('<I', len(data)) + pm_body[p + 4:p + 12] + data + bytes(len(data) & 1)
            + pm_body[-2:])
    return body, tgt


def shrink(body, limit, steps=((2, 2), (3, 3), (4, 4), (5, 5), (6, 6))):
    """Same picture, same header, re-encoded so the body is at most `limit` bytes (smallest tolerance that fits).
    Returns (body, (tol, rtol)) or (None, None) when no step fits."""
    hd = header(body)
    W, H, rows = decode(body)
    p = hd['size_pos']; fixed = p + 12 + 2
    start = 0 if len(body) * 0.84 <= limit else min(2, len(steps) - 1)    # measured: (2,2) saves ~15%, (4,4) ~28%
    for tol, rtol in steps[start:]:
        data = encode(W, H, rows, tol, rtol)
        if fixed + len(data) + (len(data) & 1) <= limit:
            return (body[:p] + struct.pack('<I', len(data)) + body[p + 4:p + 12] + data + bytes(len(data) & 1)
                    + body[-2:]), (tol, rtol)
    return None, None
