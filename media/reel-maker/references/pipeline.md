# How the reel system was built

End-to-end architecture of the system this skill was extracted from: five short vertical reels for a restaurant client, cut from raw phone
footage, with branded intros/end cards, beat-synced editing to songs the client provided (clear music rights before publishing), and two customer testimonials (an older
and a younger speaker, recorded in a noisy room) turned into soundbite reels. Everything below is generic; the numbers are the ones that
survived testing. Pitfalls and exact fixes are in `workflow.md`; the code is in `../assets/`.

```
 raw clips/photos ─► inventory + contact sheets ─┐
 songs ───────────► beat grid · drops · phrases ─┼─► cut lists (in beats) ─► compositor ─► picture (raw frames, one x264 encode)
                                                 │        ▲        ▲            │
 clips ─► color (LUT + shot matching)  ──────────┘        │        └─ reframing (crops, tight boxes)
 testimonial audio ─► voice isolation (candidates → metrics → pick) ─► voice stem ─┐
 song section ─► instrumental stem (bed) ──────────────────────────────────────────┴─► mix (bed, duck, voice chain, limiter) ─► AAC
 picture + audio ─► mux ─► verify (A/V, gaps, loudness, ASR recall, safe zone, repeats) ─► review loop ─► 4K finals
```

## 1. Ingest and contact sheets

- `ffprobe` every file: size, fps, rotation tag, duration, **audio `start_time` vs video** (one phone file had its audio 40.6 ms late: the voice
  must be shifted by that for lip sync; the engine takes it as `av=`).
- Rotation metadata lies sometimes: render one frame with and without `-noautorotate`, compare, and record the winner as the clip's input opts.
- HEIC stills go through ffmpeg to PNG first. Photos are cropped by hand in source pixels (a wide room photo is split into two 9:16 crops used on
  consecutive beats, so a sign never has to fit).
- `tools/contact_sheet.py` at 2 fps for sources, 4 fps for renders. Every clip is looked at before any window is chosen; "good windows" (start, end) go
  into the clip table, and the engine refuses a shot outside them. Reject blurry floor frames and black or frozen runs.
- Group clips into themed reels (place / food / atmosphere / testimonial) of 15-30 s. Each source range is used once across all reels.

## 2. Music analysis

- `tools/analyze_songs.py`: librosa beat tracker (22.05 kHz mono) -> beat list, tempo, energy per 8-beat block (the printed map), drop candidates
  (2 beats after vs 2 beats before: broadband RMS ratio x 20-150 Hz energy ratio). Tracker tempo can lock to 2/3 or 1/2 time: check the beat count
  against `duration x BPM / 60` and force the tempo with `--bpm`.
- A reel starts on the drop or on a hook. Video versions of songs often open with spoken skits or shouts: an RMS "drop" with near-silent music under it
  (-55 dB instrumental) looks perfect on the mix. **Verify the start on the instrumental stem**, then by ear.
- `tools/phrases.py`: beat-synchronous chroma novelty -> the 8-beat (phrase) and 4-beat (bar) grid phase with the most chord change. End cards stop on a
  phrase end (bar end as fallback, +0.35 score penalty) so the card is 2.5-3.5 s (1.8-4.6 s accepted) and the song fades 0.4 s.
- **Grid lag.** The tracker's beats sit ~15-35 ms after the audible hit (`tools/rhythm_check.py` measures median onset - beat per song). Cuts are placed
  `BEAT_LAG` = 20 ms before the grid beat; a cut 0-30 ms before the hit feels tight, after it feels late.

## 3. Cut lists in beats

- A shot is `(clip, source start, beats, speed)`; its length is `beats x beat time x speed` of source. 2/4/8-beat shots, transitions end on the beat.
  Slow motion (0.5x) is only clean from 120 fps sources (`setpts=2*PTS,fps=60`).
