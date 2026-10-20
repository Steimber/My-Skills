# Reel maker - pitfalls, fixes and specs

Architecture and the reasoning behind the numbers: `pipeline.md`. This file is the checklist: what bites, and the exact fix.

## Environment (Windows)

- Paths > ~200 chars break native apps and Python: work in a short dir such as `%TEMP%/<project>_build`; keep file names short (`clip_01.mp4`).
- `python -I` disables user site-packages: run plain `python` from the build dir. Read and write text with `encoding="utf-8"` (cp1252 breaks on accents);
  the engine reconfigures stdout, your own scripts should not print non-ASCII.
- Tools: ffmpeg (libx264, lut3d, curves, vibrance, cas, hqdn3d, ebur128, alimiter), `pip install --user numpy scipy librosa "opencv-python<5" pillow faster-whisper demucs soundfile`
  (+ torch CPU wheel; optional `noisereduce speechmos deepfilternet matplotlib`). OpenCV 5 dropped `CascadeClassifier` (face detection).
- faster-whisper + a new PyAV fails on `metadata_errors`: decode the audio yourself (`ffmpeg -ac 1 -ar 16000 -f f32le -`) and pass a float32 array.
- ffmpeg filter paths on Windows: `lut3d=file='C\:/dir/look.cube'` (forward slashes, escaped colon, single quotes) - `look/grade.py` does it.
- Fonts and the logo/hero video are never shipped: bring your own, licensed for your use. Songs: only files the user provides, and warn that platforms may mute them.

## Project layout and CLI

```
clips/    raw clips + photos       music/   songs you are licensed to use
assets/   fonts, hero video        build/    songs.json phrases.json voice/ beds/ look/ cache/ preview/ notext/
out/      4K finals                my_project.py   copy of assets/project_example.py
```

`python assets/reel_engine.py --config my_project.py [--preview] [--notext] [--table] [--list] [--audio-only] [--overwrite] [--grade lut|legacy] [--no-reframe] [reel names]`
with `--videos --music --assets --build-dir --out` (env `REEL_*`). Config keys: `CLIPS FOOD_CLIPS AMBIENCE_CLIP UPSCALED`, `PALETTE FONTS HERO LOGO LOGO_W GROUP_CY GROUP_BOTTOM`,
`END_TITLE END_LINES END_MIN_CAP`, `ACCENT_WORDS FUNC_WORDS SUB_PX`, `GRADE REFRAME TIGHT BEAT_LAG`, `LOOK FOOD_WARM V4_PARAMS V4_FOOD`, `VOICE_EQ VOICE_DYN BED_DB LIMITER FADE_OUT`, `REELS`.
Reel keys: `song gain_db shots` + `music_fx`, `sfx`, voice (`voice voice_gain_db voice_t0 first_word_offset av voice_lufs voice_ref`), bed (`bed bed_db carve_db`).
Shot keys: see `V()` / `P()` / `hero()` / `end_card()` and the `voice_track` entry in `project_example.py`.

| Step | Tool |
|------|------|
| Look at footage / renders | `tools/contact_sheet.py` |
| Beats, energy map, drops | `tools/analyze_songs.py` (`--bpm` to force a tempo), `tools/phrases.py` |
| Word timings for subtitles and cut points | `tools/words.py` |
| Isolated voice | `voice/` (`quick.py` or `extract -> sep -> build_cands -> evaluate -> finalize`) |
| Instrumental bed | `tools/make_bed.py` |
| Gains, mix balance | `tools/gain_check.py`, `tools/audio_buses.py` (voice vs music per band, limiter action) |
| Colour look | `look/before_after.py`, `look/make_lut.py`, `tools/grade_metrics.py` |
| Rhythm, text, repeats | `tools/rhythm_check.py`, `tools/textzone.py`, `tools/orb_repeats.py`, `reel_engine.py --table` |
| Final checks | `tools/verify_media.py`, `tools/verify_voice.py` |

## Source handling

- Rotation metadata can be wrong: compare an autorotated and a `-noautorotate` frame, put `["-noautorotate"]` in the clip's input opts.
- A/V start offsets: `ffprobe -show_entries stream=start_time`. Audio 40 ms late -> `av=0.04` on the voice track (voice follows the picture).
- Trim with filters (`trim`, `setpts=PTS-STARTPTS`), not input `-ss/-to`, when chaining xfade/concat (the simple builder does).
- PNG/JPG inputs into xfade negotiate 4:4:4: force `-pix_fmt yuv420p`. HEIC: `ffmpeg -i x.heic -frames:v 1 out.png` (no `-vf` on that command).
- 120 fps sources -> clean 0.5x slow motion (`setpts=2*PTS,fps=60`). A shot must sit inside a verified good window; do not rely on "it looked fine at 30 fps".
- Phone files can have a director's cue at the start of a take ("...ok go ahead"): start the piece after it (a 150 ms tail is enough to be heard) and drop false-start takes.

