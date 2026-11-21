"""Fast forms of the picture pass's re-encodes (build_all's CG re-crops, gallery copies / thumbnails, story re-cuts and
0.1.2's gallery pictures; reencache's misses and picpool's workers). Pure Python, no numpy, no compiled code.

Every function here returns exactly the bytes of its reference in cgcrop / galcg (which stay unchanged: they are the
oracles and the re-encode cache's identity, reencache._code_id / _gal_code_id; nothing here assigns to them):
  decode            cgcrop.decode (same rows)
  encode_track      cgcrop.encode with rtol 0 (same stream) and the rows its decoder reads back from that stream
  resample          cgcrop.resample;  resample2  galcg.resample2
  thumb             galcg.thumb
  rebuild           cgcrop.rebuild;   rebuild_copy  galcg.rebuild_copy;   rebuild_thumb  galcg.rebuild_thumb
  shrink            cgcrop.shrink
Proofs (lab-tools/out/research/fast-build/impl): every function against its reference (lab-only picoracle.py, verbatim
copies of the 0.1.2 functions) on random and edge inputs (sizes 1..4097, extreme values, every coder path), the code
tables exhaustively, and every picture of the default build byte for byte against the reference build's cache.

How (form only, the same arithmetic):
  decode        no pr / pg / pb (the row above is the previous output row, which holds exactly those values); a loop
                per group (count code, count + 1 literal / copy pixels, a run); a literal pixel's three codes in one
                lookup of the next 20 stream bits (LT); a run code and the next count code in one 16-bit lookup (UU)
  encode_track  equal-neighbour spans by big-integer XOR / OR and a regex over the zero bytes; a literal pixel in a few
                table lookups (BASE, HC, RESD, TR, A2); 'copy the pixel above' decided per row at once from the row above's
                reconstruction (big-integer lanes); it keeps the reconstruction, which is the decoder's rows (the
                decode-back check of rebuild_copy reads them instead of decoding the stream again)
  resample(2)   output = (gy (gx s[j0][o] + fx s[j0][o+3]) + fy (gx s[j0+1][o] + fx s[j0+1][o+3]) + 32768) >> 16 is an
                exact integer sum, so the vertical pass comes first: per output row gy row_j0 + fy row_j0+1 as one big
                integer of 16-bit lanes (<= 65280, no carry), in bands of rows; then per output column and channel the
                horizontal pass on a column of those (24-bit lanes, < 2^24); the result is each lane's top byte
  thumb         the taps once; vertical taps on 32-bit lanes with an exact bias, horizontal taps on transposed 64-bit
                lanes; the last step (round, clamp, & 0xfe) per value
  checks        rebuild_copy's 'within 2 of the target' on 16-bit lanes (bytes.translate); on a failure the reference
                computes the worst value for the same message"""
import re, struct, sys
import cgcrop
import galcg
from builder import BuildError

__all__ = ['decode', 'encode_track', 'resample', 'resample2', 'thumb', 'rebuild', 'rebuild_copy', 'rebuild_thumb',
           'shrink', 'within']

_fb = int.from_bytes
_LE = sys.byteorder == 'little'

# ---------------------------------------------------------------- code tables (built on first use)
LT_BITS = 20
_T = {}


def _lit_table(bits):
    """t[next `bits` stream bits] = (v1, v2, v3, L1 + L2 + L3) when a literal pixel's three signed codes fit in `bits`,
    else None (the decoder then reads them one by one from cgcrop.STAB)."""
    t = [None] * (1 << bits)
    codes = [(v, c, L) for v, (c, L) in cgcrop.SCODE.items()]
    for v1, c1, L1 in codes:
        if L1 >= bits: continue
        for v2, c2, L2 in codes:
            if L1 + L2 >= bits: continue
            for v3, c3, L3 in codes:
                L = L1 + L2 + L3
                if L > bits: continue
                c = c1 | (c2 << L1) | (c3 << (L1 + L2))
                t[c::1 << L] = [(v1, v2, v3, L)] * (1 << (bits - L))
    return t


def _uu_table():
    """t[next 16 stream bits] = (run n, next count n, L) when a run code and the following count code both fit in 16
    bits (unsigned codes v < 255: the ones cgcrop.UTAB holds), else None."""
    t = [None] * 65536
    codes = [(v + 1, c, L) for v, (c, L) in ((v, cgcrop._unsigned_code(v)) for v in range(4096)) if L < 16]
    for n1, c1, L1 in codes:
        for n2, c2, L2 in codes:
            L = L1 + L2
            if L > 16: continue
            t[(c1 | (c2 << L1))::1 << L] = [(n1, n2, L)] * (1 << (16 - L))
    return t


