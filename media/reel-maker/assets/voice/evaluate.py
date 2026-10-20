"""Score the voice candidates. Results are cached as JSON in the work dir; every stage is incremental.

    python evaluate.py mask                      # Silero VAD on several cleaned candidates -> shared speech/gap frame masks (vad.json)
    python evaluate.py sig [cand ...]            # signal metrics (+ DNSMOS if `speechmos` is installed), level-matched, shared masks
    python evaluate.py asr [cand ...]            # word recall vs the reference text on the used ranges, faster-whisper small + medium
    python evaluate.py ll  [cand ...]            # teacher-forced Whisper log-likelihood of the reference text (continuous intelligibility)
    python evaluate.py asrj cand ...             # recall with the range edges jittered by a few tens of ms (robustness, 3 variants)
    (all take --work build/voice_work; `asr`/`ll` take --models small,medium)

Method notes from testing:
  * Every candidate is scaled to the same speech RMS (-26 dB) before measuring: ASR and DNSMOS are level sensitive.
  * ASR recall is noisy (+-2 words on ~100): use `ll` (likelihood of the reference) as the steadier gate and `asrj` to see jitter.
  * A candidate "passes" when it matches the baseline htdemucs stem on both Whisper sizes AND improves speech-to-residual.
  * Residual metrics alone reward over-gating; always read them next to recall and the hole/carved columns of report.py.
"""
import argparse, collections, glob, os
import numpy as np
import common as C
import metrics as M

TARGET_DB = -26.0  # speech RMS every candidate is scaled to before measuring


def cand_names(sp):
    return [os.path.basename(f)[len(sp) + 1:-4] for f in sorted(glob.glob(str(C.HERE / "cands" / f"{sp}_*.wav")))]


def whisper(size):
    from faster_whisper import WhisperModel
    return WhisperModel(size, device="cpu", compute_type="int8")


def load_cand(sp, name):
    return C.read_mono48(C.HERE / "cands" / f"{sp}_{name}.wav")