- Variants: `src_end` derives the speed so a shot consumes exactly a source range; `until_abs` cuts on the beat nearest an absolute song time (a drop);
  `dur`/`frames` for non-musical lengths. The planner asserts that every range fits its good window and the file duration.
- Hook: logo intro <= ~2 s (4 beats, tagline on beat 1) with a flare that starts on frame 1 (never a white blend on frame 0: it becomes the thumbnail).
  Testimonial reels use a **cold open**: the customer's payoff line plays under the logo and the tagline letters land with those words.
- Arc for testimonials: hook -> context -> reasons -> call to action. The hook line is not repeated in the body.
- End card = call to action built from verified business facts (ordering channel, number, area), no URL; all lines <= 70 % of the height.
- Uniqueness: `reel_engine.py --table` prints every source range and flags overlaps across reels; `tools/orb_repeats.py` catches the visual repeats the
  table cannot (same hand on the same grill from another range scored 144 inliers; unrelated shots stay below ~30).

## 4. Compositor (`reel_engine.py`)

- Frames are composed in numpy/OpenCV at 60 fps and piped raw (rgb24) into **one** libx264 encode (CRF 16 / medium at 4K, CRF 23 / veryfast preview,
  High@5.2, bt709 limited range). Each source is its own ffmpeg process decoding `setpts=(PTS-STARTPTS)/speed,fps=60, crop, scale, colour` straight
  from the original file, so nothing is ever re-encoded between steps.
- Per shot: push-in 1.00 -> 1.06, zoom punch 1.12 -> 1.0 over 15 frames on every cut, beat pulse +1.5 % decaying with tau 90 ms, vignette (the only
  numpy colour step).
- Transitions (how a shot *arrives*): `hard`; `flash` (white 0.85 -> 0 over 6 frames + brightness 1.55 / saturation 1.35 flare easing out over 18 frames);
  `whip` (8-frame strip pan, horizontal blur proportional to speed, alternating direction); `zoom` (10-frame radial zoom-through 1 -> 1.5); `shake`
  (+-2 % decaying over 6 frames). Never a plain crossfade.
- Titles: display font, per-letter rise-in (35 ms stagger, 20 ms for long titles), `{accent}` words, sparks on landing, kicker line above; cap-top at 18-20.5 %
  of the height, block inside **15-72 %** (platform UI covers the rest), >= 1.0 s fully visible before the exit (the engine asserts it).
- Subtitles: 210 px at 4K, kicker font, thick outline + soft shadow, pop-in 1.15 -> 1.0 over 120 ms, chunks <= 4 words and <= 78 % of the width, a chunk never
  ends on a dangling function word, >= 0.5 s on screen, y = 61 % (68.5 % over B-roll). Word starts come from Whisper snapped to voice-energy onsets.
- Hero layout: the logo and its text lines are one group centred at 37.5 %; if it would end below 70 % the logo shrinks. Embers are stateless particles with a
  glow pass. Fonts and the logo video are the client's; the engine only needs the logo's content bbox.
- Voice tracks: ordered source pieces laid back to back with 0.12 s of real silence; picture = talking-head shots lip-synced to the piece that is heard,
  overridden by B-roll inserts anchored to source times (the voice never stops: J/L cuts); inserts snap to beats within 0.2 s and never leave a < 0.4 s sliver;
  wide <-> tight framing switches hide jump cuts; no face-only stretch beyond ~4 s.
- SFX: synthesized whooshes/booms (`sfx.py`) were rejected by the client on music-driven reels. Off by default; if used, derive sounds from the scene.

## 5. Colour (`look/grade.py`)

- Goal: a punchy warm look that stays consistent across phone clips shot under different lamps, without orange faces and blown lights.
- Per reel a **target** is built from all its shots (6 sample frames each at 540x960): median L* of the best-exposed half, pulled 50 % toward the brief (L50 30,
  faces L* 52), plus the confidence-weighted white-balance cast of near-neutral pixels (only 60 % trusted: keep the warm room).
