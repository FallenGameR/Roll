# -*- coding: utf-8 -*-
"""Собирает excalidraw-батлмапы по страницам локаций кампании.

Карта каждой локации растягивается так, чтобы клетка её сетки совпала по
размеру с клеткой эталонной батлмапы. Тогда токены и примитивы копируются
из одного документа в другой без подгонки масштаба.

В готовом листе: подложка заблокирована, памятка про скорость и свет взята
из `markers.json` этой же карты, токены игроков лежат в левом нижнем углу.
Ссылка на лист дописывается на страницу локации сразу под заголовком `# Map`.

Запуск: python make-battlemap-excalidraw.py
"""

import hashlib
import json
import random
import re
import string
from pathlib import Path

from lzstring import LZString
from PIL import Image

VAULT = Path(r"C:\vaults\Рудники Фанделвера")
LOCATIONS = VAULT / "Adventure" / "Locations"
MAPS_DIR = VAULT / "_img" / "maps"
ZOOMMAP_DIR = MAPS_DIR / "zoommap"
MARKERS_DIR = MAPS_DIR / "markers"
OUT_DIR = MAPS_DIR / "battles"
TOKENS_DIR = VAULT / "_img" / "players" / "tokens"

# Эталон масштаба: сколько единиц сцены занимает одна клетка сетки.
# Взято из «Засада гоблинов»: картинка 3900 px = 26 клеток = 999.4706131782198 ед.
SCENE_PER_CELL = 999.4706131782198 / 26

# Размер токена игрока на сцене (совпадает с make-player-tokens.py).
TOKEN_W, TOKEN_H = 38.52975918257891, 39.312

TOKEN_ORDER = [
    "Эдрик",
    "Эйра",
    "Дворик Трахак",
    "Кали Мейхем",
    "Калиостро Великолепный",
    "Ириван",
]

LEGEND_FONT_SIZE = 36
# Доля ширины карты, которую занимает плашка памятки. Подобрана по Аксхольму:
# там она даёт кегль 36. Размер считается от карты, иначе на маленьких картах
# памятка закрывает половину боя.
LEGEND_WIDTH_SHARE = 0.32

# Шаг сетки карты в пикселях. Измерен гребёнкой по градиентному профилю и
# сверен глазами по оверлею; половинный и двойной шаг проверены отдельно.
# Карты, которой здесь нет, пропускается: на ней либо нет сетки (Фандалин,
# обзорные карты), либо её шаг ещё не проверен.
GRID_PITCH = {
    "Аксхольм - карта.webp": 43.7576,
    "Ранчо Сырные Черепушки - карта.webp": 43.7576,
    "Круг Гроз - карта.webp": 43.7576,
    "Драконий Курган - карта.webp": 43.7576,
    "Раскопки Дворфов - карта.webp": 43.7576,
    "Охотничий домик Сокола - карта.webp": 43.7576,
    "Гноменгард - карта.webp": 43.7576,
    "Ледяная Твердыня - карта.webp": 43.7576,
    "Лагерь Лесорубов - карта.webp": 43.7576,
    "Подгорный Прииск - карта.webp": 43.7576,
    "Дозор Провидцев - карта.webp": 43.7576,
    "Башня Штормов - карта.webp": 43.7576,
    "Холм Обид - карта.webp": 43.7576,
    "Лесная Усадьба - карта.webp": 43.7576,
    "Замок Скальной Пасти - карта.webp": 143.15,
    "Логово Скальной Пасти - карта.webp": 149.84,
    "Логово Алых Плащей - карта.webp": 149.97,
    "Громовое Древо.webp": 149.48,
    "Пещера Волнового Эха - карта.webp": 120.64,
    "Трактир Стоунхилл - Общий зал.jpg": 64.52,
    "Трактир Стоунхилл - Комнаты наверху.jpg": 64.52,
    "Трактир Стоунхилл - Погреб.jpg": 64.52,
}

PLUGIN_SOURCE = (
    "https://github.com/zsviczian/obsidian-excalidraw-plugin/releases/tag/2.27.3"
)

HEADER = """---

excalidraw-plugin: parsed
tags: [excalidraw]

---
==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠== You can decompress Drawing data with the command palette: 'Decompress current Excalidraw file'. For more info check in plugin settings under 'Saving'


# Excalidraw Data

## Text Elements"""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def file_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def new_id(rng: random.Random) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(rng.choice(alphabet) for _ in range(8))


