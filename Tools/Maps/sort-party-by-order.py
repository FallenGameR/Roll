# -*- coding: utf-8 -*-
"""Выстраивает игроков в партиях Initiative Tracker по полю order из карточек.

Порядок игроков в блоке encounter и при старте боя берётся из списка партии
в data.json трекера. Скрипт сортирует этот список по order из шапки карточки
игрока (связь через path в настройках трекера). Пересадили людей - поменяли
order в шапках и запустили ещё раз.

Пока Обсидиан открыт, трекер держит настройки в памяти и затрёт правку,
поэтому скрипт ждёт закрытия.
"""
import json, os, re, subprocess, time

VAULT = r"C:\vaults\Рудники Фанделвера"
DATA = os.path.join(VAULT, ".obsidian", "plugins", "initiative-tracker", "data.json")

while "Obsidian.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                       capture_output=True, text=True).stdout:
    print("Жду, пока закроется Обсидиан...", flush=True)
    time.sleep(5)

d = json.load(open(DATA, encoding="utf-8"))
order = {}
for p in d["players"]:
    path = os.path.join(VAULT, p.get("path") or "")
    m = None
    if os.path.isfile(path):
        m = re.search(r"(?m)^order:\s*(\d+)\s*$", open(path, encoding="utf-8").read())
    order[p["name"]] = int(m.group(1)) if m else 999

d["players"].sort(key=lambda p: order[p["name"]])
for party in d["parties"]:
    party["players"].sort(key=lambda n: order.get(n, 999))
    print(party["name"], ":", ", ".join(f"{order.get(n, '?')}. {n}" for n in party["players"]))

open(DATA, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2))
print("Готово, можно открывать Обсидиан.")
