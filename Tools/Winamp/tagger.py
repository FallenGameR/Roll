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

ROLL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROLL_PSD1 = os.path.join(ROLL, "Roll.psd1")
TAXONOMY = os.path.join(ROLL, "Private", "Music", "Get-GenreTaxonomy.ps1")
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

    # Intensity, Emotion и Scene идут в порядке словаря: там он задан
    # нарочно (по нарастанию, от тёмного к светлому, группы сцен по
    # панели), и алфавит его ломает. Game и Type - по алфавиту.
    for category in values:
        if category not in ("Intensity", "Emotion", "Scene"):
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
                 f"Import-Module {ps_quote(ROLL_PSD1)} -Force")

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
            "winamp_ratings", os.path.join(ROLL, "Tools", "Winamp", "read-winamp-ratings.py"))
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
        # Звёзды - пометка «теги проставлены»: Мастер ставит их после
        # разметки, и в списке видно, что ещё не размечено.
        for item in items:
            item["stars"] = read_stars(item["path"])[0] if item["path"] else 0
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
                "shuffle": now.get("shuffle", False), "repeat": now.get("repeat", False),
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
        "shuffle": now.get("shuffle", False),
        "repeat": now.get("repeat", False),
        "situation": sections.get("Situation", ""),
        "description": sections.get("Description", ""),
        "measurement": sections.get("Measurement", ""),
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


def winamp_exe():
    for candidate in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Winamp" / "winamp.exe",
                      Path(os.environ.get("ProgramFiles", "")) / "Winamp" / "winamp.exe"):
        if candidate.is_file():
            return candidate
    return None


def launch_winamp():
    """Запускает Winamp, если он ещё не запущен. Через оболочку, чтобы плеер
    не зависел от сервера и пережил его остановку."""
    if winamp_now.current().get("running"):
        return
    exe = winamp_exe()
    if not exe:
        raise RuntimeError("winamp.exe не найден в Program Files")
    os.startfile(exe)


CATALOG = Path(os.environ.get("APPDATA", "")) / "Winamp" / "Plugins" / "ml" / "playlists"


def scenes():
    """Плейлисты медиатеки, чьё имя начинается с точки: их выгружает
    Import-WinampPlaylist из файлов кампании. Остальные - личные Мастера,
    селектору они не нужны."""
    import xml.etree.ElementTree as ET
    index = CATALOG / "playlists.xml"
    if not index.exists():
        return []
    result = []
    for node in ET.parse(index).getroot():
        title = node.get("title") or ""
        m3u = CATALOG / (node.get("filename") or "")
        if not title.startswith(".") or not m3u.is_file():
            continue
        tracks = [line.strip() for line in m3u.read_text(encoding="utf-8-sig").splitlines()
                  if line.strip() and not line.startswith("#")]
        place, _, scene = title[1:].partition(" - ")
        result.append({"title": title, "place": place, "scene": scene,
                       "tracks": tracks, "seconds": int(node.get("seconds") or 0)})
    return result


def scenes_state():
    """Список сцен и та, что сейчас в плеере: она узнаётся по совпадению
    треков, так что кнопка не врёт, даже если плейлист открыли в самом Winamp."""
    items = playlist_state().get("items", [])
    loaded = [i["path"].lower() for i in items]
    out, current = [], ""
    for s in scenes():
        if loaded and [t.lower() for t in s["tracks"]] == loaded:
            current = s["title"]
        out.append({k: s[k] for k in ("title", "place", "scene", "seconds")}
                   | {"songs": len(s["tracks"])})
    return {"scenes": out, "current": current}


