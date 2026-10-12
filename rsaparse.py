"""Parser for decrypted rUGP CRsa instruction heaps (AF 2007 = heap version 0x11).

Based on alterdec (rsa.cpp / common.cpp, chinesize) and omClasses.txt signatures.
Self-check: must consume exactly `count` instructions.
"""
import struct, sys, os, ast

HERE = os.path.dirname(os.path.abspath(__file__))
# OM argument signatures (pure data dict, copied from chinesize/Rugp/tools/omClasses.txt; parsed, never executed)
OMSIG = ast.literal_eval(open(os.path.join(HERE, 'omsig_data.txt'), encoding='utf-8').read())

KO, KS = 0xA2FB6AD1, 0xE7B5D9F8
M = 0xFFFFFFFF


def dec_off(v):
    return 3 + 2 * ((v - KO) & M)


def dec_size(v):
    a = (v - KS) & M; c = a >> 13; d = c & 0xFFF; a2 = (a - d) & M
    return (((a2 << 19) & M) | c) - 3


def decode_class_name(buf):
    bits = len(buf) * 8
    bit = lambda s: (buf[s >> 3] >> (s & 7)) & 1
    s = 0; name = ''
    if not bit(s): name += 'C'
    s += 1
    while s < bits:
        if not bit(s):
            s += 1
            if s + 3 >= bits: break
            t = sum(bit(s + i) << i for i in range(4)); s += 4
            name += 'eaitrosducmnSglR'[t]
        else:
            s += 1
            if s >= bits: break
            if not bit(s):
                s += 1
                if s + 3 >= bits: break
                t = sum(bit(s + i) << i for i in range(4)); s += 4
                if t:
                    name += '_COFLfBMxphyAVbI'[t]
                else:
                    if s + 7 >= bits: break
                    t = sum(bit(s + i) << i for i in range(8)); s += 8
                    name += chr(t)
            else:
                s += 1
                if s + 4 >= bits: break
                t = sum(bit(s + i) << i for i in range(5)); s += 5
                if t < 31: name += 'EHTDPWXkqvNjwGz02U_K15JQZ467839'[t]
    return name


class ParseError(Exception):
    pass


class EntryLog(list):
    """The MFC load array. Every append is logged as ('ent', pos, index, item) in heap.ev."""

    def __init__(self, heap, init):
        super().__init__(init); self.heap = heap

    def append(self, item):
        self.heap.ev.append(('ent', self.heap.p, len(self), item))
        super().append(item)

    def extend(self, items):
        for it in items: self.append(it)


