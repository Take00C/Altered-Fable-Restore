"""Restoration blocks: AF instruction ranges to restore and the PM insertion/landing points.
block(name) -> dict(af, lo, hi, keep=[af instr indices], drop={i: reason}, pm, pm_before, land, ach)"""
import sys, os, json, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rsaparse import Heap
from align import pm_messages
from scenes import heap, scene_range
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.environ.get('AFR_OUT') or os.path.join(HERE, '..', 'out')
ACH = 0x6ac1f193
REPLAY_BOOL = 0x5915b          # AF CBool tested by the replay-return FlagOps
REPLAY_MENU = 0x3a16db         # AF replay menu heap
PM_CHAPTER_END = 0x670d5aaf    # PM chapter-end helper (reads a system-db setting, may show PM's end card, writes the db)
# (AF before-anchor, AF end (exclusive; None = to the end of the AF heap), PM heap, PM before-anchor instr)
SITES = {
    'yuuhi_a':   (1649, 2341, '01ab8c3d66', 5247),
    'yuuhi_b':   (2507, 3201, '01ab8c3d66', 5413),   # 3201: route guard (3ca72f) - what follows is Kashiwagi's route
    'kashiwagi': (4976, 5312, '01ad9ce956', 2477),   # 5312: route guard - what follows is Sumika's route
    'sumika':    (7466, 7960, '01ad9ce956', 4938),
    'meiya':     (1878, 2432, '01b30e953a', 1944),   # 2432: route guard - what follows is another route
    'ayamine':   (4771, 5326, '01b30e953a', 4441),
    'chizuru':   (7719, None, '01b8c7a482', 2220),
    'miki':      (2183, None, '01bef7a5ca', 2360),
    'mikoto':    (1801, None, '01b8c7a482', 4364),
}
CONTROL = ('CVmFlagOp', 'CVmJump', 'CVmRet', 'CVmLabel')
# PM instruction that plays the AF block's end anchor (same heap only) - never skip it
AFTER_PM = {'sumika': 4955, 'ayamine': 4479}
_pm = {}


def pmh(n):
    if n not in _pm:
        h = Heap(open(os.path.join(OUT, 'pm_rsa', n + '.bin'), 'rb').read(), 2); h.parse()
        m = {}
        for (i0, t0) in pm_messages(h): m.setdefault(i0, t0)
        _pm[n] = (h, m)
    return _pm[n]


def base_pos(d, s):
    tag = struct.unpack_from('<H', d, s)[0]; p = s + 2
    if tag == 0xffff: p += 2; n = d[p]; p += 1 + n
    return p


def af_offsets(h):
    return [0] + [struct.unpack_from('<I', h.d, base_pos(h.d, h.instrs[i][0]))[0] for i in range(h.count - 1)]


def is_ach(h, i):
    r = [x for x in h.ins_res[i] if x and isinstance(x[0], tuple)]
    return h.instrs[i][2] == 'CVmCall' and r and r[0][1] == ACH


