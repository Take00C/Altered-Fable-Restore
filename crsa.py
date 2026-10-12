"""CRsa object encode/decode: 9-byte header + crypted heap block (engine FUN_005beb70 format)."""
import struct

M = 0xFFFFFFFF


def keystream_xor(data, key=0x7E6B8CE2):
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ (key & 0xFF)
        key = (~(key * 2 + 0xA3B376C9 + ((key >> 15) & 1))) & M
    return out


def encrypt_block(heap, key=0x7E6B8CE2):
    """Writer path of FUN_005beb70: A=size^0x36d1a974, B=(size*8)^0xc92e568b, then 32-byte chunks + checksum."""
    n = len(heap)
    out = bytearray(struct.pack('<II', n ^ 0x36D1A974, ((n * 8) & M) ^ 0xC92E568B))
    k = key; pos = 0
    while True:
        chunk = min(32, n - pos)
        cc = 0
        for j in range(chunk):
            b = heap[pos + j]
            cc = (cc + b * (chunk - j)) & 0xFFFF
            out.append(b ^ (k & 0xFF))
            k = (~(k * 2 + 0xA3B376C9 + ((k >> 15) & 1))) & M
        out += struct.pack('<H', cc)
        pos += chunk
        if pos >= n:
            break
    return bytes(out)


def decrypt_block(data, key=0x7E6B8CE2):
    a, b = struct.unpack_from('<II', data, 0)
    n = ((b ^ 0xC92E568F) & M) >> 3
    assert n == (~(a ^ 0xC92E568B)) & M, 'size check'
    out = bytearray(); p = 8; k = key; pos = 0
    while True:
        chunk = min(32, n - pos); cc = 0
        for j in range(chunk):
            v = data[p] ^ (k & 0xFF); p += 1
            out.append(v); cc = (cc + v * (chunk - j)) & 0xFFFF
            k = (~(k * 2 + 0xA3B376C9 + ((k >> 15) & 1))) & M
        chk = struct.unpack_from('<H', data, p)[0]; p += 2
        assert chk == cc, 'checksum'
        pos += chunk
        if pos >= n: break
    return bytes(out), p


def crsa_body(header9, heap):
    return bytes(header9) + encrypt_block(heap)


if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from objio import read_at, PM_RIO, AF_RIO
    # round-trip: PM script at known position (file name = position of 6e 03)
    for path, rio in [('out/pm_rsa/01b30e953a.bin', PM_RIO), ('out/af_rsa/000045d98b.bin', AF_RIO)]:
        pos = int(os.path.basename(path)[:-4], 16)
        heap = open(os.path.join(os.path.dirname(__file__), '..', path), 'rb').read()
        enc = encrypt_block(heap)
        orig = read_at(rio, pos + 9, len(enc))
        print(path, 'heap', len(heap), 'enc', len(enc), 'identical to archive bytes:', enc == orig)
        dec, used = decrypt_block(enc)
        print('   decrypt roundtrip', dec == heap, used == len(enc))
