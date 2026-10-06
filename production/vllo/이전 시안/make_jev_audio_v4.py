"""Create a short, license-safe instrumental loop and UI hits for the Jev Reel."""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "media/audio/jev-loop-v4.wav"
SR = 44_100
DURATION = 16.0


def add_note(buf, start, length, freq, amp=0.11):
    start_i = int(start * SR)
    end_i = min(len(buf), int((start + length) * SR))
    for i in range(start_i, end_i):
        t = (i - start_i) / SR
        env = min(1.0, t / 0.012) * math.exp(-2.7 * t / length)
        # A clean, slightly digital pluck: the sped-up loop stays behind captions.
        wavev = math.sin(2 * math.pi * freq * t) + 0.28 * math.sin(2 * math.pi * freq * 2 * t)
        buf[i] += amp * env * wavev


def add_click(buf, start, amp=0.20):
    start_i = int(start * SR)
    length = int(0.045 * SR)
    for j in range(length):
        i = start_i + j
        if i >= len(buf):
            break
        t = j / SR
        noise = random.uniform(-1.0, 1.0)
        tone = math.sin(2 * math.pi * 2600 * t)
        buf[i] += amp * (0.58 * noise + 0.42 * tone) * math.exp(-75 * t)


def add_impact(buf, start, amp=0.22):
    start_i = int(start * SR)
    length = int(0.28 * SR)
    for j in range(length):
        i = start_i + j
        if i >= len(buf):
            break
        t = j / SR
        buf[i] += amp * math.sin(2 * math.pi * (90 - 35 * t) * t) * math.exp(-12 * t)


def main():
    random.seed(23)
    n = int(SR * DURATION)
    left = [0.0] * n
    right = [0.0] * n
    bpm = 138
    step = 60.0 / bpm / 2.0
    notes = [220.0, 277.18, 329.63, 369.99, 329.63, 277.18, 246.94, 329.63]

    # Repeating arpeggio, intentionally brighter/faster than a narration bed.
    t = 0.0
    k = 0
    while t < DURATION:
        freq = notes[k % len(notes)]
        add_note(left, t, step * 1.25, freq, amp=0.10)
        add_note(right, t + 0.007, step * 1.25, freq * 1.002, amp=0.10)
        # Quiet low pulse every other beat.
        if k % 4 == 0:
            add_note(left, t, step * 2.2, freq / 2, amp=0.035)
            add_note(right, t + 0.01, step * 2.2, freq / 2, amp=0.035)
        t += step
        k += 1

    # UI transitions: click on proof screens, low thump at scene changes.
    for stamp in (0.05, 2.62, 5.42, 8.32, 12.34, 14.65):
        add_click(left, stamp, 0.16)
        add_click(right, stamp + 0.008, 0.16)
    for stamp in (0.05, 5.42, 8.32, 12.34):
        add_impact(left, stamp, 0.14)
        add_impact(right, stamp + 0.012, 0.14)

    # Gentle fade in/out and safe peak.
    peak = max(max(abs(v) for v in left), max(abs(v) for v in right), 1e-9)
    gain = 0.72 / peak
    pcm = array("h")
    for i in range(n):
        fade = min(1.0, i / (0.08 * SR), (n - i) / (0.18 * SR))
        pcm.append(int(max(-1.0, min(1.0, left[i] * gain * fade)) * 32767))
        pcm.append(int(max(-1.0, min(1.0, right[i] * gain * fade)) * 32767))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    print(OUT)


if __name__ == "__main__":
    main()
