"""Extract the audio of every speaker's source file as 48 kHz stereo float WAV, sample 0 = first AUDIO sample of the file.

    python extract.py --work build/voice_work

Check `ffprobe -show_entries stream=start_time` of the source: phone files sometimes start their audio tens of ms after the video.
That offset is NOT removed here; give it to the engine as `av=` on the voice track (and `voice_t0` when a stem is cut).
Source paths in spec.json are relative to the current directory.
"""
import argparse, subprocess
import common as C


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("speakers", nargs="*", help="speaker ids (default: all)")
    a = ap.parse_args()
    C.init(a.work)
    for sp in C.speakers(a.speakers):
        out = C.HERE / "src" / f"{sp}_orig48.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", C.SPEC["speakers"][sp]["source"], "-vn", "-ac", "2", "-ar", str(C.SR),
                        "-c:a", "pcm_f32le", str(out)], check=True)
        print(sp, "->", out)


if __name__ == "__main__":
    main()
