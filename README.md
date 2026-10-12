# Altered Fable Restore

Restores content that was cut from **Muv-Luv Altered Fable** when it was included in the Steam release of
**Muv-Luv photonmelodies♮**.


## What it restores

- +18 scenes
- The Marimo-chan route

That is 73 restored parts and about 5,100 lines, with the original voices, background music, sound effects,
backgrounds, event CGs and character sprites.

## Requirements

You need **both** games:

Muv-Luv photonmelodies♮ and Muv-Luv Altered Fable 2007 from Dlsite (You can get it on the sukebei.nyaa.si site specfically from the 20th BOX Edition)

## How to use

1. Download `AFRestore.exe` from the [Releases](../../releases) page and run it.
   Windows may warn that the app is unrecognized; choose **More info → Run anyway**.
2. Both games are found automatically. If not, click **Browse...** and pick each game's folder.
   Each line must show **"found, correct version"**.
3. Click **Build & install** (takes a few minutes).
4. Click **Play (via Steam)**. 

**Turn ON / OFF** switches the restored content without rebuilding. Close the game first.

**Text language:** the restored text is Japanese. Set *Options → Text Language* to **Japanese** for the intended
look. With the text language on English, restored lines still display, in Japanese.

**Getting Marimo-chan's route:** during the island section, pick Marimo in the "who to spend time with" portrait
picker whenever it appears.

## Troubleshooting

- **The game shows an error right after starting.** The game resumes your last session automatically; that session
  was saved with a different version of the restored content (or with it OFF). Go back to the title screen
  (right-click → Return to Title) and load an earlier save or start again.
- **Saves made while the content is ON** (especially inside restored scenes) may not load while it is OFF.
- **Steam updated Photonmelodies.** Open the app and click **Turn OFF** before playing. The restored content is
  built for one exact game version; the app will not build or turn it back ON for a different version, so it cannot
  break the game.

## Uninstall

Click **Turn OFF**, then delete `AFRestore.exe`, the `AFRestore-off` folder inside the Photonmelodies folder, and
the folder `%LOCALAPPDATA%\AFRestore`.

## Safety notes

- Only Altered Fable story scripts are changed, and only by *inserting* calls. No original instruction is removed
  or reordered, so every Steam achievement trigger stays reachable (checked for every build).
- Other stories (Alternative, Adoration, Resurrection, ...) are untouched. The mini-games are not restored.
- The restored content lives in one patch file, `photonmelodies11.rio.ruo1`, in the game folder. The game's own
  archives are never modified.

## How it works

The app reads the script heaps of both games, converts the cut Altered Fable passages into Photonmelodies-native
scripts (new instruction format, Unicode text, voice/BGM/sprite imports, engine helper mapping) and writes them,
plus the imported assets, into a `.ruo1` patch file that the game loads at startup. Each restored passage is called
from one inserted instruction in the matching Photonmelodies chapter.

[`docs/MODLOG.md`](docs/MODLOG.md) is the full engineering journal: file formats, engine facts, decisions and
test results.

## Building from source

```
pip install pyinstaller==6.22.3
pyinstaller --noconfirm src/AFRestore.spec
```

Python 3.12. The result is `dist/AFRestore.exe`. You can also run the app directly with `python src/app.py`, or
build the patch without the GUI: `python src/app.py --build "<photonmelodies folder>" "<Altered Fable folder>" <out.ruo1>`.

## Credits

- Muv-Luv, Muv-Luv Altered Fable and Muv-Luv photonmelodies♮ are © âge / aNCHOR. This is an unofficial fan
  project, not affiliated with or endorsed by the rights holders. Please buy the games.
- Format knowledge from the rUGP/AGES community tools (rugptools and others).
- **AI disclosure:** this tool was reverse-engineered and written with AI coding agents (Anthropic's Claude in
  Claude Code, with OpenAI Codex for part of the work), directed and play-tested by the project owner.

## License

The code in this repository is released under the [MIT License](LICENSE). It contains no game data; the game
content it restores remains the property of its rights holders.