def zoommap_blocks(page: Path):
    """Все блоки zoommap страницы: отступ каллаута, номер строки, карта, название.

    Название берётся из `name` внутри блока: так подписаны этажи трактира.
    Без него лист называется по странице локации. Приставку `Battlemap - `
    дописывает вызывающий: имя листа обязано отличаться от имени страницы.
    """
    lines = read_text(page).split("\n")
    fence = re.compile(r"^(>? *)```zoommap\s*$")
    heading = ""
    found = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("# "):
            heading = lines[i][2:].strip()
        m = fence.match(lines[i])
        if not m:
            i += 1
            continue
        pre = m.group(1)
        j = i + 1
        body = []
        while j < len(lines) and lines[j].strip() not in ("```", ">```", "> ```"):
            body.append(lines[j])
            j += 1
        text = "\n".join(body)
        path = re.search(r"- path: (.+)", text)
        name = re.search(r"^\s*>?\s*name: (.+)$", text, re.M)
        if path:
            title = (
                f"{heading} - {name.group(1).strip()}"
                if name
                else page.stem
            )
            found.append((pre, i, Path(path.group(1).strip()).name, title))
        i = j + 1
    return found


def legend_lines(image_name: str):
    """Памятка про скорость и свет из текстового слоя markers.json."""
    markers = MARKERS_DIR / f"{image_name}.markers.json"
    if not markers.exists():
        return []
    data = json.loads(read_text(markers))
    out = []
    for layer in data.get("textLayers") or []:
        if layer.get("id") != "txt-travel":
            continue
        for box in layer.get("boxes") or []:
            for line in box.get("lines") or []:
                text = (line.get("text") or "").strip()
                if text:
                    out.append(text)
    return out


def image_element(rng, x, y, w, h, fid, index, locked):
    return {
        "id": new_id(rng),
        "type": "image",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": "transparent",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "roundness": None,
        "seed": rng.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": rng.randint(1, 2**31 - 1),
        "updated": 1790400000000,
        "isDeleted": False,
        "groupIds": [],
        "boundElements": [],
        "link": None,
        "locked": locked,
        "frameId": None,
        "hasTextLink": False,
        "fileId": fid,
        "scale": [1, 1],
        "crop": None,
        "index": index,
        "status": "pending",
    }


def legend_elements(rng, x, y, lines, size, index_rect, index_text):
    """Памятка: контрастная плашка с привязанной к ней подписью."""
    text = "\n".join(lines)
    pad = size * 0.6
    text_w = max(len(line) for line in lines) * size * 0.52
    text_h = len(lines) * size * 1.25
    rect_id, text_id = new_id(rng), new_id(rng)

    rect = {
        "id": rect_id,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": text_w + pad * 2,
        "height": text_h + pad * 2,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "#ffffff",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": index_rect,
        "roundness": {"type": 3},
        "seed": rng.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": rng.randint(1, 2**31 - 1),
        "isDeleted": False,
        "boundElements": [{"id": text_id, "type": "text"}],
        "updated": 1790400000000,
        "locked": False,
        "link": None,
        "hasTextLink": False,
    }

    label = {
        "id": text_id,
        "type": "text",
        "x": x + pad,
        "y": y + pad,
        "width": text_w,
        "height": text_h,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": index_text,
        "roundness": None,
        "seed": rng.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": rng.randint(1, 2**31 - 1),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1790400000000,
        "locked": False,
        "text": text,
        "rawText": text,
        "fontSize": size,
        "fontFamily": 6,
        "textAlign": "left",
        "verticalAlign": "middle",
        "containerId": rect_id,
        "originalText": text,
        "autoResize": True,
        "lineHeight": 1.25,
        "labelPosition": None,
        "hasTextLink": False,
        "link": None,
    }
    return rect, label, text_id


def app_state():
    return {
        "theme": "dark",
        "viewBackgroundColor": "#ffffff",
        "currentItemStrokeColor": "#1e1e1e",
        "currentItemBackgroundColor": "#ff8787",
        "currentItemFillStyle": "solid",
        "currentItemStrokeWidthKey": "thin",
        "currentItemStrokeVariability": "constant",
        "currentItemStrokeStyle": "solid",
        "currentItemRoughness": 0,
        "currentItemOpacity": 100,
        "currentItemFontFamily": 5,
        "currentItemFontSize": 12,
        "currentItemTextAlign": "left",
        "currentItemStartArrowhead": None,
        "currentItemEndArrowhead": "arrow",
        "currentItemArrowType": "round",
        "currentItemFrameRole": None,
        "scrollX": 40,
        "scrollY": 40,
        "zoom": {"value": 0.35},
        "currentItemRoundness": "round",
        "gridSize": 20,
        "gridStep": 5,
        "gridModeEnabled": False,
        "gridColor": {
            "Bold": "rgba(179, 179, 179, 0.5)",
            "Regular": "rgba(204, 204, 204, 0.5)",
        },
        "colorTopPicks": {
            "elementStroke": None,
            "elementBackground": None,
            "bucketFill": None,
        },
        "currentStrokeOptions": None,
        "frameRendering": {
            "enabled": True,
            "clip": True,
            "name": True,
            "outline": True,
            "markerName": True,
            "markerEnabled": True,
        },
        "objectsSnapModeEnabled": False,
        "activeTool": {
            "type": "selection",
            "customType": None,
            "locked": False,
            "fromSelection": False,
            "lastActiveTool": None,
        },
        "disableContextMenu": False,
        "bindingPreference": "enabled",
        "isMidpointSnappingEnabled": True,
        "boxSelectionMode": "contain",
    }


