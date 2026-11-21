"""PM's EXTRAS > Gallery, AF tab: the Altered Fable 2007 entries PM's gallery lacks (build_all F30 GALADD, F31 GALPM,
F32 CG4721). Data tables, the gallery heaps' inline inserts and the picture jobs. Pure Python, run on the player's files
at patch time; no picture data ships with the tool.

Evidence (numbers only, no picture looked at): lab-tools/out/research/gallery-add (skeptic_result.json, impl/pre-nav,
impl/pre-inventory, impl/impl). Instruction indexes below are PM's (heap@index).

The AF tab is three PM heaps that index one entry list by the running counter of an unrolled chain:
  00d5836b7e (register, CRsa 6ac1b5c1(tab, idx)): per entry 'counter == idx ?' then OM_GetCgRegisterByDatabase on the
    entry's story picture (an OR of a second picture, or a CStdb flag through 5cc2ec3f, where PM has one), result in
    CInt 27b4f007; tab 0 = [3, 268)
  00d5994f52 (tiles, CRsa 6acca7ab): per entry 'counter == idx ?' then 323dbd9b(.., thumbnail 210x123, ..); locked
    tiles jump past the chain (@2 / @5 -> 268) and show only the background 92829ae3; tab 0 = [7, 268)
  00ba7f84ba (pages and full view): the count @924 (85), the page / title / button drawing, the select (324f2e3f:
    OM_AskUserSelectEx), the click map @1971-2048 and the view chain [2051, 2562): per entry 'counter == idx ?' then
    6acd5cb3(CImgAreaBox 454c9, #1 / #2 copy (1280-wide) ... / #3)
New entries are appended in AF 2007's order (AF tab index 85 on). Every inserted instruction is a byte clone of an
instruction of the same heap (only the fields named in its spec change: next / target, id, op, constants, the new
picture's key and size, an index operand), and every insert is NON-CAPTURING: only the fall-through of the instruction
before it enters it; every other next or branch that pointed at the instruction after it still points there (the
writer remaps each original target to the same original instruction). The register heap's new blocks need its flag
read (5cc2ec3f), first defined after tab 0's chain, so they sit after its first closing CVmRet @755 (no fall-through)
and are entered by @267's next (its only change), leaving to @268. With every fix off nothing here runs and the
three heaps stay PM's (not in the patch).

The gallery heap writer (write_heap) re-emits a parsed heap with heapwriter.Slicer (load-array indexes renumbered as
patch_pm does) and emits the clones in the output's own index space: a class or object the template references becomes
the output's index of the same entry, a GenericMsg's OM instance (and any other anonymous load-array entry the engine
appends while reading it) gets a new entry, a new picture is a new explicit reference (a new entry). The result is
re-parsed and checked: every original instruction resolves to exactly its original references, every clone to its
template's with the listed changes, the load array has the size the writer counted, the tail is unchanged."""
import struct
from builder import BuildError
from rsaparse import Heap
from heapwriter import Slicer

K = 0xA2FB6AD1
M = 0xFFFFFFFF
REG, TILE, VIEW = '00d5836b7e', '00d5994f52', '00ba7f84ba'
STORY = '01b8c7a482'                 # F32: the PM site heap of AF 45d98b [7612, 7644) (PM [2101, 2137))
CHAIN_SRC = ('00b94df0aa', 112)      # the explicit chain CObjectOcean 5d35f8c5 (C108) > 27b4ea1b (C308) > pad2

