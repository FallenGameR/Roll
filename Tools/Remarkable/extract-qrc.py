"""Достаёт ресурсы Qt (QML-исходники интерфейса, иконки SVG) из программы
интерфейса reMarkable, /usr/bin/xochitl.

    python extract-qrc.py <xochitl> <папка-вывода>

Бинарник берут с планшета: scp -O root@<адрес>:/usr/bin/xochitl .
Результат - код reMarkable, в репозиторий его не кладут.

Как устроено. rcc вшивает в программу по три массива на каждый .qrc:
имена (u16 длина, u32 хеш, имя в UTF-16BE), дерево (записи по 22 байта:
u32 смещение имени, u16 флаги, дальше у папки u32 число детей и u32 номер
первого ребёнка, у файла u16 страна, u16 язык и u32 смещение данных, в конце
u64 время) и данные (u32 длина, затем содержимое; флаг 4 - сжато zstd,
флаг 1 - zlib с u32 исходного размера впереди). Указателей на массивы
скрипт не ищет: он находит таблицы имён по самим именам, по ним записи
дерева, а начало данных подбирает так, чтобы у большинства файлов на месте
оказался заголовок zstd или текст.
"""
import os
import re
import struct
import sys
import zlib
from collections import Counter

import zstandard

B = b""
DZ = zstandard.ZstdDecompressor()


def name_at(p):
    if p < 0 or p + 6 > len(B):
        return None
    n = struct.unpack(">H", B[p:p + 2])[0]
    if n == 0 or n > 200:
        return None
    try:
        s = B[p + 6:p + 6 + 2 * n].decode("utf-16-be")
    except UnicodeDecodeError:
        return None
    if not all(32 <= ord(c) < 127 for c in s):
        return None
    return s, p + 6 + 2 * n


def names_base(entry):
    cur = entry
    while True:
        prev = None
        for n in range(1, 200):
            s = cur - 6 - 2 * n
            r = name_at(s)
            if r and r[1] == cur and len(r[0]) == n:
                prev = s
                break
        if prev is None:
            return cur
        cur = prev


def find_tables():
    bases = set()
    for ext in (".qml", ".svg", ".js", ".png", ".qmldir", "icons"):
        for m in re.finditer(re.escape(ext.encode("utf-16-be")), B):
            end = m.end()
            for n in range(len(ext), 200):
                s = end - 6 - 2 * n
                r = name_at(s)
                if r and r[1] == end:
                    bases.add(names_base(s))
                    break
    return sorted(bases)


def frames():
    return [m.start() for m in re.finditer(rb"\x28\xb5\x2f\xfd", B)]


def u16(p):
    return struct.unpack(">H", B[p:p + 2])[0] if 0 <= p and p + 2 <= len(B) else None


def u32(p):
    return struct.unpack(">I", B[p:p + 4])[0] if 0 <= p and p + 4 <= len(B) else None


def read_table(nb, zframes):
    names = {}
    p = nb
    while True:
        r = name_at(p)
        if not r:
            break
        names[p - nb] = r[0]
        p = r[1]

    def ok(c):
        n, f = u32(c), u16(c + 4)
        if n is None or f is None or c + 22 > len(B):
            return False
        return f in (0, 1, 2, 4) and n in names

    # Сначала имена с расширением, потом остальные: у иконок расширения нет.
    file_offs = [o for o, s in names.items() if "." in s] + [o for o, s in names.items() if "." not in s]
    for file_off in file_offs[:12]:
        for m in re.finditer(re.escape(struct.pack(">I", file_off)), B):
            rec = m.start()
            if not ok(rec) or u16(rec + 4) == 2:
                continue
            tb = rec
            while ok(tb - 22):
                tb -= 22
            recs = []
            c = tb
            while ok(c):
                recs.append(c)
                c += 22
            # Ложное совпадение даёт обрывок в пару записей; настоящее дерево
            # ссылается почти на все имена таблицы.
            if len(recs) < len(names) * 0.8:
                continue
            files = [r for r in recs if u16(r + 4) != 2]
            packed = [r for r in files if u16(r + 4) == 4]
            best = None
            if packed:
                votes = Counter()
                for r in packed:
                    off = u32(r + 10)
                    for fr in zframes:
                        if fr - 4 - off >= 0:
                            votes[fr - 4 - off] += 1
                base, n = votes.most_common(1)[0] if votes else (None, 0)
                if n >= max(1, (len(packed) + 1) // 2):
                    best = base
            else:
                off0 = u32(files[0] + 10)
                for m2 in re.finditer(rb"import |module |\x89PNG|<svg|<\?xml|depends ", B):
                    base = m2.start() - 4 - off0
                    lens = [u32(base + u32(r + 10)) if base >= 0 else None for r in files]
                    if all(x is not None and 0 < x < 20_000_000 for x in lens):
                        best = base
                        break
            if best is None:
                continue
            return list(collect(recs, names, best))
    return []


def collect(recs, names, base):
    paths = {0: ""}
    for i, r in enumerate(recs):
        if u16(r + 4) == 2:
            cc, fc = u32(r + 6), u32(r + 10)
            for k in range(fc, min(fc + cc, len(recs))):
                paths[k] = paths.get(i, "") + "/" + names.get(u32(recs[k]), "?")
    for i, r in enumerate(recs):
        flags = u16(r + 4)
        if flags == 2:
            continue
        q = base + u32(r + 10)
        n = u32(q)
        if n is None or n > 50_000_000:
            continue
        raw = B[q + 4:q + 4 + n]
        try:
            if flags == 4:
                raw = DZ.decompress(raw, max_output_size=50_000_000)
            elif flags == 1:
                raw = zlib.decompress(raw[4:])
        except Exception:
            continue
        yield paths.get(i) or "/" + names.get(u32(r), "?"), raw

def main():
    global B
    src, dst = sys.argv[1], sys.argv[2]
    B = open(src, "rb").read()
    zframes = frames()
    total = 0
    seen = set()
    for nb in find_tables():
        for path, raw in read_table(nb, zframes):
            if path in seen:
                continue
            seen.add(path)
            target = os.path.join(dst, *path.strip("/").split("/"))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
            except OSError:
                continue
            if os.path.isdir(target):
                continue
            with open(target, "wb") as f:
                f.write(raw)
            total += 1
    print(f"files: {total}")


if __name__ == "__main__":
    main()
