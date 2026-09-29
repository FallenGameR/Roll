# -*- coding: utf-8 -*-
"""Делит звуковой антураж локации на `## Атмосфера` и `## Эффекты`.

Атмосфера — то, что играет петлёй и не требует внимания: метель, капель,
шум стройки. Эффект — разовое событие: рык, обвал, вой, лай. Делить надо
потому, что каждая секция едет в плеер отдельным плейлистом и крутится в
случайном порядке: рык посреди метели ломает сцену.

Основной признак — длительность (в папке эффектов разрыв между 122 и 176
секундами), но он лишь прокси. Решает характер звука: непрерывный
процесс — петля, даже если запись короткая. Такие треки перечислены в
SHORT_LOOPS явно.
"""
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

FFPROBE = next(
    Path(r"C:\Users\alexk\AppData\Local\Microsoft\WinGet\Packages").glob(
        "Gyan.FFmpeg_*/**/ffprobe.exe"))

ROOT = Path(r"C:\vaults\Рудники Фанделвера\Adventure\Locations")
LOOP_SECONDS = 150

# Короткие записи непрерывного процесса: жёрнов мелет, шаги шуршат,
# сердце стучит, рой жужжит. Зацикливаются без слышимого стыка.
SHORT_LOOPS = {
    "Effect - Stone Grinder",
    "Effect - Dry Branches",
    "Effect - Heartbeat Suspense (Jonas West)",
    "Effect - Fly Swarm",
}

AMBIENCE, ONESHOT = "## Атмосфера", "## Эффекты"
OLD_SECTIONS = ("## Атмосфера", "## Эффекты", "## Удары")

_cache = {}


def is_loop(url):
    path = Path(urllib.parse.unquote(url))
    if path.stem in SHORT_LOOPS:
        return True
    if path not in _cache:
        out = subprocess.run(
            [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True).stdout.strip()
        _cache[path] = float(out) if out else 0.0
    return _cache[path] >= LOOP_SECONDS


def main():
    apply = "--apply" in sys.argv
    header = re.compile(r"^#{1,6} ", re.MULTILINE)

    for md in sorted(ROOT.glob("*.md")):
        text = md.read_text(encoding="utf-8")

        # Собираем строки всех имеющихся секций антуража и вырезаем их.
        loops, hits, cut_from = [], [], None
        for section in OLD_SECTIONS:
            while True:
                start = text.find(f"\n{section}\n")
                if start < 0:
                    break
                body_start = start + len(section) + 2
                nxt = header.search(text, body_start)
                end = nxt.start() if nxt else len(text)
                for line in text[body_start:end].splitlines():
                    m = re.search(r"file:///(C:/vaults/Music/[^)\s]+)", line)
                    if m:
                        (loops if is_loop(m.group(1)) else hits).append(line)
                cut_from = start if cut_from is None else min(cut_from, start)
                text = text[:start] + text[end:]

        if cut_from is None:
            continue

        print(f"{md.stem}: атмосфера {len(loops)}, эффекты {len(hits)}")
        if not apply:
            continue

        blocks = []
        if loops:
            blocks.append(f"\n{AMBIENCE}\n\n" + "\n".join(loops) + "\n")
        if hits:
            blocks.append(f"\n{ONESHOT}\n\n" + "\n".join(hits) + "\n")
        md.write_text(text[:cut_from] + "".join(blocks) + text[cut_from:],
                      encoding="utf-8")


if __name__ == "__main__":
    main()
