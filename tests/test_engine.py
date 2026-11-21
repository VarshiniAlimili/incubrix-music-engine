import numpy as np
from app.engine.composer import generate_stems
from app.engine.audio import apply_shared_gain

def test_stems_have_exact_length_and_are_independent():
    sr = 48000
    duration = 5.25
    stems, bpm, key = generate_stems("calm optimistic instrumental", duration, 100, "C major", [], 7, sr)
    expected = round(duration * sr)
    assert set(stems) == {"drums","bass","harmony","melody"}
    assert all(len(x) == expected for x in stems.values())
    assert all(np.any(np.abs(x) > 0) for x in stems.values())
    scaled, mix, gain = apply_shared_gain(stems, -16)
    reconstructed = np.sum(np.stack(list(scaled.values())), axis=0)
    assert np.allclose(mix, reconstructed, atol=1e-6)
    assert len(mix) == expected