def block(name):
    af = scene_range(name)[0]
    b, end, pn, pb = SITES[name]
    A = heap(af)
    hi = A.count if end is None else end
    offs = af_offsets(A); inv = {o: i for i, o in enumerate(offs)}
    keep, drop = [], {}
    skip_until = None
    for i in range(b + 1, hi):
        ins = A.instrs[i]
        if skip_until is not None and i < skip_until:
            drop[i] = 'replay-only path'; continue
        skip_until = None
        r = [x for x in A.ins_res[i] if x and isinstance(x[0], tuple)]
        if ins[2] == 'CVmFlagOp':
            t = struct.unpack_from('<I', A.d, ins[1] - 4)[0]
            ti = inv.get(t)
            if r and r[0][1] == REPLAY_BOOL and ti is not None and ti > i:
                skip_until = ti; drop[i] = 'replay check -> skip to %d' % ti
            else:
                drop[i] = 'branch (route logic) -> %s' % ti
            continue
        if ins[2] == 'CVmJump':
            drop[i] = 'jump %s' % (','.join('%x' % x[1] for x in r)); continue
        if ins[2] in ('CVmLabel', 'CVmRet'):
            drop[i] = ins[2]; continue
        if ins[2] == 'CVmGenericMsg' and ins[3] and 'AccessWrite' in str(ins[3][0]):
            drop[i] = 'AccessWrite (AF system flag)'; continue
        keep.append(i)
    # PM landing: just after the last PM message in (pb, stop), stop = first ACH / control instr after pb
    h, m = pmh(pn)
    # stop at the first ACH / control instruction, or at the PM line where PM resumes AF content after our block
    after_pm = AFTER_PM.get(name)
    stop = pb + 1
    while stop < h.count and not is_ach(h, stop) and h.instrs[stop][2] not in CONTROL and stop != after_pm:
        stop += 1
    msgs = [i for i in m if pb < i < stop]
    land = (max(msgs) + 1) if msgs else pb + 1
    # PM's own closing of its all-ages stand-in (between its last line and the stop) is not in the 2007 game: a CG
    # flash, a screen shake, a music change, a fade to white, or a replay of the shots our block already played
    # (2026-10-11, compared against the 2007 game). Land on the PM line that plays the AF block's end anchor when there
    # is one, otherwise on PM's chapter-end helper 670d5aaf (then the achievement call and the chapter jump).
    if after_pm is not None and stop == after_pm:
        land = after_pm
    elif stop < h.count and is_ach(h, stop):
        book = [i for i in range(land, stop) if h.instrs[i][2] == 'CVmCall'
                and any(x and isinstance(x[0], tuple) and x[1] == PM_CHAPTER_END for x in h.ins_res[i])]
        land = book[0] if book else stop
    return dict(name=name, af=af, lo=b + 1, hi=hi, keep=keep, drop=drop, pm=pn, pm_before=pb, land=land,
                stop=stop, stop_kind=('ACH' if is_ach(h, stop) else h.instrs[stop][2]) if stop < h.count else 'END',
                skipped_pm=list(range(pb + 1, land)))


if __name__ == '__main__':
    allobj = collections.Counter()
    for n in SITES:
        bl = block(n); A = heap(bl['af'])
        kinds = collections.Counter(A.instrs[i][2] for i in bl['keep'])
        oms = collections.Counter(str(A.instrs[i][3][0]) for i in bl['keep'] if A.instrs[i][2] == 'CVmGenericMsg' and A.instrs[i][3])
        h, m = pmh(bl['pm'])
        sk = bl['skipped_pm']
        sk_kinds = collections.Counter(h.instrs[i][2] for i in sk)
        sk_oms = collections.Counter(str(h.instrs[i][3][0]) for i in sk if h.instrs[i][2] == 'CVmGenericMsg' and h.instrs[i][3])
        print('== %-9s AF %s [%d,%d) keep %d drop %d | PM %s insert after %d, land %d (stop %d %s), skip %d PM instrs %s %s' % (
            n, bl['af'], bl['lo'], bl['hi'], len(bl['keep']), len(bl['drop']), bl['pm'], bl['pm_before'], bl['land'],
            bl['stop'], bl['stop_kind'], len(sk), dict(sk_kinds), dict(sk_oms)))
        print('     keep kinds', dict(kinds), 'OMs', dict(oms))
        print('     drops', sorted(set(bl['drop'].values()))[:8])


