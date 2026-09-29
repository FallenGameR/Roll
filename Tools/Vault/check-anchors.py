# -*- coding: utf-8 -*-
"""Проверяет, что якоря вида [[#Раздел]] указывают на существующий
заголовок того же файла."""
import re
from pathlib import Path

ROOT = Path(r"C:\vaults\Рудники Фанделвера\Adventure")

bad = 0
for md in sorted(ROOT.rglob("*.md")):
    text = md.read_text(encoding="utf-8")
    heads = {h.strip().lower()
             for h in re.findall(r"^#{1,6}\s+(.+?)\s*$", text, re.MULTILINE)}
    for m in re.finditer(r"\[\[#([^\]|^]+)(?:\|[^\]]*)?\]\]", text):
        target = m.group(1).strip().rstrip("\\").lower()
        if target and target not in heads:
            bad += 1
            print(f"{md.stem}: [[#{m.group(1)}]]")
print("битых якорей:", bad)
