# Reel maker — pitfalls and specs

## Environment (Windows)

- Paths > ~200 chars break native apps/Python: work in a short dir such as `%TEMP%/<project>_build`.
- `python -I` disables user site-packages; run plain `python` from the build dir.
- Read/write text with `encoding="utf-8"` (cp1252 default breaks on accents).
- Tools: ffmpeg (libass, libx264), `pip install --user librosa faster-whisper "opencv-python<5" pillow scipy demucs` (+ torch CPU wheel). OpenCV 5 dropped `CascadeClassifier`.
- faster-whisper + new PyAV fails on `metadata_errors`: decode audio yourself and pass a float32 numpy array.

## Project layout

```
clips/    raw clips + photos      music/   songs you are licensed to use
assets/   fonts, hero video       build/    songs.json, voice stems, previews
out/      finals                  my_project.py   copy of assets/project_example.py
```

- `python assets/analyze_songs.py song_a=music/song_a.mp3 --out build/songs.json`
- `python assets/reel_engine.py --config my_project.py --preview reel1_place`
- Flags/env vars: `--videos`/`REEL_VIDEOS`, `--music`/`REEL_MUSIC`, `--assets`/`REEL_ASSETS`, `--build-dir`/`REEL_BUILD_DIR`, `--out`/`REEL_OUT`, `--config`/`REEL_CONFIG`.
- Config sets: `CLIPS` (file, input opts, crop, good windows), `FOOD_CLIPS`, `AMBIENCE_CLIP`, `PALETTE`, `FONTS`, `HERO`/`LOGO`, `END_TITLE`, `DOMAIN`, `REELS` (songs, gains, shots).
- Fonts and the hero video are not shipped: supply your own, licensed for your use.

## Source handling

- Rotation metadata can be wrong: compare autorotated vs `-noautorotate` frame before deciding.
- Trim with filters (`trim`, `setpts=PTS-STARTPTS`), not input `-ss/-to`, when chaining xfade/concat.
- PNG/JPG inputs into xfade negotiate 4:4:4 → force `-pix_fmt yuv420p`.
- HEIC: `ffmpeg -i x.heic -frames:v 1 out.png` (no `-vf` on the same command).
- 120 fps sources → clean 0.5x slow motion (`setpts=2*PTS,fps=60`).

## Audio

- Silence before speech must be real samples (`anullsrc` + `concat`), never `adelay` gaps; add `asetpts=N/SR/TB` after mixing.
- Check: `ffprobe -select_streams a -show_entries packet=pts_time` deltas < 0.03 s.
- Avoid single-pass dynamic `loudnorm` on music (pumps). Measure with `ebur128`, apply fixed `volume=XdB` to reach -14 LUFS, then `alimiter=limit=0.84:level=false`.
- Voice: Demucs `--two-stems=vocals -n htdemucs` on the exact kept range; +8 dB, highpass 90 Hz; music ducks 12 dB from voice start.
- Speech cut points: faster-whisper `word_timestamps=True`; drop false-start takes ("ok", "ready", "start").

## Music selection

- Video versions of songs often have spoken intros: find the drop (max RMS ratio post/pre over 2 beats) and the hook (transcribe vocals).
- Start the reel on the drop; segment lengths in whole beats (2/4/8); transition ends on the beat.

## Effects spec (reel_engine)

- Every shot: push-in 1.00→1.06; zoom punch 1.12→1.0 in 0.25 s on cuts; beat pulse +1.5 %.
- Transitions: whip pan (8 frames, horizontal motion blur ∝ speed, alternate direction), flash (white 0.85→0 over 6 frames + brightness flare), zoom-through (1→1.5 radial blur), shake (±2 % decaying). Never plain crossfades.
- Grade: warm, contrast 1.06, saturation 1.15, vignette.
- Titles: brand display font (e.g. a condensed bold face), ~85 % width, letter rise-in staggered 35 ms, `{accent}` words in the accent color, kicker in a condensed bold font.
- Subtitles: chunks of 2–3 words, ≈240 px at 4K, pop-in 1.15→1.0, key words accented.
- Intro/end: brand logo asset (hero video on black) centered with tagline, ember particles, sparks on title landing.

## Review loop

- Preview at 540×960 CRF 23 veryfast; contact sheet `fps=4,scale=135:-2,tile=16x8`.
- Look for: faces covered, text outside 15–72 % height, blurry floor frames, black/frozen runs, empty frame halves.

## Color grade (warm fire look)

- Grade in the ffmpeg decode chain (one pass), never stack a second numpy grade on top; keep only the vignette in Python.
- Measure gains PER SHOT on 3 frames (10/50/90 % of its source range; pans change exposure), never once per clip: a dark wide shot's +28 % gain blew out the bright close-up of the same clip (0 % → 4 % clipped). Add a highlight guard: scale gains so the 99.5th percentile stays ≤ 0.92.
- Per-clip match first: measure one mid-window frame, gains = 50 % gray-world WB × 50 % pull to mid exposure (0.36 luma), clipped 0.75–1.45 → `colorchannelmixer=rr:gg:bb`.
- Look: `curves` gentle S (deep blacks) with highlight roll-off (`0.95/0.94 1/0.98`) → `colorbalance` teal shadows / warm highlights → `vibrance=0.28` (not plain saturation: protects skin) → `eq=contrast=1.04:saturation=1.05` → `cas=0.45`. Override with `LOOK` in the config.
- Food clips: add warmth (`colorbalance=rm=0.05:bm=-0.05:rh=0.04:bh=-0.04`, `vibrance=0.10`) — warm food reads appetizing. List them in `FOOD_CLIPS`.
- Show the client a before/after sheet first: `assets/grade_before_after.py --videos clips file@time[:crop] ...`.

## Sound design (`assets/sfx.py`)

- Default OFF (`sfx=True` in a reel config to enable). A client rejected generic synthesized SFX on music-driven reels: they clashed with the song and the scene. If ever used, derive sounds from the song/scene itself, never generic stock hits.

- Synthesize SFX with numpy/scipy (license-free): whoosh (swept band-noise, panned by whip direction, peak lands on the cut), boom (pitch-drop sine + click), crack, punch, riser (into zoom cuts), fire ignite (intro/end), sparkle (title landing).
- Real ambience beats synthetic: pull the room/cooking sound from a clip (`AMBIENCE_CLIP`; check with whisper that it has no speech; highpass 300 Hz), play it at real speed even under slow-mo picture.
- Levels that read on phones: SFX RMS 1–7 dB under the music at each hit (measure fx vs mix in a ±0.3 s window). First pass at -10…-15 dB under was inaudible.
- Dip SFX 10 dB under speech; mix before the master `alimiter`; re-check -14 LUFS and audio packet gaps.

- Clipping audit: scan previews at 4 fps for % pixels ≥250; flashes, the white logo and light-colored titles are expected hits — compare suspicious shots against the source frame.
