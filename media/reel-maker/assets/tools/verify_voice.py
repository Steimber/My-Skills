"""Is the speech still intelligible in the FINAL MIX? Score word recall with Whisper against the reference text.

    python verify_voice.py mix out/reel4_voice.mp4 --window 3.2:18.5 --ref "what the speaker says, as said" --model small,medium
    python verify_voice.py reel reel4_voice --config my_project.py --final out/reel4_voice.mp4 --build-dir build --videos clips --music music

`mix`  : transcribe the window of a finished file and score recall vs --ref (normalised words: lower case, no accents/punctuation).
`reel` : window from the cut plan (voice track start..end), reference from cfg["voice_ref"] in the config; scores (1) the final mix,
         (2) the assembled voice bus alone (pieces + gaps, exactly as mixed) and prints the missed words of each. If the clean bus
         misses a word too, it is pronunciation or separation (subtitles cover it); if only the mix misses it, music is masking:
         lower bed_db, deepen carve_db, or trim the song's 1-4 kHz band.
Rules of thumb from testing: judge on the final mix, not the clean voice; recall is noisy (+-2 words), re-run with `small` and
`medium`; ~85 % recall on a sung track is fine when subtitles carry the rest; the same score on the clean voice caps what is possible.
"""
import argparse, difflib, re, subprocess, sys, unicodedata
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FS = 48000


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", s)


def recall(hyp, ref):
    h, r = norm(hyp), norm(ref)
    sm = difflib.SequenceMatcher(None, r, h, autojunk=False)
    got = sum(b.size for b in sm.get_matching_blocks())
    missed = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            missed.append(" ".join(r[i1:i2]) + ("->" + " ".join(h[j1:j2]) if tag == "replace" else ""))
    return got / max(1, len(r)), len(r), missed


def load_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", str(FS), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def transcribe(model, x48_stereo, lang):
    from scipy.signal import resample_poly
    m = x48_stereo.mean(1) if x48_stereo.ndim == 2 else x48_stereo
    a = resample_poly(m, 1, 3).astype(np.float32)
    segs, _ = model.transcribe(a, language=lang, beam_size=5, vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)


def report(label, hyp, ref):
    r, n, missed = recall(hyp, ref)
    print(f"  [{label}] recall {r * 100:.0f}% of {n} words | missed/substituted: {missed}\n      heard: {hyp}", flush=True)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    m = sub.add_parser("mix", help="score a window of a finished file")
    m.add_argument("file")
    m.add_argument("--window", required=True, help="START:END seconds of the speech in the file")
    m.add_argument("--ref", required=True, help="reference text")
    r = sub.add_parser("reel", help="window + reference from the project config")
    r.add_argument("name", help="reel name in the config")
    r.add_argument("--config", required=True)
    r.add_argument("--final", required=True, help="the rendered file of that reel")
    for p in (r,):
        p.add_argument("--build-dir", default="./build")
        p.add_argument("--videos", default="./clips")
        p.add_argument("--music", default="./music")
        p.add_argument("--assets", default="./assets")
    for p in (m, r):
        p.add_argument("--model", default="small", type=lambda s: s.split(","), help="Whisper sizes, comma separated (default small)")
        p.add_argument("--lang", default="en")
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    if a.mode == "mix":
        s, e = (a.window.split(":", 1) + [""])[:2]
        x = load_audio(a.file)[int(float(s) * FS):int((float(e) + 0.2) * FS)]
        for size in a.model:
            print(f"== {a.file} [{size}] {a.window}")
            report("final mix", transcribe(WhisperModel(size, device="cpu", compute_type="int8"), x, a.lang), a.ref)
        return

    import reel_engine as E
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    cfg = reels[a.name]
    ref = cfg.get("voice_ref")
    if not ref:
        sys.exit(f'{a.name}: set voice_ref="reference text" in the reel config')
    _, plan_ = E.plan(cfg)
    vt = cfg.get("_vt")
    t0, t1 = (vt["v_start"], vt["v_end"]) if vt else E.voice_window(cfg, plan_)
    if t1 <= t0:
        sys.exit(f"{a.name} has no voice")
    mix = load_audio(a.final)[int(t0 * FS):int((t1 + 0.2) * FS)]
    bus = None
    if vt:  # the assembled voice exactly as mixed (pieces, gaps, EQ), without music
        g = E.voice_gain_db(vt, cfg)
        graph = ";".join(E.voice_graph(vt, 0, g)) + f";[vpad]aresample={FS},aformat=channel_layouts=stereo[o]"
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(E.build_path(cfg["voice"])), "-filter_complex", graph, "-map", "[o]", "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        bus = np.frombuffer(raw, np.float32).reshape(-1, 2)[int(t0 * FS):int((t1 + 0.2) * FS)]
    for size in a.model:
        model = WhisperModel(size, device="cpu", compute_type="int8")
        print(f"== {a.name} [{size}] voice section {t0:.2f}-{t1:.2f}s")
        report("final mix", transcribe(model, mix, a.lang), ref)
        if bus is not None:
            report("voice bus only", transcribe(model, bus, a.lang), ref)


if __name__ == "__main__":
    main()
