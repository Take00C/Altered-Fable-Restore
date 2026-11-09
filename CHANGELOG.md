# Changelog

Supported game versions are checked by file size and SHA-1 (`required.json`).

## 0.1.0 - 2026-11-09

- Uncensored CGs: 27 pictures that Photonmelodies edited (the hot spring scene and its close-ups, the Myun × Chizuru
  CGs, several gallery CGs) now show the original 2007 art, also in the scenes Photonmelodies kept and in the
  gallery. Cropped close-ups are rebuilt from your own copy of the 2007 game when you build.
- Optional English text: pick the afhook fan translation's `afhook.pkg` and the restored lines appear in English
  (with Photonmelodies' English names) when the game's *Options → Text Language* is set to English. Without it
  everything stays as before.
- Scenes that started on the wrong picture (Myun × Chizuru, the hot spring lead-in) now open on the 2007 CG and
  framing.
- Camera framing, checked against the game's code:
  - Every CG shot uses the 2007 game's own camera values (Photonmelodies frames on the same 1024×600 camera screen),
    so the restored scenes are framed like 2007. The zoom factors of the first release (about 1.2× closer) are gone.
  - The 2007 camera carries over when the picture changes, in every restored scene, the way Photonmelodies' own ports
    of these scenes do it. Shots that showed the whole picture inside black bars, or started on it before a camera
    move (Mikoto's scene, and the same kind of shot in other scenes), now use the 2007 framing.
  - Mikoto's close-ups are the 2007 game's 3D close-ups, no longer flattened into plain pictures as in the first
    release.
  - A close-up pan in the Marimo-chan chapter that showed the wrong part of the picture now shows the 2007 close-up,
    centred about 11 pixels lower (the engine's camera values are whole numbers).
- Closer to the 2007 staging in every restored scene, checked against the game's code:
  - Camera moves keep their 2007 position (Meiya, Yuuhi).
  - Yuuhi's opening colour flash plays.
  - 15 screen shakes that showed nothing now shake (mostly the Marimo-chan chapter).
  - Every shake starts on its own line instead of a few lines later, and the scenes wait for it to finish before
    the background changes.
- Every restored scene compared with the 2007 game and its official update in the game's code, and these differences
  fixed:
  - Yuuhi's first scene goes on into the aftermath that 2007 plays there (150 lines).
  - The Kashiwagi lead-in conversation and the Myun × Chizuru CGs are as in 2007, and Kasumi's hut foreground is
    drawn in front.
  - The Marimo-chan chapter's song plays, two songs no longer restart, and sound no longer runs on past the end of
    a chapter.
  - The official update's close-ups in three scenes (Sumika, Mikoto, Kasumi), its sprite positions and shakes, and
    the two lines it emptied.
  - Two lines of the Marimo-chan chapter play both of their voices. The speaker's mouth moves, and the game's
    per-character voice settings apply.
  - Scenes start on the 2007 picture, camera and sprites, and no camera move or sound plays twice when a scene hands
    back to the game.
  - The text window hides before white fades and shows on every line, as in 2007.
  - Mikoto's and Yuuhi's 12 large close-ups and 36 Marimo sprites are the 2007 pictures, not re-encoded.
  - Saving no longer fails during the last seconds of five restored scenes.
- Saves: a save from the first release made inside a scene's lead-in may repeat a few lines or a camera move once,
  where the restored lines hand back to the game. *Skip read text* stops once on new or re-made lines (including the
  Kashiwagi lead-in conversation).
- **AFRestore Scene Tester**, a second program: pick a restored scene and play it right away (after the game's short
  prologue and opening movie). Your saves are backed up first; **Back to normal** takes the scene out and puts your
  restored content and saves back exactly as they were, also by itself when the game closes while the Scene Tester
  is open (on by default). Only one of the two programs can be open at a time.
- Rebuilds are faster: the re-encoded pictures are kept for the next build.
- Downloads: `AFRestore-v0.1.0-win-x64.zip` for Windows and `AFRestore-v0.1.0-linux-x64.tar.gz` for Linux and the
  Steam Deck (Desktop Mode), each with both programs.
- **Check for updates** button: downloads the new version of both programs, verifies it and restarts.

## First release - 2026-10-11

First public release.

- Restores 73 parts (about 5,100 lines): most cut 18+ scenes with their lead-ins and aftermaths, Kasumi Yashiro's
  18+ replay scene, the Myun × Chizuru scene, cut adult gags, Yuuko & Marimo's room event and the Marimo-chan route.
- Original voices (including two-voice lines), BGM, sound effects, backgrounds, CGs, sprites, furigana and screen
  shake.
- Restored lines display correctly with the game's text language set to Japanese or English (in English mode the
  Japanese text is pre-wrapped for the English text layout).
- GUI: auto-detects both games, checks versions, Build & install, Turn ON / OFF, Play via Steam.
- Uses Altered Fable's official patch when present: corrected text and voice takes on restored lines (the unpatched
  release plays the wrong voice take on some lines), the patch's re-staged shots, and the assets that exist only in
  the patch.
- Every restored scene compared with the original 2007 game: scene endings hand back to Photonmelodies at the right
  line (no replayed or extra shots, no stray seconds of another route), music and sound effects use Photonmelodies'
  copy only when it is the same recording, and CG framing is adjusted for Photonmelodies' 16:9 screen.
