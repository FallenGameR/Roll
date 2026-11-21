# -*- coding: utf-8 -*-
"""Сверяет токены врагов на батлмапах с блоками encounter страниц локаций.

Использование:
    python sync-battlemap-tokens.py [Локация ...] [--write] [--base REF]

Лист локации - `_img/maps/battles/Battlemap - <Локация>*.excalidraw.md`,
состав боя - блоки ```encounter``` в разделах страницы `Adventure/Locations`
(отыгранные локации в `Done` пропускаются). Без имён проходит все локации.
Без `--write` только печатает план: что убрать, что поставить, кого
перенумеровать. С `--write` пишет листы и недостающие картинки номеров.

Что делает с листом:
  * лишние токены врагов у значка комнаты убирает, недостающие ставит в
    свободные клетки рядом с ним (размер по статблоку: Большой - 2x2 и т.д.);
  * однотипных нумерует: рисует `<токен> N.webp` со значком номера (Cambria
    Bold) и ставит его вместо голого токена; одиночку оставляет без номера;
  * именного NPC, у которого есть свой токен в `_img/npc/tokens`, ставит
    этим токеном вместо кружка его статблока;
  * токены, которые не относятся к этому бою ни до правки, ни после, не
    трогает: на листе бывают и сознательно поставленные Мастером.
  * дописывает в `## Embedded Files` строки картинок, которые на листе
    есть, а в списке пропали (ключ - sha1 от `file:`, `token:`, `map:` или
    `icon:` плюс путь или имя файла). Без них Excalidraw рисует пустые рамки.

Про `--base`. «До правки» - состав боя на странице в git, по умолчанию в
HEAD: так видно, какие токены были поставлены под старый состав и теперь
лишние. Если страница уже закоммичена с новым составом, укажи коммит до
правки (`--base HEAD~1`); `--base ""` сравнивает только с текущей страницей.

Нужен пакет `lzstring` (`pip install lzstring`).
"""
import argparse
import copy, glob, hashlib, json, math, os, re, subprocess, sys
import lzstring
import yaml
from PIL import Image, ImageDraw, ImageFont

V = r'C:\vaults\Рудники Фанделвера'
C = 38.4412
TW, TH = 38.52975918257891, 39.312
SIZE = {'Крошечный': 1, 'Маленький': 1, 'Средний': 1, 'Большой': 2, 'Огромный': 3, 'Громадный': 4}
B62 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
L = lzstring.LZString()