def drop_from_scene(queue, index, path):
    """Вычёркивает трек из сцены медиатеки, если очередь плеера - эта сцена.

    Удаление из очереди само по себе живёт до следующего выбора сцены, а
    Мастер удаляет, чтобы подобрать музыку к месту. Поэтому трек убирается и
    из .m3u8 сцены в медиатеке; оттуда Sync-WinampPlaylist перенесёт правку в
    markdown кампании. Сцена узнаётся по совпадению всех треков, как и в
    scenes_state, а вычёркивается ровно строка с этим номером.
    """
    import xml.etree.ElementTree as ET
    index_file = CATALOG / "playlists.xml"
    if not index_file.exists():
        return ""
    wanted = [p.lower() for p in queue]
    for node in ET.parse(index_file).getroot():
        title = node.get("title") or ""
        m3u = CATALOG / (node.get("filename") or "")
        if not title.startswith(".") or not m3u.is_file():
            continue
        lines = m3u.read_text(encoding="utf-8-sig").splitlines()
        tracks = [i for i, line in enumerate(lines) if line.strip() and not line.startswith("#")]
        if [lines[i].strip().lower() for i in tracks] != wanted:
            continue
        if not 0 <= index < len(tracks) or lines[tracks[index]].strip().lower() != path.lower():
            return ""
        del lines[tracks[index]]
        # Winamp пишет свои списки в UTF-8 с BOM и CRLF - так и оставляем.
        with open(m3u, "w", encoding="utf-8-sig", newline="\r\n") as handle:
            handle.write("\n".join(lines) + "\n")
        return title
    return ""


def load_scene(title):
    match = next((s for s in scenes() if s["title"] == title), None)
    if not match:
        raise RuntimeError(f"нет плейлиста {title}")
    if not winamp_now.load(match["tracks"]):
        raise RuntimeError("Winamp не запущен")
    _playlist_cache["at"] = 0.0
    return len(match["tracks"])


