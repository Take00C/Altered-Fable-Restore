"""Slice an instruction range out of a parsed rUGP heap into a standalone heap (same format/version),
re-emitting any class/object definitions the range depends on and renumbering all load-array tags.

The output ends with a CVmRet so it can be CVmCall'ed. Verified by re-parsing (verify_slice).
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rsaparse import Heap, ParseError


class SliceError(Exception):
    pass


class Slicer:
    def __init__(self, h):
        self.h = h; self.d = h.d
        self.def_class = {}      # entry -> event index (cdef/rdef)
        self.def_ref = {}        # object entry -> event index ('ref')
        self.pad = None
        for k, ev in enumerate(h.ev):
            if ev[0] in ('cdef', 'rdef', 'adef'): self.def_class[ev[3]] = k
            elif ev[0] == 'ref': self.def_ref[ev[3]] = k
            elif ev[0] == 'pad': self.pad = ev
        self.rcl_to_ref = {}     # rcl event index -> ref event index (explicit definitions only)
        for k, ev in enumerate(h.ev):
            if ev[0] == 'ref':
                self.rcl_to_ref[self._rcl_start(k)] = k
        self.ref_overrides = {}  # enc_pos -> 8 bytes replacing enc_off+enc_size (used by the remapper)

    # ---- emission helpers
    def _alloc(self, old):
        self.map[old] = self.next; self.next += 1

    def _copy_to(self, pos):
        if pos > self.cur:
            self.out += self.d[self.cur:pos]
        self.cur = max(self.cur, pos)

    def _rcl_start(self, k):
        """Event index of the 'rcl' that opened the read_class_list whose 'ref' event is k."""
        start = self.h.ev[k][1]
        depth = 0
        for j in range(k - 1, -1, -1):
            ev = self.h.ev[j]
            if ev[0] == 'ref' and j != k:
                pass
            if ev[0] == 'rcl' and ev[1] in (start, start - 1):
                # make sure it is not a nested call starting at the same byte (cannot happen: nested starts later)
                return j
        raise SliceError('rcl for ref event %d not found' % k)

    def emit_class_def(self, e):
        k = self.def_class.get(e)
        if k is None:
            raise SliceError('class entry %d has no definition' % e)
        ev = self.h.ev[k]
        self.out += self.d[ev[1]:ev[2]]
        self._alloc(e)

    def emit_object_def(self, e):
        k = self.def_ref.get(e)
        if k is None:
            raise SliceError('object entry %d not defined by an explicit ref (inline/OM/name?)' % e)
        R = self.h.ev[k]
        kr = self._rcl_start(k)
        saved = (self.cur,)
        self.cur = R[1]
        self._emit_events(kr + 1, k, R[2], skip_pad=True)
        self._copy_to(R[2])
        self.cur = saved[0]
        self._alloc(e)

    def _emit_events(self, ev_lo, ev_hi, byte_hi, skip_pad=False):
        skip_ents = 0
        skip_entry = set()
        k = ev_lo - 1
        while k + 1 < ev_hi:
            k += 1
            ev = self.h.ev[k]; kind = ev[0]
            if kind == 'rcl' and k in self.rcl_to_ref:
                kr = self.rcl_to_ref[k]
                R = self.h.ev[kr]
                if self.map.get(R[3]) is not None and kr < ev_hi:
                    # object already defined in the output: emit a 2-byte object index instead of a 2nd definition
                    if not self.pad_emitted and not (self.pad is not None and self.pad[1] == ev[1]):
                        self._copy_to(ev[1]); n = self.pad[3] if self.pad else 0
                        self.out.append(n)
                        for j in range(n): self._alloc(self.pad[2] + j)
                        self.pad_emitted = True
                    self._copy_to(R[1])
                    self.out += struct.pack('<H', self.map[R[3]])
                    self.cur = R[2]
                    k = kr + 1          # skip the span and the object's own 'ent' event
                    continue
            if kind == 'ent':
                if skip_ents:
                    skip_ents -= 1; continue
                if ev[2] in skip_entry:
                    skip_entry.discard(ev[2]); continue
                if ev[2] in self.map and ev[2] not in self.pending:
                    continue
                self.pending.discard(ev[2])
                self._alloc(ev[2]); continue
            if kind == 'rcl':
                if not self.pad_emitted:
                    self._copy_to(ev[1])
                    if self.pad is not None and self.pad[1] == ev[1]:
                        pass  # original pad sits right here; the 'pad' event will copy it
                    else:
                        n = self.pad[3] if self.pad else 0
                        self.out.append(n)
                        for j in range(n): self._alloc(self.pad[2] + j)
                        self.pad_emitted = True
                continue
            if kind == 'pad':
                if skip_pad or self.pad_emitted:
                    skip_ents = ev[3]
                    if not skip_pad:
                        self._copy_to(ev[1]); self.cur = ev[1] + 1  # drop duplicate pad byte (should not happen)
                    continue
                self._copy_to(ev[1]); self.out += self.d[ev[1]:ev[1] + 1]; self.cur = ev[1] + 1
                self.pad_emitted = True
                continue
            if kind in ('cdef', 'rdef', 'adef'):
                self._copy_to(ev[1])
                e = ev[3]
                if e in self.map:
                    self.out += struct.pack('<H', 0x8000 | self.map[e]); skip_entry.add(e)
                else:
                    self.out += self.d[ev[1]:ev[2]]; self.pending.add(e); self.map[e] = None
                self.cur = ev[2]; continue
            if kind == 'cidx':
                self._copy_to(ev[1]); e = ev[2]
                if self.map.get(e) is None: self.emit_class_def(e)
                else: self.out += struct.pack('<H', 0x8000 | self.map[e])
                self.cur = ev[1] + 2; continue
            if kind == 'oidx':
                self._copy_to(ev[1]); e = ev[2]
                if self.map.get(e) is None: self.emit_object_def(e)
                else: self.out += struct.pack('<H', self.map[e])
                self.cur = ev[1] + 2; continue
            if kind == 'ref':
                # optional remap of the encoded offset/size of this explicit reference
                enc_pos = ev[4]
                if enc_pos in self.ref_overrides:
                    self._copy_to(enc_pos)
                    self.out += self.ref_overrides[enc_pos]
                    self.cur = enc_pos + 8
                continue
        self._copy_to(byte_hi)

    def slice(self, i0, i1, add_ret=True):
        h = self.h
        self.out = bytearray(); self.map = {0: 0, 1: 1}; self.next = 2; self.pending = set()
        self.pad_emitted = False
        body_start = len(self.out)
        lo = h.ins_ev[i0][0]; hi = h.ins_ev[i1 - 1][1]
        self.cur = h.instrs[i0][0]
        self._emit_events(lo, hi, h.instrs[i1 - 1][1])
        count = i1 - i0
        if add_ret:
            ret = next((ins for ins in h.instrs if ins[2] == 'CVmRet'), None)
            if ret is None:
                raise SliceError('no CVmRet in source heap to copy')
            ridx = h.instrs.index(ret)
            ev = h.ev[h.ins_ev[ridx][0]]   # its class tag event
            e = ev[3] if ev[0] in ('cdef', 'rdef', 'adef') else ev[2]
            if self.map.get(e) is None:
                self.emit_class_def(e)
            else:
                self.out += struct.pack('<H', 0x8000 | self.map[e])
            tag_len = (ev[2] - ev[1]) if ev[0] == 'cdef' else 2
            self.out += self.d[ret[0] + tag_len:ret[1]]
            count += 1
        hdr = self.d[0:4] + struct.pack('<IIIII', 0xffff0000, h.version, h.size, count, h.extra)
        return bytes(hdr) + bytes(self.out)


def verify_slice(h, i0, i1, data, check_ret=True):
    """Re-parse the slice; every instruction must resolve to the same references as the original."""
    g = Heap(data, 2)
    g.parse()
    n = i1 - i0
    assert g.count == n + (1 if check_ret else 0), (g.count, n)
    assert g.p == len(data), ('trailing bytes', g.p, len(data))
    bad = 0
    for j in range(n):
        a = [x for x in h.ins_res[i0 + j]]
        b = [x for x in g.ins_res[j]]
        norm = lambda L: [('pad', None) if (x and x[0] == 'pad') else x for x in L]
        if norm(a) != norm(b) or h.instrs[i0 + j][2] != g.instrs[j][2]:
            bad += 1
            if bad <= 5:
                print('  mismatch at', i0 + j, h.instrs[i0 + j][2], a[:3], '!=', b[:3])
    return bad == 0, g


if __name__ == '__main__':
    p = sys.argv[1]; i0 = int(sys.argv[2]); i1 = int(sys.argv[3])
    h = Heap(open(p, 'rb').read(), 2); h.parse()
    s = Slicer(h)
    out = s.slice(i0, i1)
    ok, g = verify_slice(h, i0, i1, out)
    print('slice', i0, i1, 'bytes', len(out), 'verify', ok)