# ---------------------------------------------------------------- the entries (AF 2007 gallery heap 0000390163)
# F30 GALADD: AF entries of restored scenes. (name = AF page/slot, key CG (AF off, size), its size, views (AF off, size,
# W, H)). The key CG is the tile and the unlock picture; unlock = the CStdb flag 'AFR_GAL_<name>' (written right after
# every display of the key CG's import in the restored parts) OR the register of that import (explicit chain
# Cr6Ti > CObjectOcean 5d35f8c5 > CObjectOcean 27b4ea1b > pad2, the import's node chain: CHAIN_SRC's form).
GALADD_ENTRIES = (
    ('P1S4', 0x3979454b, 2032480, (2604, 2816), [(0x3979454b, 2032480, 2604, 2816), (0x3ad4ec0f, 2037992, 2604, 2816), (0x3af404fb, 2031546, 2604, 2816), (0x3b1304b9, 2037956, 2604, 2816), (0x3b321d81, 2067318, 2604, 2816), (0x3b51a8fb, 2062692, 2604, 2816), (0x3b712263, 2054872, 2604, 2816), (0x3b907d3f, 2061286, 2604, 2816)]),
    ('P1S5', 0x399848b3, 1873620, (2604, 1836), [(0x399848b3, 1873620, 2604, 1836), (0x3baff129, 1868588, 2604, 1836), (0x3bcc7459, 1866934, 2604, 1836), (0x3be8f113, 1866024, 2604, 1836), (0x3c056a3f, 1904206, 2604, 1836), (0x3c227891, 1897518, 2604, 1836), (0x3c3f6cc3, 1896610, 2604, 1836)]),
    ('P1S11', 0x3a097d55, 1373990, (2604, 1838), [(0x3a097d55, 1373990, 2604, 1838), (0x3ce3beff, 1374066, 2604, 1838), (0x3cf8b675, 1364706, 2604, 1838), (0x3d0d895b, 1364780, 2604, 1838), (0x3d225c8b, 1322438, 2604, 1838), (0x3d368a55, 1320094, 2604, 1838), (0x3d4aaef7, 1313228, 2604, 1838), (0x3d5eb8c7, 1313152, 2604, 1838), (0x3d72c24b, 1322352, 2604, 1838), (0x3d86efbf, 1331640, 2604, 1838)]),
    ('P1S12', 0x3a1e747f, 1151810, (2604, 1838), [(0x3a1e747f, 1151810, 2604, 1838), (0x3d9b417b, 1152432, 2604, 1838), (0x3dacd72f, 1154364, 2604, 1838), (0x3dbe746f, 1143672, 2604, 1838), (0x3dcfe7eb, 1144292, 2604, 1838), (0x3de15dd3, 1146060, 2604, 1838), (0x3df2daa3, 1162998, 2604, 1838)]),
    ('P2S10', 0x3f2f15f7, 1280324, (2604, 1838), [(0x3f2f15f7, 1280324, 2604, 1838), (0x3fab2e47, 1286232, 2604, 1838), (0x3fbecea3, 1286772, 2604, 1838), (0x3fd2711b, 1283756, 2604, 1838), (0x3fe607cb, 1284090, 2604, 1838), (0x3ff99fc9, 1286504, 2604, 1838), (0x400d4135, 1286600, 2604, 1838), (0x4020e301, 1283572, 2604, 1838), (0x403478f9, 1283934, 2604, 1838), (0x4048105b, 1287902, 2604, 1838), (0x405bb73d, 1285494, 2604, 1838), (0x406f54b7, 1285898, 2604, 1838), (0x4082f3c5, 1261472, 2604, 1838), (0x40963369, 1257622, 2604, 1838), (0x40a96403, 1267794, 2604, 1838), (0x40bcbc59, 1268358, 2604, 1838), (0x40d016e3, 1265320, 2604, 1838), (0x40e3658f, 1265688, 2604, 1838)]),
    ('P2S11', 0x3f429f3f, 1579808, (2604, 1938), [(0x3f429f3f, 1579808, 2604, 1938), (0x40f6b5ab, 1579192, 2604, 1938), (0x410ece67, 1581040, 2604, 1938), (0x4126ee5b, 1578796, 2604, 1938), (0x413f058b, 1580038, 2604, 1938), (0x41572195, 1582996, 2604, 1938), (0x416f492d, 1580752, 2604, 1938), (0x41876801, 1581992, 2604, 1938), (0x419f8bad, 1601446, 2604, 1938), (0x41b7fb57, 1601736, 2604, 1938)]),
    ('P3S9', 0x42bceb6d, 1523408, (2604, 1838), [(0x42bceb6d, 1523408, 2604, 1838), (0x4369c16b, 1525118, 2604, 1838), (0x438106ed, 1523952, 2604, 1838), (0x439847e1, 1529506, 2604, 1838), (0x43af9e87, 1531186, 2604, 1838), (0x43c6fbbd, 1530034, 2604, 1838), (0x43de5473, 1532898, 2604, 1838), (0x43f5b859, 1534490, 2604, 1838), (0x440d2277, 1533348, 2604, 1838), (0x4424881f, 1540568, 2604, 1838), (0x443c09fb, 1539444, 2604, 1838)]),
    ('P3S10', 0x42d42a41, 1318542, (2604, 1838), [(0x42d42a41, 1318542, 2604, 1838), (0x44538773, 1318472, 2604, 1838), (0x4467a5bf, 1314970, 2604, 1838), (0x447bb65d, 1326468, 2604, 1838)]),
    ('P3S11', 0x42e848d3, 2143248, (2604, 3677), [(0x42e848d3, 2143248, 2604, 3677), (0x448ff3e5, 2143200, 2604, 3677), (0x44b0a7c9, 2143788, 2604, 3677), (0x44d15df9, 2176044, 2604, 3677), (0x44f29229, 2176562, 2604, 3677), (0x4513c85f, 2175476, 2604, 3677)]),
    ('P4S5', 0x45a09107, 2522042, (2604, 1838), [(0x45a09107, 2522042, 2604, 1838), (0x474c6923, 2532156, 2604, 1838), (0x47730c63, 2523110, 2604, 1838), (0x47998c4d, 2524052, 2604, 1838), (0x47c00fe5, 2533226, 2604, 1838), (0x47e6b753, 2533900, 2604, 1838), (0x480d6163, 2533358, 2604, 1838)]),
    ('P4S9', 0x45fa97d3, 936834, (2604, 1838), [(0x45fa97d3, 936834, 2604, 1838), (0x4839886b, 935334, 2604, 1838), (0x4847ce15, 936534, 2604, 1838), (0x4856186f, 931528, 2604, 1838), (0x48644f3b, 930028, 2604, 1838), (0x4872802b, 944146, 2604, 1838), (0x4880e841, 949930, 2604, 1838), (0x488f66ef, 951300, 2604, 1838)]),
    ('P4S10', 0x4608e359, 1577016, (2604, 1838), [(0x4608e359, 1577016, 2604, 1838), (0x489deaf7, 1576056, 2604, 1838), (0x48b5f773, 1575014, 2604, 1838), (0x48cdffdd, 1574096, 2604, 1838), (0x48e604b1, 1587452, 2604, 1838), (0x48fe3db1, 1584556, 2604, 1838), (0x49166b61, 1598100, 2604, 1838), (0x492ecdf9, 1593982, 2604, 1838)]),
    ('P5S2', 0x4951fb2f, 1467436, (2604, 1838), [(0x4951fb2f, 1467436, 2604, 1838), (0x4a99b955, 1468250, 2604, 1838), (0x4ab020b3, 1462348, 2604, 1838), (0x4ac67103, 1463198, 2604, 1838)]),
    ('P5S3', 0x49685f5f, 1610544, (2604, 1838), [(0x49685f5f, 1610544, 2604, 1838), (0x4adcc4a5, 1609396, 2604, 1838), (0x4af5535d, 1608798, 2604, 1838), (0x4b0ddfbf, 1607642, 2604, 1838), (0x4b26679d, 1620714, 2604, 1838), (0x4b3f228b, 1617810, 2604, 1838)]),
    ('P5S6', 0x49cbd43d, 2148196, (2604, 1838), [(0x49cbd43d, 2148196, 2604, 1838), (0x4c80b343, 2145362, 2604, 1838), (0x4ca16f99, 2143474, 2604, 1838), (0x4cc2248f, 2140504, 2604, 1838), (0x4ce2cdeb, 2179152, 2604, 1838), (0x4d040e3f, 2176180, 2604, 1838)]),
    ('P5S9', 0x4a062295, 1326572, (2604, 1838), [(0x4a062295, 1326572, 2604, 1838), (0x4d5856f1, 1324650, 2604, 1838), (0x4d6c8d5f, 1327554, 2604, 1838), (0x4d80cf25, 1329048, 2604, 1838), (0x4d9516c1, 1364718, 2604, 1838), (0x4da9e9b3, 1380240, 2604, 1838)]),
    ('P5S10', 0x4a1a6085, 1628242, (2604, 1838), [(0x4a1a6085, 1628242, 2604, 1838), (0x4dbef947, 1629812, 2604, 1838), (0x4dd7d7bf, 1624224, 2604, 1838), (0x4df0a063, 1622630, 2604, 1838), (0x4e0962cd, 1655324, 2604, 1838), (0x4e22a4ed, 1657110, 2604, 1838)]),
    # p6s4: its key CG 4e806001 is not one of its views (AF's tile picture only): its 1280-wide resize is made for the
    # thumbnail and not stored
    ('P6S4', 0x4e806001, 2319066, (2604, 2522), [(0x4f5b7ef9, 2318280, 2604, 2522), (0x4f7edec5, 2319134, 2604, 2522), (0x4fa241e7, 2320204, 2604, 2522), (0x4fc5a937, 2372970, 2604, 2522), (0x4fe9dea5, 2316134, 2604, 2522), (0x500d360f, 2365830, 2604, 2522), (0x50314f99, 2371044, 2604, 2522), (0x50557d81, 2370842, 2604, 2522), (0x5079aa9f, 2330664, 2604, 2522), (0x509d3acb, 2385574, 2604, 2522), (0x50c1a175, 2384510, 2604, 2522), (0x50e603f7, 2392432, 2604, 2522), (0x510a856b, 2389240, 2604, 2522)]),
    ('P6S5', 0x4ea3c2df, 1833332, (2604, 1838), [(0x4ea3c2df, 1833332, 2604, 1838), (0x512efa67, 1831596, 2604, 1838), (0x514aed17, 1831166, 2604, 1838), (0x5166de19, 1828144, 2604, 1838), (0x5182c34d, 1828154, 2604, 1838), (0x519ea88b, 1889794, 2604, 1838)]),
    ('P7S2', 0x5220d965, 1171054, (2604, 1838), [(0x5220d965, 1171054, 2604, 1838)]),
    ('P7S3', 0x5232b7d7, 1347308, (2604, 1838), [(0x5232b7d7, 1347308, 2604, 1838)]),
    ('P7S5', 0x526605a5, 1902534, (2604, 1838), [(0x526605a5, 1902534, 2604, 1838)]),
    ('P10S10', 0x56461497, 1646796, (2604, 1838), [(0x56461497, 1646796, 2604, 1838), (0x57dd36af, 1640168, 2604, 1838)]),
)
# F31 GALPM: AF entries of pictures PM's story keeps but its gallery dropped (AF page 9 and p8s10). (name, key CG (AF off,
# size), its size, PM story object (off, size; byte-identical body), the PM folder its story reference hangs under,
# views). Unlock = the register of PM's own story object with the story's chain (Cr6Ti > folder > 32749557 > 32749559 >
# 453c7 > pad3), like PM's own entries; the folders are in 00d5836b7e's load array (checked).
GALPM_ENTRIES = (
    ('P8S10', 0x53782951, 304156, (1024, 600), 0x5ca47b0d, 304155, 0x5ca6cd1d, [(0x53782951, 304156, 1024, 600)]),
    ('P9S1', 0x2fe869ff, 82328, (2176, 1536), 0x87d14c2b, 82327, 0x327c5201, [(0x2fe869ff, 82328, 2176, 1536), (0x2fe9ab9b, 87758, 2176, 1536), (0x2feb026d, 79904, 2176, 1536), (0x54a75d51, 87758, 2176, 1536), (0x2fec3ad1, 145340, 2176, 1536), (0x2fee72d1, 176480, 2176, 1536), (0x2ff12435, 168202, 2176, 1536), (0x2ff3b543, 121444, 2176, 1536), (0x2ff58fab, 88048, 2176, 1536), (0x54a8b423, 89614, 2176, 1536), (0x2ff6e7db, 95206, 2176, 1536)]),
    ('P9S2', 0x36f7c8df, 2351516, (2344, 1654), 0x96914653, 2351515, 0x327c5201, [(0x36f7c8df, 2351516, 2344, 1654), (0x371baabf, 2346024, 2344, 1654), (0x373f7727, 2427260, 2344, 1654)]),
    ('P9S3', 0x539573ff, 2183864, (2604, 1838), 0x9d602b2d, 2183863, 0x327c5201, [(0x539573ff, 2183864, 2604, 1838)]),
    ('P9S4', 0x53b6c6bb, 2134832, (2604, 1838), 0xa243f357, 2134831, 0x327c5201, [(0x53b6c6bb, 2134832, 2604, 1838)]),
    ('P9S5', 0x53d759ef, 2944554, (2246, 1588), 0xafd9db8b, 2944553, 0x327a843d, [(0x53d759ef, 2944554, 2246, 1588)]),
    ('P9S6', 0x5404481d, 1114292, (2604, 1838), 0xbf24e7f3, 1114291, 0x327a843d, [(0x5404481d, 1114292, 2604, 1838), (0x54aa1235, 1113868, 2604, 1838)]),
    ('P9S7', 0x541548d5, 958740, (2604, 1838), 0xbf4010f3, 958739, 0x327a843d, [(0x541548d5, 958740, 2604, 1838), (0x54bb1145, 959294, 2604, 1838)]),
    ('P9S8', 0x5423e9ed, 1178416, (2604, 1838), 0xbf600ca1, 1178415, 0x327a843d, [(0x5423e9ed, 1178416, 2604, 1838)]),
    ('P9S9', 0x5435e521, 929280, (2604, 1838), 0xb7dbaad5, 929279, 0x327a843d, [(0x5435e521, 929280, 2604, 1838), (0x54c9b487, 929418, 2604, 1838), (0x54d7e315, 930134, 2604, 1838), (0x54e6146f, 930434, 2604, 1838), (0x54f446f5, 930126, 2604, 1838), (0x55027847, 844598, 2604, 1838)]),
    ('P9S10', 0x54441325, 868994, (2604, 1838), 0xb7d50993, 868993, 0x327a843d, [(0x54441325, 868994, 2604, 1838)]),
    ('P9S11', 0x545155ab, 2061990, (2604, 1838), 0xb80e91d1, 2061989, 0x327a843d, [(0x545155ab, 2061990, 2604, 1838)]),
    ('P9S12', 0x5470cc55, 957340, (2604, 1838), 0xbb018f89, 957339, 0x327a843d, [(0x550f5b81, 945832, 2604, 1838), (0x551dca2d, 951498, 2604, 1838), (0x552c4efb, 958108, 2604, 1838), (0x5470cc55, 957340, 2604, 1838)]),
    ('P9S13', 0x547f67f5, 823082, (2604, 1838), 0xbb421a35, 823081, 0x327a843d, [(0x547f67f5, 823082, 2604, 1838), (0x553aed9b, 800738, 2604, 1838)]),
    ('P9S14', 0x548bf723, 752372, (2604, 1838), 0xbb5e4e75, 752371, 0x327a843d, [(0x548bf723, 752372, 2604, 1838), (0x55472581, 765522, 2604, 1838), (0x5552d3d7, 752534, 2604, 1838), (0x555e4f71, 765684, 2604, 1838)]),
    ('P9S15', 0x5497721b, 1043250, (2604, 1838), 0xbf4eb31f, 1043249, 0x327a843d, [(0x5497721b, 1043250, 2604, 1838), (0x5569fe69, 1230798, 2604, 1838)]),
)
# the AF tab's new indexes in AF 2007's page / slot order (index 85 on): F30's p1s4 .. p7s5, F31's p8s10 and page 9,
# F30's p10s10. With one fix off its entries are left out and the later ones move down (indexes are runtime only).
ORDER = ('P1S4', 'P1S5', 'P1S11', 'P1S12', 'P2S10', 'P2S11', 'P3S9', 'P3S10', 'P3S11', 'P4S5', 'P4S9', 'P4S10',
         'P5S2', 'P5S3', 'P5S6', 'P5S9', 'P5S10', 'P6S4', 'P6S5', 'P7S2', 'P7S3', 'P7S5', 'P8S10', 'P9S1', 'P9S2',
         'P9S3', 'P9S4', 'P9S5', 'P9S6', 'P9S7', 'P9S8', 'P9S9', 'P9S10', 'P9S11', 'P9S12', 'P9S13', 'P9S14',
         'P9S15', 'P10S10')
