# -*- coding: utf-8 -*-
import json, os, subprocess, time
R = r"C:\vaults\Рудники Фанделвера"
while "Obsidian.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"], capture_output=True, text=True).stdout:
    time.sleep(3)
time.sleep(2)
p = os.path.join(R, ".obsidian/plugins/obsidian-5e-statblocks/data.json")
d = json.load(open(p, encoding="utf-8"))
d["paths"] = [x.replace("DnD Rules/", "DnD Notes/") for x in d["paths"]]
open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2))
p2 = os.path.join(R, ".obsidian/plugins/initiative-tracker/data.json")
t = open(p2, encoding="utf-8").read(); n = t.count('"DnD Rules/')
t = t.replace('"DnD Rules/', '"DnD Notes/'); json.loads(t)
open(p2, "w", encoding="utf-8", newline="\n").write(t)
print("statblocks:", d["paths"], "| tracker paths:", n, "| DONE", flush=True)
