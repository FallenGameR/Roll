# -*- coding: utf-8 -*-
"""PDF приключения -> markdown для Обсидиана, с картинками.

Вырос из конвертера сессии wh40k для двух книг Wrath & Glory, но под
конкретную вёрстку больше не заточен: всё, что там было зашито именами
шрифтов и координатами, здесь выводится из самой книги.

* Основной текст - размер и семейство шрифта, которыми набрано больше
  всего знаков. От него считаются абзацные отступы и порог заголовков.
* Заголовок - строка крупнее основного текста в 1.4 раза. Уровень берётся
  из оглавления PDF, если строка там есть, иначе по размеру.
* Колонтитулы, номера страниц, боковые закладки, водяные знаки - строки у
  краёв страницы, набранные не шрифтом основного текста и повторяющиеся на
  многих страницах (цифры при сравнении не учитываются).
* Буквица - одна-две буквы крупнее 30pt, приклеивается к первой строке
  рядом.
* Две колонки: читается сначала левая, потом правая; строка шире 55%
  страницы считается общей.
* Абзац - по отступу после строки с точкой, по вертикальному зазору, после
  заголовка или жирной строки-подзаголовка. Перенос со знаком «-» в конце
  строки склеивается.
* Картинки - только встречающиеся в книге один раз и крупнее 90pt (рамки,
  фоны и повторяющиеся украшения отсеиваются). Вырезаются рендером области
  страницы, чтобы легли маски и наложения. Первая страница - обложка
  целиком.
* На каждой странице метка `%% p. N %%`, страница с оглавлением пропускается.

Выход: <out>\\<title>.md и <out>\\img\\, UTF-8 без BOM, LF.

Использование:
    python pdf-to-markdown.py book.pdf --out DIR [--title T] [--language en]
        [--heading-font RE] [--skip-font RE] [--skip-text RE]
"""
import argparse
import collections
import os
import re
import sys

import fitz


def norm(t):
    return re.sub(r"[\W_]", "", t.lower())


def fix(t):
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2014", " - ").replace("\u2013", "-").replace("\u2026", "...").replace("\u00a0", " ")
    return t.replace("\ufb01", "fi").replace("\ufb02", "fl")


def family(font):
    return re.split(r"[-,]", font)[0]


