"""Example project config for reel_engine.py. Copy it, rename the placeholders, point it at your own media.

    python assets/reel_engine.py --config my_project.py --preview        # fast 540x960 check
    python assets/reel_engine.py --config my_project.py                  # 4K finals

Everything project-specific lives here: clip table, brand palette/fonts/hero video, end-card text, subtitle words,
audio knobs and the reel cut lists. File names are resolved against --videos (clips, photos), --music (songs), --assets
(fonts, hero video) and --build-dir (songs.json, phrases.json, voice stems in voice/, instrumental beds in beds/).

The four reels below cover every engine feature:
  reel1_place       hero intro, split crops of one photo, mixed transitions, kicker + title, beat-exact cuts, auto end card
  reel2_food        one testimonial clip with its isolated voice stem, bed under speech, word-timed subtitles
  reel3_atmosphere  photos + clips, fast cuts, no voice
  reel4_voice       a voice track: several pieces of one talking-head clip, B-roll inserts, a cold-open hook that plays
                    under the logo intro, framing switches (wide <-> tight), the instrumental bed under speech
"""

# ----------------------------------------------------------------------------- brand
PALETTE = dict(
    text=(251, 245, 231),    # title / subtitle color
    accent=(255, 176, 102),  # {accent} keywords and kickers
    fire=(244, 108, 39),     # embers
    bg=(12, 14, 18),         # hero / end-card background
)
FONTS = dict(display="display.ttf", kicker="kicker.ttf", body="body.ttf")  # in --assets; bring your own fonts
# display = titles/taglines (heavy condensed), kicker = kickers + subtitles + emphasised CTA line (bold condensed), body = CTA lines
HERO = "hero.mp4"                # logo animation on black, 2560x1440, in --assets
LOGO = (800, 1640, 130, 1190)    # stable logo content bbox (x0, x1, y0, y1) inside the hero video
LOGO_W, GROUP_CY, GROUP_BOTTOM = 0.72, 0.375, 0.70  # logo width / frame width; group centre; text must end above 70 % (platform UI)

# End card = logo + title + call-to-action lines. {braces} mark accent words. Lines: text, cap height (fraction of the frame height,
# >= 0.029 for legibility), strong=True uses the kicker font, gap = space above the line, spacing = letter spacing in em.
END_TITLE = "SEE YOU AT {YOUR BRAND.}"
END_LINES = [
    dict(text="ORDER ON WHATSAPP", cap=0.032, gap=0.02),
    dict(text="{000 000 0000}", cap=0.042, strong=True, gap=0.008),
    dict(text="YOUR AREA · YOUR CITY", cap=0.030, spacing=0.0, gap=0.016),
]
# DOMAIN = "yourbrand.com"   # v1.1 shorthand: one small line under the title, used only when END_LINES is empty

# ----------------------------------------------------------------------------- look, framing, subtitles
GRADE = "lut"        # "lut": per-shot LUT grade with skin guard (look/grade.py) | "legacy": gains + the ffmpeg LOOK chain below
REFRAME = True       # subject-aware 9:16 crops and face-based tight boxes (look/reframe.py) | False: plain center crops
BEAT_LAG = 0.020     # cuts land this much BEFORE the grid beat; measure yours with tools/rhythm_check.py
TIGHT = 1.22         # zoom of a "tight" talking-head shot (the source must tolerate it: 4K phone video does)
SUB_PX = 210         # subtitle size at 4K; chunks are <= 4 words and <= 78 % of the frame width
ACCENT_WORDS = {"great", "friendly", "amazing", "recommend", "family"}  # subtitle words (lower case) shown in the accent color
# FUNC_WORDS = {...}  # words a subtitle chunk may not end on (default: short English function words; set yours for other languages)
UPSCALED = set()     # clips upscaled > 2.5x at 4K (Full-HD sources): extra luma sharpening

