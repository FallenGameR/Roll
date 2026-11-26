# -*- coding: utf-8 -*-
# Decode hashed names in .qmd mods via the tablet hashtab.
# Usage: python decode-qmd.py <dir with hashtab> <mods dir>
# Writes <mods dir>\decoded\..., prints hashes missing from this firmware.
import struct, re, sys, os, glob
d, root = sys.argv[1], sys.argv[2]
b = open(os.path.join(d, "hashtab"), "rb").read()
tab, i = {}, 0
while i + 12 <= len(b):
    h, n = struct.unpack(">QI", b[i:i+12]); i += 12
    tab[h] = b[i:i+n].decode("utf-8", "replace"); i += n
miss = []
def name(m):
    q, s = m.group(1), m.group(2)
    parts = []
    for p in s.split("."):
        if int(p) in tab: parts.append(tab[int(p)])
        else: miss.append(p); parts.append("<нет в прошивке:" + p + ">")
    v = ".".join(parts)
    return f'"{v}"' if q else v
out = os.path.join(root, "decoded")
for f in sorted(glob.glob(os.path.join(root, "**", "*.qmd"), recursive=True)):
    if os.sep + "decoded" + os.sep in f: continue
    rel = os.path.relpath(f, root)
    src = open(f, encoding="utf-8").read()
    dec = re.sub(r"\[\[(\"?)([\d.]+)\]\]", name, src)
    dec = re.sub(r"~&(\"?)([\d.]+)&~", name, dec)
    dst = os.path.join(out, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8", newline="\n").write(dec)
print("unresolved:", sorted(set(miss)))