def _arith_tables():
    A2 = [0] * 65536                 # A2[(x << 8) | (d & 255)] = clamp(x + 2 d), d a signed byte
    for x in range(256):
        for d in range(-128, 128):
            v = x + 2 * d; A2[(x << 8) | (d & 255)] = 0 if v < 0 else 255 if v > 255 else v
    BASE = [0] * 65536               # BASE[(g << 8) | (dg & 255)] = trunc((clamp(g + 2 dg) - g) / 2)
    for g in range(256):
        for dg in range(-128, 128):
            t = g + dg * 2; t = (0 if t < 0 else 255 if t > 255 else t) - g
            BASE[(g << 8) | (dg & 255)] = t // 2 if t >= 0 else -((-t) // 2)
    HALF = [0] * (256 * 513)         # HALF[G * 513 - c + 255] = cgcrop._half(G - c, G), c in 0..255
    for G in range(256):
        for c in range(256):
            HALF[G * 513 - c + 255] = cgcrop._half(G - c, G)
    return A2, BASE, HALF


def _encode_tables(A2, HALF, SC):
    """The encoder's literal pixel in three lookups (cgcrop.encode's arithmetic with rtol 0, every clamp included):
      HC[G * 513 - g + 255] = (clamp(_half(G - g, G), -128, 127) & 255) << 8       the green step wanted
      RESD[want8 | (base & 255)] = (dg & 255, code, L) for res = clamp(want - base, -127, 127), dg = clamp(res + base,
                                   -128, 127), code = SCODE[res]
      TR[(R << 8) | r] = (clamp(r + 2 s), code, L) for s = clamp(_half(R - r, R), -127, 127), code = SCODE[s]
                                   (the red / blue residual after the green step)"""
    HC = [((-128 if v < -128 else 127 if v > 127 else v) & 255) << 8 for v in HALF]
    RESD = [None] * 65536
    for want in range(-128, 128):
        for base in range(-128, 128):
            res = want - base
            res = -127 if res < -127 else 127 if res > 127 else res
            dg = res + base
            dg = -128 if dg < -128 else 127 if dg > 127 else dg
            c, L = SC[res + 127]
            RESD[((want & 255) << 8) | (base & 255)] = (dg & 255, c, L)
    TR = [None] * 65536
    for R in range(256):
        for r in range(256):
            v = HALF[R * 513 - r + 255]
            v = -127 if v < -127 else 127 if v > 127 else v
            c, L = SC[v + 127]
            TR[(R << 8) | r] = (A2[(r << 8) | (v & 255)], c, L)
    return HC, RESD, TR


def tables():
    if not _T:
        _T['LT'] = _lit_table(LT_BITS)
        _T['UU'] = _uu_table()
        _T['A2'], _T['BASE'], _T['HALF'] = _arith_tables()
        _T['SC'] = [cgcrop.SCODE[v] for v in range(-127, 128)]
        _T['HC'], _T['RESD'], _T['TR'] = _encode_tables(_T['A2'], _T['HALF'], _T['SC'])
        _T['near'] = {}
    return _T


def _near_tabs(tol):
    """(LO, HI): bytes.translate tables of a lane a - b + 256 + tol in 16 bits: 1 when |a - b| <= tol, by byte."""
    T = tables()['near']
    if tol not in T:
        lo = bytearray(256); hi = bytearray(256)
        for v in range(0, 2 * tol + 1): lo[v] = 1
        hi[1] = 1
        T[tol] = (bytes(lo), bytes(hi))
    return T[tol]


