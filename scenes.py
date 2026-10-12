"""Scene definitions (AF instruction ranges) from the replay labels, plus dependency summary.
Boundaries: start after the CVmLabel and any leading CVmFlagOp; end before the trailing
replay-return cluster (CVmJump to the replay menu / CVmFlagOp / OM_AccessWrite)."""
import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rsaparse import Heap

HERE = os.path.dirname(os.path.abspath(__file__))
# name: (af_heap, label_instr, end_instr (exclusive, first instr of the return cluster or flag write))
RAW = {
    'yuuhi_a':   ('00003eab17', 1654, 2340),
    'yuuhi_b':   ('00003eab17', 2511, 3196),
    'kashiwagi': ('00003eab17', 4980, 5311),
    'sumika':    ('00003eab17', 7472, 7945),
    'meiya':     ('000045d98b', 1880, 2365),
    'ayamine':   ('000045d98b', 4788, 5319),
    'chizuru':   ('000045d98b', 7741, 7983),
    'miki':      ('00004cfd31', 2193, 2665),
    'mikoto':    ('00004f4791', 1803, 2227),
    'marimo_h':  ('000054cf59', 2672, 2984),
}

_heaps = {}


def heap(name):
    if name not in _heaps:
        h = Heap(open(os.path.join(os.environ.get('AFR_OUT') or os.path.join(HERE, '..', 'out'), 'af_rsa', name + '.bin'), 'rb').read(), 2); h.parse()
        _heaps[name] = h
    return _heaps[name]


def scene_range(name):
    af, lab, end = RAW[name]
    h = heap(af)
    s = lab + 1
    while h.instrs[s][2] == 'CVmFlagOp': s += 1
    e = end
    while e > s and (h.instrs[e - 1][2] in ('CVmJump', 'CVmFlagOp') or
                     (h.instrs[e - 1][2] == 'CVmGenericMsg' and h.instrs[e - 1][3] and 'Access' in h.instrs[e - 1][3][0])):
        e -= 1
    return af, s, e


def deps(name):
    af, s, e = scene_range(name)
    h = heap(af)
    kinds = collections.Counter(h.instrs[i][2] for i in range(s, e))
    objs = collections.defaultdict(set)
    for i in range(s, e):
        for x in h.ins_res[i]:
            if x and isinstance(x[0], tuple):
                objs[x[0][0]].add(x[1])
    special = [(i, h.instrs[i][2]) for i in range(s, e) if h.instrs[i][2] in ('CVmFlagOp', 'CVmJump', 'CVmLabel', 'CVmRet', 'CVmBlt')]
    return af, s, e, kinds, objs, special


if __name__ == '__main__':
    for n in RAW:
        af, s, e, kinds, objs, special = deps(n)
        print('==', n, af, [s, e], dict(kinds))
        print('   objs:', {k: len(v) for k, v in sorted(objs.items())})
        if special: print('   special:', special[:12])
