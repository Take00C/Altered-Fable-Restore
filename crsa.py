"""CRsa object encode/decode: 9-byte header + crypted heap block (engine FUN_005beb70 format).

encrypt_block / decrypt_block give exactly the bytes of the byte-by-byte forms kept below (*_ref; the 0.1.2 code):
the keystream does not depend on the data (the key runs on from its start value over the whole block), so it is made
once per process and the XOR is one big-integer XOR; the 16-bit checksum of 32-byte chunk c, sum_j p[32c + j] * (32 - j),
is coefficient 32c + 31 of P(x) * K(x) with P = the plain bytes as 24-bit lanes and K = sum_t (t + 1) x^t (t < 32):
every coefficient is at most 255 * 528 < 2^24, so the lanes never carry. A block decrypt_block cannot read (size check,
checksum, too short) goes through decrypt_block_ref, which raises its own error. The kept keystream is extended under
a lock, so calls from several threads at once give the same bytes too."""
import struct, threading

M = 0xFFFFFFFF
KEY = 0x7E6B8CE2


def keystream_xor(data, key=KEY):
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ (key & 0xFF)
        key = (~(key * 2 + 0xA3B376C9 + ((key >> 15) & 1))) & M
    return out


def encrypt_block_ref(heap, key=KEY):
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


def decrypt_block_ref(data, key=KEY):
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


_KS = [bytearray(), KEY]            # the default key's keystream so far, and the key state after it
_KS_LOCK = threading.Lock()         # (one thread at a time extends and reads it)


def _keystream(n, key):
    """The first n bytes of key's keystream (exactly n)."""
    if key != KEY:
        return keystream_xor(bytes(n), key)
    with _KS_LOCK:
        ks, k = _KS
        if len(ks) < n:
            add = bytearray(n - len(ks))
            for i in range(len(add)):
                add[i] = k & 0xFF
                k = (~(k * 2 + 0xA3B376C9 + ((k >> 15) & 1))) & M
            ks += add; _KS[1] = k
        return ks[:n]


_KER = sum((t + 1) << (24 * t) for t in range(32))


def _checksums(plain):
    """The '<H' checksums of plain's 32-byte chunks (the last one shorter; one chunk when plain is empty), joined."""
    n = len(plain); nf = n // 32; out = bytearray()
    if nf:
        lanes = bytearray(3 * 32 * nf); lanes[0::3] = plain[:32 * nf]
        prod = (int.from_bytes(lanes, 'little') * _KER).to_bytes(3 * 32 * nf + 100, 'little')
        cs = bytearray(2 * nf); cs[0::2] = prod[93:93 + 96 * nf:96]; cs[1::2] = prod[94:94 + 96 * nf:96]
        out += cs
    r = n - 32 * nf
    if r or n == 0:
        cc = 0
        for j in range(r): cc = (cc + plain[32 * nf + j] * (r - j)) & 0xFFFF
        out += struct.pack('<H', cc)
    return out


def encrypt_block(heap, key=KEY):
    """encrypt_block_ref(heap, key), the same bytes."""
    heap = bytes(heap)
    n = len(heap)
    ks = _keystream(n, key)
    enc = (int.from_bytes(heap, 'little') ^ int.from_bytes(ks, 'little')).to_bytes(n, 'little')
    cs = _checksums(heap)
    nf = n // 32; r = n - 32 * nf
    nch = nf + (1 if (r or n == 0) else 0)
    out = bytearray(8 + n + 2 * nch)
    out[0:8] = struct.pack('<II', n ^ 0x36D1A974, ((n * 8) & M) ^ 0xC92E568B)
    if nf:
        for j in range(32): out[8 + j:8 + 34 * nf:34] = enc[j:32 * nf:32]
        out[8 + 32:8 + 34 * nf:34] = cs[0:2 * nf:2]; out[8 + 33:8 + 34 * nf:34] = cs[1:2 * nf:2]
    if nch > nf:
        p = 8 + 34 * nf
        out[p:p + r] = enc[32 * nf:]; out[p + r:p + r + 2] = cs[2 * nf:]
    return bytes(out)


def decrypt_block(data, key=KEY):
    """decrypt_block_ref(data, key): (heap, index after the block); its errors for a block it cannot read."""
    try:
        a, b = struct.unpack_from('<II', data, 0)
        n = ((b ^ 0xC92E568F) & M) >> 3
        if n != (~(a ^ 0xC92E568B)) & M: raise ValueError
        nf = n // 32; r = n - 32 * nf
        nch = nf + (1 if (r or n == 0) else 0)
        end = 8 + n + 2 * nch
        blk = bytes(data[8:end])
        if len(blk) != end - 8: raise ValueError
        enc = bytearray(n); stored = bytearray(2 * nch)
        if nf:
            for j in range(32): enc[j:32 * nf:32] = blk[j:34 * nf:34]
            stored[0:2 * nf:2] = blk[32:34 * nf:34]; stored[1:2 * nf:2] = blk[33:34 * nf:34]
        if nch > nf:
            p = 34 * nf
            enc[32 * nf:] = blk[p:p + r]; stored[2 * nf:] = blk[p + r:p + r + 2]
        ks = _keystream(n, key)
        plain = (int.from_bytes(enc, 'little') ^ int.from_bytes(ks, 'little')).to_bytes(n, 'little')
        if _checksums(plain) != stored: raise ValueError
        return plain, end
    except Exception:
        return decrypt_block_ref(data, key)


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
