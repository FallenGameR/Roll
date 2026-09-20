# -*- coding: utf-8 -*-
"""Ищет ссылки на заголовок, который в файле встречается несколько раз.

Obsidian уводит по такой ссылке на первое совпадение, а не туда, где
лежит нужное, — и молча: якорь-то существует.
"""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\vaults\Рудники Фанделвера\Adventure")

total = 0
for md in sorted(ROOT.rglob("*.md")):
    text = md.read_text(encoding="utf-8")
    heads = Counter(h.strip().lower()
                    for h in re.findall(r"^#{1,6}\s+(.+?)\s*$", text, re.MULTILINE))
    seen = set()
    for m in re.finditer(r"\[\[#([^\]|^]+)(?:\|([^\]]*))?\]\]", text):
        target = m.group(1).strip().rstrip("\\").lower()
        if heads.get(target, 0) > 1 and target not in seen:
            seen.add(target)
            total += 1
            print(f"{md.stem}: [[#{m.group(1)}]] — заголовок встречается "
                  f"{heads[target]} раза")
print("неоднозначных ссылок:", total)