def idx(i):
    return 'a' + B62[i] if i < 62 else 'b' + B62[i // 62] + B62[i % 62]


def norm(s):
    return re.sub(r'\s+', ' ', s.replace('ё', 'е').strip().lower())


# --- справочник существ: имя/алиас -> (токен, размер)
CRE = {}
for p in glob.glob(V + r'\DnD Lists n Rules\Bestiary\*.md'):
    t = open(p, encoding='utf-8').read()
    img = re.search(r'^"image":\s*"([^"]+)"', t, re.M)
    size = re.search(r'^"size":\s*"([^"]+)"', t, re.M)
    if not img:
        continue
    info = (img[1], SIZE.get(size[1] if size else '', 1))
    names = [os.path.splitext(os.path.basename(p))[0]]
    fm = t.split('---')[1] if t.startswith('---') else ''
    names += re.findall(r'^\s*-\s*"?([^"\n]+?)"?\s*$', fm.split('aliases:')[1], re.M) if 'aliases:' in fm else []
    for n in names:
        CRE.setdefault(norm(n), info)
NPC = {}
NPC_SB = {}
for p in glob.glob(V + r'\Adventure\NPC\*.md'):
    n = os.path.splitext(os.path.basename(p))[0]
    tok = f'_img/npc/tokens/{n} токен.png'
    t = open(p, encoding='utf-8').read()
    mon = re.search(r'^monster:\s*(.+)$', t, re.M)
    size = re.search(r'^"size":\s*"([^"]+)"', t, re.M)
    own_img = re.search(r'^"image":\s*"([^"]+)"', t, re.M)
    if mon and norm(mon[1]) in CRE:
        NPC_SB[norm(n)] = CRE[norm(mon[1])][0]
    elif own_img and not own_img[1].startswith('_img/npc/'):
        NPC_SB[norm(n)] = own_img[1]
    if os.path.exists(os.path.join(V, tok)):
        NPC[norm(n)] = (tok, SIZE.get(size[1] if size else '', 1))
    elif mon and norm(mon[1]) in CRE:
        NPC[norm(n)] = CRE[norm(mon[1])]
    elif re.search(r'^"image":', t, re.M):
        img = re.search(r'^"image":\s*"([^"]+)"', t, re.M)
        NPC[norm(n)] = (img[1], SIZE.get(size[1] if size else '', 1))


def resolve(statblock, label):
    for key in (label, statblock):
        if key and norm(key) in NPC:
            return NPC[norm(key)]
    if norm(statblock) in CRE:
        return CRE[norm(statblock)]
    return None


def parse_line(s):
    """`- N: Существо`, `- N: [Существо, Имя, hidden|ally]` или
    `- N: {creature: Существо, name: Имя, ...}` -> (N, статблок, подпись, союзник).

    Значение разбирается как YAML: имя с запятой стоит в кавычках
    ("Незнар, Чёрный Паук"), и резать его по запятой нельзя.
    """
    m = re.match(r'^\s*-\s*(\d+)\s*:\s*(.+?)\s*$', s)
    if not m:
        return None
    n, rest = int(m[1]), m[2]
    try:
        v = yaml.safe_load(rest)
    except yaml.YAMLError:
        v = None
    if isinstance(v, list) and v:
        parts = [str(x).strip() for x in v]
        label = parts[1] if len(parts) > 1 and parts[1] not in ('hidden', 'ally') else parts[0]
        return n, parts[0], label, 'ally' in parts
    if isinstance(v, dict):
        sb = str(v.get('creature') or v.get('name') or '').strip()
        if sb:
            return n, sb, str(v.get('name') or sb).strip(), bool(v.get('ally'))
    if isinstance(v, str) and v.strip():
        return n, v.strip(), v.strip(), False
    # Не YAML: прежний разбор, на случай записи, которую понимает только трекер.
    if rest.startswith('['):
        parts = [x.strip() for x in rest.strip('[]').split(',')]
        return n, parts[0], parts[1] if len(parts) > 1 and parts[1] not in ('hidden', 'ally') else parts[0], 'ally' in parts
    if rest.startswith('{'):
        cr = re.search(r'creature:\s*([^,}]+)', rest)
        nm = re.search(r'name:\s*([^,}]+)', rest)
        sb = cr[1].strip() if cr else rest.strip('{}')
        return n, sb, nm[1].strip() if nm else sb, False
    return n, rest, rest, False


def page_sections(page, text=None):
    t = text if text is not None else open(page, encoding='utf-8').read()
    out = {}
    for s in re.split(r'(?m)^(?=# )', t):
        if not s.startswith('# '):
            continue
        h = s.split('\n', 1)[0][2:].strip()
        blocks = []
        for b in re.findall(r'```encounter\n(.*?)```', s, re.S):
            b = re.sub(r'(?m)^>\s?', '', b)
            lines = [parse_line(x) for x in b.split('\n')]
            blocks.append([x for x in lines if x])
        if blocks:
            out[h] = blocks
    return out


# --- значок номера
BADGE_FONT = r'C:\Windows\Fonts\cambriab.ttf'


def numbered(path, n):
    """`_img/bestiary/tokens/x.webp` -> `x N.webp`, создаёт при надобности."""
    base, ext = os.path.splitext(path)
    out = f'{base} {n}{ext}'
    full = os.path.join(V, out)
    if os.path.exists(full):
        return out
    src = Image.open(os.path.join(V, path)).convert('RGBA')
    k = src.width / 280
    S = 4
    big = Image.new('RGBA', (int(300 * k) * S, int(300 * k) * S), (0, 0, 0, 0))
    big.alpha_composite(src.resize((src.width * S, src.height * S), Image.LANCZOS))
    d = ImageDraw.Draw(big)
    cx = cy = (140 + 140 * math.cos(math.pi / 4)) * k * S
    half = 50 * k * S
    d.rounded_rectangle((cx - half, cy - half, cx + half, cy + half), radius=16 * k * S,
                        fill=(91, 6, 14, 255), outline=(240, 180, 40, 255), width=int(7 * k * S))
    f = ImageFont.truetype(BADGE_FONT, int(78 * k * S))
    txt = str(n)
    l, t_, r, b = d.textbbox((0, 0), txt, font=f)
    d.text((cx - (l + r) / 2, cy - (t_ + b) / 2), txt, font=f, fill=(255, 255, 255, 255))
    big.resize((int(300 * k), int(300 * k)), Image.LANCZOS).save(full, quality=92)
    return out


def base_of(path):
    return re.sub(r' \d+(\.\w+)$', r'\1', path)



def sync(ONLY, write, base):
    """Сверка всех листов; возвращает строки отчёта."""
    report = []
    for page in glob.glob(V + r'\Adventure\Locations\**\*.md', recursive=True):
        if '\\Done\\' in page:
            continue
        loc = os.path.splitext(os.path.basename(page))[0]
        if ONLY and loc not in ONLY:
            continue
        secs = page_sections(page)
        rel = os.path.relpath(page, V).replace('\\', '/')
        old_secs = secs
        if base:
            try:
                old_text = subprocess.run(['git', '-C', V, 'show', f'{base}:' + rel],
                                          capture_output=True, check=True).stdout.decode('utf-8')
                old_secs = page_sections(page, old_text)
            except Exception:
                pass  # страницы нет в этой ревизии: сравниваем с текущей
        old_bases = {}
        for sec, blocks in old_secs.items():
            for b in blocks:
                for n, sb, label, ally in b:
                    info = resolve(sb, label)
                    if info:
                        old_bases.setdefault(sec, set()).add(info[0])
        sheets = glob.glob(V + rf'\_img\maps\battles\Battlemap - {glob.escape(loc)}*.excalidraw.md')
        if not sheets:
            report.append(f'{loc}: нет листа')
            continue
        done = set()
        for sheet in sheets:
            t = open(sheet, encoding='utf-8').read()
            m = re.search(r'```compressed-json\n(.*?)```', t, re.S)
            d = json.loads(L.decompressFromBase64(m[1].replace('\n', '')))
            files = dict(re.findall(r'^([0-9a-f]{40}): \[\[(.*?)\]\]', t, re.M))

            def fpath(e):
                p = files.get(e.get('fileId'), '')
                if '/' not in p:
                    for r_, _, fs in os.walk(os.path.join(V, '_img')):
                        if p in fs:
                            return os.path.relpath(os.path.join(r_, p), V).replace('\\', '/')
                return p

            els = [e for e in d['elements'] if not e.get('isDeleted')]
            bg = els[0]
            icons = {}
            fight_secs = set(secs) | set(old_secs)
            for e in els:
                bm = (e.get('customData') or {}).get('battlemap') or {}
                if bm.get('action') == 'goto' and '#' in bm.get('target', ''):
                    sec = bm['target'].split('#', 1)[1]
                    if sec in fight_secs:
                        icons.setdefault(sec, (e['x'] + e['width'] / 2, e['y'] + e['height'] / 2))
            creature_tok = lambda p: p.startswith('_img/bestiary/tokens/') or p.startswith('_img/npc/tokens/')
            toks = [e for e in els if e['type'] == 'image' and creature_tok(fpath(e))]
            # закрепить токены за ближайшим значком комнаты
            own = {}
            for e in toks:
                ex, ey = e['x'] + e['width'] / 2, e['y'] + e['height'] / 2
                best = min(icons.items(), key=lambda kv: math.hypot(kv[1][0] - ex, kv[1][1] - ey), default=None)
                if best and math.hypot(best[1][0] - ex, best[1][1] - ey) < 12 * C:
                    own.setdefault(best[0], []).append(e)
            occ = set()
            for e in els[1:]:
                if e['type'] == 'image':
                    occ.add((int((e['x'] + e['width'] / 2) // C), int((e['y'] + e['height'] / 2) // C)))
            remove, add, renum = set(), [], []
            tpl = toks[0] if toks else next(e for e in els[1:] if e['type'] == 'image')
            for sec, blocks in secs.items():
                if sec not in icons:
                    continue
                done.add(sec)
                # нужное: по базовому токену максимум по блокам; группы по подписи
                want, groups = {}, {}
                npc_base = {}
                for b in blocks:
                    cnt, grp = {}, {}
                    for n, sb, label, ally in b:
                        if ally:
                            continue
                        info = resolve(sb, label)
                        if not info:
                            report.append(f'{loc} / {sec}: нет токена для "{sb}"')
                            continue
                        if info[0].startswith('_img/npc/tokens/'):
                            npc = (CRE[norm(sb)][0] if norm(sb) != norm(label) and norm(sb) in CRE else None) \
                                or NPC_SB.get(norm(label)) or NPC_SB.get(norm(sb))
                            if npc:
                                npc_base[info[0]] = npc
                        cnt[info] = cnt.get(info, 0) + n
                        grp.setdefault(info, []).append(n)
                    for k, v in cnt.items():
                        if v > want.get(k, 0):
                            want[k] = v
                            groups[k] = grp[k]
                have = {}
                for e in own.get(sec, []):
                    p = base_of(fpath(e))
                    if not any(k[0] == p for k in want) and p not in old_bases.get(sec, set()) \
                            and p not in npc_base.values():
                        continue  # не из этого боя ни до, ни после - не трогаем
                    have.setdefault(p, []).append(e)
                # именной NPC раньше стоял токеном своего статблока: перекрашиваем лишний
                for p_npc, p_sb in npc_base.items():
                    need_npc = max((v for k, v in want.items() if k[0] == p_npc), default=0) - len(have.get(p_npc, []))
                    need_sb = max((v for k, v in want.items() if k[0] == p_sb), default=0)
                    spare = have.get(p_sb, [])
                    spare.sort(key=lambda e: math.hypot(e['x'] - icons[sec][0], e['y'] - icons[sec][1]), reverse=True)
                    while need_npc > 0 and len(spare) > need_sb:
                        e = spare.pop()
                        have.setdefault(p_npc, []).append(e)
                        need_npc -= 1
                cx, cy = icons[sec]
                allp = {k[0] for k in want} | set(have)
                for p in sorted(allp):
                    info = next((k for k in want if k[0] == p), None)
                    need = want.get(info, 0) if info else 0
                    cur = have.get(p, [])
                    cur.sort(key=lambda e: math.hypot(e['x'] - cx, e['y'] - cy))
                    keep = cur[:need]
                    for e in cur[need:]:
                        remove.add(e['id'])
                    sz = info[1] if info else 1
                    for q in range(need - len(keep)):
                        c0 = (int(cx // C), int(cy // C))
                        placed = None
                        for r in range(1, 14):
                            ring = [(c0[0] + dx, c0[1] + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                                    if max(abs(dx), abs(dy)) == r]
                            ring.sort(key=lambda c: (math.hypot(c[0] - c0[0], c[1] - c0[1]), c[1], c[0]))
                            for cell in ring:
                                cells = {(cell[0] + a, cell[1] + b) for a in range(sz) for b in range(sz)}
                                x0, y0 = cell[0] * C, cell[1] * C
                                if cells & occ or x0 < 0 or y0 < 0 or x0 + sz * C > bg['width'] or y0 + sz * C > bg['height']:
                                    continue
                                mx, my = x0 + sz * C / 2, y0 + sz * C / 2
                                near = min(icons.items(), key=lambda kv: math.hypot(kv[1][0] - mx, kv[1][1] - my))[0]
                                if near != sec:
                                    continue
                                occ |= cells
                                w, h = (TW, TH) if sz == 1 else (sz * C, sz * C)
                                e = copy.deepcopy(tpl)
                                i = hashlib.sha1(f'sync:{sheet}:{sec}:{p}:{q}:{len(add)}'.encode()).digest()
                                e.update(id=''.join(B62[b % 62] for b in i[:8]), x=x0 + (sz * C - w) / 2,
                                         y=y0 + (sz * C - h) / 2, width=w, height=h, locked=False, link=None,
                                         version=1, versionNonce=int.from_bytes(i[8:12], 'big') % 2**31,
                                         seed=int.from_bytes(i[12:16], 'big') % 2**31, groupIds=[],
                                         boundElements=[], customData={})
                                e['_path'] = p
                                placed = e
                                break
                            if placed:
                                break
                        if placed:
                            keep.append(placed)
                            add.append(placed)
                        else:
                            report.append(f'{loc} / {sec}: не нашла места для {p}')
                    # нумерация: одиночная группа без номера, иначе 1..n по чтению
                    gs = groups.get(info, []) if info else []
                    keep.sort(key=lambda e: (round(e['y'] / C), e['x']))
                    numbered_need = sum(g for g in gs if g > 1)
                    k = 0
                    for gi, g in enumerate(sorted(gs, reverse=True)):
                        for j in range(g):
                            if k >= len(keep):
                                break
                            renum.append((keep[k], p, j + 1 if g > 1 else 0, sz))
                            k += 1
                    if need != len(cur):
                        report.append(f'{loc} / {sec}: {os.path.basename(p)} {len(cur)} -> {need}')
            if not (remove or add or renum):
                continue
            emb = []
            known = set(files)
            changed = bool(remove or add)
            for e, p, n, sz in renum:
                target = numbered(p, n) if n and write else (p if not n else re.sub(r'(\.\w+)$', rf' {n}\1', p))
                fid = hashlib.sha1(('file:' + target).encode()).hexdigest()
                cur = fpath(e) if '_path' not in e else None
                if cur == target:
                    continue
                changed = True
                w0 = (TW if sz == 1 else sz * C)
                h0 = (TH if sz == 1 else sz * C)
                if n:
                    e['width'], e['height'] = w0 * 300 / 280, h0 * 300 / 280
                else:
                    e['width'], e['height'] = w0, h0
                e['fileId'] = fid
                e['version'] = e.get('version', 1) + 1
                if fid not in known:
                    known.add(fid)
                    emb.append(f'{fid}: [[{target}]]')
            if not changed:
                continue
            new = [e for e in d['elements'] if e['id'] not in remove] + add
            for e in new:
                e.pop('_path', None)
            for i, e in enumerate(new):
                e['index'] = idx(i)
            d['elements'] = new
            print(f'{os.path.basename(sheet)}: -{len(remove)} +{len(add)}')
            if write:
                comp = L.compressToBase64(json.dumps(d, ensure_ascii=False, separators=(',', ':')))
                assert json.loads(L.decompressFromBase64(comp)) == d
                t = t[:m.start(1)] + '\n\n'.join(comp[i:i + 256] for i in range(0, len(comp), 256)) + '\n' + t[m.end(1):]
                if emb:
                    t = t.replace('## Embedded Files\n', '## Embedded Files\n' + ''.join(l + '\n\n' for l in emb), 1)
                open(sheet, 'w', encoding='utf-8', newline='\n').write(t)
        for sec in secs:
            if sec not in done:
                report.append(f'{loc} / {sec}: бой вне комнаты на листе, токены не ставлю')
    return report


def repair_embeds(sheets, write):
    """Дописывает в ## Embedded Files пропавшие строки картинок; возвращает отчёт."""
    rev = {}
    for p in glob.glob(os.path.join(V, '_img', '**', '*.*'), recursive=True):
        r = os.path.relpath(p, V).replace('\\', '/')
        for pre in ('file:', 'token:', 'map:', 'icon:'):
            for s in (r, os.path.basename(r)):
                rev[hashlib.sha1((pre + s).encode()).hexdigest()] = r
    out = []
    for sheet in sheets:
        t = open(sheet, encoding='utf-8').read()
        m = re.search(r'```compressed-json\n(.*?)```', t, re.S)
        if not m:
            continue
        d = json.loads(L.decompressFromBase64(m[1].replace('\n', '')))
        files = dict(re.findall(r'^([0-9a-f]{40}): \[\[(.*?)\]\]', t, re.M))
        miss = {e['fileId'] for e in d['elements']
                if e['type'] == 'image' and not e.get('isDeleted') and e['fileId'] not in files}
        if not miss:
            continue
        add = sorted(f'{f}: [[{rev[f]}]]' for f in miss if f in rev)
        unknown = sorted(f for f in miss if f not in rev)
        out.append(f'{os.path.basename(sheet)}: нет в Embedded Files {len(miss)}, '
                   f'{"дописано" if write else "можно дописать"} {len(add)}'
                   + (f', не найдены картинки для {unknown}' if unknown else ''))
        if add and write:
            t = t.replace('## Embedded Files\n', '## Embedded Files\n' + ''.join(l + '\n\n' for l in add), 1)
            open(sheet, 'w', encoding='utf-8', newline='\n').write(t)
    return out


def main():
    ap = argparse.ArgumentParser(description='Токены врагов на батлмапах по блокам encounter.')
    ap.add_argument('locations', nargs='*', help='имена страниц локаций; без них все')
    ap.add_argument('--write', action='store_true', help='записать листы, без него только план')
    ap.add_argument('--base', default='HEAD', help='git-ревизия страницы «до правки»; "" - без неё')
    a = ap.parse_args()
    report = sync(set(a.locations), a.write, a.base)
    sheets = []
    for loc in a.locations or ['']:
        sheets += glob.glob(V + rf'\_img\maps\battles\Battlemap - {glob.escape(loc)}*.excalidraw.md')
    report += repair_embeds(sorted(set(sheets)), a.write)
    print('\n'.join(report))
    if not a.write:
        print('план, ничего не записано: для записи добавь --write')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
