# -*- coding: utf-8 -*-
"""Режет круглые токены из портретов игроков и собирает из них лист для
Excalidraw.

Использование:
    python make-player-tokens.py

На выходе в `_img/players/tokens`:
  * `<Имя> токен.png` - кругляшок 512x512 с прозрачным фоном, головой из
    портрета и цветной каёмкой;
  * `Токены игроков.excalidraw.md` - лист, где все токены уже вставлены
    размером с кружки бойцов на батлмапе.

Про размер. В Excalidraw картинка вставляется в натуральную величину, то
есть 512 единиц сцены - это в пятнадцать раз больше кружка бойца. Поэтому
токены заранее разложены на листе нужным размером: оттуда их копируют в
карту, и масштаб менять не надо. Сами PNG при этом остаются крупными,
чтобы не мылились на приближении.

Про кадрирование. Головы на портретах стоят по-разному, автоматически их
не поймать, поэтому вырез задан руками: cx и cy - центр головы, r -
половина стороны выреза, всё в долях от стороны портрета. Проверять
удобно так: нарисовать круг поверх портрета и посмотреть, что в него
попало.

Про источник. По умолчанию токен режется из `<Имя>.png`, но ключ `src`
в настройке персонажа задаёт другой файл. У Калиостро так и сделано: в
раздатку идёт его обычный облик, а в токен - настоящий, без грима.
"""
import hashlib
import json
import os
import random

from PIL import Image, ImageDraw

VAULT = r"C:\vaults\Рудники Фанделвера"
SRC = os.path.join(VAULT, "_img", "players")
DST = os.path.join(SRC, "tokens")
SHEET = os.path.join(DST, "Токены игроков.excalidraw.md")

SIZE = 512
SS = 4  # суперсэмплинг, иначе край круга лесенкой

# размер кружков бойцов на карте "Засада гоблинов", увеличенный на 8%:
# с портретом внутри кружок читается хуже, чем цифра, поэтому чуть крупнее
W, H = 38.52975918257891, 39.312
STEP = 60  # шаг раскладки токенов на листе

TOKENS = {
    "Дворик Трахак": dict(cx=0.537, cy=0.211, r=0.200, ring="#1f4fa0"),
    "Эдрик": dict(cx=0.516, cy=0.126, r=0.140, ring="#c1662f"),
    "Эйра": dict(cx=0.437, cy=0.162, r=0.162, ring="#a82a1e"),
    "Кали Мейхем": dict(cx=0.500, cy=0.143, r=0.155, ring="#6b5fd6"),
    "Калиостро Великолепный": dict(cx=0.536, cy=0.313, r=0.276, ring="#14663c",
                                   src="Калиостро Великолепный - без грима"),
    "Ириван": dict(cx=0.473, cy=0.199, r=0.192, ring="#2f6b18"),
}

INDEX = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
rnd = random.Random(20260925)


def crop_head(img, cx, cy, r):
    """Квадратный вырез вокруг головы. Если он вылезает за край портрета -
    двигаем его внутрь, а не режем, иначе лицо уедет из центра круга."""
    w, h = img.size
    half = r * w
    box = [cx * w - half, cy * h - half, cx * w + half, cy * h + half]
    dx = min(0, box[0]) + max(0, box[2] - w)
    dy = min(0, box[1]) + max(0, box[3] - h)
    box = [box[0] - dx, box[1] - dy, box[2] - dx, box[3] - dy]
    return img.crop(tuple(int(round(v)) for v in box))


def make_token(name, cfg):
    src = Image.open(os.path.join(SRC, cfg.get("src", name) + ".png")).convert("RGB")
    big = SIZE * SS
    head = crop_head(src, cfg["cx"], cfg["cy"], cfg["r"]).resize((big, big), Image.LANCZOS)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    token = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    token.paste(head, (0, 0), mask)

    # каёмка цветом персонажа, с тонким тёмным контуром снаружи и изнутри
    d = ImageDraw.Draw(token)
    ring = int(big * 0.068)
    thin = max(1, int(big * 0.012))
    d.ellipse((ring / 2, ring / 2, big - 1 - ring / 2, big - 1 - ring / 2),
              outline=cfg["ring"], width=ring)
    d.ellipse((thin / 2, thin / 2, big - 1 - thin / 2, big - 1 - thin / 2),
              outline="#1e1e1e", width=thin)
    inner = ring + thin // 2
    d.ellipse((inner, inner, big - 1 - inner, big - 1 - inner),
              outline="#1e1e1e", width=thin)

    token = token.resize((SIZE, SIZE), Image.LANCZOS)
    os.makedirs(DST, exist_ok=True)
    token.save(os.path.join(DST, name + " токен.png"))


