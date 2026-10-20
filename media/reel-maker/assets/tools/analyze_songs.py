"""Beat grid + energy map + drop candidates per song, to pick the best section for each reel.

    python analyze_songs.py song_a=music/song_a.mp3 song_b=music/song_b.mp3 --out build/songs.json
    python analyze_songs.py music/song_a.mp3 music/song_b.mp3          # key = file name without extension
    python analyze_songs.py song_b=music/song_b.mp3 --bpm 126          # force the tempo when the tracker picks half / 2/3 / double time

Use only audio files you are licensed to use. Existing keys of --out are kept, so you can run it song by song.
Output: songs.json {key: {tempo, beats, blocks, drops}}:
    beats   beat times (s) from librosa's tracker - the cut grid of the engine (the engine shifts it by BEAT_LAG)
    blocks  [(start s, energy 0..1)] per 8-beat block: the printed energy map is one character per block
    drops   [(time s, score)] candidate "drops" = beats where the mix gets much louder AND the bass comes back after a quiet
            stretch (score = geometric mean of the broadband-RMS and the 20-150 Hz energy ratio, 2 beats after vs 2 beats before)
A drop is a candidate, not a fact: VERIFY it by listening and on the instrumental stem (a spoken intro or a shout can look like a drop
while no music plays under it). Video versions of songs often start with talking. Start a reel on the drop; cut on beats.
"""
import argparse, json
from pathlib import Path


def drops(y, sr, beats, top=5, min_gap=8):
    """Rank beats by the energy jump across them. Returns [(time, score)] sorted by time, at least `min_gap` beats apart."""
    import numpy as np, librosa
    hop = 512
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    fr = librosa.fft_frequencies(sr=sr, n_fft=2048)
    rms = librosa.feature.rms(S=S, frame_length=2048, hop_length=hop)[0]
    bass = S[(fr >= 20) & (fr < 150)].sum(0)
    bt = librosa.times_like(rms, sr=sr, hop_length=hop)

    def per_beat(v):  # mean of v between consecutive beats
        idx = np.searchsorted(bt, beats)
        return np.array([v[idx[i]:max(idx[i + 1], idx[i] + 1)].mean() for i in range(len(beats) - 1)])

    r, b = per_beat(rms), per_beat(bass)
    sc = np.zeros(len(r))
    for i in range(2, len(r) - 2):
        rr = r[i:i + 2].mean() / (r[i - 2:i].mean() + 1e-9)
        bb = b[i:i + 2].mean() / (b[i - 2:i].mean() + 1e-9)
        sc[i] = float(np.sqrt(max(rr, 0) * max(bb, 0)))
    out = []
    for i in np.argsort(sc)[::-1]:
        if sc[i] <= 1.2:
            break
        if all(abs(i - j) >= min_gap for j, _ in out):
            out.append((int(i), float(sc[i])))
        if len(out) == top:
            break
    return sorted((round(float(beats[i]), 3), round(s, 2)) for i, s in out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("songs", nargs="+", help="key=path or plain path (key = file stem)")
    ap.add_argument("--out", default="./build/songs.json", help="output JSON (default: ./build/songs.json)")
    ap.add_argument("--bpm", type=float, default=None, help="force the tempo (BPM) when the tracker locks to 1/2, 2/3 or double time (start_bpm / tightness did not fix that in tests)")
    a = ap.parse_args()
    import numpy as np, librosa  # after parsing so --help works without them

    dest = Path(a.out)
    out = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
    for item in a.songs:
        key, path = (item.split("=", 1) + [""])[:2]
        if not path:
            key, path = Path(item).stem, item
        y, sr = librosa.load(path, sr=22050, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time", bpm=a.bpm)
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
        line = "".join(chars[min(9, int(v * 10))] for v in E)
        for j in range(0, len(line), 60):
            print(f"  {blocks[j][0]:7.1f}s |{line[j:j+60]}|")
        dr = drops(y, sr, beats)
        print("drop candidates (time s, score):", ", ".join(f"{t:.2f} ({s:.1f})" for t, s in dr) or "none")
        out[key] = {"tempo": tempo, "beats": [round(float(b), 3) for b in beats],
                    "blocks": [(b[0], round(float(e), 3)) for b, e in zip(blocks, E)], "drops": dr}

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out), encoding="utf-8")
    print("wrote", dest)


if __name__ == "__main__":
    main()
