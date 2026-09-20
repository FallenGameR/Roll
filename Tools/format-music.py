# -*- coding: utf-8 -*-
"""Приводит раздел `# Music` локаций к текущему формату.

  * после заголовка нет пустой строки;
  * в сценах только строки треков, без вводных пояснений;
  * ситуация — ссылка на трек и ссылка на место в локации;
  * `Атмосфера` и `Эффекты` слиты в одни `Эффекты`, петли идут первыми
    и помечены «— цикл», разовые звуки без примечаний.
"""
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\vaults\Рудники Фанделвера\Adventure\Locations")
ORDER = ["Фон", "Бой", "Ситуации", "Эффекты"]

link = re.compile(r"^- (?:\*[^*]+\*\s+)?(\[[^\]]+\]\(file:[^)]+\))(\s*\*)?(.*)$")
wiki = re.compile(r"\[\[[^\]]+\]\]")

todo = []


def rebuild(md):
    text = md.read_text(encoding="utf-8")
    start = text.find("\n# Music")
    if start < 0:
        return None
    head, block = text[:start], text[start:]

    scenes = {}
    for m in re.finditer(r"^## (.+?)\s*$", block, re.MULTILINE):
        name = m.group(1).strip()
        nxt = re.search(r"^## ", block[m.end():], re.MULTILINE)
        body = block[m.end():m.end() + (nxt.start() if nxt else len(block))]
        scenes[name] = body

    out = {}
    for name, body in scenes.items():
        for line in body.splitlines():
            m = link.match(line.strip())
            if not m:
                continue
            track, star, tail = m.group(1), (m.group(2) or "").strip(), m.group(3)
            key = "Эффекты" if name in ("Атмосфера", "Эффекты") else name
            loop = name == "Атмосфера"

            if key == "Ситуации":
                place = wiki.search(tail)
                if place:
                    tail = f" — {place.group(0)}"
                else:
                    tail = ""
                    todo.append(f"{md.stem}: {track[:60]}")
            elif key == "Эффекты":
                tail = " — цикл" if loop else ""
            else:
                tail = ""

            entry = f"- {track}{(' ' + star) if star else ''}{tail}"
            out.setdefault(key, ([], []))[0 if loop else 1].append(entry)

    parts = ["# Music"]
    for name in ORDER:
        if name not in out:
            continue
        loops, rest = out[name]
        lines = loops + rest
        parts.append(f"\n## {name}\n" + "\n".join(lines))
    return head + "\n".join(parts) + "\n"


def main():
    apply = "--apply" in sys.argv
    for md in sorted(ROOT.glob("*.md")):
        new = rebuild(md)
        if new is None:
            continue
        if apply:
            md.write_text(new, encoding="utf-8")
        print(f"{'записан' if apply else 'готов'}: {md.stem}")
    if todo:
        print("\nбез ссылки на место (доделать руками):")
        for t in todo:
            print("  ", t)


if __name__ == "__main__":
    main()
