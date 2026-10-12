"""oor (COptimizedObs) page parser, ported from deoptimizeobs (oor_framing.erl). MSb-first bit packing.
read_stream(data, start) -> list of pages (ver, flags, granulepos, pktlens, body_off) or raises."""
import struct


class Bits:
    def __init__(self, d, byte_off=0):
        self.d = d; self.pos = byte_off * 8

    def get(self, n):
        v = 0
        for _ in range(n):
            byte = self.d[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def align(self):
        pad = (-self.pos) % 8
        v = self.get(pad) if pad else 0
        return pad, v


def read_page(d, off):
    b = Bits(d, off)
    ver = b.get(2); flags = b.get(4)
    gp = None
    if ver != 0:
        b.get(2); gp = b.get(64); b.get(6)
    bos = (flags >> 1) & 1
    if bos:
        # info header: size inferred
        save = b.pos
        b.get(7); ratesel = b.get(2); b.pos = save
        size = 2 + (1 if ratesel >= 3 else 0) + (10 if ver > 0 else 0)
        pktlens = [size]
    else:
        vlen = b.get(4); b.get(1); npkt = b.get(8); sel = b.get(2)
        bsz_bits = {0: 0, 1: 8, 2: 11}.get(sel)
        if bsz_bits is None: raise ValueError('bad base size selector')
        base = b.get(bsz_bits) if bsz_bits else 0
        pktlens = [base + (b.get(vlen) if vlen else 0) for _ in range(npkt)]
    pad, v = b.align()
    if v != 0 and not bos: raise ValueError('nonzero pad')
    body = b.pos >> 3
    return dict(ver=ver, flags=flags, gp=gp, pktlens=pktlens, body=body, next=body + sum(pktlens))


def read_stream(d, start=0, limit=100000):
    pages = []; off = start
    while off < len(d) and len(pages) < limit:
        p = read_page(d, off); pages.append(p)
        if p['next'] > len(d): raise ValueError('page overruns data at %d' % off)
        off = p['next']
        if p['flags'] & 1: break
    return pages, off
