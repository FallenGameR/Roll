# -*- coding: utf-8 -*-
"""Переносит правки из медиатеки Winamp обратно в файлы кампании.

Порядок работы с музыкой такой: сначала треки назначаются в markdown,
оттуда собираются плейлисты, а дальше источником правды становится
сам плеер — Мастер удаляет там лишнее и расставляет звёзды прямо во
время игры. Этот скрипт возвращает такие правки в markdown, чтобы
следующая выгрузка их не затёрла.

Что переносится:

* трек удалён из плейлиста -> строка убирается из соответствующей
  сцены, а пара «плейлист, трек» дописывается в журнал отказов
  Music\\Rejected.csv, чтобы при подборе трек не вернули туда же;
* плейлист удалён целиком -> убирается вся сцена (для ситуации или
  эффекта это одна строка), её треки тоже идут в журнал;
* то же для тем NPC: их списки `<локация> - НПС - <имя>` собираются из
  `music:` в шапке карточки, и удалённое в плеере уходит оттуда;
* тег Meta:Delete -> послушали, не понравилось: mp3 уезжает в
  Music\\Deleted, ссылки на него исчезают из файлов кампании;
* тег Meta:Excluded -> отложен на потом: то же самое, но в
  Music\\Excluded;
* любая оценка звёздами -> трек разобран: снимается тег Unsorted, файл
  переезжает из Music\\Unsorted в обычную папку франшизы, ссылки в
  кампании переписываются на новый путь.

Теги Delete и Excluded после переезда остаются: они описывают состояние
трека, а не разовое поручение. Раньше выбрасывала одна звезда. От этого
отказались, когда звёзды стали настоящей оценкой: единица
посредственному, но нужному треку не должна стоить ему места в
библиотеке.

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
REJECTED = MUSIC / "Rejected.csv"
CATALOG = Path(os.environ["APPDATA"]) / r"Winamp\Plugins\ml\playlists"

head = re.compile(r"^(#{1,6})\s+(.*)$")
track = re.compile(r"\[([^\]]*)\]\(file:///([^)]+)\)")
# Сцена-псевдоним для `music` из шапки карточки NPC.
NPC_SCENE = "\x00npc"


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
        # Папки с точкой (.github, .obsidian, .git) - не страницы кампании:
        # в скиллах лежат примеры разделов музыки, и их нельзя переписывать.
        rel = md.relative_to(ROOT).parts
        if "_Locations_backup" in rel or any(p.startswith(".") for p in rel[:-1]):
            continue
        lines = md.read_text(encoding="utf-8").splitlines()
        in_music = level = 0
        scene = ""
        scenes = {}
        header_lines = {}
        # Тема NPC живёт в шапке (`music`), а не в разделе: её тоже надо
        # видеть, иначе переезд трека из Unsorted оставит ссылку сиротой.
        if lines and lines[0].strip() == "---":
            in_key = False
            for i, line in enumerate(lines[1:], start=1):
                if line.strip() == "---":
                    break
                if re.match(r"^\S[^:]*:", line):
                    in_key = line.startswith("music:")
                if in_key:
                    t = track.search(line)
                    if t:
                        scenes.setdefault(NPC_SCENE, []).append(
                            (i, to_path(t.group(2))))
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


def playlist_base_name(md):
    """Имя файла в дереве плеера: свойство `playlist` или имя файла."""
    try:
        lines = md.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            m = re.match(r"^playlist:\s*(.+?)\s*$", line)
            if m:
                value = m.group(1).strip()
                if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    return value
                break
    name = md.stem
    if "\\Adventure\\Locations\\" not in str(md):
        # Точка в начале уводит сквозные подборки наверх дерева плеера,
        # отдельно от мест на карте.
        name = "." + name
    return name


def playlist_title(md, scene):
    name = playlist_base_name(md)
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


def genre_of(path):
    """Строка тега genre или пустая строка."""
    try:
        from mutagen.id3 import ID3
        frames = ID3(path).getall("TCON")
    except Exception:
        return ""
    return frames[0].text[0] if frames and frames[0].text else ""


def has_meta(genre, value):
    """Есть ли значение в категории Meta."""
    for chunk in genre.split():
        category, _, values = chunk.partition(":")
        if category == "Meta" and value in values.split(","):
            return True
    return False


def repath_track_everywhere(files, old_path, new_path, apply):
    """Переписывает ссылки на трек, когда файл переехал в другую папку."""
    old_url = "file:///" + urllib.parse.quote(old_path.replace("\\", "/"), safe="/:")
    new_url = "file:///" + urllib.parse.quote(new_path.replace("\\", "/"), safe="/:")
    count = 0
    for md, data in files.items():
        if not any(old_url in line for line in data["lines"]):
            continue
        lines = [line.replace(old_url, new_url) for line in data["lines"]]
        count += sum(1 for line in data["lines"] if old_url in line)
        if apply:
            data["lines"] = lines
            write_lines(md, lines)
    if apply:
        count += repath_playlists(old_path, new_path)
        repath_rejected(old_path, new_path)
    return count


def repath_rejected(old_path, new_path):
    """Тот же переезд в журнале отказов: Export-Playlist сверяет по полному
    пути, и отказ со старым путём из Unsorted молча перестал бы работать.
    Регистр не учитывается: журнал местами пишут руками."""
    if not REJECTED.exists():
        return
    raw = REJECTED.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    fixed = re.sub(re.escape(old_path), lambda _m: new_path, text, flags=re.IGNORECASE)
    if fixed != text:
        REJECTED.write_bytes((b"\xef\xbb\xbf" if bom else b"") + fixed.encode("utf-8"))


def repath_playlists(old_path, new_path):
    """Тот же переезд в .m3u8: каталог плеера и выгрузка в `_playlists`.

    Без этого следующий прогон не находит новый путь в каталоге плеера и
    считает трек удалённым Мастером - и сносит его со страницы. Файлы
    правятся байт в байт: BOM и окончания строк остаются, какими были.
    Обход через listdir, а не glob: glob пропускает имена с точкой, а
    сцены кампании называются именно так.
    """
    count = 0
    for folder in (CATALOG, PLAYLISTS):
        if not folder.exists():
            continue
        for name in os.listdir(folder):
            if not name.lower().endswith(".m3u8"):
                continue
            m3u = folder / name
            raw = m3u.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
            hits = text.count(old_path)
            if not hits:
                continue
            m3u.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.replace(old_path, new_path).encode("utf-8"))
            count += hits
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


def stars_of(path):
    """Оценка трека из файла: число звёзд, либо None, если её там нет.

    Ноль во фрейме POPM - это осознанно снятая оценка, а не её отсутствие.
    """
    try:
        from mutagen.id3 import ID3
        popm = ID3(path).getall("POPM")
    except Exception:
        return None
    if not popm:
        return None
    best = max(f.rating for f in popm)
    for stars, edge in ((5, 224), (4, 160), (3, 96), (2, 32), (1, 1)):
        if best >= edge:
            return stars
    return 0


def set_stars(path, stars):
    """Переносит оценку из базы плеера в сам файл."""
    try:
        from mutagen.id3 import ID3, POPM
        from mutagen.id3._util import ID3NoHeaderError
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("POPM")
        tags.add(POPM(email="rating@winamp.com",
                      rating={1: 1, 2: 64, 3: 128, 4: 196, 5: 255}.get(stars, 0),
                      count=0))
        tags.save(path, v2_version=3)
        return True
    except Exception:
        return False


def handle_ratings(files, apply):
    """Любая оценка означает, что трек отслушан.

    Раньше смысл был у двух значений: одна звезда выбрасывала трек, пять
    снимали пометку «не отслушано». Теперь звёзды - просто оценка, а
    выбрасывает отдельный тег Meta:Delete. Отслушанным же трек делает сам
    факт оценки: Мастер её поставил, значит слушал.

    Оценок два источника: база медиатеки плеера и фрейм POPM в самом
    файле, куда пишет Start-WinampPlaylist. Правда - файл, потому что база
    привязана к путям и осиротеет при первом же переименовании. Поэтому
    здесь оценки из базы сперва вливаются в файлы, где их ещё нет, а
    дальше работа идёт только по файлам.

    Отслушанный трек уезжает из Music\\Unsorted в обычную папку франшизы -
    ту же по имени, уровнем выше. Ссылки в файлах кампании переписываются
    на новый путь, звёздочка неотслушанного снимается.
    """
    from_db = read_all_ratings()
    merged = 0
    for path, stars in from_db.items():
        if stars and Path(path).exists() and stars_of(path) is None:
            merged += 1
            if apply:
                set_stars(path, stars)
    if merged:
        print(f"  перенесено оценок из плеера в файлы: {merged}")

    rated = {}
    for mp3 in MUSIC.rglob("*.mp3"):
        if DELETED in mp3.parents:
            continue
        stars = stars_of(str(mp3))
        if not stars:
            # Либо оценки нет, либо она снята - в обоих случаях делать нечего.
            # На сухом прогоне оценка из базы ещё не переехала в файл.
            if not apply and from_db.get(str(mp3), 0) and stars is None:
                stars = from_db[str(mp3)]
            else:
                continue
        rated[str(mp3)] = stars
    print(f"  оценённых треков: {len(rated)}")

    promoted = moved = 0
    for path, stars in sorted(rated.items()):
        mp3 = Path(path)
        unsorted = has_unsorted_tag(str(mp3))
        in_unsorted_folder = (MUSIC / "Unsorted") in mp3.parents
        if not unsorted and not in_unsorted_folder:
            continue

        promoted += 1
        if unsorted:
            print(f"  {stars}*: {mp3.name} -> снять Unsorted")
            if apply and clear_unsorted_tag(str(mp3)):
                unstar(files, str(mp3))

        # Раскладка по франшизам: Unsorted\Witcher -> Witcher. Огрызки из
        # Unsorted\Misc так же едут в общий Misc.
        if in_unsorted_folder:
            target_dir = MUSIC / mp3.parent.name
            target = target_dir / mp3.name
            if target.exists():
                print(f"  {stars}*: {mp3.name} -> в {target_dir.name} уже есть такой, "
                      "оставляю на месте")
                continue
            moved += 1
            print(f"  {stars}*: {mp3.name} -> {target_dir.name}\\")
            if apply:
                target_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(mp3), str(target))
                except OSError as exc:
                    # Winamp держит играющий файл и всё, что в открытых
                    # плейлистах. Тег записать он даёт, а переместить нет,
                    # поэтому переезд просто откладывается до следующего раза.
                    moved -= 1
                    print(f"     занят плеером, оставляю на месте: {exc.strerror or exc}")
                    continue
                repath_track_everywhere(files, str(mp3), str(target), apply)
    return promoted, moved


def handle_pending_moves(files, apply):
    """Выполняет отложенные действия: теги Delete и Excluded переносят файл.

    Тег ставится на слух и означает решение о треке: Delete - послушали и не
    понравилось, Excluded - отложили на потом. Исполняется решение здесь:
    файл уезжает в свою папку, ссылки на него уходят из подборок кампании -
    ни выброшенный, ни отложенный в игре не звучат.

    Тег после переезда остаётся: он описывает состояние трека, а не разовое
    поручение, и по нему видно, почему файл оказался в этой папке. Повторный
    прогон такие треки просто не трогает - они уже на месте.
    """
    moves = {"Delete": DELETED, "Excluded": MUSIC / "Excluded"}
    done = {"Delete": 0, "Excluded": 0}

    for mp3 in sorted(MUSIC.rglob("*.mp3")):
        genre = genre_of(str(mp3))
        for value, target_dir in moves.items():
            if not has_meta(genre, value):
                continue
            if target_dir in mp3.parents:
                continue        # уже там, где просили
            done[value] += 1
            target = target_dir / mp3.name
            if target.exists():
                target = target_dir / f"{mp3.stem} ({mp3.parent.name}){mp3.suffix}"
            print(f"  {value}: {mp3.name} -> {target_dir.name}\\")
            if apply:
                target_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(mp3), str(target))
                except OSError as exc:
                    done[value] -= 1
                    print(f"     занят плеером, оставляю на месте: {exc.strerror or exc}")
                    break
                drop_track_everywhere(files, str(mp3), apply)
            break
    return done


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

    Третье значение - путь -> имена списков, где он лежит: по нему журнал
    отказов узнаёт название плейлиста ситуации или эффекта, у которых в
    разделе музыки нет своего заголовка.
    """
    names, paths, where = set(), set(), {}
    if not PLAYLISTS.exists():
        return names, paths, where
    for m3u in PLAYLISTS.glob("*.m3u8"):
        names.add(m3u.stem)
        for line in m3u.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                paths.add(line.lower())
                where.setdefault(line.lower(), []).append(m3u.stem)
    return names, paths, where