## Music and cuts

- Video versions of songs often start with spoken intros: find the drop (`analyze_songs.py` drops, then verify on the instrumental stem, then by ear) and the hook.
- Start the reel on the drop; segment lengths in whole beats (2/4/8); transitions end on the beat; a shot is `beats x beat time x speed` of source - re-check every window when you change song or tempo.
- The beat tracker may lock to 2/3 or 1/2 time (a synthetic 126 BPM track came out at 83 BPM): count beats vs `duration x BPM / 60`; fix with `analyze_songs.py --bpm <known tempo>` (librosa's `start_bpm` / `tightness` did not change it).
- Cuts go `BEAT_LAG` (20 ms) before the grid beat. Run `tools/rhythm_check.py`; change the value only if the median over several songs agrees.
- End card: `end_card(trans)` without a length stops on a phrase end (2.5-3.5 s). `after=`/`beats=` otherwise. Final song fade 0.4 s.

## Audio rules

- Silence before/between speech is real samples (`anullsrc` + `concat`), never `adelay` gaps; add `asetpts=N/SR/TB` after mixing. Check packet timestamp deltas < 0.03 s
  (`ffprobe -select_streams a -show_entries packet=pts_time`; AAC frames are 21 ms).
- Avoid single-pass dynamic `loudnorm` on music (pumps). Measure with `ebur128`, apply a fixed `volume=XdB` to reach -14 LUFS (`tools/gain_check.py`), then `alimiter=limit=0.79:level=false`.
- Voice chain order: `highpass 90 -> (dynamics, off by default) -> EQ -> gain -> mix -> master limiter`. Gain before a compressor is non-linear (it lowered loudness to -17 LUFS).
  Mono-fold the voice (L=R); check any stereo source for cancellation (`verify_media.py` prints mono-fold loss).
- Voice EQ that helped ASR: 300 Hz -2 dB, 2.8 kHz +2.5 dB. A +4 dB 5 kHz shelf and a compressor (thr -28 dB, ratio 4) lowered recall 94 -> 87 % on a separated voice: test every EQ against ASR.
- Separate the full original with Demucs, then cut ranges (excerpts separate worse). Speech cut points: faster-whisper `word_timestamps=True`, then snap to energy onsets (`tools/words.py`;
  raw starts can be off by ~0.5 s). Join soundbites with ~0.12 s gaps and 20 ms fades; re-transcribe the assembled audio to prove no word is cut.

## Speech over a sung song (intelligibility)

- Verify on the FINAL MIX, not the clean voice (`tools/verify_voice.py reel`): if the clean voice misses a word too it is pronunciation or separation (subtitles cover it), if only the mix misses it music masks it.
- Do not duck deep (-16 dB felt empty and still masked words). Crossfade the song into its own instrumental stem at -4.5...-12 dB (per song) with a 1-4 kHz carve (-4...-9 dB):
  `tools/make_bed.py`, `bed_db`, `carve_db`. Without a stem the engine falls back to duck -16 dB + carve -8 dB.
- Verify a song start on the instrumental stem: an RMS "drop" can be a spoken skit or a shout with near-silent music (-55 dB) under it.
- The bed stem must start at the reel's song start (the config's third song value); a stem from another start is out of phase.

## Voice isolation decisions

- `quick.py` (one htdemucs stem, mono, -3 dBFS) is enough for a clean speaker over a quiet or musical background.
- Noisy room or a speaker you care about: run candidates (h1/h2/m3, ensembles, DeepFilterNet3 full or `atten_lim_db` 12/24, soft gate) and score them (`evaluate.py`): recall small + medium, Whisper likelihood,
  residual, holes. Pick on the final mix; keep a fallback file. Recall moves +-2 words between runs: use the likelihood and the jitter runs before concluding anything.
- DeepFilterNet3: `pip install --user deepfilternet`; weights are NOT shipped - leave `DFN_MODEL_DIR` unset so `df` fetches them from the upstream project (github.com/Rikorose/DeepFilterNet) on first use, or unzip upstream's `models/DeepFilterNet3.zip` and point `DFN_MODEL_DIR` at the folder with `config.ini` + `checkpoints/` (offline). `voice/libdf.py` (credited MIT OR Apache-2.0 port) replaces the Rust extension on Pythons without a wheel; `python voice/selftest_df.py [--e2e]` checks it.

## Effects spec (engine)

