# -*- coding: utf-8 -*-
"""Переводит теги genre всей фонотеки на словарь ноября 2026 года.

Использование:
    python migrate-genre-2026-11.py                 # вхолостую: отчёт, файлы не трогаются
    python migrate-genre-2026-11.py --apply         # записать; сперва пишется файл отката
    python migrate-genre-2026-11.py --rollback FILE # вернуть genre из файла отката

План и потрековые правки лежат в сессии tags (--plan-dir):
    tag-cleanup-plan.md        пункты 1, 2, 4, 5, 8 - таблицы зашиты ниже
    scene-draft.csv            Name,Scene,Reason - Scene для треков без сцены,
                               несколько сцен через ";"
    intro-outro-candidates.md  "## Intro" / "## Outro", строки "- Имя — пояснение"
                               (имя от пояснения отделяет длинное тире)

Что делает с каждым mp3 под --root (вся библиотека, включая Excluded):
1. переводит старые значения Intensity, Emotion и Scene в новые и
   выстраивает их в порядке словаря, дубли после слияния схлопывает;
2. трекам из scene-draft.csv ставит Scene, если своей сцены у них нет;
3. трекам из intro-outro-candidates.md добавляет Type Intro или Outro;
4. трём трекам из пункта 8 плана ставит Scene вручную, поверх перевода.

Значения старой схемы из Excluded (Haven, Hostile, Lively и прочие) тоже
переводятся, по таблице от сессии tags. Если всё же встретится значение,
которого нет ни в таблицах, ни в новом словаре, оно не трогается и
попадает в отчёт.

Отчёт: сводка в консоль и CSV со строками path,old,new в --report.
После записи скрипт перечитывает каждый файл и сверяет genre.

Запись идёт через write_genre.write, той же функцией, что у Set-Track:
ID3 правится на месте, версия тега сохраняется, звук не трогается.
Тег comment скрипт не читает и не пишет.
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
from collections import Counter

from mutagen.id3 import ID3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Music"))
import write_genre  # noqa: E402

PLAN_DIR = r"C:\Users\alexk\.copilot\session-state\c07140c8-b73c-4f44-855e-042b14a332fc\files"

ORDER = {
    "Intensity": ["Idle", "Tension", "Battle", "Climax"],
    "Emotion": ["Anger", "Fear", "Sorrow", "Reverence", "Curiosity", "Light"],
    "Scene": ["Rest(Tavern)", "Rest(Peaceful)", "Travel", "Urban(Town)", "Urban(Court)",
              "Mystic(Ritual)", "Mystic(Haunt)", "Dungeon(Ruins)", "Dungeon(Underworld)",
              "Action(Investigation)", "Action(Chase)", "Action(Stealth)", "Other"],
}
RENAME = {
    "Intensity": {"Background": "Idle", "Combat": "Battle", "Crisis": "Climax"},
    "Emotion": {"Unease": "Fear", "Dread": "Fear", "Disgust": "Fear",
                "Melancholy": "Sorrow", "Grief": "Sorrow", "Guilt": "Sorrow",
                "Awe": "Reverence",
                "Calm": "Light", "Joy": "Light", "Pride": "Light", "Tenderness": "Light",
                # Ещё более старая схема, она живёт только в Excluded.
                "Haven": "Light", "Hostile": "Anger", "Secrets": "Curiosity",
                "Triumph": "Light", "Tragic": "Sorrow", "Forbidden": "Fear",
                "Playful": "Light", "Divine": "Reverence"},
    "Scene": {"Tavern": "Rest(Tavern)", "Shelter": "Rest(Peaceful)",
              "Travel": "Travel", "Wilds": "Travel",
              "Urban": "Urban(Town)", "Court": "Urban(Court)",
              "Ritual": "Mystic(Ritual)", "Anomaly": "Mystic(Haunt)",
              "Ruins": "Dungeon(Ruins)", "Depths": "Dungeon(Underworld)",
              "Investigation": "Action(Investigation)", "Chase": "Action(Chase)",
              "Lively": "Rest(Tavern)"},
}
# Пункт 8 плана: Shelter тут не про передышку.
SCENE_OVERRIDE = {
    "Baldurs Gate 2 - The Pirate Isle": ["Rest(Tavern)"],
    "Plague Tale Innocence - By the River (Olivier Deriviere)": ["Action(Chase)"],
    "Wasteland 3 - Survivalist Bunker": ["Dungeon(Underworld)"],
}
CATEGORY_ORDER = ["Intensity", "Emotion", "Scene", "Game", "Type", "Meta"]
NO_SCENE_TYPES = {"Intro", "Outro", "Effect"}


def parse(genre):
    """'Intensity:A,B Meta:C' -> {категория: [значения]} с порядком как в строке."""
    result = {}
    for chunk in genre.split():
        category, sep, raw = chunk.partition(":")
        if not sep:
            raise ValueError("не формат Категория:значения: " + genre)
        result.setdefault(category, []).extend(v for v in raw.split(",") if v)
    return result


def serialize(cats):
    names = [c for c in CATEGORY_ORDER if cats.get(c)] + \
            [c for c in cats if c not in CATEGORY_ORDER and cats[c]]
    return " ".join(f"{c}:{','.join(cats[c])}" for c in names)


def migrate_values(category, values, unknown):
    rename, order = RENAME[category], ORDER[category]
    out = []
    for v in values:
        new = rename.get(v, v)
        if new not in order:
            unknown[(category, v)] += 1
        if new not in out:
            out.append(new)
    known = sorted((v for v in out if v in order), key=order.index)
    return known + [v for v in out if v not in order]


def load_plan(plan_dir):
    with open(os.path.join(plan_dir, "scene-draft.csv"), encoding="utf-8-sig", newline="") as f:
        draft = {}
        for row in csv.DictReader(f):
            scenes = [s.strip().rstrip("*") for s in row["Scene"].split(";") if s.strip()]
            bad = [s for s in scenes if s not in ORDER["Scene"]]
            if bad or not scenes:
                raise ValueError(f"scene-draft.csv: неизвестная сцена {bad} у {row['Name']}")
            draft[row["Name"].strip()] = sorted(set(scenes), key=ORDER["Scene"].index)
    types, section = {}, None
    with open(os.path.join(plan_dir, "intro-outro-candidates.md"), encoding="utf-8-sig") as f:
        for line in f:
            head = re.match(r"^##\s+(Intro|Outro)\s*$", line)
            if head:
                section = head.group(1)
            elif line.startswith("- ") and section:
                types[line[2:].split(" \u2014 ", 1)[0].strip()] = section
    return draft, types


def plan_track(name, genre, draft, types, unknown, notes):
    cats = parse(genre)
    for category in ORDER:
        if category in cats:
            cats[category] = migrate_values(category, cats[category], unknown)
    if name in SCENE_OVERRIDE:
        cats["Scene"] = list(SCENE_OVERRIDE[name])
        notes["override"] += 1
    if name in draft:
        if cats.get("Scene"):
            notes["draft_skipped_has_scene"] += 1
            print(f"  ! {name}: в черновике {draft[name]}, но своя сцена уже есть: {cats['Scene']}")
        else:
            cats["Scene"] = list(draft[name])
            notes["draft"] += 1
    if name in types:
        cats.setdefault("Type", [])
        if types[name] not in cats["Type"]:
            cats["Type"].append(types[name])
            notes[types[name].lower()] += 1
    return serialize(cats), cats


def library(root):
    for folder, _, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(".mp3"):
                yield os.path.join(folder, f)


def read_genre(path):
    frame = ID3(path).get("TCON")
    return str(frame) if frame else ""


def run(args):
    draft, types = load_plan(args.plan_dir)
    unknown, notes, changes = Counter(), Counter(), []
    seen, missing_scene = set(), []
    for path in library(args.root):
        name = os.path.splitext(os.path.basename(path))[0]
        seen.add(name)
        old = read_genre(path)
        new, cats = plan_track(name, old, draft, types, unknown, notes)
        if not cats.get("Scene") and not NO_SCENE_TYPES & set(cats.get("Type", [])):
            missing_scene.append((path, "Excluded" in cats.get("Meta", [])))
        if new != old:
            changes.append({"path": path, "old": old, "new": new})

    for label, names in (("scene-draft.csv", draft), ("intro-outro-candidates.md", types),
                         ("пункт 8", SCENE_OVERRIDE)):
        lost = sorted(set(names) - seen)
        if lost:
            raise SystemExit(f"{label}: нет в библиотеке {len(lost)} треков: {lost[:5]}")

    print(f"треков к правке: {len(changes)}")
    print(f"Scene из черновика: {notes['draft']}, Intro: {notes['intro']}, Outro: {notes['outro']}, "
          f"ручных правок (пункт 8): {notes['override']}")
    if notes["draft_skipped_has_scene"]:
        print(f"черновик пропущен, сцена уже есть: {notes['draft_skipped_has_scene']}")
    if unknown:
        print("значения вне словаря, оставлены как есть:")
        for (category, value), n in sorted(unknown.items()):
            print(f"  {category}:{value} - {n}")
    playable = [p for p, excluded in missing_scene if not excluded]
    print(f"без Scene после миграции: {len(playable)} в игре, "
          f"{len(missing_scene) - len(playable)} с Meta:Excluded")
    for p in playable[:20]:
        print("  ", os.path.relpath(p, args.root))

    if args.report:
        with open(args.report, "x", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, ["path", "old", "new"])
            w.writeheader()
            w.writerows(changes)
        print("отчёт:", args.report)

    if not args.apply:
        print("вхолостую: файлы не тронуты. Для записи добавь --apply.")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rollback = args.rollback_out or os.path.join(args.plan_dir, f"genre-rollback-{stamp}.json")
    with open(rollback, "x", encoding="utf-8") as f:
        json.dump([{"path": c["path"], "genre": c["old"]} for c in changes], f,
                  ensure_ascii=False, indent=1)
    print("откат:", rollback)
    return write_all([(c["path"], c["new"]) for c in changes])


def write_all(items):
    failed = 0
    for i, (path, genre) in enumerate(items, 1):
        try:
            write_genre.write(path, genre)
            if read_genre(path) != genre:
                raise OSError("после записи genre не совпал")
        except Exception as exc:  # noqa: BLE001 - остальные файлы не виноваты
            failed += 1
            print(f"!! {path}: {exc}")
        if i % 100 == 0:
            print(f"  записано {i} из {len(items)}", flush=True)
    print(f"готово: {len(items) - failed} из {len(items)}, ошибок {failed}")
    return 1 if failed else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=r"C:\vaults\Music")
    ap.add_argument("--plan-dir", default=PLAN_DIR)
    ap.add_argument("--report", help="новый CSV path,old,new; файл не должен существовать")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback-out", help="куда писать файл отката, по умолчанию в --plan-dir")
    ap.add_argument("--rollback", help="вернуть genre из файла отката")
    args = ap.parse_args()
    if args.rollback:
        items = json.load(open(args.rollback, encoding="utf-8"))
        print(f"откат {len(items)} треков из {args.rollback}")
        return write_all([(i["path"], i["genre"]) for i in items])
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
