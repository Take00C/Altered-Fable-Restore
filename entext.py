"""Optional English text for restored lines, from the player's own copy of the afhook fan translation package
(afhook.pkg, read in place at build time, never copied or shipped). Without it the build is unchanged.

Package format (afhook plugin CResourceManager::LoadPackage): 13 uint32 header (magic 0x8D120AB6, textOffset,
textCount, ...); text entries: uint32 id, uint32 len(src)+1, uint32 len(tr)+1, src + NUL, [tr + NUL]. The plugin
replaces a line by exact byte match of the whole cp932 line, so the lookup here does the same."""
import re
import struct

PKG_MAGIC = 0x8D120AB6
# characters PM's own English text never uses (3,000+ PM lines checked); U+3000 may not count as a wrap point
_TYPO = {'　': ' ', '’': "'", '‘': "'", '～': '~'}


def load_pkg(path):
    """{source line bytes: translation bytes}; empty dict when the file is missing, damaged or not a package."""
    try:
        d = open(path, 'rb').read()
        hdr = struct.unpack_from('<13I', d, 0)
        if hdr[0] != PKG_MAGIC: return {}
        out, p = {}, hdr[1]
        for _ in range(hdr[2]):
            _id, s, t = struct.unpack_from('<III', d, p); p += 12
            if s <= 1: continue
            src = d[p:p + s - 1]; p += s
            if t > 1:
                out.setdefault(src, d[p:p + t - 1]); p += t
            if p > len(d): return {}
        return out
    except (OSError, struct.error):
        return {}


def pm_name_map(heaps):
    """{Japanese speaker name: English speaker name} from PM's own two-slot lines (slot 0 Japanese, slot 1 English,
    both '【name】...'), kept only where PM is at least 98% unanimous."""
    from align import pm_table
    votes = {}
    for h in heaps:
        body = pm_table(h); d = h.d
        for ins in h.instrs:
            if ins[2] != 'CVmMsg3': continue
            b = d[ins[0]:ins[1]]
            t = 2 if b[:2] != b'\xff\xff' else 2 + 2 + 1 + b[4]
            if b[t + 12] != 2: continue
            offs = [struct.unpack_from('<I', b, t + 14 + 12 * k)[0] for k in range(2)]
            names = []
            for off in offs:
                k = body + 2 * off
                if d[k:k + 2] != b'\x10\x30': break
                e = d.find(b'\x11\x30', k)
                if e < 0 or (e - k) % 2 or e - k > 80: break
                names.append(d[k + 2:e].decode('utf-16le', 'replace'))
            if len(names) == 2:
                votes.setdefault(names[0], {}).setdefault(names[1], 0)
                votes[names[0]][names[1]] += 1
    out = {}
    for jp, c in votes.items():
        en, n = max(c.items(), key=lambda kv: kv[1])
        if n >= 0.98 * sum(c.values()): out[jp] = en
    return out


def to_pm_english(tr, jp, names=None):
    """Translation bytes -> the string for PM's English slot, or None (then the line keeps its Japanese copy)."""
    try:
        s = tr.decode('cp932')
    except UnicodeDecodeError:
        return None
    s = s.replace('\x03', '')
    for a, b in _TYPO.items(): s = s.replace(a, b)
    s = s.rstrip(' \n\x01').replace('\x01', ' ')
    s = '\n'.join(re.sub(' {2,}', ' ', x).strip(' ') for x in s.split('\n'))
    if names and jp[:2] == b'\x81\x79' and s.startswith('【') and '】' in s:
        e = jp.find(b'\x81\x7a')
        nm = jp[2:e].decode('cp932', 'replace') if e > 2 else None
        if nm in names: s = '【' + names[nm] + s[s.index('】'):]
    if not s: return None
    return s + ('\x01' if jp.endswith(b'\x01') else '')
