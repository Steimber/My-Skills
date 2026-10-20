"""Print the candidate x metric tables (markdown) from sig.json / asr.json / ll.json / asrj.json.

    python report.py --work build/voice_work

PASS = the candidate matches the htdemucs baseline (h1) on word recall for BOTH Whisper sizes. Columns: gate, recall hits
small/medium (of N reference words), mean recall of the 3 edge-jittered variants + the plain run, mean log-likelihood of the
reference (higher = more intelligible), speech-to-residual in pauses and next to speech (dB, higher), hole fraction (lower),
share of >3 kHz cells carved away (lower), DNSMOS signal/background/overall (higher).
"""
import argparse
import common as C

LABEL = {"orig": "orig mix (control)", "h1": "htdemucs (baseline)", "h2": "htdemucs_ft", "m3": "mdx_extra", "e12": "ens h1+h2",
         "e23": "ens h2+m3", "e123": "ens h1+h2+m3", "orig_df": "DFN on orig (control)",
         "h1_g": "htdemucs + VAD expander", "e12_g": "ens h1+h2 + VAD expander", "e12_dfa12": "ens h1+h2 + DFN (max 12 dB)",
         "e12_dfa24": "ens h1+h2 + DFN (max 24 dB)", "e12_dfa12_g": "ens h1+h2 + DFN12 + expander"}
for k in ("h1", "h2", "m3", "e12", "e23", "e123"):
    LABEL[k + "_df"] = LABEL[k] + " + DFN"
    LABEL[k + "_nr"] = LABEL[k] + " + noisereduce"
ORDER = ["orig", "h1", "h2", "m3", "e12", "e23", "e123", "orig_df", "h1_df", "h2_df", "m3_df", "e12_df", "e23_df", "e123_df", "h1_nr", "e123_nr",
         "h1_g", "e12_g", "e12_dfa12", "e12_dfa24", "e12_dfa12_g"]


def mean4(asrj, sp, k, a_):
    j = asrj.get(sp, {}).get(k)
    if not j:
        return "-"
    m = lambda z: (a_[z]["hits"] + sum(j[z])) / (1 + len(j[z]))
    return " / ".join(f"{m(z):.2f}" for z in ("small", "medium") if z in a_ and z in j) or "-"


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    a = ap.parse_args()
    C.init(a.work)
    sig, asr, ll, asrj = (C.jload(n, {}) for n in ("sig.json", "asr.json", "ll.json", "asrj.json"))
    for sp in C.speakers():
        print(f"\n### Speaker {sp}\n")
        print("| candidate | gate | words small/med | 4-run mean s/m | LL small/med | S/R pauses | S/R near speech | holes | carved>3k | DNSMOS S/B/O |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        b = asr.get(sp, {}).get("h1")
        nan = float("nan")
        for k in ORDER:
            s_, a_ = sig.get(sp, {}).get(k), asr.get(sp, {}).get(k)
            if s_ is None or a_ is None:
                continue
            l_ = ll.get(sp, {}).get(k, {})
            ok = b is not None and all(a_[m]["hits"] >= b[m]["hits"] for m in ("small", "medium") if m in a_ and m in b)
            lls = " / ".join(f"{l_[m]['mean_lp']:.3f}" for m in ("small", "medium") if m in l_) or "-"
            words = "/".join(str(a_[m]["hits"]) for m in ("small", "medium") if m in a_)
            ref = next(iter(a_.values()))["ref"]
            print(f"| {LABEL.get(k, k)} | {'PASS' if ok else 'fail'} | {words} (of {ref}) | {mean4(asrj, sp, k, a_)} | {lls} "
                  f"| {s_['sr_all_db']:.1f} | {s_['sr_guard_db']:.1f} | {s_['hole_frac']:.3f} | {s_['carved_hf']:.2f} "
                  f"| {s_.get('dnsmos_sig', nan):.2f}/{s_.get('dnsmos_bak', nan):.2f}/{s_.get('dnsmos_ovrl', nan):.2f} |")


if __name__ == "__main__":
    main()