- Every shot: push-in 1.00 -> 1.06, zoom punch 1.12 -> 1.0 over 15 frames on cuts, beat pulse +1.5 %.
- Transitions: whip (8 frames, blur proportional to speed, alternate direction), flash (white 0.85 -> 0 over 6 frames + flare), zoom-through (10 frames, 1 -> 1.5), shake (+-2 % decaying). Never plain crossfades.
- Titles: display font, ~85 % width, letter rise-in 35 ms stagger, `{accent}` words, kicker line, fully visible >= 1.0 s (needs >= 6 beats at ~125 BPM); block inside 15-72 % of the height.
- Subtitles: <= 4 words, <= 78 % width, 210 px at 4K, pop-in 1.15 -> 1.0, never end a chunk on a function word, >= 0.5 s; `FUNC_WORDS` and `ACCENT_WORDS` are per language/project.
- Intro/end: logo (hero video on black) + tagline, embers, sparks; the flare starts on frame 1 so the thumbnail frame is clean; hero text ends above 70 % of the height.
- Do not put text over faces: `tools/textzone.py --faces`.

## Colour

- Grade in the ffmpeg decode chain (one pass), never stack a second numpy grade on top; keep only the vignette in Python.
- `GRADE = "lut"` (default): LUT look + per-shot match to a per-reel target, skin guard, food variant. `look/before_after.py --mode lut` first; tune `V4_PARAMS` (`sat` up if it looks flat); keep the skin guard in the food LUT.
- `GRADE = "legacy"`: gains per SHOT on 3 frames (10/50/90 % of its range), never per clip (a dark wide shot's +28 % gain blew out the bright close-up of the same clip: 0 % -> 4 % clipped);
  50 % gray-world WB x 50 % exposure pull, clip 0.75-1.45, highlight guard 99.5th percentile <= 0.92; look = curves S + colorbalance + `vibrance` (not plain saturation) + `cas`.
- Dark stills with `GRADE = "legacy"`: `lift=True` (`eq=gamma=1.18`); the LUT grade matches exposure itself. Sources upscaled > 2.5x at 4K: list in `UPSCALED` (luma unsharp).
- Clipping audit: scan previews at 4 fps for % pixels >= 250; flashes, the white logo and light titles are expected hits - compare suspicious shots against the source frame.

## Reframing and talking heads

- `REFRAME = True`: moving subject-aware crop for landscape clips (static scenes stay static); `tight=True` on a talking-head shot = 1.22x with the eyes on the 37 % line.
- Alternate wide / tight per piece, no face-only stretch over ~4 s; cover jump cuts with B-roll inserts that illustrate the words (the voice continues).
- Landscape clips with a fixed crop (speaker off-centre): `CENTER + ":x:0"` in the clip table; `tight` then crops 1/1.22 about the top centre.

## Multi-bite testimonials and unique reels

- Long testimonial -> several reels: pick soundbites from word timestamps of the isolated voice, join with ~0.12 s gaps and 20 ms fades, B-roll inserts over jump cuts.
- Cold open: the payoff line plays under the logo intro and the tagline letters land with its words; do not repeat that line in the body. Arc: hook -> context -> reasons -> CTA.
- "No repeats" means VISUAL repeats: the same person, sign or table from another range of the same clip still reads as repeated. `reel_engine.py --table` for ranges, `tools/orb_repeats.py` for looks.
- Confirm brand and place names heard in speech with the user before burning subtitles.

## Sound design (`assets/sfx.py`) - off by default

- A client rejected generic synthesized SFX (whooshes/booms) on music-driven reels: off-music and off-context. Enable per reel with `sfx=True` only on explicit request, and derive sounds from the scene
  (real ambience from `AMBIENCE_CLIP`, checked for speech with Whisper, highpass 300 Hz, played at real speed even under slow motion).
- Levels that read on phones: SFX RMS 1-7 dB under the music at each hit (first attempt at -10...-15 dB was inaudible); dip SFX 10 dB under speech; mix before the master limiter; re-check -14 LUFS and packet gaps.

## Review loop

- Preview at 540x960 CRF 23 veryfast; contact sheet `fps=4,scale=135:-2,tile=16x8`. Look for faces covered, text outside 15-72 %, blurry frames, black/frozen runs, empty frame halves.
- Ultra review: 4 parallel read-only reviewers (visual/framing, rhythm/story, audio, social/marketing) -> ranked findings with numbers and engine fixes -> the coordinator resolves conflicts against the client's rules ->
  ONE fix list for one writer -> re-verify. Bed level is set per song: stems differ by 3-6 dB in effective duck depth.
- Before shipping: `verify_media.py` on every final (A/V diff, decode, gaps, LUFS, TP, mono fold), `verify_voice.py` on voice reels, `textzone.py --faces`, `orb_repeats.py`, a human pass over the contact sheets.