# ---------------------------------------------------------------- Marimo route (route value 10)
# (AF heap, AF range [lo, hi), PM heap, insert before PM instr, land) - FlagOps inside are kept as internal branches
MARIMO_PARTS = {
    'marimo_rung1':    ('0000514e5d', 26, 29, '01aa6fedfe', 26, 26),      # selector 1: Marimo rung (route = 10)
    'marimo_plus1':    ('00007098a5', 3269, 3270, '017b6114d2', 3736, 3736),  # Marimo affection +1 (PM dropped it)
    'marimo_chapter':  ('000054cf59', 0, 2990, '01bef7a5ca', 2427, 2427),  # the Marimo route chapter (guarded)
    'marimo_5caf15_a': ('00005caf15', 1238, 1348, '01acfa2412', 1588, 1588),  # case 10, ladder 1
    'marimo_5caf15_b': ('00005caf15', 1621, 1642, '01acfa2412', 2301, 2301),  # case 10, ladder 2
    'marimo_rung2':    ('0000514e5d', 26, 29, '01b10e10d6', 707, 707),     # PM's extra re-selection: Marimo rung
    'marimo_5fe2d7':   ('00005fe2d7', 2897, 3103, '01b10e10d6', 3117, 3117),
    'marimo_65a0db_a': ('000065a0db', 369, 376, '01b5fc732e', 374, 374),
    'marimo_65a0db_b': ('000065a0db', 657, 661, '01b5fc732e', 644, 644),
    'marimo_6953ef':   ('00006953ef', 281, 313, '01bc04eaee', 338, 338),
    'marimo_ending':   ('00006ebf77', 1850, 1851, '01c5e2de72', 1981, 1981),  # route %= 9 before the ending ladder
}


def _af_heap_all(name):
    if name not in _af_all:
        h = Heap(open(os.path.join(OUT, 'af_rsa_all', name + '.bin'), 'rb').read(), 2); h.parse(); _af_all[name] = h
    return _af_all[name]


_af_all = {}


def range_block(name):
    af, lo, hi, pn, ins_before, land = part(name)
    A = _af_heap_all(af)
    offs = af_offsets(A); inv = {o: i for i, o in enumerate(offs)}
    keep, drop = [], {}
    skip_until = None
    for i in range(lo, hi):
        ins = A.instrs[i]
        if skip_until is not None and i < skip_until:
            drop[i] = 'replay-only path'; continue
        skip_until = None
        r = [x for x in A.ins_res[i] if x and isinstance(x[0], tuple)]
        if ins[2] == 'CVmFlagOp' and r and r[0][1] == REPLAY_BOOL:
            t = inv.get(struct.unpack_from('<I', A.d, ins[1] - 4)[0])
            if t is not None and t > i:
                skip_until = t; drop[i] = 'replay check -> skip to %d' % t; continue
        if ins[2] == 'CVmJump':
            drop[i] = 'jump'; continue
        if ins[2] in ('CVmLabel', 'CVmRet'):
            drop[i] = ins[2]; continue
        if ins[2] == 'CVmGenericMsg' and ins[3] and 'AccessWrite' in str(ins[3][0]):
            drop[i] = 'AccessWrite (AF system flag)'; continue
        keep.append(i)
    return dict(name=name, af=af, lo=lo, hi=hi, keep=keep, drop=drop, pm=pn, pm_before=ins_before - 1, land=land,
                full_heap=True)


