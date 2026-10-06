"""Build a quiet ASMR-style, no-music foley bed for the Jev explainer."""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "media/audio/jev-foley-v5.wav"
SR = 44_100
DURATION = 16.0


def tap(buf_l, buf_r, start, amp=0.18, tone=2850, pan=0.5, duration=0.032):
    """Short, close key/trackpad tap built from noise and a tiny resonant click."""
    start_i = int(start * SR)
    n = int(duration * SR)
    lg, rg = math.sqrt(1.0 - pan), math.sqrt(pan)
    phase = random.random() * math.tau
    for j in range(n):
        i = start_i + j
        if i >= len(buf_l):
            break
        t = j / SR
        env = math.exp(-t * (95 if duration < 0.02 else 72))
        noise = random.uniform(-1.0, 1.0)
        click = 0.42 * math.sin(math.tau * tone * t + phase)
        low = 0.18 * math.sin(math.tau * 310 * t)
        v = amp * env * (0.68 * noise + click + low)
        buf_l[i] += v * lg
        buf_r[i] += v * rg


def soft_tone(buf_l, buf_r, start, freq, dur=0.22, amp=0.075, pan=0.5):
    start_i = int(start * SR)
    n = int(dur * SR)
    lg, rg = math.sqrt(1.0 - pan), math.sqrt(pan)
    for j in range(n):
        i = start_i + j
        if i >= len(buf_l):
            break
        t = j / SR
        env = min(1.0, t / 0.012) * math.exp(-t * 15)
        v = amp * env * math.sin(math.tau * freq * t)
        buf_l[i] += v * lg
        buf_r[i] += v * rg


def main():
    random.seed(523)
    n = int(SR * DURATION)
    left = [0.0] * n
    right = [0.0] * n

    # No song or voice: soft close-mic-style key taps and trackpad clicks.
    typing_groups = [
        (0.24, 1.0, 9),
        (2.72, 3.35, 5),
        (5.40, 6.05, 7),
        (8.55, 9.42, 10),
        (12.86, 13.35, 5),
    ]
    for start, end, count in typing_groups:
        stamps = sorted(random.uniform(start, end) for _ in range(count))
        for j, stamp in enumerate(stamps):
            pan = 0.25 + 0.5 * random.random()
            amp = 0.11 + 0.045 * random.random()
            tap(left, right, stamp, amp=amp, tone=random.choice((2400, 2780, 3220)), pan=pan)

    # A restrained pointer click on proof/diagram reveals.
    for i, stamp in enumerate((0.08, 2.62, 5.20, 8.38, 12.72, 15.35)):
        tap(left, right, stamp, amp=0.21, tone=1900, pan=(0.38 if i % 2 == 0 else 0.62), duration=0.018)

    # One soft low-to-high confirmation at the final routing reveal.
    soft_tone(left, right, 12.94, 659.25, dur=0.20, amp=0.045, pan=0.44)
    soft_tone(left, right, 13.00, 987.77, dur=0.24, amp=0.035, pan=0.56)

    # Gentle fade and conservative mastering headroom.
    peak = max(max(abs(v) for v in left), max(abs(v) for v in right), 1e-9)
    gain = 0.56 / peak
    pcm = array("h")
    for i, (l, r) in enumerate(zip(left, right)):
        fade = min(1.0, i / (0.04 * SR), (n - i) / (0.22 * SR))
        pcm.append(int(max(-1.0, min(1.0, l * gain * fade)) * 32767))
        pcm.append(int(max(-1.0, min(1.0, r * gain * fade)) * 32767))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    print(OUT)


if __name__ == "__main__":
    main()
