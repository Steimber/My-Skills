---
name: reel-maker
description: "Trigger: reels, TikTok, Shorts, beat sync, vertical 4K, testimonial voice, brand intro. Build beat-synced branded vertical reels from raw clips."
license: Apache-2.0
metadata:
  author: "Steimber"
  version: "1.2"
---

## Activation Contract

Load when raw phone clips/photos must become short vertical videos: beat-synced cuts, titles/subtitles, brand intro/end card, color matching, testimonial voice isolation, music under speech.

## Hard Rules

- Never lower quality: decode originals each render, one H.264 encode (CRF 16 at 4K); never overwrite originals; finals go to a separate `--out`.
- View every clip (contact sheets) before choosing windows; check rotation and A/V start offsets.
- Verify each output with `tools/verify_media.py` (A/V diff, clean decode, packet gaps < 0.03 s, ~-14 LUFS, TP <= -1 dBTP), then a human contact-sheet pass.
- Text inside 15-72 % of the height (hero group above 70 %), never over faces (`tools/textzone.py --faces`).
- Judge speech on the FINAL MIX (`tools/verify_voice.py`); confirm names heard in speech before burning subtitles.
- Only songs the user provides (platforms may mute them); fonts/logo are the user's. No synthesized SFX unless asked.
- Each source range once across reels (`--table`, `tools/orb_repeats.py`).

## Decision Gates

| Situation | Action |
|-----------|--------|
| Landscape clip to 9:16 | `CENTER` crop; `REFRAME` follows the subject |
| Talking head | wide/`tight=True` alternation, B-roll inserts over jump cuts |
| Speech in a clip | `voice/quick.py`; noisy room: candidates + `evaluate.py` |
| Speech over a sung song | instrumental bed (`tools/make_bed.py`), not deep ducking |
| Color | LUT grade + shot matching; `look/before_after.py` first |
| Plain cut list | `assets/build_music_reels_ffmpeg.py` |

## Execution Steps

1. Inventory (`ffprobe`), `tools/contact_sheet.py`, pick good windows, group into 15-30 s reels.
2. `tools/analyze_songs.py`, `tools/phrases.py`; verify the drop on the instrumental stem.
3. Copy `assets/project_example.py`; fill clips, songs, beat cut lists, brand text, fonts, hero video.
4. Voice reels: `tools/words.py`, `voice/` stem, `tools/make_bed.py`, `tools/gain_check.py`.
5. `reel_engine.py --preview` (+ `--notext` for checks), fix, 4K finals, verify.

## Output Contract

Output paths, durations, per-reel timeline (segment, start, transition), verification numbers, open risks (licensing, unheard audio, unconfirmed names).

## References

- `references/workflow.md` - pitfalls, exact fixes, specs, tool cheat sheet.
- `references/pipeline.md` - how the system was built: stages, numbers, review loop.
- `assets/reel_engine.py`, `project_example.py` - compositor and config template.
- `assets/look/` grade, reframe, LUT; `assets/voice/` isolation + scoring; `assets/tools/` analysis, verifiers; `assets/sfx.py` opt-in.