def speech_gain(x, speech_frames):
    """gain (linear) so the RMS over shared-mask speech frames equals TARGET_DB."""
    m = np.repeat(speech_frames, M.HOP)[: len(x)]
    m = np.pad(m, (0, len(x) - len(m)))
    m = np.roll(m, -M.HOP // 2)  # frame k is centred on k*HOP -> shift by HOP/2 to cover samples
    if not m.any():
        raise SystemExit("no speech frames: the VAD consensus found no voice inside the ranges of spec.json - check the ranges, "
                         "re-run `evaluate.py mask` once more candidates exist (build_cands.py)")
    return 10 ** ((TARGET_DB - C.rms_db(x[m])) / 20)


def masks(sp, vad, n):
    return M.masks_from_vad(sp, vad[sp], n // M.HOP + 1)


def stage_mask(a):
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    out = {}
    for sp in C.speakers(a.speakers):
        out[sp] = {}
        for name in ("h1", "h2", "m3", "e12", "e123", "h1_df", "e12_df", "e123_df"):  # the cleaned candidates that exist
            if not (C.HERE / "cands" / f"{sp}_{name}.wav").exists():
                continue
            x16 = C.to16k(load_cand(sp, name))
            seg = get_speech_timestamps(x16, VadOptions(threshold=0.5, min_speech_duration_ms=60, min_silence_duration_ms=60, speech_pad_ms=20))
            out[sp][name] = [(round(s["start"] / 16000, 3), round(s["end"] / 16000, 3)) for s in seg]
        print(sp, {k: len(v) for k, v in out[sp].items()})
    old = C.jload("vad.json", {})
    old.update(out)
    C.jsave("vad.json", old)


def stage_sig(a):
    res = C.jload("sig.json", {})
    vad = C.jload("vad.json", {})
    try:
        from speechmos import dnsmos
    except Exception as e:  # optional
        dnsmos = None; print("DNSMOS unavailable:", e)
    for sp in C.speakers(a.speakers):
        orig = load_cand(sp, "orig")
        speech, gap, gap_all, guard = masks(sp, vad, len(orig))
        print(sp, "speech frames", int(speech.sum()), "gap frames", int(gap.sum()), "gap_all", int(gap_all.sum()), flush=True)
        g0 = speech_gain(orig, speech)
        refP = M.stft_pow(orig * g0)
        for name in cand_names(sp):
            if a.cands and name not in a.cands:
                continue
            x = load_cand(sp, name)
            x = x * speech_gain(x, speech)
            r = M.analyze(x, refP, sp, speech, gap, gap_all, guard)
            r["lag_vs_orig"] = M.lag_vs(x, orig * g0, sp)
            r["used_peak_dbfs"] = float(20 * np.log10(np.abs(C.used_concat(sp, x)).max() + 1e-12))
            if dnsmos is not None:
                u16 = C.to16k(C.used_concat(sp, x))
                u16 = u16 / max(1.0, np.abs(u16).max() / 0.99)
                try:
                    d = dnsmos.run(u16.astype(np.float32), 16000)
                    r.update(dnsmos_sig=float(d["sig_mos"]), dnsmos_bak=float(d["bak_mos"]), dnsmos_ovrl=float(d["ovrl_mos"]))
                except Exception as e:
                    print("dnsmos failed", name, e)
            res.setdefault(sp, {})[name] = r
            print(sp, name, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
        C.jsave("sig.json", res)


def stage_asr(a):
    res = C.jload("asr.json", {})
    vad = C.jload("vad.json", {})
    models = {s: whisper(s) for s in a.models}
    for sp in C.speakers(a.speakers):
        orig = load_cand(sp, "orig")
        speech = masks(sp, vad, len(orig))[0]
        ref_total = sum(len(C.norm_words(t)) for _, _, t in C.RANGES[sp])
        for name in cand_names(sp):
            if a.cands and name not in a.cands:
                continue
            x = load_cand(sp, name)
            x = x * speech_gain(x, speech)
            x16 = C.to16k(x)
            entry = res.setdefault(sp, {}).setdefault(name, {})
            for msize, model in models.items():
                hits = extra = 0
                lps, texts = [], []
                for s0, s1, ref in C.RANGES[sp]:
                    seg, _i = model.transcribe(x16[int(s0 * 16000):int(s1 * 16000)], language=C.LANG,
                                               condition_on_previous_text=False, temperature=0.0, beam_size=5)
                    seg = list(seg)
                    hyp = " ".join(s.text for s in seg)
                    lps += [s.avg_logprob for s in seg]
                    rc, hc = collections.Counter(C.norm_words(ref)), collections.Counter(C.norm_words(hyp))
                    h = sum((rc & hc).values())
                    hits += h; extra += sum(hc.values()) - h
                    texts.append(hyp.strip())
                entry[msize] = dict(recall=hits / ref_total, hits=hits, ref=ref_total, extra=extra,
                                    logprob=float(np.mean(lps)) if lps else None, text=texts)
                print(sp, name, msize, "recall %.3f (%d/%d) extra %d lp %.3f" % (hits / ref_total, hits, ref_total, extra, entry[msize]["logprob"] or 0), flush=True)
            C.jsave("asr.json", res)


def stage_ll(a):
    from faster_whisper.audio import pad_or_trim
    from faster_whisper.tokenizer import Tokenizer
    res = C.jload("ll.json", {})
    vad = C.jload("vad.json", {})
    models = {s: whisper(s) for s in a.models}
    for sp in C.speakers(a.speakers):
        orig = load_cand(sp, "orig")
        speech = masks(sp, vad, len(orig))[0]
        # optional punctuated / accented reference per range ("ref_tf" in spec.json): scored as typed, tokens included
        refs = C.SPEC["speakers"][sp].get("ref_tf") or [t for _, _, t in C.RANGES[sp]]
        for name in cand_names(sp):
            if a.cands and name not in a.cands:
                continue
            x = load_cand(sp, name)
            x16 = C.to16k(x * speech_gain(x, speech))
            entry = res.setdefault(sp, {}).setdefault(name, {})
            for msize, model in models.items():
                tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=C.LANG)
                lps = []
                for (s0, s1, _), ref in zip(C.RANGES[sp], refs):
                    seg = x16[int(s0 * 16000):int(s1 * 16000)]
                    feats = model.feature_extractor(seg)
                    enc = model.encode(pad_or_trim(feats))
                    toks = tok.encode(" " + ref.strip())
                    r = model.model.align(enc, tok.sot_sequence, [toks], len(seg) // 160)[0]
                    p = np.asarray(r.text_token_probs, dtype=np.float64)[: len(toks)]
                    lps += list(np.log(np.clip(p, 1e-9, 1)))
                lps = np.asarray(lps)
                entry[msize] = dict(mean_lp=float(lps.mean()), frac_gt05=float((lps > np.log(0.5)).mean()), n=int(len(lps)))
            print(sp, name, {m: round(v["mean_lp"], 3) for m, v in entry.items()}, flush=True)
            C.jsave("ll.json", res)


def stage_asrj(a):
    # robustness: recall with the used ranges' edges jittered by a few tens of ms (3 variants); the unjittered run is in asr.json
    JIT = [(-0.02, 0.02), (0.015, -0.015), (0.0, 0.03)]
    res = C.jload("asrj.json", {})
    vad = C.jload("vad.json", {})
    models = {s: whisper(s) for s in a.models}
    for sp in C.speakers(a.speakers):
        orig = load_cand(sp, "orig")
        speech = masks(sp, vad, len(orig))[0]
        for name in a.cands:
            if not (C.HERE / "cands" / f"{sp}_{name}.wav").exists():
                continue
            x = load_cand(sp, name)
            x16 = C.to16k(x * speech_gain(x, speech))
            entry = res.setdefault(sp, {}).setdefault(name, {})
            for msize, model in models.items():
                hits_all = []
                for ds, de in JIT:
                    hits = 0
                    for s0, s1, ref in C.RANGES[sp]:
                        seg, _i = model.transcribe(x16[int((s0 + ds) * 16000):int((s1 + de) * 16000)], language=C.LANG,
                                                   condition_on_previous_text=False, temperature=0.0, beam_size=5)
                        hyp = " ".join(s.text for s in seg)
                        hits += sum((collections.Counter(C.norm_words(ref)) & collections.Counter(C.norm_words(hyp))).values())
                    hits_all.append(hits)
                entry[msize] = hits_all
            print(sp, name, entry, flush=True)
            C.jsave("asrj.json", res)


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("stage", choices=["mask", "sig", "asr", "ll", "asrj"])
    ap.add_argument("cands", nargs="*", help="candidate names (default: all in cands/)")
    ap.add_argument("--speaker", dest="speakers", action="append", default=[], help="restrict to a speaker id (repeatable)")
    ap.add_argument("--models", default="small,medium", type=lambda s: s.split(","), help="Whisper sizes for asr/ll/asrj")
    a = ap.parse_args()
    C.init(a.work)
    {"mask": stage_mask, "sig": stage_sig, "asr": stage_asr, "ll": stage_ll, "asrj": stage_asrj}[a.stage](a)


if __name__ == "__main__":
    main()
