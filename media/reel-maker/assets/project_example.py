"""Example project config for reel_engine.py. Copy it, rename the placeholders, point it at your own media.

    python assets/reel_engine.py --config my_project.py --preview        # fast 540x960 check
    python assets/reel_engine.py --config my_project.py                  # 4K finals

Everything project-specific lives here: clip table, brand palette/fonts/hero video, brand text and the
reel cut lists. File names are resolved against --videos (clips, photos), --music (songs), --assets
(fonts, hero video) and --build-dir (voice stems, derived images).
"""

# ----------------------------------------------------------------------------- brand
PALETTE = dict(
    text=(251, 245, 231),    # title / subtitle color
    accent=(255, 176, 102),  # {accent} keywords and kickers
    fire=(244, 108, 39),     # embers
    bg=(12, 14, 18),         # hero / end-card background
)
FONTS = dict(display="display.ttf", kicker="kicker.ttf", body="body.ttf")  # in --assets; bring your own fonts
HERO = "hero.mp4"                # logo animation on black, 2560x1440, in --assets
LOGO = (800, 1640, 130, 1190)    # stable logo content bbox (x0, x1, y0, y1) inside the hero video
LOGO_W, GROUP_CY = 0.88, 0.45    # logo width / frame width; vertical center of logo + text group
END_TITLE = "SEE YOU AT {YOUR BRAND.}"  # end card title; {braces} mark accent words
DOMAIN = "yourbrand.com"                # end card domain line

# Optional overrides of the default warm color look (ffmpeg filter chains):
# LOOK = "curves=...,vibrance=intensity=0.28,eq=contrast=1.04:saturation=1.05,cas=strength=0.45"
# FOOD_WARM = "colorbalance=rm=0.05:bm=-0.05,vibrance=intensity=0.10"

# ----------------------------------------------------------------------------- clips
# name -> (file, ffmpeg input opts, ffmpeg crop filter or None, allowed source windows (start, end) in s).
# A shot must fit inside one window; windows are the ranges you verified on the contact sheets.
# Shot length = beats x beat time x speed, so re-check windows for your song's tempo (placeholders here fit ~130 BPM).
CENTER = "crop=ih*9/16:ih"  # 9:16 center crop of landscape footage
CLIPS = {
    "clip_01": ("clip_01.mp4", ["-noautorotate"], CENTER, [(1.0, 7.85)]),  # wrong rotation metadata
    "clip_02": ("clip_02.mp4", [], CENTER, [(0, 5.5)]),
    "clip_03": ("clip_03.mp4", [], CENTER, [(0, 10.5)]),
    "clip_04": ("clip_04.mp4", [], CENTER, [(2.0, 7.7)]),
    "clip_05": ("clip_05.mp4", [], CENTER, [(0.3, 7.6)]),
    "clip_06": ("clip_06.mp4", [], None, [(0, 0.98), (2.0, 6.2)]),         # already vertical: no crop
    "clip_07": ("clip_07.mp4", [], CENTER, [(0, 3.5), (8.0, 12.5)]),       # food footage
    "clip_08": ("clip_08.mp4", [], CENTER, [(0, 4.8)]),
    "clip_09": ("clip_09.mp4", [], CENTER + ":1159:0", [(1.95, 10.25)]),  # testimonial: crop shifted to the speaker
}
FOOD_CLIPS = {"clip_07"}     # food clips get the extra appetizing warmth
AMBIENCE_CLIP = "clip_07"    # real sound of this clip is the ambience bed when a reel sets sfx=True (opt-in)

# ----------------------------------------------------------------------------- songs
# (key in songs.json, file in --music, start second of the section: the drop / hook)
SONG_A = ("song_a", "song_a.mp3", 49.6)
SONG_B = ("song_b", "song_b.mp3", 14.35)
SONG_C = ("song_c", "song_c.mp3", 42.2)


# ----------------------------------------------------------------------------- cut-list helpers
def hero(beats, tagline, start=0.3, tag_beat=4, **kw):
    """Intro: logo + embers, tagline lands on `tag_beat`."""
    return dict(kind="hero", start=start, beats=beats, embers=90, tagline=tagline, tag_beat=tag_beat, **kw)


