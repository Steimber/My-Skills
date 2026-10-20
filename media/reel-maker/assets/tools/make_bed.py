"""Instrumental bed for the speech sections of a reel: the song's own no-vocals stem of the exact section the reel uses.

    python make_bed.py song_b=music/song_b.mp3@14.35 song_d=music/song_d.mp3@15.5 --build-dir build --seconds 40
    python make_bed.py song_b=music/song_b.mp3@14.35 --model htdemucs_ft

KEY=FILE@START : START is the reel's song start (third value of the song tuple in the config). Output:
<build>/beds/<key>_<start>/no_vocals.wav (stereo, 44.1 kHz, sample 0 = song time START) - the path the engine looks for.
Why: ducking a sung song by 16 dB under speech made the reel feel empty and still masked words; crossfading into the SAME
section without vocals (phase-aligned) at -7..-10 dB keeps the beat full while no sung words compete with the speaker.
Set bed_db / carve_db per song in the reel config (stems differ by 3-6 dB in effective depth). Check the START on this stem:
a "drop" that is a spoken skit has no music under it. Needs demucs (CPU is fine); models download on first use.
"""
import argparse, shutil, subprocess, sys, tempfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("items", nargs="+", help="KEY=FILE@START")
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--seconds", type=float, default=45.0, help="length of the section to separate (cover the longest reel using it)")
    ap.add_argument("--model", default="htdemucs", help="demucs model (default htdemucs)")
    a = ap.parse_args()
    for item in a.items:
        key, rest = (item.split("=", 1) + [""])[:2]
        path, start = rest.rsplit("@", 1) if "@" in rest else ("", "")
        if not (key and path and start):
            raise SystemExit(f"bad item '{item}': expected KEY=FILE@START")
        dest_dir = Path(a.build_dir) / "beds" / f"{key}_{float(start)}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            sec = Path(tmp) / f"{key}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", start, "-t", f"{a.seconds}", "-i", path, "-ac", "2", "-ar", "44100",
                            "-c:a", "pcm_s16le", str(sec)], check=True)
            subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", a.model, "-o", tmp, str(sec)], check=True)
            shutil.copyfile(Path(tmp) / a.model / key / "no_vocals.wav", dest_dir / "no_vocals.wav")
        print("wrote", dest_dir / "no_vocals.wav")


if __name__ == "__main__":
    main()
