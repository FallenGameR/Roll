# -*- coding: utf-8 -*-
"""Переносит правки из медиатеки Winamp обратно в файлы кампании.

Порядок работы с музыкой такой: сначала треки назначаются в markdown,
оттуда собираются плейлисты, а дальше источником правды становится
сам плеер — Мастер удаляет там лишнее и расставляет звёзды прямо во
время игры. Этот скрипт возвращает такие правки в markdown, чтобы
следующая выгрузка их не затёрла.

Что переносится:

* трек удалён из плейлиста -> строка убирается из соответствующей
  сцены;
* плейлист удалён целиком -> убирается вся сцена (для ситуации или
  эффекта это одна строка);
* одна звезда -> трек больше не нужен: mp3 уезжает в Music\\Deleted,
  а ссылки на него исчезают из всех файлов кампании;
* пять звёзд -> трек хорош: если он лежал в Music\\Unsorted, файл
  переезжает в обычную папку франшизы, звёздочка в markdown снимается.

Рейтинг читается из тега POPM самого mp3, поэтому в Winamp должна быть
включена запись рейтингов в файлы (Preferences -> Media Library ->
Local Media). Без этого звёзды остаются только во внутренней базе
плеера и скрипту не видны.

Использование:
    python sync-from-winamp.py [--apply]
"""
import os
import re
import shutil
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(r"C:\vaults\Рудники Фанделвера")
MUSIC = Path(r"C:\vaults\Music")
DELETED = MUSIC / "Deleted"
PLAYLISTS = MUSIC / "_playlists"
CATALOG = Path(os.environ["APPDATA"]) / r"Winamp\Plugins\ml\playlists"

head = re.compile(r"^(#{1,6})\s+(.*)$")
track = re.compile(r"\[([^\]]*)\]\(file:///([^)]+)\)")


def to_path(url):
    return urllib.parse.unquote(url).replace("/", "\\")


