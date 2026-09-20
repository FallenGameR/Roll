# -*- coding: utf-8 -*-
"""Считает провалы звука на выходе звуковой карты.

Критерий один и надёжный: участок почти полной тишины посреди
звучащей музыки. Такое бывает только при выпавшем буфере, поэтому
эталонный файл не нужен, а на контроле (нативный плеер вроде
`ffplay -nodisp <файл>`) детектор даёт ровно ноль.

Чего делать НЕ надо (проверено, оба способа врут):

* считать провалом любое тихое место записи — тихий эмбиент выдаёт
  десятки ложных «срывов»;
* сравнивать запись с огибающей исходного файла — на ритмичном
  материале выравнивание находит ложный максимум, и ложные срывы
  сыплются даже у нативного плеера.

Использование:
    python loopback-dropouts.py [сколько замеров] [секунд на замер]

Нужен пакет soundcard: pip install soundcard
"""
import sys
import time
import warnings

import numpy as np
import soundcard as sc

warnings.filterwarnings("ignore")

RATE = 48000
WIN = RATE // 500          # окна по 2 мс: провалы короткие


def record(seconds):
    speaker = sc.default_speaker()
    mic = sc.get_microphone(speaker.id, include_loopback=True)
    started = time.perf_counter()
    with mic.recorder(samplerate=RATE, channels=2, blocksize=1024) as rec:
        data = rec.record(numframes=RATE * seconds)
    return data.mean(axis=1), time.perf_counter() - started


def holes(data):
    frames = data[: len(data) // WIN * WIN].reshape(-1, WIN)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-12)
    top = db.max()

    # Провал: падение больше чем на 45 дБ от общего уровня, окружённое
    # звуком с обеих сторон. Музыкальная пауза так не выглядит: у неё
    # нет громкого звука сразу с двух сторон в пределах двадцати
    # миллисекунд.
    loud = db > top - 20
    quiet = db < top - 45
    found = []
    for i in range(2, len(db) - 2):
        if quiet[i] and loud[max(0, i - 10):i].any() \
                and loud[i + 1:i + 11].any():
            found.append(round(i * WIN / RATE, 3))
    return found, float(top)


def measure(seconds=3):
    data, elapsed = record(seconds)
    peak = np.abs(data).max()
    if peak < 1e-4:
        return {"ошибка": "на выходе тишина"}
    if elapsed - seconds > 0.15:
        return {"ошибка": f"запись отстала на {elapsed - seconds:.2f} с"}

    found, _top = holes(data)
    # Соседние окна одного провала считаем за один разрыв.
    breaks, last = 0, -1.0
    for t in found:
        if t - last > 0.02:
            breaks += 1
        last = t
    return {"разрывов": breaks,
            "тишины_мс": round(len(found) * WIN * 1000 / RATE, 1),
            "первые_с": found[:5],
            "пик_dBFS": round(float(20 * np.log10(peak)), 1)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rounds = int(args[0]) if args else 6
    seconds = int(args[1]) if len(args) > 1 else 3

    if "--wait" in sys.argv:
        print("жду, когда появится звук (до 60 секунд)...")
        for _ in range(60):
            data, _elapsed = record(1)
            if np.abs(data).max() > 1e-3:
                print("звук пошёл, меряю")
                break
        else:
            print("звука так и не было")
            return

    for i in range(rounds):
        print(i + 1, measure(seconds))
        time.sleep(1)


if __name__ == "__main__":
    main()
