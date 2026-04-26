# v1.0.5 — Multi-platform builds + StreamCraft 0.7.26

First TBA release with platform-specific builds. Mac and Linux players now have working webcam, screen share, and voice in-game — previously these were Windows-only because StreamCraft's LiveKit/FFmpeg natives only shipped for Windows.

## Pick the file for your OS

| Your platform | File |
|---|---|
| Windows | `TBA-1.0.5.mrpack` |
| macOS Apple Silicon (M1/M2/M3) | `TBA-1.0.5-macos-arm64.mrpack` |
| macOS Intel | `TBA-1.0.5-macos-x86_64.mrpack` |
| Linux | `TBA-1.0.5-linux.mrpack` |

The Modrinth App's **Install** button defaults to the Windows file. On Mac or Linux, pick your variant from the file list — using the wrong one means StreamCraft won't load (you'll see "failed to load native library" errors and no voice/video). Or grab the right one automatically at https://theblock.academy/downloads.

## What changed since 1.0.3

### Updated
- **StreamCraft 0.6.2 → 0.7.26** — adds platform-specific native bundles (LiveKit FFI, JNA, JavaCV/FFmpeg). This is what unlocks the Mac/Linux experience.

### Fixed
- **Distant Horizons update prompt** — suppressed the "New update available! 2.4.5-b → 3.0.2-b" popup on first launch. DH is pinned to 2.4.5-b deliberately; 3.0.x breaks server-side mixins (Travelers Backpack `LanguageMixin` crash, see v1.0.3 incident notes).

### Notes
- Mod count: 195 (unchanged from 1.0.3).
- v1.0.4 was published with the multi-platform changes but missed the DH popup fix — v1.0.5 supersedes it.