class Heap:
    def __init__(self, data, variant=2, trace=False):
        self.d = data; self.p = 0; self.variant = variant; self.trace = trace
        self.ev = []        # token events for the rewriter
        self.cache = EntryLog(self, [None, None])
        self.readclasslist = False
        self.refs = []      # (pos_of_encoded_offset, class, offset, size)
        self.strings = []   # (pos, text)
        self.resolved = []  # top-level references in order, resolved to (cls, off, size)
        self.objinfo = {}   # load-array index -> (cls, off, size) for explicit refs
        self.pad_end = 0

    # primitives
    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def skip(self, n):
        self.p += n
        if self.p > len(self.d): raise ParseError('eof')

    def string(self):
        """MFC CString: byte len, 0xff -> word len, 0xfffe -> UTF-16 marker + len, 0xffff -> dword len."""
        n = self.u8()
        if n == 0xff:
            n = self.u16()
            if n == 0xfffe:
                n = self.u8()
                if n == 0xff:
                    n = self.u16()
                    if n == 0xffff: n = self.u32()
                s = self.d[self.p:self.p + 2 * n]; self.p += 2 * n
                return s.decode('utf-16le', 'replace').encode('cp932', 'replace')
            if n == 0xffff: n = self.u32()
        s = self.d[self.p:self.p + n]; self.p += n
        return s

    # classes
    def _tag_event(self, p0, w, kind_def):
        if w == 0xffff:
            return
        if w & 0x8000:
            self.ev.append(('cidx', p0, w & 0x7fff))
        elif w:
            self.ev.append(('oidx', p0, w))
        else:
            self.ev.append(('null', p0))

    def read_class(self):
        p0 = self.p
        w = self.u16()
        if w == 0x7fff: raise ParseError('7fff class idx @%x' % self.p)
        if w == 0xffff:
            schema = self.u16()
            n = self.u8()
            name = decode_class_name(self.d[self.p:self.p + n]); self.p += n
            cls = (name, schema)
            self.ev.append(('cdef', p0, self.p, len(self.cache), cls))
            self.cache.append(cls)
            return cls
        self._tag_event(p0, w, 'cdef')
        if w & 0x8000:
            n = w & 0x7fff
            if n >= len(self.cache): raise ParseError('class idx %d >= %d @%x' % (n, len(self.cache), self.p))
            return self.cache[n]
        return None

    def read_raw_class(self):
        p0 = self.p
        w = self.u16()
        if w == 0x7fff: raise ParseError('7fff raw @%x' % self.p)
        if w == 0xffff:
            schema = self.u8()
            name = self.string().decode('cp932', 'replace')
            cls = (name, schema)
            self.ev.append(('rdef', p0, self.p, len(self.cache), cls))
            self.cache.append(cls)
            return cls
        self._tag_event(p0, w, 'rdef')
        if w & 0x8000:
            n = w & 0x7fff
            if n >= len(self.cache): raise ParseError('raw idx %d >= %d @%x' % (n, len(self.cache), self.p))
            return self.cache[n]
        return None

    def read_class_list(self):
        """An object reference (or inline object)."""
        self.ev.append(('rcl', self.p))
        if not self.readclasslist:
            p0 = self.p
            n = self.u8()
            self.ev.append(('pad', p0, len(self.cache), n))
            self.cache.extend([None] * n)
            self.pad_end = len(self.cache)
            self.readclasslist = True
        start = self.p
        depth = getattr(self, 'depth', 0)
        cls = self.read_class()
        if cls is None:
            w = struct.unpack_from('<H', self.d, start)[0]
            if depth == 0:
                self.resolved.append(self.objinfo.get(w, ('pad' if w < self.pad_end else '?', w)) if w else ('null',))
            return None
        flag = self.u16()
        if flag & 0x40:
            if depth == 0: self.resolved.append(('inline', cls))
            self.cache.append(cls)
            self.inline_object(cls)
            return ('inline', cls)
        pos = self.p
        off = dec_off(self.u32()); size = dec_size(self.u32())
        self.refs.append((pos, cls, off, size))
        if depth == 0: self.resolved.append((cls, off, size))
        self.depth = depth + 1
        self.read_class_list()
        self.depth = depth
        if (flag & 7) == 1:
            self.u32()
        elif flag & 0x8000:
            self.u8()
        else:
            self.u16()
        self.ev.append(('ref', start, self.p, len(self.cache), pos, cls, off, size))
        self.objinfo[len(self.cache)] = (cls, off, size)
        self.cache.append(cls)
        return ('ref', cls, off, size)

    def inline_object(self, cls):
        name = cls[0]
        fn = {'CPostureMoment': self.io_posture, 'CDcAgesModelQsT': self.io_dcages,
              'CMoveAcsOngen': self.io_moveacs, 'CAcsPos': self.io_acspos,
              'CMN_Time_2G': lambda c: self.u32(),
              'CMN_Time_Bezier': lambda c: self.skip(0x18 * self.u16())}.get(name)
        if fn is None and name in self.FADES:
            fn = getattr(self, 'fade_' + self.FADES[name])
        if fn is None:
            raise ParseError('inline object %s @%x' % (cls, self.p))
        fn(cls)

    # fade effects (formats from alterdec fade.cpp)
    FADES = {
        'CFadeNormal': 'normal', 'CFadeSdtRatio': 'normal', 'CFadeRSideCarten': 'normal', 'CFadeMozaik': 'normal',
        'CFadeMulHorz': 'normal', 'CFadeInvert': 'normal', 'CFadeShock': 'normal',
        'CFadeMergeWhite': 'mergewhite', 'CFadeMergeColor': 'mergewhite', 'CFadeMergeBlack': 'mergeblack',
        'CFadeXsRatio': 'xsratio', 'CFadeXsMergeBlack': 'xsratio', 'CFadeOverStretchAnti': 'overstretch',
        'CFadeXsRasterNoize': 'xsrasternoize', 'CFadeCarten': 'carten', 'CFadeQubeStretchAnti': 'qube',
        'CFadeStretchAnti': 'stretch', 'CFadeXsSqrRaster_HRasterV_VRasterH': 'sqr', 'CFadeXsHRasterHOffset': 'sqr',
        'CFadeXsSrcRotate': 'srcrotate', 'CFadeXsCircleRaster': 'circle', 'CFadeTelevisionWipe': 'tv',
        'CFadeXsOverStretchAnti': 'xsover', 'CFadeHSV': 'hsv',
    }

    def fade_normal(self, cls=None):
        n = self.u16(); self.u16()
        for _ in range(3): self.read_class_list()
        self.skip(24 + 4 * n)

    def fade_mergewhite(self, cls=None):
        self.fade_normal(); self.u32()

    def fade_mergeblack(self, cls=None):
        self.u16(); self.u16()
        for _ in range(3): self.read_class_list()
        self.skip(24 + 0x44)

    def fade_carten(self, cls=None):
        self.skip(6); self.fade_normal()

    def fade_stretch(self, cls=None):
        self.fade_normal(); self.skip(17)

    def fade_overstretch(self, cls=None):
        self.fade_stretch(); self.skip(8)

    def fade_qube(self, cls=None):
        self.fade_stretch(); self.skip(27)

    def fade_xsratio(self, cls=None):
        n = self.u16(); self.u16()
        for _ in range(3): self.read_class_list()
        self.skip(24 + 4 * n + 6)

    def fade_xsrasternoize(self, cls=None):
        self.fade_xsratio(); self.skip(8 + 3 + 6)

    def fade_sqr(self, cls=None):
        self.fade_xsratio(); self.skip(11)

    def fade_circle(self, cls=None):
        self.fade_sqr(); self.u32()

    def fade_tv(self, cls=None):
        self.fade_normal(); self.u8()

    def fade_srcrotate(self, cls=None):
        self.fade_xsratio(); self.skip(18)

    def fade_xsover(self, cls=None):
        self.fade_xsratio(); self.skip(24)

    def fade_hsv(self, cls=None):
        self.fade_normal(); self.skip(26)

    def cstring(self):
        """MFC CString serialization (length prefix, optional unicode marker)."""
        n = self.u8()
        if n == 0xff:
            n = self.u16()
            if n == 0xfffe:
                n = self.u8()
                if n == 0xff: n = self.u16()
                self.skip(2 * n); return
            if n == 0xffff: n = self.u32()
        self.skip(n)

    def io_posture(self, cls):
        """Mirrors PM FUN_00484b00 read path, which handles the old internal versions."""
        schema = cls[1]
        self.u8(); v = 0
        if schema > 2:
            v = self.u8(); self.u8()
            if v > 10: self.u32()
        if v <= 8: self.read_class_list()
        if v < 7:
            self.read_class_list()
            if v > 5: self.read_class_list()
        for _ in range(3): self.read_class_list()
        self.skip(12)
        if v < 9:
            self.skip(4 if v < 3 else 8)
            if v < 4:
                if schema > 3 or v != 0: self.skip(24 + (12 if v > 1 else 0))
            else:
                if self.u8(): self.skip(0x48)
        self.u16(); self.u16()
        if v > 1: self.u16()
        if schema > 1: self.skip(12)
        if v > 4:
            self.cstring()
            if v == 8: self.u8()
            if v > 9: self.u32()

    def io_acspos(self, cls):
        """PM FUN_0040f4d0: 6 dwords, 2 words, dword if schema > 1."""
        self.skip(24 + 4)
        if cls[1] > 1: self.u32()

    def io_dcages(self, cls):
        n = self.u8(); self.u32()
        if n >= 1: self.skip(12)
        k = self.u32(); self.skip(k)
        k = self.u32(); self.skip(k)
        cnt = self.u16()
        for _ in range(cnt):
            self.read_class_list(); self.skip(20)
        self.read_class_list()
        if cls[1] > 1: self.skip(8)

    def read_archive_object(self):
        p0 = self.p
        w = self.u16()
        if w == 0xffff:
            schema = self.u16(); n = self.u16(); name = self.d[self.p:self.p + n].decode('cp932', 'replace'); self.p += n
            cls = (name, schema)
            self.ev.append(('adef', p0, self.p, len(self.cache), cls))
            self.cache.append(cls)
        elif w & 0x8000:
            self.ev.append(('cidx', p0, w & 0x7fff))
            cls = self.cache[w & 0x7fff]
        else:
            return False
        self.cache.append(cls)
        self.inline_object(cls)
        return True

    def io_moveacs(self, cls):
        self.skip(12)
        while True:
            b = self.u8()
            if b == 0x70: break
            b = self.u8(); self.u32()
            if b & 1: self.skip(12)
            else: self.skip(8)
            n = self.u16(); self.skip(12 * n)
            if b & 2: self.read_archive_object()
        self.skip(12 + 1 + 2)

    def sub1(self):
        d = self.u32()
        k = d & 3
        if k == 0:
            self.read_class_list()
        elif k == 1:
            self.strings.append((self.p, self.string()))
        elif k == 2:
            pass
        else:
            t1 = self.u32()
            if t1 == 0x137:
                self.u32()
            elif t1 != 0x138:
                raise ParseError('sub1 t1=%x @%x' % (t1, self.p))

    def sub1_om(self):
        d = self.u32()
        if d == 4:
            w = self.u16()
            if w == 0x1e57: self.read_class()
            elif w == 0x369e: self.read_raw_class()
            elif w in (0x2d6b, 0x2f1a):
                self.u16(); n = self.u16(); self.skip(n)
            else: raise ParseError('om sub1 w=%x @%x' % (w, self.p))
            self.skip(4)
            return
        k = d & 3
        if k == 0: self.read_class_list()
        elif k == 1: self.strings.append((self.p, self.string()))
        elif k == 2: pass
        else: raise ParseError('om sub1 d=%x @%x' % (d, self.p))

    # OM argument signature
    def om_args(self, name):
        key = name[2:] if name.startswith('&-') else name
        sig = OMSIG.get(key)
        if sig is None:
            raise ParseError('unknown OM %s @%x' % (key, self.p))
        if sig == 'None': return
        for t in sig.split():
            if t == 'd': self.u32()
            elif t == 'w': self.u16()
            elif t == 'b': self.u8()
            elif t == 'str': self.strings.append((self.p, self.string()))
            elif t == 'list': self.read_class_list()
            elif t == 'sub1': self.sub1_om()
            else: raise ParseError('sig type %s' % t)

    # instructions
    def vm_sound(self):
        """PM FUN_004c6790 (schema >= 7 path)."""
        self.u32(); self.u32(); self.read_class_list(); typ = self.u8()
        f = self.u8(); self.u16(); self.u16(); self.u16()
        if self.cur_schema >= 0x13 and typ in (2, 4):
            self.read_class_list()
        if f & 4:
            if f & 8: self.read_class_list()
            else:
                self.skip(8)
                if not f & 0x10: self.skip(6)

    def vm_flagop(self):
        self.u32(); self.u32(); self.sub1(); self.sub1(); self.read_class_list(); self.u16(); self.u8(); self.u32()

    def vm_genericmsg(self):
        self.u32(); self.u32(); self.sub1()
        cls = self.read_raw_class()
        self.cache.append(cls)
        self.om_args(cls[0])
        self.u16(); n = self.u16()
        for _ in range(n):
            w = self.u16()
            if w == 0x1e57: self.read_class()
            elif w == 0x369e: self.read_raw_class()
            elif w in (0x2d6b, 0x2f1a): self.u16(); k = self.u16(); self.skip(k)
            else: raise ParseError('genericmsg w=%x @%x' % (w, self.p))
            w2 = self.u16()
            if w2 == 0x7fff: self.u32()
            if w2 == 0xffff:
                k_ = struct.unpack_from('<H', self.d, self.p)[0]; nm_ = self.d[self.p + 2:self.p + 2 + k_]
                named = 0 < k_ < 64 and len(nm_) == k_ and all(b >= 0x20 for b in nm_)   # else a dword (PM form)
                if self.variant == 2 and named:
                    k = self.u16(); nm = self.d[self.p:self.p + k]; self.p += k
                    self.cache.append((nm.decode('cp932', 'replace'), 0))
                else:
                    self.u32(); self.cache.append(None)
            self.sub1()
        return cls

    def vm_call(self):
        self.u32(); self.u32(); self.read_class_list(); n = self.u16()
        for _ in range(n):
            d = self.u32()
            if d == 4:
                w = self.u16()
                if w == 0x1e57: self.read_class()
                elif w == 0x369e: self.read_raw_class()
                elif w in (0x2d6b, 0x2f1a): self.u16(); k = self.u16(); self.skip(k)
                else: raise ParseError('call w=%x @%x' % (w, self.p))
                self.skip(4)
            else:
                k = d & 3
                if k == 0: self.read_class_list()
                elif k == 1: self.string()
                elif k == 2: pass
                else:
                    t1 = self.u32()
                    if t1 == 0x137: self.u32()
                    elif t1 != 0x138: raise ParseError('call t1 @%x' % self.p)
        if self.cur_schema > 0x12:
            # PM FUN_004bc9d0 / FUN_004bcaf0 / FUN_004bc870: count (byte, 0xff -> word), then items
            k = self.u8()
            if k == 0xff: k = self.u16()
            for _ in range(k):
                w = self.u16()
                if w & 0x8000: self.string()
                else: self.read_class_list()

    def vm_msg3(self):
        """PM FUN_004be430: base, word, word, byte n1, byte n2, n1*12, n2*10 (text lives in the table)."""
        self.u32(); self.u32(); self.u16(); self.u16()
        n1 = self.u8(); n2 = self.u8()
        self.skip(12 * n1 + 10 * n2)

    def vm_directionsync(self):
        """PM FUN_004c79c0: base, dword flags, [schema>0x13: word n, n refs], [flags bit15 & schema>0x14: dword + variant]."""
        self.u32(); self.u32()
        flags = self.u32()
        if self.cur_schema > 0x13:
            n = self.u16()
            for _ in range(n): self.read_class_list()
        if flags & 0x8000 and self.cur_schema > 0x14:
            self.u32(); self.sub1()

    def vm_sync(self):
        self.u32(); self.u32(); self.read_class_list(); self.u8(); self.u32()

    def vm_label(self):
        self.u32(); self.u32(); self.read_class_list()

    vm_jump = vm_label

    def vm_ret(self):
        self.u32(); self.u32()

    def vm_blt(self):
        self.u32(); self.u32()
        cls = self.read_class()
        if cls:
            self.cache.append(cls)
            self.inline_object(cls)
        self.u16(); self.u8(); self.u8()
        for _ in range(4 if self.variant == 1 else 1):
            self.sub1()

    def vm_msg(self):
        num = self.u32(); flag = self.u32(); self.read_class_list()
        n = self.u8()
        if n == 0xff: n = self.u16()
        if getattr(self, 'msg_utf16', False):     # PM's legacy CVmMsg reader (FUN_004be3c0): n UTF-16 chars
            if n == 0xfffe:
                n = self.u8()
                if n == 0xff: n = self.u16()
            n *= 2
        self.strings.append((self.p, self.d[self.p:self.p + n])); self.p += n
        self.read_class_list()
        if flag & 0x4000000: self.read_class_list()
        if flag & 0x200000:
            w = self.u16()
            if w & 4: self.string()
            if w & 0x40: self.string()
            if w & 0x20: self.u32()
            if w & 3:
                k = self.u16()
                for _ in range(k):
                    if w & 8: self.u16()
                    self.read_class_list()
                    if (w & 3) == 3: self.read_class_list()

    def vm_image(self):
        self.u32(); self.u32(); self.u16(); self.u16(); self.u8(); self.u8(); self.sub1(); self.sub1()

    DISPATCH = {
        'CVmSound': 'vm_sound', 'CVmFlagOp': 'vm_flagop', 'CVmGenericMsg': 'vm_genericmsg', 'CVmCall': 'vm_call',
        'CVmSync': 'vm_sync', 'CVmLabel': 'vm_label', 'CVmJump': 'vm_jump', 'CVmRet': 'vm_ret',
        'CVmBlt': 'vm_blt', 'CVmMsg': 'vm_msg', 'CVmImage': 'vm_image',
        'CVmMsg3': 'vm_msg3', 'CVmDirectionSync': 'vm_directionsync',
    }

    def parse(self):
        hdr = struct.unpack_from('<IIIIII', self.d, 0)
        self.hdr = hdr
        if hdr[1] != 0xffff0000: raise ParseError('bad marker %x' % hdr[1])
        self.version, self.size, self.count, self.extra = hdr[2], hdr[3], hdr[4], hdr[5]
        self.p = 24
        self.instrs = []
        self.ins_ev = []    # (ev_lo, ev_hi) per instruction
        self.ins_res = []   # resolved top-level references per instruction
        for i in range(self.count):
            start = self.p
            ev_lo = len(self.ev)
            cls = self.read_class()
            if cls is None: raise ParseError('null class at instr %d @%x' % (i, start))
            fn = self.DISPATCH.get(cls[0])
            if fn is None: raise ParseError('unknown instr class %s at %d @%x' % (cls, i, start))
            self.cur_schema = cls[1]
            r0, s0, v0 = len(self.refs), len(self.strings), len(self.resolved)
            extra = getattr(self, fn)()
            self.instrs.append((start, self.p, cls[0], extra, self.refs[r0:], self.strings[s0:]))
            self.ins_ev.append((ev_lo, len(self.ev)))
            self.ins_res.append(self.resolved[v0:])
        # version > 0x11 (PM): tail = dword nchars + UTF-16 text table, word n + n object refs (FUN_00441430/441580)
        self.tail = None
        if self.version > 0x11 and self.p < len(self.d):
            t0 = self.p; ev_lo = len(self.ev); v0 = len(self.resolved)
            nchars = self.u32(); self.skip(2 * nchars)
            text_end = self.p
            nrefs = self.u16()
            for _ in range(nrefs): self.read_class_list()
            self.tail = dict(start=t0, text_start=t0 + 4, text_end=text_end, end=self.p, nrefs=nrefs,
                             ev=(ev_lo, len(self.ev)), res=self.resolved[v0:])
        return self.instrs


def main():
    import glob
    args = sys.argv[1:] or [os.path.join(HERE, '..', 'out', 'af_rsa')]
    paths = []
    for a in args:
        paths += sorted(glob.glob(os.path.join(a, '*.bin'))) if os.path.isdir(a) else [a]
    ok = 0
    for p in paths:
        d = open(p, 'rb').read()
        res = None
        fails = []
        for variant in (2, 1):
            h = Heap(d[4:] if False else d, variant)
            try:
                h.parse()
                res = 'OK v%d instrs=%d end=%x/%x' % (variant, h.count, h.p, len(d))
                ok += 1
                break
            except (ParseError, IndexError, struct.error) as e:
                fails.append('v%d@%d: %s' % (variant, len(getattr(h, 'instrs', [])), e)); res = 'FAIL ' + ' | '.join(fails)
        print(os.path.basename(p), res)
    print('parsed', ok, '/', len(paths))


if __name__ == '__main__':
    main()
