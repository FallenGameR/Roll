"""Измеряет объективные акустические характеристики треков.

Нужно, чтобы утверждения вида «тяжёлые барабаны» или «почти без
перкуссии» опирались на измерение файла, а не на память. Веб-источники
дают контекст (где играет в игре), а этот скрипт — факты о самом звуке.

Считаем:
  * длительность и громкость (RMS), разброс громкости по времени;
  * динамику: отношение громкости пиковых и тихих участков — у ровного
    фона она мала, у трека с нарастанием велика;
  * спектральный баланс по полосам (низ/середина/верх) и центроид —
    грубый признак «тёмный гул» против «яркие струнные»;
  * частоту резких атак (onset rate) — прокси для наличия ударных и
    ритмической плотности;
  * долю энергии в диапазоне 200-1000 Гц, где живёт человеческий голос,
    вместе с оценкой стабильности гармоник — намёк на вокал.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FFMPEG = next(
    Path(r"C:\Users\alexk\AppData\Local\Microsoft\WinGet\Packages").glob(
        "Gyan.FFmpeg_*/**/ffmpeg.exe"
    )
)

SR = 22050
FRAME = 1024
HOP = 512


def decode(path):
    raw = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-map", "0:a",
         "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def frames(x):
    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    return x[idx] * np.hanning(FRAME)


def analyse(path):
    x = decode(path)
    if len(x) < SR:
        return None
    fr = frames(x)
    spec = np.abs(np.fft.rfft(fr, axis=1))
    freqs = np.fft.rfftfreq(FRAME, 1 / SR)

    rms = np.sqrt((fr ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    loud = float(np.percentile(db, 95))
    quiet = float(np.percentile(db, 10))

    total = spec.sum(axis=1) + 1e-9
    def band(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        return float((spec[:, m].sum(axis=1) / total).mean())

    centroid = float((spec * freqs[None, :]).sum(axis=1).mean() /
                     (spec.sum(axis=1).mean() + 1e-9))

    # Onset rate: считаем резкие приросты энергии — прокси для ударов.
    flux = np.diff(spec, axis=0)
    flux[flux < 0] = 0
    novelty = flux.sum(axis=1)
    novelty /= novelty.max() + 1e-9
    thresh = np.percentile(novelty, 90)
    peaks = 0
    last = -10
    for i, v in enumerate(novelty):
        if v > thresh and i - last > 4:
            peaks += 1
            last = i
    seconds = len(x) / SR
    onset_rate = peaks / seconds * 60  # событий в минуту

    return {
        "seconds": round(seconds, 1),
        "loud_db": round(loud, 1),
        "quiet_db": round(quiet, 1),
        "dynamic_range_db": round(loud - quiet, 1),
        "low_0_250": round(band(0, 250), 3),
        "mid_250_2k": round(band(250, 2000), 3),
        "high_2k_plus": round(band(2000, SR / 2), 3),
        "voice_200_1k": round(band(200, 1000), 3),
        "centroid_hz": round(centroid),
        "onsets_per_min": round(onset_rate),
    }


def main():
    paths = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = []
    for p in paths:
        path = Path(p)
        res = analyse(path)
        if res is None:
            continue
        res["name"] = path.stem
        out.append(res)
        print(f"{res['seconds']:6.1f}s  dyn {res['dynamic_range_db']:5.1f}dB  "
              f"onsets/min {res['onsets_per_min']:4d}  "
              f"low {res['low_0_250']:.2f} mid {res['mid_250_2k']:.2f} "
              f"high {res['high_2k_plus']:.2f}  cent {res['centroid_hz']:5d}Hz  "
              f"{path.stem}", flush=True)
    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                 encoding="utf-8")


if __name__ == "__main__":
    main()
