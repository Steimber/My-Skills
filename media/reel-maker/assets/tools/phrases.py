"""Musical phrase (8-beat) and bar (4-beat) boundaries per song, so end cards and long shots can end where the music ends.

    python phrases.py song_a=music/song_a.mp3 song_b=music/song_b.mp3 --songs build/songs.json --out build/phrases.json
    python phrases.py song_a=music/song_a.mp3 --songs build/songs.json --section song_a=49.6:40

Method: beat-synchronous chroma (CQT) -> novelty = 1 - cosine(chroma[i], chroma[i-1]); the phase of the 8-beat (and 4-beat) grid
is the one whose beats carry the highest mean novelty (chord / section changes land on phrase starts). Output
{key: {phr: [absolute times], bars: [absolute times], conf: share of novelty explained}}. `conf` = best phase / mean phase:
below ~1.2 the phase is a guess, so check by ear. --section KEY=START:SPAN restricts the phase estimate to the part of the song
a reel actually uses (songs whose arrangement changes meter or tempo need it); boundaries are still listed for the whole song.
Needs <build>/songs.json from analyze_songs.py. The engine reads phrases.json for `end_card(trans)` without a length.
"""
import argparse, json, warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def phrase_grid(path, beats, section=None):
    import numpy as np, librosa
    sr = 22050
    y, _ = librosa.load(path, sr=sr, mono=True)
    beats = np.asarray(beats, float)
    fr = librosa.time_to_frames(beats, sr=sr, hop_length=512)
    ch = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=512, fmin=librosa.note_to_hz("C1"), n_octaves=4)
    chb = librosa.util.sync(ch, fr, aggregate=np.median).T[1:len(fr) + 1]
    chn = chb / (np.linalg.norm(chb, axis=1, keepdims=True) + 1e-9)
    nov = 1 - (chn[1:] * chn[:-1]).sum(1)  # change between beat i and i+1 (index i+1 in `bt`)
    bt = beats[1:]
    n = min(len(nov), len(bt))
    nov, bt = nov[:n], bt[:n]
    idx = np.arange(n)
    sel = np.ones(n, bool) if not section else (bt >= section[0]) & (bt <= section[0] + section[1])
    out = {}
    for name, period in (("phr", 8), ("bars", 4)):
        sc = np.array([nov[sel & (idx % period == p)].mean() if (sel & (idx % period == p)).any() else 0.0 for p in range(period)])
        p = int(np.argmax(sc))
        out[name] = [round(float(bt[i]), 3) for i in range(n) if i % period == p]
        out[name + "_conf"] = round(float(sc.max() / (sc.mean() + 1e-12)), 2)
    return {"phr": out["phr"], "bars": out["bars"], "conf": out["phr_conf"], "bars_conf": out["bars_conf"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("songs", nargs="+", help="key=path (key must exist in songs.json)")
    ap.add_argument("--songs-json", "--songs", dest="songs_json", default="./build/songs.json", help="beat grids from analyze_songs.py")
    ap.add_argument("--out", default="./build/phrases.json")
    ap.add_argument("--section", action="append", default=[], metavar="KEY=START:SPAN", help="restrict the phase estimate to a song section (s)")
    a = ap.parse_args()
    S = json.load(open(a.songs_json, encoding="utf-8"))
    sections = {}
    for s in a.section:
        k, v = (s.split("=", 1) + [""])[:2]
        st, span = (v.split(":", 1) + [""])[:2]
        sections[k] = (float(st), float(span))
    dest = Path(a.out)
    out = json.load(open(dest, encoding="utf-8")) if dest.exists() else {}
    for item in a.songs:
        key, path = (item.split("=", 1) + [""])[:2]
        if key not in S:
            raise SystemExit(f"'{key}' is not in {a.songs_json}")
        r = phrase_grid(path, S[key]["beats"], sections.get(key))
        out[key] = r
        print(f"{key}: {len(r['phr'])} phrase starts (confidence {r['conf']}), {len(r['bars'])} bar starts (confidence {r['bars_conf']})")
        print("   first phrases:", r["phr"][:8])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out), encoding="utf-8")
    print("wrote", dest)


if __name__ == "__main__":
    main()
