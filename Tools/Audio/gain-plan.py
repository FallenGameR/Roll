"""Строит план выравнивания громкости библиотеки до -15.4 LUFS.

Использование:
    python gain-plan.py <замеры.json> <план.csv>

На вход идёт результат loudness.py (массив объектов с полями lufs и
true_peak_db), на выходе — CSV, где у каждого трека проставлено, что с
ним делать:

  skip     — уже в пределах половины шага от цели, трогать нечего;
  lossless — правка поля global_gain через mp3rgain, без перекодирования;
  reencode — lossless-путь не дотягивает больше чем на шаг, догнать
             может только loudnorm с лимитером.

Уровень -15.4 LUFS взят не с потолка: это громкость трека
`Assassins Creed 3 - What Came Before` до всякой обработки — уровень,
названный комфортным на практике.

Про округление. Величина сдвига считается шагами по 1.5 дБ, и два
ограничения округляются по-разному:

  * по запасу до потолка — ВНИЗ (int), иначе трек уйдёт в клиппинг;
  * по потребности — К БЛИЖАЙШЕМУ (round), иначе трек систематически
    недобирает до цели. На этом уже погорели: округление вниз по обоим
    ограничениям увело медиану библиотеки на 0.6 дБ ниже цели и
    потребовало второго прохода по 417 трекам.

Треки, которые клиппируют уже в исходнике (пик выше 0 dBFS), поднимать
нельзя — запаса нет, и если они при этом заметно отстают от цели, их
догоняет loudnorm со своим лимитером. А вот ослаблять их можно и нужно:
тише — всегда безопасно, и клиппирование заодно уходит.
"""
import csv
import json
import sys
from pathlib import Path

TARGET = -15.4
PEAK_CEILING = -1.0
STEP = 1.5
# Насколько трек может отстать от цели, прежде чем его стоит догонять
# перекодированием. Один шаг правки — естественный порог.
LAG_LIMIT = 1.5


def plan_track(lufs, peak):
    """Возвращает (действие, шагов, примечание) для одного трека."""
    need = TARGET - lufs

    if abs(need) < STEP / 2:
        return "skip", 0, ""

    if need < 0:
        # Ослабление ничем не ограничено: тише — всегда безопасно.
        return "lossless", round(need / STEP), ""

    peak_room = PEAK_CEILING - peak
    steps = min(round(need / STEP), int(peak_room / STEP))

    if steps <= 0:
        # Даже один шаг не влезает по пику.
        if need > LAG_LIMIT:
            return "reencode", 0, f"запаса по пику нет, отстаёт на {need:.1f}"
        return "skip", 0, "запаса по пику нет"

    reached = lufs + steps * STEP
    if TARGET - reached > LAG_LIMIT:
        return "reencode", 0, f"lossless дотянет только до {reached:.1f}"

    return "lossless", steps, ""


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)

    measurements = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    rows = []
    counts = {"skip": 0, "lossless": 0, "reencode": 0}

    for r in sorted(measurements, key=lambda r: r.get("path", "")):
        if r.get("lufs") is None:
            continue
        action, steps, note = plan_track(r["lufs"], r["true_peak_db"])
        counts[action] += 1
        rows.append({
            "Action": action,
            "Steps": steps,
            "GainDb": round(steps * STEP, 1),
            "NeedDb": round(TARGET - r["lufs"], 1),
            "CurrentLufs": r["lufs"],
            "PeakDb": r["true_peak_db"],
            "Note": note,
            "Name": r["name"],
            "Path": r["path"],
        })

    if not rows:
        print("во входном файле нет пригодных замеров")
        raise SystemExit(1)

    out = Path(sys.argv[2])
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"цель {TARGET} LUFS, треков {len(rows)}")
    for k, v in counts.items():
        print(f"  {k:9s}: {v:5d}")

    ls = [r for r in rows if r["Action"] == "lossless"]
    up = sum(1 for r in ls if r["Steps"] > 0)
    print(f"  из lossless: подъём {up}, ослабление {len(ls) - up}")
    print(f"план: {out}")


if __name__ == "__main__":
    main()
