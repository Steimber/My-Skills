"""Sanity checks for the numpy libdf port (no media needed):
(1) STFT perfect reconstruction + delay, (2) ERB band widths, (3) optional end-to-end: speech-like signal + synthetic
background (pink noise + a chord pad) at known SNRs -> DeepFilterNet3 must raise the SNR.

    python selftest_df.py            # steps 1-2 (only numpy/scipy)
    python selftest_df.py --e2e      # + step 3 (needs deepfilternet and its weights, see dfrun.py)
"""
import argparse
import numpy as np
import libdf
from libdf import DF


def speechlike(n, sr=48000, seed=1):
    """Voiced-looking signal: harmonic stack on a gliding pitch, formant-ish weighting, syllable-rate amplitude envelope."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    f0 = 120 + 25 * np.sin(2 * np.pi * 0.35 * t) + 5 * rng.standard_normal(n).cumsum() / np.sqrt(n)
    ph = 2 * np.pi * np.cumsum(f0) / sr
    x = sum(np.sin(h * ph) * np.exp(-((h * f0.mean() - 700) / 500) ** 2) / h ** 0.5 for h in range(1, 40))
    env = np.clip(np.sin(2 * np.pi * 3.2 * t) + 0.4, 0, None) ** 1.5
    return (x * env / np.abs(x * env).max() * 0.5).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--e2e", action="store_true", help="run the end-to-end DeepFilterNet3 check")
    a = ap.parse_args()

    df = DF(48000, 960, 480, 32, 2)
    print("erb widths", df.erb_widths().tolist(), "sum", int(df.erb_widths().sum()))
    rng = np.random.default_rng(0)
    x = rng.standard_normal((1, 48000)).astype(np.float32) * 0.1
    n = 960
    xp = np.concatenate([x, np.zeros((1, n), np.float32)], axis=1)
    y = df.synthesis(df.analysis(xp))
    d = n - 480
    err = np.max(np.abs(y[0, d:d + x.shape[1]] - x[0]))
    print("PR max abs err (delay %d):" % d, err)
    assert err < 1e-5

    clean = speechlike(48000 * 6)
    spec = df.analysis(clean[None])
    e = libdf.erb(spec, df.erb_widths())
    print("erb dB percentiles (expect roughly -100..-20):", np.percentile(e, [1, 50, 99]).round(1))
    print("erb_norm range", np.percentile(libdf.erb_norm(e, 0.99), [1, 50, 99]).round(3))
    if not a.e2e:
        print("ok (pass --e2e for the model check)")
        return

    import dfrun
    N = len(clean)
    w = rng.standard_normal(N)
    F = np.fft.rfft(w); f = np.fft.rfftfreq(N, 1 / 48000); F[1:] /= np.sqrt(f[1:] / 100 + 1); noise = np.fft.irfft(F, N)
    t = np.arange(N) / 48000
    noise = noise / noise.std() + 0.5 * sum(np.sin(2 * np.pi * fr * t) for fr in (220, 277, 330, 440, 660))  # pad-like background
    noise = noise.astype(np.float32)

    def snr(sig, ref):
        return 10 * np.log10(np.sum(ref ** 2) / np.sum((sig - ref) ** 2))

    for snr_db in (0, 5, 10):
        g = np.sqrt(np.sum(clean ** 2) / np.sum(noise ** 2) / 10 ** (snr_db / 10))
        noisy = clean + g * noise
        enh = dfrun.df_enhance(noisy)
        s = np.dot(enh, clean) / np.dot(enh, enh)  # best scalar fit of the enhanced to clean (the model may change gain)
        print("input SNR %2d dB -> output SNR %.1f dB (scaled), %.1f dB (raw)" % (snr_db, snr(s * enh, clean), snr(enh, clean)))


if __name__ == "__main__":
    main()