# Optional overrides of the legacy color look (ffmpeg filter chains), used when GRADE = "legacy":
# LOOK = "curves=...,vibrance=intensity=0.28,eq=contrast=1.04:saturation=1.05,cas=strength=0.45"
# FOOD_WARM = "colorbalance=rm=0.05:bm=-0.05,vibrance=intensity=0.10"
# Optional overrides of the LUT look (see look/grade.py PARAMS): V4_PARAMS = dict(sat=1.8, ...), V4_FOOD = dict(...)

# Optional audio-chain overrides (defaults are what survived ASR testing; see references/workflow.md):
# VOICE_EQ = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,equalizer=f=300:t=q:w=1:g=-2,equalizer=f=2800:t=q:w=1:g=2.5"
# VOICE_DYN = "anull"          # an acompressor here lowered ASR recall of separated voices
# BED_DB = -7.0                # instrumental bed level under speech (per reel: bed_db)
# LIMITER = "alimiter=limit=0.79:level=false"

# ----------------------------------------------------------------------------- clips
# name -> (file, ffmpeg input opts, ffmpeg crop filter or None, allowed source windows (start, end) in s).
# A shot must fit inside one window; windows are the ranges you verified on the contact sheets.
# Shot length = beats x beat time x speed, so re-check windows for your song's tempo (placeholders here fit ~125-135 BPM).
CENTER = "crop=ih*9/16:ih"  # 9:16 center crop of landscape footage; with REFRAME it becomes a subject-aware moving crop
CLIPS = {
    "clip_01": ("clip_01.mp4", ["-noautorotate"], CENTER, [(1.0, 7.85)]),  # wrong rotation metadata
    "clip_02": ("clip_02.mp4", [], CENTER, [(0, 6.0)]),
    "clip_03": ("clip_03.mp4", [], CENTER, [(0, 10.5)]),
    "clip_04": ("clip_04.mp4", [], CENTER, [(2.0, 7.7)]),
    "clip_05": ("clip_05.mp4", [], CENTER, [(0.3, 7.6)]),
    "clip_06": ("clip_06.mp4", [], None, [(0, 0.98), (2.0, 6.2)]),         # already vertical: no crop
    "clip_07": ("clip_07.mp4", [], CENTER, [(0, 3.5), (3.5, 8.0), (8.0, 12.5)]),  # food footage
    "clip_08": ("clip_08.mp4", [], CENTER, [(0, 4.8)]),
    "clip_09": ("clip_09.mp4", [], CENTER + ":1159:0", [(1.95, 10.25)]),  # testimonial: fixed crop shifted to the speaker
    "clip_10": ("clip_10.mp4", [], None, [(0, 20.0)]),                     # vertical talking head (voice track source)
    "clip_11": ("clip_11.mp4", [], CENTER, [(0, 8.0)]),                    # B-roll that illustrates the words (voice-track insert)
}
FOOD_CLIPS = {"clip_07"}     # food clips get the extra appetizing warmth (food LUT / FOOD_WARM)
AMBIENCE_CLIP = "clip_07"    # real sound of this clip is the ambience bed when a reel sets sfx=True (opt-in)

# ----------------------------------------------------------------------------- songs
# (key in songs.json, file in --music, start second of the section: the drop / hook)
SONG_A = ("song_a", "song_a.mp3", 49.6)
SONG_B = ("song_b", "song_b.mp3", 14.35)
SONG_C = ("song_c", "song_c.mp3", 42.2)
SONG_D = ("song_d", "song_d.mp3", 15.5)

# ----------------------------------------------------------------------------- voice track (reel4_voice)
# Word starts in SOURCE seconds of the talking-head clip: run faster-whisper with word_timestamps on the isolated voice and snap
# every start to the nearest energy onset (+-0.15 s); Whisper's own starts can be off by half a second. Words shape the subtitles only.
WORDS = [
    (2.13, "Honestly"), (3.00, "this"), (3.14, "place"), (3.30, "is"), (3.50, "great"), (3.68, "every"), (3.98, "single"), (4.30, "time"),
    (7.00, "The"), (7.40, "staff"), (7.62, "is"), (7.86, "friendly"), (8.20, "and"), (8.46, "the"), (8.64, "food"), (8.74, "is"), (8.98, "amazing"),
    (12.14, "I"), (12.32, "recommend"), (12.60, "it"), (12.76, "to"), (12.94, "everyone"), (13.86, "come"), (14.02, "visit"),
]