def winamp_icon():
    """Иконка вкладки берётся из установленного winamp.exe, а не хранится у нас."""
    if "png" in ICON_CACHE:
        return ICON_CACHE["png"]
    exe = winamp_exe()
    data = None
    if exe:
        tmp = Path(tempfile.gettempdir()) / "roll-winamp-icon.png"
        script = (f"Import-Module {ps_quote(ROLL_PSD1)} -Force; "
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
          display:flex; align-items:center; gap:14px; flex-wrap:nowrap; }
 /* Шапка всегда в одну строку: длинное название трека сжимается и
    обрезается многоточием, а не сталкивает ползунки и статус вниз. */
 header > * { flex:none; }
 h1 { font-size:19px; margin:0; font-weight:600;
      flex:0 1 auto !important; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 .folder { color:#8b8f9c; font-size:13px; white-space:nowrap; }
 .transport { display:flex; gap:5px; }
 .transport button { font-size:15px; line-height:1; padding:7px 11px; cursor:pointer;
                     background:#242731; color:#dcdde1; border:1px solid #333744;
                     border-radius:6px; }
 .transport button:hover { background:#2e3240; border-color:#4a5164; }
 .transport button:active { background:#3a4052; }
 button.mode { flex:none; display:flex; align-items:center; justify-content:center; width:40px;
               padding:0; cursor:pointer; background:#242731; color:#6f7585;
               border:1px solid #333744; border-radius:8px; }
 button.mode:hover { background:#2e3240; border-color:#4a5164; }
 button.mode svg { width:17px; height:16px; display:block; }
 button.mode.on { background:#2b4a63; border-color:#43708f; color:#eaf4fb; }
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
        min-height:calc(100vh / var(--z, 1) - 94px); }
 /* Ширина плейлиста идёт от самого длинного названия, но не меньше 430 px
    (в узком окне - не больше 45% экрана, чтобы не сплющить теги). */
 aside { flex:0 0 auto; min-width:min(430px, 45vw); max-width:760px; margin-left:auto; position:sticky;
         top:calc(var(--hdr, 66px) + 18px);
         height:calc(100vh / var(--z, 1) - var(--hdr, 66px) - 36px); display:flex; flex-direction:column;
         border-left:1px solid #2c2f38; padding-left:16px; }
 aside .pl { flex:1 1 auto; overflow:auto; min-height:0; }
 aside h2 { font-size:12px; text-transform:uppercase; letter-spacing:.09em;
            color:#8b8f9c; margin:0 0 8px; font-weight:600; }
 .pl { list-style:none; margin:0; padding:0; font-size:13px; }
 .pl li { padding:5px 8px; border-radius:5px; cursor:pointer; color:#a9adba;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 .pl li:hover { background:#232733; color:#dcdde1; }
 .pl li.now { background:#2b4a63; color:#eaf4fb; }
 .pl li b { color:#6f7585; font-weight:400; margin-right:7px; }
 .pl li .rated { position:absolute; right:10px; top:50%; transform:translateY(-50%);
                 font-style:normal; font-size:12px; color:#6f7585; }
 .pl li { padding-right:26px; }
 .pl li:hover .rated { visibility:hidden; }
 .pl li { position:relative; }
 /* Кнопка лежит поверх конца названия и ширину строки не меняет: колонка
    подстраивается под самую широкую строку и прыгала бы при наведении. */
 .pl li .del { position:absolute; right:3px; top:50%; transform:translateY(-50%); display:none;
               width:24px; height:22px; padding:0; align-items:center; justify-content:center;
               border:1px solid #333744; border-radius:5px; background:#242731; color:#8b8f9c;
               box-shadow:-18px 0 12px -2px #232733; }
 .pl li.now .del { box-shadow:-18px 0 12px -2px #2b4a63; }
 .pl li .del svg { width:14px; height:14px; display:block; }
 .pl li:hover .del { display:flex; }
 .pl li .del:hover { background:#2e3240; border-color:#4a5164; color:#dcdde1; }
 .pl li.gone { opacity:.35; }
 .cat { margin-bottom:18px; }
 .cat h2 { font-size:12px; text-transform:uppercase; letter-spacing:.09em;
           color:#8b8f9c; margin:0 0 7px; font-weight:600; }
 .row { display:flex; flex-wrap:wrap; gap:6px; }
 .grp { display:inline-flex; flex-wrap:wrap; align-items:center; gap:6px; padding:4px 6px;
        border:1px dashed #3a3f4d; border-radius:8px; }
 .grp > span { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:#8b8f9c;
               margin:0 2px 0 4px; }
 .grp:has(input:checked) { border:1px solid #43708f; background:#1a2530; }
 .grp:has(input:checked) > span { color:#b9d3e6; }
 label { display:inline-flex; align-items:center; gap:5px; padding:5px 9px;
         border:1px solid #333744; border-radius:6px; background:#1b1d24;
         cursor:pointer; user-select:none; font-size:14px; white-space:nowrap; }
 label:hover { border-color:#4a5164; }
 label.on { background:#2b4a63; border-color:#43708f; color:#eaf4fb; }
 label.meta.on { background:#5a4320; border-color:#8a6a33; color:#f6ead6; }
 input { accent-color:#5aa7d8; margin:0; }
 .prose { margin-top:auto; border-top:1px solid #2c2f38; padding-top:16px;
          color:#b9bdc9; font-size:14px; line-height:1.5; }
 .prose div { margin-bottom:11px; }
 .prose b { color:#e6e8ee; font-weight:700; }
 .idle { padding:40px 20px; color:#8b8f9c; }
 .launch { margin-left:10px; font:inherit; padding:7px 14px; cursor:pointer; white-space:nowrap;
           background:#2b4a63; color:#eaf4fb; border:1px solid #43708f; border-radius:6px; }
 .launch:hover { background:#345a78; }
 .launch:disabled { cursor:default; opacity:.6; }
 code { color:#7f8596; font-size:12px; }
 .scenebar { flex:0 0 auto; display:flex; gap:6px; margin-top:10px; }
 #scenebtn { flex:1 1 auto; min-width:0; text-align:left;
             font:inherit; font-size:14px; padding:8px 12px; cursor:pointer;
             background:#242731; color:#dcdde1; border:1px solid #43708f; border-radius:8px;
             white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 #scenebtn:hover { background:#2e3240; }
 #scenebtn small { color:#8b8f9c; margin-right:6px; }
 /* Попап сцен живёт в колонке плейлиста и стоит над кнопкой плейлиста
    ровно по её ширине: края берутся от колонки, без расчётов в JS. */
 aside { z-index:6; }
 #scenes { position:absolute; left:16px; right:0; bottom:48px; z-index:21;
           max-height:calc(100vh / var(--z, 1) - 90px); display:none; flex-direction:column;
           background:#1d1f26; border:1px solid #333744; border-radius:10px;
           box-shadow:0 10px 30px rgba(0,0,0,.6); }
 #scenes.open { display:flex; }
 #scenes input { margin:12px 12px 6px; padding:7px 10px; font:inherit; font-size:14px;
                 background:#15161a; color:#dcdde1; border:1px solid #333744; border-radius:6px; }
 #scenelist { overflow:auto; padding:4px 4px 12px; }
 .place { margin-top:8px; padding:6px 8px 2px; border:1px solid transparent; border-radius:8px; }
 .place h3 { font-size:12px; text-transform:uppercase; letter-spacing:.09em;
             color:#8b8f9c; margin:0 0 6px; font-weight:600; }
 /* Локация, где играет текущая сцена, подсвечена так же, как группа тегов
    с отмеченным тегом. Рамка есть у всех групп, но прозрачная, чтобы
    список не сдвигался. */
 .place:has(.scene.now, select.npc.now) { border-color:#43708f; background:#1a2530; }
 .place:has(.scene.now, select.npc.now) h3 { color:#b9d3e6; }
 select.npc { margin:0 6px 6px 0; padding:5px 8px; font:inherit; font-size:14px; color:#dcdde1;
              border:1px solid #333744; border-radius:6px; background:#1b1d24; cursor:pointer; }
 select.npc:hover { border-color:#5aa7d8; }
 select.npc.now { background:#2b4a63; border-color:#43708f; color:#eaf4fb; }
 select.npc option { background:#1d1f26; color:#dcdde1; }
 .scene { display:inline-block; margin:0 6px 6px 0; padding:5px 10px; font-size:14px;
          border:1px solid #333744; border-radius:6px; background:#1b1d24; cursor:pointer; }
 .scene:hover, .scene.hot { border-color:#5aa7d8; }
 .scene.now { background:#2b4a63; border-color:#43708f; color:#eaf4fb; }
 .scene i { color:#7f8596; font-style:normal; font-size:12px; margin-left:6px; }
 .scene.now i { color:#b9d3e6; }
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
    <div class="scenebar">
      <button id="scenebtn" title="Сменить плейлист (клавиша P)"><small>плейлист</small><span id="scenename">…</span></button>
      <button class="mode" data-mode="shuffle" title="случайный порядок"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4.5h2.5c3 0 4 7 7 7H14M2 11.5h2.5c1.2 0 2-1 2.6-2.3M9 6.8c.6-1.3 1.4-2.3 2.6-2.3H14M12 2.5l2 2-2 2M12 9.5l2 2-2 2"/></svg></button>
      <button class="mode" data-mode="repeat"  title="повтор списка по кругу"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V6a2 2 0 0 1 2-2h8M11 2l2 2-2 2M13 9v1a2 2 0 0 1-2 2H3M5 14l-2-2 2-2"/></svg></button>
    </div>
    <div id="scenes">
      <input id="scenefind" placeholder="Локация или сцена… Enter - включить, Esc - закрыть" autocomplete="off">
      <div id="scenelist"></div>
    </div>
  </aside>
</div>
<script>
// Во вкладке приложения (пульт открывает её с #app) страница наследует зум
// приложения. outerWidth в пикселях окна, innerWidth в пикселях страницы:
// их отношение и есть этот зум, и CSS zoom его снимает. 100vh под zoom
// сжимается вместе со страницей, поэтому CSS делит его на --z.
function fitZoom(){
  const root = document.documentElement;
  if (location.hash !== "#app") {
    root.style.removeProperty("zoom");
    root.style.removeProperty("--z");
    return;
  }
  const z = Math.min(1, Math.round(innerWidth / outerWidth * 100) / 100) || 1;
  root.style.zoom = z;
  root.style.setProperty("--z", z);
}
fitZoom();
addEventListener("resize", fitZoom);
addEventListener("hashchange", fitZoom);

// Шапка переносится на вторую строку, когда название трека длинное, и
// правая колонка должна знать её настоящую высоту, иначе кнопка
// плейлиста уезжает под нижний край окна.
new ResizeObserver(() => document.documentElement.style.setProperty(
  "--hdr", document.querySelector("header").offsetHeight + "px"))
  .observe(document.querySelector("header"));

const CATS = __CATS__, VALUES = __VALUES__, META = __META__, HINTS = __HINTS__;
let cur = null, saving = false, plDrawn = "";

function esc(s){ return (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

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
  document.getElementById("name").title = d.name || "";
  document.getElementById("folder").textContent = d.folder ? "/" + d.folder : "";
  renderStars(d.stars || 0);
  let html = "";
  for (const cat of CATS){
    const on = new Set(d.selected[cat] || []);
    html += `<div class="cat"><h2>${cat}</h2><div class="row">`;
    // Scene пишется как Группа(Тег): теги одной группы стоят в общей
    // рамке с подписью группы, на кнопке - только сам тег.
    let group = null;
    for (const v of VALUES[cat] || []){
      const m = cat === "Scene" ? /^(.+)\((.+)\)$/.exec(v) : null;
      const g = m ? m[1] : null;
      if (cat === "Scene" && g !== group){
        if (group) html += `</div>`;
        if (g) html += `<div class="grp"><span>${esc(g)}</span>`;
        group = g;
      }
      const id = "t_" + cat + "_" + v;
      html += `<label class="${on.has(v)?"on":""}" for="${id}" title="${esc(HINTS[v]||"")}">
               <input type="checkbox" id="${id}" data-cat="${cat}" data-val="${v}"
                      ${on.has(v)?"checked":""}>${esc(m ? m[2] : v)}</label>`;
    }
    if (group) html += `</div>`;
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
  if (d.measurement) html += `<div><b>Measurement.</b> ${esc(d.measurement)}</div>`;
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
  // Значения, которых нет в словаре (старая разметка до миграции), галочек
  // не имеют; без этой строки первая же запись стёрла бы их молча.
  for (const cat of CATS) sel[cat] = (cur.selected[cat] || []).filter(v => !(VALUES[cat] || []).includes(v));
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

document.querySelectorAll("button[data-cmd]").forEach(b => {
  b.onclick = () => fetch("/api/control", {method:"POST",
    body: JSON.stringify({cmd: b.dataset.cmd})});
});

// Случайный порядок и повтор: кнопка показывает режим плеера и
// переключает его. Секунду после щелчка опрос её не трогает, иначе
// подсветка мигала бы назад до ответа плеера.
let modeTouched = 0;
document.querySelectorAll("button[data-mode]").forEach(b => {
  b.onclick = () => {
    const on = !b.classList.contains("on");
    b.classList.toggle("on", on); modeTouched = Date.now();
    fetch("/api/mode", {method:"POST", body: JSON.stringify({[b.dataset.mode]: on})});
  };
});
function showModes(d){
  if (Date.now() - modeTouched < 1000) return;
  document.querySelectorAll("button[data-mode]").forEach(b =>
    b.classList.toggle("on", !!d[b.dataset.mode]));
}

const volBox = document.getElementById("vol");
let volTouched = 0, volKnown = false;
volBox.addEventListener("input", () => {
  volTouched = Date.now();
  document.getElementById("volnum").textContent =
    Math.round(volBox.value / 255 * 100) + "%";
  fetch("/api/volume", {method:"POST", body: JSON.stringify({level: +volBox.value})});
});

// Колесо мыши над шапкой и над левой частью с тегами крутит громкость на
// 5% за щелчок. Над плейлистом справа колесо по-прежнему прокручивает его.
function wheelVolume(e){
  if (!e.deltaY) return;
  e.preventDefault();
  // До первого ответа плеера ползунок стоит на 255 по умолчанию, и шаг
  // от него выкрутил бы звук почти на максимум.
  if (!volKnown) return;
  const step = Math.round(255 * 0.05) * (e.deltaY < 0 ? 1 : -1);
  volBox.value = Math.max(0, Math.min(255, +volBox.value + step));
  volBox.dispatchEvent(new Event("input"));
}
for (const el of [document.querySelector("header"), document.getElementById("main")])
  el.addEventListener("wheel", wheelVolume, {passive: false});

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

const TRASH = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" ' +
  'stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v4.5M9.2 6.5v4.5"/></svg>';

function renderPlaylist(items, index){
  const ul = document.getElementById("playlist");
  // Перерисовываем список только когда он сам поменялся: иначе каждую
  // секунду сбрасывалась бы прокрутка. Отпечаток берём по всем именам -
  // трек могли не удалить, а заменить, и тогда длина не меняется.
  const stamp = items.map(i => i.name + "\u0002" + (i.stars ? 1 : 0)).join("\u0001");
  if (stamp !== plDrawn){
    plDrawn = stamp;
    ul.innerHTML = items.map(it =>
      `<li data-i="${it.index}" data-p="${esc(it.path)}" title="${esc(it.name)}"><b>${it.index + 1}</b>${esc(it.name)}` +
      (it.stars ? `<i class="rated" title="оценён: ${it.stars}★, теги проставлены">★</i>` : "") +
      `<span class="del" title="убрать из плейлиста (Delete)">${TRASH}</span></li>`
    ).join("");
    ul.querySelectorAll("li").forEach(li => {
      li.onclick = e => {
        if (e.target.closest(".del")) { removeTrack(li); return; }
        fetch("/api/jump", {method:"POST", body: JSON.stringify({index: +li.dataset.i})});
      };
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

// Убрать трек из плейлиста плеера: крестиком при наведении или клавишей
// Delete. Delete берёт трек под курсором, а если курсор не над списком -
// тот, что играет. Сервер сверяет путь по номеру и откажет, если список
// успел сдвинуться.
async function removeTrack(li){
  if (!li) return;
  li.classList.add("gone");
  try {
    const j = await (await fetch("/api/remove", {method:"POST",
      body: JSON.stringify({index: +li.dataset.i, path: li.dataset.p})})).json();
    if (!j.ok){ li.classList.remove("gone"); setState("не удалила: " + (j.error || "?"), "failed"); }
    else setState(j.scene ? "убрала из сцены " + j.scene.slice(1) : "убрала из очереди, сцены у неё нет", "saved");
  } catch(e){ li.classList.remove("gone"); setState("ошибка: " + e, "failed"); }
  plDrawn = ""; pollPlaylist();
}
document.addEventListener("keydown", e => {
  if (e.key !== "Delete" || /INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
  const ul = document.getElementById("playlist");
  removeTrack(ul.querySelector("li:hover") || ul.querySelector("li.now"));
});

async function poll(){
  try {
    const d = await (await fetch("/api/now")).json();
    if (!d.running){
      // Перерисовываем только при переходе в это состояние, иначе опрос
      // раз в 700 мс пересоздавал бы кнопку прямо под курсором.
      if (!document.getElementById("launch"))
        document.getElementById("main").innerHTML = '<div class="idle">Winamp не запущен. ' +
          '<button id="launch" class="launch">Запустить Winamp</button></div>';
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
    if (d.running && !d.error) showModes(d);
    // Ползунки не трогаем секунду после того, как их двигали руками,
    // иначе они дёргаются назад на ответе плеера.
    if (d.volume != null && Date.now() - volTouched > 1000){
      volKnown = true;
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

// Селектор сцен: плейлисты медиатеки с точкой в начале имени,
// сгруппированные по локации (".Фандалин - Бой" -> Фандалин / Бой).
let scenes = [], sceneNow = "";
const sceneBox = document.getElementById("scenes"), sceneFind = document.getElementById("scenefind");

async function pollScenes(){
  try {
    const d = await (await fetch("/api/scenes")).json();
    scenes = d.scenes || []; sceneNow = d.current || "";
    document.getElementById("scenename").textContent =
      sceneNow ? sceneNow.slice(1) : (scenes.length ? "свой список" : "нет плейлистов");
    if (sceneBox.classList.contains("open") && !document.activeElement.matches("select.npc")) drawScenes();
  } catch(e){ }
}

function drawScenes(){
  const q = sceneFind.value.trim().toLowerCase();
  const groups = new Map();
  for (const s of scenes){
    if (q && !s.title.toLowerCase().includes(q)) continue;
    if (!groups.has(s.place)) groups.set(s.place, []);
    groups.get(s.place).push(s);
  }
  let html = "", first = true;
  const chip = (s, label) => {
    const cls = "scene" + (s.title === sceneNow ? " now" : "") + (first ? " hot" : "");
    first = false;
    return `<span class="${cls}" data-t="${esc(s.title)}">${esc(label)}<i>${s.songs}</i></span>`;
  };
  for (const [place, list] of groups){
    // Темы НПС собраны в свою подгруппу в конце локации, как группы тегов:
    // в кнопке только имя, приставка «НПС - » ушла в подпись.
    const npc = list.filter(s => s.scene.startsWith("НПС - "));
    html += `<div class="place"><h3>${esc(place)}</h3>`;
    for (const s of list) if (!npc.includes(s)) html += chip(s, s.scene || place);
    if (npc.length){
      // Тема НПС играет одна, поэтому все НПС локации - один выпадающий
      // список размером с кнопку сцены; выбор сразу включает тему.
      const cur = npc.find(s => s.title === sceneNow);
      html += `<select class="npc${cur ? " now" : ""}" title="Тема НПС">` +
        `<option value="" ${cur ? "" : "selected"} disabled>НПС</option>` +
        npc.map(s => `<option value="${esc(s.title)}" ${s === cur ? "selected" : ""}>${esc(s.scene.slice(6))}</option>`).join("") +
        `</select>`;
    }
    html += `</div>`;
  }
  const list = document.getElementById("scenelist");
  list.innerHTML = html || '<div class="idle" style="padding:10px 0">ничего не нашлось</div>';
  list.querySelectorAll(".scene").forEach(el => el.onclick = () => pickScene(el.dataset.t));
  list.querySelectorAll("select.npc").forEach(el => el.onchange = () => el.value && pickScene(el.value));
}

async function pickScene(title){
  closeScenes();
  setState("включаю " + title.slice(1) + "…");
  try {
    const j = await (await fetch("/api/scene", {method:"POST",
      body: JSON.stringify({title})})).json();
    if (j.ok){ setState("играет: " + title.slice(1), "saved"); sceneNow = title;
      document.getElementById("scenename").textContent = title.slice(1); pollPlaylist(); }
    else setState("ошибка: " + j.error, "failed");
  } catch(e){ setState("ошибка: " + e, "failed"); }
}

function openScenes(){
  sceneBox.classList.add("open"); sceneFind.value = ""; drawScenes(); sceneFind.focus();
}
function closeScenes(){ sceneBox.classList.remove("open"); }

document.getElementById("scenebtn").onclick = () =>
  sceneBox.classList.contains("open") ? closeScenes() : openScenes();
sceneFind.addEventListener("input", drawScenes);
sceneFind.addEventListener("keydown", e => {
  if (e.key === "Escape") closeScenes();
  if (e.key === "Enter"){ const hot = document.querySelector("#scenelist .scene.hot");
    if (hot) pickScene(hot.dataset.t); }
});
document.addEventListener("keydown", e => {
  if ((e.key === "p" || e.key === "з") && !e.ctrlKey && !e.altKey &&
      !/INPUT|TEXTAREA/.test(document.activeElement.tagName)){ e.preventDefault(); openScenes(); }
});
document.addEventListener("click", e => {
  if (!e.target.closest("#scenes, #scenebtn")) closeScenes();
});
setInterval(pollScenes, 3000); pollScenes();

document.getElementById("main").addEventListener("click", async e => {
  const b = e.target.closest("#launch");
  if (!b) return;
  b.disabled = true; b.textContent = "Запускаю…";
  try {
    const j = await (await fetch("/api/launch", {method:"POST", body:"{}"})).json();
    if (!j.ok){ b.disabled = false; b.textContent = "Запустить Winamp";
      setState("ошибка: " + j.error, "failed"); }
  } catch(err){ b.disabled = false; b.textContent = "Запустить Winamp";
    setState("ошибка: " + err, "failed"); }
});
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
        # Без этого вкладка приложения после перезапуска сервера показывала
        # старую страницу из кэша.
        self.send_header("Cache-Control", "no-store")
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
        if self.path.startswith("/api/scenes"):
            self._send(200, json.dumps(scenes_state(), ensure_ascii=False))
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
            if self.path.startswith("/api/mode"):
                ok = winamp_now.set_mode(payload.get("shuffle"), payload.get("repeat"))
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
            if self.path.startswith("/api/remove"):
                queue = [i["path"] for i in winamp_now.playlist()]
                ok = winamp_now.remove(payload["index"], payload["path"])
                _playlist_cache["at"] = 0.0
                if not ok:
                    self._send(200, json.dumps({"ok": False, "error": "список изменился, трек не удалён"},
                                               ensure_ascii=False))
                    return
                scene = drop_from_scene(queue, int(payload["index"]), payload["path"])
                self._send(200, json.dumps({"ok": True, "scene": scene}, ensure_ascii=False))
                return
            if self.path.startswith("/api/launch"):
                launch_winamp()
                self._send(200, json.dumps({"ok": True}))
                return
            if self.path.startswith("/api/scene"):
                songs = load_scene(payload["title"])
                self._send(200, json.dumps({"ok": True, "songs": songs}))
                return
            if self.path.startswith("/api/stars"):
                stars = write_stars(payload["path"], int(payload["stars"]))
                _playlist_cache["at"] = 0.0
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