def clean_inline(t):
    t = re.sub(r"\*\*\s*\*\*", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    # «exam- ple» -> «example»; дефис перед заглавной оставляем.
    t = re.sub(r"(\w)- (\w)", lambda m: m.group(1) + m.group(2) if m.group(2).islower() else m.group(0), t)
    return t.replace(" ,", ",").replace(" .", ".").strip()


class Book:
    def __init__(self, path, args):
        self.doc = fitz.open(path)
        self.args = args
        self.skip_font = re.compile(args.skip_font) if args.skip_font else None
        self.skip_text = re.compile(args.skip_text) if args.skip_text else None
        self.heading_font = re.compile(args.heading_font) if args.heading_font else None
        self.toc = {norm(t): lvl for lvl, t, _pg in self.doc.get_toc()}
        self.survey()

    def raw_lines(self, page):
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"].strip()]
                if spans:
                    yield l, spans

    def survey(self):
        """Один проход по книге: основной шрифт и повторяющиеся у краёв строки."""
        sizes, fonts = collections.Counter(), collections.Counter()
        for page in self.doc:
            for _l, spans in self.raw_lines(page):
                for s in spans:
                    n = len(s["text"].strip())
                    sizes[round(s["size"], 1)] += n
                    fonts[family(s["font"])] += n
        self.body = sizes.most_common(1)[0][0] if sizes else 9.0
        self.body_family = fonts.most_common(1)[0][0] if fonts else ""
        self.head_min = max(self.body * 1.4, self.body + 3)

        seen = collections.defaultdict(set)
        for page in self.doc:
            for l, spans in self.raw_lines(page):
                if self.at_edge(page, l["bbox"]) and family(spans[0]["font"]) != self.body_family:
                    seen[self.edge_key(l, spans)].add(page.number)
        # Закладка главы стоит только на страницах своей главы, поэтому порог
        # низкий: три страницы или десятая часть книги.
        need = max(3, len(self.doc) * 0.1)
        self.furniture = {k for k, pages in seen.items() if len(pages) >= need}

    @staticmethod
    def at_edge(page, bbox):
        W, H = page.rect.width, page.rect.height
        x0, y0, x1, y1 = bbox
        return y1 < H * 0.1 or y0 > H * 0.9 or x1 < W * 0.2 or x0 > W * 0.8

    @staticmethod
    def edge_key(l, spans):
        text = re.sub(r"\d+", "#", "".join(s["text"] for s in spans).strip())
        return text, spans[0]["font"], round(spans[0]["size"])

    def is_heading(self, l):
        if l["size"] < self.head_min or len(l["plain"]) > 120:
            return False
        return not self.heading_font or bool(self.heading_font.search(l["font"]))

    def span_md(self, s):
        t = fix(s["text"])
        if not t.strip():
            return t
        f = s["font"]
        lead = t[: len(t) - len(t.lstrip())]
        trail = t[len(t.rstrip()):]
        core = t.strip()
        # В заголовках жирность - свойство самого заголовка, звёздочки не нужны.
        if s["size"] >= self.head_min:
            return t
        if "Bold" in f or "Black" in f or "Heavy" in f:
            return f"{lead}**{core}**{trail}"
        if "Italic" in f or "Oblique" in f:
            return f"{lead}*{core}*{trail}"
        return t

    def page_lines(self, page):
        W = page.rect.width
        lines = []
        for l, spans in self.raw_lines(page):
            s0 = max(spans, key=lambda s: len(s["text"].strip()))
            plain = fix("".join(s["text"] for s in l["spans"])).strip()
            if self.skip_text and self.skip_text.search(plain):
                continue
            if self.skip_font and self.skip_font.search(s0["font"]):
                continue
            if self.at_edge(page, l["bbox"]) and self.edge_key(l, spans) in self.furniture:
                continue
            x0, y0, x1, y1 = l["bbox"]
            lines.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, size=round(s0["size"], 1), font=s0["font"],
                              text="".join(self.span_md(s) for s in l["spans"]), plain=plain))
        # Выровненный по ширине текст PyMuPDF режет на куски по словам:
        # склеиваем куски одной базовой линии, но не через середину страницы.
        lines.sort(key=lambda l: (round(l["y0"]), l["x0"]))
        merged = []
        for l in lines:
            m = merged[-1] if merged else None
            if (m and abs(m["y0"] - l["y0"]) < 2 and abs(m["size"] - l["size"]) < 0.5
                    and 0 <= l["x0"] - m["x1"] < 30 and not (m["x0"] < W / 2 - 15 <= l["x0"])):
                m["text"] = m["text"].rstrip() + " " + l["text"].lstrip()
                m["plain"] += " " + l["plain"]
                m["x1"] = l["x1"]
            else:
                merged.append(dict(l))
        lines = merged
        for cap in [l for l in lines if len(l["plain"]) <= 2 and l["size"] > 30]:
            lines.remove(cap)
            near = [l for l in lines if l["x0"] > cap["x0"] and -5 <= l["y0"] - cap["y0"] < 40]
            if near:
                tgt = min(near, key=lambda l: (l["y0"], l["x0"]))
                tgt["text"] = re.sub(r"^(\*\*)?", lambda m: (m.group(1) or "") + cap["plain"], tgt["text"], count=1)
                tgt["plain"] = cap["plain"] + tgt["plain"]
        for l in lines:
            l["col"] = 0 if l["x0"] < W / 2 - 15 or l["x1"] - l["x0"] > W * 0.55 else 1
        return lines

    def convert(self, out_dir, title):
        img_dir = os.path.join(out_dir, "img")
        os.makedirs(img_dir, exist_ok=True)
        uses = collections.Counter()
        for page in self.doc:
            for i in page.get_image_info(xrefs=True):
                uses[i["xref"]] += 1

        source = os.path.basename(self.doc.name)
        out = [f'---\ntitle: "{title}"\nsource: "{source}"\nlanguage: {self.args.language}\n---']
        images = 0
        for page in self.doc:
            pn = page.number + 1
            W, H = page.rect.width, page.rect.height
            head = page.get_text()[:400]
            if re.search(r"^\s*(CONTENTS|Contents|СОДЕРЖАНИЕ|Содержание|Оглавление)\s*$", head, re.M):
                continue
            if page.number == 0:
                images += 1
                name = f"{title} - p{pn:02d}-cover.jpg"
                page.get_pixmap(dpi=110).save(os.path.join(img_dir, name), jpg_quality=85)
                out.append(f"![[{name}]]")
                continue

            items = []
            for i in page.get_image_info(xrefs=True):
                x0, y0, x1, y1 = i["bbox"]
                w, h = x1 - x0, y1 - y0
                if uses[i["xref"]] > 1 or w < 90 or h < 90 or (w > W * 0.95 and h > H * 0.9):
                    continue
                images += 1
                name = f"{title} - p{pn:02d}-{images:02d}.jpg"
                page.get_pixmap(dpi=150, clip=fitz.Rect(i["bbox"]) & page.rect).save(
                    os.path.join(img_dir, name), jpg_quality=85)
                items.append((0 if (x0 + x1) / 2 < W / 2 else 1, y0, "img", name))
            lines = self.page_lines(page)
            items += [(l["col"], l["y0"], "line", l) for l in lines]
            items.sort(key=lambda it: (it[0], it[1]))

            margins = {}
            for col in (0, 1):
                xs = [l["x0"] for l in lines if l["col"] == col and abs(l["size"] - self.body) <= 2.5]
                if xs:
                    margins[col] = collections.Counter(round(x) for x in xs).most_common(1)[0][0]

            out.append(f"%% p. {pn} %%")
            para, prev = None, None

            def flush():
                nonlocal para
                if para:
                    out.append(clean_inline(" ".join(para)))
                para = None

            for col, _y, kind, it in items:
                if kind == "img":
                    flush()
                    out.append(f"![[{it}]]")
                    prev = None
                    continue
                l = it
                if self.is_heading(l):
                    flush()
                    # Заголовок в две строки: вторая дописывается к первой.
                    if (prev and prev.get("head") and prev["col"] == col
                            and abs(l["y0"] - prev["y1"]) < l["size"] * 1.2):
                        out[-1] += " " + l["plain"].title()
                    else:
                        lvl = self.toc.get(norm(l["plain"]))
                        if lvl is None:
                            lvl = 1 if l["size"] >= self.body * 2.5 else 2 if l["size"] >= self.body * 1.75 else 3
                        out.append("#" * min(lvl, 6) + " " + l["plain"].title())
                    prev = dict(l, head=True)
                    continue
                indent = l["x0"] - margins.get(col, l["x0"]) > 12
                gap = prev is not None and l["y0"] - prev["y1"] > l["size"] * 0.9
                newcol = prev is not None and prev.get("col") != col
                boldline = l["text"].startswith("**") and l["text"].rstrip().endswith("**") and len(l["plain"]) < 60
                ends = bool(para) and re.search(r"[.!?:)\"'*]\s*$", para[-1] or "") is not None
                indent = indent and (ends or not para)
                if para is None or indent or gap or prev.get("head") or boldline or prev.get("boldline"):
                    # Абзац, перетёкший в следующую колонку, не рвём.
                    if not (newcol and para and not indent and not boldline and not gap):
                        flush()
                        para = []
                text = l["text"].rstrip()
                if para and para[-1].endswith("-") and not para[-1].endswith(" -"):
                    para[-1] = para[-1][:-1] + text.lstrip()
                else:
                    para.append(text)
                prev = dict(l, boldline=boldline)
            flush()

        md = re.sub(r"\n{3,}", "\n\n", "\n\n".join(x for x in out if x.strip()))
        path = os.path.join(out_dir, f"{title}.md")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(md + "\n")
        return path, images


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--language", default="en")
    ap.add_argument("--heading-font", help="заголовок только этим шрифтом (регулярка по имени)")
    ap.add_argument("--skip-font", help="выбросить строки этого шрифта (регулярка по имени)")
    ap.add_argument("--skip-text", help="выбросить строки с этим текстом (регулярка)")
    args = ap.parse_args()

    book = Book(args.pdf, args)
    title = args.title or (book.doc.metadata or {}).get("title") or os.path.splitext(os.path.basename(args.pdf))[0]
    title = re.sub(r'[\\/:*?"<>|]', "-", title).strip()
    path, images = book.convert(args.out, title)
    print(f"{path}")
    print(f"страниц {len(book.doc)}, картинок {images}, основной текст {book.body_family} {book.body}pt, "
          f"заголовки от {book.head_min:.1f}pt, отброшено повторяющихся строк у краёв: {len(book.furniture)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
