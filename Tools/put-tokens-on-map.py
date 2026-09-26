# -*- coding: utf-8 -*-
"""Меняет на батлмапе белые кружки с номерами на токены героев.

Использование:
    python put-tokens-on-map.py [путь к .excalidraw.md]

Номер в кружке - это поле `order` во фронтматтере карточки игрока, то есть
порядок партии. Белые кружки (заливка #ffffff) считаются героями, кружки
других цветов - монстрами, их скрипт не трогает.

Кружок меняется на картинку токена с тем же положением, размером и местом
в стопке, так что на карте ничего не съезжает. Связанный с кружком текст с
номером убирается: имя теперь читается по лицу.

Токены берутся из `_img/players/tokens`, делает их
`Roll/Tools/make-player-tokens.py`. Ссылка на картинку прописывается в
секцию Embedded Files - Excalidraw ищет файл по ключу оттуда, содержимое
он не хэширует, лишь бы ключи сходились.

Скрипт идемпотентный: если кружки уже заменены, второй запуск ничего не
делает.
"""
import hashlib
import json
import os
import re
import sys

import lzstring

VAULT = r"C:\vaults\Рудники Фанделвера"
PLAYERS = os.path.join(VAULT, "Adventure", "Players")
DEFAULT_MAP = os.path.join(
    VAULT, "_img", "alchemist", "Засада Гоблинов", "Засада гоблинов.excalidraw.md")


def party_order():
    """Номер в кружке -> имя героя, по полю order во фронтматтере."""
    order = {}
    for name in os.listdir(PLAYERS):
        if not name.endswith(".md"):
            continue
        text = open(os.path.join(PLAYERS, name), encoding="utf-8").read()
        m = re.search(r"^order:\s*(\d+)\s*$", text, re.M)
        if m:
            order[m.group(1)] = name[:-3]
    return order


def file_id(name):
    return hashlib.sha1(("token:" + name).encode()).hexdigest()


def main(path):
    src = open(path, encoding="utf-8").read()
    z = lzstring.LZString()
    block = re.search(r"```compressed-json\n(.*?)\n```", src, re.S)
    if not block:
        raise SystemExit("в файле нет блока compressed-json")
    drawing = json.loads(z.decompressFromBase64("".join(block.group(1).split())))

    order = party_order()
    texts = {e["id"]: e for e in drawing["elements"] if e["type"] == "text"}
    drop, elements, used = set(), [], []

    for e in drawing["elements"]:
        if e["type"] != "ellipse" or e["backgroundColor"] != "#ffffff":
            elements.append(e)
            continue
        bound = [b["id"] for b in (e.get("boundElements") or [])]
        label = next((texts[i]["text"].strip() for i in bound if i in texts), None)
        name = order.get(label)
        if not name:
            elements.append(e)
            continue
        drop.update(bound)
        used.append(name)
        elements.append({
            "id": e["id"], "type": "image",
            "x": e["x"], "y": e["y"], "width": e["width"], "height": e["height"],
            "angle": e["angle"], "strokeColor": "transparent",
            "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0,
            "opacity": 100, "roundness": None, "seed": e["seed"],
            "version": e["version"] + 1, "versionNonce": e["versionNonce"],
            "updated": e["updated"], "isDeleted": False,
            "groupIds": e.get("groupIds", []), "boundElements": [],
            "link": None, "locked": False, "frameId": e.get("frameId"),
            "hasTextLink": False, "fileId": file_id(name), "scale": [1, 1],
            "crop": None, "index": e["index"], "status": "pending",
        })

    if not used:
        print("менять нечего: белых кружков с номерами партии нет")
        return

    drawing["elements"] = [e for e in elements if e["id"] not in drop]

    text_lines = [f'{e["text"]} ^{e["id"]}'
                  for e in drawing["elements"] if e["type"] == "text"]
    embedded = re.search(r"## Embedded Files\n(.*?)\n\n%%", src, re.S).group(1)
    embedded = [l for l in embedded.strip().split("\n")
                if l.strip() and "токен.png" not in l]
    embedded += [f"{file_id(n)}: [[{n} токен.png]]" for n in used]

    packed = z.compressToBase64(json.dumps(drawing, ensure_ascii=False))
    wrapped = "\n\n".join(packed[i:i + 256] for i in range(0, len(packed), 256))

    out = re.sub(r"## Text Elements\n.*?\n\n## Embedded Files",
                 "## Text Elements\n" + "\n\n".join(text_lines) + "\n\n## Embedded Files",
                 src, flags=re.S)
    out = re.sub(r"## Embedded Files\n.*?\n\n%%",
                 "## Embedded Files\n" + "\n".join(embedded) + "\n\n%%",
                 out, flags=re.S)
    out = re.sub(r"```compressed-json\n.*?\n```",
                 "```compressed-json\n" + wrapped + "\n```", out, flags=re.S)

    open(path, "w", encoding="utf-8").write(out)
    print("заменено кружков:", len(used), "->", ", ".join(used))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MAP)
