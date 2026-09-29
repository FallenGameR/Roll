# -*- coding: utf-8 -*-
"""Запекает рваный край в портреты для печатной раздатки.

Использование:
    python bake-torn-edge.py

Берёт портреты из `_img/players` и кладёт в `_img/print/Раздатка приёмов`
те же картинки, но с оборванным краем по всем четырём сторонам. Край
запекается в альфу самой PNG: в GM Binder оверлей поверх картинки даёт
либо бледную плашку, либо ровный срез, а `mask-image` там не работает
вовсе.

Форма края берётся у самого GM Binder - из его оверлея `cPPYV7h.png`,
кремовой страницы с оборванным низом. Скрипт качает её один раз в
`%TEMP%` и вырезает оттуда полосу кромки целиком, двумерной картинкой,
а не профилем глубины: весь эффект держится на круглых каплях, подтёках
и отлетевших брызгах, и профиль от них ничего не оставляет.

Главное правило: калибр капель везде родной, оверлей не ужимается.
Ужимать пробовали, и это и есть та ошибка, из-за которой капли
пропадают - по высоте они расплющиваются в полоски, а по обеим осям
сразу мельчают до крупы. Поэтому там, где рвать глубоко нельзя, капля
не уменьшается, а меньше высовывается: полоса кромки сдвигается наружу
на столько пикселей, сколько лишних. Рисунок один и тот же по всему
периметру, разная только высовка.

Сдвиг считается по карте помех. Слева и справа у всех шестерых фон, там
кромка стоит в родном виде во всю глубину. Сверху мешает причёска,
снизу баннер с именем; их границы замерены по картинкам и лежат в
`PORTRAITS`. По углам помех нет даже сверху, и туда кромка выходит
целиком.

Поля вокруг кадра не наращиваются. Наращивать пробовали четырьмя
способами, и каждый выдаёт себя: растяжка крайних пикселей даёт полосы
поперёк себя, отражение - зеркальный шов вертикальной линией, размытая
копия - прямой кант там, где обрывается резкость, а продолжение
картинки по масштабу - вторые рога над головой и второй баннер под
подписью.

Проверять удобно так: собрать картинку на кремовом фоне GM Binder
(241, 235, 212) и посмотреть, не съеден ли волос.
"""
import os
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

VAULT = r"C:\vaults\Рудники Фанделвера"
SRC = os.path.join(VAULT, "_img", "players")
DST = os.path.join(VAULT, "_img", "print", "Раздатка приёмов")

OVERLAY_URL = "https://www.gmbinder.com/images/cPPYV7h.png"
OVERLAY = os.path.join(os.environ.get("TEMP", "."), "cPPYV7h.png")

# замеры кромки оверлея, в его собственных пикселях при ширине 1275:
# выше EDGE_TOP всё непрозрачно, ниже EDGE_END нет даже брызг, а тело
# обрыва проходит по EDGE_BODY - от него и считается высовка
EDGE_TOP = 1190
EDGE_BODY = 1230
EDGE_END = 1380

RAMP = 0.14  # за какую долю стороны высовка выходит на полную
BLUR = 0.0015  # размытие самого реза, в долях стороны кадра

# что мешает рвать сверху и снизу у каждого портрета:
# (докуда можно сверху, докуда снизу, где стоит голова) в долях стороны
PORTRAITS = {
    "Дворик Трахак": (0.012, 0.055, (0.25, 0.71)),
    "Ириван": (0.020, 0.040, (0.30, 0.74)),
    "Кали Мейхем": (0.012, 0.025, (0.33, 0.73)),
    "Калиостро Великолепный": (0.030, 0.025, (0.21, 0.79)),
    "Эдрик": (0.020, 0.025, (0.31, 0.71)),
    "Эйра": (0.012, 0.045, (0.31, 0.72)),
}

BANNER = (0.08, 0.92)  # баннер с именем внизу занимает почти всю ширину


