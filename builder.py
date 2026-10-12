"""Multi-source heap builder.

Emits instructions taken from one or more parsed source heaps into a new heap, rendering every object
reference through a remap policy:
  ('PM', off)   -> reference an existing Photonmelodies object (rendered from a PM template span, or constructed)
  ('NEW', off)  -> an AF object imported into the .ruo under a new key (parent = our owner-chain pad 0)
Class definitions are de-duplicated per (name, schema, kind); load-array indices are renumbered.
"""
import struct, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rsaparse import Heap

K = 0xA2FB6AD1


def enc_off_pm_from_dec(dec):        # dec = AF-style decoded value (3 + 2x) of a PM extent
    return (K + (dec - 3) // 2) & 0xFFFFFFFF


class BuildError(Exception):
    pass


class Src:
    def __init__(self, heap, archive, name=''):
        self.h = heap; self.archive = archive; self.name = name
        self.map = {0: 0, 1: 1}
        self.def_class = {}; self.def_ref = {}
        self.pad = None
        for k, ev in enumerate(heap.ev):
            if ev[0] in ('cdef', 'rdef', 'adef'): self.def_class[ev[3]] = k
            elif ev[0] == 'ref': self.def_ref[ev[3]] = k
            elif ev[0] == 'pad' and self.pad is None: self.pad = ev
        self.rcl_to_ref = {}
        for k, ev in enumerate(heap.ev):
            if ev[0] == 'ref':
                self.rcl_to_ref[self._rcl_start(k)] = k

    def _rcl_start(self, k):
        start = self.h.ev[k][1]
        for j in range(k - 1, -1, -1):
            ev = self.h.ev[j]
            if ev[0] == 'rcl' and ev[1] in (start, start - 1):
                return j
        raise BuildError('rcl not found')

    def class_def_bytes(self, e):
        k = self.def_class[e]; ev = self.h.ev[k]
        return self.h.d[ev[1]:ev[2]], ev[0]

    def is_pad(self, e):
        return self.pad is not None and self.pad[2] <= e < self.pad[2] + self.pad[3]


class Builder:
    def __init__(self, pad_count, remap, pm_templates, packed_names, key_alloc):
        self.out = bytearray(); self.next = 2
        self.classes = {}; self.objs = {}
        self.pad_count = pad_count; self.pad_first = None
        self.remap = remap                    # fn(src, (cls, off, size)) -> target tuple
        self.pm_templates = pm_templates      # dict: pm_off -> (Src, ref_event_index)  (same owner chain!)
        self.packed = packed_names            # class name -> packed name bytes
        self.key_alloc = key_alloc            # fn(af_off, cls) -> (enc_off, enc_size) for imported objects
        self.imports = {}                     # af_off -> (cls, size)
        self.constructed = {}                 # pm_off -> spec for objects without template
        self.schema_override = {}             # class name -> schema written instead of the source's (cdef only)
        self.repl_used = []                   # (src name, pos, original bytes) of applied raw_repl substitutions

    # -------- primitives
    def alloc(self):
        i = self.next; self.next += 1; return i

    def ensure_pad(self):
        if self.pad_first is None:
            self.out.append(self.pad_count)
            self.pad_first = self.next; self.next += self.pad_count

    def emit_class(self, name, schema, kind, defbytes=None):
        if kind == 'cdef' and name in self.schema_override and schema != self.schema_override[name]:
            schema = self.schema_override[name]
            if defbytes is not None:
                defbytes = defbytes[:2] + struct.pack('<H', schema) + defbytes[4:]
        key = (name, schema, kind)
        if key in self.classes:
            self.out += struct.pack('<H', 0x8000 | self.classes[key]); return self.classes[key]
        if defbytes is None:
            if kind == 'cdef':
                pk = self.packed[name]
                defbytes = b'\xff\xff' + struct.pack('<H', schema) + bytes([len(pk)]) + pk
            else:
                nb = name.encode('cp932')
                defbytes = b'\xff\xff' + bytes([schema]) + bytes([len(nb)]) + nb
        self.out += defbytes
        i = self.alloc(); self.classes[key] = i; return i

    # -------- object rendering
    def object_slot(self, src, cls, off, size, R=None):
        """Emit an object reference slot (we are positioned at a read_class_list slot)."""
        self.ensure_pad()
        target = self.remap(src, (cls, off, size))
        if target in self.objs:
            self.out += struct.pack('<H', self.objs[target]); return self.objs[target]
        kind = target[0]
        if kind == 'PAD':
            idx = self.pad_first + target[1]
            self.out += struct.pack('<H', idx); return idx
        if kind == 'PM':
            pm_off = target[1]
            if pm_off in self.pm_templates:
                tsrc, tk = self.pm_templates[pm_off]
                self._prime_pads(tsrc)
                R2 = tsrc.h.ev[tk]
                kr = tsrc._rcl_start(tk)
                self._replay(tsrc, kr + 1, tk, R2[1], R2[2], nested=True)
            elif pm_off in self.constructed:
                c = self.constructed[pm_off]
                self.emit_class(c['cls'][0], c['cls'][1], 'cdef')
                self.out += struct.pack('<H', c.get('flag', 0xC108))
                self.out += struct.pack('<II', enc_off_pm_from_dec(pm_off), c['enc_size'])
                # parent slot
                p = c['parent']
                self.object_slot(None, p[0], p[1], p[2])
                self.out += b'\x00'
            else:
                raise BuildError('no PM template for %s %x' % (cls, pm_off))
            idx = self.alloc(); self.objs[target] = idx; return idx
        if kind == 'NEW':
            af_off = target[1]
            enc_off, enc_size = self.key_alloc(af_off, cls, size)
            self.emit_class(cls[0], cls[1], 'cdef')
            flag = 0xC108
            if R is not None and src is not None:
                flag = struct.unpack_from('<H', src.h.d, R[4] - 2)[0]
            self.out += struct.pack('<H', flag)
            self.out += struct.pack('<II', enc_off, enc_size)
            # parent: our owner-chain pad 0 (the route folder)
            self.out += struct.pack('<H', self.pad_first)
            self.out += (b'\x00' if (flag & 3) == 0 else b'\x00\x00\x00\x00')
            self.imports[af_off] = (cls, size)
            idx = self.alloc(); self.objs[target] = idx; return idx
        raise BuildError('bad target %r' % (target,))

    def _prime_pads(self, src):
        if src.pad is not None and self.pad_first is not None:
            for j in range(min(src.pad[3], self.pad_count)):
                src.map.setdefault(src.pad[2] + j, self.pad_first + j)

    # -------- event replay
    def _replay(self, src, ev_lo, ev_hi, byte_lo, byte_hi, nested=False):
        h = src.h; d = h.d
        cur = byte_lo
        skip_ent = set(); skip_n = 0
        k = ev_lo - 1
        while k + 1 < ev_hi:
            k += 1
            ev = h.ev[k]; kind = ev[0]
            if kind == 'ent':
                if skip_n: skip_n -= 1; continue
                e = ev[2]
                if e in skip_ent: skip_ent.discard(e); continue
                if e in src.map: continue
                src.map[e] = self.alloc(); continue
            if kind == 'rcl':
                if ev[1] > cur: self._raw(src, cur, ev[1])
                cur = ev[1]
                had_pad = src.pad is not None and src.pad[1] == ev[1]
                self.ensure_pad(); self._prime_pads(src)
                k_rcl = k
                if had_pad:
                    cur += 1  # drop the source's pad byte; ours was emitted
                    # skip the 'pad' event and its pad 'ent' events
                    if k + 1 < ev_hi and h.ev[k + 1][0] == 'pad':
                        k += 1; skip_n = h.ev[k][3]
                kr = src.rcl_to_ref.get(k_rcl)
                if kr is not None:
                    R = h.ev[kr]
                    idx = self.object_slot(src, R[5], R[6], R[7], R)
                    src.map[R[3]] = idx
                    cur = R[2]; k = kr + 1   # skip span + the object's own 'ent'
                continue
            if kind == 'pad':
                continue
            if kind in ('cdef', 'rdef', 'adef'):
                if ev[1] > cur: self._raw(src, cur, ev[1])
                e = ev[3]; cls = ev[4]
                idx = self.emit_class(cls[0], cls[1], kind, d[ev[1]:ev[2]])
                src.map[e] = idx; skip_ent.add(e)
                cur = ev[2]; continue
            if kind == 'cidx':
                if ev[1] > cur: self._raw(src, cur, ev[1])
                e = ev[2]
                if e in src.def_class:
                    db, dk = src.class_def_bytes(e)
                    cls = h.cache[e]
                    idx = self.emit_class(cls[0], cls[1], dk, db)
                    src.map[e] = idx
                elif e in src.map:
                    self.out += struct.pack('<H', 0x8000 | src.map[e])
                else:
                    raise BuildError('class idx %d unresolved in %s' % (e, src.name))
                cur = ev[1] + 2; continue
            if kind == 'oidx':
                if ev[1] > cur: self._raw(src, cur, ev[1])
                e = ev[2]
                if src.is_pad(e):
                    if e not in src.map: raise BuildError('pad %d unmapped' % e)
                    self.out += struct.pack('<H', src.map[e])
                elif e in h.objinfo:
                    cls, off, size = h.objinfo[e]
                    R = h.ev[src.def_ref[e]] if e in src.def_ref else None
                    idx = self.object_slot(src, cls, off, size, R)
                    src.map[e] = idx
                elif e in src.map:
                    self.out += struct.pack('<H', src.map[e])
                else:
                    raise BuildError('object idx %d unresolved in %s' % (e, src.name))
                cur = ev[1] + 2; continue
            # 'null', 'ref' markers: raw copy handles them
        if byte_hi > cur: self._raw(src, cur, byte_hi)

    def _raw(self, src, a, b):
        """Copy source bytes [a, b), applying src.raw_repl substitutions {start: (end, new_bytes)}."""
        d = src.h.d
        repl = getattr(src, 'raw_repl', None)
        if not repl:
            self.out += d[a:b]; return
        cur = a
        for s in sorted(k for k in repl if a <= k < b):
            e, nb = repl[s]
            if e > b: raise BuildError('replacement crosses a token boundary at %x' % s)
            self.out += d[cur:s]; self.out += nb; cur = e
            self.repl_used.append((src.name, s, bytes(d[s:e])))
        self.out += d[cur:b]

    def emit_instructions(self, src, i0, i1):
        h = src.h
        for i in range(i0, i1):
            lo, hi = h.ins_ev[i]
            self._replay(src, lo, hi, h.instrs[i][0], h.instrs[i][1])

    def emit_raw_instruction(self, data):
        self.out += data

    def heap_bytes(self, first_dword, version, size, count, extra):
        return first_dword + struct.pack('<IIIII', 0xffff0000, version, size, count, extra) + bytes(self.out)
