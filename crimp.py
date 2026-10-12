"""AF CRimp (sprite set property map, schema 3) -> PM-readable bytes.
Format (FUN_0056f8f0 / FUN_005e3490): u16 count, then count x [CString key, value]; value = dword d:
  d == 4 -> typed: u16 w (0x2f1a), u16 a, u16 len, name[len], payload[size(type)]
  d & 3 == 2 -> immediate (no payload)
AF writes ANSI cp932 keys and Japanese type names; PM writes UTF-16 keys (0xff 0xfffe len) and ASCII type names."""
import struct

TYPE_MAP = {'ロングベクトル': ('_CVector32', 12), '点': ('_CPoint32', 8)}


class CrimpError(Exception):
    pass


def read_cstring(b, p):
    n = b[p]; p += 1
    if n == 0xff:
        n = struct.unpack_from('<H', b, p)[0]; p += 2
        if n == 0xfffe:
            n = b[p]; p += 1
            if n == 0xff: n = struct.unpack_from('<H', b, p)[0]; p += 2
            s = b[p:p + 2 * n].decode('utf-16le'); return s, p + 2 * n
    s = b[p:p + n].decode('cp932'); return s, p + n


def write_cstring_utf16(s):
    u = s.encode('utf-16le'); n = len(u) // 2
    return b'\xff\xfe\xff' + (bytes([n]) if n < 0xff else b'\xff' + struct.pack('<H', n)) + u


def convert(body):
    """Returns (new_body, stats). Raises CrimpError if the layout is not understood."""
    p = 0; out = bytearray()
    count = struct.unpack_from('<H', body, p)[0]; p += 2
    if count > 64: raise CrimpError('count %d' % count)
    out += struct.pack('<H', count)
    types = []
    for _ in range(count):
        key, p = read_cstring(body, p)
        out += write_cstring_utf16(key)
        d = struct.unpack_from('<I', body, p)[0]; p += 4
        out += struct.pack('<I', d)
        if d == 4:
            w, a, ln = struct.unpack_from('<HHH', body, p); p += 6
            name = body[p:p + ln].decode('cp932'); p += ln
            if w != 0x2f1a or name not in TYPE_MAP: raise CrimpError('type %x %r' % (w, name))
            pm, size = TYPE_MAP[name]
            out += struct.pack('<HHH', w, a, len(pm)) + pm.encode('ascii') + body[p:p + size]; p += size
            types.append(name)
        elif d & 3 != 2:
            raise CrimpError('value kind d=%x' % d)
    out += body[p:]             # any trailing fields unchanged
    return bytes(out), dict(count=count, types=types, trailing=len(body) - p)


if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from objio import read_at, AF_RIO, af_header
    for off in [int(x, 16) for x in sys.argv[1:]]:
        raw = read_at(AF_RIO, off - 3, 4096); n = af_header(raw)[0]
        try:
            nb, st = convert(raw[n:]); print(hex(off), st)
        except Exception as e:
            print(hex(off), 'ERR', e)