def fetch_overlay():
    """GM Binder отдаёт картинки только с User-Agent, иначе 429."""
    if os.path.exists(OVERLAY):
        return
    req = urllib.request.Request(OVERLAY_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(OVERLAY, "wb") as fh:
        fh.write(resp.read())


def edge_strip(length, shift):
    """Полоса кромки в родном масштабе, набранная на нужную длину.

    Оверлей уже 1275 пикселей шириной, а сторона портрета - 1254, так
    что одного куска почти хватает. Остаток добирается повторами через
    один зеркально, чтобы рисунок не читался как орнамент."""
    a = np.array(Image.open(OVERLAY).convert("RGBA").split()[3]).astype(np.float32)
    tile = a[EDGE_TOP:EDGE_END]
    tiles = [tile if i % 2 == 0 else tile[:, ::-1]
             for i in range(length // tile.shape[1] + 2)]
    strip = np.concatenate(tiles, axis=1)
    off = int(shift * tile.shape[1]) % (strip.shape[1] - length)
    return strip[:, off:off + length]


def lift(n, limit, span):
    """На сколько пикселей отодвинуть кромку наружу вдоль стороны.

    Ноль - кромка стоит как в оверлее и грызёт на всю свою глубину. Там,
    где под краем причёска или баннер, высовка урезается до `limit`
    пикселей, и полоса уезжает наружу на разницу. Между помехой и
    свободным углом переход плавный, иначе на стыке видно ступеньку."""
    t = np.linspace(0.0, 1.0, n)
    body = EDGE_BODY - EDGE_TOP
    inner = max(0.0, body - limit)
    a, b = span
    out = np.zeros(n, dtype=np.float32)
    out = np.where(t < a, inner * (1.0 - np.clip((a - t) / RAMP, 0, 1)) ** 1.6, out)
    out = np.where(t > b, inner * (1.0 - np.clip((t - b) / RAMP, 0, 1)) ** 1.6, out)
    return np.where((t >= a) & (t <= b), inner, out)


def side_cover(length, limit, span, shift):
    """Кромка на одну сторону: одна и та же полоса, сдвинутая по
    столбцам на свою высовку."""
    strip = edge_strip(length, shift)
    k = lift(length, limit, span)
    depth = strip.shape[0]
    rows = np.arange(depth).reshape(-1, 1) + k.reshape(1, -1)
    rows = np.clip(np.rint(rows).astype(np.int32), 0, depth - 1)
    cover = strip[rows, np.arange(length).reshape(1, -1)]
    # хвост за пределами полосы кромки ничего не режет
    cover[np.arange(depth).reshape(-1, 1) + k.reshape(1, -1) > depth - 1] = 0.0
    return cover


def torn_alpha(size, top, bottom, head):
    """Маска обрыва: четыре стороны одной и той же кромкой."""
    W, H = size
    cover = np.zeros((H, W), dtype=np.float32)

    def put(part, where):
        if where == "top":
            cover[:part.shape[0]] = np.maximum(cover[:part.shape[0]], part)
        elif where == "bottom":
            part = part[::-1]
            cover[-part.shape[0]:] = np.maximum(cover[-part.shape[0]:], part)
        elif where == "left":
            part = part.T
            cover[:, :part.shape[1]] = np.maximum(cover[:, :part.shape[1]], part)
        else:
            part = part.T[:, ::-1]
            cover[:, -part.shape[1]:] = np.maximum(cover[:, -part.shape[1]:], part)

    put(side_cover(W, top * H, head, 0.0), "top")
    put(side_cover(W, bottom * H, BANNER, 0.31), "bottom")
    put(side_cover(H, 1e9, (0.0, 1.0), 0.57), "left")
    put(side_cover(H, 1e9, (0.0, 1.0), 0.84), "right")

    mask = Image.fromarray(np.clip(cover, 0, 255).astype(np.uint8))
    return mask.filter(ImageFilter.GaussianBlur(BLUR * W))


def bake(name):
    top, bottom, head = PORTRAITS[os.path.splitext(name)[0]]
    img = Image.open(os.path.join(SRC, name)).convert("RGBA")
    cover = np.array(torn_alpha(img.size, top, bottom, head)).astype(np.float32)
    alpha = np.array(img.split()[3]).astype(np.float32)
    img.putalpha(Image.fromarray((alpha * (255.0 - cover) / 255.0).astype(np.uint8)))
    img.save(os.path.join(DST, name))

    a = np.array(img.split()[3])
    # 48 из 255 - порог видимости на кремовой странице: ниже него хвост
    # размытия глазом не читается
    spill = ((a[0] > 48).sum(), (a[-1] > 48).sum(),
             (a[:, 0] > 48).sum(), (a[:, -1] > 48).sum())
    print(name, "нетронутых пикселей по краям:", spill)


if __name__ == "__main__":
    fetch_overlay()
    os.makedirs(DST, exist_ok=True)
    for name in sorted(os.listdir(SRC)):
        # в папке лежат и запасные облики, и прежние портреты; в раздатку
        # идёт только то, что названо в PORTRAITS
        if name.lower().endswith(".png") and os.path.splitext(name)[0] in PORTRAITS:
            bake(name)
