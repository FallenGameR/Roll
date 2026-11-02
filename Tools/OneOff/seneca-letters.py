# -*- coding: utf-8 -*-
"""Нравственные письма Сенеки к Луцилию с ancientrome.ru в EPUB для Remarkable.

Использование:
    python seneca-letters.py 97            # одно письмо
    python seneca-letters.py 97-124        # диапазон
    python seneca-letters.py 97 --out DIR  # куда класть, по умолчанию %TEMP%\\seneca\\out

Письмо N лежит на https://ancientrome.ru/antlitr/t.htm?a=13465700NN, страница
в windows-1251. Из неё берутся текст (div.otext) и примечания (div.prim).

Что меняется по дороге:
- мягкие переносы (U+00AD) сайт ставит в каждое слово, они вырезаются;
- номера параграфов "(1)" убираются, для чтения они только шум;
- примечание встаёт прямо в текст на место сноски, мелким шрифтом в
  квадратных скобках;
- внешние ссылки в примечаниях превращаются в простой текст.

Файл называется "097 - краткое содержание.epub": номер с нулями, чтобы
сортировалось, и три-шесть слов о чём письмо из TITLES. Remarkable берёт
имя документа из имени файла.
"""
import argparse
import html
import os
import re
import sys
import tempfile
import urllib.request
import uuid
import zipfile

URL = "https://ancientrome.ru/antlitr/t.htm?a={}"
FIRST_ID = 1346570000

TITLES = {
    97: "Пороки вечны, совесть карает",
}

CSS = """\
body { font-family: 'Times New Roman', serif; margin: 0 8pt 0 0; padding: 0; }
h1 { font-size: 1.5em; font-weight: bold; text-align: center; margin: 1em 0 0.3em 0; page-break-after: avoid; }
p.sub { text-align: center; font-style: italic; text-indent: 0; margin: 0 2em 1.5em 2em; }
p { text-indent: 1.5em; margin: 0; text-align: justify; }
p.greet { text-indent: 0; margin-bottom: 0.5em; font-style: italic; }
sup { font-size: 0.7em; line-height: 0.1; }
span.note { font-size: 0.8em; font-style: normal; }
"""


def roman(n):
    out = ""
    for value, sym in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                       (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += sym
            n -= value
    return out


def fetch(n):
    with urllib.request.urlopen(URL.format(FIRST_ID + n)) as r:
        return r.read().decode("cp1251")


def clean(fragment):
    s = fragment.replace("\xad", "")
    s = re.sub(r'<font class=kav>(.*?)</font>', r"\1", s)
    s = re.sub(r'\(<a name="\d+" id="\d+"></a>\d+\)\s*', "", s)
    s = re.sub(r'<span class=z1></span>', "", s)
    return s


def to_xhtml_text(s):
    s = html.unescape(s)
    s = html.escape(s, quote=False)
    return s


def inline(s, notes=None):
    """Оставляет из разметки только курсив и текст; сноску заменяет текстом примечания."""
    parts = []
    pos = 0
    for m in re.finditer(r"<sup><a [^>]*?href=\"#n(\d+)\"[^>]*>\d+</a></sup>|<(/?)i>|<[^>]+>", s):
        parts.append(to_xhtml_text(s[pos:m.start()]))
        if m.group(1):
            note = (notes or {}).get(m.group(1))
            if note:
                parts.append(f' <span class="note">[{note}]</span>')
        elif m.group(0) in ("<i>", "</i>"):
            parts.append(m.group(0))
        pos = m.end()
    parts.append(to_xhtml_text(s[pos:]))
    text = "".join(parts)
    return re.sub(r"\s+", " ", text).strip()


def parse(page):
    notes = {}
    if 'class="prim"' in page:
        prim = page[page.index('class="prim"'):]
        prim = prim[:prim.index('<div class="ignored">')]
        for m in re.finditer(r'<li id="n(\d+)">(.*?)(?=<li id="n|</div>)', clean(prim), re.S):
            text = re.sub(r"^<sup>.*?</sup>", "", m.group(2).strip())
            notes[m.group(1)] = inline(text)

    body = page[page.index('<div class="otext">'):]
    body = body[:body.index("</div>")]
    body = clean(body)
    paragraphs = [inline(p, notes) for p in re.split(r"</?p>", body)]
    paragraphs = [p for p in paragraphs if p]
    return paragraphs, notes


def build(n, title, paragraphs, out_dir):
    name = f"{n:03d} - {title}"
    heading = f"Письмо {roman(n)}"
    body = [f"<h1>{heading}</h1>", f'<p class="sub">{html.escape(title)}</p>']
    for i, p in enumerate(paragraphs):
        cls = ' class="greet"' if i == 0 and "приветствует" in p else ""
        body.append(f"<p{cls}>{p}</p>")

    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        'lang="ru" xml:lang="ru">\n'
        f"<head><meta charset=\"utf-8\"/><title>{html.escape(name)}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        "<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ru">\n'
        f"<head><meta charset=\"utf-8\"/><title>{html.escape(name)}</title></head>\n"
        '<body><nav epub:type="toc"><ol>'
        f'<li><a href="letter.xhtml">{heading}</a></li>'
        "</ol></nav></body></html>\n"
    )
    book_id = uuid.uuid5(uuid.NAMESPACE_URL, URL.format(FIRST_ID + n))
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"<dc:identifier id=\"id\">urn:uuid:{book_id}</dc:identifier>\n"
        f"<dc:title>{html.escape(name)}</dc:title>\n"
        "<dc:creator>Луций Анней Сенека</dc:creator>\n"
        "<dc:language>ru</dc:language>\n"
        '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>\n'
        "</metadata>\n<manifest>\n"
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>\n'
        '<item id="css" href="style.css" media-type="text/css"/>\n'
        '<item id="letter" href="letter.xhtml" media-type="application/xhtml+xml"/>\n'
        '</manifest>\n<spine><itemref idref="letter"/></spine>\n</package>\n'
    )
    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles>\n</container>\n"
    )

    path = os.path.join(out_dir, name + ".epub")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/letter.xhtml", xhtml, compress_type=zipfile.ZIP_DEFLATED)
    return path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("letters", help="номер или диапазон, например 97 или 97-124")
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "seneca", "out"))
    args = ap.parse_args()

    a, _, b = args.letters.partition("-")
    numbers = range(int(a), int(b or a) + 1)
    missing = [n for n in numbers if n not in TITLES]
    if missing:
        sys.exit(f"Нет названий для писем: {missing}. Допиши их в TITLES.")

    os.makedirs(args.out, exist_ok=True)
    for n in numbers:
        paragraphs, notes = parse(fetch(n))
        path = build(n, TITLES[n], paragraphs, args.out)
        print(f"{os.path.basename(path)}: абзацев {len(paragraphs)}, примечаний {len(notes)}")


if __name__ == "__main__":
    main()