def write_lines(md, lines):
    """Пишет файл кампании с LF: канон вольта задан .gitattributes."""
    with open(md, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def remove_lines(md, data, drop):
    """Убирает строки из файла и чинит индексы разобранных сцен.

    Индексы в scenes и headers считаны по исходному файлу, поэтому
    после удаления их надо сдвинуть: иначе следующая правка того же
    файла попадёт не в ту строку.
    """
    kept = [line for i, line in enumerate(data["lines"]) if i not in drop]
    write_lines(md, kept)
    data["lines"] = kept

    shift = []
    gone = 0
    for i in range(len(data["lines"]) + len(drop)):
        if i in drop:
            gone += 1
            shift.append(None)
        else:
            shift.append(i - gone)
    data["scenes"] = {
        scene: [(shift[i], path) for i, path in items
                if shift[i] is not None]
        for scene, items in data["scenes"].items()}
    data["headers"] = {
        scene: shift[i] for scene, i in data["headers"].items()
        if shift[i] is not None}


def read_catalog():
    """Название плейлиста -> список путей, как их видит плеер."""
    index = CATALOG / "playlists.xml"
    if not index.exists():
        return {}
    result = {}
    for node in ET.parse(index).getroot():
        m3u = CATALOG / node.get("filename")
        if not m3u.exists():
            continue
        tracks = [line.strip() for line
                  in m3u.read_text(encoding="utf-8-sig").splitlines()
                  if line.strip() and not line.startswith("#")]
        result[node.get("title")] = tracks
    return result


def scan_markdown():
    """Разбирает разделы музыки: файл -> сцена -> список строк."""
    files = {}
    for md in sorted(ROOT.rglob("*.md")):
        if "_Locations_backup" in str(md):
            continue
        lines = md.read_text(encoding="utf-8").splitlines()
        in_music = level = 0
        scene = ""
        scenes = {}
        header_lines = {}
        for i, line in enumerate(lines):
            m = head.match(line)
            if m:
                lvl, title = len(m.group(1)), m.group(2).strip()
                if in_music and lvl <= level:
                    in_music = 0
                elif in_music:
                    scene = title
                    header_lines[scene] = i
                    scenes.setdefault(scene, [])
                    continue
                if title.lower() in ("music", "музыка"):
                    in_music, level, scene = 1, lvl, ""
                continue
            if not in_music:
                continue
            t = track.search(line)
            if t:
                scenes.setdefault(scene, []).append((i, to_path(t.group(2))))
        if scenes:
            files[md] = {"lines": lines, "scenes": scenes,
                         "headers": header_lines}
    return files


def playlist_title(md, scene):
    name = md.stem
    if "\\Adventure\\Locations\\" not in str(md):
        # Точка в начале уводит сквозные подборки наверх дерева плеера,
        # отдельно от мест на карте.
        name = "." + name
    if scene in ("Ситуации", "Эффекты"):
        return None            # у них имя собирается из ярлыка
    return f"{name} - {scene}" if scene else name


def read_all_ratings():
    """Рейтинги из базы медиатеки: путь -> звёзды."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "winamp_ratings",
        str(Path(__file__).with_name("read-winamp-ratings.py")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.read_ratings()
    except Exception as error:
        print(f"  база Winamp не прочиталась: {error}")
        return {}


def drop_track_everywhere(files, path, apply):
    """Убирает ссылки на трек из всех файлов кампании."""
    count = 0
    for md, data in files.items():
        drop = {i for i, p in
                [(i, p) for items in data["scenes"].values()
                 for i, p in items]
                if p.lower() == path.lower()}
        if not drop:
            continue
        count += len(drop)
        if apply:
            remove_lines(md, data, drop)
    return count


def clear_unsorted_tag(path):
    """Убирает значение Unsorted из тега genre.

    Оно живёт в категории Meta, рядом с Intro и Outro; в Type лежат
    Effect, Vocals и Excluded. Другие категории не трогаем: разложить
    одно и то же значение по двум местам - верный способ получить
    рассинхрон.
    """
    try:
        from mutagen.id3 import ID3, TCON
        tags = ID3(path)
    except Exception:
        return False

    frames = tags.getall("TCON")
    if not frames or not frames[0].text:
        return False
    genre = frames[0].text[0]
    if "Meta:" not in genre or "Unsorted" not in genre:
        return False

    # Теги лежат как «Категория:значение1,значение2».
    parts = []
    for chunk in genre.split():
        category, _, values = chunk.partition(":")
        if category != "Meta" or not values:
            parts.append(chunk)
            continue
        kept = [v for v in values.split(",") if v and v != "Unsorted"]
        if kept:
            parts.append("Meta:" + ",".join(kept))
    tags.setall("TCON", [TCON(encoding=3, text=[" ".join(parts)])])
    tags.save(path)
    return True


def handle_ratings(files, apply):
    """Одна звезда - в Deleted, пять - снять тег Unsorted."""
    ratings = read_all_ratings()
    rated = {path: stars for path, stars in ratings.items() if stars}
    print(f"  оценено треков: {len(rated)} из {len(ratings)}")

    banished = promoted = 0
    for path, stars in sorted(rated.items()):
        mp3 = Path(path)
        if not mp3.exists() or DELETED in mp3.parents:
            continue
        if stars == 1:
            banished += 1
            print(f"  одна звезда: {mp3.name} -> Deleted")
            if apply:
                DELETED.mkdir(parents=True, exist_ok=True)
                shutil.move(str(mp3), str(DELETED / mp3.name))
                drop_track_everywhere(files, str(mp3), apply)
        elif stars == 5:
            # Файл остаётся на месте: перенос из Unsorted - отдельная
            # пакетная операция в конце кампании. Здесь только снимаем
            # метку «не отслушано».
            if not has_unsorted_tag(str(mp3)):
                print(f"  пять звёзд: {mp3.name} -> уже отслушан, "
                      "делать нечего")
                continue
            promoted += 1
            if not apply:
                print(f"  пять звёзд: {mp3.name} -> снять Unsorted")
                continue
            if clear_unsorted_tag(str(mp3)):
                print(f"  пять звёзд: {mp3.name} -> Unsorted снят")
                unstar(files, str(mp3))
    return banished, promoted


def has_unsorted_tag(path):
    try:
        from mutagen.id3 import ID3
        tags = ID3(path)
    except Exception:
        return False
    frames = tags.getall("TCON")
    if not frames or not frames[0].text:
        return False
    return "Unsorted" in frames[0].text[0]


def unstar(files, path):
    """Убирает звёздочку неотслушанного у строк с этим треком."""
    url = "file:///" + urllib.parse.quote(path.replace("\\", "/"), safe="/:")
    for md, data in files.items():
        if not any(url in line for line in data["lines"]):
            continue
        lines = []
        for line in data["lines"]:
            if url in line:
                m = track.search(line)
                if m:
                    tail = line[m.end():]
                    line = line[:m.end()] + re.sub(r"^\s*\*", "", tail)
            lines.append(line)
        data["lines"] = lines
        write_lines(md, lines)


def read_exported():
    """Что уже уезжало в плеер: имена списков и пути внутри них.

    Нужно, чтобы отличить «Мастер удалил» от «ещё не выгружали».
    Плейлиста нет в каталоге по обеим причинам, а последствия разные:
    в первом случае сцену надо убрать, во втором - это свежая работа,
    и трогать её нельзя.
    """
    names, paths = set(), set()
    if not PLAYLISTS.exists():
        return names, paths
    for m3u in PLAYLISTS.glob("*.m3u8"):
        names.add(m3u.stem)
        for line in m3u.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                paths.add(line.lower())
    return names, paths


def main():
    apply = "--apply" in sys.argv
    catalog = read_catalog()
    files = scan_markdown()
    if not catalog:
        print("каталог Winamp пуст - нечего синхронизировать")
        return

    exported_names, exported_paths = read_exported()

    # Все пути, которые плеер сейчас знает.
    alive = set()
    for tracks in catalog.values():
        alive.update(t.lower() for t in tracks)

    skipped = []
    removed = 0
    for md, data in files.items():
        drop = set()
        for scene, items in data["scenes"].items():
            title = playlist_title(md, scene)
            if title is None:
                # Ситуации и эффекты: плейлист на трек, ищем по пути.
                # Трек, которого плеер не знает и который туда никогда
                # не выгружался, - не удалённый, а новый.
                for index, path in items:
                    if (path.lower() not in alive
                            and path.lower() in exported_paths):
                        drop.add(index)
                continue
            if title not in catalog:
                if title not in exported_names:
                    # Сцену ещё ни разу не выгружали: это свежая работа,
                    # а не удаление Мастером. Снести её здесь означало
                    # бы стереть только что подобранную музыку.
                    skipped.append(title)
                    continue
                # Плейлист удалён целиком - убираем сцену вместе с
                # заголовком.
                for index, _path in items:
                    drop.add(index)
                if scene in data["headers"]:
                    drop.add(data["headers"][scene])
                continue
            known = {t.lower() for t in catalog[title]}
            for index, path in items:
                if path.lower() not in known:
                    drop.add(index)

        if not drop:
            continue
        removed += len(drop)
        print(f"{md.stem}: убрать строк {len(drop)}")
        if apply:
            remove_lines(md, data, drop)

    print(f"строк к удалению: {removed}")
    if skipped:
        print(f"не выгружалось в плеер, не трогаю: {len(skipped)}")
        for title in sorted(skipped):
            print(f"  {title}")
        print("  выгрузи их Export-Playlist, иначе правки оттуда не вернутся")

    print("звёзды:")
    banished, promoted = handle_ratings(files, apply)
    print(f"  в Deleted: {banished}, снято Unsorted: {promoted}")

    if not apply:
        print("сухой прогон, для записи добавь --apply")


if __name__ == "__main__":
    main()
