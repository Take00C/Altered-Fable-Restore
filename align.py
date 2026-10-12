"""Align an AF heap with its PM counterpart by message text; report AF-only runs as instruction ranges.
Prints structure only (counts, instruction indices, flag identifiers), never dialogue.
usage: align.py <af_heap> <pm_heap> [min_run]"""
import sys, os, re, struct, difflib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rsaparse import Heap


def norm(s):
    return re.sub(r'[\s\x00-\x1f]', '', s)


def af_messages(h):
    out = []
    for i, ins in enumerate(h.instrs):
        if ins[2] == 'CVmMsg':
            for (_, txt) in ins[5]:
                t = txt.decode('cp932', 'replace')
                if len(t) > 1:
                    out.append((i, norm(t))); break
    return out


def pm_table(h):
    """Return (body_start) of the UTF-16 text table that follows the instruction stream."""
    if getattr(h, 'tail', None):
        return h.tail['text_start']
    return h.p + 4


def pm_text_at(d, body, off):
    s = []
    k = body + 2 * off
    while k + 1 < len(d):
        c = struct.unpack_from('<H', d, k)[0]
        if c in (0, 1): break
        s.append(chr(c)); k += 2
    return ''.join(s)


def pm_messages(h):
    d = h.d; body = pm_table(h)
    out = []
    for i, ins in enumerate(h.instrs):
        if ins[2] != 'CVmMsg3': continue
        b = d[ins[0]:ins[1]]
        t = 2 if b[:2] != b'\xff\xff' else 2 + 2 + 1 + b[4]
        n1 = b[t + 12]
        if n1 < 1: continue
        off_jp = struct.unpack_from('<I', b, t + 14)[0]
        out.append((i, norm(pm_text_at(d, body, off_jp))))
    return out


FLAG = re.compile(rb'(SEE_[A-Z0-9_]+|CLEAR_[A-Z0-9_]+|[A-Z]{3,}_H(?:_[A-Z])?\b)')


def flags_in(h, i0, i1):
    lo = h.instrs[i0][0]; hi = h.instrs[i1 - 1][1]
    return sorted({m.group().decode() for m in FLAG.finditer(h.d[lo:hi])})


def align(af_path, pm_path, min_run=8):
    A = Heap(open(af_path, 'rb').read(), 2); A.parse()
    P = Heap(open(pm_path, 'rb').read(), 2); P.parse()
    am, pm = af_messages(A), pm_messages(P)
    sm = difflib.SequenceMatcher(None, [x[1] for x in am], [x[1] for x in pm], autojunk=False)
    cuts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ('delete', 'replace') and (i2 - i1) >= min_run and (i2 - i1) > 2 * (j2 - j1):
            a_start = am[i1 - 1][0] + 1 if i1 > 0 else 0
            a_end = am[i2][0] if i2 < len(am) else A.count
            p_after = pm[j1 - 1][0] + 1 if j1 > 0 else 0
            p_next = pm[j2][0] if j2 < len(pm) else P.count
            cuts.append(dict(af_range=[a_start, a_end], af_msgs=i2 - i1, pm_insert=p_after, pm_gap=[p_after, p_next],
                             pm_msgs_in_gap=j2 - j1, flags=flags_in(A, a_start, a_end)))
    return A, P, am, pm, sm.ratio(), cuts


if __name__ == '__main__':
    mr = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    A, P, am, pm, ratio, cuts = align(sys.argv[1], sys.argv[2], mr)
    print('AF msgs', len(am), 'PM msgs', len(pm), 'ratio %.3f' % ratio)
    for c in cuts:
        print(json.dumps(c, ensure_ascii=False))
