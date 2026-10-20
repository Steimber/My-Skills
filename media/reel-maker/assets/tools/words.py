"""Word start times for subtitles and cut points: faster-whisper word timestamps snapped to the energy onsets of the voice.

    python words.py voice.wav 7.5:18.0 25:31 --lang en --model medium
    python words.py voice.wav 7.5:18.0 --snap 0.15 --thr 0.02

Each WINDOW is START:END in seconds of the file. Output per window:  word@snapped(raw_start-raw_end)  ...
Whisper's word starts can be off by ~0.5 s on separated voices; an onset of the voice envelope (silence >= 30 ms, then energy above
--thr RMS) within --snap seconds of the raw start is the true word start. Paste the snapped numbers into WORDS of the config.
Also the way to find cut points: end a piece in a pause, never inside a word; drop false-start takes ("ok", "ready", "and go").
Decodes the audio itself and passes a float32 array (faster-whisper + a new PyAV can fail on file inputs).
"""
import argparse, subprocess
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("audio", help="isolated-voice wav (or any media with audio)")
    ap.add_argument("windows", nargs="+", help="START:END seconds")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--model", default="medium", help="Whisper size (default medium)")
    ap.add_argument("--snap", type=float, default=0.15, help="max distance (s) to snap a word start to an onset")
    ap.add_argument("--thr", type=float, default=0.02, help="RMS threshold of the 10 ms envelope for an onset")
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.audio, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    sr = 16000
    r = np.array([np.sqrt(np.mean(x[i:i + 160] ** 2)) for i in range(0, len(x) - 160, 160)])
    ons, quiet = [], 0
    for i, v in enumerate(r):
        if v < a.thr:
            quiet += 1
        else:
            if quiet >= 3:
                ons.append(i / 100)
            quiet = 0
    ons = np.array(ons)
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    for w in a.windows:
        s, e = (w.split(":", 1) + [""])[:2]
        s, e = float(s), float(e)
        segs, _ = model.transcribe(x[int(s * sr):int(e * sr)], language=a.lang, beam_size=5, word_timestamps=True,
                                   condition_on_previous_text=False, vad_filter=False)
        out = []
        for sg in segs:
            for wd in sg.words:
                t, te = s + wd.start, s + wd.end
                if len(ons):
                    d = np.abs(ons - t); j = d.argmin()
                    snapped = ons[j] if d[j] <= a.snap else t
                else:
                    snapped = t
                out.append(f"{wd.word.strip()}@{snapped:.2f}({t:.2f}-{te:.2f})")
        print(f"[{s}-{e}]", " ".join(out), flush=True)


if __name__ == "__main__":
    main()
