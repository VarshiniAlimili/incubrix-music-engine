from pathlib import Path
import numpy as np
import soundfile as sf

def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(audio, dtype=np.float32), sample_rate, subtype="PCM_24")

def apply_shared_gain(stems: dict[str, np.ndarray], target_lufs: float, peak_ceiling_db: float = -1.0):
    mix = np.sum(np.stack(list(stems.values()), axis=0), axis=0)
    # Pyloudnorm is used when available. A conservative RMS fallback keeps the
    # prototype runnable, but final LUFS compliance must be independently checked.
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(48000)
        measured = meter.integrated_loudness(mix)
        gain_db = target_lufs - measured if np.isfinite(measured) else 0.0
    except Exception:
        rms = float(np.sqrt(np.mean(mix ** 2) + 1e-12))
        measured_db = 20 * np.log10(max(rms, 1e-9))
        gain_db = target_lufs - measured_db - 3.0

    peak = float(np.max(np.abs(mix)) + 1e-12)
    peak_db = 20 * np.log10(peak)
    gain_db = min(gain_db, peak_ceiling_db - peak_db)
    gain = 10 ** (gain_db / 20.0)
    scaled = {name: (audio * gain).astype(np.float32) for name, audio in stems.items()}
    final_mix = np.sum(np.stack(list(scaled.values()), axis=0), axis=0).astype(np.float32)
    return scaled, final_mix, float(gain_db)

def audio_metrics(audio: np.ndarray, sample_rate: int):
    peak = float(np.max(np.abs(audio)) + 1e-12)
    peak_dbfs = 20 * np.log10(peak)
    try:
        import pyloudnorm as pyln
        lufs = float(pyln.Meter(sample_rate).integrated_loudness(audio))
    except Exception:
        rms = float(np.sqrt(np.mean(audio ** 2) + 1e-12))
        lufs = float(20 * np.log10(max(rms, 1e-9)))
    return {"integrated_lufs": lufs, "sample_peak_dbfs": peak_dbfs}
