import math
import re
import numpy as np

NOTE = {"C":0,"C#":1,"Db":1,"D":2,"D#":3,"Eb":3,"E":4,"F":5,"F#":6,"Gb":6,"G":7,"G#":8,"Ab":8,"A":9,"A#":10,"Bb":10,"B":11}
SCALES = {
    "major": [0,2,4,5,7,9,11],
    "minor": [0,2,3,5,7,8,10],
}
def _key_root(key):
    if not key: return 0, "major"
    m = re.match(r"^\s*([A-G](?:#|b)?)\s*(major|minor|maj|min)?\s*$", key, re.I)
    if not m: return 0, "major"
    name, mode = m.group(1), (m.group(2) or "major").lower()
    return NOTE.get(name, 0), ("minor" if mode in ("minor","min") else "major")

def _mood_energy(text):
    t = text.lower()
    if any(w in t for w in ["peak","exciting","energetic","uplifting","aggressive","intense"]): return 1.0
    if any(w in t for w in ["build","rising","growing","dramatic"]): return 0.72
    if any(w in t for w in ["calm","soft","peaceful","ambient","gentle"]): return 0.35
    if any(w in t for w in ["tense","dark","suspense"]): return 0.62
    return 0.58

def _section_energy(t, sections, default):
    active = default
    for s in sections:
        if s["start_s"] <= t: active = _mood_energy(s["mood"])
        else: break
    return active

def _env(n, sr, attack=0.005, release=0.04):
    a = max(1, int(attack*sr)); r = max(1, int(release*sr))
    e = np.ones(n, dtype=np.float32)
    e[:min(a,n)] = np.linspace(0,1,min(a,n),endpoint=False)
    e[max(0,n-r):] = np.linspace(1,0,min(r,n),endpoint=True)
    return e

def _tone(freq, n, sr, kind="sine", phase=0):
    x = np.arange(n, dtype=np.float32) / sr
    p = 2*np.pi*freq*x + phase
    if kind == "triangle": y = (2/np.pi)*np.arcsin(np.sin(p))
    elif kind == "saw": y = 2*((freq*x) % 1)-1
    else: y = np.sin(p)
    return y.astype(np.float32)

def generate_stems(prompt: str, duration_s: float, tempo_bpm: float | None, key: str | None,
                   sections: list[dict], seed: int, sample_rate: int = 48000):
    rng = np.random.default_rng(seed)
    sr = sample_rate
    n_total = int(round(duration_s * sr))
    beat = 60.0 / (tempo_bpm or (112 if _mood_energy(prompt) > .7 else 96))
    bpm = 60.0 / beat
    root, mode = _key_root(key)
    scale = SCALES[mode]
    # Deterministic chord progression in the selected scale.
    chord_degrees = [0, 3, 4, 0] if mode == "major" else [0, 5, 2, 6]
    stems = {name: np.zeros(n_total, dtype=np.float32) for name in ["drums","bass","harmony","melody"]}

    def add(name, start_s, signal, gain):
        start = max(0, int(round(start_s*sr)))
        if start >= n_total: return
        end = min(n_total, start + len(signal))
        stems[name][start:end] += signal[:end-start] * gain

    total_beats = math.ceil(duration_s / beat)
    for b in range(total_beats):
        t = b * beat
        if t >= duration_s: break
        energy = _section_energy(t, sections, _mood_energy(prompt))
        bar = b // 4
        beat_in_bar = b % 4
        # Kick and snare are synthesized as distinct transient events.
        if beat_in_bar in (0,2):
            length = min(int(.22*sr), n_total-int(t*sr))
            tt = np.arange(length)/sr
            kick = np.sin(2*np.pi*(75-35*tt/.22)*tt) * np.exp(-tt*22)
            add("drums", t, kick.astype(np.float32), .42*energy)
        if beat_in_bar in (1,3):
            length = min(int(.16*sr), n_total-int(t*sr))
            tt = np.arange(length)/sr
            noise = rng.normal(0,1,length).astype(np.float32)
            snare = noise*np.exp(-tt*28) + .25*np.sin(2*np.pi*180*tt)*np.exp(-tt*25)
            add("drums", t, snare, .13*energy)
        # Offbeat hats.
        hat_t = t + beat*.5
        if hat_t < duration_s:
            length = min(int(.045*sr), n_total-int(hat_t*sr))
            tt = np.arange(length)/sr
            noise = rng.normal(0,1,length).astype(np.float32)
            add("drums", hat_t, noise*np.exp(-tt*85), .035*energy)

        # Bass plays root/fifth on alternating beats.
        degree = chord_degrees[(bar//2) % len(chord_degrees)]
        semitone = scale[degree % 7] + (12 if beat_in_bar == 2 else 0)
        freq = 55 * 2**((root+semitone)/12)
        length = min(int(beat*.82*sr), n_total-int(t*sr))
        if length > 0:
            tt = np.arange(length)/sr
            bass = _tone(freq, length, sr, "saw") * np.exp(-tt*2.8)
            add("bass", t, bass, .12 + .09*energy)

        # Harmony: sustained triad once per bar, with a gentle pad envelope.
        if beat_in_bar == 0:
            deg = chord_degrees[(bar//2) % len(chord_degrees)]
            triad = [deg % 7, (deg+2) % 7, (deg+4) % 7]
            chord_len = min(int(beat*4*sr), n_total-int(t*sr))
            if chord_len > 0:
                tt = np.arange(chord_len)/sr
                pad = np.zeros(chord_len, dtype=np.float32)
                for idx, d in enumerate(triad):
                    sem = scale[d] + (12 if idx == 2 else 0)
                    f = 220 * 2**((root+sem)/12)
                    pad += _tone(f, chord_len, sr, "triangle", idx*.3) / 3
                fade = np.minimum(1, tt/.25) * np.minimum(1, (chord_len/sr-tt)/.3)
                add("harmony", t, pad*fade, .075)

        # Sparse melody, more active as energy rises.
        if (b % (2 if energy > .7 else 4) == 0):
            degree_idx = int(rng.integers(0,7))
            sem = scale[degree_idx] + 24
            f = 440 * 2**((root+sem-9)/12)
            length = min(int(beat*.7*sr), n_total-int(t*sr))
            if length > 0:
                tt = np.arange(length)/sr
                note = _tone(f, length, sr, "sine") * np.exp(-tt*3.2) * _env(length,sr,.025,.08)
                add("melody", t, note, .07*energy)

    # Deliberate fade at the end; apply identically to every stem so their sum remains exact.
    fade_n = min(int(.45*sr), n_total)
    if fade_n:
        fade = np.ones(n_total, dtype=np.float32)
        fade[-fade_n:] = np.linspace(1, 0, fade_n, endpoint=True)
        stems = {k: v*fade for k,v in stems.items()}
    return stems, bpm, f"{['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B'][root]} {mode}"
