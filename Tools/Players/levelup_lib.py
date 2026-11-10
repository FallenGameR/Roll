# -*- coding: utf-8 -*-
"""Общая часть раздаток на повышение уровня: индексы dnd.su, вёрстка, печать в PDF.

Сам по себе не запускается. Его импортирует файл уровня, например
`levelup-2.py`, где лежат тексты под каждого персонажа.

Что здесь есть:
  * `spells(cls, level, exclude)` - заклинания класса нужного круга из индекса
    dnd.su, только из книг BOOKS, с учётом расширенных списков Таши;
  * `sp(en)` и `beast(en)` - ссылка на заклинание или зверя по английскому имени;
  * `table`, `ul`, `h2`, `p`, `spell_grid`, `page` - кирпичи HTML-страницы;
  * `render(docs, level)` - печатает словарь {персонаж: html} в
    `Adventure/Players/Characters/Levelup/Уровень N/<персонаж>.pdf` через Edge.

Индексы dnd.su. Страницы списков на сайте пустые и подгружают содержимое
скриптом, поэтому качаются сами куски `/piece/spells/index-list/` и
`/piece/bestiary/index-list/`. Они кешируются в %TEMP%/dndsu на сутки;
ключ `--refresh` у файла уровня качает заново.

Номера в индексе заклинаний:
  классы  - бард 12, жрец 13, паладин 16, следопыт 17, чародей 19,
            колдун 20, волшебник 21, друид 22, изобретатель 23;
  книги   - PHB 102, XGE 109, TCE 117.
`filter_class` - основной список класса, `filter_class_tce` - то, что
добавила Таша.
"""
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

SU = "https://dnd.su"
VAULT = pathlib.Path(r"C:\vaults\Рудники Фанделвера")
OUT_ROOT = VAULT / "Adventure" / "Players" / "Characters" / "Levelup"
CACHE = pathlib.Path(tempfile.gettempdir()) / "dndsu"
EDGES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

CLS = {"bard": 12, "cleric": 13, "paladin": 16, "ranger": 17, "sorcerer": 19,
       "warlock": 20, "wizard": 21, "druid": 22}
BOOKS = {102, 109, 117}  # PHB, XGE, TCE

CLASS_PAGE = {
    "barbarian": "/class/87-barbarian/", "bard": "/class/88-bard/", "cleric": "/class/89-cleric/",
    "druid": "/class/90-druid/", "fighter": "/class/91-fighter/", "monk": "/class/93-monk/",
    "paladin": "/class/94-paladin/", "ranger": "/class/97-ranger/", "rogue": "/class/99-rogue/",
    "sorcerer": "/class/101-sorcerer/", "warlock": "/class/104-warlock/", "wizard": "/class/105-wizard/",
}


def _fetch(piece, refresh):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / (piece.strip("/").replace("/", "-") + ".html")
    if refresh or not f.exists() or time.time() - f.stat().st_mtime > 86400:
        req = urllib.request.Request(SU + piece, headers={"User-Agent": "Mozilla/5.0"})
        f.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return f.read_text(encoding="utf-8")


REFRESH = "--refresh" in sys.argv
_spells_raw = _fetch("/piece/spells/index-list/", REFRESH)
SPELLS = json.loads(re.search(r"window\.LIST = (\{.*?\});?\s*</script>", _spells_raw, re.S).group(1))["cards"]
_beasts_raw = _fetch("/piece/bestiary/index-list/", REFRESH)
BEASTS = {ds.split(",")[1].strip().lower(): (t.strip(), h)
          for ds, h, t in re.findall(r"data-search='([^']*)'.*?href='([^']+)'.*?list-item-title'>([^<]*)<",
                                      _beasts_raw, re.S) if "," in ds}


def cls_url(cls, anchor=""):
    """Страница класса на dnd.su, с якорем вида `feature.wild-shape` или `circle.moon`."""
    return SU + CLASS_PAGE[cls] + (f"#{anchor}" if anchor else "")


def cantrips_url(cls):
    return f"{SU}/spells/?search=&level=0&class={CLS[cls]}"


def a(href, text):
    return f'<a href="{html.escape(href)}">{html.escape(text)}</a>'


def sp(en):
    """Ссылка на заклинание по английскому имени, подпись русская с dnd.su."""
    x = next(c for c in SPELLS if c["title_en"].lower() == en.lower())
    return a(SU + x["link"], x["title"])


def beast(en):
    t, h = BEASTS[en.lower()]
    return a(SU + h, t)


def beasts(*names):
    return ", ".join(beast(n) for n in names)


