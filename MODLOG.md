> Engineering journal kept while building this tool. Paths, lab scripts (`scripts/...`), decompiles and extracted
> data it mentions belong to the private research setup and are **not** part of this repository; the app's code is in
> `src/`. Offsets and function names refer to the current Steam build of Muv-Luv_PM.exe.

# MODLOG: Altered Fable cut content -> Muv-Luv photonmelodies (Steam)

## Goal / scope (user, 2026-10-09)
- Restore into PM (Steam): the Altered Fable H-scenes + Marimo route. NOT the mini-games. Other PM stories untouched.
- Steam achievements must keep working; user has not played yet: don't touch their saves/progress.
- Restore the rest of the h-scenes.
- I never view or describe explicit images/text; I work on structure only.

## Paths
- AF (2007, DLsite): `C:\age\マブラヴオルタードフェイブル` (rUGP 5.x; altfable.rio + .002, .ruo1 patch, .ici)
- PM (Steam): `C:\Program Files (x86)\Steam\steamapps\common\Muv-Luv photonmelodies` (Muv-Luv_PM.exe = AGES3, 32-bit, NOT SteamStub-wrapped; photonmelodies11.rio + .002-.004, .ici)
- Lab (all derived data, never in game dirs): `%TEMP%\claude_rugp\`
  - scripts/: rsadump.py, rsascan2.py (find+decrypt CRsa), cutdiff.py (AF vs PM text diff), rsaparse.py (heap parser),
    ruotable.py (ruo table codec), fn.py (extract fn from decompile), ghx.sh/ghv.sh (Ghidra headless xref/vtable dumps)
  - out/af_rsa, out/pm_rsa: decrypted script heaps (file name = byte offset in archive)
  - decomp/pm.c (Ghidra decompile of Muv-Luv_PM.exe), rvmm.dll.c, Vm60.dll.c, af_rugp.exe.c
  - ghidra_proj/ (projects pm, af_*). Tools: ~/tools/ghidra_12.1.4_PUBLIC, ~/tools/jdk-21.0.12.1+1 (portable).
    Note: user also approved a system Temurin JDK 21 via winget (installed).
  - Gotchas: run only ONE Ghidra headless at a time per project (lock). cmd /c splits args on commas -> use '+'.
    python -I ignores PYTHONIOENCODING -> scripts reconfigure stdout to utf-8.
    Safety classifier blocked running a script that loaded data from the cloned repo: keep data copies in scripts/.

## Format facts (verified)
- Offsets/sizes: dec_off(v)=3+2*(v-0xA2FB6AD1); dec_size via 0xE7B5D9F8 (rugptools). Virtual offset space spans all .rio parts.
- Root object: find dword 0x1EDB927C (AF rio @0x41F50, PM @0x85A94, AF ruo1 @0x43670). rugptools parses index from there.
- CRsa object: 9-byte header `6e 03 01 00 00 XX 00 00 00` (word 0x36e, word flags, byte, dword) then crypted block key 0x7E6B8CE2
  (size dwords ^0xC92E568B / ^0xC92E568F, 2-byte checksum every 32 bytes).
- Decrypted heap: dword ?, dword 0xFFFF0000, dword version (AF 0x11, PM 0x12), dword size, dword count, dword extra, then instructions.
  MFC-style class tags (0xFFFF new: word schema + bit-packed name; 0x8000|idx ref). AF instr schema 0x11, PM 0x15.
- PM engine (FUN_00440dd0) loads heaps with first-class schema 0x15 (new) OR older (<0xb / >=0xb paths) -> old AF heaps supported.
- Object refs in heap: class tag, word flag, (flag&0x40 inline object) else enc_off dword + enc_size dword, nested parent ref, tail.
- PM text: UTF-16 table inside each script, JP/EN alternating, separated by 01 00 00 00. AF text: CVmMsg inline cp932 with length byte.
- .ruo patch format (PM FUN_005de150): file = [object data][N x 12 bytes: enc_off(original/new key), enc_off(location in ruo), enc_size(size)][u32 N].
  PM startup enumerates `<rio>.ruo*` (CFileFind) after loading .ici; no signature check. Uninstall = delete file.
- Achievements: CSteamAchievements in exe; scripts call OM_OperatePlatformDependence only from SYSTEM scripts (not story scripts).

## Cut map (AF script -> PM script), from text alignment
- 3eab17 -> 01ad9ce956: SEE_SUMIKA_H, SEE_KASHIWAGI_H, SEE_YUUHI_H_A/B
- 45d98b -> 01b30e953a: SEE_MEIYA_H, SEE_AYAMINE_H, SEE_CHIZURU_H
- 4cfd31 -> 01bef7a5ca: SEE_MIKI_H
- 4f4791 -> (PM?): SEE_MIKOTO_H
- 54cf59: Marimo route + SEE_MARIMO_H; only 9% of its lines exist anywhere in PM (route removed)
- 3a16db: AF CG/scene flag registry

## More format facts (verified 2026-10-09 evening)
- Object placement: AF pos = 2*(enc-K) (3-byte varying prefix, then body); PM pos = 4*(enc-K) (2-byte header [flags][schema], then body).
  Extent raw size (= dec_size()+3) = full stored length incl. prefix/header. Size encode (PM writer):
  enc = (((x>>19)&0xfff) + (x&0xfff) | (x<<13)) + 0xE7B5D9F8.
- PM object header reader FUN_005c7230: flags byte; !(f&4) -> schema byte else skip word; f&8 magic; f&2 word; f&0x80 extra byte.
- .ruo table entry = (key enc_off, K + ruo_filepos>>shift, enc_size(rawsize)). PM shift=2 (4-byte units), AF shift=1.
  Engine consults the ruo hash map for ANY key (new keys beyond base work). Only the last ruo's base is used -> ship ONE ruo.
- Heap = [word archive version (AF 0x14, PM 0x30), word 1] + [0xFFFF0000, version 0x11/0x12, size, count, extra] + instrs.
  First ReadClassList reads a pad byte (archive ver >= 0x13) = number of owner-chain objects pre-mapped (FUN_005ca320).
- MFC tags: 0xFFFF new class; 0x8000|n class index; n<0x8000 (nonzero) existing OBJECT index; 0 = null.
- PM CVmMsg3: base(2 dw), w, w, n1, n2, n1*12 (dword UTF-16 char offset into text table per language: JP, EN), n2*10 (voice idx...).
  Text table follows final CVmRet: dword, then UTF-16 strings starting at char 1, terminated by U+0001.
- PM CVmCall schema 0x15: ... + count byte (0xff->word) + items (word w; w&0x8000 ? CString : objref).
- Achievements: ACH_MUVPM_001..039 via platform cmd 0x168 in a dispatcher CRsa (PM pos 0xd583e320) CALLED FROM ROUTE SCRIPTS
  (e.g. 01b30e953a instr 1953, 01ad9ce956 instr 2516, 01bef7a5ca 2425). Rule: never remove/reorder PM instructions; only insert calls.
- PM saves via Steam Remote Storage (cloud). No userdata/<id>/889710 folder exists yet (never played on this PC).
- COptimizedObs = raw oor (Ogg-Vorbis repack) blob; Serialize reads whole stream. AF and PM oor page versions differ.

## Scenes (AF heap, instruction range [start,end) from replay labels in 3a16db menu -> SEE_*_H AccessWrite)
yuuhi_a 3eab17 [1655,2340) | yuuhi_b 3eab17 [2512,3195) | kashiwagi 3eab17 [4981,5311) | sumika 3eab17 [7473,7944)
meiya 45d98b [1881,2364) | ayamine 45d98b [4789,5318) | chizuru 45d98b [7742,7982) | miki 4cfd31 [2194,2665)
mikoto 4f4791 [1804,2227) | marimo_h 54cf59 [2673,2984. See scripts/scenes.py.
PM counterparts: 3eab17 -> 01ad9ce956 (latter half) + 01ab8c3d66 (first half); 45d98b -> 01b30e953a + 01b8c7a482 (Chizuru part);
4cfd31 -> 01bef7a5ca; 4f4791 -> 01b8c7a482. Insertion points via scripts/align.py.

## Tooling status
- rsaparse.py logs events (cdef/rdef/cidx/oidx/null/pad/rcl/ref/ent), ins_res (resolved refs per instr).
- heapwriter.py Slicer: slice any instr range into a standalone heap (+CVmRet), re-defining deps & renumbering.
  Fuzz: 294/294 AF and 411/411 PM random slices verify (scripts/slicefuzz.py).

## Parser status
- rsaparse.py: 52/60 AF heaps parse exactly (count + end-of-buffer). Failing: system/minigame (OM_StartGame, OM_TWF_*), 32a1f9 (CFadeOverStretchAnti inline).

## Next
1. Parse PM heaps (v0x12, CVmMsg3, schema 0x15). 2. Locate AF segment instruction ranges + PM insertion points.
3. Build ruo with: modified PM scripts (call into restored segments) + AF segment scripts + AF assets under new keys (> PM space end 0x1D01xxxxx).
4. Test in a way that does not touch the user's saves/achievements (see plan before any launch).

## Live-test findings (2026-10-10) - FIRST WORKING RESTORED SCENE
- .ruo is mapped at virtual 6 GiB; FUN_005de420 returns the FIRST part containing a position, and the base archive is
  7,786,022,612 bytes -> ruo data must start past 1,343,571,668. ruowrite.py writes data at 0x50200000 in an NTFS sparse
  file (logical 1.34 GB, ~2 MB on disk). Name: photonmelodies11.rio.ruo1 (game folder). ONE ruo only.
- Heap tail (version > 0x11) object refs are load-array tags too -> must be renumbered (Slicer emits the tail).
- Schema-0x15 heaps: base dw1 = in-memory offset of the NEXT instruction (-1 last), fixed up to pointers by vtable+0x20.
  CVmFlagOp branch target (its last stream dword) is also an in-memory offset. Inserting an instruction shifts both.
- In-memory sizes (verified over ALL PM heaps): CVmCall 20+12*nargs+8*nextras; CVmMsg3 (20+12*n1+10*n2) round up 4;
  CVmRet 12; CVmJump/CVmLabel 16; CVmSync 24; CVmGenericMsg 28; CVmFlagOp 32; CVmSound 28..44.
- Header 'extra' field = number of CVmMsg3 in the heap. All PM CVm* classes use schema 0x15 (21). PM has NO CVmMsg/CVmBlt/CVmImage.
- Loader FUN_00440dd0: if FIRST instruction's class schema == 0x15 -> new path (dw1 chain); else legacy path finalized by
  FUN_004411f0 (size walk). PM's legacy CVmMsg is broken in the Unicode build (FUN_004c0160 counts UTF-16 chars as bytes)
  -> NEVER emit legacy heaps; convert AF CVmMsg -> CVmMsg3.
- CVmMsg3 = base(dw1 next, dw2 flags|id) w1 (tail index of msg box = 1) w2 (0) n1=2 n2=#voices; items1 (charoff,0,0) [JP,EN];
  items2 (tail index of voice,0,0,0,0,0). Tail = u32 nchars + UTF-16 table (starts with '\0' at 0; strings '\0'-terminated)
  + u16 nrefs + refs [null, CMsgSelBox, voices...]. AF text (cp932) uses the same control codes (\x03 pause, \x01 end).
- dw2 low 20 bits = instruction id registered in a global bitmap (FUN_004bad80, seen map). PM ids <= 0x1dfd0;
  restored instructions use 0x30000+ (<0x3ffff avoids a warning flag).
- InternalError(831) = VM got a NULL next instruction (FUN_00443050). Seen once when the game auto-resumed a q-save made with
  an older patch (q*.uux are auto-resume saves). A fresh START works.
- RESULT: maketest2.py scene (AF 00007098a5 [1129,1137): CG + 5 lines, 2 voiced) plays inside PM's AF story after instr 17
  of 00ce1abaf2 and returns to PM's next line. Debugger: scripts/dbg2.py (software breakpoints, Ghidra VAs).
- VOICES: COptimizedObs is stored NAKED in both archives (class string "OptimizedObsforR;oor;naked"): the extent (dec_size+3
  bytes) IS the oor stream. Import AF voices byte-for-byte (no header). AF = oor page v0, PM = v1; both use predefined setup
  header #5; PM decodes v0 fine. Verified by per-process WASAPI loopback capture (scripts/procloop.py <pid> out.wav secs):
  restored Meiya line burst ~-22 dBFS over ~-50 ambient. (Earlier wrapped voices were silent.)
- Import closure needs: CRmt (20 objs) and CPmBgm bodies contain MFC object refs (rewrite enc_off/enc_size in place);
  Cr6Ti bodies are self-contained (123/125, check the 2 flagged). AF Cr6Ti schema 3 displays fine in PM (PM uses 4).
- Testing gotcha: PM auto-resumes the last session on launch (q*.uux). Use right-click -> タイトル -> YES, then START.

## Full build (2026-10-10) - scripts/build_all.py, blocks.py
- Sites = PM achievement calls 25-33 (cut H scenes). Each site: ONE inserted CVmCall right after PM's last line before the
  cut; its dw1 (next) may bypass PM's all-ages stand-in lines (land just after PM's last stand-in line, before PM's own
  transition + ACH call + chapter jump). Never bypass ACH/Jump/FlagOp/Ret; checked no gallery CG is lost (CG gallery =
  OM_GetCgRegisterByDatabase list in 00d5836b7e; ACH 37/38 count it). Restored block = AF cut range around the scene
  (lead-in + aftermath), minus replay machinery (replay FlagOp on CBool@5915b + its skipped path, jump to 3a16db,
  AccessWrite SEE flag, labels).
- PM-native conversion rules learned the hard way:
  * typed call args (d==4, w=0x2f1a): PM (archive >= 0x16) looks type names up as ASCII: '低精度実数'->'_float', '色'->'_VCOLOR'
    (else badIndex from FUN_005cf940).
  * CVmSound typ 2/4 needs an extra ref = the effect's oor stream (PM pairs learned from PM heaps; for imported effects
    use the nested stream ref).
  * nested refs inside imported bodies (CPmBgm/CPmEffect -> stream + CObjectOcean; CRmt -> CRimp + data): sizes use the
    parser convention (raw-3); shared objects (CObjectOcean, CRimp) mapped to PM via learned pairs.
  * AF CRmt (sprite) objects are NOT loadable by PM's CRmt reader (PM revision-2 layout: header flag 0x80 + extra byte,
    pre-declared refs) -> calls showing unmapped CRmt are dropped for now (69 in H blocks, 388 in Marimo chapter).
  * AF camera-shake helper 236d4ed: PM successor 676dcc71 takes different args -> calls dropped (visual only).
  * AF sprite helper 1afbc71 -> PM 672040dd (same 8 args, PM extras optional).
  * FlagOps: ops 0 assign,1 add,2 sub,3 mul,4 div,5 mod; 0x42.. compares (0x46 = less-than); target = in-memory offset.
- Builder bug fixed: rcl lookup when the source's first object slot (pad byte) is inside the replayed instruction.
- Parser: GenericMsg w2==0xffff -> name string if printable, else dword (PM form). 247/265 PM heaps parse.
- LIVE TEST: Meiya block (554 instrs) played fully via a debug entry call (P instr 18), voices + imported BGM audible,
  no exceptions, returned to PM. Debugger trace of CVmMsg3 ids (FUN_004be740, [ecx+8]) used instead of screenshots.
## Marimo route (route value 10)
- AF: route var CInt@3ca72f (PM 27b4e919); selector 1 = 514e5d (PM 01aa6fedfe has 9 rungs, Marimo rung removed);
  route chain 3eab17->45d98b->4f4791->4cfd31->54cf59(Marimo, guarded 'route!=10')->5caf15; later chapters have case-10
  branches (5caf15 x2, 5fe2d7, 65a0db x2, 6953ef), ending 6ebf77 does route%=9 before case 1. PM also inserted a 9-rung
  re-selection in 01b10e10d6 (needs the Marimo rung too). PM dropped Marimo +1 at AF 7098a5:3269 (PM 017b6114d2:3736),
  changed AF 6b9fa1:899 Marimo-=3 to +=2 (kept as PM designed; PM 2nd-half selector 01960c2bce keeps Marimo case 10).
- All 11 Marimo parts are in blocks.MARIMO_PARTS; offline build OK (2014 imports, 353 MB).

## Sprites, choices, saves (2026-10-10 late) - FINAL PATCH INSTALLED
- AF CRmt sprites DO load once their CRimp property map is converted (the earlier "not loadable" note was wrong):
  * PM load array for an imported CRmt: [2 C:CRmt, 3 self, 4 owner, 5 CRimti, 6 CRimp, 7 Cr6Ti] + pads; AF tags are right.
  * CRimp (schema 3) = u16 count + [CString key, dword d, value]; d==4 typed (w 0x2f1a, a, len, name, payload).
    AF writes cp932 keys + Japanese type names; PM wants UTF-16 keys and ASCII names:
    ロングベクトル -> _CVector32 (12 bytes), 点 -> _CPoint32 (8). scripts/crimp.py; all 35 sets convert.
  * Verified live: Marimo chapter opening shows AF backgrounds + Marimo sprite correctly. DROP_SPRITES now off.
- Choice text: OM_AddSelector args are ANSI CStrings; PM (Unicode build) shows them as mojibake. builder converts every
  non-ASCII ANSI CString in call/OM args to a UTF-16 CString (only 2 exist: Marimo chapter choice). Verified live.
- SaveError(246) fix: the CVmCall instructions inserted into PM heaps had id 0. Saves (incl. the periodic auto q-save)
  serialize each VM frame's current instruction by id (FUN_00443e10 store branch throws NotSupported on id 0; load
  looks the id up linearly, FUN_00441800). Inserted calls now get unique ids (continuing the 0x30000+ counter).
- Builder fix: a block with no object slot before its tail must emit the pad byte before the tail's null ref.
- LIVE (debug chain of all 20 parts at opening instr 18, Ctrl force-skip, blind for H): ~4100 restored lines,
  0 exceptions, 0 error dialogs, returned to PM. Auto q-save written mid-run. Quick save inside the Marimo chapter ->
  quick load -> correct next lines -> chapter end -> back to PM, 0 errors.
- Not live-tested on purpose: the real insertion sites inside PM chapters (running them would unlock the user's Steam
  achievements). Covered by patch_pm asserts; same call mechanism as the live-tested debug insertion.
- Final: build_all.py <game>/photonmelodies11.rio.ruo1 all -> 20 parts, 12 PM heaps patched, 4208 imports (456 MB).
  Final build smoke-tested (AF opening plays normally, no restored ids, no errors).
- Cleanup: test save folder userdata/<steam id>/889710 deleted (did not exist before testing).
- Uninstall: delete photonmelodies11.rio.ruo1 from the game folder.

## Furigana, two-voice lines, screen shake (2026-10-10, after the user's preview)
- AF CVmMsg flag 0x200000 extension (u16 w): w&4 = ruby string 'base:reading[;base:reading]' (cp932); w&3 = k extra
  entries, each a class list = extra voice (multi-speaker lines); w&0x40 string, w&0x20 dword, w&8 per-entry word unused here.
  PM keeps ruby in the CVmMsg3 text item's 2nd dword (text-table offset of the same 'base:reading' string), and plays
  several voices via n2 entries. builder: MsgExtHeap -> ruby (8 lines) + extra voices (2 lines). Verified live: おはこ over
  十八番; two-voice line plays two clips.
- Screen shake: AF helper 236d4ed(posture, int, wait) and PM 676dcc71(posture, int) both send OM_AddPostureMomentum to the
  BG box; AF's 3rd arg only adds a CVmSync (PM's own AF-scene ports pass (posture, 1) with no wait). Calls now mapped to
  676dcc71 with nargs 3->2 and the 3rd arg removed (raw_repl). CPostureMoment AF schema 4 is read by PM's reader exactly
  like schema 6 (only internal version byte matters); standalone CMoveAcsOngen (schema 3 in both) imported (IMPORT_OK).
  Verified live: 1-second bounce on the BG/sprite layer.
- Builder test hooks: TEST_PARTS="name:afheap:lo:hi" (debug-only parts), ID_BASE env, DUMP_HEAPS env.
- LIVE: test passages + yuuhi_b, meiya, ayamine, miki chained: 1436 lines, 0 exceptions. Final rebuilt + smoke-tested.
- Cleanup: preview/test save folder deleted again (userdata/.../889710).

## Audit, extra adult content, builder bug, gallery (2026-10-10 evening)
- Audit (scripts/cutaudit2.py fuzzy, cutparts.py line alignment AF route heaps vs PM counterparts):
  * Still missing but OUT OF SCOPE: Total Eclipse preview (498b5, 319e45), TSF sim tutorial (5b3e3), ~3,140 lines of
    all-ages island free-roam events (7cea05..a65a9d; AF had a location map, PM linearized it), many single-line PM wording edits.
  * Marimo route reachability: PM keeps Marimo affection (+1 x13, +2 x12) incl. the island partner picker
    (01a5a5500e OM_AskUserSelectExc -> 27e5fc33, Marimo = 7 -> +2/+1 blocks in 01a1a526a2/01a5dbc45a/01a7a1adca/
    01a9727932). Restored rung is last -> Marimo wins ties. Pick Marimo in the picker to get her route.
- Restored 49 more parts (blocks.EXTRA_PARTS): H-scene lead-ins/outs PM trimmed (Yuuhi x2, Kashiwagi, Sumika, Meiya,
  Ayamine, Miki, Mikoto), the Myun x Chizuru scene (45d98b ~7354-7652), adult gags (Kashiwagi chapter, Mikoto morning,
  'ムスコ', Iruma/Piatif 6b9fa1). 'delete' runs = insert-only (land==insert); 'replace' = bypass PM's rewrite
  (checked: no ACH/control; the bypassed gallery CGs 8f9661bd / 9055a8e5 are shown earlier on the same path).
  CBg2d added to IMPORT_OK (same schema 6).
- BUILDER BUG FIXED: PM template Src.map was shared across blocks -> a text-only block (pad one index later) left stale
  pad mappings -> next block's template parent refs pointed at a class entry -> access violation ("CPmE" as pointer).
  convert_block now resets every template Src.map. scripts/validate_built.py checks oidx->object, cidx->class (69/69 OK).
- LIVE: all 69 parts chained (debug): 4,480 restored lines, 0 exceptions. Backlog OK for normally read lines (one odd
  per-char wrap seen only on a line cut off by Ctrl-skip at a choice; AF text already has PM's \x03/\x01 markers).
- Gallery (EXTRAS > Gallery, tabs AF/Adoration/Resurrection/Wallpaper, AF 6 pages x 15): engine-native. Unlock check =
  OM_GetCgRegisterByDatabase (handler 0x43c5b0: game-database string key derived from the CG object). 00d5836b7e only
  counts 159 CGs (achievements). Thumbnail list not found in any CRsa (258 decrypted + 7 extra), memory (no gallery OM
  strings), or text tables (only staff rolls). AF's gallery = 390163 script + CRbx menu + OM_SetSelecterByDatabase.
  Next step if continued: reverse the native CG-mode UI (CSelecterCgModeThumb, create 0x58d7b0) to find its data source.

## Final review (2026-10-10, late)
- scripts/review_patch.py <ruo>: independent check of the built patch (reads only the ruo + original PM heaps).
  14 overridden PM heaps (AF story only) + 70 restored scene heaps + 4,685 imported assets. All original PM
  instructions present/unchanged; no dangling next/branch pointers; all 42 ACH dispatcher sites reachable as before;
  bypassed PM lines contain no FlagOp/Jump/Label/Ret/ACH. Gallery CGs in bypassed lines: 8fba3c65, 8f9661bd, 9055a8e5
  shown elsewhere on reachable lines; 8fca8611 (Mikoto) shown by the restored Mikoto scene via the same PM helper
  27e92633 -> unlocks. Restored scenes only WRITE Marimo affection 27b4e8f5 (+1, AF original) and route 27b4e919;
  other refs are reads (compares). Ids unique, all >= 0x30000; id 0 only on final CVmRet (same as all 247 PM heaps).
  (The one "payload length changed" report at 01aa6fedfe:26 is a class tag becoming an index: benign.)
- App fixes: Turn OFF is always allowed when the patch is in the game folder (before: disabled after a Steam update);
  OFF stash moved to <PM>\AFRestore-off\ (same drive: instant, stays sparse; migrates the old %LOCALAPPDATA% stash);
  build temp file in that sub-folder (never matches '<rio>.ruo*'), removed on failure; write-permission and
  free-space checks; error dialogs on failed moves. Rebuilt dist\AFRestore.exe; GUI build -> byte-identical patch
  (sha1 53e10b6f...), toggles tested (scripts/test_app.py). Current state: OFF.
- LIVE re-test (2026-10-10 ~10:05-10:20): debug chain of all 70 parts (ID_BASE 0x38000) -> 4,516 restored lines traced,
  0 exceptions/error dialogs, returned to PM. Marimo chapter option-2 branch run (+ quick save at the restored choice,
  quick load -> back at the choice, continue): 0 errors. Flag-dependent Marimo lines (AF 54cf59 [487,758) and
  [962,1217), behind CBool 27b4e979/981) via TEST_PARTS: 193/193 lines, 0 errors. => all 4,799 restored lines played.
  Real patch smoke test (AF opening, 60 lines): 0 errors. Save folder restored to pre-test state (only the user's
  own save, unchanged); test q*.uux removed. Patch back OFF in <PM>\AFRestore-off (sha1 53e10b6f...).

## Broken line layout of restored text in English text mode (2026-10-10, afternoon) - FIXED, verified live
- User report (Kasumi test): restored lines showed as narrow 2-5 character lines plus one overlong line (first build:
  even one character per line). Cause: the game's TEXT LANGUAGE was English. English-text players see the CVmMsg3
  second item (EN); restored lines put the Japanese text there. PM's English layout only wraps at spaces, so an unbroken
  Japanese line wider than the box is mangled. With text language = Japanese all restored lines render correctly
  (verified live on the Marimo chapter opening, multi-part and long lines included).
- Not the cause (ruled out): flag 0x62 (on 572 PM lines; the earlier 0x62->0x60 kasumi_h workaround was removed),
  message box, helper mapping,  placement, instruction ids.
- Fix (build_all.py, app_src too): EN item = JP text without  (PM's own EN items never have pauses) and, when
  longer than 28 chars, pre-wrapped with explicit newlines (prewrap(): pieces <= 28, break after punctuation in the
  second half of the window). Verified live in English mode: a 42-char line now shows as 19 + 23 like the JP layout;
  lines <= 28 chars already fit and stay unchanged. EN item with n1=1 (JP only) was tried: English mode then shows
  blank text boxes.
- Testing notes: debug test builds must use a fresh ID_BASE (0x38000+), else the game's read flags from earlier runs
  skip the restored lines. Debug entry 00ce1abaf2@18 = right after the AF opening's first line (id 0x89a), reached after
  the Los Alamos prologue (ids 0x3a0-0x3d8) and the OP movie. Killing the game loses settings changed in that session
  (written to gdb.uuc on a normal QUIT). 00ce1abaf2 has no ACH calls (safe to play).
- Rebuilt dist/AFRestore.exe; full build via the exe (71 scene heaps, 5,021 lines); review_patch: only the known
  benign 01aa6fedfe:26 class-tag note, all ACH sites reachable. Installed ON; stale stash removed; settings patch_fp
  updated. User saves restored to the pre-test state (gdb.uuc kept: holds the Japanese text-language setting).

## Placement audit of all restored parts (2026-10-10, evening) - Kasumi boundary FIXED
- Message ids (dw2 low 20 bits) are shared by AF CVmMsg and PM CVmMsg3 in most AF-story heaps (PM renumbered some
  lines, so ids are confirmed with text similarity). Checked every part: AF line before the range vs PM line before
  the insertion, AF line after the range vs PM line at the landing point, and restored lines that PM still plays.
- kasumi_h (added late, outside the main audit) was off: inserted before PM 3448, but PM keeps AF up to b371
  (AF 3640 = PM 3451) and resumes at b488 (AF 3978 = PM 3457). Result: the pre-scene line played after the scene and
  AF 3978-3981 played twice. Fixed: range AF [3641, 3978) (includes the pre-scene transition 0xac73e1 -> PM 6715dbe7,
  used 45x in live-tested scenes), insert/land PM 3452. The scene BGM still covers the 4 aftermath lines (as in AF);
  PM restores its BGM at 3473 with no line in between.
- All other parts: exact or explained (PM renumbering; marimo_chapter id matches are unrelated lines, 0/13 same text;
  x_6b9fa1_2244's after-line is restored inside the part). Full build: 71 scenes, 5,017 lines, validate 0 bad refs,
  review: all ACH reachable, only the known 01aa6fedfe:26 note. Exe rebuilt; exe build == lab build; installed ON.

## Deep review (2026-10-10, night): AF official patch, asset matching, text checks
- AF's official patch (altfable.rio.ruo1, 487 objects) overrides EVERY AF script; the app read the unpatched scripts
  from altfable.rio. The unpatched release plays the wrong voice take on 459 lines (old clip often reused on another
  line; patch gives each line its own clip, same speaker) and has typos. Restored lines now take text + voice from the
  patched script by message id (build_all.af_patch_msgs; used only if the ruo1 matches size+sha1 17dbeb8a...):
  24 text fixes, 34 corrected voice takes. 5 lines the patch split into timed pieces (text + sync + 0x61 continuation,
  no ) keep their complete unpatched text/voice (a split first piece would cut the line and skip the click wait).
  Structure/staging stays unpatched: the patch adds 432 helper calls, CVmBlt (PM has none) and ruo-only assets.
- All 2,136 voice clips of restored lines are imported byte-for-byte (none mapped to PM objects).
- Asset matching: AF->PM objmap votes below 80% used for 32 objects. Backgrounds (CBg2d) are now reused only when
  byte-identical (2 were different pictures -> imported); CPmEffect/CRmt below 80% are imported (PM re-encoded audio
  and re-laid sprites, so bytes cannot be compared; even 100% pairs differ). BGM kept: durations match within 1-3%.
- Variables: AF CInt 3ca6e7 -> PM 27b4e8f5 matches at all 4 PM spots; CBool 5caf0d/5caf11 -> 27b4e979/981 partly
  (PM linearized the island) - they only select between restored Marimo line variants (both restored, 193 lines tested).
- Checked OK: helper call arg counts all match PM's own usage; no PUA/replacement chars; 26 kanji PM never uses render
  via CreateFontIndirectW/GetGlyphOutlineW (Windows fonts); read-flag bitmap grows to 0x1ffff bytes, ids <= 0x3239d.
- Build: 71 scenes, 5,017 lines, validate 0 bad refs, review all ACH reachable; exe build == lab build; installed ON.

## Revert: asset matching back to PM's copies (2026-10-11)
- The "deep review" change that imported AF originals for non-identical backgrounds (and <80% sprites/effects) was
  wrong: PM remastered those backgrounds for its screen layout, so the imported AF background (0x6deb814f, Marimo
  chapter opening; also used by meiya, miki and 3 extra parts) rendered small and skewed in game. All of it reverted:
  CBg2d/CRmt/CPmEffect use the PM mapping again (imports back to the pre-change set: CBg2d 1, CPmEffect 8, CRmt 1203).
  Kept: AF official patch text/voice corrections and the Kasumi boundary fix.
- Verified: background/CG displays per part equal the AF ranges (674 = 674, no part differs); 122 background refs map
  to PM backgrounds, 1 (no PM copy) imported. Full build review: all ACH reachable; exe build == lab build.

## Marimo chapter hut/ceiling shots fixed against the 2007 original (2026-10-11)
- Compared live with the 2007 game (its prologue patched to jump into 54cf59; user screenshots of each shot).
- Wrong background pair: objmap paired AF 0x7696d25b (night hut; Marimo @364, meiya @2371, miki, 2 extra parts) with
  PM 0xc2c5cf29 on 1 of 2 votes; c2c5cf29 is another picture (1400x820, the 5/5 pair of AF 0xb6f2a731). PM's own port of
  AF 45d98b@1777 (same background, same camera 21,45,0,864) uses 0xdc1cabef -> build_all.OBJMAP_FIX.
- Missing foreground: AF's two "special" hut backgrounds (0x7696d25b, 0x6deb814f; CBg2d flag 0x01000000) contain the
  foreground (tree trunk, canopy bed, plant, post). PM converted them to plain backgrounds (dc1cabef, c9258e0f) and
  draws the foreground as three overlay layers after every background call: helper 67fb353f (CAC7Ti, CCharBox2
  27b4ee85/27b4ed65/27b4eecd) + OM_SetVarData depth per box; the next background call replaces them. Without them the
  bed's pale curtain edge showed as a white strip and trunk/bed were missing. build_all.BG_OVERLAYS copies PM's own six
  instructions (01b30e953a@1856-1861 night, 0192586282@18-23 day) after each restored hut background: 9 shots in
  marimo_chapter, meiya, miki, x_45d98b_1809, x_4cfd31_2066, x_7cea05_1276. The AF camera values were right all along
  (room features match the 2007 screenshots within ~1%).
- Ceiling close-up (AF 401-407, billboard helper 39b5f9d -> PM 86697a41, depth 1000): AF camera distance 168 made the
  picture 21% of the screen in PM, tilted. On PM's billboard the picture size scales with the distance (0.905 of the
  screen at 720); the 2007 shot is ~1.25x a full fill -> build_all.CAMERA_FIX distance 1020, AF's tilt kept (rotation
  45 -> 4 over 600 ms). Verified live: matches the 2007 screenshots, tilt works.
- Builder bug found on the way: copying the same PM instructions twice reused the source index map, so each repeated
  OM_SetVarData skipped its load-array entry (index drift -> wrong references -> crash at the section start in one test
  build). Each copy now gets a fresh map, and convert_block fails if the parsed load array size != builder allocation.
- With dc1cabef referenced early the engine raises a handled first-chance PAVCArchiveException while reading ahead
  (also with c9258e0f in that slot); no dialog, picture loads; same reference form as 26 PM scripts.
- Build: 71 scenes, 5,017 lines, 9 overlay insertions, validate 0 bad refs, review all ACH reachable (known
  01aa6fedfe:26 note only).

## Restored scenes checked against the 2007 game, scene by scene (2026-10-11, evening)
- Method: a scratch copy of the official AF patch with the prologue's last jump retargeted to a chapter script and the
  chapter's first FlagOp(s) retargeted to the scene's anchor line, so the 2007 game starts inside a restored scene
  (Kasumi's chapter 514e5d starts with 6 FlagOps; all 6 retargeted). PM side: one debug build per heroine. The user
  compared each scene in both games; all scenes confirmed.
- **AF official patch staging adopted.** Between two lines where the patched script's staging differs (and holds only
  calls / syncs / sounds / messages), the patched instructions replace the unpatched ones (build_all
  `patched_stretch`; 277 stretches): the patch's close-ups, backgrounds, shakes and transitions. Replay paths,
  Jump/Label/Ret and AccessWrite are dropped as in the unpatched blocks.
- **Patch-only objects.** Objects that exist only in the patch file are mapped at virtual position 0xD0000000
  (`objio.map_patch`), and `body_refs` accepts their 0xC118 refs. Before this, two patch-only sounds were emitted
  without an audio stream and PM froze on the scene that plays them; 12 missing sprite pieces / streams came in too.
- **Scene endings.** (a) Three SITES ran past a route guard (FlagOp on the route CInt 3ca72f): yuuhi_b, kashiwagi and
  meiya ended with a few seconds of another heroine's route (background, sprites, BGM). Ends moved to the guard
  (3201, 5312, 2432). (b) The landing skipped too little of PM's all-ages stand-in: after the restored scene PM played
  its own closing (a CG flash, Mikoto's screen shake, a BGM change, a fade to white, or a replay of the last shots for
  ayamine/sumika). Now: land on the PM line that plays the AF block's end anchor (ayamine 4479, sumika 4955), else on
  PM's chapter-end helper 670d5aaf right before the achievement call. (c) kasumi_h: PM's kept lines AF 3978-3981 play
  over PM's stand-in pictures (one PM-only); they are restored too (AF [3641,3982), land 3467).
- **Sounds.** objmap paired some restored sounds with other clips (lengths x0.66, x0.78, x1.5, x16; birdsong in a
  cave). A sound now uses PM's clip only when its audio packet count is within 3% (or 2 packets) of AF's; PM's
  re-encode gives the same recording 1-2.3% fewer packets (every restored BGM pair: 0.977-0.990). An exact-count rule
  sent every BGM to AF's own clip and restarted the song PM was already playing before the scene.
- **Imported CGs.** PM draws an imported AF picture (raw Cr6Ti without an identical PM copy) at 1/1.2 of the size of
  PM's own copy; cameras framing one get distance x1.2 (`IMPORTED_IMAGE_ZOOM`).
- **Mikoto's scene.** The official patch re-staged it as 3D billboard close-ups (helper 39b5f9d -> PM 86697a41, depth
  1440). In PM those stayed a small whole picture inside black bars whatever the camera call said (the billboard
  helper gives the picture an exclusive camera; camera mode 65 instead of 1 did not help either). For this scene only
  (`BB_TO_BG`) the billboard calls become background calls (PM 27e92633, args (picture, 2)); the following camera
  distances are multiplied by 1000/depth, 8-arg camera calls are cut to PM's 6 (as PM's own ports do), and CG shots
  framed below 720 are raised to 720, centred (`FILL_FLOOR`; 720 fills PM's 16:9 screen, measured in game). 34
  billboard shots converted, 23 raised. The patch's other shots (its forest background lines, shakes) are kept.
  Other scenes' billboards (depth 1000 / 1200 / 1360 / 1440) were checked by the user and left as they are.
- Tried and reverted: converting AF's 8-arg camera calls to 6 args everywhere (Meiya and Yuuhi use 11 of them and
  were approved as they were).
- Debug builds: the entry point moved from the AF opening's instruction 18 to 16. The opening starts an ambient sound
  loop at 16 and stops it at 19, so every test scene played with it.
- Lab and app builder files are identical now (paths from env `AFR_OUT`, `AFR_AF_RIO`, `AFR_PM_RIO`, defaulting to the
  lab layout).
- **Kasumi's lead-in and aftermath.** Her scene was added after the lead-in/aftermath audit, so PM's trims around it
  were still in place: AF 3593-3616 (PM rewrote it as 4 lines, PM 3415-3429) and AF 3631-3636 (1 line, PM 3447)
  before the scene, and AF 3991-4087 after it (to the end of her route section; PM has none of it and goes from its
  closing to the achievement call). Found by line alignment only (identical / missing), restored as
  x_514e5d_3593 / x_514e5d_3631 (replace) and kasumi_h extended to [3641, 4088) landing on the achievement call (3475).
  The rest of the chapter's differences are single lines or short runs the original audit left as PM wording edits.
- Build: 73 scenes, 5,082 lines, validate 0 bad refs, review: all achievement triggers reachable (known
  01aa6fedfe:26 note only). exe build == lab build (sha1 a5c198cecae063282abf893196dfbead055f5b97).
