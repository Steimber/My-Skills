---
name: reel-maker
description: "Trigger: reels, TikTok, Shorts, edit clips into video, best moments, beat sync, vertical 4K, brand intro. Build energetic beat-synced branded vertical reels from raw clips."
license: Apache-2.0
metadata:
  author: "Steimber"
  version: "1.1"
---

## Activation Contract

Load when the user wants raw phone clips/photos edited into short vertical videos (Reels/TikTok/Shorts), highlight cuts, music sync, titles/subtitles, or brand-styled intros.

## Hard Rules

- Never lower quality: decode from originals every render, H.264 CRF ≤16, keep 4K when sources allow; one encode per output.
- Never overwrite user originals; write new outputs to a separate `--out` dir.
- Inspect every clip visually (contact sheets) before choosing moments; check rotation metadata per clip.
- Verify every output: A/V durations match, no audio packet gap > 0.03 s, `ffmpeg -v error -f null` clean, ≈ -14 LUFS, contact-sheet review.
- Keep all text inside the safe zone (15–72 % of height); never cover faces.
- Never download copyrighted music; only use files the user provides, and warn platforms may mute them.
- Confirm brand/place names heard in speech with the user before burning subtitles.
- No synthesized SFX by default on music-driven reels (generic whooshes/booms read as off-music); `sfx` is opt-in on explicit request.

## Decision Gates

| Situation | Action |
|-----------|--------|
| Landscape clip in 9:16 | Center crop `ih*9/16`; shift x to keep the subject |
| Wide sign/logo won't fit 9:16 | Two crops on consecutive beats |
| Speech in a clip | Keep only that audio; Demucs-isolate voice; duck music 12 dB |
| No music given | Ship silent cuts; suggest in-app platform audio |
| Energy/brand requested | `assets/reel_engine.py --config <project>.py` |
| Simple cut list only | `assets/build_music_reels_ffmpeg.py` (xfade) |
| Color look | Per-shot match + look chain in decode; before/after first |

## Execution Steps

1. Inventory sources (ffprobe: size, fps, rotation, duration); 2 fps contact sheets; note good windows.
2. Group clips into 2–3 themed reels (place / food / atmosphere) of 15–30 s.
3. Music: `assets/analyze_songs.py key=path ... --out build/songs.json`; find the drop beat; transcribe for the hook.
4. Copy `assets/project_example.py`, fill clips, songs, cut lists (in beats), brand text, fonts, hero video.
5. Render `--preview` (540×960), review contact sheets, fix, then render 4K finals and verify.

## Output Contract

Return output paths, durations, per-reel timeline (segment, start, transition), verification numbers, unresolved risks (copyright, unheard audio).

## References

- `references/workflow.md` — pitfalls, ffmpeg/Python fixes, effect specs.
- `assets/reel_engine.py` — compositor; project data via `--config`, dirs via `--videos --music --assets --build-dir --out`.
- `assets/project_example.py` — config template (clips, reels, palette, fonts, brand text).
- `assets/analyze_songs.py` — beat grid + energy map.
- `assets/grade_before_after.py` — before/after color sheet (`file@time[:crop]`).
- `assets/sfx.py` — opt-in synthesized SFX + real ambience bed.
- `assets/build_music_reels_ffmpeg.py` — simple xfade/ducking builder.
