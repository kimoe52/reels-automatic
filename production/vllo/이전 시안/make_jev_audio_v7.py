"""Make a restrained, no-voice ASMR foley track synced to Jev Reel v7."""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v7/assets/jev-asmr-v7.wav"
SR = 44_100
DURATION = 18.0


def click(left, right, start, *, amp=0.10, pan=0.5, tone=1850, duration=0.024):
    start_i = int(start * SR)
    n = int(duration * SR)
    lg, rg = math.sqrt(1.0 - pan), math.sqrt(pan)
    phase = random.random() * math.tau
    for j in range(n):
        i = start_i + j
        if i >= len(left):
            break
        t = j / SR
        env = math.exp(-t * 85)
        noise = random.uniform(-1.0, 1.0)
        body = 0.25 * math.sin(math.tau * 320 * t)
        tick = 0.35 * math.sin(math.tau * tone * t + phase)
        sample = amp * env * (0.55 * noise + tick + body)
        left[i] += sample * lg
        right[i] += sample * rg


def soft_brush(left, right, start, *, duration=0.38, amp=0.018, pan=0.5):
    start_i = int(start * SR)
    n = int(duration * SR)
    lg, rg = math.sqrt(1.0 - pan), math.sqrt(pan)
    prior = 0.0
    for j in range(n):
        i = start_i + j
        if i >= len(left):
            break
        t = j / SR
        raw = random.uniform(-1.0, 1.0)
        noise = prior * 0.82 + raw * 0.18
        prior = noise
        fade = min(1.0, t / 0.05, (duration - t) / 0.07)
        swell = 0.88 + 0.12 * math.sin(math.tau * 5.0 * t)
        sample = amp * max(0.0, fade) * swell * noise
        left[i] += sample * lg
        right[i] += sample * rg


def main():
    random.seed(723)
    n = int(SR * DURATION)
    left = [0.0] * n
    right = [0.0] * n

    # Distinct cut cues: error click, route reveal, question, response structure, boundary, save.
    for i, stamp in enumerate((0.12, 2.78, 5.68, 8.18, 12.18, 15.58, 17.66)):
        click(left, right, stamp, amp=0.115 if i in (0, 6) else 0.082,
              pan=(0.42 if i % 2 == 0 else 0.58), tone=1550 if i == 0 else 2100,
              duration=0.03 if i == 0 else 0.019)

    # Short, irregular typing clusters, kept quiet enough to sit under captions.
    clusters = ((0.40, 1.12, 9), (3.10, 4.12, 8), (6.88, 7.46, 5),
                (8.62, 9.10, 6), (10.0, 10.88, 8), (13.04, 13.66, 5))
    for start, end, count in clusters:
        for stamp in sorted(random.uniform(start, end) for _ in range(count)):
            click(left, right, stamp, amp=random.uniform(0.036, 0.052),
                  pan=random.uniform(0.38, 0.62), tone=random.choice((1380, 1720, 2010, 2290)),
                  duration=random.uniform(0.012, 0.019))

    # Soft page/trackpad-like movement as the reel moves from problem to explanation.
    soft_brush(left, right, 5.92, duration=0.34, amp=0.014, pan=0.43)
    soft_brush(left, right, 9.30, duration=0.46, amp=0.019, pan=0.57)

    peak = max(max(map(abs, left)), max(map(abs, right)), 1e-9)
    gain = 0.48 / peak
    pcm = array("h")
    for i, (l, r) in enumerate(zip(left, right)):
        fade = min(1.0, i / (0.05 * SR), (n - i) / (0.32 * SR))
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