# ----------------------------------------------------------------------------- cut-list helpers
def hero(beats, tagline, start=0.3, tag_beat=4, **kw):
    """Intro: logo + embers, tagline lands on `tag_beat`. hook_sync=True: the tagline letters follow the hook words of a voice track."""
    return dict(kind="hero", start=start, beats=beats, embers=90, tagline=tagline, tag_beat=tag_beat, **kw)


def end_card(trans, beats=None, after=None):
    """Closing logo + END_TITLE + END_LINES. Length: `beats` beats, or until the first beat >= `after` s, or (default) up to
    the musical phrase/bar end that gives a 2.5-3.5 s card (needs build/phrases.json from tools/phrases.py)."""
    sp = dict(kind="hero", start=1.0, embers=90, trans=trans, end=True)
    if beats: sp["beats"] = beats
    elif after: sp["after"] = after
    else: sp["end_auto"] = True
    return sp


def V(clip, start, beats=None, speed=1.0, trans="flash", **kw):
    """Video shot: `clip` key, source start (s), length in beats, speed (0.5 = slow-mo, 1.5 = fast).
    trans = how the shot ARRIVES: hard | flash | whip | zoom. Extras: shake=True, title=, kicker=, subs=, tight=True (talking heads),
    zoom=1.8 (bottom-anchored crop-in), src_end= (derive the speed so the shot uses exactly start..src_end),
    until_abs= (cut on the beat nearest to an absolute song time instead of a beat count)."""
    sp = dict(kind="video", clip=clip, start=start, speed=speed, trans=trans, **kw)
    if beats: sp["beats"] = beats
    return sp


def P(file, beats, trans="hard", crop=None, **kw):
    """Photo shot. crop=(x, y, w, h) in source pixels (default: 9:16 center); drift=+-0.02 pans slowly; lift=True brightens dark stills (legacy grade only: the LUT grade matches exposure itself)."""
    return dict(kind="photo", file=file, beats=beats, trans=trans, crop=crop, **kw)