def log_rejected(rows):
    """Дописывает отказы Мастера в Music\\Rejected.csv.

    Удаление трека из сцены в плеере - решение «сюда не подходит». Без
    журнала оно пропадает вместе со строкой в markdown, и при следующем
    подборе тот же трек возвращается в ту же сцену. Формат как у
    остальных csv в Music: UTF-8 с BOM, CRLF.
    """
    import csv
    import datetime
    new = not REJECTED.exists()
    today = datetime.date.today().isoformat()
    with open(REJECTED, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        out = csv.writer(f, lineterminator="\r\n")
        if new:
            out.writerow(["Date", "Playlist", "Track"])
        for playlist, path in rows:
            out.writerow([today, playlist, path])


def npc_playlists(md, lines, pages):
    """Названия списков плеера для темы NPC - так же, как их собирает
    Export-Playlist: `<локация> - НПС - <имя до запятой>` на каждую
    страницу из `location` карточки. Отыгранные локации (Done) в плеер не
    едут, их списки не в счёт."""
    titles = []
    if not lines or lines[0].strip() != "---":
        return titles
    in_key = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if re.match(r"^\S[^:]*:", line):
            in_key = line.startswith("location:")
        if not in_key:
            continue
        for target in re.findall(r"\[\[([^\]|#]+)", line):
            page = pages.get(target.strip())
            if page is None or "Done" in page.parts:
                continue
            name = md.stem.split(",")[0].strip()
            titles.append(f"{playlist_base_name(page)} - НПС - {name}")
    return titles


def main():
    apply = "--apply" in sys.argv
    catalog = read_catalog()
    files = scan_markdown()
    if not catalog:
        print("каталог Winamp пуст - нечего синхронизировать")
        return

    exported_names, exported_paths, exported_where = read_exported()
    pages = {}
    for page in ROOT.rglob("*.md"):
        if not any(p.startswith(".") for p in page.relative_to(ROOT).parts[:-1]):
            pages.setdefault(page.stem, page)

    # Все пути, которые плеер сейчас знает.
    alive = set()
    for tracks in catalog.values():
        alive.update(t.lower() for t in tracks)

    skipped = []
    removed = 0
    rejected = []
    for md, data in files.items():
        if "Done" in md.parts:
            # Отыгранные локации в плеер не выгружаются, поэтому отсутствие
            # их списков в каталоге не значит, что Мастер их удалил.
            continue
        drop = set()
        # Ситуации и эффекты живут каждый в своём списке из одного трека.
        # Удалён ли такой список, решаем по спискам этой же страницы, а не
        # по всему плееру: трек, переложенный Мастером в Бой, жив в каталоге,
        # но ситуация под него при этом удалена.
        base = playlist_base_name(md)
        local_single = set()
        base_in_player = False
        for name, tracks in catalog.items():
            if name.startswith(f"{base} - "):
                base_in_player = True
            if (name.startswith(f"{base} - Ситуация")
                    or name.startswith(f"{base} - Эффект")
                    or name.startswith(f"{base} - Фон")):
                local_single.update(t.lower() for t in tracks)
        for scene, items in data["scenes"].items():
            if scene == NPC_SCENE:
                # Тема NPC живёт в шапке карточки, и её список собирается
                # по `location`. Удалённое из списка в плеере уходит из
                # `music:` так же, как из сцены; удалённый целиком список -
                # вся тема. Если локаций несколько, трек остаётся, пока он
                # жив хоть в одном из её списков.
                titles = (npc_playlists(md, data["lines"], pages)
                          if "NPC" in md.parts else [])
                live = [t for t in titles if t in catalog]
                if live:
                    known = {p.lower() for t in live for p in catalog[t]}
                    for index, path in items:
                        if path.lower() not in known:
                            drop.add(index)
                            rejected.extend((t, path) for t in live)
                    continue
                gone = [t for t in titles if t in exported_names]
                if gone:
                    for index, path in items:
                        drop.add(index)
                        rejected.extend((t, path) for t in gone)
                elif titles:
                    skipped.extend(titles)
                continue
            title = playlist_title(md, scene)
            if title is None:
                # Ситуации и эффекты: плейлист на трек, ищем по пути.
                # Трек, которого плеер не знает и который туда никогда
                # не выгружался, - не удалённый, а новый. Страница, которой
                # под нынешним именем в плеере нет вовсе (переименовали и ещё
                # не выгрузили), не трогается: её списки висят под старым.
                if not base_in_player:
                    continue
                for index, path in items:
                    if (path.lower() not in local_single
                            and path.lower() in exported_paths):
                        drop.add(index)
                        own = [n for n in exported_where.get(path.lower(), [])
                               if n.startswith(f"{base} - ")]
                        rejected.append((own[0] if own else f"{base} - {scene}", path))
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
                for index, path in items:
                    drop.add(index)
                    rejected.append((title, path))
                if scene in data["headers"]:
                    drop.add(data["headers"][scene])
                continue
            known = {t.lower() for t in catalog[title]}
            for index, path in items:
                if path.lower() not in known:
                    drop.add(index)
                    rejected.append((title, path))

        if not drop:
            continue
        removed += len(drop)
        print(f"{md.stem}: убрать строк {len(drop)}")
        if apply:
            remove_lines(md, data, drop)

    print(f"строк к удалению: {removed}")
    if rejected:
        print(f"в журнал отказов {REJECTED.name}: {len(rejected)}")
        for playlist, path in rejected:
            print(f"  {playlist}: {Path(path).stem}")
        if apply:
            log_rejected(rejected)
    if skipped:
        print(f"не выгружалось в плеер, не трогаю: {len(skipped)}")
        for title in sorted(skipped):
            print(f"  {title}")
        print("  выгрузи их Export-Playlist, иначе правки оттуда не вернутся")

    print("звёзды:")
    promoted, moved = handle_ratings(files, apply)
    print(f"  отслушано: {promoted}, переложено из Unsorted: {moved}")

    print("отложенные действия:")
    done = handle_pending_moves(files, apply)
    print(f"  в Deleted: {done['Delete']}, в Excluded: {done['Excluded']}")

    if not apply:
        print("сухой прогон, для записи добавь --apply")


if __name__ == "__main__":
    main()
