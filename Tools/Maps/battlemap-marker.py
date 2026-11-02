# -*- coding: utf-8 -*-
"""Маркер-плашка "Battlemap" в левом нижнем углу карты локации.

Добавляет в библиотеку zoom-map значок `battlemap` - прямоугольную плашку с
надписью Battlemap - и ставит на карту локации маркер, который ведёт на лист
`Battlemap - <Локация>.excalidraw`. Повторный запуск маркер не дублирует.

    python battlemap-marker.py Аксхольм [Гноменгард ...]

Пока Обсидиан открыт, настройки zoom-map он держит в памяти и затрёт
правку, поэтому скрипт ждёт его закрытия.
"""
import json, os, subprocess, sys, time, urllib.parse

R = r"C:\vaults\Рудники Фанделвера"
DATA = os.path.join(R, ".obsidian", "plugins", "zoom-map", "data.json")
MARKERS = os.path.join(R, "_img", "maps", "markers")
ICON_KEY = "battlemap"
ICON = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="32" viewBox="0 0 120 32">'
        '<rect x="1" y="1" width="118" height="30" rx="6" fill="#000000" stroke="#ffffff" stroke-width="2"/>'
        '<text x="60" y="21.5" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" '
        'font-size="17" font-weight="700" fill="#ffffff" letter-spacing="0.5">Battlemap</text></svg>')
POS = (0.06, 0.955)          # левый нижний угол

locations = sys.argv[1:] or ["Аксхольм"]

while "Obsidian.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                       capture_output=True, text=True).stdout:
    print("Жду, пока закроется Обсидиан...", flush=True)
    time.sleep(5)
time.sleep(2)

d = json.load(open(DATA, encoding="utf-8"))
d["icons"] = [i for i in d["icons"] if i["key"] != ICON_KEY]
template = next(i for i in d["icons"] if i["key"] == "loc-axeholm")
icon = {k: v for k, v in template.items()}
icon.update(key=ICON_KEY, size=120, anchorX=60, anchorY=16,
            pathOrDataUrl="data:image/svg+xml;charset=UTF-8," + urllib.parse.quote(ICON, safe=""))
d["icons"].append(icon)
if True:
    open(DATA, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2))
    print("значок battlemap записан в библиотеку")

for loc in locations:
    p = os.path.join(MARKERS, f"{loc} - карта.webp.markers.json")
    sheet = os.path.join(R, "_img", "maps", "battles", f"Battlemap - {loc}.excalidraw.md")
    if not os.path.exists(p) or not os.path.exists(sheet):
        print(f"{loc}: нет карты или листа, пропуск")
        continue
    m = json.load(open(p, encoding="utf-8"))
    m["markers"] = [k for k in m["markers"] if k.get("id") != "marker-battlemap"]
    m["markers"].append({
        "type": "pin", "id": "marker-battlemap", "x": POS[0], "y": POS[1],
        "layer": m["layers"][0]["id"], "iconKey": ICON_KEY,
        "tooltip": "Battlemap",
        "link": f"Battlemap - {loc}.excalidraw",
    })
    open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(m, ensure_ascii=False, indent=2))
    print(f"{loc}: маркер Battlemap поставлен")
print("Готово, можно открывать Обсидиан.")
