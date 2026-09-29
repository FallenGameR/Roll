"""Ищет одинаковый музыкальный материал среди файлов папки.

Зачем. В библиотеке оказались две подборки одной игры: чистые треки с
названиями и рипы с игрового процесса, названные по локациям. На слух
пары очевидны не всегда, а имена не совпадают вовсе.

Как. ffmpeg декодирует кусок файла в моно 8 кГц, из него собирается
16-полосная лог-спектрограмма - тот же признак, что в loop-trim.py.
Дальше нормированная кросс-корреляция двух признаков по всем сдвигам:
у одной и той же записи пик близок к единице даже при разной обрезке
начала и поверх игрового шума.

    python compare-audio.py <папка> [<папка> ...] [--threshold 0.5]
"""
import argparse
import itertools
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 8000
WIN = 1024
HOP = 400          # 20 кадров в секунду
BANDS = 16
SECONDS = 150

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def decode(path, seconds=SECONDS):
    cmd = [os.environ.get("FFMPEG", "ffmpeg"), "-v", "error", "-i", str(path),
           "-t", str(seconds), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def features(x):
    n = (len(x) - WIN) // HOP
    if n < 2:
        return np.zeros((BANDS, 0))
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(WIN)[None, :]
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    edges = np.unique(np.geomspace(1, spec.shape[1] - 1, BANDS + 1).astype(int))
    cols = [spec[:, edges[i]:edges[i + 1]].mean(axis=1) for i in range(len(edges) - 1)]
    f = np.log10(np.stack(cols, axis=0) + 1e-10)
    f -= f.mean(axis=1, keepdims=True)
    norm = np.sqrt((f ** 2).sum(axis=1, keepdims=True))
    norm[norm == 0] = 1.0
    return f / norm


def best_match(a, b):
    """Максимум нормированной кросс-корреляции и сдвиг в секундах."""
    m = max(a.shape[1], b.shape[1])
    n = 1 << (2 * m - 1).bit_length()
    fa = np.fft.rfft(a, n, axis=1)
    fb = np.fft.rfft(b, n, axis=1)
    cc = np.fft.irfft(fa * np.conj(fb), n, axis=1).sum(axis=0)
    cc = np.concatenate([cc[-(m - 1):], cc[:m]])
    top = int(cc.argmax())
    return float(cc[top] / BANDS), (top - (m - 1)) / (SR / HOP)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         stdout=subprocess.PIPE, text=True, check=True).stdout
    return float(out.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--threshold", type=float, default=0.45)
    args = ap.parse_args()

    files = []
    for folder in args.folders:
        files.extend(sorted(Path(folder).glob("*.mp3")))
    print(f"файлов: {len(files)}", flush=True)

    prints = {}
    for path in files:
        prints[path] = (features(decode(path)), duration(path))
        print(".", end="", flush=True)
    print()

    rows = []
    for one, two in itertools.combinations(files, 2):
        score, shift = best_match(prints[one][0], prints[two][0])
        if score >= args.threshold:
            rows.append((score, shift, one, two))

    rows.sort(reverse=True, key=lambda r: r[0])
    print(f"\nпар выше {args.threshold}: {len(rows)}\n")
    for score, shift, one, two in rows:
        d1, d2 = prints[one][1], prints[two][1]
        print(f"{score:.3f}  сдвиг {shift:+.1f} с")
        print(f"    {one.name}   [{d1:.0f} с]")
        print(f"    {two.name}   [{d2:.0f} с]")


if __name__ == "__main__":
    main()