def end_card(trans, beats=None, after=None):
    """Closing logo + END_TITLE + DOMAIN, for `beats` beats or until the first beat >= `after` seconds."""
    sp = dict(kind="hero", start=1.0, embers=90, trans=trans, end=True)
    if beats: sp["beats"] = beats
    else: sp["after"] = after
    return sp


def V(clip, start, beats, speed=1.0, trans="flash", **kw):
    """Video shot: `clip` key, source start (s), length in beats, speed (0.5 = slow-mo, 1.5 = fast).
    trans = how the shot ARRIVES: hard | flash | whip | zoom. Extras: shake=True, title=, kicker=, subs=."""
    return dict(kind="video", clip=clip, start=start, beats=beats, speed=speed, trans=trans, **kw)


def P(file, beats, trans="hard", crop=None, **kw):
    """Photo shot. crop=(x, y, w, h) in source pixels (default: 9:16 center); drift=+-0.02 pans slowly."""
    return dict(kind="photo", file=file, beats=beats, trans=trans, crop=crop, **kw)


# ----------------------------------------------------------------------------- reels
REELS = {
    # 1) the place: hero intro, split crops of one wide photo, mixed transitions, titles with kicker
    "reel1_place": dict(
        song=SONG_A, gain_db=-3.4,
        shots=[
            hero(8, "YOUR TAGLINE"),
            P("photo_01.jpg", 2, "whip", crop=(100, 300, 1237, 2200), drift=0.02),                 # left half
            P("photo_01.jpg", 2, "hard", crop=(1261, 300, 1237, 2200), drift=-0.02, shake=True),   # right half
            V("clip_05", 0.3, 8, 1.25, "flash", kicker="YOUR KICKER", title="TITLE {ONE}"),
            V("clip_04", 3.0, 4, 1.0, "zoom", shake=True),
            V("clip_03", 1.4, 8, 1.6, "whip"),
            V("clip_02", 0.0, 8, 1.5, "flash", title="TITLE TWO"),
            V("clip_08", 0.8, 4, 1.0, "zoom"),
            V("clip_01", 3.0, 8, 1.35, "whip"),
            end_card("flash", beats=8),
        ]),
    # 2) food + testimonial: slow-mo, voice isolated with Demucs, music ducked, word-accurate subtitles
    "reel2_food": dict(
        song=SONG_B, gain_db=-4.0, voice_gain_db=8.4,
        voice="sep/htdemucs/voice_src/vocals.wav",  # relative to --build-dir
        shots=[
            hero(8, "ANOTHER TAGLINE"),
            V("clip_07", 0.3, 4, 1.0, "flash", title="FOOD {TITLE}"),
            V("clip_07", 8.5, 8, 0.5, "whip"),  # 0.5 = slow motion (use 120 fps sources)
            V("clip_06", 0.0, 2, 1.0, "hard", shake=True),
            V("clip_06", 2.0, 8, 1.0, "flash", title="TITLE {THREE}"),
            dict(kind="video", clip="clip_09", start=1.95, dur=8.3, speed=1.0, trans="zoom", voice_shot=True,
                 # (source start s, source end s, text); {braces} = accent word. Each chunk must fit ~96 % of the
                 # frame width at 240 px (4K): use a condensed kicker font and 2-3 word chunks.
                 subs=[(2.10, 3.30, "FIRST LINE"), (3.40, 4.30, "SECOND {ACCENT} LINE"),
                       (4.40, 5.50, "THIRD LINE"), (5.60, 6.70, "FOURTH {ACCENT} LINE")]),
            end_card("flash", after=3.2),
        ]),
    # 3) atmosphere: photos + clips, fast cuts, no voice
    "reel3_atmosphere": dict(
        song=SONG_C, gain_db=1.4,
        shots=[
            hero(8, "A NIGHT AT {YOUR BRAND}"),
            P("photo_02.jpg", 2, "whip", drift=0.02),
            V("clip_08", 0.0, 8, 1.03, "flash", title="YOUR TAGLINE"),
            P("photo_03.jpg", 2, "hard", drift=-0.02, shake=True),
            P("photo_04.jpg", 2, "whip", drift=0.02),
            V("clip_03", 3.5, 4, 1.0, "zoom"),
            V("clip_02", 0.0, 4, 2.0, "whip"),
            V("clip_01", 1.0, 8, 1.5, "flash", title="TITLE {ONE}"),
            end_card("zoom", beats=8),
        ]),
}
