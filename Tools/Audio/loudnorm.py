"""Поднимает громкость тихих треков перекодированием (ffmpeg loudnorm).

Нужно там, где lossless-путь закрыт: поле global_gain в MP3 упирается в
255, и увеличить громкость правкой фреймов физически нельзя.

Работает в два прохода: первый измеряет трек, второй применяет
нормализацию с уже известными параметрами — так loudnorm попадает в
цель точно, а не приблизительно. Встроенный лимитер держит истинный пик
под -1 dBTP, поэтому трекам без запаса по амплитуде отдельная обработка
не нужна.

Битрейт берётся из исходника, чтобы не терять качество сверх
неизбежного. Обложка и все ID3-теги переносятся.
"""
import json
import subprocess
import sys
from pathlib import Path

FFMPEG = next(
    Path(r"C:\Users\alexk\AppData\Local\Microsoft\WinGet\Packages").glob(
        "Gyan.FFmpeg_*/**/ffmpeg.exe"
    )
)
FFPROBE = FFMPEG.parent / "ffprobe.exe"

TARGET_I = -15.4
TARGET_TP = -1.0
TARGET_LRA = 20.0  # широко: сжимать динамику музыки не хотим


def bitrate_kbps(path):
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=bit_rate", "-of", "default=nw=1:nk=1", "--", str(path)],
        capture_output=True,
    ).stdout.decode().strip()
    try:
        kbps = int(int(out) / 1000)
    except (ValueError, TypeError):
        kbps = 0
    return max(128, min(320, kbps)) if kbps else 224


def analyse(path):
    """Первый проход: снимаем параметры для точной нормализации."""
    proc = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a",
         "-af", f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
         "-f", "null", "-"],
        capture_output=True,
    )
    text = proc.stderr.decode("utf-8", "replace")
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def normalise(path, stats, apply=False):
    kbps = bitrate_kbps(path)
    tmp = path.with_suffix(".loudnorm-tmp.mp3")
    flt = (
        f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}"
        f":measured_I={stats['input_i']}"
        f":measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}"
        ":linear=true:print_format=summary"
    )
    if not apply:
        return kbps, None

    proc = subprocess.run(
        [str(FFMPEG), "-y", "-v", "error", "-i", str(path),
         "-map", "0:a", "-map", "0:v?", "-map_metadata", "0",
         "-af", flt, "-c:a", "libmp3lame", "-b:a", f"{kbps}k",
         "-c:v", "copy", "-id3v2_version", "3", "--", str(tmp)],
        capture_output=True,
    )
    if proc.returncode != 0 or not tmp.exists():
        if tmp.exists():
            tmp.unlink()
        return kbps, proc.stderr.decode("utf-8", "replace")[-300:]

    # Обложка приезжает отдельным потоком; если её не было, ffmpeg просто
    # пропустит -map 0:v? и файл соберётся без неё.
    path.write_bytes(tmp.read_bytes())
    tmp.unlink()
    return kbps, None


def main():
    paths = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    apply = "--apply" in sys.argv
    report = []

    for i, p in enumerate(paths, 1):
        path = Path(p)
        stats = analyse(path)
        if stats is None:
            print(f"НЕ ИЗМЕРЕН: {path.name}", flush=True)
            continue

        kbps, err = normalise(path, stats, apply)
        rec = {
            "name": path.stem,
            "path": str(path),
            "input_i": float(stats["input_i"]),
            "output_i": float(stats["output_i"]),
            "input_tp": float(stats["input_tp"]),
            "bitrate": kbps,
            "error": err,
        }
        report.append(rec)
        mark = "ПРИМЕНЕНО" if apply and not err else ("ОШИБКА" if err else "проба")
        print(f"{rec['input_i']:7.1f} -> {rec['output_i']:6.1f} LUFS  "
              f"{kbps:3d}k  {mark}  {path.stem[:50]}", flush=True)

        if i % 20 == 0:
            Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                         encoding="utf-8")

    Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    bad = [r for r in report if r["error"]]
    print(f"готово: {len(report)} | ошибок: {len(bad)}")


if __name__ == "__main__":
    main()
