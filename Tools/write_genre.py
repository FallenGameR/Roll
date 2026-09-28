"""Переписывает тег genre в mp3, не трогая ни звук, ни остальные теги.

Раньше это делал ffmpeg: он пересобирал файл во временную копию и подменял
оригинал. Работало всюду, кроме единственного места, где нужнее всего, - на
треке, который звучит прямо сейчас. Winamp держит открытым то, что играет, и
подмена срывается невнятным "Cannot create a file when that file already
exists".

Оказалось, плеер запрещает не запись в файл, а именно его замену: открыть mp3
на запись он даёт. Поэтому тег правится на месте, поверх существующего
ID3-блока. Обложка, комментарий и звук остаются как были, а тегировать можно не
закрывая плеер.

    python write_genre.py "<файл>" "<строка genre>"
    python write_genre.py --batch      # список {"path","genre"} из stdin

Версия ID3 сохраняется та же, что была у файла: библиотека собиралась годами,
и незаметная смена 2.3 на 2.4 для половины треков - не та плата, которой стоит
оплачивать правку одного поля.
"""

import json
import sys

from mutagen.id3 import ID3, TCON
from mutagen.id3._util import ID3NoHeaderError


def write(path, genre):
    try:
        tags = ID3(path)
        version = 4 if tags.version[1] >= 4 else 3
    except ID3NoHeaderError:
        tags, version = ID3(), 3
    if genre:
        tags.setall("TCON", [TCON(encoding=3, text=[genre])])
    else:
        tags.delall("TCON")
    tags.save(path, v2_version=version)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--batch" in sys.argv:
        items = json.load(sys.stdin)
        failed = 0
        for item in items:
            try:
                write(item["path"], item.get("genre", ""))
            except Exception as exc:  # noqa: BLE001 - остальные файлы не виноваты
                failed += 1
                print(f"!! {item['path']}: {exc}")
        print(f"записано {len(items) - failed} из {len(items)}")
        sys.exit(1 if failed else 0)

    if len(sys.argv) < 2:
        print("нужен путь к файлу", file=sys.stderr)
        sys.exit(2)
    write(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")


if __name__ == "__main__":
    main()
