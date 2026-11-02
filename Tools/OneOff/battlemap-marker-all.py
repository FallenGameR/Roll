# -*- coding: utf-8 -*-
"""Плашка Battlemap на все карты локаций, на место, выбранное Мастером на Аксхольме.

Позиция берётся с карты Аксхольма в долях ширины и высоты. Карты, у которых
один файл маркеров на две страницы (Громолесье, Замок и Логово Ядоклыка),
пропускаются: одна плашка не может вести на два листа.
"""
import json, os, subprocess, time

R = r"C:\vaults\Рудники Фанделвера"
M = os.path.join(R, "_img", "maps", "markers")
Z = os.path.join(R, "_img", "maps", "zoommap")
PAIRS = [
    (os.path.join(M, f"{n} - карта.webp.markers.json"), f"Battlemap - {n}") for n in [
        "Башня Штормов", "Гноменгард", "Дозор Провидцев", "Драконий Курган", "Круг Гроз",
        "Лагерь Лесорубов", "Ледяная Твердыня", "Лесная Усадьба", "Логово Алых Плащей",
        "Логово Скальной Пасти", "Охотничий домик Сокола", "Пещера Волнового Эха",
        "Подгорный Прииск", "Ранчо Сырные Черепушки", "Раскопки Дворфов", "Холм Обид"]
] + [
    (os.path.join(Z, f"Трактир Стоунхилл - {n}.jpg.markers.json"), f"Battlemap - Трактир Стоунхилл - {n}")
    for n in ["Общий зал", "Комнаты наверху", "Погреб"]
]

while "Obsidian.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                       capture_output=True, text=True).stdout:
    print("Жду, пока закроется Обсидиан...", flush=True)
    time.sleep(5)
time.sleep(2)

ax = json.load(open(os.path.join(M, "Аксхольм - карта.webp.markers.json"), encoding="utf-8"))
ref = next(k for k in ax["markers"] if k.get("id") == "marker-battlemap")
X, Y = ref["x"], ref["y"]
print(f"позиция с Аксхольма: x={X:.4f} y={Y:.4f}")

for path, sheet in PAIRS:
    if not os.path.exists(path):
        print("нет файла маркеров:", path); continue
    if not os.path.exists(os.path.join(R, "_img", "maps", "battles", sheet + ".excalidraw.md")):
        print("нет листа:", sheet); continue
    m = json.load(open(path, encoding="utf-8"))
    layer = m["layers"][0]["id"] if m.get("layers") else "default"
    m["markers"] = [k for k in m.get("markers", []) if k.get("id") != "marker-battlemap"]
    m["markers"].append({"type": "pin", "id": "marker-battlemap", "x": X, "y": Y,
                         "layer": layer, "iconKey": "battlemap", "tooltip": "Battlemap",
                         "link": sheet + ".excalidraw"})
    open(path, "w", encoding="utf-8", newline="\n").write(json.dumps(m, ensure_ascii=False, indent=2))
    print("ок:", sheet)
print("Готово, можно открывать Обсидиан.")
