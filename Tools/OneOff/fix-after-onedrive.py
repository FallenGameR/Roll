# -*- coding: utf-8 -*-
"""Чинит то, что можно править только при закрытом Обсидиане.

1. Возвращает из последнего коммита файлы, которые OneDrive заменил старыми
   копиями: список включённых плагинов, маркеры пяти карт, манифесты и
   colored-tags, удалённый маркер 014.
2. Переводит пути бестиария в Fantasy Statblocks и Initiative Tracker
   с DnD Rules на DnD Notes.
"""
import json, os, subprocess, time

R = r"C:\vaults\Рудники Фанделвера"
RESTORE = [
    ".obsidian/community-plugins.json",
    ".obsidian/plugins/colored-tags/data.json",
    ".obsidian/plugins/colored-tags/manifest.json",
    ".obsidian/plugins/obsidian-admonition/manifest.json",
    ".obsidian/plugins/obsidian-git/manifest.json",
    ".obsidian/plugins/templater-obsidian/manifest.json",
    "_img/014-map-db-pc.webp.markers.json",
    "_img/maps/markers/Гноменгард - карта.webp.markers.json",
    "_img/maps/markers/Логово Скальной Пасти - карта.webp.markers.json",
    "_img/maps/markers/Побережье Мечей - карта.webp.markers.json",
    "_img/maps/markers/Фандалин - карта.webp.markers.json",
    "_img/maps/markers/Фандалин - рисунок.jpg.markers.json",
]

while "Obsidian.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                       capture_output=True, text=True).stdout:
    print("Жду, пока закроется Обсидиан...", flush=True)
    time.sleep(5)

r = subprocess.run(["git", "restore", "--worktree", "--source=HEAD", "--", *RESTORE], cwd=R,
                   capture_output=True, text=True, encoding="utf-8")
print("восстановлено из коммита:", len(RESTORE), r.stderr.strip())

p = os.path.join(R, ".obsidian/plugins/obsidian-5e-statblocks/data.json")
d = json.load(open(p, encoding="utf-8"))
d["paths"] = [x.replace("DnD Rules/", "DnD Notes/") for x in d["paths"]]
open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2))
print("statblocks:", d["paths"])

p = os.path.join(R, ".obsidian/plugins/initiative-tracker/data.json")
t = open(p, encoding="utf-8").read()
n = t.count('"DnD Rules/')
t = t.replace('"DnD Rules/', '"DnD Notes/')
json.loads(t)
open(p, "w", encoding="utf-8", newline="\n").write(t)
print("initiative tracker: путей поправлено", n)

m = json.load(open(os.path.join(R, "_img/maps/markers/Побережье Мечей - карта.webp.markers.json"), encoding="utf-8"))
print("маркеров на карте Побережья:", len(m["markers"]))
print("плагины:", json.load(open(os.path.join(R, ".obsidian/community-plugins.json"), encoding="utf-8"))[-6:])
print("Готово, можно открывать Обсидиан.")
