"""Regenerate apps/merchant_app/assets/sounds/new_order.wav.

    python3 design/make_alert_sound.py

A WAV rather than an MP3 because there is no encoder in the build container, and
because 76KB inside an APK is not worth a dependency. Mono, 22.05kHz, 16-bit.

Shaped rather than a raw beep. A square wave at full volume through a phone
speaker is unpleasant enough that somebody turns the feature off, which defeats
the point of having it. Two notes with an attack and a decay so it reads as a
doorbell, then a second of silence so the loop sounds like a repeated chime
rather than a siren - this plays until the merchant taps the dialog, and the
difference between "noticeable" and "intolerable" is mostly that gap.
"""

import math
import struct
import wave
from pathlib import Path

RATE = 22050
OUT = Path(__file__).resolve().parent.parent / "apps/merchant_app/assets/sounds/new_order.wav"


def tone(freq: float, seconds: float, amp: float = 0.55) -> list[float]:
    n = int(RATE * seconds)
    attack, release = int(n * 0.04), int(n * 0.45)
    out = []
    for i in range(n):
        if i < attack:
            env = i / attack
        elif i > n - release:
            env = (n - i) / release
        else:
            env = 1.0
        # A touch of second harmonic: a pure sine reads as a test tone rather
        # than a chime somebody recognises across a counter.
        s = math.sin(2 * math.pi * freq * i / RATE)
        s += 0.3 * math.sin(4 * math.pi * freq * i / RATE)
        out.append(amp * env * s / 1.3)
    return out


def silence(seconds: float) -> list[float]:
    return [0.0] * int(RATE * seconds)


def main() -> None:
    samples = tone(880, 0.26) + silence(0.06) + tone(1175, 0.34) + silence(1.1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(
            b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples)
        )
    print(f"  {OUT.relative_to(Path.cwd())}: {len(samples) / RATE:.2f}s")


if __name__ == "__main__":
    main()
