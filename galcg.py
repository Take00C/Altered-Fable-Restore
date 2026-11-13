"""PM's EXTRAS > Gallery pictures rebuilt from the player's own Altered Fable originals (build_all F27 GALLERY; also the
story re-cuts of F28 CG45 and the gallery copy of F29 CG88). Pure Python, run on the player's files at patch time; no
picture data ships with the tool.

PM's gallery never draws the story objects that the CG overrides replace. Its full view (heap 00ba7f84ba, instructions
2051-2561) passes its own smaller Cr6Ti copies, its tiles (heap 00d5994f52) one 210x123 thumbnail per entry, and both
load by key through the ruo table like any other object (pm.exe FUN_005df070). Those are PM's edited pictures again, so
the build overrides them by key with pictures made here, PM's header kept (cgcrop.rebuild's layout):
  copies      Opaque1 (flag 0x00810602): the AF original resampled into PM's geometry by resample2 (cgcrop.resample's
              bilinear convention and fixed-point rounding with a separate y scale) and re-encoded by cgcrop.encode
              (rebuild_copy; checked: decodes back within 2 of the target);
  thumbnails  Transparent (flag 0x00810303): a Lanczos3 downscale (thumb) of the DECODED rebuilt copy at PM's window,
              7-bit like PM's own (floor(v + 0.5) & 0xfe), opaque, encoded by tencode for PM's drawer (rebuild_thumb).

PM's Transparent drawer FUN_0057eb80 (lab-tools/decomp/pm.c line 321661) holds a pixel as bytes biased by 0x80
(DAT_006241e0 = 80 80 80 00) and adds with paddsb, a signed saturating byte add, so every single add clamps to 0..255:
  prediction  pred = sat(sat(g + dg) + dg); tg = pred - g as a wrapping byte; base = tg >> 1 (psraw 9: floor)
  green step  dg = sat_s8(v1 + base); r, g, b = sat(sat(c + dg) + dg)
  residuals   r = sat(sat(r + v2) + v2); b = sat(sat(b + v3) + v3)
  store       pixel & DAT_006241f8 (fe fe fe ff); the masked pixel is also the register the next prediction starts from
  alpha       the alpha code ta (paddsb) is stored as ta << 26 into the pixel's dword (pm.c 321839 / 322188;
              DAT_00624228 = ff ff ff 00 keeps B / G / R), so the alpha byte is (ta & 0x3f) << 2; a copy-above pixel
              also masks ta to its low 6 bits (& 0x3f0000003f, pm.c 322065 / 322429); the blit draws a pixel opaque
              when the byte's top bit is set (pm.c 322543). ta 32 -> 0x80, PM's own thumbnails' value on every pixel
The research decoder cr6ti._transparent clamps once at the end and halves toward zero: it misreads 289 of PM's 293
thumbnails. tdecode here is the drawer's arithmetic, tencode tracks the drawer's state (for even targets 0..254 every
residual fits in -127..127: the prediction never leaves g's distance to 0 / 255), and rebuild_thumb refuses (BuildError)
a stream whose tdecode differs from its target or whose alpha byte is not 0x80 (ta 32) on every pixel.

thumb is platform-independent by construction: tap positions and Lanczos3 weights use only IEEE + - * / and floor (a
series sine, no libm call, no sum(), whose algorithm changed in Python 3.12), each output's taps are rounded to integers
that sum to exactly 1 << WBITS, and the pixel sums are exact integers, so every system and Python version gives the same
bytes (Windows and the Linux / Steam Deck build)."""
import math, operator, struct
import cgcrop
from builder import BuildError

__all__ = ['COPY_FLAG', 'THUMB_FLAG', 'DEPTH', 'WBITS', 'resample2', 'rows_needed2', 'taps', 'thumb', 'tencode',
           'tdecode', 'check_header', 'rebuild_copy', 'rebuild_thumb']

COPY_FLAG = 0x00810602          # Opaque1 (flag low byte 2, depth bit 2): PM's gallery copies and story cuts
THUMB_FLAG = 0x00810303         # Transparent (flag low byte 3): PM's gallery thumbnails
DEPTH = 0x07070707              # PM's depth field on all of them
WBITS = 14                      # fixed-point bits of the thumbnail's tap weights
_ONE = 1 << WBITS
_HEADER_FIELDS = ('w', 'h', 'w0', 'h0', 'flag', 'depth', 'scale', 'size_pos')


