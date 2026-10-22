"""Genera las campanitas de aviso (WAV) con síntesis aditiva.

Uso: python3 scripts/generate_chimes.py <directorio_salida>
Después se convierten a MP3 con ffmpeg (ver README del repositorio).
Los sonidos son originales y se publican con la misma licencia (MIT).
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import wave

RATE = 44100
LEAD_IN = 0.3  # silencio inicial: algunos altavoces Cast recortan el arranque

# Parciales de una campana: (relación de frecuencia, amplitud, caída en s^-1)
BELL = ((1.0, 1.0, 3.0), (2.0, 0.45, 4.5), (2.76, 0.25, 6.0), (5.4, 0.1, 9.0))
SOFT = ((1.0, 1.0, 4.0), (2.0, 0.2, 7.0), (3.0, 0.08, 10.0))


def tone(
    freq: float, start: float, length: float, partials=BELL, gain: float = 1.0
) -> list[tuple[int, float]]:
    """Muestras (índice, valor) de una nota con ataque corto y caída exponencial."""
    first = int((LEAD_IN + start) * RATE)
    out = []
    for n in range(int(length * RATE)):
        t = n / RATE
        attack = min(1.0, t / 0.005)
        value = sum(
            amp * math.exp(-decay * t) * math.sin(2 * math.pi * freq * ratio * t)
            for ratio, amp, decay in partials
        )
        out.append((first + n, gain * attack * value))
    return out


def render(notes: list[list[tuple[int, float]]], path: Path) -> None:
    """Mezcla las notas, normaliza a -3 dBFS y guarda WAV mono 16 bits."""
    total = max(i for note in notes for i, _ in note) + int(0.2 * RATE)
    buf = [0.0] * total
    for note in notes:
        for i, v in note:
            buf[i] += v
    peak = max(abs(v) for v in buf) or 1.0
    scale = 0.7 / peak
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(v * scale * 32767)) for v in buf))


C5, E5, G5, C6, A5 = 523.25, 659.25, 783.99, 1046.5, 880.0

CHIMES = {
    # Una campana suave.
    "ding": [tone(E5, 0, 1.8)],
    # Timbre clásico de dos notas.
    "ding_dong": [tone(E5, 0, 1.4), tone(C5, 0.55, 1.8)],
    # Arpegio ascendente, estilo asistente.
    "aviso": [
        tone(C5, 0.0, 1.2, SOFT, 0.8),
        tone(E5, 0.11, 1.2, SOFT, 0.8),
        tone(G5, 0.22, 1.2, SOFT, 0.8),
        tone(C6, 0.33, 1.5, SOFT, 0.9),
    ],
    # Tres pitidos rápidos y claros, para alertas.
    "alerta": [tone(A5, k * 0.22, 0.18, SOFT) for k in range(3)]
    + [tone(A5, 0.9 + k * 0.22, 0.18, SOFT) for k in range(3)],
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, notes in CHIMES.items():
        render(notes, out / f"{name}.wav")
        print("ok", name)
