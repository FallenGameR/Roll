"""Шифрует имена в своём моде .qmd хешами из hashtab прошивки.

    python encode-qmd.py <hashtab> <мод.qmd.in> <мод.qmd>

В исходнике имена прошивки пишут открытым текстом, но в тех же скобках,
что и в готовых модах: [[Имя]] в селекторах AFFECT/TRAVERSE/IMPORT и
~&имя&~ в коде. Имя с точками ([[com.remarkable]]) кодируется по частям.
Свои новые имена (id таймеров, свойства) пишут без скобок, их в таблице нет.
Если имени нет в hashtab, скрипт его называет и ничего не пишет.
"""
import re
import struct
import sys


def load(path):
    b = open(path, "rb").read()
    i, t = 0, {}
    while i + 12 <= len(b):
        h, n = struct.unpack(">QI", b[i:i + 12])
        t[b[i + 12:i + 12 + n].decode("utf-8", "replace")] = h
        i += 12 + n
    return t


def main():
    table, src, dst = sys.argv[1:4]
    names = load(table)
    text = open(src, encoding="utf-8-sig").read().replace("\r\n", "\n")
    missing = []

    def enc(name, dotted):
        if dotted and "." in name:
            parts = name.split(".")
            if all(p in names for p in parts):
                return ".".join(str(names[p]) for p in parts)
        if name in names:
            return str(names[name])
        missing.append(name)
        return name

    text = re.sub(r"\[\[([^\]\d][^\]]*)\]\]", lambda m: "[[" + enc(m.group(1), True) + "]]", text)
    text = re.sub(r"~&([A-Za-z_][\w.]*)&~", lambda m: "~&" + enc(m.group(1), False) + "&~", text)
    if missing:
        print("нет в hashtab: " + ", ".join(sorted(set(missing))))
        sys.exit(1)
    open(dst, "w", encoding="utf-8", newline="\n").write(text)


if __name__ == "__main__":
    main()
