# -*- coding: utf-8 -*-
"""Выравнивает КОРОТКИЕ эффекты по мгновенной громкости (momentary max).

Интегральный замер EBU R128 рассчитан на музыкальный трек: на файле в
пять секунд, где половина времени тишина, gating занижает результат, и
трек, формально стоящий на -15.4 LUFS, звучит заметно тише соседей.
Для разовых звуков (рык, лай, обвал) слушатель судит по громкости
самого события, поэтому цель здесь — момент, а не интеграл.

Порог 60 секунд отделяет разовые эффекты от петель: петли остаются на
интегральной шкале.
"""
import json
import re
import os
import subprocess
import sys
from pathlib import Path

FFMPEG = next(
    Path(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages").glob(
        "Gyan.FFmpeg_*/**/ffmpeg.exe"))
FFPROBE = next(
    Path(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages").glob(
        "Gyan.FFmpeg_*/**/ffprobe.exe"))
MP3RGAIN = next(
    Path(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages").glob(
        "**/mp3rgain.exe"))

TARGET_M = -11.0      # медиана momentary max по папке эффектов
MAX_SECONDS = 150     # что считаем разовым эффектом, а не петлёй
TOLERANCE = 2.0       # ниже этого перекодировать ради громкости не стоит


def probe(path):
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout
    return float(out.strip())


def momentary_max(path):
    raw = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace").stderr
    vals = [float(v) for v in re.findall(r"M:\s*(-?\d+\.\d+)", raw)]
    vals = [v for v in vals if v > -70]
    return max(vals) if vals else None


def main():
    folder = Path(sys.argv[1])
    apply = "--apply" in sys.argv

    for path in sorted(folder.glob("*.mp3")):
        seconds = probe(path)
        if seconds > MAX_SECONDS:
            continue

        m = momentary_max(path)
        gain = TARGET_M - m
        if abs(gain) < TOLERANCE:
            print(f"  ok   {m:6.1f} -> оставлено  {path.stem}")
            continue

        if not apply:
            print(f"  plan {m:6.1f} {gain:+5.1f} дБ  {path.stem}")
            continue

        tmp = path.with_suffix(".gain.mp3")
        if gain < 0:
            # Ослабление правится в самих фреймах, без перекодирования.
            steps = round(gain / 1.5)
            subprocess.run([str(MP3RGAIN), "-g", str(steps), "-p", "-q",
                            str(path)], check=True,
                           stdout=subprocess.DEVNULL)
            print(f"  fix  {m:6.1f} {steps * 1.5:+5.1f} дБ lossless -> "
                  f"{momentary_max(path):6.1f}  {path.stem}")
            continue

        # Подъём: лимитер обязателен, у разовых звуков пик уже у потолка.
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-i", str(path),
             "-map", "0", "-map_metadata", "0", "-c:v", "copy",
             "-af", f"volume={gain}dB,alimiter=limit=0.891",
             "-c:a", "libmp3lame", "-q:a", "0", str(tmp)], check=True)
        path.unlink()
        tmp.rename(path)
        print(f"  fix  {m:6.1f} {gain:+5.1f} дБ -> {momentary_max(path):6.1f}"
              f"  {path.stem}")


if __name__ == "__main__":
    main()
