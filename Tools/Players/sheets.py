# -*- coding: utf-8 -*-
"""Лист персонажа под телефон, свёрстанный как статблок в Обсидиане.

Источник один: блок ```statblock``` карточки персонажа в `Adventure/Players`. Лист
повторяет его поле в поле, только вики-ссылки на заклинания превращаются в ссылки на
dnd.su, а у умений класса и расы появляются ссылки из словаря `links` персонажа.
Поправили статблок в карточке, перепечатали лист, и они снова совпадают.

Страница узкая, чтобы читалась на телефоне; у PDF есть закладки по разделам.

Запуск: `python sheets.py [имя файла персонажа ...]`, без имён печатает всех из SHEETS.
PDF ложится в `Adventure/Players/Sheets/<имя файла карточки>.pdf`.
"""
import base64
import html
import os
import re
import subprocess
import sys

import yaml

from levelup_lib import CACHE, EDGES, SPELLS, SU, VAULT, cls_url, spell_grid, spells, SPELL_NOTE

PLAYERS = VAULT / "Adventure" / "Players"
OUT = PLAYERS / "Sheets"

ABIL = ["Сил", "Лов", "Тел", "Инт", "Мдр", "Хар"]
SAVE = {"strength": "Сила", "dexterity": "Ловкость", "constitution": "Телосложение",
        "intelligence": "Интеллект", "wisdom": "Мудрость", "charisma": "Харизма"}

# слаг заклинания из волта (имя файла) -> карточка индекса dnd.su
SPELL_BY_SLUG = {c["link"].strip("/").split("/")[-1].split("-", 1)[1].replace("_", "-"): c for c in SPELLS}

CSS = """
@page { size: 90mm 190mm; margin: 0; }
html { background: #fdf1dc; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; padding: 4mm 4mm; font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt;
       color: #58180d; line-height: 1.35; border-top: 1.5mm solid #e69a28; }
a { color: #2a6fc0; font-style: italic; text-decoration: underline; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 3mm; }
h1 { font-family: Georgia, 'Times New Roman', serif; font-variant: small-caps; font-size: 20pt;
     color: #7a200d; margin: 1mm 0 0; letter-spacing: 0.3pt; }
.sub { font-style: italic; margin: 0.5mm 0 0; font-size: 9.5pt; }
.portrait { width: 22mm; height: 22mm; border-radius: 50%; flex: none; }
.rule { height: 1.3mm; margin: 2mm 0; background: #922610;
        clip-path: polygon(0 0, 100% 50%, 0 100%); }
.line { margin: 0.8mm 0; }
.line b { color: #7a200d; margin-right: 1mm; }
table.stats { width: 100%; border-collapse: collapse; text-align: center; margin: 0.5mm 0; }
table.stats th { color: #7a200d; font-weight: 700; padding: 0 0 0.5mm; }
table.stats td { padding: 0; white-space: nowrap; font-size: 9.5pt; }
.trait { margin: 1.4mm 0; break-inside: avoid; }
.trait > .n { font-weight: 700; font-style: italic; color: #7a200d; margin-right: 1mm; }
.trait > .n a { font-weight: 700; }
.trait i { font-style: italic; }
h2 { font-family: Georgia, 'Times New Roman', serif; font-variant: small-caps; font-weight: 400;
     font-size: 15pt; color: #7a200d; border-bottom: 1px solid #7a200d; margin: 4mm 0 1.5mm;
     padding-bottom: 0.3mm; break-after: avoid; }
.su { font-style: italic; font-weight: 400; color: #8a5a4a; font-size: 8.5pt; }
h3 { font-family: Georgia, 'Times New Roman', serif; font-size: 11.5pt; color: #7a200d; margin: 3mm 0 1mm;
     break-after: avoid; }
ul.grid { columns: 2; column-gap: 4mm; list-style: none; padding: 0; margin: 1mm 0; }
ul.grid li { break-inside: avoid; margin: 0 0 1.2mm; }
ul.grid a { font-style: normal; text-decoration: none; }
.star { color: #922610; font-weight: 700; }
.en { display: block; color: #a07a6a; font-size: 8pt; }
.tag { color: #922610; font-size: 8pt; }
.note { color: #8a5a4a; font-size: 8.5pt; margin: 1mm 0; }
@media screen { body { max-width: 82mm; margin: 0 auto; } }
"""

WIKI = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def spell_card(target):
    slug = target.split("#")[0].split("/")[-1].strip().lower()
    return SPELL_BY_SLUG.get(slug)


AVG = re.compile(r"\b\d+ \((\d+d\d+(?:\s*[+-]\s*\d+)?)\)")


def md(text):
    """Строка статблока в HTML: заклинания ссылками на dnd.su, прочие вики-ссылки текстом.

    Среднее перед формулой снимается: "9 (2d8)" даёт "2d8", игрок кидает кости сам.
    """
    text = AVG.sub(r"\1", text)
    out, pos = [], 0
    for m in WIKI.finditer(text):
        out.append(_plain(text[pos:m.start()]))
        target, cap = m.group(1), m.group(2) or m.group(1).split("#")[-1].split("/")[-1]
        c = spell_card(target)
        if c:
            out.append(f'<a href="{html.escape(SU + c["link"])}">{html.escape(cap)}</a>')
        else:
            out.append(html.escape(cap))
        pos = m.end()
    out.append(_plain(text[pos:]))
    return "".join(out)


