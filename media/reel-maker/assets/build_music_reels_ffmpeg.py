"""Beat-synced 4K vertical reels with plain ffmpeg xfade: cuts land on the song's beats, music ducks under speech.

    python build_music_reels_ffmpeg.py --videos clips --music music --build-dir build --out out [reel names...]

Needs <build-dir>/songs.json from tools/analyze_songs.py. Edit REELS below (placeholder names) for your project.
For the full compositor (whips, titles, embers) use reel_engine.py instead.
"""
import argparse, json, subprocess
from pathlib import Path

# Directories: replaced from the CLI in main().
SRC, MUSIC, TMP, OUT = Path("clips"), Path("music"), Path("build"), Path("out")
OUT_W, OUT_H = 2160, 3840
CENTER = "crop=ih*9/16:ih"
SONGS = {}
HARD = ("fade", 1 / 60)  # one-frame blend = hard cut

# Segment: (kind, file, src_start, beats, crop, input_opts)
#   kind "p" = still photo, "v" = video. beats=None means "use src_end" (fixed-length, last segment only):
#   the tuple then carries a 7th item, the source end time.
# trans[i] = (xfade transition, duration) between segment i and i+1; it ends exactly on the beat.
# File names resolve against --videos, then --build-dir.
REELS = {
    "reel1_place_music": dict(
        song=("song_a", "song_a.mp3", 49.6), gain_db=-3.4,
        segs=[
            ("p", "photo_01.jpg", 0, 2, "crop=1237:2200:100:300", []),
            ("p", "photo_01.jpg", 0, 2, "crop=1237:2200:1261:300", []),
            ("v", "clip_05.mp4", 0.3, 16, CENTER, []),
            ("v", "clip_04.mp4", 2.0, 12, CENTER, []),
            ("v", "clip_03.mp4", 1.4, 20, CENTER, []),
            ("v", "clip_02.mp4", 0.0, 12, CENTER, []),
        ],
        trans=[HARD, ("fadewhite", 0.22), ("smoothleft", 0.22), ("zoomin", 0.22), ("smoothup", 0.22)],
    ),
    "reel2_food_music": dict(
        song=("song_b", "song_b.mp3", 14.35), gain_db=-4.0, voice_gain_db=8.4,
        segs=[
            ("v", "clip_06.mp4", 0.0, 2, None, []),
            ("v", "clip_07.mp4", 0.0, 8, CENTER, []),
            ("v", "clip_07.mp4", 8.0, 8, CENTER, []),
            ("v", "clip_06.mp4", 2.0, 8, None, []),
            ("v", "clip_09.mp4", 1.95, None, "crop=ih*9/16:ih:1159:0", [], 10.25),
        ],
        trans=[("fadewhite", 0.24), ("zoomin", 0.24), ("smoothleft", 0.24), ("smoothup", 0.24)],
        voice="voice/clip_09_cut.wav",  # isolated speech cut to start at the testimonial segment (clip time 1.95 here), relative to --build-dir
        subs=[  # (source start s, end s, text) of the testimonial clip; {\c&H00D7FF&} = accent color (BGR)
            (2.10, 3.30, "FIRST LINE"),
            (3.40, 4.30, "SECOND {\\c&H00D7FF&}ACCENT LINE"),
            (4.40, 5.50, "THIRD LINE"),
            (5.60, 6.70, "FOURTH {\\c&H00D7FF&}ACCENT LINE"),
        ],
    ),
    "reel3_atmosphere_music": dict(
        song=("song_c", "song_c.mp3", 42.2), gain_db=2.4,
        segs=[
            ("p", "photo_02.jpg", 0, 4, CENTER, []),
            ("p", "photo_03.jpg", 0, 4, CENTER, []),
            ("v", "clip_08.mp4", 0.0, 7, CENTER, []),
            ("p", "photo_04.jpg", 0, 5, CENTER, []),
            ("v", "clip_01.mp4", 0.6, 12, CENTER, ["-noautorotate"]),
        ],
        trans=[("smoothleft", 0.28), ("zoomin", 0.28), ("smoothright", 0.28), ("fadewhite", 0.28)],
    ),
}

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 2160
PlayResY: 3840
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reel,Arial Black,190,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,12,6,2,120,120,1300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def media(name):
    """Absolute path as-is, else the clips dir, else the build dir."""
    p = Path(name)
    if p.is_absolute():
        return p
    return next((b / p for b in (SRC, TMP) if (b / p).exists()), SRC / p)


