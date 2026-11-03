"""Измеряет громкость треков по стандарту EBU R128 (LUFS).

Пиковые значения из acoustics.py показывают, насколько трек громкий в
максимуме, а воспринимаемую громкость они описывают плохо: тихий, но
плотный эмбиент и динамичная оркестровка с редкими всплесками могут
иметь одинаковый пик и совершенно разную слышимую громкость.

LUFS (integrated loudness) учитывает частотную чувствительность слуха и
усредняет по времени — это то, что и нужно, чтобы Мастер не крутил
регулятор при смене трека.

Дополнительно снимаем true peak: он показывает, есть ли запас, чтобы
поднять громкость без клиппинга.
"""
import json
import re
import os
import subprocess
import sys
from pathlib import Path

FFMPEG = next(
    Path(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages").glob(
        "Gyan.FFmpeg_*/**/ffmpeg.exe"
    )
)

# ffmpeg печатает сводку ebur128 в stderr в конце прогона.
SUMMARY = re.compile(
    r"I:\s*(-?[\d.]+|-inf)\s*LUFS.*?"
    r"LRA:\s*([\d.]+|-inf)\s*LU.*?"
    r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS",
    re.S,
)


def measure(path):
    proc = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-nostats", "-i", str(path),
         "-map", "0:a", "-af", "ebur128=peak=true:framelog=quiet",
         "-f", "null", "-"],
        capture_output=True,
    )
    text = proc.stderr.decode("utf-8", "replace")
    tail = text[-1500:]
    m = SUMMARY.search(tail)
    if not m:
        return None
    return {
        "lufs": float(m.group(1)) if m.group(1) != "-inf" else None,
        "lra": float(m.group(2)) if m.group(2) != "-inf" else None,
        "true_peak_db": float(m.group(3)) if m.group(3) != "-inf" else None,
    }


def main():
    paths = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = []
    for i, p in enumerate(paths, 1):
        path = Path(p)
        res = measure(path)
        if res is None:
            print(f"НЕ ИЗМЕРЕН: {path.name}", flush=True)
            continue
        res["name"] = path.stem
        res["folder"] = path.parent.name
        res["path"] = str(path)
        out.append(res)
        print(f"{res['lufs']:7.1f} LUFS  LRA {res['lra']:5.1f}  "
              f"peak {res['true_peak_db']:6.1f} dBFS  {path.stem}", flush=True)
        if i % 50 == 0:
            Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                 encoding="utf-8")


if __name__ == "__main__":
    main()