PM_COUNT = 85                        # PM's AF-tab entries (the count @924)
# AF frames missing inside PM's own entries (view chain): (PM entry, fix, after instruction, frames (AF off, size, W, H),
# window). Entry 31's 4 copies are AF frames 1 / 3 / 5 / 6 (0.1.1's pixel proof): AF's order is kept by inserting after
# @2251 (frame 1), @2252 (3) and @2254 (6); 4721aabf (frame 8) only with F32, which restores its story display. Entry
# 37: PM's copies are AF frames 1-4 (variant-region test), frames 5-8 follow. Entry 47: 332d80df (PM's only copy is
# 330b2021). Entry 64: 538c23f5, gated like 2007 (390163@1841) on the CStdb key GATE64 that PM itself writes at
# 017b6114d2@4134 right before it shows 538c23f5's twin 3278aaa1 (@4135).
_TALL = (1280 / 2604, 953 / 1939, 0, 219)      # PM's 16:9 window of the tall 2604x3677 frames (as 0.1.1's _TALL_G)
VARIANTS = (
    (31, 'galadd', 2251, ((0x4620f395, 2798134, 2604, 3677),), _TALL),
    (31, 'galadd', 2252, ((0x46768397, 2796886, 2604, 3677),), _TALL),
    (31, 'galadd', 2254, ((0x46f6f13b, 2800000, 2604, 3677),), _TALL),
    (31, 'cg4721', 2254, ((0x4721aabf, 2801248, 2604, 3677),), _TALL),
    (37, 'galadd', 2288, ((0x4bd6b69d, 2785218, 2604, 1836), (0x4c013663, 2786036, 2604, 1836),
                          (0x4c2bb95b, 2784106, 2604, 1836), (0x4c5634c9, 2784886, 2604, 1836)), None),
    (47, 'galpm', 2344, ((0x332d80df, 1151876, 2604, 1838),), None),
    (64, 'galpm', 2442, ((0x538c23f5, 605124, 2176, 1536),), None),
)
GATE64 = 'SEE_WOKEN_MEMO_CG_YUKO_MANA_TUIKA'
GATE64_SRC = ('017b6114d2', 4134)    # PM's OM_AccessWrite of that key (its first string, checked)
GATE_IDX = 999                       # the register heap's pseudo entry for the gate: an index no tile / click / ACH asks
# F32 CG4721: AF 45d98b@7626-7628 (2007 and the official update show 4721aabf there; PM dropped the shot and has no
# object for it): one import and a non-capturing 3-instruction insert after PM 01b8c7a482@2119 (the bgm = AF 7625),
# cloned from @2115-2117 (picture 27e92633(.., #2), camera 27e92e99, transition 27e9379d) with AF's values
CG4721_AF = (0x4721aabf, 2801248)
CG4721_AT = 2119
CG4721_CAM = (100, -279, 0, 1752, 1, 0)        # AF 7627 d13d87 (the exact rule: 2007's values)
CG4721_TRANS = (0, 100)                        # AF 7628 d14fbb

# ---------------------------------------------------------------- ids and keys (one range per fix)
ID_RANGES = (('GALFLAG', 0x3F360, 0x3F3F0), ('CG4721', 0x3F3F0, 0x3F400), ('GALADD', 0x3F920, 0x3FB10),
             ('GALPM', 0x3FB10, 0x3FBF0), ('GALNAV', 0x3FBF0, 0x3FC00))
KEY_RANGES = (('GALADD', 0x7FB00000, 0x7FB80000), ('GALPM', 0x7FB80000, 0x7FBF0000), ('CG4721', 0x7FBF0000, 0x7FC00000))
FIX_OF_RANGE = {'galadd': 'GALADD', 'galpm': 'GALPM', 'cg4721': 'CG4721', 'nav': 'GALNAV', 'flag': 'GALFLAG'}

# ---------------------------------------------------------------- pictures
COPY_FLAG, THUMB_FLAG, DEPTH = 0x00810602, 0x00810303, 0x07070707
COPY_TPL = (0x6e11a8c7, 668095)      # a PM AF-tab copy (00ba7f84ba@2557): its header bytes, w0 / h0 / w / h set
THUMB_TPL = (0x9297b653, 23063)      # a PM AF-tab thumbnail (00d5994f52@266)
TW, TH = 210, 123


def flag_name(name):
    return 'AFR_GAL_' + name


def copy_size(W, H):
    """PM's gallery copy of a whole AF picture: 1280 wide, round(1280 H / W) high (fits 117 of PM's 121 copy / source
    pairs; 1838 -> 903, 1836 -> 902)."""
    return 1280, int(1280 * H / W + 0.5)


def copy_window(W, H):
    ow, oh = copy_size(W, H)
    return (ow / W, oh / H, 0, 0), ow, oh


