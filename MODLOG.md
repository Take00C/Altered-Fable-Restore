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

## 1.1.0: English text, censored CGs, lead-in pictures, updater, Linux (2026-11-07)

- **English text (optional).** `entext.py` reads the player's own afhook.pkg (the fan translation of the 2007 release:
  13-word header, magic 0x8D120AB6; entries id, len(src)+1, len(tr)+1, src, tr; cp932, exact full-line match) in
  place. A restored line looks up the builder's text, then the unpatched and the patch text; the English goes into
  CVmMsg3 slot 1 (PM's English slot) without pre-wrapping, with PM's punctuation (U+3000 -> space, curly quotes ->
  ', U+FF5E -> ~), \x03 pauses dropped, and the speaker name in PM's English (`pm_name_map`: PM's own 2-slot lines,
  kept where >= 98% of them agree). 4,994 of 5,082 restored lines get English; the 86 lines the package lacks (all in
  marimo_chapter AF 54cf59 504-752) keep the pre-wrapped Japanese copy. Without a package (env `AFR_EN_PKG=''`, or
  none next to altfable.rio) the patch is byte-identical to the build without this feature. The package is never
  copied or shipped.
- **Censored pictures.** A whole-game pixel comparison (lab-tools/out/research/censored-cg and asset-sweep: every AF
  base/patch picture against PM's, statistics only) found PM pictures with an edited region. They are replaced in
  PM's archive itself (ruo override of PM's key `K + (pm_off - 3) // 2`), so PM's own scenes and the gallery show the
  original too:
  - 17 direct overrides (`CG_OVERRIDES`, data `00 04` + AF body): the hot-spring CGs (AF 7098a5 / PM 017b6114d2
    6521-6931, 10 pictures), AF 6b9fa1 / PM 01715ad2b6 (2), three gallery CGs and two smaller edits. Every one has
    the same display size as PM's (stored size x f32 scale, e.g. 2604 x 0.5 = 2344 x 0.5556 = 1302 px) within 0.25 px,
    except the two gallery CGs 8f48daa7 / 8fc2711d, whose PM 2/3-scale copies are 1-2 px larger.
  - 10 rebuilt crops (`CG_RECROPS`, `cgcrop.py`): PM's 1028x604 close-ups cut from the edited hot-spring CG (PM
    017b6114d2 6764-6899) and its 2344x1745 16:9 cuts of the tall 45d98b CGs (PM 01b8c7a482 2039-2115). No AF object
    has their geometry, so the build resamples the AF original into PM's window (bilinear; window from the crop search,
    PM pixel centre (u+0.5)/k - 0.5 + x) and re-encodes it with PM's coder (Cr6Ti Opaque1, depth 0x07070707) under
    PM's header. The decoder equals the reference decoder bit for bit; re-encodes are within 2/255 per channel. The
    encoder never uses 'copy the pixel above' in row 0: PM's Opaque1 drawer (FUN_0057e490) reads an uninitialised
    line buffer there, and age's encoder never does it (0 of 1,955 originals). Against
    PM's crop the rebuilt one differs where the sweep flagged PM's edit (6.5-45% of blocks; bfc6703d, a close-up of
    the edited region, is the 45% one), median block difference 1.7-3.3/255 (bfc6703d 9.1).
    About 30 s per build.
  - Not changed: PM pictures that equal another AF variant or the official patch's version (152 pairs, e.g. PM
    c86c2f37 = the patch's bca3bcd3), PM's 16:9 widenings (1280x750, band differences at the sides), one layered
    background PM flattened (31aefdc9, PM adds its own overlays), one thin band (1d197d7).