# ---------------------------------------------------------------- adult lines PM removed/rewrote outside the replay ranges
# (lead-ins/outs of the H scenes, the Myun x Chizuru scene, adult gags). From scripts/cutparts.py line alignment.
# (AF heap, AF range [lo, hi), PM heap, insert before PM instr, land): land == insert -> PM lines kept, AF lines added;
# land > insert -> PM's rewritten lines [insert, land) bypassed (checked: no ACH/control; gallery CGs shown earlier).
EXTRA_PARTS = {
    # Kasumi's adult scene, omitted from PM's 01ab8c3d66 script. Message ids match across AF/PM here: PM keeps AF lines
    # up to b371 (AF 3640 = PM 3451) and resumes at b488 (AF 3978 = PM 3457), so the cut is exactly AF [3641, 3978):
    # pre-scene transition (3641), replay label (dropped), the scene and its aftermath. PM's kept lines AF 3978-3981
    # (PM 3457-3463) still play over PM's stand-in pictures (black + overlays, one PM-only), where the 2007 game keeps
    # the scene's last CG: restored too. After AF's closing (BGM + white, 3982) the 2007 game continues to the end of
    # the route section (3991-4087, the jump at 4088 dropped); PM has none of it and goes from its own closing to the
    # achievement call: PM resumes there (3475: achievement, chapter-end helper, chapter jump).
    'kasumi_h':         ('0000514e5d', 3641, 4088, '01ab8c3d66', 3452, 3475),
    # Kasumi's lead-in, trimmed by PM (found by line alignment 2026-10-11): AF 3593-3616 (PM 3415-3429 rewritten, its
    # BGM start moved there - AF starts it at the scene, 3643) and AF 3631-3636 (PM 3447, one line).
    'x_514e5d_3593':    ('0000514e5d', 3593, 3617, '01ab8c3d66', 3415, 3430),   # replace 4 lines
    'x_514e5d_3631':    ('0000514e5d', 3631, 3637, '01ab8c3d66', 3447, 3448),   # replace 1 line
    'x_3eab17_1598':     ('00003eab17', 1598, 1608, '01ab8c3d66', 5208, 5208),   # delete 4 lines
    'x_3eab17_1624':     ('00003eab17', 1624, 1625, '01ab8c3d66', 5225, 5225),   # delete 1 lines
    'x_3eab17_2453':     ('00003eab17', 2453, 2463, '01ab8c3d66', 5370, 5370),   # delete 4 lines
    'x_3eab17_3683':     ('00003eab17', 3683, 3685, '01ad9ce956', 627, 627),   # delete 2 lines
    'x_3eab17_4068':     ('00003eab17', 4068, 4076, '01ad9ce956', 1272, 1272),   # delete 2 lines
    'x_3eab17_4090':     ('00003eab17', 4090, 4095, '01ad9ce956', 1294, 1294),   # delete 2 lines
    'x_3eab17_4548':     ('00003eab17', 4548, 4553, '01ad9ce956', 1912, 1914),   # replace 5 lines
    'x_3eab17_4957':     ('00003eab17', 4957, 4960, '01ad9ce956', 2449, 2449),   # delete 3 lines
    'x_3eab17_4963':     ('00003eab17', 4963, 4967, '01ad9ce956', 2458, 2459),   # replace 4 lines
    'x_3eab17_4970':     ('00003eab17', 4970, 4974, '01ad9ce956', 2472, 2472),   # delete 2 lines
    'x_3eab17_5688':     ('00003eab17', 5688, 5691, '01ad9ce956', 2959, 2962),   # replace 1 lines
    'x_3eab17_7099':     ('00003eab17', 7099, 7104, '01ad9ce956', 4560, 4567),   # replace 5 lines
    'x_3eab17_7397':     ('00003eab17', 7397, 7400, '01ad9ce956', 4891, 4892),   # replace 3 lines
    'x_3eab17_7414':     ('00003eab17', 7414, 7421, '01ad9ce956', 4906, 4906),   # delete 4 lines
    'x_3eab17_7449':     ('00003eab17', 7449, 7465, '01ad9ce956', 4934, 4934),   # delete 13 lines
    'x_45d98b_1809':     ('000045d98b', 1809, 1842, '01b30e953a', 1906, 1906),   # delete 16 lines
    'x_45d98b_1845':     ('000045d98b', 1845, 1846, '01b30e953a', 1913, 1914),   # replace 1 lines
    'x_45d98b_1854':     ('000045d98b', 1854, 1855, '01b30e953a', 1922, 1922),   # delete 1 lines
    'x_45d98b_3736':     ('000045d98b', 3736, 3740, '01b30e953a', 3377, 3377),   # delete 1 lines
    'x_45d98b_4644':     ('000045d98b', 4644, 4647, '01b30e953a', 4332, 4332),   # delete 3 lines
    'x_45d98b_4678':     ('000045d98b', 4678, 4691, '01b30e953a', 4363, 4374),   # replace 6 lines
    'x_45d98b_4723':     ('000045d98b', 4723, 4739, '01b30e953a', 4406, 4408),   # replace 10 lines
    'x_45d98b_5333':     ('000045d98b', 5333, 5371, '01b30e953a', 4486, 4496),   # replace 18 lines
    'x_45d98b_5704':     ('000045d98b', 5704, 5705, '01b8c7a482', 260, 261),   # replace 1 lines
    'x_45d98b_5726':     ('000045d98b', 5726, 5727, '01b8c7a482', 285, 285),   # delete 1 lines
    'x_45d98b_7302':     ('000045d98b', 7302, 7307, '01b8c7a482', 1975, 1975),   # delete 3 lines
    'x_45d98b_7354':     ('000045d98b', 7354, 7356, '01b8c7a482', 2036, 2036),   # delete 2 lines
    'x_45d98b_7366':     ('000045d98b', 7366, 7382, '01b8c7a482', 2050, 2053),   # replace 11 lines
    'x_45d98b_7384':     ('000045d98b', 7384, 7475, '01b8c7a482', 2058, 2063),   # replace 52 lines
    'x_45d98b_7477':     ('000045d98b', 7477, 7588, '01b8c7a482', 2068, 2073),   # replace 70 lines
    'x_45d98b_7593':     ('000045d98b', 7593, 7596, '01b8c7a482', 2084, 2094),   # replace 3 lines
    'x_45d98b_7601':     ('000045d98b', 7601, 7612, '01b8c7a482', 2101, 2101),   # delete 10 lines
    'x_45d98b_7644':     ('000045d98b', 7644, 7652, '01b8c7a482', 2137, 2137),   # delete 4 lines
    'x_45d98b_7674':     ('000045d98b', 7674, 7675, '01b8c7a482', 2172, 2172),   # delete 1 lines
    'x_4cfd31_1620':     ('00004cfd31', 1620, 1621, '01bef7a5ca', 1797, 1798),   # replace 1 lines
    'x_4cfd31_2031':     ('00004cfd31', 2031, 2039, '01bef7a5ca', 2214, 2215),   # replace 4 lines
    'x_4cfd31_2066':     ('00004cfd31', 2066, 2085, '01bef7a5ca', 2247, 2265),   # replace 7 lines
    'x_4cfd31_2142':     ('00004cfd31', 2142, 2153, '01bef7a5ca', 2323, 2335),   # replace 4 lines
    'x_4cfd31_2165':     ('00004cfd31', 2165, 2166, '01bef7a5ca', 2347, 2348),   # replace 1 lines
    'x_4cfd31_2169':     ('00004cfd31', 2169, 2182, '01bef7a5ca', 2351, 2359),   # replace 11 lines
    'x_4f4791_185':      ('00004f4791', 185, 198, '01b8c7a482', 2547, 2547),   # delete 6 lines
    'x_4f4791_289':      ('00004f4791', 289, 303, '01b8c7a482', 2704, 2705),   # replace 6 lines
    'x_4f4791_322':      ('00004f4791', 322, 325, '01b8c7a482', 2731, 2731),   # delete 1 lines
    'x_4f4791_332':      ('00004f4791', 332, 333, '01b8c7a482', 2740, 2740),   # delete 1 lines
    'x_4f4791_1649':     ('00004f4791', 1649, 1655, '01b8c7a482', 4211, 4211),   # delete 6 lines
    'x_4f4791_1666':     ('00004f4791', 1666, 1670, '01b8c7a482', 4222, 4223),   # replace 4 lines
    'x_4f4791_1674':     ('00004f4791', 1674, 1702, '01b8c7a482', 4228, 4228),   # delete 17 lines
    'x_4f4791_1762':     ('00004f4791', 1762, 1767, '01b8c7a482', 4316, 4320),   # replace 3 lines
    'x_6b9fa1_2244':     ('00006b9fa1', 2244, 2278, '01715ad2b6', 2393, 2410),   # replace 19 lines
    # island free-roam event PM dropped entirely: Yuuko & Marimo's cottage room (map location 6 on the arrival day),
    # played as Takeru sets off to wander (end of PM's arrival-day script, right before its jump to the picker)
    'x_7cea05_1276':     ('00007cea05', 1276, 1429, '01907a78fe', 823, 823),     # event 57 lines
}


def part(name):
    return MARIMO_PARTS.get(name) or EXTRA_PARTS[name]