def thumb_window(oh):
    """The 210x123 thumbnail of a 1280-wide copy oh rows high: PM's 1280x750 window (kx = 210 / 1280, ky = 123 / 750) at
    x0 = 0, y0 = R / ky, R = min(12, floor((oh ky - 123) / 2)) whole thumbnail rows (12 rows = PM's offset on all 19 of
    its indexes 66-84; 0 for a 750-row copy)."""
    kx, ky = TW / 1280, TH / 750
    R = min(12, (TH * (oh - 750)) // 1500)            # floor((oh ky - 123) / 2) in integers
    if R < 0: raise BuildError('thumbnail: copy of %d rows is shorter than the window' % oh)
    return (kx, ky, 0, R / ky)


def _pic_ok(win, ow, oh, W, H):
    """The window reads inside the AF picture (build_all._pic_extent_ok's rule)."""
    kx, ky, x0, y0 = win
    return -2 <= x0 and -2 <= y0 and x0 + ow / kx <= W + 2 and y0 + oh / ky <= H + 2


def picture_header(tpl_body, w, h, flag):
    """A plain Cr6Ti body of w x h with no data, from PM's template body: PM's header bytes with w0 / h0 / w / h set (the
    only fields that differ between PM's AF-tab copies / thumbnails; checked against PM's uniform form), data size 0."""
    import cgcrop
    hd = cgcrop.header(tpl_body)
    p = hd['size_pos']
    if p != 30 or hd['flag'] != flag or hd['depth'] != DEPTH or hd['w'] != hd['w0'] or hd['h'] != hd['h0']:
        raise BuildError('picture template: unexpected header %r' % hd)
    hdr = bytearray(tpl_body[:p])
    struct.pack_into('<HH', hdr, 4, w, h); struct.pack_into('<HH', hdr, 12, w, h)
    want = (b'\x45\x00\x00\x00' + struct.pack('<HH', w, h) + bytes(4) + struct.pack('<HH', w, h)
            + struct.pack('<II', flag, DEPTH) + bytes.fromhex('000800060000'))
    if bytes(hdr) != want: raise BuildError('picture template: header is not PM\'s uniform AF-tab form')
    body = bytes(hdr) + struct.pack('<I', 0) + tpl_body[p + 4:p + 12] + tpl_body[-2:]
    if tpl_body[p + 4:p + 12] != bytes(8) or tpl_body[-2:] != bytes(2):
        raise BuildError('picture template: scale / trailer not zero')
    h2 = cgcrop.header(body)
    if (h2['w'], h2['h'], h2['w0'], h2['h0'], h2['flag'], h2['size_pos'], h2['data_size']) != (w, h, w, h, flag, 30, 0):
        raise BuildError('picture template: rebuilt header reads back wrong')
    return body


# ---------------------------------------------------------------- the switches' plan
def plan(fix30, fix31, fix32, skip=()):
    """The entries / variants in the build: (rows, variants), rows = [(index, name, group, entry tuple)]; skip: entry
    names left out (a build whose parts never show their key CG: no unlock is possible)."""
    a = {e[0]: e for e in GALADD_ENTRIES}; p = {e[0]: e for e in GALPM_ENTRIES}
    if set(ORDER) != set(a) | set(p) or set(a) & set(p) or len(ORDER) != 39: raise BuildError('galadd ORDER')
    rows = []
    for n in ORDER:
        if n in skip: continue
        if n in a and fix30: rows.append((PM_COUNT + len(rows), n, 'galadd', a[n]))
        if n in p and fix31: rows.append((PM_COUNT + len(rows), n, 'galpm', p[n]))
    var = [v for v in VARIANTS if (v[1] == 'galadd' and fix30) or (v[1] == 'galpm' and fix31)
           or (v[1] == 'cg4721' and fix30 and fix32)]
    return rows, var


def picture_plan(rows, variants, keys):
    """The new pictures and their keys, in key order (per fix: each entry's copies, then its thumbnail; then the
    variant frames). copies: dicts label, key (None: not stored), af (off, size, W, H), win, ow, oh, fix; thumbs:
    dicts name, key, src (the copy label it is made from: the key CG's copy), fix."""
    copies, thumbs = [], []
    for idx, name, grp, e in rows:
        src = None
        for n, v in enumerate(e[-1]):
            win, ow, oh = copy_window(v[2], v[3])
            copies.append(dict(label=(name, n), key=keys.next(grp), af=v, win=win, ow=ow, oh=oh, fix=grp))
            if v[0] == e[1] and src is None: src = (name, n)
        if src is None:                  # the key CG is not one of the views (p6s4): its resize for the thumbnail only
            W, H = e[3]; win, ow, oh = copy_window(W, H)
            copies.append(dict(label=(name, 'key'), key=None, af=(e[1], e[2], W, H), win=win, ow=ow, oh=oh, fix=grp))
            src = (name, 'key')
        thumbs.append(dict(name=name, key=keys.next(grp), src=src, fix=grp))
    for pm_e, fx, after, frames, win in variants:
        for fr in frames:
            if win is None: w_, ow, oh = copy_window(fr[2], fr[3])
            else: w_, ow, oh = win, 1280, 953
            copies.append(dict(label=('var', pm_e, fr[0]), key=keys.next(fx), af=fr, win=w_, ow=ow, oh=oh, fix=fx))
    return copies, thumbs


class Ids:
    """Per-fix id counters inside their ID_RANGES; next(fix) -> id."""
    def __init__(self):
        self.c = {nm: lo for nm, lo, hi in ID_RANGES}; self.hi = {nm: hi for nm, lo, hi in ID_RANGES}
        self.lo = {nm: lo for nm, lo, hi in ID_RANGES}

    def next(self, fix):
        nm = FIX_OF_RANGE[fix]; i = self.c[nm]
        if i >= self.hi[nm]: raise BuildError('galadd: id range %s full' % nm)
        self.c[nm] += 1
        return i

    def used(self):
        return {nm: (self.lo[nm], self.c[nm]) for nm in self.c}


class Keys:
    """Per-fix key counters (step 0x10) inside their KEY_RANGES; next(fix) -> ruo key."""
    def __init__(self):
        self.c = {nm: lo for nm, lo, hi in KEY_RANGES}; self.hi = {nm: hi for nm, lo, hi in KEY_RANGES}

    def next(self, fix):
        nm = FIX_OF_RANGE[fix]; x = self.c[nm]
        if x >= self.hi[nm]: raise BuildError('galadd: key range %s full' % nm)
        self.c[nm] += 0x10
        return (K + x) & M


# ---------------------------------------------------------------- heap parsing helpers
class CountHeap(Heap):
    """rsaparse.Heap returning CVmCall's (args, extras) and CVmSound's extra bytes (build_all.CountHeap's form)."""
    def vm_call(self):
        self.u32(); self.u32(); self.read_class_list(); n = self.u16()
        for _ in range(n):
            d = self.u32()
            if d == 4:
                w = self.u16()
                if w == 0x1e57: self.read_class()
                elif w == 0x369e: self.read_raw_class()
                elif w in (0x2d6b, 0x2f1a): self.u16(); k = self.u16(); self.skip(k)
                else: raise BuildError('call w=%x' % w)
                self.skip(4)
            else:
                k = d & 3
                if k == 0: self.read_class_list()
                elif k == 1: self.string()
                elif k == 3:
                    t1 = self.u32()
                    if t1 == 0x137: self.u32()
        k = 0
        if self.cur_schema > 0x12:
            k = self.u8()
            if k == 0xff: k = self.u16()
            for _ in range(k):
                w = self.u16()
                if w & 0x8000: self.string()
                else: self.read_class_list()
        return n, k

    def vm_sound(self):
        self.u32(); self.u32(); self.read_class_list(); typ = self.u8()
        f = self.u8(); self.u16(); self.u16(); self.u16()
        if self.cur_schema >= 0x13 and typ in (2, 4):
            self.read_class_list()
        extra = 0
        if f & 4:
            if f & 8: self.read_class_list(); extra = 4
            else:
                self.skip(8); extra = 8
                if not f & 0x10: self.skip(6); extra = 16
        return extra


_FIXED = {'CVmRet': 12, 'CVmSync': 24, 'CVmGenericMsg': 28, 'CVmJump': 16, 'CVmLabel': 16, 'CVmFlagOp': 32}


def base_pos(d, s):
    tag = struct.unpack_from('<H', d, s)[0]; p = s + 2
    if tag == 0xffff: p += 2; n = d[p]; p += 1 + n
    return p


def mem_size(h, i):
    name = h.instrs[i][2]
    if name == 'CVmCall':
        na, ne = h.instrs[i][3]; return 20 + 12 * na + 8 * ne
    if name == 'CVmMsg3':
        p = base_pos(h.d, h.instrs[i][0]); n1, n2 = h.d[p + 12], h.d[p + 13]
        return (20 + 12 * n1 + 10 * n2 + 3) & ~3
    if name == 'CVmSound':
        return 28 + h.instrs[i][3]
    if name == 'CVmDirectionSync':      # 24, 32 with flag 0x8000 (PM's 185 of them, n = 0; measured on the next chain)
        p = base_pos(h.d, h.instrs[i][0]); fl = struct.unpack_from('<I', h.d, p + 8)[0]
        if struct.unpack_from('<H', h.d, p + 12)[0] != 0: raise BuildError('CVmDirectionSync with objects')
        return 32 if fl & 0x8000 else 24
    return _FIXED[name]


def parse(d):
    h = CountHeap(bytes(d), 2); h.parse()
    if h.tail is None or h.tail['end'] != len(d): raise BuildError('galadd: heap does not parse to its end')
    return h


def offsets(h):
    o, out = 0, []
    for i in range(h.count):
        out.append(o); o += mem_size(h, i)
    return out, o


def flag_parts(h, i):
    """CVmFlagOp i of h: (op, x, target)."""
    e = h.instrs[i][1]
    op, x, t = struct.unpack_from('<HBI', h.d, e - 7)
    return op, x, t


def _norm(res):
    return [('pad',) if x and x[0] == 'pad' else x for x in res]


def rcl_map(h):
    """rcl event index -> its explicit 'ref' event index (heapwriter.Slicer's rcl_to_ref)."""
    return Slicer(h).rcl_to_ref


def ref_chain(h, kr):
    """Parent chain of the explicit ref event kr: [(cls name, off, flag), ...] up to an index reference, which ends the
    list as ('idx', entry) (a pad entry or an object defined earlier: ('obj', cls name, off))."""
    out = []
    while True:
        R = h.ev[kr]
        out.append((R[5][0], R[6], struct.unpack_from('<H', h.d, R[4] - 2)[0]))
        p = R[4] + 8                         # the parent's read_class_list starts after the enc pair
        j = kr - 1
        while j >= 0 and not (h.ev[j][0] == 'rcl' and h.ev[j][1] == p): j -= 1
        nxt = h.ev[j + 1]
        if nxt[0] == 'oidx':
            e = nxt[2]
            out.append(('obj', h.objinfo[e][0][0], h.objinfo[e][1]) if e in h.objinfo else ('idx', e))
            return out
        q = next((q for q in range(kr - 1, j, -1) if h.ev[q][0] == 'ref' and h.ev[q][1] == p), None)
        if q is None: raise BuildError('ref chain: parent of event %d not understood' % kr)
        kr = q


# ---------------------------------------------------------------- the writer
def _trailing(flag):
    return 4 if (flag & 7) == 1 else 1 if flag & 0x8000 else 2


def write_heap(H, inserts, consts=(), what='heap', redirect=None):
    """H: parsed source heap (rsaparse.Heap). inserts: {after original index a: [clone spec, ...]} (non-capturing:
    entered only from a's fall-through). consts: [(original index, byte offset in the instruction, old bytes, new
    bytes)]. Clone spec (dict): tpl (index in H), id, op (FlagOp op), a_int (FlagOp A, an int constant in the template),
    target / next (('orig', j) | ('lab', name); default next = sequential, FlagOp assignments: target = next), label,
    newref {event index (the rcl of an explicit ref, or an oidx): (cls entry, flag, enc 8 bytes, parent)} with parent
    ('idx', original entry) | ('new', key) | ('chain', [(cls entry, flag, enc, key), ...outer first], ('idx', e)),
    newkey (key under which the new object is remembered), oidx {oidx event index: original entry}, args {arg byte
    position in the template: new 4 bytes (an int replacing an int), or (old span end, new bytes)}, raw {template
    position: (end, new bytes)}. redirect: {original index: ('lab', name)}: that instruction's next goes to a clone
    block placed after a CVmRet (no fall-through enters it), whose last clone's next returns to the original flow.
    Returns (heap bytes, items) with items = [('orig', j) | ('clone', spec)]."""
    H = parse(H.d)                                     # (CountHeap: the in-memory sizes; the same events)
    S = Slicer(H)
    S.out = bytearray(); S.map = {0: 0, 1: 1}; S.next = 2; S.pending = set(); S.pad_emitted = False
    S.cur = H.instrs[0][0]
    rcl_to_ref = S.rcl_to_ref
    newobj = {}
    items = []; ev_pos = H.ins_ev[0][0]; prev = 0
    for a in sorted(inserts):
        if not 0 <= a < H.count - 1: raise BuildError('%s: insert after %d' % (what, a))
        if H.instrs[a][2] in ('CVmRet', 'CVmJump') and not (redirect and any(
                r_[1] == inserts[a][0].get('label') for r_ in redirect.values())):
            raise BuildError('%s: a block after %s %d must be entered by a redirect' % (what, H.instrs[a][2], a))
        S._emit_events(ev_pos, H.ins_ev[a][1], H.instrs[a][1]); ev_pos = H.ins_ev[a][1]
        items += [('orig', j) for j in range(prev, a + 1)]; prev = a + 1
        for c in inserts[a]:
            _emit_clone(H, S, rcl_to_ref, c, newobj, what)
            items.append(('clone', c))
    S._emit_events(ev_pos, H.ins_ev[H.count - 1][1], H.instrs[H.count - 1][1])
    items += [('orig', j) for j in range(prev, H.count)]
    S.cur = H.tail['start']
    S._emit_events(H.tail['ev'][0], H.tail['ev'][1], H.tail['end'])
    n = len(items)
    newP = bytearray(H.d[0:4] + struct.pack('<IIIII', 0xffff0000, H.version, 0, n, H.extra) + bytes(S.out))
    q = parse(newP)
    if q.count != n: raise BuildError('%s: %d instructions, want %d' % (what, q.count, n))
    if len(q.cache) != S.next: raise BuildError('%s: load array %d entries, writer counted %d' % (what, len(q.cache), S.next))
    offs, total = offsets(q)
    struct.pack_into('<I', newP, 12, total)
    old_off, _ = offsets(H)
    inv = {o: j for j, o in enumerate(old_off)}
    pos_orig = {}; pos_lab = {}
    for t, (k, x) in enumerate(items):
        if k == 'orig': pos_orig[x] = t
        elif x.get('label'): pos_lab[x['label']] = t

    def where(spec):
        if spec[0] == 'orig': return offs[pos_orig[spec[1]]]
        if spec[0] == 'lab': return offs[pos_lab[spec[1]]]
        raise BuildError('%s: target %r' % (what, spec))
    for t, (k, x) in enumerate(items):
        bp = base_pos(newP, q.instrs[t][0])
        cls = q.instrs[t][2]
        seq = offs[t + 1] if t + 1 < n else None
        if k == 'orig':
            j = x
            dw1, dw2 = struct.unpack_from('<II', H.d, base_pos(H.d, H.instrs[j][0]))
            if j + 1 < H.count:
                if redirect and j in redirect:
                    if dw1 != old_off[j + 1]: raise BuildError('%s: redirect of a non-sequential next' % what)
                    nx = where(redirect[j])
                elif dw1 == old_off[j + 1] and H.instrs[j][2] in ('CVmRet', 'CVmJump'):
                    nx = offs[pos_orig[j + 1]]         # no fall-through: its (unused) next stays on the same instruction
                elif dw1 == old_off[j + 1]:
                    nx = seq                           # the fall-through (it enters a block inserted after j)
                elif dw1 in inv:
                    nx = offs[pos_orig[inv[dw1]]]      # a next to another instruction (patch_pm's landing): kept
                else:
                    raise BuildError('%s: %d has a next to no instruction' % (what, j))
            else:
                nx = dw1
            struct.pack_into('<I', newP, bp, nx)
            if cls == 'CVmFlagOp':
                op, xx, tv = flag_parts(H, j)
                if op < 0x40:
                    if tv != dw1: raise BuildError('%s: assignment %d targets another instruction' % (what, j))
                    nt = nx
                else:
                    nt = tv if tv == M else offs[pos_orig[inv[tv]]]
                struct.pack_into('<I', newP, q.instrs[t][1] - 4, nt)
        else:
            c = x
            tdw2 = struct.unpack_from('<I', H.d, base_pos(H.d, H.instrs[c['tpl']][0]) + 4)[0]
            nx = where(c['next']) if c.get('next') else seq
            if nx is None: raise BuildError('%s: a clone is the last instruction' % what)
            struct.pack_into('<II', newP, bp, nx, (tdw2 & 0xFFF00000) | c['id'])
            if cls == 'CVmFlagOp':
                op = struct.unpack_from('<H', newP, q.instrs[t][1] - 7)[0]
                if op < 0x40:
                    if c.get('target') and where(c['target']) != nx:
                        raise BuildError('%s: assignment clone with a branch target' % what)
                    nt = nx
                else:
                    if not c.get('target'): raise BuildError('%s: compare clone without a target' % what)
                    nt = where(c['target'])
                struct.pack_into('<I', newP, q.instrs[t][1] - 4, nt)
    for j, at, old, new in consts:
        t = pos_orig[j]; s = q.instrs[t][0]
        if bytes(newP[s + at:s + at + len(old)]) != old or len(old) != len(new):
            raise BuildError('%s: constant at %d+%d is not %s' % (what, j, at, old.hex()))
        newP[s + at:s + at + len(new)] = new
    newP = bytes(newP)
    _verify(H, newP, items, what)
    return newP, items


def _emit_clone(H, S, rcl_to_ref, c, newobj, what):
    j = c['tpl']
    s, e = H.instrs[j][0], H.instrs[j][1]; lo, hi = H.ins_ev[j]
    ins = H.instrs[j][2]
    bp = base_pos(H.d, s)
    raw = dict(c.get('raw') or {})
    if c.get('op') is not None:
        if ins != 'CVmFlagOp': raise BuildError('%s: op on a %s' % (what, ins))
        raw[e - 7] = (e - 5, struct.pack('<H', c['op']))
    if c.get('a_int') is not None:
        if ins != 'CVmFlagOp' or struct.unpack_from('<I', H.d, bp + 8)[0] & 3 != 2:
            raise BuildError('%s: a_int on a template whose A is not an int' % what)
        raw[bp + 8] = (bp + 12, struct.pack('<I', ((c['a_int'] << 2) | 2) & M))
    for p, v in (c.get('args') or {}).items():
        if isinstance(v, tuple): raw[p] = v
        else:
            if struct.unpack_from('<I', H.d, p)[0] & 3 != 2: raise BuildError('%s: arg at %x is not an int' % (what, p))
            raw[p] = (p + 4, v)
    newref = c.get('newref') or {}; oidx = c.get('oidx') or {}
    out = S.out
    cur = [s]

    def copy(b):
        """Copy template bytes [cur, b) applying raw patches that start there; cur may end past b (a patch)."""
        a = cur[0]
        while a < b:
            ps = [p for p in raw if a <= p < b]
            if not ps:
                out.extend(H.d[a:b]); a = b; break
            p = min(ps); end, nb = raw.pop(p)
            out.extend(H.d[a:p]); out.extend(nb); a = end
        cur[0] = max(cur[0], a)

    def mapped(entry, kind):
        v = S.map.get(entry)
        if v is None: raise BuildError('%s: clone of %d references %s entry %d not in the output yet' % (what, j, kind, entry))
        return v

    def emit_ref(spec):
        cls_e, flag, enc, parent = spec
        out.extend(struct.pack('<HH', 0x8000 | mapped(cls_e, 'class'), flag)); out.extend(enc)
        emit_parent(parent)
        out.extend(bytes(_trailing(flag))); i = S.next; S.next += 1
        return i

    def emit_parent(parent):
        if parent[0] == 'idx':
            out.extend(struct.pack('<H', mapped(parent[1], 'object')))
        elif parent[0] == 'new':
            out.extend(struct.pack('<H', newobj[parent[1]]))
        elif parent[0] == 'chain':
            items_, base = parent[1], parent[2]
            if items_[0][3] in newobj:                 # defined by an earlier clone: its index
                out.extend(struct.pack('<H', newobj[items_[0][3]])); return
            ce, fl, en, key = items_[0]
            out.extend(struct.pack('<HH', 0x8000 | mapped(ce, 'class'), fl)); out.extend(en)
            emit_parent(('chain', items_[1:], base) if len(items_) > 1 else base)
            out.extend(bytes(_trailing(fl))); newobj[key] = S.next; S.next += 1
        else:
            raise BuildError('%s: parent %r' % (what, parent))

    skip_ent = set()
    k = lo
    while k < hi:
        ev = H.ev[k]; kind = ev[0]
        if kind != 'ent':
            copy(ev[1])
            if ev[1] < cur[0]:                         # inside a patched span (e.g. an index operand made an int)
                k += 1; continue
        if kind == 'rcl':
            kr = rcl_to_ref.get(k)
            if k in newref:
                R = H.ev[kr]
                copy(R[1]); i = emit_ref(newref[k])
                if c.get('newkey') is not None: newobj[c['newkey']] = i
                cur[0] = R[2]
                k = kr + 1
                if not (k < hi and H.ev[k][0] == 'ent' and H.ev[k][2] == R[3]): raise BuildError('%s: ref entry' % what)
                k += 1; continue
            if kr is not None and kr < hi:
                R = H.ev[kr]
                copy(R[1]); out.extend(struct.pack('<H', mapped(R[3], 'object'))); cur[0] = R[2]
                k = kr + 1
                if not (k < hi and H.ev[k][0] == 'ent' and H.ev[k][2] == R[3]): raise BuildError('%s: ref entry' % what)
                k += 1; continue
            k += 1; continue
        if kind == 'cidx':
            copy(ev[1]); out.extend(struct.pack('<H', 0x8000 | mapped(ev[2], 'class'))); cur[0] = ev[1] + 2
        elif kind == 'oidx':
            copy(ev[1])
            if k in newref:
                i = emit_ref(newref[k])
                if c.get('newkey') is not None: newobj[c['newkey']] = i
            else:
                out.extend(struct.pack('<H', mapped(oidx.get(k, ev[2]), 'object')))
            cur[0] = ev[1] + 2
        elif kind in ('cdef', 'rdef', 'adef'):
            copy(ev[1]); out.extend(struct.pack('<H', 0x8000 | mapped(ev[3], 'class'))); cur[0] = ev[2]
            skip_ent.add(ev[3])
        elif kind == 'ent':
            if ev[2] in skip_ent: skip_ent.discard(ev[2])
            else: S.next += 1                          # anonymous entry (an OM instance): the engine appends one
        elif kind in ('null',):
            pass
        else:
            raise BuildError('%s: clone of %d: event %s not handled' % (what, j, kind))
        k += 1
    copy(e)
    if raw: raise BuildError('%s: clone of %d: patches not applied %s' % (what, j, sorted(raw)))


def _verify(H, newP, items, what):
    q = Heap(newP, 2); q.parse()
    if q.count != len(items) or q.tail is None or q.tail['end'] != len(newP): raise BuildError('%s: re-parse' % what)
    for t, (k, x) in enumerate(items):
        if k == 'orig':
            if _norm(q.ins_res[t]) != _norm(H.ins_res[x]) or q.instrs[t][2] != H.instrs[x][2]:
                raise BuildError('%s: original instruction %d changed its references' % (what, x))
        else:
            want = x.get('expect')
            if want is not None and _norm(q.ins_res[t]) != _norm(want):
                raise BuildError('%s: clone of %d resolves to %s, want %s' % (what, x['tpl'], q.ins_res[t], want))
            if q.instrs[t][2] != H.instrs[x['tpl']][2]: raise BuildError('%s: clone class' % what)
    if _norm(q.tail['res']) != _norm(H.tail['res']): raise BuildError('%s: tail references changed' % what)


# ---------------------------------------------------------------- template checks
def _ref_event(H, i, nth=0, cls=None):
    """The nth explicit top-level ref (its rcl event index, ref event index) of instruction i, optionally of class cls."""
    lo, hi = H.ins_ev[i]; rr = rcl_map(H); found = []
    depth_end = -1
    for k in range(lo, hi):
        ev = H.ev[k]
        if ev[0] == 'rcl' and k in rr and ev[1] >= depth_end:
            R = H.ev[rr[k]]
            if cls is None or R[5][0] == cls: found.append((k, rr[k]))
            depth_end = R[2]
    return found[nth]


def _oidx_events(H, i):
    lo, hi = H.ins_ev[i]
    return [k for k in range(lo, hi) if H.ev[k][0] == 'oidx']


def _class_entry(H, name):
    e = next((ev[3] for ev in H.ev if ev[0] == 'cdef' and ev[4][0] == name), None)
    if e is None: raise BuildError('class %s not defined in the heap' % name)
    return e


def _entry_of(H, off, cls=None):
    """Load-array entry of the object off defined in H (an explicit ref)."""
    es = [ev[3] for ev in H.ev if ev[0] == 'ref' and ev[6] == off and (cls is None or ev[5][0] == cls)]
    if len(es) != 1: raise BuildError('object %x defined %d times' % (off, len(es)))
    return es[0]


def _expect(H, i, repl):
    """Template i's resolved references with repl {position in ins_res: new item or None (removed)}."""
    out = []
    for n, x in enumerate(H.ins_res[i]):
        if n in repl:
            if repl[n] is not None: out.append(repl[n])
        else:
            out.append(x)
    return out


def dec_off(enc):
    return 3 + 2 * ((enc - K) & M)


def dec_size(v):
    a = (v - 0xE7B5D9F8) & M; c = a >> 13; d = c & 0xFFF; a2 = (a - d) & M
    return (((a2 << 19) & M) | c) - 3


def _cr6ti(enc8):
    eo, es = struct.unpack('<II', enc8)
    return (('Cr6Ti', 4), dec_off(eo), dec_size(es))


def _fo(H, i, op=None, a=None, b=None):
    """Check FlagOp template i: op, A (int or object offset), B (object offset)."""
    if H.instrs[i][2] != 'CVmFlagOp': return False
    o, x, t = flag_parts(H, i)
    if op is not None and o != op: return False
    bp = base_pos(H.d, H.instrs[i][0]); res = H.ins_res[i]
    objs = [r for r in res if r and isinstance(r[0], tuple)]
    if a is not None:
        if isinstance(a, int) and a < 0x10000:
            dw = struct.unpack_from('<I', H.d, bp + 8)[0]
            if dw & 3 != 2 or (dw >> 2) != a: return False
        elif not objs or objs[0][1] != a: return False
    if b is not None and (not objs or objs[-1][1] != b): return False
    return True


def _call_target(H, i):
    r = H.ins_res[i][0] if H.ins_res[i] else None
    return r[1] if r and isinstance(r[0], tuple) else None


def _int_args(H, i, n):
    """The last n args of CVmCall i (no extras) are plain ints: their positions."""
    e = H.instrs[i][1]
    if H.d[e - 1] != 0 or struct.unpack_from('<H', H.d, e - 3 - 4 * n)[0] != n: return None
    ps = [e - 1 - 4 * (n - q) for q in range(n)]
    if any(struct.unpack_from('<I', H.d, p)[0] & 3 != 2 for p in ps): return None
    return ps


def _iv(v):
    return struct.pack('<I', ((v << 2) | 2) & M)


# ---------------------------------------------------------------- the three gallery heaps
def build_gallery(pm, rows, variants, n_total, ids, imports, copy_keys, thumb_keys, gate_ok=True):
    """pm: {heap name: parsed PM heap}. rows / variants: plan(). n_total: the AF tab's entry count. imports: {AF off of a
    GALADD key CG: its import's (enc_off, enc_size) as the restored parts reference it}. copy_keys: {(row name or
    ('var', pm entry, AF off), view n): (key, enc_size)} of the new copies; thumb_keys: {row name: (key, enc_size)}.
    Returns {heap name: (new heap bytes, items)} and a report."""
    out = {}; report = {}
    R = pm[REG]; T = pm[TILE]; V = pm[VIEW]; C = pm[CHAIN_SRC[0]]
    # ---- templates (asserted)
    CNT, IDX, TAB, RES, FLG = 0x8e5bc7e7, 0x8e5bc7eb, 0x8e5bc7e9, 0x27b4f007, 0x27b4e8df
    if not (_fo(R, 6, 0x42, CNT, IDX) and _fo(R, 5, 1, 1, CNT) and _fo(R, 14, 0x42, 0, RES) and _fo(R, 347, 0, FLG, RES)
            and _fo(R, 267, 1, 1, CNT) and _fo(R, 268, 0x42, 1, TAB) and _call_target(R, 346) == 0x5cc2ec3f
            and R.instrs[10][2] == 'CVmGenericMsg' and 'GetCgRegisterByDatabase' in str(R.instrs[10][3])):
        raise BuildError('galadd: register heap templates are not what they should be')
    folders ={0x327c5201: _entry_of(R, 0x327c5201), 0x327a843d: _entry_of(R, 0x327a843d),
               0x5ca6cd1d: _entry_of(R, 0x5ca6cd1d)}
    for f, e in folders.items():                      # each folder's chain: > 32749557 > 32749559 > 453c7 (C308) > pad3
        kr = next(k for k, ev in enumerate(R.ev) if ev[0] == 'ref' and ev[3] == e)
        ch = ref_chain(R, kr)
        names = [x[1] for x in ch[:-1]]
        tail = ch[-1]
        want_pad = next(ev for ev in R.ev if ev[0] == 'pad')[2] + 3
        full = names
        if tail[0] == 'obj':                          # the rest of the chain defined earlier
            kr2 = next(k for k, ev in enumerate(R.ev) if ev[0] == 'ref' and ev[6] == tail[2])
            ch2 = ref_chain(R, kr2); full = names + [x[1] for x in ch2[:-1]]; tail = ch2[-1]
        if full != [f, 0x32749557, 0x32749559, 0x453c7][:len(full)] or len(full) != 4 or tail != ('idx', want_pad):
            raise BuildError('galadd: folder %x chain %s' % (f, ch))
    # GALADD chain: CHAIN_SRC's explicit ref of 5d35f8c5 (C108) > 27b4ea1b (C308) > pad2; both heaps' pads start at 3
    kc = next(k for k, ev in enumerate(C.ev) if ev[0] == 'ref' and ev[6] == 0x5d35f8c5)
    chc = ref_chain(C, kc)
    padR = next(ev for ev in R.ev if ev[0] == 'pad'); padC = next(ev for ev in C.ev if ev[0] == 'pad')
    if (chc != [('CObjectOcean', 0x5d35f8c5, 0xC108), ('CObjectOcean', 0x27b4ea1b, 0xC308), ('idx', padC[2] + 2)]
            or padR[2:] != padC[2:]):
        raise BuildError('galadd: %s chain %s' % (CHAIN_SRC[0], chc))
    encs = {}
    for k_ in (kc, next(k for k, ev in enumerate(C.ev) if ev[0] == 'ref' and ev[6] == 0x27b4ea1b)):
        encs[C.ev[k_][6]] = bytes(C.d[C.ev[k_][4]:C.ev[k_][4] + 8])
    for o_, ee in encs.items():
        if dec_off(struct.unpack('<I', ee[:4])[0]) != o_: raise BuildError('galadd: chain enc')
    oc_cls = _class_entry(R, 'CObjectOcean'); cr_cls = _class_entry(R, 'Cr6Ti')
    chain = ('chain', [(oc_cls, 0xC108, encs[0x5d35f8c5], 0x5d35f8c5), (oc_cls, 0xC308, encs[0x27b4ea1b], 0x27b4ea1b)],
             ('idx', padR[2] + 2))
    reg_tpl = {}                                       # folder -> a GetCg template whose Cr6Ti hangs under it by index
    for i in range(3, 268):
        if R.instrs[i][2] != 'CVmGenericMsg': continue
        kr = _ref_event(R, i, 0, 'Cr6Ti')[1]
        ch = ref_chain(R, kr)
        if len(ch) == 2 and ch[1][0] == 'obj' and ch[1][2] in folders and ch[1][2] not in reg_tpl:
            reg_tpl[ch[1][2]] = i
    if set(reg_tpl) != set(folders): raise BuildError('galadd: register templates %s' % reg_tpl)
    # ---- register heap: tab 0's chain ends at @267 (@2: tab != 0 jumps to @268). The flag read 5cc2ec3f (@346 / @347)
    # is first defined after it (CVmCall class, CRsa 5cc2ec3f, CInt 27b4e8df at @336-337): so the new blocks sit after
    # the first closing CVmRet @755 (PM has code after a CVmRet in 34 heaps), entered by @267's next and leaving to @268
    reg = []

    def lab(*a): return '/'.join(str(x) for x in a)
    for idx, name, grp, e in rows:
        fx = grp
        end = lab('r', name, 'inc')
        reg.append(dict(tpl=6, id=ids.next(fx), target=('lab', end), expect=R.ins_res[6]))
        if grp == 'galadd':
            fl = flag_name(name)
            old = 'PM_CGOPEN_ADO220'
            tb = R.d[R.instrs[346][0]:R.instrs[346][1]]
            o_ = b'\xff\xfe\xff' + bytes([len(old)]) + old.encode('utf-16le')
            p = tb.find(o_)
            if p < 0 or tb.find(o_, p + 1) >= 0: raise BuildError('galadd: register flag template string')
            p += R.instrs[346][0]
            reg.append(dict(tpl=346, id=ids.next(fx), raw={p: (p + len(o_), b'\xff\xfe\xff' + bytes([len(fl)]) + fl.encode('utf-16le'))},
                            expect=R.ins_res[346]))
            reg.append(dict(tpl=347, id=ids.next(fx), expect=R.ins_res[347]))
            reg.append(dict(tpl=14, id=ids.next(fx), target=('lab', end), expect=R.ins_res[14]))
            enc = struct.pack('<II', *imports[e[1]])
            t = reg_tpl[0x327a843d]; ke = _ref_event(R, t, 0, 'Cr6Ti')
            pos = [n for n, r in enumerate(R.ins_res[t]) if r and isinstance(r[0], tuple) and r[0][0] == 'Cr6Ti'][0]
            reg.append(dict(tpl=t, id=ids.next(fx), newref={ke[0]: (cr_cls, 0xC108, enc, chain)},
                            expect=_expect(R, t, {pos: _cr6ti(enc)})))
        else:
            enc = struct.pack('<II', (K + (e[4] - 3) // 2) & M, _enc_size(e[5] + 3))
            t = reg_tpl[e[6]]; ke = _ref_event(R, t, 0, 'Cr6Ti')
            pos = [n for n, r in enumerate(R.ins_res[t]) if r and isinstance(r[0], tuple) and r[0][0] == 'Cr6Ti'][0]
            reg.append(dict(tpl=t, id=ids.next(fx), newref={ke[0]: (cr_cls, 0xC108, enc, ('idx', folders[e[6]]))},
                            expect=_expect(R, t, {pos: _cr6ti(enc)})))
        reg.append(dict(tpl=5, id=ids.next(fx), label=end, expect=R.ins_res[5]))
    gate = [v for v in variants if v[0] == 64]
    if gate and gate_ok:
        # the key is PM's own: GATE64_SRC is OM_AccessWrite on CStdb 44c13 (the database 5cc2ec3f reads) of exactly
        # this key (its first string, UTF-16 in PM's marker form) to '1'
        Hg = pm.get(GATE64_SRC[0])
        if Hg is None: raise BuildError('galadd: %s not available for the entry-64 gate check' % GATE64_SRC[0])
        s_, e_ = Hg.instrs[GATE64_SRC[1]][0], Hg.instrs[GATE64_SRC[1]][1]
        kb_ = b'\xff\xfe\xff' + bytes([len(GATE64)]) + GATE64.encode('utf-16le') + b'\xff\xfe\xff\x01' + '1'.encode('utf-16le')
        rg = Hg.ins_res[GATE64_SRC[1]][0] if Hg.ins_res[GATE64_SRC[1]] else None
        if not (Hg.instrs[GATE64_SRC[1]][2] == 'CVmGenericMsg' and 'OM_AccessWrite' in str(Hg.instrs[GATE64_SRC[1]][3])
                and rg and isinstance(rg[0], tuple) and rg[0][0] == 'CStdb' and rg[1] == 0x44c13 and kb_ in Hg.d[s_:e_]):
            raise BuildError('galadd: %s@%d is not PM\'s write of %s' % (GATE64_SRC + (GATE64,)))
        # entry 64's gate: a pseudo entry GATE_IDX = the CStdb key GATE64 (00ba7f84ba has no CStdb reader of its own)
        kb = [k for k in _oidx_events(R, 268)]
        if len(kb) != 1: raise BuildError('galadd: gate template')
        e_idx = next(ev[3] for ev in R.ev if ev[0] == 'ref' and ev[6] == IDX)
        # 'idx == GATE_IDX ?' (@268's form: an int A, the index variable as B) else on to @268 (tab 1)
        reg.append(dict(tpl=268, id=ids.next('galpm'), a_int=GATE_IDX, oidx={kb[0]: e_idx}, target=('orig', 268),
                        expect=[(('_int', 0), IDX, -1) if r and isinstance(r[0], tuple) else r for r in R.ins_res[268]]))
        old = 'PM_CGOPEN_ADO220'
        tb = R.d[R.instrs[346][0]:R.instrs[346][1]]
        o_ = b'\xff\xfe\xff' + bytes([len(old)]) + old.encode('utf-16le')
        p = tb.find(o_) + R.instrs[346][0]
        reg.append(dict(tpl=346, id=ids.next('galpm'),
                        raw={p: (p + len(o_), b'\xff\xfe\xff' + bytes([len(GATE64)]) + GATE64.encode('utf-16le'))},
                        expect=R.ins_res[346]))
        reg.append(dict(tpl=347, id=ids.next('galpm'), expect=R.ins_res[347]))
    if R.instrs[755][2] != 'CVmRet' or R.instrs[756][2] != 'CVmRet' or R.count != 757:
        raise BuildError('galadd: register heap does not end in two CVmRet')
    if reg:
        reg[0]['label'] = 'r/start'; reg[-1]['next'] = ('orig', 268)
        out[REG] = write_heap(R, {755: reg}, what=REG, redirect={267: ('lab', 'r/start')})
    # ---- tile heap: after @267; locked tiles (@5) and tabs 1-3 (@2) still jump to @268
    if not (_fo(T, 265, 0x42, 0x92829ad7, 0x92829adb) and _fo(T, 267, 1, 1, 0x92829ad7)
            and _call_target(T, 266) == 0x323dbd9b):
        raise BuildError('galadd: tile heap templates')
    rt, ke = _ref_event(T, 266, 0, 'Cr6Ti')
    if ref_chain(T, ke)[1] != ('obj', 'CObjectOcean', 0x6accf19f): raise BuildError('galadd: thumbnail folder')
    tile = []
    pos = [n for n, r in enumerate(T.ins_res[266]) if r and isinstance(r[0], tuple) and r[0][0] == 'Cr6Ti'][0]
    folder_t = _entry_of(T, 0x6accf19f); crt = _class_entry(T, 'Cr6Ti')
    for idx, name, grp, e in rows:
        end = lab('t', name)
        enc = struct.pack('<II', *thumb_keys[name])
        tile.append(dict(tpl=265, id=ids.next(grp), target=('lab', end), expect=T.ins_res[265]))
        tile.append(dict(tpl=266, id=ids.next(grp), newref={rt: (crt, 0xC108, enc, ('idx', folder_t))},
                         expect=_expect(T, 266, {pos: _cr6ti(enc)})))
        tile.append(dict(tpl=267, id=ids.next(grp), label=end, expect=T.ins_res[267]))
    out[TILE] = write_heap(T, {267: tile}, what=TILE)
    # ---- view heap
    PAGE, LASTP, BB, VIDX, STY, SEL, TABV = 0x6ac85fd1, 0x6ac85fdd, 0x6ac1b5bb, 0x6ac1b5bf, 0x6ac1f20f, 0x4e205, 0x6ac1b5bd
    chk = (_fo(V, 924, 0, PM_COUNT, 0x6ac85fdb) and _fo(V, 1857, 0x46, 0, PAGE) and _fo(V, 980, 0x42, 5, PAGE)
           and _fo(V, 1784, 0, 2, STY) and _fo(V, 2015, 0x42, 21, SEL) and _fo(V, 2050, 0x42, 0, TABV)
           and _fo(V, 1906, 1, 1, PAGE) and _fo(V, 1907, 0x44, LASTP, PAGE) and _fo(V, 1908, 0, 0, PAGE)
           and _fo(V, 2555, 0x42, BB, VIDX) and _fo(V, 2561, 1, 1, BB) and _fo(V, 8, 0x43, 0, RES)
           and _fo(V, 1972, 0x46, 21, SEL) and _fo(V, 1973, 0, SEL, PAGE) and _fo(V, 1974, 2, 15, PAGE)
           and _fo(V, 1782, 0x42, 0, TABV) and _fo(V, 1783, 0x45, 6, BB) and _fo(V, 1780, 0x42, BB, PAGE)
           and _call_target(V, 1363) == 0x324ed42d and _call_target(V, 1364) == 0x324ed4c3
           and _call_target(V, 2045) == 0x6ac1b5c1 and all(_call_target(V, i_) == 0x6acd5cb3 for i_ in (2556, 2557, 2560)))
    if not chk: raise BuildError('galadd: view heap templates')
    vins = {}
    # title (owner: no page title on pages 7+): skip @1364's fade-in of title item 1504 on page index >= 6
    vins[1363] = [dict(tpl=1857, id=ids.next('nav'), a_int=6, target=('orig', 1365), expect=V.ins_res[1857])]
    # page button 6 (k = 5, tab 0) drawn in the current-page style 2 on page index >= 5
    vins[1782] = [dict(tpl=980, id=ids.next('nav'), op=0x45, target=('orig', 1783), expect=V.ins_res[980]),
                  dict(tpl=1784, id=ids.next('nav'), expect=V.ins_res[1784])]
    # click map: button 6 (select id 20) on tab 0 at page index >= 5 steps on (last page -> page index 5); else @1973
    vins[1972] = [dict(tpl=2015, id=ids.next('nav'), a_int=20, target=('orig', 1973), expect=V.ins_res[2015]),
                  dict(tpl=2050, id=ids.next('nav'), target=('orig', 1973), expect=V.ins_res[2050]),
                  dict(tpl=980, id=ids.next('nav'), op=0x45, target=('orig', 1973), expect=V.ins_res[980]),
                  dict(tpl=1906, id=ids.next('nav'), expect=V.ins_res[1906]),
                  dict(tpl=1907, id=ids.next('nav'), target=('orig', 1975), expect=V.ins_res[1907]),
                  dict(tpl=1908, id=ids.next('nav'), a_int=5, next=('orig', 1975), expect=V.ins_res[1908])]
    rv, kv = _ref_event(V, 2557, 0, 'Cr6Ti')
    if ref_chain(V, kv)[1] != ('obj', 'CObjectOcean', 0x6ad256ed): raise BuildError('galadd: copy folder')
    posv = [n for n, r in enumerate(V.ins_res[2557]) if r and isinstance(r[0], tuple) and r[0][0] == 'Cr6Ti'][0]
    folder_v = _entry_of(V, 0x6ad256ed); crv = _class_entry(V, 'Cr6Ti')

    def view_call(fx, key):
        enc = struct.pack('<II', *key)
        return dict(tpl=2557, id=ids.next(fx), newref={rv: (crv, 0xC108, enc, ('idx', folder_v))},
                    expect=_expect(V, 2557, {posv: _cr6ti(enc)}))
    for pm_e, fx, after, frames, win in variants:
        L = vins.setdefault(after, [])
        if pm_e == 64 and gate_ok:
            # 2007 shows 538c23f5 only once its CStdb key is set: 6ac1b5c1(tab, GATE_IDX, #0) (@2045 with its index
            # variable argument made the constant) asks the register heap's pseudo entry; 'result != 0 ?' (@8) else
            # on to entry 64's own #3 call
            ob = _oidx_events(V, 2045)                     # target CRsa, tab, index
            p_arg2 = V.ev[ob[2]][1] - 4                    # the index argument's dword, then its 2-byte index
            if len(ob) != 3 or struct.unpack_from('<I', V.d, p_arg2)[0] & 3 != 0 or V.ins_res[2045][2][1] != VIDX:
                raise BuildError('galadd: gate call template')
            L.append(dict(tpl=2045, id=ids.next(fx), args={p_arg2: (p_arg2 + 6, _iv(GATE_IDX))},
                          expect=[r for n, r in enumerate(V.ins_res[2045]) if n != 2]))
            L.append(dict(tpl=8, id=ids.next(fx), target=('orig', after + 1), expect=V.ins_res[8]))
        for fr in frames:
            L.append(view_call(fx, copy_keys[('var', pm_e, fr[0])]))
    blocks = []
    for idx, name, grp, e in rows:
        end = lab('v', name)
        blocks.append(dict(tpl=2555, id=ids.next(grp), target=('lab', end), expect=V.ins_res[2555]))
        blocks.append(dict(tpl=2556, id=ids.next(grp), expect=V.ins_res[2556]))
        for n_, fr in enumerate(e[-1]):
            blocks.append(view_call(grp, copy_keys[(name, n_)]))
        blocks.append(dict(tpl=2560, id=ids.next(grp), expect=V.ins_res[2560]))
        blocks.append(dict(tpl=2561, id=ids.next(grp), label=end, expect=V.ins_res[2561]))
    vins[2561] = blocks
    s0 = V.instrs[924][0]
    consts = [(924, 10, _iv(PM_COUNT), _iv(n_total))]
    out[VIEW] = write_heap(V, vins, consts, what=VIEW)
    report.update(count=n_total, rows=len(rows), variants=len(variants), gate=bool(gate and gate_ok))
    return out, report


def _enc_size(x):
    return ((((x >> 19) & 0xfff) + (x & 0xfff) | (x << 13)) + 0xE7B5D9F8) & M


# ---------------------------------------------------------------- F32: the story heap insert
def build_story(P, after, ids, enc):
    """P: parsed patched 01b8c7a482 (patch_pm's output); after: the patched index of PM's @2119; the templates are PM's
    @2115-2117 at after - 4 .. after - 2. enc: the import's (enc_off, enc_size). Returns (heap bytes, items)."""
    t0, t1, t2 = after - 4, after - 3, after - 2
    if not (_call_target(P, t0) == 0x27e92633 and _call_target(P, t1) == 0x27e92e99 and _call_target(P, t2) == 0x27e9379d
            and P.instrs[after][2] == 'CVmSound' and P.instrs[after + 1][2] == 'CVmMsg3'):
        raise BuildError('F32: %s templates' % STORY)
    e0 = P.instrs[t0][1]
    pa = [e0 - 5] if P.d[e0 - 1] == 0 and struct.unpack_from('<I', P.d, e0 - 5)[0] & 3 == 2 else None
    pc = _int_args(P, t1, 6); pt = _int_args(P, t2, 2)
    ob = _oidx_events(P, t0)
    if pa is None or pc is None or pt is None or len(ob) != 2 or P.ins_res[t0][1][0][0] != 'Cr6Ti':
        raise BuildError('F32: template args')
    if P.d[pa[0]:pa[0] + 4] != _iv(2): raise BuildError('F32: picture mode is not #2')
    pad = next(ev for ev in P.ev if ev[0] == 'pad')
    cr = _class_entry(P, 'Cr6Ti')
    e8 = struct.pack('<II', *enc)
    posc = [n for n, r in enumerate(P.ins_res[t0]) if r and isinstance(r[0], tuple) and r[0][0] == 'Cr6Ti'][0]
    clones = [dict(tpl=t0, id=ids.next('cg4721'), newref={ob[1]: (cr, 0xC108, e8, ('idx', pad[2]))},
                   expect=_expect(P, t0, {posc: _cr6ti(e8)})),
              dict(tpl=t1, id=ids.next('cg4721'), args={p: _iv(v) for p, v in zip(pc, CG4721_CAM)}, expect=P.ins_res[t1]),
              dict(tpl=t2, id=ids.next('cg4721'), args={p: _iv(v) for p, v in zip(pt, CG4721_TRANS)}, expect=P.ins_res[t2])]
    return write_heap(P, {after: clones}, what=STORY + ' (F32)')