def build(name, cfg):
    key, song_file, S = cfg["song"]
    beats = [b - S for b in SONGS[key]["beats"] if b >= S - 0.05]
    segs, trans = cfg["segs"], cfg["trans"]
    assert len(trans) == len(segs) - 1

    # cut times on the beat grid: t[k] = moment segment k is fully on screen
    t, bi = [0.0], 0
    for seg in segs[:-1]:
        bi += seg[3]
        t.append(beats[bi])
    last = segs[-1]
    if last[3] is None:
        total = t[-1] + (last[6] - last[2]) - trans[-1][1]
    else:
        total = beats[bi + last[3]]

    args, vf, durs = [], [], []
    for k, seg in enumerate(segs):
        kind, f, s, nb, crop, opts = seg[:6]
        f = media(f)
        tin = trans[k - 1][1] if k else 0.0
        end_k = t[k + 1] if k + 1 < len(segs) else total
        d = end_k - t[k] + tin  # segment also covers the incoming transition
        if kind == "p":
            args += ["-loop", "1", "-framerate", "60", "-t", f"{d:.3f}", "-i", str(f)]
            trim = "setpts=PTS-STARTPTS"
        else:
            avail = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]))
            assert s + d <= avail + 0.005, f"{f.name}: needs {s + d:.3f}s, has {avail:.3f}s"
            args += [*opts, "-i", str(f)]
            trim = f"trim={s}:{s + d:.3f},setpts=PTS-STARTPTS"
        chain = [trim, "fps=60"] + ([crop] if crop else []) + [
            f"scale={OUT_W}:{OUT_H}:flags=lanczos", "setsar=1", "format=yuv420p"]
        vf.append(f"[{k}:v]{','.join(chain)}[s{k}]")
        durs.append(d)

    prev = "s0"
    for k in range(1, len(segs)):
        tr, T = trans[k - 1]
        out = f"x{k}"
        vf.append(f"[{prev}][s{k}]xfade=transition={tr}:duration={T:.4f}:offset={t[k] - T:.4f}[{out}]")
        prev = out

    n_in = len(segs)
    # --- audio: song section, ducked under the voice if any
    args += ["-ss", f"{S}", "-t", f"{total + 0.5:.3f}", "-i", str(MUSIC / song_file)]
    mi = n_in; n_in += 1
    fade_out = f"afade=t=out:st={total - 0.8:.3f}:d=0.8"
    # Fixed gains to ~-14 LUFS (measured with ebur128); a dynamic loudnorm made the music pump.
    gain = f"volume={cfg['gain_db']}dB"
    limit = "alimiter=limit=0.84:level=false"  # ~-1.5 dBTP safety
    voice = cfg.get("voice")
    if voice:
        v_start = t[-1] - trans[-1][1]  # first frame of the testimonial segment
        a0, r, floor = v_start, 0.3, 0.25  # music down 12 dB right as the speaker starts
        duck = f"volume='1-{1 - floor}*min(1,max(0,(t-{a0:.3f})/{r}))':eval=frame"
        vf.append(f"[{mi}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},{gain},{duck},{fade_out}[mus]")
        args += ["-i", str(TMP / voice)]
        vi = n_in; n_in += 1
        vf.append(f"[{vi}:a]aresample=48000,aformat=channel_layouts=stereo,volume={cfg['voice_gain_db']}dB,"
                  f"highpass=f=90,afade=t=in:d=0.08,afade=t=out:st={total - v_start - 0.25:.3f}:d=0.25[vo]")
        # real silence before the voice (no timestamp gap)
        vf.append(f"anullsrc=r=48000:cl=stereo:d={v_start:.3f}[sil];[sil][vo]concat=n=2:v=0:a=1[vpad]")
        vf.append(f"[mus][vpad]amix=inputs=2:normalize=0:duration=first,{limit},"
                  f"asetpts=N/SR/TB,atrim=0:{total:.3f}[a]")
    else:
        vf.append(f"[{mi}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},{gain},{fade_out},"
                  f"{limit},asetpts=N/SR/TB,atrim=0:{total:.3f}[a]")

    if cfg.get("subs"):
        s0 = segs[-1][2]
        v_start = t[-1] - trans[-1][1]
        lines = [f"Dialogue: 0,{ts(v_start + a - s0)},{ts(min(total, v_start + b - s0))},Reel,,0,0,0,,{txt}"
                 for a, b, txt in cfg["subs"]]
        ass = TMP / f"{name}.ass"
        ass.write_text(ASS_HEAD + "\n".join(lines) + "\n", encoding="utf-8")
        vf.append(f"[{prev}]ass={ass.name}[v]")
    else:
        vf.append(f"[{prev}]null[v]")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.mp4"  # all dirs are absolute (see main): ffmpeg runs with cwd=TMP so the .ass name stays relative
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *args,
           "-filter_complex", ";".join(vf), "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "16",
           "-profile:v", "high", "-level", "5.2", "-c:a", "aac", "-b:a", "256k",
           "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
    print(f"{name}: {total:.2f}s, cuts at " + ", ".join(f"{x:.2f}" for x in t[1:]), flush=True)
    subprocess.run(cmd, check=True, cwd=TMP)


def main():
    global SRC, MUSIC, TMP, OUT
    ap = argparse.ArgumentParser(description="Simple beat-synced xfade reel builder.")
    ap.add_argument("names", nargs="*", help="reel names from REELS (default: all)")
    ap.add_argument("--videos", default="./clips", help="dir with the source clips and photos")
    ap.add_argument("--music", default="./music", help="dir with the song files you provide")
    ap.add_argument("--build-dir", default="./build", help="dir with songs.json, voice stems; .ass files are written here")
    ap.add_argument("--out", default="./out", help="dir for the finished reels")
    a = ap.parse_args()
    SRC, MUSIC, TMP, OUT = (Path(x).resolve() for x in (a.videos, a.music, a.build_dir, a.out))
    SONGS.update(json.load(open(TMP / "songs.json", encoding="utf-8")))
    for n in (a.names or REELS):
        build(n, REELS[n])


if __name__ == "__main__":
    main()