# ---------------------------------------------------------------- copies: resampling
def resample2(rows, W, H, kx, ky, x0, y0, ow, oh):
    """cgcrop.resample with a separate y scale: output pixel (u, v) centre maps to source (x0 + (u + 0.5) / kx - 0.5,
    y0 + (v + 0.5) / ky - 0.5), source pixel centres on integers, edges clamp, 8-bit fixed-point weights. With
    kx == ky the same expressions as cgcrop.resample, so the same bytes."""
    cols = []
    for u in range(ow):
        sx = x0 + (u + 0.5) / kx - 0.5
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
        sy = y0 + (v + 0.5) / ky - 0.5
        j0 = int(sy // 1); f = sy - j0
        if j0 < 0: j0, f = 0, 0.0
        if j0 >= H - 1: j0, f = H - 2, 1.0
        f = int(f * 256 + 0.5); g = 256 - f
        a = hrow(j0); b = hrow(j0 + 1)
        out.append(bytearray((a[i] * g + b[i] * f + 32768) >> 16 for i in range(3 * ow)))
    return out


def rows_needed2(H_src, ky, y0, oh):
    """Source rows resample2 reads for an output of oh rows (cgcrop.rows_needed with the y scale)."""
    return min(H_src, int(y0 + oh / ky) + 3)


# ---------------------------------------------------------------- thumbnails: Lanczos3, integer arithmetic
_PI = 3.141592653589793
_SIN = tuple((-1) ** k / math.factorial(2 * k + 1) for k in range(13))   # int / int: correctly rounded everywhere


def _sinpi(t):
    """sin(pi * t) from IEEE + - * and floor only: t - n is exact (|t - n| <= 0.5), then the series to x^25."""
    n = math.floor(t + 0.5)
    x = _PI * (t - n); x2 = x * x
    s = _SIN[-1]
    for c in _SIN[-2::-1]:
        s = s * x2 + c
    s *= x
    return -s if n & 1 else s


def _lanczos3(t):
    if t == 0: return 1.0
    if not -3.0 < t < 3.0: return 0.0
    p = _PI * t
    return 3.0 * _sinpi(t) * _sinpi(t / 3.0) / (p * p)


def taps(k, x0, n_out, N):
    """Per output position u (centre x0 + (u + 0.5) / k - 0.5 in source pixels): [(source index, integer weight)],
    Lanczos3 antialiased (support 3 / k when k < 1), indices outside 0..N-1 folded onto the edge pixel, the weights
    rounded cumulatively so that they sum to exactly 1 << WBITS."""
    s = k if k < 1.0 else 1.0
    R = 3.0 / s
    out = []
    for u in range(n_out):
        c = x0 + (u + 0.5) / k - 0.5
        idx = []; ws = []
        for i in range(math.floor(c - R), math.ceil(c + R) + 1):
            w = _lanczos3((i - c) * s)
            if w == 0.0: continue
            j = 0 if i < 0 else N - 1 if i >= N else i
            if idx and idx[-1] == j: ws[-1] += w
            else: idx.append(j); ws.append(w)
        total = 0.0
        for w in ws: total += w
        acc = 0.0; prev = 0; iw = []
        for w in ws:
            acc += w
            cur = math.floor(acc / total * _ONE + 0.5)
            iw.append(cur - prev); prev = cur
        if prev != _ONE or not idx: raise BuildError('thumbnail taps: weights sum to %d, not %d' % (prev, _ONE))
        out.append(list(zip(idx, iw)))
    return out


def thumb(rows, W, H, kx, ky, x0, y0, ow=210, oh=123):
    """rows: source rows (bytes-like, 3 per pixel; at least the rows the window reads) of a W x H picture -> oh
    bytearrays of 3 * ow: the Lanczos3 downscale at window (kx, ky, x0, y0), each value floor(v + 0.5) clamped to
    0..255 and & 0xfe."""
    ty = taps(ky, y0, oh, H); tx = taps(kx, x0, ow, W)
    if max(t[-1][0] for t in ty) >= len(rows): raise BuildError('thumbnail: source rows missing')
    c0 = min(t[0][0] for t in tx); c1 = max(t[-1][0] for t in tx) + 1
    txo = [[(3 * (i - c0), w) for i, w in t] for t in tx]
    sh = 2 * WBITS; half = 1 << (sh - 1)
    out = []
    for v in range(oh):
        acc = None
        for j, w in ty[v]:
            r = rows[j][3 * c0:3 * c1]
            acc = [w * b for b in r] if acc is None else [a + w * b for a, b in zip(acc, r)]
        row = bytearray(3 * ow); q = 0
        for t in txo:
            sr = sg = sb = 0
            for o, w in t:
                sr += w * acc[o]; sg += w * acc[o + 1]; sb += w * acc[o + 2]
            for val in (sr, sg, sb):
                val = (val + half) >> sh
                row[q] = (0 if val < 0 else 255 if val > 255 else val) & 0xfe; q += 1
        out.append(row)
    return out


# ---------------------------------------------------------------- Transparent coder (PM's drawer arithmetic)
def _cl(v): return 0 if v < 0 else 255 if v > 255 else v
def _s8(v): return -128 if v < -128 else 127 if v > 127 else v
def _wrap(t): return ((t + 128) & 0xff) - 128


class _Writer:
    def __init__(self): self.acc = 0; self.n = 0; self.out = bytearray()

    def put(self, code):
        c, L = code; self.acc |= c << self.n; self.n += L
        while self.n >= 8:
            self.out.append(self.acc & 0xFF); self.acc >>= 8; self.n -= 8

    def done(self):
        if self.n: self.out.append(self.acc & 0xFF)
        return bytes(self.out)


def _drawer_px(r, g, b, dg, v1, v2, v3):
    """One literal pixel under the drawer's arithmetic -> (r, g, b, dg), colours masked & 0xfe."""
    pred = _cl(_cl(g + dg) + dg)
    d = _s8(v1 + (_wrap(pred - g) >> 1))
    r1 = _cl(_cl(r + d) + d); g1 = _cl(_cl(g + d) + d); b1 = _cl(_cl(b + d) + d)
    r2 = _cl(_cl(r1 + v2) + v2); b2 = _cl(_cl(b1 + v3) + v3)
    return r2 & 0xfe, g1 & 0xfe, b2 & 0xfe, d


def tencode(W, H, rows):
    """rows: H bytes-like of 3 * W, every value even and at most 254 -> Transparent stream (bytes) that the drawer
    decodes to exactly these pixels, opaque (alpha byte 0x80). Per row PM's own form: alpha delta 32 with samea =
    W - 1, then literal spans and runs of exact repeats; a literal pixel is 'copy the pixel above' on an exact match
    (never in row 0) or a green step with red / blue residuals chosen under the drawer's arithmetic. BuildError on a
    value the coder cannot hold or a pixel it would not reach exactly."""
    SC = cgcrop.SCODE; U = cgcrop._ucode
    w = _Writer(); pr = [0] * W; pg = [0] * W; pb = [0] * W
    for y in range(H):
        T = rows[y]
        if len(T) != 3 * W: raise BuildError('Transparent coder: row %d has %d values, not %d' % (y, len(T), 3 * W))
        px = [(T[3 * x], T[3 * x + 1], T[3 * x + 2]) for x in range(W)]
        if any((R | G | B) & 1 or R > 254 or G > 254 or B > 254 for (R, G, B) in px):
            raise BuildError('Transparent coder: row %d has an odd value or 255 (7-bit pixels only)' % y)
        spans = []; x = 0                    # literal span [x, j), then a run of pixel j - 1 repeated k - j times
        while x < W:
            j = x + 1
            while j < W and px[j] != px[j - 1]: j += 1
            k = j
            while k < W and px[k] == px[j - 1]: k += 1
            spans.append((x, j, k - j)); x = k
        w.put(SC[32]); w.put(U(W - 1))      # ta = 32 -> alpha byte 0x80 for the whole row (samea = W - 1)
        r = g = b = dg = 0
        for (x0, x1, nrun) in spans:
            w.put(U(x1 - x0 - 1)); dg = 0   # span toggle: literal span of x1 - x0 pixels
            for x in range(x0, x1):
                R, G, B = px[x]
                if y and (pr[x], pg[x], pb[x]) == (R, G, B):
                    w.put((1, 1)); r, g, b = R, G, B; dg = 0
                    continue
                w.put((0, 1))
                pred = _cl(_cl(g + dg) + dg); base = _wrap(pred - g) >> 1
                v1 = (G - g) // 2 - base
                if not -127 <= v1 <= 127:
                    raise BuildError('Transparent coder: pixel (%d, %d) green step %d out of range' % (x, y, v1))
                d = _s8(v1 + base)
                r1 = _cl(_cl(r + d) + d); b1 = _cl(_cl(b + d) + d)
                v2 = (R - (r1 & 0xfe)) // 2; v3 = (B - (b1 & 0xfe)) // 2     # r1 = 255: 255 + 2*v2 = R + 1 -> R
                w.put(SC[v1]); w.put(SC[v2]); w.put(SC[v3])
                r, g, b, dg = _drawer_px(r, g, b, dg, v1, v2, v3)
                if (r, g, b) != (R, G, B):
                    raise BuildError('Transparent coder: pixel (%d, %d) would decode inexactly' % (x, y))
                pr[x], pg[x], pb[x] = r, g, b
            if nrun:
                w.put(U(nrun - 1)); dg = 0  # span toggle: run of the last pixel
                for x in range(x1, x1 + nrun): pr[x], pg[x], pb[x] = r, g, b
    return w.done()


class _Reader:
    def __init__(self, b, i): self.b = b; self.i = i; self.nb = 8; self.cur = 0

    def bit(self):
        if self.nb == 8:
            self.cur = self.b[self.i] if self.i < len(self.b) else 0; self.i += 1; self.nb = 0
        r = self.cur & 1; self.cur >>= 1; self.nb += 1
        return r

    def unsigned(self):
        if self.bit() == 0: return 0
        t = 1
        while True:
            t = (t << 1) | self.bit()
            if self.bit() == 0: break
        return t - 1

    def signed(self):
        if self.bit() == 0: return 0
        s = 1 - self.bit() * 2; t = 1
        for _ in range(6):
            if self.bit() == 0: break
            t = (t << 1) | self.bit()
        return s * t


def tdecode(body):
    """PM's Transparent drawer FUN_0057eb80 emulated (saturating adds, floor halving, 7-bit colour; control flow as
    cr6ti._transparent) -> (W, H, RGBA bytearray, end), alpha = the byte the drawer stores ((ta & 0x3f) << 2; 0x80 =
    opaque for ta 32), end = index of the byte after the last one read."""
    hd = cgcrop.header(body); W, H = hd['w'], hd['h']
    s = _Reader(body, hd['data_start']); px = bytearray(W * H * 4)
    pr = [0] * W; pg = [0] * W; pb = [0] * W
    for y in range(H):
        r = g = b = a = dg = ta = samea = samef = 0; f = True; row = y * W * 4; x = 0
        while x < W:
            samea -= 1
            if samea < 0:
                ta = _s8(ta + s.signed())
                if ta == 0:
                    n = s.unsigned()
                    for _ in range(n + 1):
                        if x >= W: break
                        pr[x] = pg[x] = pb[x] = 0; o = row + 4 * x; px[o:o + 4] = b'\0\0\0\0'; x += 1
                    continue
                if ta == 32: samea = s.unsigned()
                a = (ta & 0x3f) << 2                     # ta << 26 in the pixel dword: its top byte
            samef -= 1
            if samef < 0:
                f = not f; samef = s.unsigned(); dg = 0
            if f:
                if samea < samef:
                    pr[x] = r; pg[x] = g; pb[x] = b; o = row + 4 * x; px[o:o + 4] = bytes((r, g, b, a)); x += 1
                else:
                    if samef > 0: samea -= samef
                    for _ in range(samef + 1):
                        if x >= W: break
                        pr[x] = r; pg[x] = g; pb[x] = b; o = row + 4 * x; px[o:o + 4] = bytes((r, g, b, a)); x += 1
                    samef = 0
            elif s.bit() == 1:
                r = pr[x]; g = pg[x]; b = pb[x]; dg = 0; ta &= 0x3f      # copy above: the drawer masks ta too
                o = row + 4 * x; px[o:o + 4] = bytes((r, g, b, a)); x += 1
            else:
                pred = _cl(_cl(g + dg) + dg)
                dg = _s8(s.signed() + (_wrap(pred - g) >> 1))
                r = _cl(_cl(r + dg) + dg); g = _cl(_cl(g + dg) + dg); b = _cl(_cl(b + dg) + dg)
                v2 = s.signed(); r = _cl(_cl(r + v2) + v2)
                v3 = s.signed(); b = _cl(_cl(b + v3) + v3)
                r &= 0xfe; g &= 0xfe; b &= 0xfe
                pr[x] = r; pg[x] = g; pb[x] = b
                o = row + 4 * x; px[o:o + 4] = bytes((r, g, b, a)); x += 1
    return W, H, px, s.i


# ---------------------------------------------------------------- PM header kept
def check_header(body, flag, what):
    """PM's picture: the expected coder (flag, depth) and a plain stored picture (w == w0, h == h0); -> header."""
    try:
        hd = cgcrop.header(body)
    except ValueError as e:
        raise BuildError('%s: %s' % (what, e))
    if hd['flag'] != flag or hd['depth'] != DEPTH or hd['w'] != hd['w0'] or hd['h'] != hd['h0']:
        raise BuildError('%s: PM picture is flag %#x depth %#x, %dx%d in %dx%d (want flag %#x depth %#x, plain)' % (
            what, hd['flag'], hd['depth'], hd['w'], hd['h'], hd['w0'], hd['h0'], flag, DEPTH))
    return hd


def _relayout(pm_body, hp, data, what):
    """PM's body with a new data stream (cgcrop.rebuild's layout); the header fields must come out unchanged."""
    p = hp['size_pos']
    body = (pm_body[:p] + struct.pack('<I', len(data)) + pm_body[p + 4:p + 12] + data + bytes(len(data) & 1)
            + pm_body[-2:])
    h2 = cgcrop.header(body)
    bad = [k for k in _HEADER_FIELDS if h2[k] != hp[k]]
    if bad or body[:p] != pm_body[:p] or body[p + 4:p + 12] != pm_body[p + 4:p + 12] or h2['data_size'] != len(data):
        raise BuildError('%s: rebuilt header differs from PM\'s (%s)' % (what, ', '.join(bad) or 'bytes'))
    return body


def rebuild_copy(pm_body, src, win, what='copy'):
    """PM Opaque1 body (header kept) whose pixels are a decoded AF picture src = (W, H, rows; at least the rows the
    window reads) resampled into window win = (kx, ky, x0, y0). Decoded back (cgcrop.decode) and refused unless every
    value is within 2 of the target. Returns (new body, target rows)."""
    hp = check_header(pm_body, COPY_FLAG, what)
    W, H, rows = src
    kx, ky, x0, y0 = win
    if rows_needed2(H, ky, y0, hp['h']) > len(rows): raise BuildError('%s: source rows missing' % what)
    tgt = resample2(rows, W, len(rows), kx, ky, x0, y0, hp['w'], hp['h'])
    body = _relayout(pm_body, hp, cgcrop.encode(hp['w'], hp['h'], tgt), what)
    W2, H2, back = cgcrop.decode(body)
    if (W2, H2, len(back)) != (hp['w'], hp['h'], hp['h']): raise BuildError('%s: decodes to another size' % what)
    worst = 0
    for t, b in zip(tgt, back):
        if t != b: worst = max(worst, max(map(abs, map(operator.sub, t, b))))
    if worst > 2: raise BuildError('%s: decodes up to %d away from its target (at most 2)' % (what, worst))
    return body, tgt


def rebuild_thumb(pm_body, copy_body, win, what='thumbnail'):
    """PM Transparent thumbnail body (header kept) made from the Opaque1 copy copy_body as decoded: Lanczos3 at window
    win = (kx, ky, x0, y0) in copy pixels, 7-bit, opaque. Refused unless the drawer emulation (tdecode) reads back
    exactly the target with alpha byte 0x80 (ta 32, like PM's own thumbnails) on every pixel. Returns the new body."""
    ht = check_header(pm_body, THUMB_FLAG, what)
    hc = cgcrop.header(copy_body)
    kx, ky, x0, y0 = win
    need = max(t[-1][0] for t in taps(ky, y0, ht['h'], hc['h'])) + 1
    W, H, rows = cgcrop.decode(copy_body, need)
    trows = thumb(rows, W, H, kx, ky, x0, y0, ht['w'], ht['h'])
    data = tencode(ht['w'], ht['h'], trows)
    body = _relayout(pm_body, ht, data, what)
    Wd, Hd, px, end = tdecode(body)
    rgb = bytearray(3 * Wd * Hd); rgb[0::3] = px[0::4]; rgb[1::3] = px[1::4]; rgb[2::3] = px[2::4]
    if (Wd, Hd) != (ht['w'], ht['h']) or bytes(rgb) != b''.join(bytes(r) for r in trows):
        raise BuildError('%s: the drawer would not read back the target' % what)
    if px[3::4] != b'\x80' * (Wd * Hd): raise BuildError('%s: not opaque everywhere (alpha byte not 0x80)' % what)
    if end > ht['size_pos'] + 12 + len(data): raise BuildError('%s: the drawer reads past the stream' % what)
    return body
