# -*- coding: utf-8 -*-
"""Наводит порядок в разделах музыки: сортировка и звёздочки.

Правило Мастера: внутри плейлиста сначала идут отслушанные треки по
алфавиту, следом неотслушанные — тоже по алфавиту. Звёздочка в
markdown обязана совпадать с тегом `Type:Unsorted` в самом mp3: файл
при этом может лежать где угодно, потому что перенос из папки
Unsorted — отдельная пакетная операция в конце кампании, а тег
снимается сразу, как только трек понравился.

Сортируется любой плейлист, где треки взаимозаменяемы: сцены
«Локация» и «Бой», сцены глав вроде «Дорога» и «Привал», а также
плоский список без сцены — так устроены сквозные подборки, нулевая
сессия и правила погони. Не трогаем только «Ситуации» и «Эффекты»:
там порядок смысловой, эффекты-петли идут первыми.
"""
import re
import sys
import urllib.parse
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"C:\vaults\Рудники Фанделвера")
UNSORTED_SCENES = ("Ситуации", "Эффекты")
head = re.compile(r"^(#{1,6})\s+(.*)$")
track = re.compile(r"\[([^\]]*)\]\(file:///([^)]+)\)")

_unsorted_cache = {}


def is_unsorted(path):
    """Неотслушанное определяется тегом, а не папкой."""
    if path in _unsorted_cache:
        return _unsorted_cache[path]
    result = "\\Unsorted\\" in path          # запасной признак
    try:
        from mutagen.id3 import ID3
        frames = ID3(path).getall("TCON")
        if frames and frames[0].text:
            result = "Unsorted" in frames[0].text[0]
    except Exception:
        pass
    _unsorted_cache[path] = result
    return result


def parse(line):
    """Возвращает (заголовок, путь, есть ли звёздочка) или None."""
    m = track.search(line)
    if not m:
        return None
    path = urllib.parse.unquote(m.group(2)).replace("/", "\\")
    # Звёздочка стоит сразу за ссылкой, а не в конце строки: у ситуаций
    # после неё идёт ещё тире и ссылка на комнату.
    starred = bool(re.match(r"\s*\*(\s|$)", line[m.end():]))
    return m.group(1), path, starred


def fix_star(line, unsorted):
    m = track.search(line)
    if not m:
        return line.rstrip()
    body = line.rstrip()
    tail = body[m.end():]
    has = bool(re.match(r"\s*\*(\s|$)", tail))
    if unsorted and not has:
        return body[:m.end()] + " *" + tail
    if not unsorted and has:
        return body[:m.end()] + re.sub(r"^\s*\*", "", tail)
    return body


def main():
    apply = "--apply" in sys.argv
    changed_files = stars = moved = 0

    for md in sorted(ROOT.rglob("*.md")):
        if "_Locations_backup" in str(md):
            continue
        lines = md.read_text(encoding="utf-8").splitlines()
        in_music = level = 0
        scene = ""
        block = []
        start = None
        touched = False

        def flush(end):
            """Сортирует накопленный блок треков и вписывает обратно."""
            nonlocal touched, moved
            if not block or scene in UNSORTED_SCENES:
                return
            order = sorted(
                block,
                key=lambda item: (item[1], item[2].lower()))
            if [b[0] for b in order] != [b[0] for b in block]:
                moved += 1
                touched = True
            for offset, item in enumerate(order):
                lines[start + offset] = item[3]

        for i, line in enumerate(lines):
            m = head.match(line)
            if m:
                flush(i)
                block, start = [], None
                lvl, title = len(m.group(1)), m.group(2).strip()
                if in_music and lvl <= level:
                    in_music = 0
                elif in_music:
                    scene = title
                    continue
                if title.lower() in ("music", "музыка"):
                    in_music, level, scene = 1, lvl, ""
                continue

            if not in_music:
                continue

            parsed = parse(line)
            if not parsed:
                flush(i)
                block, start = [], None
                continue

            name, path, starred = parsed
            unsorted = is_unsorted(path)
            fixed = fix_star(line, unsorted)
            if fixed != line.rstrip():
                stars += 1
                touched = True
            lines[i] = fixed

            if start is None:
                start = i
            block.append((i, unsorted, name, fixed))

        flush(len(lines))

        if touched:
            changed_files += 1
            if apply:
                # Канон вольта - LF, и задан он .gitattributes: write_text
                # на Windows молча поставил бы CRLF, и Обсидиан начал бы
                # показывать страницу изменённой при пустом diff.
                with open(md, "w", encoding="utf-8", newline="\n") as out:
                    out.write("\n".join(lines) + "\n")
            print(f"{md.stem}: порядок и пометки поправлены")

    print(f"файлов затронуто: {changed_files}, звёздочек исправлено: {stars}, "
          f"блоков пересортировано: {moved}")
    if not apply:
        print("это сухой прогон, для записи добавь --apply")


if __name__ == "__main__":
    main()