# ----------------------------------------------------------------------------- reels
REELS = {
    # 1) the place: hero intro, split crops of one wide photo, mixed transitions, titles with kicker, end card to a phrase end
    "reel1_place": dict(
        song=SONG_A, gain_db=-3.4,
        shots=[
            hero(4, "YOUR TAGLINE", tag_beat=1),       # a short intro (<= ~2 s) is the hook
            P("photo_01.jpg", 3, "whip", crop=(100, 300, 1237, 2200), drift=0.02),                # left half
            P("photo_01.jpg", 3, "hard", crop=(1261, 300, 1237, 2200), drift=-0.02, shake=True),  # right half
            V("clip_05", 0.3, 8, 1.25, "flash", kicker="YOUR AREA · YOUR CITY", title="TITLE {ONE}"),
            V("clip_04", 3.0, 4, 1.0, "zoom", shake=True),
            V("clip_03", 1.4, 8, 1.6, "whip"),
            V("clip_02", 0.0, 8, 1.4, "flash", title="TITLE TWO"),
            end_card("flash"),
        ]),
    # 2) food + testimonial: slow-mo, one clip with its isolated voice stem, bed under speech, word-timed subtitles
    "reel2_food": dict(
        song=SONG_B, gain_db=-4.0, voice_gain_db=8.4, bed_db=-6.0,
        voice="voice/clip_09_voice.wav",  # relative to --build-dir; sample 0 = clip time 0 (else set voice_t0 / av)
        voice_t0=0.0,            # source time of the voice file's sample 0 (a stem cut at 1.95 s would say 1.95)
        av=0.0,                  # s the clip's audio starts AFTER its video (ffprobe start_time difference): the voice is shifted to match
        first_word_offset=0.0,   # s from the cut start to the first spoken word: the bed ramps follow the speech, not the cut
        shots=[
            hero(8, "ANOTHER TAGLINE"),
            V("clip_07", 0.3, 6, 1.0, "flash", title="FOOD {TITLE}"),  # a title needs >= 1 s fully on screen: >= 6 beats at ~125 BPM
            V("clip_07", 8.5, 8, 0.5, "whip"),  # 0.5 = slow motion (use 120 fps sources)
            V("clip_06", 0.0, 2, 1.0, "hard", shake=True),
            V("clip_06", 2.0, 8, 1.0, "flash", title="TITLE {THREE}"),
            dict(kind="video", clip="clip_09", start=1.95, dur=8.3, speed=1.0, trans="zoom", voice_shot=True,
                 # (source start s, source end s, text[, y]); {braces} = accent word. Each chunk must fit ~78 % of the
                 # frame width at SUB_PX: use a condensed kicker font and 2-3 word chunks.
                 subs=[(2.10, 3.30, "FIRST LINE"), (3.40, 4.30, "SECOND {ACCENT} LINE"),
                       (4.40, 5.50, "THIRD LINE"), (5.60, 6.70, "FOURTH {ACCENT} LINE")]),
            end_card("flash", after=3.2),
        ]),
    # 3) atmosphere: photos + clips, fast cuts, no voice
    "reel3_atmosphere": dict(
        song=SONG_C, gain_db=1.4, music_fx="bass=g=-6:f=80:w=0.7",  # music_fx: any ffmpeg audio filters on the music bus
        shots=[
            hero(8, "A NIGHT AT {YOUR BRAND}"),
            P("photo_02.jpg", 2, "whip", drift=0.02),
            V("clip_08", 0.0, 8, 1.03, "flash", title="YOUR TAGLINE"),
            P("photo_03.jpg", 2, "hard", drift=-0.02, shake=True),
            P("photo_04.jpg", 2, "whip", drift=0.02),
            V("clip_03", 7.9, 4, 1.0, "zoom"),
            V("clip_04", 5.0, 4, 1.2, "whip"),
            V("clip_01", 1.0, 8, 1.5, "flash", title="TITLE {ONE}"),
            end_card("zoom", beats=8),
        ]),
    # 4) voice track: pieces of one talking-head clip + inserts + cold-open hook + instrumental bed
    "reel4_voice": dict(
        song=SONG_D, gain_db=-0.5, bed_db=-8.5, carve_db=-7.0,   # bed_db/carve_db are per song: stems differ by 3-6 dB
        voice="voice/talker.wav", voice_lufs=-13.6,              # isolated voice (voice/ pipeline); LUFS of the assembled voice
        voice_ref="honestly this place is great every single time the staff is friendly and the food is amazing i recommend it to everyone come visit",  # for tools/verify_voice.py
        shots=[
            # cold open: the payoff line plays under the logo, the tagline letters land with its words (hook_sync)
            hero(7, "WORTH {EVERY} SINGLE MINUTE", hook_sync=True),
            dict(kind="voice_track", clip="clip_10", words=WORDS, first_trans="whip", av=0.0,
                 hook=dict(src=(16.0, 18.4), at=0.25, words=[16.00, 16.50, 16.88, 17.26]),  # one source time per tagline word
                 pieces=[(2.0, 5.2), (7.0, 10.4), (12.0, 15.0)],     # source ranges, laid back to back with 0.12 s of real silence
                 framing=[(2.0, "wide"), (7.0, "tight"), (12.0, "wide")],  # alternate wide / tight to hide jump cuts
                 inserts=[                                            # B-roll over the voice (J/L-cut): anchored to SOURCE times
                     dict(at=8.0, until=10.4, kind="video", clip="clip_11", src=(1.0, 3.4)),
                     dict(at=13.0, until=14.6, kind="photo", file="photo_05.jpg"),
                 ]),
            end_card("flash"),
        ]),
}