# ---------------------------------------------------------------- Opaque1 decode
def decode(body, rows=None):
    """cgcrop.decode(body, rows): (W, H, list of bytearray rows, 3 bytes per pixel in the coder's channel order)."""
    T = tables()
    LT = T['LT']; LTM = (1 << LT_BITS) - 1; UU = T['UU']
    hd = cgcrop.header(body)
    if hd['flag'] & 0xff != 2 or not hd['depth'] & 4: raise ValueError('Cr6Ti: only Opaque1 is handled')
    W, H = hd['w'], hd['h']
    n_rows = H if rows is None else min(H, rows)
    ip = hd['data_start']; end = hd['data_start'] + hd['data_size']
    data = bytes(body[ip:end]) + b'\x00' * 16; ip = 0
    fb = _fb
    buf = 0; nb = 0
    S = cgcrop.STAB; U = cgcrop.UTAB
    prev = bytes(3 * W)
    out = []
    W3 = 3 * W
    for y in range(n_rows):
        row = bytearray(prev)
        o = 0; r = g = b = 0; dg = 0
        n = 0                                     # 0: read the count code
        while o < W3:
            if not n:
                if nb < 64: buf |= fb(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                e = U[buf & 0xFFFF]
                if e is None:
                    if buf & 1 == 0: n = 1; buf >>= 1; nb -= 1
                    else:
                        buf >>= 1; nb -= 1; t = 1
                        while True:
                            if nb < 8: buf |= fb(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                            t = (t << 1) | (buf & 1); c = (buf >> 1) & 1; buf >>= 2; nb -= 2
                            if c == 0: break
                        n = t
                else:
                    n = e[0] + 1; buf >>= e[1]; nb -= e[1]
            stop = o + 3 * n
            if stop > W3: stop = W3
            while o < stop:
                if nb < 64: buf |= fb(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                if buf & 1:
                    buf >>= 1; nb -= 1
                    r = prev[o]; g = prev[o + 1]; b = prev[o + 2]; dg = 0
                else:
                    buf >>= 1
                    e = LT[buf & LTM]
                    if e is not None:
                        v, v2, v3, L = e; buf >>= L; nb -= 1 + L
                    else:
                        v, L = S[buf & 0xFFFF]; buf >>= L
                        v2, L2 = S[buf & 0xFFFF]; buf >>= L2
                        v3, L3 = S[buf & 0xFFFF]; buf >>= L3
                        nb -= 1 + L + L2 + L3
                    t = g + dg * 2; t = (0 if t < 0 else 255 if t > 255 else t) - g
                    dg = v + (t // 2 if t >= 0 else -((-t) // 2))
                    if dg < -128: dg = -128
                    elif dg > 127: dg = 127
                    d2 = dg * 2
                    r += d2; g += d2; b += d2
                    r = 0 if r < 0 else 255 if r > 255 else r
                    g = 0 if g < 0 else 255 if g > 255 else g
                    b = 0 if b < 0 else 255 if b > 255 else b
                    r += v2 * 2; r = 0 if r < 0 else 255 if r > 255 else r
                    b += v3 * 2; b = 0 if b < 0 else 255 if b > 255 else b
                    row[o] = r; row[o + 1] = g; row[o + 2] = b
                o += 3
            n = 0
            if o < W3:
                if nb < 32: buf |= fb(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                e = UU[buf & 0xFFFF]
                if e is not None and o + 3 * e[0] < W3:
                    k, n, L = e; buf >>= L; nb -= L       # the run, then the next group's count (already read)
                else:
                    e = U[buf & 0xFFFF]
                    if e is None:
                        buf >>= 1; nb -= 1; t = 1
                        while True:
                            if nb < 8: buf |= fb(data[ip:ip + 8], 'little') << nb; ip += 8; nb += 64
                            t = (t << 1) | (buf & 1); c = (buf >> 1) & 1; buf >>= 2; nb -= 2
                            if c == 0: break
                        k = t
                    else:
                        k = e[0] + 1; buf >>= e[1]; nb -= e[1]
                s2 = o + 3 * k
                if s2 > W3: s2 = W3; k = (W3 - o) // 3
                row[o:s2] = row[o - 3:o] * k
                o = s2; dg = 0
        out.append(row); prev = row
    return W, H, out


# ---------------------------------------------------------------- Opaque1 encode, keeping the decoder's rows
def _eq_spans(T, W):
    """Maximal stretches [s, e) of j with pixel j == pixel j + 1 (0 <= j < W - 1)."""
    if W < 2: return []
    fb = _fb
    d = (fb(T[:3 * W - 3], 'little') ^ fb(T[3:3 * W], 'little')).to_bytes(3 * W - 3, 'little')
    z = (fb(d[0::3], 'little') | fb(d[1::3], 'little') | fb(d[2::3], 'little')).to_bytes(W - 1, 'little')
    return [m.span() for m in re.finditer(b'\x00+', z)]


def _near_row(prev, T, W, tol):
    """bytes of W: 1 where every channel of T is within tol of the row above's reconstruction prev, else 0."""
    n = 3 * W
    a = bytearray(2 * n); a[0::2] = prev; a[1::2] = b'\x01' * n          # prev + 256
    bb = bytearray(2 * n); bb[0::2] = T[:n]
    one = _fb(bytes((tol, 0)) * n, 'little')                             # + tol in every lane
    z = (_fb(a, 'little') + one - _fb(bb, 'little')).to_bytes(2 * n, 'little')   # lane = prev - T + 256 + tol
    lo, hi = _near_tabs(tol)
    ok = _fb(z[0::2].translate(lo), 'little') & _fb(z[1::2].translate(hi), 'little')
    okb = ok.to_bytes(n, 'little')
    return (_fb(okb[0::3], 'little') & _fb(okb[1::3], 'little') & _fb(okb[2::3], 'little')).to_bytes(W, 'little')


def encode_track(W, H, rows, tol=2):
    """cgcrop.encode(W, H, rows, tol, 0) -> (the same bytes, the rows its decoder reads back from them): the encoder's
    own pr / pg / pb per row as bytearray rows (a copy pixel leaves them, a literal or run pixel writes them, as
    cgcrop.encode updates pr / pg / pb; the decoder keeps the same values, cgcrop.decode). The green step's dg is kept
    as its byte dd = dg & 255 (BASE and A2 take it so)."""
    if not 0 <= tol <= 127: raise ValueError('encode_track: tol out of range')
    Tb = tables()
    A2 = Tb['A2']; BASE = Tb['BASE']; HC = Tb['HC']; RESD = Tb['RESD']; TR = Tb['TR']
    UC = [cgcrop._unsigned_code(v) for v in range(W + 1)]
    out = bytearray(); acc = 0; na = 0
    prev = bytes(3 * W); recs = []
    for y in range(H):
        T = rows[y]
        rec = bytearray(prev)
        near = _near_row(prev, T, W, tol) if y else bytes(W)
        spans = _eq_spans(T, W)
        spans.append((W - 1, W - 1))               # the last group: literal pixels up to W - 1, no run
        x = 0; r = g = b = 0; dd = 0
        for s, e in spans:
            if x >= W: break
            j = s
            c, L = UC[j - x]; acc |= c << na; na += L
            o = 3 * x
            for xx in range(x, j + 1):
                if near[xx]:                       # copy the pixel above (never in row 0)
                    acc |= 1 << na; na += 1
                    r = rec[o]; g = rec[o + 1]; b = rec[o + 2]; dd = 0
                else:                              # flag 0, green step, red / blue residuals
                    dd, c1, L1 = RESD[HC[T[o + 1] * 513 - g + 255] | (BASE[(g << 8) | dd] & 255)]
                    g = A2[(g << 8) | dd]
                    r, c2, L2 = TR[(T[o] << 8) | A2[(r << 8) | dd]]
                    b, c3, L3 = TR[(T[o + 2] << 8) | A2[(b << 8) | dd]]
                    acc |= (c1 | (c2 << L1) | (c3 << (L1 + L2))) << (na + 1); na += 1 + L1 + L2 + L3
                    rec[o] = r; rec[o + 1] = g; rec[o + 2] = b
                if na >= 64:
                    out += (acc & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'); acc >>= 64; na -= 64
                o += 3
            x = j + 1
            run = e - s
            if run > 0 and x < W:
                c, L = UC[run - 1]; acc |= c << na; na += L
                rec[3 * x:3 * (x + run)] = bytes((r, g, b)) * run
                x += run; dd = 0
            if na >= 64:
                out += (acc & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'); acc >>= 64; na -= 64
        recs.append(rec); prev = rec
    while na > 0:
        out.append(acc & 0xFF); acc >>= 8; na -= 8
    return bytes(out), recs


# ---------------------------------------------------------------- resampling
BAND = 192          # output rows per band of resample2's vertical buffer (bounds its memory)


def resample2(rows, W, H, kx, ky, x0, y0, ow, oh):
    """galcg.resample2(rows, W, H, kx, ky, x0, y0, ow, oh): oh bytearrays of 3 * ow."""
    cols = []
    for u in range(ow):
        sx = x0 + (u + 0.5) / kx - 0.5
        i0 = int(sx // 1); f = sx - i0
        if i0 < 0: i0, f = 0, 0.0
        if i0 >= W - 1: i0, f = W - 2, 1.0
        cols.append((i0, int(f * 256 + 0.5)))
    rws = []
    for v in range(oh):
        sy = y0 + (v + 0.5) / ky - 0.5
        j0 = int(sy // 1); f = sy - j0
        if j0 < 0: j0, f = 0, 0.0
        if j0 >= H - 1: j0, f = H - 2, 1.0
        rws.append((j0, int(f * 256 + 0.5)))
    if W < 2 or H < 2 or not ow or not oh:                  # (degenerate sizes: the reference's own arithmetic)
        return galcg.resample2(rows, W, H, kx, ky, x0, y0, ow, oh)
    out = bytearray(3 * ow * oh)
    c_lo = min(i for i, _ in cols); c_hi = max(i for i, _ in cols) + 2          # source columns read
    n = 3 * (c_hi - c_lo)                       # source values per row in the window
    fb = _fb
    wide = {}

    def lanes16(j):                             # source row j's window as a big integer of 16-bit lanes
        z = wide.get(j)
        if z is None:
            bb = bytearray(2 * n); bb[0::2] = rows[j][3 * c_lo:3 * c_hi]
            z = wide[j] = fb(bb, 'little')
            if len(wide) > 8: wide.pop(next(iter(wide)))
        return z
    step = 2 * n
    O3 = 3 * ow
    for v0 in range(0, oh, BAND):
        v1 = min(oh, v0 + BAND); m = v1 - v0
        vb = bytearray(step * m)
        for v in range(v0, v1):
            j0, fy = rws[v]
            z = lanes16(j0) * (256 - fy) + lanes16(j0 + 1) * fy if fy else lanes16(j0) * 256
            vb[step * (v - v0):step * (v - v0 + 1)] = z.to_bytes(step, 'little')
        K = fb(b'\x00\x80\x00' * m, 'little')    # 32768 in every 24-bit lane
        colcache = {}

        def col24(q):
            z = colcache.get(q)
            if z is None:
                bb = bytearray(3 * m); bb[0::3] = vb[2 * q::step]; bb[1::3] = vb[2 * q + 1::step]
                z = colcache[q] = fb(bb, 'little')
                if len(colcache) > 24: colcache.pop(next(iter(colcache)))
            return z
        L = 3 * m; base = O3 * v0; end = O3 * v1
        for u, (i0, fx) in enumerate(cols):
            q0 = 3 * (i0 - c_lo)
            if fx:
                gx = 256 - fx
                for c in range(3):
                    z = col24(q0 + c) * gx + col24(q0 + 3 + c) * fx + K
                    out[base + 3 * u + c:end:O3] = z.to_bytes(L, 'little')[2::3]
            else:
                for c in range(3):
                    z = col24(q0 + c) * 256 + K
                    out[base + 3 * u + c:end:O3] = z.to_bytes(L, 'little')[2::3]
        del vb, colcache
    return [out[O3 * v:O3 * (v + 1)] for v in range(oh)]


def resample(rows, W, H, k, x0, y0, ow, oh):
    """cgcrop.resample: resample2 with kx = ky = k (the same expressions, so the same bytes)."""
    return resample2(rows, W, H, k, k, x0, y0, ow, oh)


# ---------------------------------------------------------------- thumbnails: Lanczos3 on big-integer lanes
def thumb(rows, W, H, kx, ky, x0, y0, ow=210, oh=123, ty=None, tx=None):
    """galcg.thumb(rows, W, H, kx, ky, x0, y0, ow, oh); ty / tx = galcg.taps(ky, y0, oh, H) / taps(kx, x0, ow, W) when
    the caller has them already."""
    if ty is None: ty = galcg.taps(ky, y0, oh, H)
    if tx is None: tx = galcg.taps(kx, x0, ow, W)
    if max(t[-1][0] for t in ty) >= len(rows): raise BuildError('thumbnail: source rows missing')
    c0 = min(t[0][0] for t in tx); c1 = max(t[-1][0] for t in tx) + 1
    n = 3 * (c1 - c0)
    fb = _fb
    ONES = fb(b'\x01\x00\x00\x00' * n, 'little')
    wide = {}

    def lanes(j):
        z = wide.get(j)
        if z is None:
            bb = bytearray(4 * n); bb[0::4] = rows[j][3 * c0:3 * c1]
            z = wide[j] = fb(bb, 'little')
        return z
    # vertical pass per output row: Z_v = neg_v + sum_j wy_j * row_j in 32-bit lanes; neg_v = 255 * (sum of the
    # negative weights' sizes) keeps every lane >= 0 and the largest lane is 255 * sum |wy| < 2^32 (SY, checked).
    # A big integer sum is exact whatever the signs of its terms; its lanes read back exactly when every final lane
    # lies in [0, 2^lane bits).
    SY = max(sum(abs(w) for _, w in t) for t in ty); SX = max(sum(abs(w) for _, w in t) for t in tx)
    if 255 * SY >= 1 << 32 or 255 * SX * SY >= 1 << 46:
        return galcg.thumb(rows, W, H, kx, ky, x0, y0, ow, oh)      # (taps far from 1 << WBITS: never in practice)
    AB = bytearray(4 * n * oh)
    negs = []
    for v in range(oh):
        neg = -sum(w for _, w in ty[v] if w < 0) * 255
        z = neg * ONES
        for j, w in ty[v]:
            z += w * lanes(j)
        AB[4 * n * v:4 * n * (v + 1)] = z.to_bytes(4 * n, 'little')
        negs.append(neg)
    wide.clear()
    sh = 2 * galcg.WBITS; half = 1 << (sh - 1); B47 = 1 << 47
    # horizontal pass per output column and channel on 64-bit lanes (one per output row): sum_i wx_i * col_i + BIAS,
    # BIAS = 2^47 - neg_v * 2^WBITS per lane (sum wx = 2^WBITS, galcg.taps), so lane = value + 2^47 with |value| <=
    # 255 * SX * SY < 2^46 (checked): every lane in (2^46, 3 * 2^46)
    BIAS = fb(b''.join((B47 - (neg << galcg.WBITS)).to_bytes(8, 'little') for neg in negs), 'little')
    step = 4 * n
    cols = {}

    def col(q):
        z = cols.get(q)
        if z is None:
            cb = bytearray(8 * oh)
            for k in range(4): cb[k::8] = AB[4 * q + k::step]
            z = cols[q] = fb(cb, 'little')
            if len(cols) > 400: cols.pop(next(iter(cols)))
        return z
    out = [bytearray(3 * ow) for _ in range(oh)]
    for u, t in enumerate(tx):
        for c in range(3):
            z = BIAS
            for i, w in t:
                z += w * col(3 * (i - c0) + c)
            zb = z.to_bytes(8 * oh, 'little')
            vals = memoryview(zb).cast('Q').tolist() if _LE else [_fb(zb[8 * v:8 * v + 8], 'little') for v in range(oh)]
            q = 3 * u + c
            for v in range(oh):
                val = ((vals[v] - B47) + half) >> sh
                out[v][q] = (0 if val < 0 else 255 if val > 255 else val) & 0xfe
    return out


# ---------------------------------------------------------------- checks
def within(tgt, back, tol=2):
    """True when every value of the rows back is within tol of tgt's (same lengths)."""
    lo, hi = _near_tabs(tol)
    fb = _fb
    for t, b in zip(tgt, back):
        if t == b: continue
        n = len(t)
        if len(b) != n: return False
        a = bytearray(2 * n); a[0::2] = t; a[1::2] = b'\x01' * n
        bb = bytearray(2 * n); bb[0::2] = b
        z = (fb(a, 'little') + fb(bytes((tol, 0)) * n, 'little') - fb(bb, 'little')).to_bytes(2 * n, 'little')
        if z[0::2].translate(lo) != b'\x01' * n or z[1::2].translate(hi) != b'\x01' * n: return False
    return True


def _worst(tgt, back):
    """galcg.rebuild_copy's measure (for its error message)."""
    import operator
    worst = 0
    for t, b in zip(tgt, back):
        if t != b: worst = max(worst, max(map(abs, map(operator.sub, t, b))))
    return worst


# ---------------------------------------------------------------- the re-encodes (references' checks and messages)
def rebuild(pm_body, src, crop):
    """cgcrop.rebuild(pm_body, src, crop) -> (new body, target rows)."""
    hp = cgcrop.header(pm_body)
    if hp['flag'] & 0xff != 2 or not hp['depth'] & 4 or hp['w'] != hp['w0'] or hp['h'] != hp['h0']:
        raise ValueError('PM picture is not a plain Opaque1 picture')
    W, H, rows = src
    k, x0, y0 = crop
    if cgcrop.rows_needed(H, k, y0, hp['h']) > len(rows): raise ValueError('source rows missing')
    tgt = resample(rows, W, len(rows), k, x0, y0, hp['w'], hp['h'])
    data = encode_track(hp['w'], hp['h'], tgt)[0]
    p = hp['size_pos']
    body = (pm_body[:p] + struct.pack('<I', len(data)) + pm_body[p + 4:p + 12] + data + bytes(len(data) & 1)
            + pm_body[-2:])
    return body, tgt


def rebuild_copy(pm_body, src, win, what='copy'):
    """galcg.rebuild_copy(pm_body, src, win, what) -> (new body, target rows, the rows the decoder reads back from the
    new body: the encoder's own reconstruction, checked within 2 of the target as the reference checks its decode)."""
    hp = galcg.check_header(pm_body, galcg.COPY_FLAG, what)
    W, H, rows = src
    kx, ky, x0, y0 = win
    if galcg.rows_needed2(H, ky, y0, hp['h']) > len(rows): raise BuildError('%s: source rows missing' % what)
    tgt = resample2(rows, W, len(rows), kx, ky, x0, y0, hp['w'], hp['h'])
    data, back = encode_track(hp['w'], hp['h'], tgt)
    body = galcg._relayout(pm_body, hp, data, what)
    h2 = cgcrop.header(body)
    if (h2['w'], h2['h'], len(back)) != (hp['w'], hp['h'], hp['h']): raise BuildError('%s: decodes to another size' % what)
    if not within(tgt, back, 2):
        raise BuildError('%s: decodes up to %d away from its target (at most 2)' % (what, _worst(tgt, back)))
    return body, tgt, back


def rebuild_thumb(pm_body, copy_body, win, what='thumbnail', copy_rows=None):
    """galcg.rebuild_thumb(pm_body, copy_body, win, what) -> the new body. copy_rows: copy_body's decoded rows when the
    caller has them (rebuild_copy's third result), else copy_body is decoded."""
    ht = galcg.check_header(pm_body, galcg.THUMB_FLAG, what)
    hc = cgcrop.header(copy_body)
    kx, ky, x0, y0 = win
    ty = galcg.taps(ky, y0, ht['h'], hc['h'])
    need = max(t[-1][0] for t in ty) + 1
    if copy_rows is None:
        W, H, rows = decode(copy_body, need)
    else:
        W, H = hc['w'], hc['h']
        if hc['flag'] & 0xff != 2 or not hc['depth'] & 4: raise ValueError('Cr6Ti: only Opaque1 is handled')
        rows = copy_rows[:min(H, need)]
    trows = thumb(rows, W, H, kx, ky, x0, y0, ht['w'], ht['h'], ty=ty)
    data = galcg.tencode(ht['w'], ht['h'], trows)
    body = galcg._relayout(pm_body, ht, data, what)
    Wd, Hd, px, end = galcg.tdecode(body)
    rgb = bytearray(3 * Wd * Hd); rgb[0::3] = px[0::4]; rgb[1::3] = px[1::4]; rgb[2::3] = px[2::4]
    if (Wd, Hd) != (ht['w'], ht['h']) or bytes(rgb) != b''.join(bytes(r) for r in trows):
        raise BuildError('%s: the drawer would not read back the target' % what)
    if px[3::4] != b'\x80' * (Wd * Hd): raise BuildError('%s: not opaque everywhere (alpha byte not 0x80)' % what)
    if end > ht['size_pos'] + 12 + len(data): raise BuildError('%s: the drawer reads past the stream' % what)
    return body


def shrink(body, limit, steps=((2, 2), (3, 3), (4, 4), (5, 5), (6, 6))):
    """cgcrop.shrink(body, limit, steps): the decode here, the encodes (rtol != 0) cgcrop's own."""
    hd = cgcrop.header(body)
    W, H, rows = decode(body)
    p = hd['size_pos']; fixed = p + 12 + 2
    start = 0 if len(body) * 0.84 <= limit else min(2, len(steps) - 1)
    for tol, rtol in steps[start:]:
        data = encode_track(W, H, rows, tol)[0] if rtol == 0 else cgcrop.encode(W, H, rows, tol, rtol)
        if fixed + len(data) + (len(data) & 1) <= limit:
            return (body[:p] + struct.pack('<I', len(data)) + body[p + 4:p + 12] + data + bytes(len(data) & 1)
                    + body[-2:]), (tol, rtol)
    return None, None
