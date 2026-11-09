# Building and releasing

The repository is flat: the code (`app.py`, `scenetester.py`, the builder modules), the data files (`*.json`,
`omsig_data.txt`, `afrestore.ico`, `afrestore.png`) and the two PyInstaller specs are all at the top level. The only
file in a folder is the release workflow, `.github/workflows/release.yml`.

## The two programs

| Program | Spec | Windows | Linux |
|---|---|---|---|
| Altered Fable Restore | `AFRestore.spec` | `AFRestore.exe` | `AFRestore` |
| AFRestore Scene Tester | `AFRestoreSceneTester.spec` | `AFRestore Scene Tester.exe` | `AFRestoreSceneTester` |

The Scene Tester is `app.py` started in tester mode by `scenetester.py`, so both programs bundle the same modules and
data files (in the bundle's `data` folder) and always have the same version.

## Release files

| File | Made by | Holds |
|---|---|---|
| `AFRestore-vX.Y.Z-win-x64.zip` | built on Windows and attached by hand (the workflow builds it when it's missing) | `AFRestore.exe`, `AFRestore Scene Tester.exe` |
| `AFRestore-vX.Y.Z-linux-x64.tar.gz` | the workflow | `AFRestore`, `AFRestoreSceneTester` |
| `SHA256SUMS.txt` | optional by hand (the zip's line); the workflow writes it for every archive | `<sha256>  <file name>` lines |
| `RELEASE_NOTES_vX.Y.Z.md` | the `CHANGELOG.md` section (attached by the workflow when missing) | the release notes |

*Check for updates* takes the archive for its system by exactly this name, with the release's own version, and the
two programs at the archive's top level. It checks GitHub's sha256 digest and, when the release has one, the archive's
line in `SHA256SUMS.txt`.

## Make a release on the website

1. In `app.py`, set `APP_VERSION = 'X.Y.Z'`, and add a `## X.Y.Z - YYYY-MM-DD` section to `CHANGELOG.md`. The app's
   update check compares `APP_VERSION` with the newest release's tag, so a wrong value makes users see the update
   offer again and again; the workflow stops when they differ.
2. Upload the changed files with *Add file → Upload files*. Every file goes to the top level.
3. *Releases → Draft a new release*: tag `vX.Y.Z` (new), a title, the `CHANGELOG.md` section as the text. Attach the
   Windows zip (or leave it out: the workflow then builds it), then *Publish release*. `SHA256SUMS.txt` and
   `RELEASE_NOTES_vX.Y.Z.md` may be attached too; the workflow writes the first and adds the second when it's missing.
4. The **Release** workflow starts by itself (*Actions* tab, about 10 minutes). It builds both programs for Linux and
   checks the Windows zip. Then it attaches `SHA256SUMS.txt` with a line for every `.zip` and `.tar.gz` the release
   will hold, then `AFRestore-vX.Y.Z-linux-x64.tar.gz`, and `RELEASE_NOTES_vX.Y.Z.md` if it's missing. If the release
   has no Windows zip, it builds and attaches that too. It never changes the release's title or text.

To make the Windows zip, build both programs from the release's files (see *Build locally*), select
`AFRestore.exe` and `AFRestore Scene Tester.exe` in `dist` (the two files, not the folder), right-click →
*Compress to → ZIP File* (Windows 10: *Send to → Compressed (zipped) folder*), and rename the zip to
`AFRestore-vX.Y.Z-win-x64.zip`.

The website can't upload folders, so the workflow file is created by typing its path: *Add file → Create new file*,
name `.github/workflows/release.yml`, paste the file's content, *Commit changes*. It has to be in the repository
before the release is published, because GitHub runs the workflow file of the release's tag.

If a run fails, fix the cause, then *Actions → Release → Run workflow* with the tag `vX.Y.Z`: it does the same again
for that release and replaces the files it attached. A re-run uses the workflow file of `main` but builds the files of
the release's tag, so a fix to `release.yml` works right away; a fix to any other file needs a new release (delete the
release and its tag and make them again, or release the next version). The Windows zip is rebuilt only when it's not
on the release. To replace your own zip, attach the new one in place of the old one and delete `SHA256SUMS.txt` on the
release before the re-run. *Run workflow* with the tag left empty makes a test build: both archives are kept as run
artifacts for 14 days and no release is touched.

## What the workflow checks

- Before building: every file the specs name is at the top level, both specs build their paths from `SPECPATH` (no
  `C:/...` paths), `app.py` has `--selftest`, and `APP_VERSION` equals the tag.
- After building: each frozen program holds its entry script, the builder modules, the data files and Tcl/Tk, and
  runs once with `--selftest`. That flag opens no window, writes no files and prints `SELFTEST OK <version>` (exit
  code 0), or `SELFTEST FAILED <step>:` and the traceback (exit code 3). It has to catch every exception itself: in
  a windowed Windows program an uncaught one opens an error box that nobody can close on the build machine.
- The archives: exactly the two programs at the top level (Linux: mode 755). A Windows zip attached by hand is opened
  the way the app's update opens it, and on a Windows machine both programs in it run once with `--selftest` and must
  print `SELFTEST OK` with the release's version.
- `SHA256SUMS.txt`: every archive already on the release is downloaded and compared with GitHub's digest and with the
  line the release's earlier `SHA256SUMS.txt` had for it. The file is attached before the archives, and at the end
  GitHub's digest of every archive must equal its line.

PyInstaller 6.22.3 and its dependencies are pinned by version and SHA-256 (`BUILD_REQUIREMENTS`). The Linux programs
are built in an AlmaLinux 8 container (glibc 2.28, so they run on the Steam Deck and most desktop Linux) with Python
3.12, Tcl/Tk 8.6 and OpenSSL from AlmaLinux's packages, updated first. The bundled OpenSSL protects the update
download; a fix that comes out later reaches Linux users with the next release.

## Build locally

```
pip install pyinstaller==6.22.3
pyinstaller --noconfirm AFRestore.spec
pyinstaller --noconfirm AFRestoreSceneTester.spec
```

This needs Python 3.12 with tkinter and writes both programs to `dist/`. A Linux build runs only on systems whose
glibc is at least as new as the build machine's. From source, `python app.py` and `python scenetester.py` start the
two programs.
