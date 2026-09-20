# -*- coding: utf-8 -*-
"""Читает рейтинги треков из базы медиатеки Winamp.

Winamp не пишет звёзды в теги файлов — они лежат в его собственной базе
(Nullsoft Database Engine): main.idx содержит смещения записей,
main.dat — сами записи в виде связанных списков полей.

Формат полей по спецификации NDE 1.0:

    0  UCHAR  id записи столбца
    1  UCHAR  тип поля
    2  INT    размер данных
    6  INT    смещение следующего поля
    10 INT    смещение предыдущего поля
    14 данные

Нулевая запись описывает столбцы, из неё и берутся номера `filename` и
`rating`, чтобы не зашивать их числами: у разных версий они разные.

База сохраняется только при штатном выходе из плеера, поэтому перед
чтением Winamp надо закрыть по-человечески, а не убивать процесс.
"""
import os
import struct
import sys
from pathlib import Path

ML = Path(os.environ["APPDATA"]) / r"Winamp\Plugins\ml"

FIELD_COLUMN = 0
FIELD_STRING = 3
FIELD_INTEGER = 4
FIELD_REDIRECTOR = 2
# У имени файла свой строковый тип: в Winamp 5.9 он 12, а не 3, как в
# спецификации первой версии.
FIELD_FILENAME = 12
STRING_TYPES = (FIELD_STRING, FIELD_FILENAME)


def read_field(data, offset):
    if offset + 14 > len(data):
        return None
    column, kind = data[offset], data[offset + 1]
    size, nxt, _prev = struct.unpack_from("<III", data, offset + 2)
    payload = data[offset + 14:offset + 14 + size]
    return {"column": column, "type": kind, "next": nxt, "data": payload}


def decode_string(payload):
    if len(payload) < 2:
        return ""
    length = struct.unpack_from("<H", payload, 0)[0]
    raw = payload[2:2 + length]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace").lstrip("\ufeff")
    return raw.decode("utf-8", errors="replace")


def read_columns(data):
    """Номер столбца -> имя, из нулевой записи таблицы."""
    columns = {}
    offset = 8                      # сразу за подписью NDETABLE
    while True:
        field = read_field(data, offset)
        if not field:
            break
        if field["type"] == FIELD_COLUMN and len(field["data"]) >= 3:
            name_size = field["data"][2]
            name = field["data"][3:3 + name_size].decode("ascii", "replace")
            columns[field["column"]] = name
        elif field["type"] != FIELD_COLUMN:
            break
        if not field["next"]:
            break
        offset = field["next"]
    return columns


def read_ratings():
    idx = (ML / "main.idx").read_bytes()
    dat = (ML / "main.dat").read_bytes()
    if idx[:8] != b"NDEINDEX" or dat[:8] != b"NDETABLE":
        raise RuntimeError("не похоже на базу Winamp")

    columns = read_columns(dat)
    by_name = {name: number for number, name in columns.items()}
    file_id = by_name.get("filename")
    rating_id = by_name.get("rating")
    if file_id is None or rating_id is None:
        raise RuntimeError(f"в базе нет нужных столбцов: {sorted(by_name)}")

    count = struct.unpack_from("<I", idx, 8)[0]
    # В индексе на запись приходится по два числа: её номер и смещение
    # в файле данных. Спецификация описывает только массив смещений, но
    # в файлах Winamp 5.9 лежат именно пары.
    pairs = struct.unpack_from(f"<{count * 2}I", idx, 12)
    offsets = pairs[1::2]

    result = {}
    for start in offsets:
        offset = start
        path = None
        rating = 0
        seen = 0
        while offset and seen < 64:
            field = read_field(dat, offset)
            if not field:
                break
            seen += 1
            if field["column"] == file_id and field["type"] in STRING_TYPES:
                path = decode_string(field["data"])
            elif field["column"] == rating_id and field["type"] == FIELD_INTEGER:
                if len(field["data"]) >= 4:
                    rating = struct.unpack_from("<i", field["data"], 0)[0]
            offset = field["next"]
        if path:
            result[path] = rating
    return result


def main():
    ratings = read_ratings()
    rated = {path: stars for path, stars in ratings.items() if stars}
    print(f"треков в базе: {len(ratings)}, с оценкой: {len(rated)}")
    for path, stars in sorted(rated.items(), key=lambda x: -x[1]):
        print(f"  {stars}* {path}")


if __name__ == "__main__":
    main()
