# -*- coding: utf-8 -*-
"""Режет круглый токен именного NPC из его портрета.

Использование:
    python make-npc-tokens.py "Пук" --cx 0.575 --cy 0.16 --r 0.165 --ring "#1f8a8a"
    python make-npc-tokens.py "Пук" --cx 0.575 --cy 0.16 --r 0.165 --preview

Портрет берётся из `_img/npc/<Имя>.png`, токен ложится в
`_img/npc/tokens/<Имя> токен.png`. Готовый токен скрипт не перезаписывает,
для этого нужен `--force`. С `--preview` токен пишется во временную папку,
скрипт печатает путь и волт не трогает: так удобно подбирать вырез.

Кругляшок рисуется тем же кодом, что у игроков (`make-player-tokens.py`,
функция render_token): 512x512, тот же суперсэмплинг, кольцо цвета
`--ring` (по умолчанию золото #b8902a, как у первых NPC) с тёмным контуром.

Вырез: --cx и --cy - центр головы, --r - половина стороны выреза, всё в
долях стороны исходного портрета, как у игроков. Портреты NPC часто
срезаны по макушке, и вырез с лицом в центре круга вылезает за верх.
Тогда сверху подклеивается полоса высотой 15% портрета из его верхних 3%,
растянутых и размытых: зеркальная подкладка рисовала бы сверху отражение
макушки, а размытая полоса читается как фон. Пересчёт выреза на подкладку
скрипт делает сам.
"""
import argparse
import importlib.util
import os
import sys
import tempfile

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("player_tokens", os.path.join(HERE, "make-player-tokens.py"))
player_tokens = importlib.util.module_from_spec(spec)
spec.loader.exec_module(player_tokens)

SRC = os.path.join(player_tokens.VAULT, "_img", "npc")
DST = os.path.join(SRC, "tokens")

PAD = 0.15    # высота подкладки, доля высоты портрета
STRIP = 0.03  # сколько сверху портрета растягивается в подкладку
BLUR = 25


def padded(img):
    """Портрет с размытой полосой сверху и её высота."""
    w, h = img.size
    pad = int(h * PAD)
    strip = img.crop((0, 0, w, max(1, int(h * STRIP)))).resize((w, pad), Image.LANCZOS)
    strip = strip.filter(ImageFilter.GaussianBlur(BLUR))
    out = Image.new("RGB", (w, h + pad))
    out.paste(strip, (0, 0))
    out.paste(img, (0, pad))
    return out, pad


def render(name, cx, cy, r, ring):
    src = Image.open(os.path.join(SRC, name + ".png")).convert("RGB")
    w, h = src.size
    if cy * h - r * w < 0:
        src, pad = padded(src)
        # crop_head меряет вырез от ширины, а она не изменилась: r остаётся,
        # сдвигается только центр по высоте.
        cy = (cy * h + pad) / (h + pad)
    return player_tokens.render_token(src, dict(cx=cx, cy=cy, r=r, ring=ring))


def main():
    ap = argparse.ArgumentParser(description="Круглый токен NPC из _img/npc/<Имя>.png")
    ap.add_argument("name", help="имя файла портрета без .png")
    ap.add_argument("--cx", type=float, required=True, help="центр головы по ширине, доля стороны")
    ap.add_argument("--cy", type=float, required=True, help="центр головы по высоте, доля стороны")
    ap.add_argument("--r", type=float, required=True, help="половина стороны выреза, доля стороны")
    ap.add_argument("--ring", default="#b8902a", help="цвет кольца")
    ap.add_argument("--preview", action="store_true", help="во временную папку, волт не трогать")
    ap.add_argument("--force", action="store_true", help="перезаписать готовый токен в волте")
    a = ap.parse_args()

    if not os.path.exists(os.path.join(SRC, a.name + ".png")):
        sys.exit(f"нет портрета {os.path.join(SRC, a.name + '.png')}")
    out_dir = os.path.join(tempfile.gettempdir(), "npc-tokens") if a.preview else DST
    path = os.path.join(out_dir, a.name + " токен.png")
    if not a.preview and os.path.exists(path) and not a.force:
        sys.exit(f"токен уже есть, не перезаписываю: {path}\nпосмотреть новый вариант: --preview, заменить: --force")
    token = render(a.name, a.cx, a.cy, a.r, a.ring)
    os.makedirs(out_dir, exist_ok=True)
    token.save(path)
    print(path)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