- Per shot a correction goes into one ffmpeg chain: `hqdn3d` (only when noise x lift is high; temporal strength capped for talking heads) -> `curves` (per-channel
  WB gains, black point <= 0.10, pchip percentile tone match with slopes kept in 0.5-2.2, highlight guard: never clip more than the source +0.3 %) -> `lut3d`
  (tetrahedral) -> `cas` 0.35. The LUT (33^3, generated by `look/make_lut.py`) is a Lab-space look: soft toe and long shoulder, teal shadows / amber highlights,
  vibrance, a skin-hue attractor and chroma limiter inside the natural skin band, a magenta tamer, a food variant that is warmer (skin guard stays on: hands on
  tongs glowed).
- Measured against the older gain-based grade: consecutive-shot dE00 7.8 -> 5.4, skin pixels in the natural hue band 33 % -> 92 %. It came out flatter, so
  `sat` was raised (~1.8 in that implementation) until non-skin chroma matched the punchy grade within +-5 %. Judge with a before/after sheet (`look/before_after.py`)
  first, numbers (`tools/grade_metrics.py`) second.
- Legacy path (`GRADE = "legacy"`): per-shot gains (50 % gray-world WB x 50 % exposure pull to luma 0.36, clipped 0.75-1.45, highlight guard 0.92) + a fixed ffmpeg chain.
  Measure gains per **shot** (10/50/90 % of its own range), never per clip.

## 6. Reframing (`look/reframe.py`)

- Landscape -> 9:16: per analysis frame (5 fps) face boxes (Haar + skin validation), HOG people, spectral-residual saliency and skin columns give a column-interest
  profile; a Viterbi pass over window positions maximises interest minus a travel cost with a speed limit; a critically damped, zero-lag smoother (omega 7, 0.55 window/s
  max) turns it into a piecewise-linear `crop x(t)` for ffmpeg. Static scenes get a plain crop; heads are never cut by the window edge. Modest gain on pans and tables.
- Vertical talking heads: `tight_box` frames 1/1.22 of the source with the eyes on the 37 % line and >= 6 % headroom.

## 7. Voice isolation (`voice/`)

- Separate the whole original (not the excerpt) with several models, then score candidates on the ranges that will actually be used:
  `htdemucs` (h1), `htdemucs_ft` (h2), `mdx_extra` (m3), ensembles (mean of stems), + DeepFilterNet3 (full or limited with `atten_lim_db`), + noisereduce, + a soft VAD gate
  (25 dB depth, 0.10 s pre / 0.20 s post guard, 25 ms ramps).
- Metrics (`voice/metrics.py`, `evaluate.py`): word recall of faster-whisper small + medium vs the reference text (beam 5, no conditioning), Whisper's likelihood of the
  reference (steadier than recall, which is +-2 words), recall under a few tens of ms of edge jitter, speech-to-residual in pauses and next to speech, musical-noise fluctuation,
  consonant holes at 3-7 kHz, share of speech cells carved >10 dB, DNSMOS. All level-matched to -26 dB speech RMS first.
- Findings: for a clean speaker htdemucs + DeepFilterNet3 won (pause residual 13.7 -> 38.5 dB, DNSMOS overall 2.48 -> 3.23). For a noisier speaker full-strength
  DeepFilterNet cost recall: the ensemble + DeepFilterNet limited to 12 dB + soft gate was the compromise. The cleanest-sounding file lost recall once mixed with music
  (81 % -> 68 %), so the pick is made on the final mix, with a fallback file.
- Deliverable: 48 kHz L=R float, full length, sample-aligned with the source, peak -3 dBFS, no fades (`finalize.py` re-reads and verifies lag, length, peak).
- The numpy port of DeepFilterNet's `libdf` exists because the Rust wheel was unavailable on the Python in use; it is a credited derivative (MIT OR Apache-2.0), weights not included.

## 8. Mix

