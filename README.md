# Altered Fable Restore

Restores the content that was cut from **Muv-Luv Altered Fable** to **Muv-Luv photonmelodies♮** on
Steam: the 18+ scenes, the uncensored CGs and the Marimo-chan route. The launcher builds everything from your own
copies of both games. This launcher uses the dlsite version of **Muv-Luv Altered Fable** which you can find on the sukebei.nyaa site if you search "20thBOX Edition".

## Download and play

1. Download the launcher from the [Releases](../../releases) page:
   - **Windows:** `AFRestore.exe`. If Windows warns that the app is unrecognized, choose **More info → Run anyway**.
   - **Linux / Steam Deck (Desktop Mode):** `AFRestore-linux-x86_64.tar.gz`. Extract it and run `AFRestore`.
2. The launcher finds both games by itself. If it doesn't, click **Browse...** and pick each game's folder.
   Both lines must say **found, correct version**.
3. Click **Build & install**. It takes a few minutes.
4. Click **Play (via Steam)**, or on the Steam Deck start the game from Gaming Mode.

**Turn OFF** removes the restored content without uninstalling anything, and **Turn ON** brings it back.
**Test a scene...** plays one restored scene (after the game's short prologue); **Back to normal** takes it out and
puts your saves back.

### English text (optional)

The restored lines are in Japanese. For English, pick the `afhook.pkg` of the
[afhook fan translation](https://forums.fuwanovel.moe/topic/29569-muv-luv-altared-fable-translation-patch-play-testers-needed-orginial-release-only/)
in the launcher's English text row before building, and set *Options → Text Language* to **English** in the game.
Only the restored lines use it; Photonmelodies' own lines keep their official translation.

### Updating

Click **Check for updates** in the launcher (it turns green when a new version is out), then **Rebuild & install**.

## Requirements

- Windows 10 or 11, or 64-bit Linux (Steam Deck included)
- Muv-Luv photonmelodies♮ on Steam, current version
- Muv-Luv Altered Fable, 2007 PC release (DLsite), the folder containing `altfable.rio`
- About 2.5 GB of free space on the drive with Photonmelodies

## Features

- The cut 18+ scenes, with their lead-ins and aftermaths
- The original, uncensored CGs, also in the scenes Photonmelodies kept
- The Marimo-chan route, chosen in the island section's "who to spend time with" picker
- Original voices, music, sound effects, backgrounds and sprites
- Steam achievements work

## Screenshots

<p align="center">
   <img width="48%" alt="Screenshot 2026-11-07 171028" src="https://github.com/user-attachments/assets/052b85e8-b8ab-4484-b7fc-134065c994d9" />
   <img width="48%" alt="Screenshot 2026-11-09 044133" src="https://github.com/user-attachments/assets/6b2a55ff-00e5-4961-92fd-8d1369dd301b" />
   <img width="48%" alt="Screenshot 2026-11-09 023605" src="https://github.com/user-attachments/assets/60d5fb4c-bdf5-4666-9f93-5797256d059a" />
   <img width="48%" height="632" alt="Screenshot 2026-11-09 022443" src="https://github.com/user-attachments/assets/25ad12df-13ac-4b4e-ad61-6d0af5ea3dea" />
</p>

## Status and support

Without the English text, set *Options → Text Language* to **Japanese** for the intended look. With it, the few
restored lines the fan translation doesn't cover stay in Japanese.

If the game shows an error right after starting, it is resuming a session saved with a different version of the
restored content: return to the title screen and load another save. If Steam updates Photonmelodies, click
**Turn OFF** before playing until the launcher supports the new version.

Found a problem? Open an issue with a screenshot and the scene it happened in.

## Documentation

- [`docs/MODLOG.md`](docs/MODLOG.md): the engineering journal (file formats, engine facts, decisions, tests)
- [`BUILDING.md`](BUILDING.md): how releases are built, and how to build the launcher yourself

## Credits and licence

Muv-Luv, Muv-Luv Altered Fable and Muv-Luv photonmelodies♮ are © âge / aNCHOR. This is an unofficial fan project,
not affiliated with or endorsed by them. Please buy the games. The English text is the work of the afhook fan
translation team.

The code is released under the [MIT License](LICENSE). Built with AI coding agents (Claude Code, with OpenAI Codex
for part of the work), directed and play-tested by the project owner.
