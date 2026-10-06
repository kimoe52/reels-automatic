"""Quiet, no-music foley for the Jev Reel: taps, short typing, and a paper/marker brush."""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v6/assets/jev-foley-v6.wav"
SR = 44_100
DURATION = 15.0


def add_click(left, right, start, amp=0.10, pan=0.5, dur=0.028, tone=2050):
    i0 = int(start * SR)
    n = int(dur * SR)
    lg, rg = math.sqrt(1-pan), math.sqrt(pan)
    phase = random.random() * math.tau
    for j in range(n):
        i = i0+j
        if i >= len(left):
            break
        t = j/SR
        env = math.exp(-t * 92)
        v = amp * env * (0.66*random.uniform(-1,1) + 0.36*math.sin(math.tau*tone*t+phase))
        left[i] += v*lg
        right[i] += v*rg


def add_brush(left, right, start, dur=0.42, amp=0.032, pan=0.5):
    i0 = int(start*SR)
    n = int(dur*SR)
    lg, rg = math.sqrt(1-pan), math.sqrt(pan)
    prev = 0.0
    for j in range(n):
        i=i0+j
        if i>=len(left): break
        t=j/SR
        # Slow, soft envelope with correlated noise; suggests paper/marker, not a synth sweep.
        raw=random.uniform(-1,1)
        noise=0.70*prev+0.30*raw
        prev=noise
        edge=min(1.0,t/0.035,(dur-t)/0.045)
        flutter=0.82+0.18*math.sin(math.tau*7.0*t)
        v=amp*max(0,edge)*flutter*noise
        left[i]+=v*lg
        right[i]+=v*rg


def main():
    random.seed(623)
    n=int(SR*DURATION)
    left=[0.0]*n
    right=[0.0]*n

    # A soft error/click, then restrained close-mic keyboard clusters. No melody or voice.
    for stamp, amp, pan in ((0.12,0.17,0.42),(0.20,0.13,0.57),(3.02,0.14,0.55),
                            (6.52,0.15,0.46),(11.02,0.16,0.54),
                            (14.60,0.14,0.55)):
        add_click(left,right,stamp,amp=amp,pan=pan)

    clusters=((0.42,2.25,18),(3.22,3.90,6),(6.72,7.40,5),(11.25,11.95,6),(13.30,14.10,4))
    for start,end,count in clusters:
        stamps=sorted(random.uniform(start,end) for _ in range(count))
        for stamp in stamps:
            add_click(left,right,stamp,amp=random.uniform(0.045,0.072),
                      pan=random.uniform(0.33,0.67),dur=random.uniform(0.014,0.026),
                      tone=random.choice((1450,1760,2180,2440)))

    # Paper brush at editorial reveal and a short marker-like draw on the flow diagram.
    add_brush(left,right,5.84,dur=0.34,amp=0.024,pan=0.46)
    add_brush(left,right,9.55,dur=0.52,amp=0.031,pan=0.55)

    peak=max(max(map(abs,left)),max(map(abs,right)),1e-9)
    gain=0.58/peak
    pcm=array("h")
    for i,(l,r) in enumerate(zip(left,right)):
        fade=min(1.0,i/(0.04*SR),(n-i)/(0.25*SR))
        pcm.append(int(max(-1,min(1,l*gain*fade))*32767))
        pcm.append(int(max(-1,min(1,r*gain*fade))*32767))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(OUT),"wb") as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR); f.writeframes(pcm.tobytes())
    print(OUT)


if __name__ == "__main__":
    main()