- Music: section starts at the song start, fixed `gain_db` (measured with ebur128; dynamic `loudnorm` made the music pump), optional `music_fx` (bass trim, glue compressor).
- Voice: pieces cut by source time, 20 ms fades (60 ms on the last), real silence between, `highpass 90`, mono fold, 300 Hz -2 dB, 2.8 kHz +2.5 dB, then gain to
  ~-16 LUFS (-13.6 over loud songs) **after** any dynamics. A compressor and a +4 dB 5 kHz shelf lifted separation noise as much as consonants and lowered ASR recall 94 -> 87 %.
- Speech over a sung song: do not duck deep (-16 dB felt "empty" and still masked words). Crossfade the full song into **its own instrumental stem** (same section, phase aligned,
  `tools/make_bed.py`) at -4.5...-12 dB (per song; stems differ by 3-6 dB) with a 1-4 kHz carve of -4...-9 dB. Ramp in 0.3 s starting 0.45 s before the first word, out over 0.35 s
  starting 0.2 s before the last word ends. With a cold-open hook the bed is already in at t = -0.4 s.
- Master: `alimiter` limit 0.79 (about -2 dBFS sample peak, true peak below -1 dBTP), final song fade 0.4 s, AAC 256k. Target -14 LUFS integrated; audio packet gaps < 0.03 s
  (silence is samples, never `adelay` gaps).

## 9. Verification (what "done" means)

`tools/audio_buses.py` (voice vs music per band, weakest 1-4 kHz windows, limiter action), `tools/verify_media.py` (A/V duration diff <= 0.05 s, clean decode, packet gap <= 0.03 s, loudness, true peak, mono-fold loss), `tools/verify_voice.py` (word recall of the final mix and of the
clean voice bus: if only the mix misses a word, music masks it), `tools/textzone.py` (pixel rows of every caption inside 15-72 %, hero text above 70 %, no face under text),
`tools/orb_repeats.py`, `tools/rhythm_check.py`, `tools/grade_metrics.py`, plus contact sheets read by a human. Clipping audit: share of pixels >= 250 at 4 fps; flashes, white logos and
cream titles are expected hits.

## 10. Review loop

Render previews (540x960), then four read-only reviewers in parallel, each returning ranked findings with numbers and concrete engine fixes: (1) visual/framing, (2) rhythm/story,
(3) audio, (4) social/marketing. The coordinator resolves conflicts against the client's rules and sends ONE fix list to a single writer; no parallel writers. Re-run the verifiers,
re-render only the changed reels. Typical findings: a cut after the hit, a title leaving too early, a repeated shot across reels, a bed level too low for one song, a CTA below 70 %.

## 11. 4K finals

`reel_engine.py` without `--preview` (2160x3840, CRF 16, `--out` dir; existing finals are never overwritten without `--overwrite`), then `verify_media.py` and a last contact sheet. Keep
originals untouched, write finals elsewhere, and tell the user which numbers were verified and which risks remain (music licensing, unheard audio, names confirmed).

## Key numbers

| Area | Value |
|------|-------|
| Preview / final | 540x960 CRF 23 veryfast / 2160x3840 CRF 16 medium, 60 fps, bt709 |
| Cut offset | `BEAT_LAG` 20 ms before the grid beat |
| Hook / end card | intro <= ~2 s; end card 2.5-3.5 s on a phrase end; fade 0.4 s |
| Text | zone 15-72 % H; hero group <= 70 % H; title visible >= 1.0 s; subtitle >= 0.5 s, <= 4 words, <= 78 % W |
| Audio | -14 LUFS, TP <= -1 dBTP, limiter 0.79, packet gaps < 0.03 s, voice -16 / -13.6 LUFS pre-mix |
| Bed | -4.5...-12 dB, carve -4...-9 dB at 2.2 kHz (Q 0.8), ramps 0.3 s in / 0.35 s out |
| Colour | target L50 30, skin L* 52, black point <= 0.10, highlight clip <= source +0.3 %, dE00 7.8 -> 5.4 |
| Repeats | ORB inliers: repeat ~144, unrelated < 30 |
