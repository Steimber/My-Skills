"""Stacked spectrograms of several candidates on the same dB scale, speech level-matched: look for what the model left or ate.

    python spec_plot.py A 7.0 6.0 out.png orig h1 e12_dfa12_g --work build/voice_work

Arguments: speaker, start s (source time), duration s, output png, candidate names. Needs matplotlib.
Read: music / noise bands that survive in the pauses, smeared or missing consonant energy above 3 kHz, "bubbling" musical noise.
"""
import argparse
import numpy as np, librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import common as C
import metrics as M


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("speaker")
    ap.add_argument("t0", type=float)
    ap.add_argument("dur", type=float)
    ap.add_argument("out")
    ap.add_argument("cands", nargs="+")
    a = ap.parse_args()
    C.init(a.work)
    sp, t0, dur = a.speaker, a.t0, a.dur
    vad = C.jload("vad.json", {})[sp]
    orig = C.read_mono48(C.HERE / "cands" / f"{sp}_orig.wav")
    speech = M.masks_from_vad(sp, vad, len(orig) // M.HOP + 1)[0]
    fig, axs = plt.subplots(len(a.cands), 1, figsize=(13, 2.6 * len(a.cands)), sharex=True)
    axs = np.atleast_1d(axs)
    for ax, n in zip(axs, a.cands):
        x = C.read_mono48(C.HERE / "cands" / f"{sp}_{n}.wav")
        m = np.pad(np.repeat(speech, M.HOP), (0, len(x)))[: len(x)]
        m = np.roll(m, -M.HOP // 2)
        x = x * 10 ** ((-26.0 - C.rms_db(x[m])) / 20)
        seg = x[int(t0 * C.SR): int((t0 + dur) * C.SR)]
        S = np.abs(librosa.stft(seg, n_fft=2048, hop_length=256, window="hann")) / 1024
        D = 20 * np.log10(S + 1e-9)
        im = ax.imshow(D, origin="lower", aspect="auto", cmap="magma", vmin=-110, vmax=-35, extent=[t0, t0 + dur, 0, C.SR / 2 / 1000])
        ax.set_ylim(0, 12); ax.set_ylabel(f"{n}\nkHz")
    fig.colorbar(im, ax=axs.tolist(), label="dB (|STFT|, speech-level matched)", pad=0.01)
    axs[-1].set_xlabel("time in the source file (s)")
    fig.suptitle(f"{sp}: spectrograms {t0}-{t0 + dur}s")
    fig.savefig(a.out, dpi=80)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