def element_id(seed):
    return hashlib.sha1(seed.encode()).hexdigest()[:8]


def file_id(name):
    """Excalidraw ищет картинку по этому ключу в секции Embedded Files,
    содержимое файла он не хэширует - лишь бы ключи сходились."""
    return hashlib.sha1(("token:" + name).encode()).hexdigest()


def make_sheet():
    elements, text_lines, embedded = [], [], []
    for i, name in enumerate(TOKENS):
        x = i * STEP
        elements.append({
            "id": element_id("img" + name), "type": "image",
            "x": x, "y": 0, "width": W, "height": H,
            "angle": 0, "strokeColor": "transparent", "backgroundColor": "transparent",
            "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "roundness": None,
            "seed": rnd.randint(1, 2 ** 31), "version": 1,
            "versionNonce": rnd.randint(1, 2 ** 31), "updated": 1790000000000,
            "isDeleted": False, "groupIds": [], "boundElements": [], "link": None,
            "locked": False, "frameId": None, "hasTextLink": False,
            "fileId": file_id(name), "scale": [1, 1], "crop": None,
            "index": "a" + INDEX[2 * i], "status": "pending",
        })
        tid = element_id("txt" + name)
        elements.append({
            "id": tid, "type": "text",
            "x": x + W / 2 - 45, "y": H + 6, "width": 90, "height": 15,
            "angle": 0, "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
            "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "groupIds": [], "frameId": None,
            "index": "a" + INDEX[2 * i + 1], "roundness": None,
            "seed": rnd.randint(1, 2 ** 31), "version": 1,
            "versionNonce": rnd.randint(1, 2 ** 31), "isDeleted": False,
            "boundElements": [], "updated": 1790000000000, "link": None,
            "locked": False, "text": name, "fontSize": 12, "fontFamily": 5,
            "textAlign": "center", "verticalAlign": "top", "containerId": None,
            "originalText": name, "autoResize": True, "lineHeight": 1.25,
            "hasTextLink": False,
        })
        text_lines.append(f"{name} ^{tid}")
        embedded.append(f"{file_id(name)}: [[{name} токен.png]]")

    drawing = {
        "type": "excalidraw", "version": 2, "source": "Roll/Tools/Maps/make-player-tokens.py",
        "elements": elements,
        "appState": {
            "theme": "dark", "viewBackgroundColor": "#ffffff",
            "currentItemStrokeColor": "#1e1e1e",
            "currentItemBackgroundColor": "transparent",
            "currentItemFillStyle": "solid", "currentItemStrokeWidth": 1,
            "currentItemStrokeStyle": "solid", "currentItemRoughness": 0,
            "currentItemOpacity": 100, "currentItemFontFamily": 5,
            "currentItemFontSize": 12, "currentItemTextAlign": "center",
            "gridSize": None, "scrollX": 60, "scrollY": 120,
            "zoom": {"value": 2},
        },
        "files": {},
    }

    nl = chr(10)
    md = f"""---

excalidraw-plugin: parsed
tags: [excalidraw]

---
==\u26a0  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. \u26a0==

Токены партии для батлмап. Кругляшки уже нужного размера ({W:.1f} x {H}) -
такого же, как кружки бойцов на карте "Засада гоблинов". Копируешь нужный
токен отсюда, вставляешь в карту, размер менять не надо.

Картинки лежат рядом, в этой же папке. Перерисовать их из портретов и
пересобрать этот лист: `Roll/Tools/Maps/make-player-tokens.py`.

# Excalidraw Data

## Text Elements
{nl.join(text_lines)}

## Embedded Files
{nl.join(embedded)}

%%
## Drawing
```json
{json.dumps(drawing, ensure_ascii=False, indent=1)}
```
%%"""
    with open(SHEET, "w", encoding="utf-8") as fh:
        fh.write(md)


if __name__ == "__main__":
    for name, cfg in TOKENS.items():
        make_token(name, cfg)
        print("токен:", name)
    make_sheet()
    print("лист:", SHEET)
