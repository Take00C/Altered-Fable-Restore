# Building and releasing

Release files are built by GitHub Actions ([`.github/workflows/release.yml`](.github/workflows/release.yml)).
Nothing has to be built locally.

## Cut a release

1. In `src/app.py`, set `APP_VERSION = 'X.Y.Z'` to the new version (the tag without the `v`). The app's update check
   compares this with the newest release's tag, so a wrong value makes users see the update offer again and again.
   The workflow stops before building when they differ. (For a pre-release tag `vX.Y.Z-rc1`, `X.Y.Z` or `X.Y.Z-rc1`
   is accepted.)
2. Add a `## X.Y.Z - YYYY-MM-DD` section to `CHANGELOG.md`. Its text becomes the release notes.
3. Commit, then push a tag that starts with `v` (the workflow file must be in the tagged commit):

   ```
   git tag v0.1.1
   git push origin v0.1.1
   ```

   Creating the tag on GitHub (*Releases → Draft a new release → new tag*) works too; the workflow then adds the
   files to that release.
4. Wait for the **Release** run in the *Actions* tab (about 10 minutes). It creates release `v0.1.1` with both
   files, or, if the release already exists, uploads them and replaces files with the same name.
   A tag with a hyphen (`v0.1.1-rc1`) is published as a pre-release. If the run fails, fix the cause, then delete the
   tag (`git push origin :refs/tags/v0.1.1`, `git tag -d v0.1.1`) and tag again.

A release run also needs these in the tagged commit (the workflow checks them first):

- `src/app.py` handles `--selftest`: no window, no files written, exit code 0 when the frozen app works. It prints
  `SELFTEST OK <version>`, or on failure `SELFTEST FAILED <step>:` and the traceback (exit code 3).
  It must catch every exception itself and exit non-zero, because an uncaught exception in the windowed Windows exe
  opens an error box that nobody can close on the build machine.
- `src/AFRestore.spec` builds every path from `SPECPATH` (no `C:/...` paths). The spec in `app_src` uses absolute
  paths, so convert them when copying it here.

## What the workflow produces

| File | Built on | For |
|---|---|---|
| `AFRestore.exe` | `windows-latest`, Python 3.12 | Windows 10/11 x64 |
| `AFRestore-linux-x86_64.tar.gz` | AlmaLinux 8 container (glibc 2.28); Python 3.12, Tcl/Tk 8.6 and OpenSSL from AlmaLinux packages | x86_64 Linux with glibc 2.28 or newer, e.g. Steam Deck. Contains one executable file, `AFRestore`. |

Both use `src/AFRestore.spec` and PyInstaller 6.22.3. PyInstaller and its dependencies are pinned by version and
SHA-256 in the workflow (`BUILD_REQUIREMENTS`). Each job syntax-checks `src/*.py`, checks that the frozen app contains
its data files, the builder modules and Tcl/Tk, and runs it once with `--selftest`. The SHA-256 of each file, and the
Linux package versions, are shown in the run summary.

The Linux binary carries its own copy of OpenSSL, which protects the app's update download. The build updates the
AlmaLinux packages first (AlmaLinux 8 gets security fixes until 2029), so each release has the fixes available on
its build day. A fix that comes out later reaches Linux users only with the next release.

## Test build without a release

*Actions → Release → Run workflow*, with **tag** left empty: both files are attached to the run as artifacts
(kept 14 days) and no release is touched, even when the run is started from a tag. Without `--selftest` in
`src/app.py`, the smoke run is skipped with a notice. Entering an existing tag instead rebuilds that tag and replaces
its release files.

## Build locally

```
pip install pyinstaller==6.22.3
pyinstaller --noconfirm src/AFRestore.spec
```

This needs Python 3.12 with tkinter and writes `dist/AFRestore.exe` (Windows) or `dist/AFRestore` (Linux). A
Linux build runs only on systems whose glibc is at least as new as the build machine's.
