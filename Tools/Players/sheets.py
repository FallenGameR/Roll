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
@page { size: 90mm 2000mm; margin: 0; }
html { background: #fdf1dc; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; padding: 3mm 3mm; font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt;
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
.slot { font-style: normal; display: inline-block; }
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
    s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)
    return re.sub(r"([◯①-⑨])", r'<span class="slot">\1</span>', s)


def line(label, value):
    return f'<div class="line"><b>{label}</b>{value}</div>'


def trait(item, links, override):
    name = item["name"]
    key = re.sub(r"[◯①-⑨]", "", WIKI.sub(lambda m: m.group(2) or m.group(1), name)).split(":")[0].strip()
    desc = override.get(key, item["desc"])
    if desc is None:
        return ""
    if key in links:
        slots = "".join(re.findall(r"[◯①-⑨]", name))
        bare = re.sub(r"\s*[◯①-⑨]", "", name)
        n = f'<a href="{html.escape(links[key])}">{md(bare)}</a>'
        if slots:
            n += " " + _plain(slots)
    else:
        n = md(name)
    return f'<div class="trait"><span class="n">{n}</span> {md(desc)}</div>'


def frontmatter(card):
    t = (PLAYERS / f"{card}.md").read_text(encoding="utf-8")
    return yaml.safe_load(t.split("---")[1])


def statblock(card):
    t = (PLAYERS / f"{card}.md").read_text(encoding="utf-8")
    block = re.search(r"```statblock\n(.*?)\n```", t, re.S).group(1)
    return yaml.safe_load(block)