def spells(cls, level, exclude=()):
    lvl = "Заговор" if level == 0 else str(level)
    cid = CLS[cls]
    ex = {e.lower() for e in exclude}
    out = [x for x in SPELLS if x["level"] == lvl
           and (cid in x["filter_class"] or cid in x["filter_class_tce"])
           and set(x["filter_source"]) & BOOKS and x["title_en"].lower() not in ex]
    return sorted(out, key=lambda x: x["title"])


def spell_grid(lst, mark=()):
    """Сетка в три колонки. `mark` - английские имена, которые помечаются звёздочкой."""
    mk = {m.lower() for m in mark}
    items = []
    for x in lst:
        tags = []
        if "2" in x["filter_concentration"]:
            tags.append("К")
        if "2" in x["filter_ritual"]:
            tags.append("Р")
        tag = f' <span class="tag">{", ".join(tags)}</span>' if tags else ""
        star = '<span class="star">* </span>' if x["title_en"].lower() in mk else ""
        items.append(f'<li>{star}{a(SU + x["link"], x["title"])}{tag}'
                     f'<span class="en">{html.escape(x["title_en"])}</span></li>')
    return '<ul class="grid">' + "".join(items) + "</ul>"


SPELL_NOTE = '<p class="note">К - концентрация, Р - можно колдовать ритуалом.</p>'


def table(head, rows):
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def ul(*items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def h2(t):
    return f"<h2>{t}</h2>"


def p(t, note=False):
    return f'<p class="note">{t}</p>' if note else f"<p>{t}</p>"


CSS = """
@page { size: A4; margin: 12mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; color: #222; line-height: 1.3; }
h1 { font-family: Georgia, serif; font-size: 20pt; margin: 0 0 2mm; color: #5a2a12; }
h2 { font-family: Georgia, serif; font-size: 13pt; margin: 5mm 0 1.5mm; color: #5a2a12;
     border-bottom: 1px solid #c9a97a; padding-bottom: 0.5mm; break-after: avoid; }
p { margin: 1mm 0 1.5mm; }
.lead { color: #555; }
a { color: #1d4f91; text-decoration: none; }
table { border-collapse: collapse; width: 100%; margin: 1mm 0 2mm; table-layout: fixed; }
tr { break-inside: avoid; }
th, td { border: 1px solid #d6c3a3; padding: 1.2mm 2mm; vertical-align: top; text-align: left; }
th { background: #f3e9d7; font-weight: 600; }
th:first-child { width: 30%; }
ul { margin: 1mm 0 2mm; padding-left: 5mm; }
li { margin: 0.6mm 0; }
ul.grid { columns: 3; column-gap: 6mm; list-style: none; padding: 0; }
ul.grid li { break-inside: avoid; margin: 0 0 1.2mm; }
.star { color: #a0522d; font-weight: 700; }
.en { display: block; color: #888; font-size: 8.5pt; }
.tag { color: #a0522d; font-size: 8.5pt; }
.note { color: #666; font-size: 9pt; }
"""

LEVEL_WORD = {2: "второй", 3: "третий", 4: "четвёртый", 5: "пятый", 6: "шестой", 7: "седьмой",
              8: "восьмой", 9: "девятый", 10: "десятый"}
LEVEL_LOC = {2: "втором", 3: "третьем", 4: "четвёртом", 5: "пятом", 6: "шестом", 7: "седьмом",
             8: "восьмом", 9: "девятом", 10: "десятом"}


def page(name, level, sections):
    word = LEVEL_WORD.get(level, f"{level}-й")
    title = f"{name}: {word} уровень"
    intro = (f"Что поменять в бланке на {LEVEL_LOC.get(level, f'{level}-м')} уровне. Всё уже посчитано, "
             "ссылки ведут на dnd.su. Книги: Книга игрока, Занатар и Таша.")
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{title}</title>'
            f'<style>{CSS}</style></head><body><h1>{title}</h1><p class="lead">{intro}</p>'
            + "".join(sections) + "</body></html>")


def render(docs, level):
    """docs: {имя файла персонажа: html}. Печатает PDF и возвращает пути."""
    edge = next(e for e in EDGES if os.path.exists(e))
    out = OUT_ROOT / f"Уровень {level}"
    out.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / "html"
    tmp.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, doc in docs.items():
        src = tmp / f"{name}.html"
        src.write_text(doc, encoding="utf-8")
        pdf = out / f"{name}.pdf"
        subprocess.run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", src.as_uri()], check=True, capture_output=True)
        paths.append(pdf)
        print(pdf)
    return paths