- **Lead-in pictures.** Six restored parts start with lines that played, in PM, over a picture the 2007 game did not
  show there (the camera inventory, lab-tools/out/research/camera-inventory: another picture, PM's crop of it, or PM's
  copy framed by cameras rewritten x1.2 for the imported AF picture): x_45d98b_7366/7384/7477/7593/7601 and
  x_6b9fa1_2244. They now start by replaying AF's last picture call before the part and its last camera + apply pair
  (`LEAD_IN`, 3 instructions each), the apply with duration 0 (AF's timed move had ended before the part's first
  line; x_45d98b_7366's was a 3 s pan). The replays take instruction ids from their own range (0x3F000+) and import
  their pictures as their own copies under keys from their own range (NEW_KEY_BASE + 0x7000000+), so every id and
  every key 1.0.0 assigned is unchanged (checked against the 1.0.0 build: 0 id shifts in all 73 parts and all PM
  insertions). Drawing ids or keys from the shared counters had shifted the ids of every later part by up to 18 and
  moved 14 imported objects, which would break read marks and sessions resumed from 1.0.0. The Kashiwagi lead-ins (3eab17 4957-4977) are left alone: PM shows another
  background for that whole conversation, and its own lines between the restored ones would switch back and forth.
- **Billboards over 2 MiB (open, test build).** PM never shows a picture over 2 MiB through its billboard helper (all
  such PM pictures use the background helper). Mikoto's patched close-ups are 2604x1836/1838 like every other
  restored billboard, but 2.1-2.8 MB (14 of her 19 pictures); every other restored billboard is <= 1.9 MB except two
  Yuuhi B shots (2.14 MB, before restored lines 234 and 276). `AFR_TEST` builds (default build unchanged):
  `bbnative` (Mikoto keeps the patch's billboards), `bbsmall` (such pictures re-encoded under 2,000,000 bytes, same
  size, tolerance 2-6/255; an imported one is re-encoded at import, a PM copy such as gallery CG 8fca8611 = AF
  49a1872f stays PM's object and that object is overridden with the re-encode, so gallery unlocks still work), `cam8` (AF's 8-argument camera 1c54b13f -> PM's 8-argument 8a8b0e89; PM calls it 42
  times, always with 8 args, and 27e92e99 12,740 times, always with 6), `hdr4` (imported pictures with PM's header
  00 04, no x1.2).

## 1.1.0: engine-code fixes (2026-11-07)

Sources: the code-level audit of the helper mappings (lab-tools/out/research/helper-audit/CONFIRMED.json, evidence in
the folders next to it) and the reverse engineering of PM's billboard / camera / picture code
(lab-tools/out/research/billboard-re/SYNTHESIS.json). Default build, every restored part. Checks and scripts:
lab-tools/out/review-1.2 (verify_ids12.py, fixcounts.py, dis.py, shakes2.py, syncsurvey.py, bshake.py, cmp_f1.py,
pm_shakescan.py, pm_preshake.py).
- **Colour flash (AF 318c15 -> PM c6f08841, HELPER_OVERRIDE).** objmap's 2/4 tie mapped AF's flash-layer helper
  (CLayerSimpleFlush) to PM's 2-arg transition 27e9379d, which plays no flash. c6f08841 is PM's identical copy (same 12
  instructions; PM calls it 16 times with 6 args; PM's own port of the scene calls it with the same values). One call:
  yuuhi_a #4, the opening flash.
- **8-arg camera (AF 1c54b13f -> PM 8a8b0e89, HELPER_OVERRIDE).** 27e92e99 never sets OM_SetWorldCamera +0x0c..+0x14,
  the camera position that AF's P5..P7 carry, so 11 shots had their position reset to 0 (meiya 496-544, yuuhi_b
  476-483). 8a8b0e89 is PM's 8-arg port (42 PM calls, all with 8 args). Mikoto's 8 -> 6 cut is removed (her P5..P7 are
  0); the distance rewrites of the 4th argument stay. Result: 18 calls, all with 8 args, and no 8-arg 27e92e99 call left.
  The earlier "tried and reverted 8 -> 6" (2026-10-11) sent the same messages as the build, so it compared nothing.
  AFR_TEST cam8 is removed.
- **Screen shock (AF 2f9782f case 25).** PM's 674ed45d case 25 points at two blank curves (no displacement), so the 15
  restored shocks showed nothing. Each one becomes PM's own port pair, copied from PM 01ad9ce956 2148-2149
  (`SHOCK_PM`): OM_AddPostureMomentumEx2 with its inline 5-segment shake curve (500 ms limit), then
  27e99af5(0,0,0,0,200). Sites: marimo_chapter (12), marimo_5fe2d7, x_6b9fa1_2244, x_7cea05_1276. This is used for both
  kept AF calls and patch staging. PM's 500 ms is kept, as in PM's ports (AF's d was 100-400 ms). The copied curve is
  byte-identical to PM's; the posture differs only in its class tag. Other cases are unchanged.
- **Shake waits (AF 236d4ed).** Correction to the 2026-10-10 note: the AF arguments are (posture, wait flag, unused).
  A wait flag of 0 means "wait until the shake ends"; the 3rd argument is never read, so dropping it is harmless. AF's
  helper stores the posture in var 319679 and syncs on it, but PM never stores into its copy 27b4f043, so the restored
  syncs on it returned at once. AF's own form would need the inline posture shared by two instructions, which no PM
  heap does (0 back-references to inline objects). The waits are therefore timed waits: PM's standard
  CVmSync(null, b=16, v) (4,036 in PM, copied from 01ad9ce956 #29, `SHAKE_WAIT_PM`). Each wait lasts as long as the
  shake itself, i.e. its longest curve: CMoveAcsOngen +0x48 when +0x44 != -1 (pm.exe FUN_005772c0 / FUN_004831e0, tail
  order from the reader FUN_00577770). The waits (built heap indices: shake call -> apply -> wait, see the next item):
  - ayamine #335 -> #336 -> #337: a wait added after the only call with wait flag 0, 350 ms;
  - mikoto #345 -> #346 -> #347 (1.0.0's #343): 1400 ms;
  - kasumi_h #72 -> #73 -> #74 and #84 -> #85 -> #86 (1.0.0's #72 and #83): 200 ms each;
  - kasumi_h #404 -> #405 -> #406 (1.0.0's #401): 400 ms.
  The 15 b=33 syncs on the var stay no-ops, as PM's own 107 are.
- **Shake start (all 22 restored shake calls, since 1.0.0).** In AF a shake starts at its call: 236d4ed sends the OM
  and 142 AF calls are followed directly by a text line. PM's CParseBgBox queues OM_AddPostureMomentum instead (receipt
  map 0x621570 -> FUN_004d7e00 -> FUN_00499d70, queue entry marker 0) and dispatches it only at the next
  OM_BecomeCompositionToCurrent or OM_ParseScreenTrigger (FUN_0049a120, marker 1; drain FUN_00498c20); CVmSync(null,
  b=16) is a pure timer (also billboard-re SYNTHESIS proven[14]). So the restored shakes played only at the next
  background / camera apply: the five timed waits above passed on a still screen and the shake then started together
  with the background change, and 19 shakes came 1-20 lines late (previous build: sumika #389, 16 lines; marimo_chapter
  #1269 played together with the Ex2 shock at #1274). PM's own scripts follow 502 of their 503 calls to 676dcc71 with
  an apply before any line or wait (the other one ends a helper, right before its Ret), 241 times as 676dcc71 followed
  directly by 27e9379d(0, 0) (67 of those then a timed wait). Every restored shake call is now followed by that apply,
  copied from PM 01ad9ce956 #28 (the instruction right before `SHAKE_WAIT_PM` #29; `SHAKE_APPLY_PM`, checked at
  start-up), then by its timed wait where it has one. Before each of the 22 calls no picture or camera call is pending
  since the previous apply (before the fix, only mikoto's second shake had something queued: her first shake, which
  now starts at its own call), so the apply starts only the shake. 12 of the calls follow a timed apply directly
  (100-3500 ms); PM's own pairs do the same 57 times (durations up to 5000 ms). Checks in review-1.2: bshake.py (all 22
  calls: apply next, 0 lines before it), cmp_f1.py (the 22 applies are the only difference to the previous default
  build, each canonically identical to PM's #28), pm_shakescan.py and pm_preshake.py (PM's own calls and pairs).
- **IDs and keys.** Instructions added after 1.0.0 (the 27e99af5 of each shock pair, the apply after each shake call,
  ayamine's wait: 38) take ids from their own range, `ADD_ID_BASE` = 0x3F100 (lead-ins: 0x3F000+); they are used
  0x3F100-0x3F125. A 1:1 replacement keeps the 1.0.0 id; the Ex2 of a shock pair counts as one. Nothing allocates keys.
  verify_ids12.py against 1.0.0 (release-final2.ruo1):
  - 9,652 instruction ids kept, in order, with 0 shifts in all 73 parts; 38 added ids, all unique;
  - 38 changed instructions, exactly the fixes: 18 cameras, 15 shocks, 4 waits, 1 flash (FlagOp targets compared by
    target id: byte offsets moved, no target changed, no branch into an added instruction);
  - the PM heaps and their 73 inserted call ids are unchanged;
  - all 5,185 1.0.0 keys are present and the scene keys are unchanged;
  - no non-scene object in the main key range changed.
- **AFR_TEST.** bbnative and bbsmall are kept (by code, bbsmall changes no code path). cam8 and hdr4 are accepted as
  aliases and kept in AFR_TEST as given, because the scene tester (scenetest/, not changed here) still builds
  'bbnative,bbsmall,cam8' and 'hdr4' and checks its build summary against those names: cam8 is a no-op (it is the
  default now; an AFR_TEST=cam8 build is byte-identical to the default) and hdr4 = nozoom (its header part is proven to
  change nothing). New flags:
  - `bb21`: BB_TO_BG keeps AF's 2nd argument, 27e92633(picture, 21), so the cameras' tilt is drawn (CONFIRMED.json
    finding 5);
  - `nozoom`: IMPORTED_IMAGE_ZOOM = 1.0;
  - `zoomall`: the x1.2 also applies to PM's Cr6Ti copies. By code, an import and its PM copy are drawn the same size,
    so the import-only rule is inconsistent.
  nozoom (or hdr4) and zoomall exclude each other. Each flag was smoke-built once; 'bbnative,bbsmall,cam8' and 'hdr4'
  were also built in full once (exit 0).
- **built/.** A DUMP_HEAPS build now removes heaps in lab-tools/out/built that are not parts of the build, so
  validate_built.py checks exactly the build's heaps (73 in the default build; three 2026-10-11 test heaps, fxtest,
  mshot and mikoto_cal, had been counted as well; copies are in review-1.2/before).
- **To check in game:**
  - the yuuhi_a opening flash;
  - meiya 496-544, where the view should be about 2.2-2.6x wider;
  - yuuhi_b 476-483;
  - mikoto 453 (mode 64; built #458) and yuuhi_b 476 (mode 65): PM never calls 8a8b0e89 in modes 64-95;
  - marimo_chapter #514 (shock);
  - ayamine #335, mikoto #345 and kasumi_h #404 (built indices): the screen should shake first and the background
    change only after the shake;
  - any restored shake, e.g. sumika #389 or kasumi_h #186: the shake should come at its own line, not at the next
    background change.

## 1.1.0: camera modes and framing from the engine code (2026-11-07)

Sources: the traces and verifications in lab-tools/out/research/framing2 (pm-projection, af-projection, camera-modes,
verify-*, review-camera, review-integrity); builder work in framing2/implement, then the corrections in framing2/fix
(scripts, builds, checks); the shot table framing2/shots_new.csv. Default build lab-tools/out/v11.ruo1 (sha1
f85c4b64...), every restored part. The owner's in-game result the same day, side by side with the 2007 game:
Mikoto's native billboards (AFR_TEST bbnative,bbsmall,cam8) "close to perfection", except one or two lines that
first showed the whole picture inside black bars; the release form (BB_TO_BG) "zooms in super close".
- **The default build is the owner-checked build plus the fix for those lines, nothing else.**
  - The checked build (AFR_TEST bbnative,bbsmall,cam8 on the builder of that afternoon) has sha1 88ca03a8. The
    default without its kept-camera inserts, AFR_TEST nokeep, rebuilds it byte for byte (checked).
  - The default adds exactly three instructions, all in Mikoto: built #318, #325 and #525, ids 0x3F200-0x3F202. The
    other 72 parts are byte-identical to the checked build, and Mikoto's 608 instructions are unchanged around the
    inserts (fix/cmp_masked.py, review-integrity/cmp_parts.py).
  - So Mikoto's patched close-ups stay PM billboards (86697a41, 3D path). BB_TO_BG runs only with AFR_TEST `bb2bg`
    (bb21 implies it); `bb2bg,nokeep` rebuilds the 1.1.0 release byte for byte (sha1 bbc1ac7a, checked).
  - Why the release framed too close: BB_TO_BG used distance x 1000/depth, while the code-exact equivalent of a
    billboard at depth D on the 2D path is x 720/D, so it was 1.39x tighter.
  - The billboard re-encode (BB_SHRINK_LIMIT, 2,000,000 bytes) stays on, because the owner checked the build with it,
    although no code path depends on a picture's byte size. It affects 13 pictures: Mikoto's 10 imports, Yuuhi B's two
    (42e848d3, 448ff3e5) and PM's gallery CG 8fca8611, which is overridden under its PM key and so changes for the
    whole game, gallery included (re-encode tolerance 2-5/255). Every 1.0.0 key keeps its object.
  - Correction to an earlier note of this section: "AFR_TEST=bbnative,bbsmall,cam8 gives the same Mikoto heap as the
    default" was true only because those flags had become no-ops. The build the owner checked is reproduced by
    AFR_TEST=nokeep, not by those flags.
- **Camera persistence (CAMERA_KEEP), the root cause of the black-bar lines.** Proven by code:
  - AF keeps one camera per screen across picture calls. 39b5f9d / c93a57 send no camera message, and box+0x8c8 is
    written only by the camera code (Vm60 FUN_100381d0 / FUN_10043a20).
  - PM gives every picture call a new CComposition (FUN_004d7f70 -> FUN_004d61a0). Its camera starts at position 0,
    angles 0, zoom 720 (constructor FUN_00493fc0), and FUN_004948e0 copies no camera.
  - So a 2007 shot that relied on the kept camera opened on PM's default view: a billboard at depth D shows the whole
    picture at 720/D inside black bars; a background shows a wider view. A shot whose first camera call is a move ran
    from (0, 0, 0, 720) instead of from the kept camera.
  - PM's own ports of these AF shots do what the inserts do. 01ab8c3d66@5409-5411 (yuuhi_a shot 0): billboard, then a
    mode-1 set to AF's kept camera (18, 81, -37, 1560), then the apply.
  - Start-store modes 64-95 work the same in both engines and are unchanged. The call only stores a start
    (AF FUN_1003ed90, PM FUN_004dc210), the next move keeps it, and PM's commit FUN_004dfde0 writes it into the
    composition's camera when the apply starts.
  The builder tracks AF's camera through each part. The start state comes from AF's script before the part (the
  official patch's script where it has the line before the part). Patch staging and lead-in replays are followed in
  output order. Per picture call:
  - Case A, no camera call before the closing apply: right after the picture call, an instant set to the kept camera
    in PM's idiom, 27e92e99(x, y, rot, dist, 1, 0), or 8a8b0e89(.., 1, cx, cy, cz) when the kept camera has a 3D
    position (none does). PM follows 9,379 of its 9,628 picture calls with a mode-1 camera call first.
  - Case B, first camera call a move under an apply longer than 0 ms: right before the move, a start store
    8a8b0e89(x, y, rot, dist, 64, cx, cy, cz). The move then runs from the kept camera while the picture fades in, as
    in 2007; PM's own scripts do picture -> 64/65 start -> move -> apply 192 times. A mode-1 set in the same block would
    not work: a second call on one composition before the apply replaces the target and takes the start from the
    composition's default camera again (FUN_004dc210). 8a8b0e89 64 sends AF's own start-store messages; 27e92e99 65
    would also send SetCpsObPropertyEx4(17, 1.325), a lighting slot that AF never sends.
  - The distance follows the default zoom rule (below) for the shot's own picture, as a camera call there would.
- **In the default build the inserts are made only in Mikoto (`KEEP_PARTS`), the scene the owner checked:**
  - Shot 56 (#524-526, two lines): a billboard at depth 1440 and a 400 ms apply with no camera. The checked build showed
    PM's default view, the whole picture with 51% of a 1024x600 screen black (68% on 1280x720). It now opens on
    2007's tilted close-up (95, -21, -133) at 2390, the framing of shot 55 just before it. On the 1024x600 model this is
    the only camera state of the checked build with black bars, which matches the owner's "one or two lines".
  - Shots 31 and 32 (#317-319, #324-326): backgrounds. They showed PM's default view of the background (51% of the
    picture on 1024x600, no bars) where 2007 showed a 5% close-up, and now open on shot 30's close-up (-175, -132, 0)
    at 2765.
  - AFR_TEST `keepall` makes all 65 inserts: case A 6 (also yuuhi_b pictures #570 and #573, x_45d98b_7384 #64; default
    build indices), case B 59 (yuuhi_a 17, yuuhi_b 26, marimo_chapter 4, meiya 3, x_3eab17_* 5, kashiwagi, sumika,
    ayamine, kasumi_h 1 each). Without them, 50 of the 58 case-B shots on CG pictures open their move, during the
    fade-in, from PM's default view with black bars on the 1024x600 model (yuuhi billboards at depth 1000: 8.5% of
    the screen). These scenes were approved in October and were not part of today's check, so the inserts there wait
    for the owner. Every planned insert, emitted or not, is listed in build_manifest.json (`camera_keep`) and
    framing2/fix/keep_list_*.txt; shots_new.csv has a 'pending insert' row for each one not emitted.
  - AFR_TEST `nokeep` makes none.
  - Ids: the inserts take ids from their own range, `KEEP_ID_BASE` = 0x3F200 (also inside a lead-in replay). Before
    this they shared ADD_ID_BASE and moved the ids of 1.1.0's 38 added instructions (e.g. ayamine #336 0x3f102 ->
    0x3f134). Now those keep 0x3F100-0x3F125 whatever the inserts do (checked in the default and keepall builds).
- **Open questions of the camera-modes trace:**
  - The three kashiwagi start + mode-32 pairs without a picture call (#245/246, #358/359, #363/364): not changed.
    PM routes the mode-32 move to a new composition copied from the shown one (FUN_004d61e0 -> FUN_004d6bb0 ->
    FUN_004d6d40: memmove of +0x1d0..+0x40f, which holds the camera; disasm 0x4d7187, verify-camera-modes/adv). So the
    move starts from the camera on screen; the stored start is dropped at the commit. Only s31 shows it: the 800 ms
    move at #358-360 opens with 14.8% more area than 2007 (no bars); the other two differ by 0% and under 1%. Changing
    the move to mode 0 (transition 4, same composition) would use the stored start but changes the transition, in a
    scene the owner approved; left as it is.
  - SetDrawRatio in marimo_chapter shot 28 (#574-582, modes 65 + 128): nothing to port. AF's d13d87 modes 32-63 /
    96-127 send OM_SetDrawRatioAsParseWnd(null, 256) and modes from 128 send (CMimeFlat16LimitOne, 272); AF's
    handler FUN_10043270 (implement/af_setdrawratio_probe.txt) stores that mime at box+0x1ba8 as the curve of the
    parse window's transition alpha (FUN_100431e0). PM's CParseBgBox maps the message to FUN_00405600, which only
    returns 0, so in PM mode 128 plays as mode 0.
- **Zoom rule: the default keeps the rule the owner checked** (the 1.1.0 rule): x1.2 on cameras framing an imported
  picture, AF's values on PM's copies, FILL_FLOOR on Mikoto's backgrounds framed at 576 / 600 (whole CG, centred).
  - Proven by code, both engines: a picture at depth D is drawn at dist / D, at canvas x Cr6Ti scale (the same for an
    import and its byte-identical PM copy). 2D path (id 2): pans clamped to the picture, rotation not read, PM adds a
    near plane. 3D path (id 0x15): perspective, no clamp. The 2007 screen is 1024x600 (AF's box body;
    OM_SetWorldSXY(512, 300)).
  - PM's camera screen is 1024x600 too, by PM's own code and data (review-camera): its init heap 004fd064ca sends
    OM_SetWorldSXY(512, 300) (#10, handler FUN_004db700 -> composition +0x254/+0x256); OM_SetBodySize / OM_SetBoxPos
    read vars 0x456ff / 0x45715, defaults 1024 and 600; PM's saved CParseBgBox body is 1024x600; PM frames its own
    1280x750 widenings at 576, exactly 1024x600. On a 1280x720 screen 1,752 of PM's own 2,749 camera states on Cr6Ti
    backgrounds would show black areas, on 1024x600 2 (review-camera/pmown.txt).
  - PM's own ports keep AF's exact values on PM's copies: 01b8c7a482@4442-4444 = Mikoto shot 41 (billboard on PM's copy
    at depth 1440, 27e92e99(0, 9, 0, 1440, 64) -> (0, 9, 54, 1776, 32)), 01ab8c3d66@5409-5410 = yuuhi_a shot 0 (1560).
  - The owner's check agrees (inferred from what was and was not reported): on a 1280x720 screen the checked build
    would have shown 12-15% side bars on eight static Mikoto shots for many lines (38-40, 43, 44 at 720; 64-66 at
    744); only shot 56 was reported, the one state with bars on 1024x600.
  - Still open: x1.2 on imports is measured in game (October) and the owner found Mikoto's imported billboards right
    with it, but by code an import and its PM copy are drawn alike. Decisive check, AFR_TEST zoomall: yuuhi_a shots 61
    / 62 (#539-541 / #543-545) have the same 2007 camera (0, 45, 0, 1008), 61 on a PM copy (default 1008, zoomall
    1210), 62 on an import (1210).
  - FRAME_RULE is AFR_TEST `framerule` only: x1.2 on every CG camera (PM's copies too), raised to cover a 1280x720
    screen, no FILL_FLOOR. It rests on the 1280x720 inference above and was not checked in game. framerule,keepall
    gives the unconfirmed default of 18:17 (v11 sha1 09aefab2) apart from the kept-camera ids (checked).
- **marimo_chapter shot 18, PM's near plane (AFR_TEST `nearplane`, not in the default).** PM's 2D path (FUN_00496bc0,
  pm.c 118536-118566) uses D = max(Zp, clamp(trunc(dist/7 + 6/7), 180, 1440)) and x_screen = s + dist ((u - cx) / D
  - 16 x / 8192): the picture term is divided by D, the pan term is not. AF has no near plane. Shot 18 (#520-523, one
  line, background, AF 5592 x1.2 = 6710) gets D = 959, so PM's view centre on the picture sits 1.33x further out
  (PM -206, 365; 2007 -155, 274) and the 2007 close-up lies wholly outside PM's view (review-camera/s18.txt); the
  next shot, 19 (4954), is below the near plane and centred like 2007. From dist 10074 up D is 1440, so (x Zp/1440,
  y Zp/1440, dist 1440/Zp) reproduces the camera exactly: (-55, 98, 0, 13420). The pan clamp (on Zp) leaves those
  pans alone (checked in the builder). It is the only camera in the parts above the near plane. Present since 1.0.0;
  waits for the owner.
- **AFR_TEST** (test builds for the scene tester; the default needs none):
  - `keepall` (kept-camera inserts in every part), `nokeep` (none: the build the owner checked), `framerule`,
    `nearplane`, `nozoom` (x1.0 everywhere), `zoomall` (x1.2 on every CG, PM's copies too), `bb2bg` / `bb21`
    (Mikoto as backgrounds, the 1.1.0 release form), `bbsmall` (the re-encode with bb2bg).
  - No-op aliases the tester still sends: `bbnative`, `cam8`; `hdr4` = nozoom. `oldzoom` (an afternoon name for the
    rule that is now the default) is gone.
  - Exclusions: framerule with nozoom / hdr4 / zoomall, keepall with nokeep, nozoom with zoomall, bbnative with bb2bg.
  - The scene tester's Version row (scenetest/pm_tester_app.py, another workflow) still offers bbnative / bb21 /
    nozoom / zoomall and its selftest fails on the new names until it is updated.
- **Lab builds and the 2007 folder.** The scene tester's AF session (scenetest/session-af.json, "running" since 16:13)
  had left its Mikoto jump patch in the 2007 folder in place of altfable.rio.ruo1 (same size, sha1 164f1689...). A
  build then silently ran without the official patch's staging (the log said "AF official patch: not found"), so it
  had no patched Mikoto billboards. Env `AFR_AF_PATCH` points the builder at a copy (size and sha1 still checked).
  These builds used save-backups/altered-fable-2007-original/altfable.rio.ruo1 (sha1 17dbeb8a...). The 2007 folder
  was not touched. The tester's "Back to normal" restores it, and that must happen before any app build or install.
- **Checks** (framing2/fix; full builds with AFR_EN_PKG= and AFR_AF_PATCH, runbuilds.sh, runs/*/):
  - Default (no AFR_TEST): exit 0, 5,217 objects, 1,931,477,564 bytes, sha1 f85c4b64; the log confirms the patch
    staging. Rebuilt with the final builder into out/v11.ruo1: the same sha1 f85c4b64 (deterministic); v11.log, build_all.log, build_manifest.json and built/ belong to it.
  - Every configuration: exit 0, validate_built 73 heaps / 0 bad refs, review_patch only the known 01aa6fedfe 26 note.
    - `nokeep` 88ca03a8: byte-identical to the build the owner checked.
    - `bb2bg,nokeep` bbc1ac7a: byte-identical to the 1.1.0 release.
    - `bbnative,bbsmall,cam8` f85c4b64: the default (aliases).
    - `framerule,keepall` d3b564df: against v11 (09aefab2) 56 parts byte-identical and 17 identical with the ids
      masked; only the ids differ (the 65 inserts now 0x3F200-0x3F240, 1.1.0's 38 additions back at 0x3F100-0x3F125).
    - `keepall` 0c38039f: the default plus 62 inserts (65 with Mikoto's, renumbered), 0 changed instructions.
    - `nearplane` 850d1515: one changed instruction, marimo_chapter #522 (-110, 195, 0, 6710) -> (-55, 98, 0, 13420).
    - `nozoom` 24a706c0: only the distances of 635 camera calls (imports, the 3 inserts included). `zoomall`
      c671c53e: only 89 distances (the PM copies). `bb21` b6b14ba7: against bb2bg,nokeep the 34 billboard args (21)
      and Mikoto's 3 inserts (#525 at 1660, the 1.1.0 value of shot 55).
  - verify_ids12 against 1.0.0 (default): 9,652 ids kept, 0 shifts in all 73 parts; 18 lead-in ids; 41 added ids
    (1.1.0's 38 at 0x3F100-0x3F125, the 3 inserts at 0x3F200-0x3F202); 102 changed instructions (34 billboard calls
    back to 86697a41, 30 camera distances, 18 8-arg cameras, 15 shocks, 4 waits, 1 flash); PM heaps and their 73
    inserted ids unchanged; all 5,185 keys present; the 12 main-range objects with new bytes are the re-encoded
    billboard pictures. PROBLEMS 0.
  - Shot table (fix/shots_new.py; 724 camera states plus 61 'pending insert' rows). On the 1024x600 model: no state
    of the default build has black bars (the checked build: 1, shot 56); the 88 states on PM copies equal 2007; the
    imports at x1.2 show about 69% of the 2007 area by code (by the in-game measurement, the same area); 10 states are off
    2007 in both screen models: Mikoto's 9 FILL_FLOOR states (centred whole CG, tighter than 2007, as checked) and
    marimo_chapter shot 18. On the 1280x720 model 84 states would have bars. Of the 58 case-B shots on CG pictures
    that only keepall fixes, 50 open with bars on the 1024x600 model.
- **To check in game** (built indices of the default build):
  - Mikoto shot 56 (#524-526): opens on the tilted close-up of shot 55, no black bars; shots 31 / 32 (#317-319,
    #324-326): open on shot 30's close-up.
  - Then, as test versions: keepall (e.g. yuuhi_a shot 2, picture #15, and yuuhi_b shot 1, picture #18: the move
    should start on 2007's framing, not on the whole picture); zoomall (yuuhi_a 61 / 62); nearplane (marimo_chapter
    #520-523).

## 1.1.0: launcher synced to the owner-checked default (2026-11-07, evening)

- The owner checked the default build (out/v11.ruo1, f85c4b64) in game with the scene tester: Mikoto's scene is fixed.
- Code: app_src/build_all.py = the lab builder that made out/v11.ruo1 (sha1 6c82a416). The other shared modules and
  data files were already identical; app.py and oscompat.py are app-only. release-repo/src mirrors app_src; its spec
  is unchanged (no new module or data file). During the sync (21:00) the lab copy gained a test-only switch,
  AFR_TEST exact (sha1 314f9566). Its default build is the same file, f85c4b64 (built through a temp copy of the
  app), so the app keeps 6c82a416 (research/launcher-sync/lab_builder_changed_during_sync.txt).
- Launcher (app.py):
  - English row: "found: in the game, set Options → Text Language to English to see the restored lines in English".
  - 2007 line: when <AF>/altfable.rio.ruo1 is missing or is not the official update (size + SHA-1 of the whole file =
    build_all.AF_PATCH; hashed once per path, size and mtime), a second amber line says that restored lines use the
    unpatched text, voices and staging. Building is not blocked. Before, the launcher said nothing and the build
    silently left out the update's text, voices and staging, Mikoto's 3D close-ups included.
  - --selftest also checks app.AF_PATCH against the constant in the compiled builder (build_all is not run).
  - do_build leaves AFR_AF_PATCH alone (the launcher never sets it), so the exe check below could point the frozen
    builder at the official copy while the scene tester's jump patch is in the 2007 folder.
- dist/AFRestore.exe rebuilt with build/pyi312 (sha1 6d8f3e28); the previous 1.1.0 exe is
  dist/old/AFRestore-1.1.0-pre-camera.exe (26f4b538).
- exe == lab (research/launcher-sync):
  - A console build of the same spec has the same archive as the windowed exe, entry by entry (base_library.zip by
    content); the frozen modules equal app_src.
  - Its `--build PM AF OUT` (LOCALAPPDATA in a temp folder, AFR_AF_PATCH = the official copy, no English) wrote sha1
    f85c4b64 = out/v11.ruo1, byte-identical (cmp). Its build_all.log equals v11.log except a timing and the output path.
  - With the lab afhook.pkg, the exe and a lab build both gave 76ce634a, byte-identical (made with a first console
    build whose builder modules and data equal the final exe's; only a space in one app.py line differs).
  - A build from release-repo/src/AFRestore.spec (as CI builds it) has the same archive content.
- Tests (research/launcher-sync):
  - test_gui_merged 71/71, 12 of them new: the update note on fake folders, the hash cache, the official copy read
    only;
  - test_selftest 30/30, 2 new;
  - test_spec 16/16, with the workflow pre-flight for v1.1.0;
  - test_windows_regression 22/22;
  - the console and windowed exe pass --selftest (exit 0).

## 1.1.0: exact 2007 framing confirmed in game (2026-11-07, late evening)

Sources: lab-tools/out/research/framing2/exact-default (builder backup build_all.pre-exact-default.py = sha1 314f9566,
runbuilds.sh / build_default.sh, runs/*/, anchors.txt, check_inserts.py, shots_exact.py, the comparisons); the shot
table framing2/shots_exact.csv (next to the old shots_new.csv). Lab only: app_src, release-repo and dist are unchanged
(the launcher still builds f85c4b64; syncing it is a separate step).
- **The owner's check.** Scene tester, AFR_TEST=exact (the 2007 camera values on every CG shot: no x1.2 on imported
  pictures, no FILL_FLOOR; the kept camera in Mikoto's scene only), side by side with the 2007 game, ~21:15: Mikoto's
  scene frames exactly like 2007, "It's perfect". The x1.2 and FILL_FLOOR had framed it 1.2-1.25x closer.
  - This is what the engine model predicts: both engines frame on a 1024x600 camera screen and draw a picture at depth
    D at distance / D, at canvas x Cr6Ti scale, the same for an import and its byte-identical PM copy (research/
    framing2: pm-projection, af-projection, review-camera; previous section).
  - The old x1.2 "measurement" (October) matched PM's 16:9 remakes (1566 wide), not the 2007 pictures. FILL_FLOOR came
    from the wrong belief that PM's camera screen is 1280x720. Lesson: the code-proven rule beat both measured factors.
- **New default of build_all.py** (scripts/build_all.py, sha1 30da4241):
  - the exact 2007 framing: every camera on a CG shot keeps the 2007 values (IMPORTED_IMAGE_ZOOM 1.0, FILL_FLOOR {});
    PM's own CBg2d backgrounds keep AF's values as before; CAMERA_FIX (the Marimo ceiling, matched to 2007
    screenshots on 2026-10-11) stays;
  - CAMERA_KEEP in every part (65 inserts: 6 instant sets, 59 start stores), as the owner asked ("make sure it's not
    just her scenes facing the same issues"); Mikoto's three are the ones the owner saw;
  - the near-plane correction, recomputed for the exact distances: marimo_chapter shot 18 (#521-523) has the 2007 value
    (-110, 195, 0, 5592), above PM's 5040 threshold (D = 799 > Zp 720), and becomes (-55, 98, 0, 11184) (the pre-exact
    rule's 6710 gave 13420). Same view size as 2007; the view centre sits 1.4 picture pixels (about 11 of 600 screen
    pixels) lower, because the pan 195 x 720/1440 = 97.5 must be a whole number (no other distance reproduces the view:
    below 10074 PM's D grows faster than the distance). near_plane() still refuses (BuildError) a change the pan clamp
    would move (checked on PM's 1024x600 screen and on 1280x720), and now also a camera the clamp had already moved;
    shot 18 passes both with a wide margin.
  - Byte-identical to AFR_TEST=exact,keepall,nearplane on the builder before the change (both ea97eb32).
  - Proven by code: the framing, the kept camera, the near plane. Seen in game: the exact framing and the kept camera in
    Mikoto's scene. Not yet seen in game: the kept camera in the other 12 parts that get inserts, and shot 18.
- **AFR_TEST after the change** (test builds; build_all.py's comment block lists each with the build it rebuilds):
  - new: `zoom12` (the pre-exact rule: x1.2 on imports + FILL_FLOOR), `keepmikoto` (inserts only in KEEP_PARTS),
    `nonearplane`; `nokeep` as before.
  - kept, same meaning relative to the pre-exact rule: `nozoom` / `hdr4` (FILL_FLOOR only), `zoomall` (zoom12 + x1.2 on
    PM's copies), `framerule`, `bb2bg` / `bb21` (imply zoom12, the rule they were made with), `bbsmall`.
  - old names as no-op aliases: `exact`, `keepall`, `nearplane` (all the default now), `bbnative`, `cam8`.
  - exclusions: exact with zoom12 / nozoom / hdr4 / zoomall / framerule / bb2bg / bb21; nozoom with zoom12 / zoomall;
    framerule with zoom12 / nozoom / hdr4 / zoomall; keepall / keepmikoto / nokeep; nearplane / nonearplane;
    bbnative with bb2bg / bb21.
  - Log and manifest: rule notes read 'exact: 2007 value (imported | PM copy)' or 'pre-exact rule: ...'; the manifest's
    'tested' field keeps the pre-exact values (the builds checked before the exact framing).
- **Regression anchors** (full builds, DUMP_HEAPS=1, AFR_EN_PKG= , AFR_AF_PATCH = the save-backups copy of the official
  update; every one exit 0, validate_built 73 heaps / 0 bad refs, review_patch only the known 01aa6fedfe 26 note):
  - `zoom12,keepmikoto,nonearplane`: f85c4b64 = the default of the evening (v11 before this change, the owner's
    "Mikoto fixed" check).
  - `zoom12,nokeep,nonearplane`: 88ca03a8 = the build the owner checked in the afternoon.
  - `bb2bg,nokeep,nonearplane`: bbc1ac7a = the 1.1.0 pre-camera release.
  - Old names: `keepmikoto,nonearplane` ae69796c = the old `exact` (the owner-confirmed build, also made with the
    pre-change builder); `exact,keepall,nearplane` ea97eb32 = the default; `zoomall,keepmikoto,nonearplane` c671c53e,
    `nozoom,keepmikoto,nonearplane` 24a706c0, `framerule,nonearplane` d3b564df (old framerule,keepall),
    `bb21,keepmikoto,nonearplane` b6b14ba7, `zoom12,nonearplane` 0c38039f (old keepall), `zoom12,keepmikoto` 850d1515
    (old nearplane): each the sha1 of its build of 2026-11-07.
  - New: `nokeep` ba6e47a3 (the default without its 65 inserts, nothing else changed); `nonearplane` 8321ad2d (one
    instruction: marimo_chapter #523 back to (-110, 195, 0, 5592)).
  - The runs used the builder at sha1 80a4b169; the final scripts/build_all.py (30da4241) differs from it in comments
    only (checked) and rebuilt the default to the same ea97eb32. anchors.txt has the table.
- **Checks of the new default** (out/v11.ruo1, sha1 ea97eb32, 1,931,480,756 bytes, 5,217 objects; v11.log,
  build_all.log, build_manifest.json and built/ belong to it):
  - validate_built: 73 heaps, 0 bad refs. review_patch: PROBLEMS 1 = the known 01aa6fedfe 26 note.
  - verify_ids12 against 1.0.0: 9,652 ids kept, 0 shifts in all 73 parts; 18 lead-in ids; 103 added ids (1.1.0's 38 at
    0x3F100-0x3F125, the 65 inserts at 0x3F200-0x3F240); PM heaps and their 73 inserted ids unchanged; all 5,185 keys
    present; PROBLEMS 0. Changed instructions against 1.0.0: 697 (625 camera distances: 1.0.0 had x1.2 on imports;
    34 billboard calls, 18 8-arg cameras, 15 shocks, 4 waits, 1 flash as before).
  - Mikoto's part heap equals the owner-confirmed AFR_TEST=exact build's (pre-change builder, ae69796c) with the
    instruction ids masked: only the ids of its 3 inserts differ (0x3F200-0x3F202 there, 0x3F233-0x3F235 here, because
    the inserts are numbered in build order and 51 come from the parts before Mikoto); their arguments are the same,
    (-175, -132, 0, 2304) twice and (95, -21, -133, 1992). Against that build the whole patch differs by 62 inserts in
    12 other parts and the one near-plane instruction (cmp_exact_pre_vs_default_*.txt).
  - Every insert carries the AF kept camera at the 2007 values (check_inserts.py: built heap arguments against the AF
    script's own camera call, read from af_rsa or the official patch's script): 65 of 65; kind A mode 1, kind B mode
    64; none is near-plane corrected. The only shot that needs the kept camera and gets no insert is x_45d98b_7366's
    (0 ms apply: the move is instant).
- **Shot table** (exact-default/shots_exact.py on runs/default -> framing2/shots_exact.csv, summary
  exact-default/shots_exact_summary.txt; the projection code of fix/shots_new.py, 1024x600 in both engines):
  - 785 camera states on Cr6Ti CG pictures (452 on the 2D path, 333 on the 3D path): 721 camera calls and 64 inserts
    (the 65th, marimo_chapter #119, is on a CBg2d background).
  - Visible picture area within 1% of 2007: 785 of 785 (all equal to 4 decimals).
  - Black bars beyond 2007's own: 0. Five states whose 2007 view itself reaches past the picture edge (tilted
    billboards: sumika s46, meiya s26-28, kasumi_h s47; 0.3-0.75% of the screen) show the same bars in PM.
  - Off by more than 1% or with extra bars: none. One state differs in position only: marimo_chapter shot 18 (#523, the
    near-plane correction), same area, overlap with the 2007 view 96.4% (the 1.4-pixel pan rounding above). No other
    state, and no move or start store, lies above PM's near plane.
  - Against the previous default f85c4b64 (same instruction ids): 622 cameras on imports lose the x1.2, Mikoto's 10
    FILL_FLOOR states get their 2007 values back, shot 18's near-plane camera is recomputed, the 88 states on PM's
    copies are unchanged; Mikoto's 3 inserts now carry the 2007 distances (2765 -> 2304, 2390 -> 1992) and 61 inserts
    are new.
    Against the owner-confirmed exact build: every state equal except the near-plane one, plus the 62 new inserts.
  - Not in the table (not Cr6Ti CGs, unchanged in every build): 239 camera calls on PM's CBg2d backgrounds and other
    pictures, and the 2 CAMERA_FIX calls on the Marimo ceiling.
- **Dev scene tester** (scenetest/pm_tester_app.py VERSIONS / VERSIONS_LEFT_OUT, scenetester.TEST_VERSIONS,
  af_scene_tester.py, selftest.py, selftest_apps.py, selftest_play.py, README_DEV.md; backups of the previous files in
  exact-default/tester-backup):
  - Version row: *Release* (the new default) / *Test: earlier framing* (`zoom12,keepmikoto,nonearplane`, id
    `preexact`: the Release before the exact framing, f85c4b64 as a full build) / *Test: no kept camera* (`nokeep`, id
    `nokeep`). "Test: before the exact framing" was too wide: with its AFR_TEST note it needed 446 of the 415 px of the
    option column (the layout check failed), so the shorter text.
  - Files and bases of the former Versions (`exact`, `allcam`, `exactall`, `testzoom12`) no longer match a Version; a
    `release` base made with the old builder is older than build_all.py and is made again on the next Play.
  - The owner's remembered choice (apps.json "tester": `exactall`) is no longer a Version, so the window opens on
    *Release*, which is the same build (ea97eb32 as a full build). The live session shows Mikoto installed with that
    former Version (read-only --selftest).
  - selftest_apps.py's takeover check compared the copied live apps.json with the former window's "pm" section only;
    since the merged window saved its own "tester" section it compares with that one (the app's documented order).
  - Results: selftest_apps.py 170 checks, 0 failed; selftest.py 375 checks, 0 failed (its fake folder removed by its
    own passing run); af_scene_tester.py --selftest-play with AFR_TESTER_FAKE = a temp folder: 57 checks, OK (the
    folder deleted); read-only af_scene_tester.py --selftest on the real folders: OK, the live state files unchanged.
- **To check in game** (built indices of the default build): a scene outside Mikoto with kept-camera inserts, e.g.
  yuuhi_a shot 2 (picture #16, start store #17) and yuuhi_b shot 1 (picture #19, start store #20): the move should
  start on the 2007 framing, not on the whole picture; marimo_chapter shot 18 (#521-523): the 2007 close-up; Mikoto
  shots 31, 32, 56 (#317-318, #324-325, #524-525) as the owner saw them.

## 1.1.0: Test a scene in AFRestore, launcher synced to the exact default, faster builds (2026-11-07, night)

Sources: lab-tools/out/research/public-tester (design tools: opening_flow.py, helper_flow.py, callers.py,
ach_reach.py, profile_build.py, bench_cgcrop.py, profile-*.txt; implementation tests and results in impl/: run_build.py,
test_kit_lab.py, make_fixture.py, test_gui_scenetest.py, measure_layout.py, exe_build_check.py, the launcher-sync
regression copies, stub_tk/, *_result.txt; the fixture in fixture/). Backups before the change: impl/build_all.pre-
speedup.py (30da4241), impl/app.pre-scenetest.py, impl/*.pre-prebuild.py.

- **Builder speedups, byte-identical** (scripts/build_all.py, sha1 b0286e68; new scripts/reencache.py):
  - reencache.py caches cgcrop.shrink (13 billboard re-encodes) and the 10 CG re-crops: key = sha1 of (kind, parameters,
    sha1 of every input body, sha1 of cgcrop.py's source, or of cgcrop's compiled code where no source exists, e.g.
    the frozen app); entries written atomically and checked on read (magic, format, payload sha1; a bad one is made
    again); finish() at the end of a build removes entries this build did not use and nobody used for an hour.
    Location env AFR_CACHE ('' / off = none); lab default out/cache/reencode; the app sets <settings>/cache.
  - image_identical compares in 64 KiB chunks and stops at the 17th differing byte (same boolean).
  - The re-crops decode each AF picture once for the most rows any of its crops needs and hand each crop the first rows
    it needs; resample reads only rows <= need - 2 and its edge clamp uses len(rows) only when need = the full height,
    so the bytes are the same (checked by sha1).
  - Default build (no English, AFR_AF_PATCH = the save-backups official copy, guarded runner, nothing in out/ touched):
    no cache 118.8 s, cold cache 118.3 s, warm cache 29.8 s; all three ea97eb32 = the default. With English (lab-tools/
    out/afhook_pkg/afhook.pkg): b03eb13f. Anchors with the warm cache: zoom12,keepmikoto,nonearplane f85c4b64 (26.5 s),
    bb2bg,nokeep,nonearplane bbc1ac7a (27.2 s, BB_SHRINK off). The build log differs only by the one cache line.
  - The process-pool pre-fill (AFR_JOBS) was not done: the shrink inputs of imported billboards are only known while the
    parts are converted (their nested references are patched first), so a pre-fill would have to repeat that.
- **Launcher synced** (app_src, release-repo/src): build_all.py = the lab builder (b0286e68: the exact default plus the
  speedups), reencache.py, scenekit.py, scenetest_session.py new; both specs list the three as hiddenimports;
  app.BUNDLED too. dist/AFRestore.exe rebuilt (build/pyi312, sha1 e0d7d037); the previous one is
  dist/old/AFRestore-1.1.0-pre-scenetest.exe (6d8f3e28). Build folder: build/scenetest-1.1.0 (windowed + console spec).
- **Test a scene** (the owner asked for a release test launcher; built into AFRestore):
  - Engine facts (proven from pm.c / PM's scripts, design in public-tester): PM's FUN_005de150 reads the patch's last 4
    bytes (count N, refused above 0x1FFFF) and the 12·N table bytes before them, nothing else but the objects the table
    points to. So a test is appended (objects, the old table, the new entries, N+k) and cutting the file back to its old
    size gives the original byte for byte. The opening 00ce1abaf2 (4419 instructions) has no achievement call; it calls
    the chapter-end helper 670d5aaf at instruction 1022 (14 FlagOps, a system database message, 5 calls, no
    achievement call; the prologue calls it in every new game too); the first achievement call on the jump chain is
    01603030ae instruction 1051, about 4,620 lines later. Inferred, not proven: 12 helper scripts called everywhere are
    not in the lab dumps; that they make no achievement call is inferred.
  - scenekit.py: the kit is made at build_all's write_ruo (capture_hook, set by app.do_build before runpy): for the 11
    PUBLIC items (the 10 18+ scenes, the Marimo-chan chapter: the ones the owner played through the dev tester) the
    patched opening with and without the lead-in (build_all's own patch_pm, the dev tester's instruction ids), checked
    with walk_direct and CVmRet ends; the Marimo-chan chapter's guard-free copy (build_menu.guard_free_copy logic); the
    build's counters, import tables and report tables are put back after each (fastplay's snapshot + the report
    tables, so even the build log stays the same) and build_all's say() is silenced meanwhile (no converted text in the
    output). Then the real write_ruo writes exactly the objects it was given. 21 openings, 13-20 s, 3 MB in
    <settings>/scenetest/kit.new; the launcher makes it the kit only after the new patch is in place. A kit that cannot
    be made leaves failed.txt; the build goes on.
  - scenekit's copies of build_all's CountHeap / base_pos / mem_size / FIXED, of scenemenu's part_span / leadins /
    walk_direct and catalog's route_guarded: the lab test checks the source (AST) and the answers for every catalog
    item; AFRestore --selftest checks the compiled code against the bundled builder's (scenekit.builder_code_matches;
    the bytecode depends on `import struct` being in the module, which both have).
  - scenetest_session.py: first test = every account's userdata/<id>/889710/remote backed up (sha1-checked) into
    <settings>/scenetest/backups/<time>/; append (r+b at the old size, fsync), read back (old entries, new objects,
    the tail's sha1, walk_direct on the opening read from the file, CVmRet ends of every called script). A later test
    cuts the old one off and appends the new one (the first backup stays). Back to normal cuts the file back (also a
    half-written append: the old table and count right before the old size decide), checks size, table and
    fingerprint, puts the saves back with copyfile (current time, so Steam treats them as local changes: inferred),
    created files moved to created-during-test, changed ones copied to changed-during-test first; nothing deleted. It
    asks first when the test is more than 24 h old or save files other than gdb.uuc were made or changed. Any other
    patch file is left alone and reported. The session file is flushed before every step (copy in the backup); an
    unreadable one stops every change until its copy is put back. Refused while the game runs and for 2 minutes after
    a Play (until the game was seen running and closed). A scene the kit does not have is refused before anything is
    backed up.
  - The window (app.py): a Toplevel in the launcher's fonts and colours: 18+ scenes (two columns, grey "N lines + M
    lead-in") and Marimo-chan route, "Start: a little before the scene / at the scene", the "In the game" box (the
    English line only for English builds), "Back to normal by itself when the game closes" (on by default; 15 s after
    the game closes, while the launcher is open), "Installed now:", a progress bar, Back to normal and ▶ Play this
    scene. 584 x 527 px (real Tk, withdrawn). Main window: a fourth button "Test a scene...", the status "Scene test
    installed: <scene> (lead-in + scene) — Back to normal puts everything back.", Turn OFF becomes Back to normal,
    Build / Rebuild and the after-update rebuild put a test back first (asked). oscompat.steam_userdata_remotes:
    every account folder of every Steam root (Windows, native Linux / Deck, Flatpak, Snap).
- **Developer scene tester: every Version's base prebuilt** (af_scene_tester.py, pm_tester_app.py, fastplay.py):
  the chosen Version first, then every other Version for the chosen Restored text, one at a time, at below-normal
  priority (raised to normal for the whole process tree when Play waits for one); not with less than 2 GB free; note
  "Preparing <Version> (k of n)"; kept: the chosen text's full set plus the newest other base, bases of Versions no
  longer in the row removed. fastplay --build-base sets AFR_CACHE, so the Versions share the re-encodes;
  out/cache is a builder output (BUILD_OUTPUTS), never a base input. The keep policy reads the Restored text from a
  plain attribute (prune_bases runs on the worker thread). lab-tools/out/scenetest/base was not touched.
- **Tests:**
  - test_kit_lab (real data, temp folder): 109 checks, 0 failed: copies, lead-ins and route guards equal the dev
    tester's for all 34 catalog items; a fastplay base for the same builder (25 s, warm cache) equals the kit's patch
    (ea97eb32); all 21 openings and the guard-free copy byte-equal fastplay.make_opening / the base's gf; on a sparse
    copy, every item with and without lead-in appended, verified, its key -> object map equal to fastplay.assemble's,
    cut back; the whole file's sha1 is the original afterwards; a half-written append is cut back; a session install,
    swap and Back to normal on a fake saves folder.
  - test_gui_scenetest (window-less Tk, fake folders, the fixture): Windows 20/20, Linux (WSL, python 3.14) 21/21.
  - Launcher regressions (copies of launcher-sync's, stub with Toplevel): test_gui_merged 70/70 (the official-copy
    check needs AFR_TEST_OFFICIAL_DIR, not set), test_selftest 31/31 (one new case: a builder whose heap reader differs
    from scenekit's copy -> exit 3), test_spec 16/16, test_windows_regression 22/22.
  - AFRestore --selftest-scenetest from source (Windows, Linux) and in both exes: synthetic and fixture, OK.
  - exe == lab: the console exe (same archive as the windowed one, entry by entry) built ea97eb32 without English (cold
    cache, 223 s) and b03eb13f with it (warm cache, 66 s); both kits byte-identical to the lab kits.
  - Dev tester: selftest_apps 180/180 (10 new), selftest.py 385/385, --selftest-play on a temp fake folder 57/57,
    read-only --selftest OK with the live state files unchanged (sha1).
- **Not seen in game yet:** the Test a scene window (OWNER-TESTS-1.1.0.md); whether Steam Cloud brings back a save made
  during a test; the Steam Deck.

## 1.1.0: launcher sync checked again, release docs (2026-11-08, after midnight)

Sources: lab-tools/out/research/sync-1.1.0 (import_scan.py, cmp_exe_archives.py with the module list taken from the
source folder, run_builds.sh, framing_lines.py, frozen_vs_src.py; results/).

- **Sources in step.** The 18 modules shared with the lab and omsig_data.txt are byte-identical in lab-tools/scripts,
  app_src and release-repo/src (build_all b0286e68, reencache 5a048a72, scenekit bb2ec733, scenetest_session
  f98b3111); app.py (f4841ab0) and oscompat.py (3a3dd960) exist only in the app and are identical in both copies;
  data/ is identical. Nothing needed copying.
- **Static import scan** (every import statement in the 20 source files: module level, inside functions, inside try):
  all 20 modules are shipped (reached from app.py, from runpy's build_all and from app.BUNDLED); every one is in both
  specs' hiddenimports, in BUNDLED (build_all is located by --selftest, not run) and in the exe's PYZ; no third-party
  import; every stdlib import is inside the exe (PYZ, base_library.zip, a bootstrap module, an extension or a
  builtin); the only dynamic imports are runpy build_all, --selftest's importlib over BUNDLED + LAZY_STDLIB and
  `__import__('struct')`. The exe's data files equal src/data + omsig_data.txt. release.yml builds from
  src/AFRestore.spec and its frozen-app check reads the spec's hiddenimports and src/data, so it covers the new modules
  without a change.
- **The exe.** dist/AFRestore.exe e0d7d037 (built 23:50 from these sources) was kept: app.py was saved again at 00:04
  with the same code (the frozen app script equals app.py compiled, line table included). Archives entry by entry:
  windowed == console exe (build/scenetest-1.1.0, a1a717f9) == a fresh build from release-repo/src/AFRestore.spec
  (6a6fa4a5, deleted afterwards): 1161 entries, base_library.zip with identical contents; the 19 frozen modules and
  the app script equal app_src and release-repo/src compiled; 7 data files equal.
- **exe == lab** (run again here; AFR_AF_PATCH = the save-backups copy of the official update, read only; every patch
  deleted after hashing): lab default (guarded runner, own cold cache, kit) ea97eb32; lab English (afhook.pkg)
  b03eb13f; console exe --build with a temp LOCALAPPDATA: ea97eb32 (167 s, cold cache) and b03eb13f (47 s, warm);
  both exe kits byte-identical to the lab kits.
- **Tests:** --selftest and --selftest-scenetest (synthetic and fixture) OK from source (Python 3.12 venv, the lab's
  3.11, release-repo/src) and in the console exe; test_gui_merged 71/71 (the official-copy check with
  AFR_TEST_OFFICIAL_DIR = the save-backups folder), test_selftest 31/31, test_spec 16/16, test_windows_regression
  22/22, test_gui_scenetest 20/20, measure_layout OK (584 x 527, nothing mapped), test_kit_lab 109/109 on the lab
  default patch and kit (lab-tools/out/scenetest and out/cache unchanged, listings compared). Linux (WSL, Python
  3.14): test_gui_scenetest 21/21, test_gui_merged 70/70, --selftest-scenetest synthetic and fixture OK.
- **Found, not fixed: --selftest fails from source on Python 3.13 and newer** (Windows 3.14 and WSL 3.14: "scenekit
  copies differ from build_all: CountHeap"; test_selftest on WSL stops there). Since 3.13 a class body stores
  `__firstlineno__`, and 3.14 loads small integers with LOAD_SMALL_INT, so the CountHeap class-body code depends on the
  line of the class statement (107 in scenekit.py, 810 in build_all.py); scenekit.same_code ignores line numbers but
  not that store. It passes on Python 3.12 (both exes; CI on Windows and Linux and BUILDING.md use 3.12) and 3.11, so
  the release is not affected. Possible fix: compare CountHeap's methods and names instead of its class-body bytecode.
- **Release docs:** CHANGELOG 1.1.0 (the exact 2007 framing with the 1.0.0 zoom factors gone, the kept camera in every
  scene, the Marimo-chan chapter pan, Test a scene); README already has the one Test a scene line; BUILDING.md is
  still true; docs/MODLOG.md mirrors this file again (header and the two privacy redactions kept; the previous step had
  left out the "exact 2007 framing confirmed" section); OWNER-TESTS-1.1.0.md rewritten.
- **Line numbers for the owner** (structure only: 1 + the CVmMsg* instructions before the built index, in built/ of the
  default build; scene start "at the scene"): first CG shots that lost the x1.2: kashiwagi #10 line 2, meiya #5 line
  3, sumika #14 line 6; kept-camera start stores: yuuhi_a #16/#17 line 6, yuuhi_b #19/#20 line 15; the near-plane pan:
  marimo_chapter #521-523 line 149; Mikoto's inserts #318 line 196, #325 line 200, #525 line 308.

## 1.1.0: review fixes for Test a scene and the release docs (2026-11-08, night)

Sources: lab-tools/out/research/review-fix-1.1.0 (repro_f1_f2.py, check_countheap.py, test_gui_scenetest.py = the
public-tester copy + 12 checks, measure_layout.py, run_builds.sh, linux_tests.sh; pre-fix/ copies of the changed
files; results/).

- **Back to normal with the game folder missing.** Before, scenekit.undo_tail's "not in the game folder any more"
  became patch 'left': the saves were put back and the session closed, so when the drive came back the test was still
  at the end of the patch with nothing to take it out (reproduced on fake folders: 6088 bytes, original 5364). Now
  back() checks the session's game folder first. When it is missing, it raises FolderMissing: nothing changes and the
  session stays. The window asks "connect it and try again, or is the game no longer installed there?". Yes calls
  back(folder_gone=True): the patch file is left (the message says to click "Rebuild & install" there later), the
  saves are put back and the session ends. A folder that exists without the patch file still closes the session as
  before (nothing to take out). The automatic Back to normal only shows the message.
- **No Steam saves folder.** Before, the install went ahead with saves [] and Back to normal still said the saves were
  back. Now a first install with no account folder raises NoSavesFolder. The window asks first (default No: nothing
  changes); Yes installs without a backup. Back to normal then says the saves were not backed up and stay as they are
  (report saves 'none'); its confirmation and the Rebuild question no longer promise the saves. A swap keeps the first
  backup and does not ask.
- **The window follows the kit.** It read the kit once, when it opened. A Rebuild made with the window open left it
  without line counts, with both Start options for scenes without a lead-in, and without the English line. Now every
  refresh reads the kit again (kit.json is a few KB) and updates the counts, the Start choice and the English line
  (packed third, also when the kit goes away after a failed build).
- **Subtitle:** "Play one restored scene. Your saves are backed up first; Back to normal puts them back." (460 px in
  real Tk; the window stays 584 x 527, 584 x 548 with the English line).
- **--selftest on Python 3.13 and newer.** scenekit.builder_code_matches compares CountHeap with same_class_body: the
  same names, the same methods (same_code) and the same other constants, leaving out the class's own line number. The
  class-body bytecode is no longer compared: 3.13 stores `__firstlineno__` there, and 3.14 puts a small line number
  inside LOAD_SMALL_INT. check_countheap.py on 3.10, 3.11, 3.12 and 3.14: the real builder matches (also with CountHeap
  moved 40 lines down); a changed vm_call, docstring, extra method or mem_size is caught.
- **Docs.** README: the Test a scene line says "after the game's short prologue"; the official-update feature says
  "when it is installed". CHANGELOG: scenes framed "like 2007"; the Marimo-chan chapter close-up is centred about 11
  pixels lower (whole-number camera values); the automatic Back to normal works while the launcher is open.
  OWNER-TESTS: "Before Rebuild & install" comes before the in-game list, step 4 starts with the scene tester's Back to
  normal, and the scene tester line names Lead-in **Scene only**.
- **The exe.** dist/AFRestore.exe is 0694c3a4; the previous e0d7d037 is in dist/old/AFRestore-1.1.0-pre-reviewfix.exe.
  The console exe (build/reviewfix-1.1.0/dist-console, d86f4e03) was built first. Archives are equal entry by entry
  (1161 entries). The frozen modules and app script equal app_src and release-repo/src compiled. The import scan is
  unchanged.
- **exe == lab** (AFR_AF_PATCH = the save-backups copy, read only; patches deleted after hashing): lab default ea97eb32
  (builder b0286e68, unchanged, so the default and the anchors stand), lab English b03eb13f; console exe --build
  ea97eb32 (238 s, cold cache) and b03eb13f (69 s, warm); both exe kits byte-identical to the lab kits.
- **Tests (Windows):**
  - --selftest and --selftest-scenetest (synthetic and fixture) OK from source on 3.11, 3.12 (also the venv) and 3.14,
    and in the console exe.
  - test_gui_scenetest 32/32. The same test on the pre-fix sources fails the new checks.
  - measure_layout (real Tk, every window withdrawn) 8/8.
  - test_gui_merged 71/71, test_selftest 31/31, test_spec 16/16, test_windows_regression 22/22.
  - test_kit_lab 109/109 on the lab default patch and kit.
  - Dev tester: selftest_apps 180/180, selftest.py 385/385, --selftest-play 57 OK, read-only --selftest OK; the live
    state is unchanged (sha1).
- **Tests (Linux, WSL, Python 3.14):** test_selftest 27/27, test_gui_merged 70/70, test_gui_scenetest 33/33,
  check_countheap 6/6, --selftest-scenetest synthetic and fixture OK. --selftest now passes the scenekit step and stops
  at "import tkinter": that WSL Python has no tkinter module (the release builds use Python 3.12 with Tk).

## 1.1.0: disk cleanup (2026-11-08, night)

Sources: lab-tools/out/research/cleanup-1.1.0 (hashfiles.py, hashes.jsonl, make_record.py, removed.json with each
file's sha1 and how to make it again, deleted.txt, pre-cleanup/ copies of the edited files, the selftest logs).

- **Deleted** (each sha1 taken from the file right before; it matched the build summary or
  scenetest/user-tested-afjump.sha1), 3.10 GiB on disk (9.36 GiB apparent, the patches are NTFS-compressed):
  - the user-tested 2007 jumps lab-tools/out/af-scene-meiya.ruo1 (09cfe8f6), af-scene-kasumi2.ruo1 (d7f25c00) and
    af-marimo-jump2.ruo1 (a8a11884), 90 MB each; afjump.py makes them again byte for byte;
  - scenetest/scene-menu.ruo1 (37322b66) and release-ref.ruo1 (bbc1ac7a), both made with the builder of
    2026-11-07 morning. The AF Scene Tester never reads them; the old window shows "not built yet" and builds the menu
    patch on demand. Their .json summaries stay;
  - scenetest/direct/test-mikoto.ruo1 (289fdc4a; its summary, review and stdout logs stay), and the cache patches of
    two Versions no longer in the row: mikoto-skip-test3d-en (a385acf9) and mikoto-skip-testzoom10-en (a698305b),
    with their summaries. No session points to them; their sha1s stay in pm-tests.json;
  - the built heaps of the framing2 research runs (exact-default/runs/*/built, fix/runs/*/built, review-camera/snap,
    implement/prev_built; 28 folders of 73 heaps, about 1 MB each). The logs, manifests and results stay;
  - build/scenetest-1.1.0 (the console exe a1a717f9 of the superseded e0d7d037), build/scenetest-stub (PyInstaller
    work folder of the tester stub; launch_stub.spec writes it again) and scenetest/pre-version-sync (backups of the
    version-sync edits, verified by every selftest since; build_all 6c82a416 = the f85c4b64 builder, and the current
    builder makes f85c4b64 with AFR_TEST=zoom12,keepmikoto,nonearplane).
- **Kept:** everything a live tester file points to (session-pm.json: direct/mikoto-skip-exactall-en.ruo1 and its
  summary; both sessions' save-backups folders), scenetest/base/, save-backups/, lab-tools/out/v11.ruo1 with its log,
  manifest and built/, release-final2.ruo1, the re-encode cache, dist/ and dist/old/, testers/, build/pyi312 and
  build/reviewfix-1.1.0 (the console twin d86f4e03 of the current dist exe 0694c3a4, for exe == lab checks). Research
  folders that another running audit reads (restore-audit, helper-audit, asset-sweep, camera-inventory, censored-cg,
  billboard-camera, framing2 af-/pm-projection) were not touched.
- **Selftests adapted:** selftest.py compares the afjump builds with the sha1s in user-tested-afjump.sha1 instead of
  the files; --real-menu and --heavy skip when scene-menu.ruo1 / direct/test-mikoto.ruo1 are not built (before, a
  summary without its patch would have failed); selftest_launch checks the real --direct summary's fields and checks it
  against its patch only while that is built. README_DEV and afjump.py's docstring say how to make the files again.
  None of these files is a builder input, so the tester's bases do not go stale.
- **Tests:** selftest_apps 180/180, selftest.py 385/385 (the three user-tested jumps by sha1), --real-menu skipped and
  --heavy 18/18 (the 2 direct-file checks skipped), --selftest-play on a temp fake folder 57 OK (deleted), read-only
  --selftest OK; the live state files, base/ and direct/ listings are unchanged.

## Restore audit, implementation step I1: F00-F06 (2026-11-08)

Plan: lab-tools/out/research/restore-audit/deep/FIXPLAN.json. Record (sha1s, checks, deviations):
restore-audit/impl/LEDGER.json; runs, tools and checks: restore-audit/impl/I1. Builder b0286e68 -> bc75c0fe (lab only;
app_src and release-repo not synced). Every fix is default-on with its own AFR_TEST off-switch.

- **F00 framework** (no byte change): AFR_TEST off-switches for the default-on fixes, opt-in tokens fadetime, hutdepth,
  posture, pmexit (test builds until the engine code proves them), and `v11`, which rebuilds v11.ruo1 byte for byte
  (ea97eb32; English b03eb13f). Owner decision: F22 and F23 will be default-on (nobbexact, nosprexact, nokashi). Own id
  ranges (OVL, PATCH, FIX_END, FIXWIN, YCONT, X45, KASHI, EXCL, fixed ENTRY / EXIT slots) and key ranges (SPR, X45,
  KASHI, ENTRY, EXIT, HUTDEPTH, SCENE), asserted and logged at the end of every build.
- **F01 (C10)** marimo_chapter lines 304 and 398: the choice jumps straight to the update's stop-all (#1514), without
  the extra 1-second transition. Off: noc10. Default 26659749.
- **F02 (T3d)** marimo_chapter lines 235 and 389: both voice clips play (w2 = 2, PM's 2-voice form). Off: not3d.
  Default 9792abf8.
- **F03 (C3)** kashiwagi line 161 and mikoto line 316: empty, as the update made them (no repeated text). Off: noc3.
  Default 6fd25b4b. English: both merged lines already have their own afhook.pkg line, so nothing is appended.
- **F04 (C7)** meiya line 1 and x_4f4791_185: the song carries on (PM's own copy of the same recording is played, so
  PM does not restart it). Off: noc7. Default a795b234.
- **F05 (C5)** marimo_chapter line 167: the Marimo song plays (its stream is imported up to its end page and gets its
  stream ref). Off: noc5. Default ed261976.
- **F06** chizuru line 10: the ambient loop fades out as in 2007 (PM's own port of the fade, 01b8c7a482 #2232). Off:
  nopmsnd. Default 649d12a5 (English 99c8d6d7).
- **Checks** for every fix: the off-switch rebuilds the build before it; id-masked and resolved compares show only the
  fix's parts (plus the host enc_size of a resized part); 9,652 1.0.0 ids kept, 0 shifts, no key moved
  (impl/verify_ids13.py); validate_built 0 bad refs; review_patch: all achievement sites reachable, only the known
  01aa6fedfe 26 note; the fix's own verifier from the audit; an English build. Anchors with `v11`:
  v11,zoom12,keepmikoto,nonearplane = f85c4b64, v11,bb2bg,nokeep,nonearplane = bbc1ac7a, v11,nokeep = ba6e47a3,
  v11,nonearplane = 8321ad2d. Not yet seen in game.

## Restore audit, implementation step I2: F07-F13 (2026-11-08)

Same plan and record (restore-audit/impl/LEDGER.json); runs, tools and checks: restore-audit/impl/I2. Builder bc75c0fe
-> 669ad378 (lab only; app_src and release-repo still b0286e68). Every fix is default-on with its own AFR_TEST
off-switch, and each off-switch rebuilds the default from before it.

- **F07 (LAND)** no PM re-stage after six parts: x_3eab17_1598 / 2453 after line 4 and x_3eab17_7449 after line 13
  (the camera stays), x_45d98b_1809 after line 16 (no billboard jump-back or repeated sweep), x_4cfd31_2031 after line 4
  (the sound only twice), x_3eab17_4970 after line 2 (no repeated effect). Only the inserted calls' landings move.
  Off: noland. Default 94af056f.
- **F08 (C11)** marimo_5caf15_a lines 16 and 21: Marimo at the update's (200, 600, 1, -80, 0); marimo_chapter lines
  329, 401, 405: the update's shake data. Off: noc11. Default 6d1e40c7.
- **F09 (C15)** every voiced line: the voice is parented to its character's PM ocean (2,092 voices), so PM animates the
  speaker's mouth and applies the per-character voice setting; the 72 lines whose AF ocean has no registration name
  their speaker box explicitly, as PM's own port does (69 of them = the update's link). Check: yuuhi_a line 21 (mouth),
  chizuru line 1. Off: noc15. Default 9e899019.
- **F10 (C4)** kasumi_h lines 226-264: the canopy bed in front (PM's own overlay set for its flat copy of the hut).
  Off: noc4. Default 1600f8d4.
- **F11 (C6)** end of mikoto, meiya, kasumi_h: silence over the end card (PM's stop-all; Kasumi ends on the update's
  600 ms white fade + stop-all). Off: noc6. Default 42b25242.
- **F12 (C14)** the text window disappears before the white fade: yuuhi_a 248 / 312, yuuhi_b 203 / end, meiya 164 /
  179 / 258, marimo_chapter 1358, end of kasumi_h. The copied OM_Invisible is PM's 00ba6ba08e #218 (the plan's
  004fd25d2e #0 is the same instruction but carries its heap's pad, which the builder's replay miscounted). Off:
  nofixwin. Default e87f1ae6.
- **F13** x_4f4791_1674 / 1762: Mikoto's box in exclusive-camera mode as in 2007 (on at the part start, off before its
  end; visible at x_4f4791_1762 lines 2-3). Off: noexcl. Default cd94f26b (English 1539a7a5).
- **Checks** as in I1, per fix (masked / resolved compares, verify_ids13 0 problems with the fix's id range allowed,
  validate_built 0 bad refs, review_patch only the known note, the fix's verifier, an English build). New verifiers:
  impl/I2/checks/c15check.py (F09), ovlcheck.py (F10: 11/11 hut shots). The final builder rebuilds every intermediate
  default; all I2 fixes off = 649d12a5, all fixes off = ea97eb32; anchors with `v11` unchanged; a lab build with the
  scene-test kit hook gives the same cd94f26b. Not yet seen in game.

## Restore audit, implementation step I3: F14-F17 (2026-11-08)

Same plan and record (restore-audit/impl/LEDGER.json); runs, tools and checks: restore-audit/impl/I3. Builder 669ad378
-> 4f32694f (lab only; app_src and release-repo still b0286e68). Every fix is default-on with its own AFR_TEST
off-switch, and each off-switch rebuilds the default from before it. The step was stopped after F16 when the PC was
shut down and resumed: the F16 builder rebuilt its default, noc8 and v11 exactly, then F17 went in.

- **F14 (C2 + L2)** the update's staging inside three split lines: sumika line 273 (billboard close-ups, flashes, the
  1400 ms shake wait, the billboard framing kept until the crossfade), mikoto lines 313-314, kasumi_h after line 38.
  Each gets one continuation line, so tester lines move by 1 in sumika from 274, mikoto from 315, kasumi_h from 39.
  Off: noc2. Default 38cfeb8f.
- **F15 (ENTRY, includes C9)** 18 parts start on the 2007 state (picture, camera, sprites) from their line 1, e.g.
  x_45d98b_1809 lines 1-11, x_3eab17_4548 1-5, x_3eab17_7099 1-5, x_4f4791_1762 1-3. Off: noentry. Default 3523fffc.
- **F16 (C8)** the Myun x Chizuru scene keeps AF's CG throughout: x_45d98b_7366 / 7384 / 7477 / 7593 run on to the
  next part (11 lines appended at the part ends, no line number moves), PM's own copies and 16:9 crops are skipped.
  Off: noc8. Default fdfeeb31.
- **F17 (C1)** Yuuhi route A: after yuuhi_a line 353 the scene goes on as in 2007 (AF 2915-3200, the aftermath route
  A shares with route B): 150 lines, then the window goes, the white fade, the BGM fades out, and PM's chapter end and
  the next chapter start in silence. It is a scene of its own ('yuuhi_a_cont', key 0x7FF00000, YCONT ids) that
  yuuhi_a calls before its end, built exactly like yuuhi_b's tail (checked instruction for instruction); no other
  part, id or key changes. Off: noc1. Default 37bd4720 (English 89e5e4a3).
- **Checks** as in I1 / I2, per fix (masked / resolved compares, verify_ids13 0 problems with the fix's ranges allowed,
  validate_built 0 bad refs, review_patch only the known note, the fix's own check, an English build). New checks:
  impl/I3/checks/c2check.py (F14), c8check.py (F16), c15check3.py / c15check4.py (F09 on the lines F14 / F16 / F17
  add), f17check.py and f17chain.py (F17: the call, the copy of yuuhi_b's tail, sound and window state over route A).
  The final builder rebuilds every intermediate default; all I3 fixes off = cd94f26b, all fixes off = ea97eb32; anchors
  with `v11` unchanged; a lab build with the scene-test kit hook gives the same 37bd4720. Not yet seen in game.

## Restore audit, implementation step I4: F18-F23 and the new default v12 (2026-11-08)

Same plan and record (restore-audit/impl/LEDGER.json); runs, tools and checks: restore-audit/impl/I4. Builder 4f32694f
-> f8b8da6f (lab only; app_src and release-repo still b0286e68). New default **lab-tools/out/v12.ruo1 = 20f0ea89**
(English 10bb4f55), built with DUMP_HEAPS=1 (lab-tools/out/built, build_all.log and build_manifest.json are v12's; v11.ruo1
untouched).

- **F18 (fadetime), F19 (hutdepth), F21 (pmexit): opt-in**, together the scene tester's *Test: extra fixes* Version
  (AFR_TEST=fadetime,hutdepth,pmexit, 1b839a31). The engine code does not prove them equal to 2007: F18 makes PM's
  two-phase transitions as long as 2007's in total, but PM splits types 15 / 16 / 22 evenly where AF runs fixed uneven
  phases (only type 24 becomes equal per phase); F19 re-frames meiya's hut base for AF's layer depth while the
  foreground overlays keep PM's; F21 puts 2007's next-shot staging on PM's own line after four parts, where PM uses its
  own values (and scaling OMs) for its remastered sprites. Lines to compare: marimo_chapter 149 / 131, ayamine 37
  (F18); meiya 265-282 (F19); the PM line after x_45d98b_3736 line 1, 4678 line 6, 5704 line 1, 7302 line 3 (F21).
- **F20 (posture): dropped.** PM's own data says PM keeps a posture set before the sprite call: the root project
  object of photonmelodies11.rio (read only) holds 100 in the settings dword that pm.exe copies to the HumanIn
  switch, and the posture call marks the posture as set. Nothing to change.
- **F22 (C13): default-on**, off nobbexact / nosprexact. Mikoto's and Yuuhi B's 12 big billboards keep their exact AF
  bytes (no re-encode; PM's gallery CG 8fca8611 is no longer overridden), and the 36 Marimo sprites that PM has as lossy
  re-encodes are imported from AF (own key range). Invisible in practice. Default 6dc243ea.
- **F23 (C12, option b): default-on**, off nokashi. The Kashiwagi lead-in conversation plays as 2007 with the update:
  background 724abae7 (PM's copy), Kashiwagi as the AF sprite, no music until kashiwagi's own H BGM. The three lead-in
  parts now carry the whole conversation AF 3eab17 4877-4976, chained like F16's parts; x_3eab17_4957 first calls the
  conversation's start (AF 4877-4956, a scene of its own, like F17's continuation) and its call moves from PM 2449 to
  PM 2308; PM's 53 lines there are bypassed and replaced by the restored copies, which keep PM's own English text.
  Every 1.0.0 id, PM-insert id and key stays (FIXPLAN's single merged scene would have moved later keys and retired two
  inserts; its range [4866, 4976) was off by PM's own message ids). Owner lines: x_3eab17_4877 1-43, then
  x_3eab17_4957 1-6, x_3eab17_4963 1-7, x_3eab17_4970 1-5, kashiwagi 1. Default 20f0ea89.
- **Checks** per fix as before (masked / resolved compares, verify_ids, validate_built 0 bad refs, review_patch only the
  known note, the fix's own check, an English build), new: impl/I4/checks/f19check.py, f22check.py, f23check.py,
  c15check5.py, and impl/verify_ids14.py (verify_ids13 that accepts F23's moved PM call). The final builder rebuilds every
  intermediate default (nokashi = 6dc243ea, + nobbexact,nosprexact = 37bd4720, ... = cd94f26b), all 20 off-switches =
  ea97eb32 = v11, anchors with `v11` unchanged (f85c4b64, bbc1ac7a, ba6e47a3, 8321ad2d); a lab build with the
  scene-test kit hook gives the same 20f0ea89.
- **Dev scene tester** (source): Version row Release / *Test: before restore fixes* (v11) / *Test: extra fixes* /
  *Test: no kept camera* (the row fits: 3 lines); the catalog counts the lines of a called scene (yuuhi_a 503,
  Kashiwagi lead-in 61); fast Play works again (fastplay followed patch_pm's new globals; since F16 every Play had
  fallen back to the full build). selftest.py 385 / 0 failed, selftest_apps.py 180 / 0, --selftest-play 57 / 0 and
  --selftest 33 / 0 on fake folders; live tester state unchanged.
- Not yet seen in game: F14-F23.

## Restore audit, review-fix step RF: F24-F26 and the new default v12 (2026-11-08)

The three reviews of the I1-I4 work (integrity, 2007 exactness, engine + save compatibility) were checked finding by
finding against code and data, and every real one fixed (record: restore-audit/impl/LEDGER.json entries R2-R6 + N1,
F24-F26 and steps.RF; runs, tools and checks in restore-audit/impl/fix). Builder f8b8da6f -> 893751c1 (lab only;
app_src and release-repo still b0286e68). New default **lab-tools/out/v12.ruo1 = 2a64319d** (English 80ffa73b), built
with DUMP_HEAPS=1 (lab-tools/out/built, build_all.log and build_manifest.json are this v12's; v12.log is complete now,
1697 lines; the 20f0ea89-state copies are in impl/fix/pre-v12/). v11.ruo1 untouched.

- **F24 (RETID), default-on, off noretid.** Saves inside a called scene work. A saved VM frame stores the instruction
  its call returns to by id, and pm.exe refuses id 0 (CVmStackFrame::Serialize FUN_00443e10 -> AfxThrowNotSupported,
  the SaveError of 2026-10-10); every scene's closing CVmRet had id 0, so no save could be made during yuuhi_a's
  150-line route-A continuation (F17), nor during the last helper of ayamine, sumika, x_7cea05_1276 and yuuhi_b. Those 6
  closing Rets now carry ids of their own (PM's form, RETID 0x3F910-0x3F915). Default 71a8e31c.
- **F25 (KASHIPM), default-on, off nokashipm.** F23 had moved x_3eab17_4957's inserted call (id 0x325c0) from PM 2449 to
  2308. It is back at 2449 (its 1.0.0 place); the Kashiwagi conversation's start x_3eab17_4877 is called by an inserted
  call of its own before PM 2308, which lands on it. Same play order; no 1.0.0 id moves any more, and a 1.0.0 save on
  PM's own lead-in lines goes on into x_3eab17_4957 again. The scene tester and Test a scene (scenekit) play the start
  scene first in a lead-in play. Default 2449b55f.
- **F26 (WINSHOW), default-on, off nowinshow.** 2007 shows the text window at every line; PM only at a line with visible
  text, so F14's three continuation lines (sumika 274, mikoto 315: click waits; kasumi_h 39) played with the window
  hidden. Before each, PM's OM_Visible on its message box (CUI 0x518eb0: the call PM's own lines make). Default 2a64319d.
- **No byte change:** build_all closes its log at the end (v12.log was cut short); exact id / key counts asserted in a
  full build; F15's kept-camera inserts take ENTRY ids (none today); comments and dead code (review R2-R6).
- **Builds without the official 2007 update failed since F09** (BuildError in its update-link count, then the
  kept-camera count): fixed; without the update the default builds (526384d4) and `v11` gives the 1.0.0-era builder's
  output (584137b4).
- **Checks:** every off-switch rebuilds the build before its fix (nowinshow = 2449b55f, + nokashipm = 71a8e31c,
  + noretid = 20f0ea89, ... down to cd94f26b), all 23 off-switches = ea97eb32 = v11, anchors with `v11` unchanged
  (f85c4b64, bbc1ac7a, ba6e47a3, 8321ad2d); validate_built 0 bad refs, review_patch only the known note; new
  impl/verify_ids15.py: 9,652 1.0.0 ids kept, 0 shifts, PM heaps = 1.0.0's ids in place plus F25's one call, every v11
  id kept; the review's own compat scripts on v12: no call returns to an id-0 instruction. Scene tester selftests 385 /
  180 / 57 / 33, 0 failed; fast-Play prove (Kashiwagi with lead-in) byte-identical; kit test 109 / 0.
- Owner notes for CHANGELOG / OWNER-TESTS: LEDGER steps.RF owner_notes. Not yet seen in game: F14-F26.

## Restore audit, sync step: launcher synced to v12, exe rebuilt (2026-11-08, night)

Sources: lab-tools/out/research/restore-audit/impl/sync (pre-sync/ copies of every file changed here, scenekit.sync.diff,
tools/ = the runners, checks/ = kit_lines.py, owner_lines.py and check_countheap2.py, results/). Record: LEDGER.json
steps.SYNC.

- **Sources in step.** build_all.py 893751c1 (the RF builder) and scenekit.py copied from lab-tools/scripts to app_src
  and release-repo/src. The 18 modules shared with the lab and omsig_data.txt are byte-identical in all three places
  (blocks 7ade25a2 unchanged). app.py dcccead2 and oscompat.py 3a3dd960 are identical in both app copies, and data/ is
  identical (objmap.json and sound_pairs.json equal the lab's). New stdlib imports in the builder (itertools, re) are
  inside the exes. The builder reads no new data file; its new outputs are written only with DUMP_HEAPS.
- **Test a scene follows F17.** scenekit 523c7dca (shipped before) -> cf885f5f (RF: the Kashiwagi start scene called
  first) -> b6431894: the new part_lines counts the scene a part comes with, as the developer catalog does
  (catalog.part_lines). The window now shows Yuuhi — first with 503 lines (353 + the 150 lines of the route-A
  continuation, which play in the same test; before: 353). The Kashiwagi lead-in stays at 61. Patch bytes are
  unchanged. checks/kit_lines.py: all 11 kit items equal the catalog's lines, lead-in lines and lead-in parts, for the
  default and the English kit.
- **Static import scan** (sync-1.1.0/import_scan.py on both source folders and both exes): 20 modules shipped, all in
  both specs' hiddenimports, in app.BUNDLED and in the PYZ; no stdlib import missing from the exes; data == src.
- **The exe.** dist/AFRestore.exe is 70bd9a66; the previous 0694c3a4 is in dist/old/AFRestore-1.1.0-pre-restorefix.exe.
  The console twin build/restorefix-1.1.0/dist-console/AFRestoreConsole.exe (d475b8b1) was built first, both with
  build/pyi312 (PyInstaller 6.22.3, Python 3.12.10). Archives are equal entry by entry (1161 entries, base_library.zip
  with identical contents); the 19 frozen modules and the app script equal app_src and release-repo/src compiled; the
  7 data files are equal.
- **exe == lab** (AFR_AF_PATCH = the save-backups copy of the official update, read only; every patch deleted after
  hashing): lab default (warm shared cache, kit) 2a64319d = v12, lab English 80ffa73b; console exe --build with a temp
  LOCALAPPDATA: 2a64319d (82 s, cold cache) and 80ffa73b (52 s, warm). Both exe kits are byte-identical to the lab kits.
- **Tests (Windows):**
  - --selftest and --selftest-scenetest (synthetic and fixture) OK from source on 3.11, 3.12 and the 3.12 venv
    (--selftest also on 3.14), and in both exes (the windowed one by exit code).
  - test_kit_lab 109/109 on the lab default patch and kit.
  - test_gui_merged 71/71 (AFR_TEST_OFFICIAL_DIR = the save-backups folder; run with -X utf8, because a cp932 console
    stopped it at a check mark), test_selftest 31/31, test_spec 16/16, test_windows_regression 22/22,
    test_gui_scenetest 32/32, measure_layout 8/8 (every window withdrawn).
  - check_countheap2 6/6 on 3.11, 3.12 and 3.14. It is a copy of review-fix-1.1.0/check_countheap.py that makes its
    mutations inside class CountHeap: the builder now has a second parser class with the same vm_call line (CanonHeap,
    F08), so the old tool's unique-text assert stopped after its two real-builder checks (both passed).
  - Developer scene tester: selftest_apps 180/180, selftest.py 385/385, --selftest-play 57 and --selftest 33 (fake
    folders). The live tester state (lab-tools/out/scenetest without fake/, testers/: 234 entries) is unchanged.
- **Tests (Linux, WSL, Python 3.14):** test_selftest 27/27, test_gui_merged 70/70, test_gui_scenetest 33/33,
  check_countheap2 6/6, --selftest-scenetest synthetic and fixture OK; --selftest stops at "import tkinter", as before
  (no tkinter in that Python).
- **Owner line numbers** read again from v12's built heaps (checks/owner_lines.py). Numbers given before F14 move by
  one after its inserted lines: mikoto's emptied line is 317 and its end comes after line 346; kasumi_h's canopy bed
  is in front from line 227 to 265 (second hut shot before 264), and its end comes after line 265. A test play calls
  the parts in a row at the prologue, so PM's own lines around a part do not run: F04, F06, F07, F11 and the end of
  F17 can only be seen when playing through (OWNER-TESTS says so).
- **Docs:** CHANGELOG 1.1.0 has one block on the restore fixes and a line on old saves (steps.RF owner notes C3 and C6;
  C5 is the README's existing note). OWNER-TESTS-1.1.0.md is rewritten as the in-game checklist. docs/MODLOG.md mirrors
  this file again (header and the two privacy redactions kept; I1-I4, RF and this section added). The README is
  unchanged.

## 1.1.0: final review, doc fixes (2026-11-08, night)

Sources: lab-tools/out/research/restore-audit/impl/fix2 (pre/ = the files before this step, partlines.py). Record:
LEDGER.json steps.FINALFIX. Docs only: no builder, launcher or exe byte changed (build_all 893751c1, v12 2a64319d,
English 80ffa73b, dist/AFRestore.exe 70bd9a66, as the sync step left them).

- **CHANGELOG 1.1.0:** saving no longer fails at the end of five restored scenes, not four (Yuuhi first and second,
  Sumika, Kei Ayamine and Yuuko & Marimo's room event: review-compat retids.txt, F24). The restore-fix block says the
  differences are fixed wherever Photonmelodies' engine can reproduce 2007 (FIXPLAN engine_limits; F18, F19 and F21
  stay opt-in). The old-save note names lead-ins (every RF C3 part is a lead-in part, up to 75 lines) and the camera
  move; skip read text covers re-made lines (the Kashiwagi lead-in, C6). Dated 2026-11-08.
- **OWNER-TESTS-1.1.0.md:** the same points. Items 11 and 12 are marked scene tester only (Test a scene lists 11
  scenes). F21's places are given: the game's own line after Kei Ayamine with-lead-in line 9, Myun × Chizuru
  with-lead-in line 3, "Narration — 1 line (2)" and "(3)" (part line counts from v12's heaps, partlines.py), and a test
  cannot show it. Yuuhi — first is in play order. The owner puts the upload day into the CHANGELOG heading.

## 1.1.0: independent verification, doc wording (2026-11-09)

Sources: lab-tools/out/research/restore-audit/impl/verify (pre/ = the files before this step). Record: LEDGER.json
steps.VERIFY. Docs only: no builder, launcher or exe byte changed (build_all 893751c1, v12 2a64319d, English 80ffa73b,
dist/AFRestore.exe 70bd9a66).

- **Rebuilt, one at a time, from the current builder:** lab default 2a64319d and console exe default 2a64319d (kit
  equal), lab and exe English 80ffa73b, AFR_TEST=v11 ea97eb32, nowinshow 2449b55f, +nokashipm 71a8e31c, +noretid
  20f0ea89, all 23 FIX_OFF tokens ea97eb32, no official update 526384d4. The windowed exe and its console twin hold the
  same archive contents, equal to app_src and release-repo/src.
- **F24, F25, F26 and N1 re-checked from pm.exe, Vm60.dll and the built heaps (not refuted).** F24: frame Serialize
  FUN_00443e10 throws on a return instruction with id 0; PM's own Rets after a call all carry ids (43). F25: no 1.0.0 id
  moves (verify_ids15). F26: AF's CVmMsg execute (FUN_1006cee0) clears the window-hidden bit at every line; the inserted
  OM_Visible is PM's own form. N1: the no-update count asserts come from real build logs. Record fix: no-update builds
  first broke at F00 (the CAMERA_KEEP 65 assert), not at F09.
- **CHANGELOG 1.1.0:** the restore-fix block no longer says every difference is fixed where the engine allows it
  (FIXPLAN still_unproven has items that are neither fixed nor engine limits); Kasumi's hut foreground "is drawn in
  front" (the overlay edges are an approximation).
- **OWNER-TESTS-1.1.0.md:** the Done line says the same, and a short *Not proven from the code* list gives the
  places to look (flash fades, the Marimo choice numbers, the Sumika 273 shake end, the hut overlay edges, the room
  scene's curtain wipe, Miki lines 1-6).

## Released as 0.1.0 (2026-11-09)

- **Version number.** The release that this log calls 1.1.0 is published as **v0.1.0**. The first release (called
  1.0.0 in this log) had no number: its tag is `Muv-LuvAlteredFable` and its app shows no version.
  - `src/app.py`: `APP_VERSION = '0.1.0'`.
  - `LEGACY_RELEASES` counts the first release as 0.0.0, below every numbered release. With 1.0.0 it would have been
    offered as an "update" to 0.1.0.
  - The rebuild hint for content built by the first release says "an older version" instead of "version 1.0.0".
  - `CHANGELOG.md`: section `## 0.1.0 - 2026-11-09`, and `## First release - 2026-10-11`. `BUILDING.md`: its examples
    use v0.1.1.
- **Checked:**
  - The workflow's pre-flight with tag v0.1.0 passes, and with v1.1.0 it refuses.
  - The release-notes extraction finds the 0.1.0 section (51 lines).
  - `app.py --selftest`: SELFTEST OK 0.1.0.
  - The updater tests with 0.1.0 expectations, against a local fake GitHub: 61/61. This includes the real download,
    sha256 check, swap and restart of a test exe. The legacy release is 0.0.0 and not newer; v0.1.1, v0.10.0 and
    v1.0.0 are newer; v0.1.0, v0.0.9 and v0.1.0-rc2 are not.
- **Exe:** `dist/AFRestore.exe` rebuilt (fdd990a1; the 1.1.0 build 70bd9a66 is kept as
  `dist/old/AFRestore-1.1.0.exe`). Its frozen self-test prints SELFTEST OK 0.1.0. Archive compare with 70bd9a66: only
  the app script differs. The 16 builder modules and the data files are identical and equal to app_src, so it builds
  the same patch (default 2a64319d).
