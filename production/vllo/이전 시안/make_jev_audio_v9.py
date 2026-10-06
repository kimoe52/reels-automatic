"""Generate a calm, original ambient bed with no keyboard or typing Foley."""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v9/assets/jev-ambient-v9.wav"
SR = 44_100
DURATION = 18.0
CHORDS = (
    (174.61, 220.00, 261.63, 329.63),
    (164.81, 207.65, 246.94, 311.13),
    (146.83, 196.00, 246.94, 293.66),
    (164.81, 220.00, 261.63, 329.63),
)


def main():
    frames = int(SR * DURATION)
    left = array("h", [0]) * frames
    right = array("h", [0]) * frames
    chord_len = 4.5

    def voice(chord, t, right_channel=False):
        result = 0.0
        for n, freq in enumerate(chord):
            tuned = freq * (1.003 if right_channel else 1.0)
            phase = math.tau * tuned * t
            partial = math.sin(phase) + 0.14 * math.sin(phase * 2)
            result += (0.42 if n == 0 else 0.28) * partial / 4.0
        return result

    for i in range(frames):
        t = i / SR
        chord_idx = min(len(CHORDS) - 1, int(t / chord_len))
        local = t - chord_idx * chord_len
        val_l = voice(CHORDS[chord_idx], t)
        val_r = voice(CHORDS[chord_idx], t, right_channel=True)
        # Crossfade chord changes over 0.9 seconds instead of dropping to silence.
        if chord_idx > 0 and local < 0.9:
            blend = local / 0.9
            old_l = voice(CHORDS[chord_idx - 1], t)
            old_r = voice(CHORDS[chord_idx - 1], t, right_channel=True)
            val_l = old_l * (1 - blend) + val_l * blend
            val_r = old_r * (1 - blend) + val_r * blend
        # A slow, shallow swell prevents the bed from feeling like a held test tone.
        swell = 0.84 + 0.16 * math.sin(math.tau * 0.095 * t)
        edge = min(1.0, t / 0.5, (DURATION - t) / 0.8)
        l = val_l * swell * max(0.0, edge) * 0.68
        r = val_r * swell * max(0.0, edge) * 0.68
        left[i] = int(max(-1, min(1, l)) * 32767)
        right[i] = int(max(-1, min(1, r)) * 32767)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(array("h", [sample for pair in zip(left, right) for sample in pair]).tobytes())
    print(OUT)


if __name__ == "__main__":
    main()
