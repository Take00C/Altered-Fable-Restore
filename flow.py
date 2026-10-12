"""Control flow around an instruction in a PM heap: in-memory offsets (dw1 chain), CVmFlagOp branch targets that
land in a window, and jump targets. usage: flow.py <pm_heap> <lo> <hi>"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rsaparse import Heap
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.environ.get('AFR_OUT') or os.path.join(HERE, '..', 'out')


def base_pos(d, s):
    tag = struct.unpack_from('<H', d, s)[0]; p = s + 2
    if tag == 0xffff: p += 2; n = d[p]; p += 1 + n
    return p


def offsets(h):
    offs = [0]
    for i in range(h.count - 1):
        offs.append(struct.unpack_from('<I', h.d, base_pos(h.d, h.instrs[i][0]))[0])
    return offs


def flagop_targets(h, offs):
    inv = {o: i for i, o in enumerate(offs)}
    out = {}
    for i, ins in enumerate(h.instrs):
        if ins[2] == 'CVmFlagOp':
            t = struct.unpack_from('<I', h.d, ins[1] - 4)[0]
            out[i] = inv.get(t, ('?', t)) if t != 0xFFFFFFFF else None
    return out


if __name__ == '__main__':
    name, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    h = Heap(open(os.path.join(OUT, 'pm_rsa', name + '.bin'), 'rb').read(), 2); h.parse()
    offs = offsets(h); ft = flagop_targets(h, offs)
    into = [(src, t) for src, t in ft.items() if isinstance(t, int) and lo <= t <= hi]
    print('branches INTO [%d,%d]:' % (lo, hi), into)
    for i in range(lo, hi + 1):
        ins = h.instrs[i]
        r = [x for x in h.ins_res[i] if x and isinstance(x[0], tuple)]
        extra = ''
        if ins[2] == 'CVmFlagOp': extra = ' -> branch to %s' % (ft.get(i),)
        if ins[2] == 'CVmGenericMsg' and ins[3]: extra = ' ' + str(ins[3][0])
        print('  %5d %-16s %s%s' % (i, ins[2], ','.join('%s@%x' % (x[0][0], x[1]) for x in r[:2]), extra))