def _plain(s):
    s = html.escape(s)
    return re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)


def line(label, value):
    return f'<div class="line"><b>{label}</b>{value}</div>'


def trait(item, links, override):
    name = item["name"]
    key = WIKI.sub(lambda m: m.group(2) or m.group(1), name).split(":")[0].strip()
    desc = override.get(key, item["desc"])
    if desc is None:
        return ""
    if key in links:
        n = f'<a href="{html.escape(links[key])}">{md(name)}</a>'
    else:
        n = md(name)
    return f'<div class="trait"><span class="n">{n}</span> {md(desc)}</div>'


def statblock(card):
    t = (PLAYERS / f"{card}.md").read_text(encoding="utf-8")
    block = re.search(r"```statblock\n(.*?)\n```", t, re.S).group(1)
    return yaml.safe_load(block)


def sheet(card, links, tail=""):
    sb = statblock(card)
    img = "data:image/png;base64," + base64.b64encode((VAULT / sb["image"]).read_bytes()).decode()
    stats = sb["stats"]
    mods = [(s - 10) // 2 for s in stats]
    saves = ", ".join(f"{SAVE[k]} {v:+d}" for d in sb.get("saves", []) for k, v in d.items())
    skills = ", ".join(f"{md(s['name'])} {s['desc']}" for s in sb.get("skillsaves", []))
    senses = md(sb.get("senses", "")).replace("passive Perception", "пассивное Восприятие")
    prof = 2 + (int(re.search(r"\d+", str(sb.get("level", "")) or "0").group(0)) - 1) // 4 \
        if sb.get("level") else 2

    parts = [
        '<div class="head"><div>',
        f'<h1 id="top">{html.escape(sb["name"])}</h1>',
        f'<p class="sub">{html.escape(sb["size"])}, {html.escape(sb["type"])}, {html.escape(sb["subtype"])}</p>',
        f'</div><img class="portrait" src="{img}"></div>',
        '<div class="rule"></div>',
        line("Класс доспеха", f'{sb["ac"]} ({md(sb.get("ac_class", ""))})'),
        line("Хиты", f'{sb["hp"]} ({sb["hit_dice"]})'),
        line("Скорость", html.escape(sb["speed"])),
        '<div class="rule"></div>',
        '<table class="stats"><tr>' + "".join(f"<th>{a}</th>" for a in ABIL) + "</tr><tr>"
        + "".join(f"<td>{s} ({m:+d})</td>" for s, m in zip(stats, mods)) + "</tr></table>",
        '<div class="rule"></div>',
        line("Спасброски", saves),
        line("Навыки", skills),
        line("Чувства", senses),
        line("Языки", html.escape(sb.get("languages", ""))),
        line("Бонус мастерства", f"+{prof}"),
        '<div class="rule"></div>',
        '<h2 id="traits">Умения</h2>',
    ]
    parts += [trait(x, links) for x in sb.get("traits", [])]
    if sb.get("actions"):
        parts.append('<h2 id="actions">Действия</h2>')
        parts += [trait(x, links) for x in sb["actions"]]
    if sb.get("bonus_actions"):
        parts.append('<h2 id="bonus">Бонусные действия</h2>')
        parts += [trait(x, links) for x in sb["bonus_actions"]]
    if sb.get("reactions"):
        parts.append('<h2 id="reactions">Реакции</h2>')
        parts += [trait(x, links) for x in sb["reactions"]]
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{html.escape(sb["name"])}</title>'
            f'<style>{CSS}</style></head><body>' + "".join(parts) + tail + "</body></html>")


def dru(anchor):
    return cls_url("druid", anchor)


TIEFLING = SU + "/race/86-tiefling/#osobennosti_tiflingov"


def prepare_block(cls, max_level, marks):
    """Список класса по кругам, от заговоров до `max_level`, внутри круга по алфавиту."""
    parts = ['<h2 id="prepare">Что можно подготовить</h2>',
             '<p class="note">Звёздочкой отмечено то, что у тебя есть сейчас.</p>',
             '<h3>Заговоры</h3>',
             '<p class="note">Заговоры не готовятся: какие знаешь, те и твои.</p>',
             spell_grid(spells(cls, 0), marks)]
    for lvl in range(1, max_level + 1):
        parts += [f'<h3>{lvl} круг</h3>', spell_grid(spells(cls, lvl), marks)]
    return "".join(parts) + SPELL_NOTE

SHEETS = {
    "Кали Мейхем": lambda: sheet("Кали Мейхем", {
        "Адская стойкость": TIEFLING,
        "Адское наследие": TIEFLING,
        "Дикий облик": dru("feature.wild-shape"),
        "Друидический язык": dru("feature.druidic"),
        "Дух дикого огня": dru("circle.wildfire"),
        "Магия друида": dru("feature.spellcasting"),
    }, tail=prepare_block("druid", 1, {"druidcraft", "shillelagh", "thunderwave", "entangle", "burning hands",
                                       "cure wounds"})),
}


def render(names):
    edge = next(e for e in EDGES if os.path.exists(e))
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / "html"
    tmp.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = tmp / f"sheet-{name}.html"
        src.write_text(SHEETS[name](), encoding="utf-8")
        pdf = OUT / f"{name}.pdf"
        subprocess.run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        "--generate-pdf-document-outline", f"--print-to-pdf={pdf}", src.as_uri()],
                       check=True, capture_output=True)
        print(pdf)


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    render(args or list(SHEETS))
