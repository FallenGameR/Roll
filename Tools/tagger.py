"""Веб-интерфейс для простановки жанровых тегов треку, который играет в Winamp.

Зачем это нужно. Теги ставятся командой Set-Track, и команда хороша всем, кроме
скорости работы руками: чтобы пометить трек, надо вспомнить путь к файлу,
вспомнить допустимые значения и набрать строку. Слушать при этом всё равно
приходится в плеере. Интерфейс убирает переписывание: Winamp говорит, что
играет прямо сейчас, а Мастер щёлкает галочки.

    python tagger.py [--port 8731] [--no-browser]

Три решения, которые стоит знать, прежде чем править этот файл.

**Теги пишет Set-Track, а не эта страница.** Команда правит ID3 на месте, а не
подменяет файл, поэтому писать можно и в звучащий трек: Winamp запрещает не
запись в файл, а его замену. Второй дороги записи здесь нет намеренно - формат
тега и порядок категорий живут в модуле, и вторая их копия разошлась бы с первой
молча. Ради этого рядом держится процесс pwsh: холодный запуск с импортом модуля
стоит 4.6 с, а вызов в уже поднятом хосте - доли секунды.

**Список значений читается из Get-GenreTaxonomy.ps1, а не дублируется.** Там он
и так есть, вместе с пояснениями, которые страница показывает подсказкой.

**Путь к файлу берётся у Winamp по IPC, а не из заголовка окна.** Заголовок
показывает "717. Gears 5 - Fracture", а тег надо записать в конкретный mp3, и
одинаковых названий в библиотеке хватает.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mutagen.id3 import ID3, TCON, POPM
from mutagen.id3._util import ID3NoHeaderError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winamp_now  # noqa: E402

ROLL = r"C:\vaults\Roll"
TAXONOMY = os.path.join(ROLL, "Private", "Get-GenreTaxonomy.ps1")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
MARKER = "<<<roll-tagger-done>>>"


# --- таксономия -------------------------------------------------------------

def load_taxonomy():
    """Значения по категориям, пояснения к ним и мета-флаги - из файла модуля."""
    text = open(TAXONOMY, encoding="utf-8-sig").read()
    order = re.search(r"RollGenreCategoryOrder\s*=\s*@\(([^)]*)\)", text)
    categories = [c.strip(" '\"") for c in order.group(1).split(",")] if order else []

    values = {c: [] for c in categories}
    body = re.search(r"RollGenreTaxonomy\s*=\s*@\{(.*?)\n\}", text, re.S).group(1)
    for value, category in re.findall(r"'([^']+)'\s*=\s*'([^']+)'", body):
        values.setdefault(category, []).append(value)

    meta_block = re.search(r"RollGenreMetaTags\s*=\s*@\(([^)]*)\)", text).group(1)
    meta = [m.strip(" '\"") for m in meta_block.split(",") if m.strip()]

    help_body = re.search(r"RollGenreHelp\s*=\s*@\{(.*?)\n\}", text, re.S)
    hints = {}
    if help_body:
        for value, hint in re.findall(r"'([^']+)'\s*=\s*'(.*?)'\s*$",
                                      help_body.group(1), re.M):
            hints[value] = hint.replace("''", "'")

    # Внутри категории значения идут по алфавиту: так их находят глазами.
    # Кроме Intensity - там порядок таксономии сам по себе шкала, от ровного
    # фона до пика, и алфавит эту шкалу ломает.
    for category in values:
        if category != "Intensity":
            values[category].sort(key=str.lower)
    return categories, values, sorted(meta, key=str.lower), hints


CATEGORIES, VALUES, META, HINTS = load_taxonomy()


# --- живой PowerShell -------------------------------------------------------

class PwshHost:
    """Один процесс pwsh с загруженным Roll, команды идут построчно в stdin."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = subprocess.Popen(
            ["pwsh", "-NoLogo", "-NoProfile", "-Command", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self.run("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                 "Import-Module C:\\vaults\\Roll\\Roll.psd1 -Force")

    def run(self, command):
        with self.lock:
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.write(f"Write-Output '{MARKER}'\n")
            self.proc.stdin.flush()
            out = []
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("pwsh закрылся: " + "".join(out))
                if MARKER in line:
                    break
                out.append(line)
            return "".join(out).strip()


    def close(self):
        try:
            self.proc.stdin.write("exit\n")
            self.proc.stdin.flush()
        except Exception:  # noqa: BLE001 - процесс мог уже уйти
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


HOST = None


def ps_quote(value):
    """Строковый литерал для pwsh; не-ASCII уезжает через base64.

    Хост pwsh читает stdin кодовой страницей консоли, а не UTF-8, и
    выставить ему InputEncoding уже поздно: поток открыт при запуске.
    Поэтому буква вроде 'ł' в имени файла приезжала как '┼é', Set-Track
    не находил файл, а страница всё равно рапортовала "записано".
    Base64 состоит из ASCII и проходит любую кодовую страницу целым.
    """
    text = str(value)
    if text.isascii():
        return "'" + text.replace("'", "''") + "'"
    packed = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{packed}')))"


def ps_array(values):
    return "@(" + ",".join(ps_quote(v) for v in values) + ")" if values else "@()"


# --- теги файла -------------------------------------------------------------

def probe_tags(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format_tags", "-of", "json", "--", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return json.loads(out.stdout.decode("utf-8", "replace")).get("format", {}).get("tags", {})
    except json.JSONDecodeError:
        return {}


def parse_genre(genre):
    """'Intensity:Background,Tension Meta:Unsorted' -> словарь категорий."""
    result = {c: [] for c in CATEGORIES}
    result["Meta"] = []
    if not genre:
        return result
    for chunk in re.findall(r"(\w+):([^\s]+)", genre):
        category, raw = chunk
        result.setdefault(category, []).extend(v for v in raw.split(",") if v)
    return result


def comment_sections(comment):
    """Пять секций комментария: Situation идёт первой и без подписи."""
    if not comment:
        return {}
    parts = re.split(r"\n\s*\n", comment)
    sections = {"Situation": parts[0].strip()}
    for part in parts[1:]:
        m = re.match(r"(\w+):\s*(.*)", part.strip(), re.S)
        if m:
            sections[m.group(1)] = m.group(2).strip()
    return sections


# --- звёзды -----------------------------------------------------------------
#
# Рейтинг Winamp живёт в его базе медиатеки, а она пишется только при выходе из
# плеера, так что свежая звезда оттуда не видна. IPC-сообщения рейтинга в этой
# сборке молчат: GETRATING всегда отдаёт 1, SETRATING ничего не меняет. Поэтому
# звёзды хранятся в самом файле, во фрейме POPM - стандартном поле рейтинга,
# которое читают и Winamp, и все остальные плееры, и которое переживёт
# переустановку. База медиатеки при этом остаётся запасным источником для
# треков, оценённых раньше.

POPM_EMAIL = "rating@winamp.com"
STARS_TO_POPM = {1: 1, 2: 64, 3: 128, 4: 196, 5: 255}


def popm_to_stars(value):
    for stars, edge in ((5, 224), (4, 160), (3, 96), (2, 32), (1, 1)):
        if value >= edge:
            return stars
    return 0


_db_ratings = {"at": 0.0, "map": {}}


def db_ratings():
    """Оценки из базы медиатеки, обновляются не чаще раза в полминуты."""
    import time
    if time.time() - _db_ratings["at"] < 30:
        return _db_ratings["map"]
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "winamp_ratings", os.path.join(ROLL, "Tools", "read-winamp-ratings.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _db_ratings["map"] = {k.lower(): v for k, v in module.read_ratings().items()}
    except Exception:  # noqa: BLE001 - база может быть занята плеером
        pass
    _db_ratings["at"] = time.time()
    return _db_ratings["map"]


def read_stars(path, tags=None):
    """Оценка трека и откуда она взята.

    Фрейм POPM с нулём - это осознанно снятая оценка, а не её отсутствие:
    иначе синхронизация вернула бы звезду из базы плеера, которую Мастер
    только что убрал.
    """
    try:
        frames = ID3(path)
    except Exception:  # noqa: BLE001
        frames = None
    if frames:
        popm = frames.getall("POPM")
        if popm:
            return max(popm_to_stars(f.rating) for f in popm), "file"
    stars = db_ratings().get(path.lower(), 0)
    return (stars, "winamp") if stars else (0, "")


def write_stars(path, stars):
    """Пишет оценку в файл. Ноль тоже пишется - как явное «снято»."""
    try:
        frames = ID3(path)
    except ID3NoHeaderError:
        frames = ID3()
    frames.delall("POPM")
    frames.add(POPM(email=POPM_EMAIL, rating=STARS_TO_POPM.get(stars, 0), count=0))
    frames.save(path, v2_version=3)
    return stars


_playlist_cache = {"at": 0.0, "items": [], "length": -1}


def playlist_state():
    """Список плеера с кэшем: имена тянутся по вызову на трек.

    Длину спрашиваем каждый раз - это один дешёвый вызов, и по ней сразу видно,
    что список правили. Полностью перечитываем ещё и раз в пятнадцать секунд:
    длина не меняется, когда трек заменили другим.
    """
    import time
    now = winamp_now.current()
    if not now.get("running"):
        return {"items": [], "index": -1}

    length = winamp_now.playlist_length()
    stale = time.time() - _playlist_cache["at"] > 15
    if length != _playlist_cache["length"] or stale:
        items = winamp_now.playlist()
        _playlist_cache.update({"at": time.time(), "items": items,
                                "length": len(items)})
    return {"items": _playlist_cache["items"], "index": now.get("index", -1)}


def track_state():
    now = winamp_now.current()
    if not now.get("running"):
        return {"running": False}
    path = now.get("path") or ""
    if not path or not os.path.exists(path):
        return {"running": True, "state": now.get("state"), "path": path,
                "error": "Winamp играет файл, которого нет на диске"}

    tags = probe_tags(path)
    genre = parse_genre(tags.get("genre", ""))
    sections = comment_sections(tags.get("comment", ""))
    stars, stars_from = read_stars(path)
    return {
        "running": True,
        "state": now.get("state"),
        "path": path,
        "name": os.path.splitext(os.path.basename(path))[0],
        "folder": os.path.basename(os.path.dirname(path)),
        "title": tags.get("title", ""),
        "album": tags.get("album", ""),
        "artist": tags.get("artist", ""),
        "genre_raw": tags.get("genre", ""),
        "selected": genre,
        "meta": genre.get("Meta", []),
        "stars": stars,
        "stars_from": stars_from,
        "volume": winamp_now.volume(),
        "elapsed_ms": now.get("elapsed_ms", 0),
        "length_sec": now.get("length_sec", 0),
        "index": now.get("index", -1),
        "situation": sections.get("Situation", ""),
        "description": sections.get("Description", ""),
        "evidence": sections.get("Evidence", ""),
        "note": sections.get("Note", ""),
        "source": sections.get("Source", ""),
    }


def write_tags(path, selected, meta):
    """Пишет теги командой модуля - другой дороги записи здесь нет.

    Раньше страница собирала строку genre сама и клала её в файл, потому что
    Set-Track подменял mp3 целиком и спотыкался о занятый Winamp'ом трек.
    Теперь команда правит ID3 на месте, так что смысла во второй дороге не
    осталось: пишем тем же, чем пишется всё остальное в библиотеке.
    """
    args = [f"-Path {ps_quote(path)}"]
    for category in CATEGORIES:
        args.append(f"-{category} {ps_array(selected.get(category, []))}")
    for flag in META:
        args.append(f"-Is{flag} ${'true' if flag in meta else 'false'}")
    command = ("try { Set-Track " + " ".join(args) + " -Apply -ErrorAction Stop "
               "| Out-Null } catch { Write-Output \"ROLLERR $($_.Exception.Message)\" }")
    out = HOST.run(command)
    for line in (out or "").splitlines():
        if line.startswith("ROLLERR"):
            raise RuntimeError(line[len("ROLLERR"):].strip())
    return out


# --- сервер -----------------------------------------------------------------

ICON_CACHE = {}

# В exe восемнадцать иконок, и порядок не совпадает с диалогом "Change
# Icon". Нужна та, на которую ссылается сам ярлык Winamp: winamp.exe,3 -
# молния на серебристом ромбе. Тёмная скруглённая плашка вокруг неё в
# меню Пуск дорисована Windows и в файле не лежит.
ICON_INDEX = 3
ICON_SIZE = 64


def winamp_icon():
    """Иконка вкладки берётся из установленного winamp.exe, а не хранится у нас."""
    if "png" in ICON_CACHE:
        return ICON_CACHE["png"]
    exe = None
    for candidate in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Winamp" / "winamp.exe",
                      Path(os.environ.get("ProgramFiles", "")) / "Winamp" / "winamp.exe"):
        if candidate.is_file():
            exe = candidate
            break
    data = None
    if exe:
        tmp = Path(tempfile.gettempdir()) / "roll-winamp-icon.png"
        script = ("Import-Module C:\\vaults\\Roll\\Roll.psd1 -Force; "
                  f"Get-ExeIcon -Path '{exe}' -Index {ICON_INDEX} -Size {ICON_SIZE} "
                  f"-Destination '{tmp}' | Out-Null")
        try:
            subprocess.run(["pwsh", "-NoLogo", "-NoProfile", "-Command", script],
                           capture_output=True, timeout=30)
            data = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
        except Exception:
            data = None
    ICON_CACHE["png"] = data
    return data

PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Winamp Playlist</title>
<link rel="icon" type="image/png" href="/favicon.png">
<style>
 :root { color-scheme: dark; }
 body { margin:0; font:15px/1.5 "Segoe UI",sans-serif; background:#15161a; color:#dcdde1; }
 header { padding:12px 20px; background:#1d1f26; border-bottom:1px solid #2c2f38;
          position:sticky; top:0; z-index:5;
          display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
 h1 { font-size:19px; margin:0; font-weight:600; }
 .folder { color:#8b8f9c; font-size:13px; }
 .transport { display:flex; gap:5px; }
 .transport button { font-size:15px; line-height:1; padding:7px 11px; cursor:pointer;
                     background:#242731; color:#dcdde1; border:1px solid #333744;
                     border-radius:6px; }
 .transport button:hover { background:#2e3240; border-color:#4a5164; }
 .transport button:active { background:#3a4052; }
 .stars { display:flex; gap:2px; margin-left:4px; }
 .stars span { font-size:20px; line-height:1; cursor:pointer; color:#3c414f; padding:0 1px; }
 .stars span.on { color:#e3b341; }
 .stars span:hover { color:#f0c862; }
 .vol { display:flex; align-items:center; gap:7px; }
 .vol input[type=range] { width:120px; accent-color:#5aa7d8; }
 .vol span { font-size:12px; color:#8b8f9c; min-width:30px; text-align:right; }
 .seek { display:flex; align-items:center; gap:7px; margin-left:auto; }
 .seek input[type=range] { width:200px; accent-color:#5aa7d8; }
 .seek span { font-size:12px; color:#8b8f9c; min-width:78px; }
 .state { font-size:13px; color:#8b8f9c; min-width:80px; text-align:right; }
 .saved { color:#7ec97e; }
 .failed { color:#e07a7a; }
 .columns { display:flex; align-items:flex-start; gap:24px; padding:18px 20px 14px; }
 main { flex:1 1 auto; min-width:0; display:flex; flex-direction:column;
        min-height:calc(100vh - 94px); }
 aside { flex:0 0 510px; margin-left:auto; position:sticky; top:66px;
         max-height:calc(100vh - 86px); overflow:auto;
         border-left:1px solid #2c2f38; padding-left:16px; }
 aside h2 { font-size:12px; text-transform:uppercase; letter-spacing:.09em;
            color:#8b8f9c; margin:0 0 8px; font-weight:600; }
 .pl { list-style:none; margin:0; padding:0; font-size:13px; }
 .pl li { padding:5px 8px; border-radius:5px; cursor:pointer; color:#a9adba;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 .pl li:hover { background:#232733; color:#dcdde1; }
 .pl li.now { background:#2b4a63; color:#eaf4fb; }
 .pl li b { color:#6f7585; font-weight:400; margin-right:7px; }
 .cat { margin-bottom:18px; }
 .cat h2 { font-size:12px; text-transform:uppercase; letter-spacing:.09em;
           color:#8b8f9c; margin:0 0 7px; font-weight:600; }
 .row { display:flex; flex-wrap:wrap; gap:6px; }
 label { display:inline-flex; align-items:center; gap:5px; padding:5px 9px;
         border:1px solid #333744; border-radius:6px; background:#1b1d24;
         cursor:pointer; user-select:none; font-size:14px; white-space:nowrap; }
 label:hover { border-color:#4a5164; }
 label.on { background:#2b4a63; border-color:#43708f; color:#eaf4fb; }
 label.meta.on { background:#5a4320; border-color:#8a6a33; color:#f6ead6; }
 input { accent-color:#5aa7d8; margin:0; }
 .prose { margin-top:auto; border-top:1px solid #2c2f38; padding-top:16px;
          color:#b9bdc9; font-size:16px; line-height:1.55; }
 .prose div { margin-bottom:11px; }
 .prose b { color:#e6e8ee; font-weight:700; }
 .idle { padding:40px 20px; color:#8b8f9c; }
 code { color:#7f8596; font-size:12px; }
</style></head><body>
<header>
  <div class="transport">
    <button data-cmd="prev"  title="предыдущий">⏮</button>
    <button data-cmd="play"  title="играть">▶</button>
    <button data-cmd="pause" title="пауза">⏸</button>
    <button data-cmd="stop"  title="стоп">⏹</button>
    <button data-cmd="next"  title="следующий">⏭</button>
  </div>
  <div class="stars" id="stars" title="звёзды пишутся в сам файл"></div>
  <h1 id="name">…</h1><span class="folder" id="folder"></span>
  <div class="seek">
    <input type="range" id="seek" min="0" max="1000" value="0" title="перемотка">
    <span id="seeknum"></span>
  </div>
  <div class="vol">
    <input type="range" id="vol" min="0" max="255" value="255" title="громкость">
    <span id="volnum"></span>
  </div>
  <span class="state" id="state"></span>
</header>
<div class="columns">
  <main id="main"><div class="idle">Жду Winamp…</div></main>
  <aside>
    <h2>Плейлист</h2>
    <ul class="pl" id="playlist"></ul>
  </aside>
</div>
<script>
const CATS = __CATS__, VALUES = __VALUES__, META = __META__, HINTS = __HINTS__;
let cur = null, saving = false, plDrawn = "";

function esc(s){ return (s||"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function setState(text, cls){
  const st = document.getElementById("state");
  st.textContent = text; st.className = "state" + (cls ? " " + cls : "");
}

function renderStars(n){
  const box = document.getElementById("stars");
  box.innerHTML = "";
  for (let i = 1; i <= 5; i++){
    const s = document.createElement("span");
    s.textContent = i <= n ? "★" : "☆";
    if (i <= n) s.className = "on";
    // Повторный щелчок по последней звезде снимает оценку целиком.
    s.onclick = () => saveStars(i === n ? 0 : i);
    box.appendChild(s);
  }
}

function render(d){
  document.getElementById("name").textContent = d.name || "";
  document.getElementById("folder").textContent = d.folder ? "/" + d.folder : "";
  renderStars(d.stars || 0);
  let html = "";
  for (const cat of CATS){
    const on = new Set(d.selected[cat] || []);
    html += `<div class="cat"><h2>${cat}</h2><div class="row">`;
    for (const v of VALUES[cat] || []){
      const id = "t_" + cat + "_" + v;
      html += `<label class="${on.has(v)?"on":""}" for="${id}" title="${esc(HINTS[v]||"")}">
               <input type="checkbox" id="${id}" data-cat="${cat}" data-val="${v}"
                      ${on.has(v)?"checked":""}>${v}</label>`;
    }
    html += `</div></div>`;
  }
  const meta = new Set(d.meta || []);
  html += `<div class="cat"><h2>Meta</h2><div class="row">`;
  for (const v of META){
    const id = "t_Meta_" + v;
    html += `<label class="meta ${meta.has(v)?"on":""}" for="${id}" title="${esc(HINTS[v]||"")}">
             <input type="checkbox" id="${id}" data-cat="Meta" data-val="${v}"
                    ${meta.has(v)?"checked":""}>${v}</label>`;
  }
  html += `</div></div>`;

  html += `<div class="prose">`;
  if (d.situation)   html += `<div><b>Situation.</b> ${esc(d.situation)}</div>`;
  if (d.description) html += `<div><b>Description.</b> ${esc(d.description)}</div>`;
  if (d.evidence)    html += `<div><b>Evidence.</b> ${esc(d.evidence)}</div>`;
  if (d.note)        html += `<div><b>Note.</b> ${esc(d.note)}</div>`;
  html += `<div><code>${esc(d.path)}</code></div></div>`;
  document.getElementById("main").innerHTML = html;

  // Слушаем change самого поля, а не click по label: щелчок по label
  // браузер и так передаёт полю, и обработчик на обоих срабатывал дважды,
  // возвращая галочку обратно.
  document.querySelectorAll("input[data-cat]").forEach(box => {
    box.addEventListener("change", () => {
      box.closest("label").classList.toggle("on", box.checked);
      save();
    });
  });
}

function collect(){
  const sel = {}, meta = [];
  for (const cat of CATS) sel[cat] = [];
  document.querySelectorAll("input[data-cat]").forEach(box => {
    if (!box.checked) return;
    const cat = box.dataset.cat, val = box.dataset.val;
    if (cat === "Meta") meta.push(val); else sel[cat].push(val);
  });
  return {path: cur.path, selected: sel, meta: meta};
}

async function save(){
  saving = true;
  setState("пишу…");
  try {
    const r = await fetch("/api/tags", {method:"POST", body: JSON.stringify(collect())});
    const j = await r.json();
    if (j.ok){ setState("записано", "saved"); cur.genre_raw = j.genre; }
    else setState("ошибка: " + j.error, "failed");
  } catch(e){ setState("ошибка: " + e, "failed"); }
  saving = false;
}

async function saveStars(n){
  if (!cur) return;
  saving = true;
  setState("пишу…");
  renderStars(n);
  try {
    const r = await fetch("/api/stars", {method:"POST",
      body: JSON.stringify({path: cur.path, stars: n})});
    const j = await r.json();
    if (j.ok){ setState(n ? "звёзды: " + n : "звёзды сняты", "saved"); cur.stars = n; }
    else setState("ошибка: " + j.error, "failed");
  } catch(e){ setState("ошибка: " + e, "failed"); }
  saving = false;
}

document.querySelectorAll(".transport button").forEach(b => {
  b.onclick = () => fetch("/api/control", {method:"POST",
    body: JSON.stringify({cmd: b.dataset.cmd})});
});

const volBox = document.getElementById("vol");
let volTouched = 0;
volBox.addEventListener("input", () => {
  volTouched = Date.now();
  document.getElementById("volnum").textContent =
    Math.round(volBox.value / 255 * 100) + "%";
  fetch("/api/volume", {method:"POST", body: JSON.stringify({level: +volBox.value})});
});

const seekBox = document.getElementById("seek");
let seekTouched = 0, seekLen = 0;

function mmss(sec){
  sec = Math.max(0, Math.round(sec));
  return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
}

function showSeek(sec){
  document.getElementById("seeknum").textContent =
    seekLen ? mmss(sec) + " / " + mmss(seekLen) : "";
}

seekBox.addEventListener("input", () => {
  seekTouched = Date.now();
  showSeek(+seekBox.value);
});
seekBox.addEventListener("change", () => {
  seekTouched = Date.now();
  fetch("/api/seek", {method:"POST", body: JSON.stringify({ms: +seekBox.value * 1000})});
});

function renderPlaylist(items, index){
  const ul = document.getElementById("playlist");
  // Перерисовываем список только когда он сам поменялся: иначе каждую
  // секунду сбрасывалась бы прокрутка. Отпечаток берём по всем именам -
  // трек могли не удалить, а заменить, и тогда длина не меняется.
  const stamp = items.map(i => i.name).join("\u0001");
  if (stamp !== plDrawn){
    plDrawn = stamp;
    ul.innerHTML = items.map(it =>
      `<li data-i="${it.index}" title="${esc(it.name)}"><b>${it.index + 1}</b>${esc(it.name)}</li>`
    ).join("");
    ul.querySelectorAll("li").forEach(li => {
      li.onclick = () => fetch("/api/jump", {method:"POST",
        body: JSON.stringify({index: +li.dataset.i})});
    });
  }
  ul.querySelectorAll("li").forEach(li => {
    const on = +li.dataset.i === index;
    li.classList.toggle("now", on);
    if (on && !li.dataset.seen){ li.dataset.seen = "1";
      li.scrollIntoView({block:"nearest"}); }
  });
}

async function pollPlaylist(){
  try {
    const d = await (await fetch("/api/playlist")).json();
    renderPlaylist(d.items || [], d.index);
  } catch(e){ }
}

async function poll(){
  try {
    const d = await (await fetch("/api/now")).json();
    if (!d.running){
      document.getElementById("main").innerHTML = '<div class="idle">Winamp не запущен.</div>';
      document.getElementById("name").textContent = "—"; cur = null;
    } else if (d.error){
      document.getElementById("main").innerHTML = '<div class="idle">' + esc(d.error) + '</div>';
      cur = null;
    } else if (!cur || cur.path !== d.path){
      cur = d; render(d); setState(d.state);
    } else if (!saving) {
      const st = document.getElementById("state");
      if (!st.classList.contains("saved") && !st.classList.contains("failed"))
        setState(d.state);
    }
    // Ползунки не трогаем секунду после того, как их двигали руками,
    // иначе они дёргаются назад на ответе плеера.
    if (d.volume != null && Date.now() - volTouched > 1000){
      volBox.value = d.volume;
      document.getElementById("volnum").textContent =
        Math.round(d.volume / 255 * 100) + "%";
    }
    if (d.length_sec){
      if (seekLen !== d.length_sec){ seekLen = d.length_sec; seekBox.max = d.length_sec; }
      if (Date.now() - seekTouched > 1000){
        seekBox.value = Math.round((d.elapsed_ms || 0) / 1000);
        showSeek(+seekBox.value);
      }
    }
  } catch(e){ /* сервер перезапускается - просто ждём */ }
}
setInterval(poll, 700); poll();
setInterval(pollPlaylist, 1000); pollPlaylist();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/favicon.png"):
            icon = winamp_icon()
            if icon:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(icon)))
                self.end_headers()
                self.wfile.write(icon)
            else:
                self._send(404, "нет иконки")
            return
        if self.path.startswith("/api/now"):
            self._send(200, json.dumps(track_state(), ensure_ascii=False))
            return
        if self.path.startswith("/api/playlist"):
            self._send(200, json.dumps(playlist_state(), ensure_ascii=False))
            return
        page = (PAGE.replace("__CATS__", json.dumps(CATEGORIES))
                    .replace("__VALUES__", json.dumps(VALUES, ensure_ascii=False))
                    .replace("__META__", json.dumps(META))
                    .replace("__HINTS__", json.dumps(HINTS, ensure_ascii=False)))
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        try:
            if self.path.startswith("/api/control"):
                ok = winamp_now.control(payload.get("cmd", ""))
                self._send(200, json.dumps({"ok": ok}))
                return
            if self.path.startswith("/api/volume"):
                level = winamp_now.volume(payload["level"])
                self._send(200, json.dumps({"ok": True, "volume": level}))
                return
            if self.path.startswith("/api/seek"):
                ok = winamp_now.seek(payload["ms"])
                self._send(200, json.dumps({"ok": ok}))
                return
            if self.path.startswith("/api/jump"):
                ok = winamp_now.jump(payload["index"])
                self._send(200, json.dumps({"ok": ok}))
                return
            if self.path.startswith("/api/stars"):
                stars = write_stars(payload["path"], int(payload["stars"]))
                self._send(200, json.dumps({"ok": True, "stars": stars}))
                return
            write_tags(payload["path"], payload["selected"], payload["meta"])
            genre = probe_tags(payload["path"]).get("genre", "")
            self._send(200, json.dumps({"ok": True, "genre": genre}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 - показываем причину в интерфейсе
            self._send(200, json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))


def main():
    global HOST
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    HOST = PwshHost()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"фонотека: {url}  (Ctrl+C чтобы закрыть)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Хост pwsh держится за консоль и осиротел бы молча.
        HOST.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