def sheet(card, cls, race_url, links, tail="", override=None):
    """`override` - текст умения для листа вместо текста карточки, None убирает умение.

    Нужен там, где карточка пишет Мастеру о будущих уровнях: в листе только то, что есть сейчас.
    """
    override = override or {}
    sb = statblock(card)
    level = int(frontmatter(card)["level"])
    img = "data:image/png;base64," + base64.b64encode((VAULT / sb["image"]).read_bytes()).decode()
    stats = sb["stats"]
    mods = [(s - 10) // 2 for s in stats]
    saves = ", ".join(f"{SAVE[k]} {v:+d}" for d in sb.get("saves", []) for k, v in d.items())
    skills = ", ".join(f"{md(s['name'])} {s['desc']}" for s in sb.get("skillsaves", []))
    senses = md(sb.get("senses", "")).replace("passive Perception", "пассивное Восприятие")
    prof = 2 + (level - 1) // 4

    parts = [
        '<div class="head"><div>',
        f'<h1 id="top">{html.escape(sb["name"])}</h1>',
        f'<p class="sub"><a href="{html.escape(race_url)}">{html.escape(sb["type"].capitalize())}</a>, '
        f'<a href="{html.escape(cls_url(cls))}">{html.escape(sb["subtype"])} {level}</a></p>',
        f'</div><img class="portrait" src="{img}"></div>',
        '<div class="rule"></div>',
        line("Класс доспеха", f'{sb["ac"]} ({md(sb["ac_class"])})' if sb.get("ac_class") else str(sb["ac"])),
        line("Хиты", f'{sb["hp"]}, кости хитов {sb["hit_dice"]}'),
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
    parts += [trait(x, links, override) for x in sb.get("traits", [])]
    if sb.get("actions"):
        parts.append('<h2 id="actions">Действия</h2>')
        parts += [trait(x, links, override) for x in sb["actions"]]
    if sb.get("bonus_actions"):
        parts.append('<h2 id="bonus">Бонусные действия</h2>')
        parts += [trait(x, links, override) for x in sb["bonus_actions"]]
    if sb.get("reactions"):
        parts.append('<h2 id="reactions">Реакции</h2>')
        parts += [trait(x, links, override) for x in sb["reactions"]]
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{html.escape(sb["name"])}</title>'
            f'<style>{CSS}</style></head><body>' + "".join(parts) + tail + "</body></html>")


def dru(anchor):
    return cls_url("druid", anchor)


TIEFLING = SU + "/race/86-tiefling/#osobennosti_tiflingov"
TIEFLING_RACE = SU + "/race/86-tiefling/"
HUMAN_RACE = SU + "/race/81-human/"
DWARF_RACE = SU + "/race/78-dwarf/"
ELF_RACE = SU + "/race/79-elf/"
HALF_ELF_RACE = SU + "/race/84-half-elf/"
TIEFLING_NOW = "Заговор [[thaumaturgy|Чудотворство]] колдуется Харизмой, без ячеек."


def prepare_block(cls, max_level, title="Что можно подготовить"):
    """Список класса по кругам, от заговоров до `max_level`, внутри круга по алфавиту.

    Кто готовит заклинания каждый день (друид, паладин) - "Что можно подготовить";
    кто знает их насовсем (бард, чародей, следопыт) - "Что можно выучить".
    """
    parts = [f'<h2 id="prepare">{title}</h2>']
    cantrips = spells(cls, 0)
    if cantrips:
        parts += ['<h3>Заговоры</h3>', spell_grid(cantrips)]
    for lvl in range(1, max_level + 1):
        parts += [f'<h3>{lvl} круг</h3>', spell_grid(spells(cls, lvl))]
    return "".join(parts) + SPELL_NOTE


def feat(cls):
    return lambda anchor: cls_url(cls, anchor)


ran, pal, bard, sor, rog = feat("ranger"), feat("paladin"), feat("bard"), feat("sorcerer"), feat("rogue")
LEARN = "Что можно выучить"

SHEETS = {
    "Кали Мейхем": lambda: sheet("Кали Мейхем", "druid", TIEFLING_RACE, {
        "Адская стойкость": TIEFLING,
        "Адское наследие": TIEFLING,
        "Дикий облик": dru("feature.wild-shape"),
        "Друидический язык": dru("feature.druidic"),
        "Дух дикого огня": dru("circle.wildfire"),
        "Магия друида": dru("feature.spellcasting"),
    }, override={
        "Адское наследие": TIEFLING_NOW,
    }, tail=prepare_block("druid", 1)),

    "Эдрик": lambda: sheet("Эдрик", "ranger", HUMAN_RACE, {
        "Избранный враг": ran("feature.favored-enemy"),
        "Исследователь": ran("feature.natural-explorer"),
        "Магия следопыта": ran("feature.spellcasting"),
        "Сражение вслепую": ran("feature.fighting-style"),
    }, tail=prepare_block("ranger", 1, LEARN)),

    "Дворик Трахак": lambda: sheet("Дворик Трахак", "paladin", DWARF_RACE, {
        "Божественная кара": pal("feature.divine-smite"),
        "Божественное чувство": pal("feature.divine-sense"),
        "Дворфийская стойкость": DWARF_RACE,
        "Знание камня": DWARF_RACE,
        "Магия паладина": pal("feature.spellcasting"),
        "Наложение рук": pal("feature.lay-on-hands"),
        "Защита": pal("feature.fighting-style"),
    }, override={
        "Магия паладина": "Ячейки: ①①. После долгого отдыха готовит три заклинания 1-го круга из списка ниже.",
    }, tail=prepare_block("paladin", 1)),

    "Эйра": lambda: sheet("Эйра", "bard", ELF_RACE, {
        "Магическое вдохновение": bard("feature.magical-inspiration"),
        "Магия барда": bard("feature.spellcasting"),
        "Мастер на все руки": bard("feature.jack-of-all-trades"),
        "Наследие фей": ELF_RACE,
        "Песнь отдыха": bard("feature.song-of-rest"),
        "Транс": ELF_RACE,
        "Вдохновение барда": bard("feature.bardic-inspiration"),
    }, tail=prepare_block("bard", 1, LEARN)),

    "Ириван": lambda: sheet("Ириван", "sorcerer", HALF_ELF_RACE, {
        "Волна дикой магии": sor("origin.wild-magic"),
        "Магия чародея": sor("feature.spellcasting"),
        "Наследие фей": HALF_ELF_RACE,
        "Поток хаоса": sor("origin.wild-magic"),
        "Источник магии": sor("feature.font-of-magic"),
    }, tail=prepare_block("sorcerer", 1, LEARN)),

    "Калиостро Великолепный": lambda: sheet("Калиостро Великолепный", "rogue", TIEFLING_RACE, {
        "Адская стойкость": TIEFLING,
        "Адское наследие": TIEFLING,
        "Скрытая атака": rog("feature.sneak-attack"),
        "Экспертиза": rog("feature.expertise"),
        "Хитрое действие": rog("feature.cunning-action"),
    }, override={
        "Адское наследие": TIEFLING_NOW,
    }),
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
        trim(pdf)
        print(pdf)


def trim(pdf):
    """Страница печатается заведомо длинной, одной; здесь она обрезается по низу текста."""
    import fitz
    d = fitz.open(pdf)
    if d.page_count != 1:
        raise SystemExit(f"{pdf}: страниц {d.page_count}, лист не влез в одну, увеличь высоту @page")
    pg = d[0]
    bottom = max(b[3] for b in pg.get_text("blocks"))
    full = pg.mediabox  # в координатах PDF ось Y идёт снизу вверх, текст у верхнего края
    pg.set_mediabox(fitz.Rect(0, full.y1 - bottom - 12, full.x1, full.y1))
    tmp = pdf.with_suffix(".tmp.pdf")
    d.save(tmp, garbage=3, deflate=True)
    d.close()
    os.replace(tmp, pdf)


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    render(args or list(SHEETS))
