"""Beat grid + energy map per song, to pick the best section for each reel.

    python analyze_songs.py song_a=music/song_a.mp3 song_b=music/song_b.mp3 --out build/songs.json
    python analyze_songs.py music/song_a.mp3 music/song_b.mp3          # key = file name without extension

Use only audio files you are licensed to use. Output: songs.json {key: {tempo, beats, blocks}}.
"""
import argparse, json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("songs", nargs="+", help="key=path or plain path (key = file stem)")
    ap.add_argument("--out", default="./build/songs.json", help="output JSON (default: ./build/songs.json)")
    a = ap.parse_args()
    import numpy as np, librosa  # after parsing so --help works without them

    out = {}
    for item in a.songs:
        key, _, path = item.partition("=")
        if not path:
            key, path = Path(item).stem, item
        y, sr = librosa.load(path, sr=22050, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        tempo = float(np.atleast_1d(tempo)[0])
        rms = librosa.feature.rms(y=y)[0]
        rt = librosa.times_like(rms, sr=sr)
        onset = librosa.onset.onset_strength(y=y, sr=sr)
        ot = librosa.times_like(onset, sr=sr)
        # energy per 8-beat block (2 bars of 4/4), starting on each beat index multiple of 4
        blocks = []
        for i in range(0, len(beats) - 8, 4):
            t0, t1 = beats[i], beats[i + 8]
            e = float(rms[(rt >= t0) & (rt < t1)].mean())
            o = float(onset[(ot >= t0) & (ot < t1)].mean())
            blocks.append((round(float(t0), 2), e, o))
        E = np.array([b[1] for b in blocks]); E = E / E.max()
        print(f"\n== {key}: {len(y)/sr:.1f}s tempo {tempo:.1f} BPM, beat {60/tempo:.3f}s, {len(beats)} beats")
        # coarse energy map, one char per block
        print("energy map (one char = 2 bars):")
        chars = " .:-=+*#%@"
        line = "".join(chars[min(9, int(v * 9.99))] for v in E)
        for j in range(0, len(line), 60):
            print(f"  {blocks[j][0]:7.1f}s |{line[j:j+60]}|")
        out[key] = {"tempo": tempo, "beats": [round(float(b), 3) for b in beats],
                    "blocks": [(b[0], round(float(e), 3)) for b, e in zip(blocks, E)]}

    dest = Path(a.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out), encoding="utf-8")
    print("wrote", dest)


if __name__ == "__main__":
    main()