def compressed_block(scene: dict) -> str:
    raw = LZString().compressToBase64(json.dumps(scene, separators=(",", ":")))
    lines = [raw[i : i + 256] for i in range(0, len(raw), 256)]
    return "\n\n".join(lines)


def build_sheet(title: str, image_name: str) -> None:
    rng = random.Random(title)
    pitch = GRID_PITCH[image_name]
    with Image.open(ZOOMMAP_DIR / image_name) as im:
        px_w, px_h = im.size
    scene_w = px_w / pitch * SCENE_PER_CELL
    scene_h = px_h / pitch * SCENE_PER_CELL

    bg_id = file_id("map:" + image_name)
    elements = [image_element(rng, 0.0, 0.0, scene_w, scene_h, bg_id, "a0", True)]
    embedded = [(bg_id, image_name)]

    gap = SCENE_PER_CELL * 0.12
    pad = SCENE_PER_CELL * 0.25
    y = scene_h - pad - TOKEN_H
    for i, name in enumerate(TOKEN_ORDER):
        png = f"{name} токен.png"
        if not (TOKENS_DIR / png).exists():
            raise SystemExit(f"нет файла токена: {TOKENS_DIR / png}")
        fid = file_id("token:" + name)
        x = pad + i * (TOKEN_W + gap)
        elements.append(
            image_element(rng, x, y, TOKEN_W, TOKEN_H, fid, f"a{i + 1}", False)
        )
        embedded.append((fid, png))

    lines = legend_lines(image_name)
    legend_text = ""
    size = 0.0
    if lines:
        longest = max(len(line) for line in lines)
        size = min(
            LEGEND_FONT_SIZE,
            scene_w * LEGEND_WIDTH_SHARE / (longest * 0.52 + 1.2),
        )
        rect, label, legend_id = legend_elements(
            rng,
            SCENE_PER_CELL * 0.6,
            SCENE_PER_CELL * 0.6,
            lines,
            size,
            f"a{len(TOKEN_ORDER) + 1}",
            f"a{len(TOKEN_ORDER) + 2}",
        )
        elements.extend([rect, label])
        legend_text = "\n".join(lines) + f" ^{legend_id}"

    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": PLUGIN_SOURCE,
        "elements": elements,
        "appState": app_state(),
        "files": {},
    }

    body = [HEADER, f"{legend_text}\n" if legend_text else "", "## Embedded Files\n"]
    for fid, link in embedded:
        body.append(f"{fid}: [[{link}]]\n")
    body.append("%%\n## Drawing\n```compressed-json\n")
    body.append(compressed_block(scene))
    body.append("\n```\n%%")

    write_text(OUT_DIR / f"{title}.excalidraw.md", "\n".join(body))
    print(
        f"  {title}: {scene_w:.0f}x{scene_h:.0f} ед. "
        f"({px_w / pitch:.1f}x{px_h / pitch:.1f} клеток), "
        f"памятка: {len(lines)} стр., кегль {size:.0f}"
    )


def add_links(page: Path, wanted) -> int:
    """Ссылки на листы - строкой прямо над своим блоком zoommap.

    Внутри каллаута строка получает его отступ `> `, иначе каллаут оборвётся.
    """
    lines = read_text(page).split("\n")
    added = 0
    for pre, idx, title in sorted(wanted, key=lambda w: -w[1]):
        link = f"{pre}[[{title}.excalidraw]]"
        if link in lines:
            continue
        lines[idx:idx] = [link, pre.rstrip()]
        added += 1
    if added:
        write_text(page, "\n".join(lines))
    return added


def main() -> None:
    # Локации разложены по папкам частей сюжета; отыгранные в Done не трогаем.
    pages = [p for p in LOCATIONS.rglob("*.md") if "Done" not in p.parts]
    for page in sorted(pages, key=lambda p: p.stem):
        blocks = zoommap_blocks(page)
        if not blocks:
            print(f"{page.stem}: нет блока zoommap — пропуск")
            continue
        print(page.stem)
        wanted = []
        for pre, idx, image_name, title in blocks:
            if image_name not in GRID_PITCH:
                print(f"  {image_name}: сетка не измерена — пропуск")
                continue
            sheet = f"Battlemap - {title}"
            build_sheet(sheet, image_name)
            wanted.append((pre, idx, sheet))
        added = add_links(page, wanted)
        if added:
            print(f"  ссылок добавлено на страницу: {added}")


if __name__ == "__main__":
    main()
