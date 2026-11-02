# -*- coding: utf-8 -*-
"""Плашка Battlemap на картах, где один файл маркеров на две страницы.

Громолесье ведёт на лист Начала, карта Замка (её же показывает Логово
Ядоклыка) - на лист Замка. Позиция та же, что на Аксхольме.
"""
import json, os, subprocess, time

R = r"C:\vaults\Рудники Фанделвера"
M = os.path.join(R, "_img", "maps", "markers")
PAIRS = [
    (os.path.join(M, "Громолесье.webp.markers.json"), "Battlemap - Громолесье - Начало"),
    (os.path.join(M, "Замок Скальной Пасти - карта.webp.markers.json"), "Battlemap - Замок Скальной Пасти"),
]

while "Obsidian.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                       capture_output=True, text=True).stdout:
    print("Жду, пока закроется Обсидиан...", flush=True)
    time.sleep(5)
time.sleep(2)

ax = json.load(open(os.path.join(M, "Аксхольм - карта.webp.markers.json"), encoding="utf-8"))
ref = next(k for k in ax["markers"] if k.get("id") == "marker-battlemap")
for path, sheet in PAIRS:
    assert os.path.exists(os.path.join(R, "_img", "maps", "battles", sheet + ".excalidraw.md")), sheet
    m = json.load(open(path, encoding="utf-8"))
    layer = m["layers"][0]["id"] if m.get("layers") else "default"
    m["markers"] = [k for k in m.get("markers", []) if k.get("id") != "marker-battlemap"]
    m["markers"].append({"type": "pin", "id": "marker-battlemap", "x": ref["x"], "y": ref["y"],
                         "layer": layer, "iconKey": "battlemap", "tooltip": "Battlemap",
                         "link": sheet + ".excalidraw"})
    open(path, "w", encoding="utf-8", newline="\n").write(json.dumps(m, ensure_ascii=False, indent=2))
    print("ок:", sheet)
print("Готово, можно открывать Обсидиан.")
