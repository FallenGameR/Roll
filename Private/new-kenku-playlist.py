"""Создать плейлисты в Kenku FM из разделов Music файлов кампании.

Kenku FM должен быть запущен с флагом --remote-debugging-port=9222.

Использование:
    python new-kenku-playlist.py <файл.md> [--scene "Фон"] [--background castle]
    python new-kenku-playlist.py <файл.md> --list
"""
import argparse
import json
import os
import re
import sys
import urllib.request

import websocket

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

CDP_URL = "http://127.0.0.1:9222/json/list"
TARGET_TITLE = "Kenku FM Player"
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")
# Ссылка на трек: любая markdown-ссылка на локальный файл в любом месте
# строки - не только маркированный список (структура файлов может меняться).
LINK = re.compile(r"\[(?P<title>[^\]\n]+)\]\((?P<url>file:/{2,3}[^)\s]+)\)")
DEFAULT_SECTION = r"^(music|музыка)$"
# Название локации отделяется от сцены пустой строкой. Работает только
# вместе со стилем white-space: pre-line, который ставит патч из
# Set-KenkuTitleStyle - без него переводы строк схлопнутся в пробел.
SEPARATOR = "\n\n"


def _links(line):
    # Пометка «— цикл» в строке означает, что звук зацикливается: в
    # соундборде такой ставят и забывают, остальные бьют разово.
    loop = bool(re.search(r"—\s*цикл\b", line))
    found = []
    for m in LINK.finditer(line):
        # Хвост после ссылки — место ситуации. Берём цель ссылки, а не
        # её подпись: подпись стоит в косвенном падеже («в псарне»), а
        # цель — это название комнаты с номером, как на карте.
        tail = line[m.end():]
        anchor = re.search(r"\[\[#?([^\]|]+)(?:\|([^\]]*))?\]\]", tail)
        if anchor:
            target = anchor.group(1).strip().split("#")[-1].strip()
            # У комнат заголовок начинается с номера маркера на карте —
            # он и нужен, чтобы кнопку можно было найти по карте. У
            # разделов вроде «Сокровища» или «Arrival» номера нет вовсе,
            # и там осмысленна подпись.
            if re.match(r"\d+[.\-–]", target):
                tail = target
            elif re.fullmatch(r"(?i)arrival|прибытие", target):
                # Подход к локации — это ещё не комната, но на карте у
                # него законное место: маркер с нулём.
                tail = f"0. {(anchor.group(2) or target).strip()}"
            else:
                tail = (anchor.group(2) or target).strip()
        else:
            tail = tail.strip().lstrip("—-").strip()
        # Звёздочка помечает неотслушанный трек, к месту она отношения не имеет.
        tail = tail.replace("*", "").strip()
        found.append((m.group("title").strip(), m.group("url"), loop, tail))
    return found


def shorten(text, limit=22):
    """Укорачивает надпись кнопки до того, что реально видно.

    На кнопке соундборда помещается около двух десятков символов,
    дальше Kenku обрывает строку многоточием — и обрывает грубо, посреди
    слова. Лучше отрезать самой по границе слова, а хвостовой предлог
    («Пещера-близнец с») убрать: он занимает место и ничего не значит.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    words = text.split()
    out = []
    for word in words:
        if out and len(" ".join(out + [word])) > limit:
            break
        out.append(word)
    while len(out) > 1 and len(out[-1]) <= 2:
        out.pop()
    return " ".join(out) if out else text[:limit]


def parse_scenes(markdown_path, section=DEFAULT_SECTION):
    """Разобрать раздел с музыкой: {название сцены: [(заголовок, url), ...]}.

    Раздел ищется по заголовку любого уровня, совпадающему с section.
    Вложенные заголовки становятся сценами; ссылки, лежащие в разделе до
    первого вложенного заголовка, попадают в сцену с пустым именем.

    Если раздела нет (структура файла поменялась), используется запасной
    разбор: берутся все ссылки на файлы во всём документе, сгруппированные
    по ближайшему заголовку сверху.
    """
    pattern = re.compile(section, re.IGNORECASE)
    scenes, fallback = {}, {}
    scene, section_level = None, None
    current_heading = ""

    with open(markdown_path, encoding="utf-8") as handle:
        for line in handle:
            heading = HEADING.match(line.rstrip())
            if heading:
                level = len(heading.group("hashes"))
                text = heading.group("text").strip()
                current_heading = text
                if pattern.match(text):
                    section_level, scene = level, ""
                    scenes.setdefault("", [])
                elif section_level is not None and level <= section_level:
                    section_level, scene = None, None
                elif section_level is not None:
                    scene = text
                    scenes.setdefault(scene, [])
                continue

            found = _links(line)
            if not found:
                continue
            if scene is not None:
                scenes[scene].extend(found)
            fallback.setdefault(current_heading, []).extend(found)

    scenes = {name: items for name, items in scenes.items() if items}
    if scenes:
        return scenes
    return {name: items for name, items in fallback.items() if items}


def evaluate(expression):
    with urllib.request.urlopen(CDP_URL) as response:
        targets = json.load(response)
    target = next((t for t in targets if t["title"] == TARGET_TITLE), None)
    if target is None:
        raise RuntimeError(
            f"окно '{TARGET_TITLE}' не найдено; Kenku FM запущен с "
            "--remote-debugging-port=9222?")
    ws = websocket.create_connection(target["webSocketDebuggerUrl"],
                                     timeout=30, suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True,
                       "awaitPromise": True},
        }))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                break
    finally:
        ws.close()
    if "exceptionDetails" in message.get("result", {}):
        raise RuntimeError(json.dumps(message["result"]["exceptionDetails"],
                                      ensure_ascii=False)[:1500])
    return message["result"]["result"].get("value")


def build_script(playlists, remove_titles=(), boards=(), reload_window=False):
    """playlists: [{'title':..., 'background':..., 'tracks':[(title,url)]}]
    boards: то же самое, но для соундбордов; у трека дополнительно
    'loop' — зациклить ли звук.

    remove_titles удаляются в этой же операции: разнесённые по двум
    вызовам удаление и публикация теряются, потому что между ними Kenku
    успевает перезагрузить окно и сохранить состояние из памяти поверх.

    reload_window перезагружает окно вместо обновления живого состояния.
    Нужно, когда поменялся сам HTML окна (патч оформления): иначе правка
    лежит в файле, а в памяти работает прежняя версия.
    """
    payload = json.dumps(playlists, ensure_ascii=False)
    removals = json.dumps(list(remove_titles), ensure_ascii=False)
    boards_payload = json.dumps(list(boards), ensure_ascii=False)
    return """
(() => {
  const incoming = %s;
  const removals = %s;
  const incomingBoards = %s;
  const raw = localStorage.getItem("persist:player");
  const outer = raw ? JSON.parse(raw) : {};
  const state = outer.playlists
    ? JSON.parse(outer.playlists)
    : { playlists: { byId: {}, allIds: [] }, tracks: {} };
  const boardState = outer.soundboards
    ? JSON.parse(outer.soundboards)
    : { soundboards: { byId: {}, allIds: [] }, sounds: {} };
  // Сопоставление без учёта разделителя между локацией и сценой, чтобы
  // плейлисты, созданные прежним форматом заголовка, обновлялись, а не
  // дублировались.
  const norm = t => t.replace(/[\\u2028\\u2014-]/g, " ")
                     .replace(/\\s+/g, " ").trim().toLowerCase();
  // Одно и то же имя сцены может быть и плейлистом, и соундбордом.
  // Удаляем только то, что не публикуется этой же операцией, иначе
  // переезд сцены из плейлиста в доску снёс бы саму доску.
  const publishedTitles = incoming.map(i => norm(i.title));
  const publishedBoards = incomingBoards.map(i => norm(i.title));
  const dropped = removals.map(norm);
  for (const id of [...state.playlists.allIds]) {
    const playlist = state.playlists.byId[id];
    if (!playlist) continue;
    const title = norm(playlist.title);
    if (!dropped.includes(title) || publishedTitles.includes(title)) continue;
    delete state.playlists.byId[id];
    state.playlists.allIds = state.playlists.allIds.filter(x => x !== id);
  }
  for (const id of [...boardState.soundboards.allIds]) {
    const board = boardState.soundboards.byId[id];
    if (!board) continue;
    const title = norm(board.title);
    if (!dropped.includes(title) || publishedBoards.includes(title)) continue;
    delete boardState.soundboards.byId[id];
    boardState.soundboards.allIds =
      boardState.soundboards.allIds.filter(x => x !== id);
  }
  const report = [];
  const publishedIds = [];
  for (const item of incoming) {
    const existing = state.playlists.allIds
      .find(id => norm(state.playlists.byId[id].title) === norm(item.title));
    const playlistId = existing || crypto.randomUUID();
    const trackIds = [];
    for (const track of item.tracks) {
      let trackId = Object.keys(state.tracks)
        .find(id => state.tracks[id].url === track.url);
      if (!trackId) {
        trackId = crypto.randomUUID();
        state.tracks[trackId] =
          { id: trackId, url: track.url, title: track.title };
      }
      if (!trackIds.includes(trackId)) trackIds.push(trackId);
    }
    state.playlists.byId[playlistId] = {
      id: playlistId,
      title: item.title,
      // Фон не задан — сохраняем тот, что уже стоит у плейлиста: это
      // позволяет перевыгружать локацию целиком, не затирая картинки,
      // подобранные для отдельных сцен.
      background: item.background
        || (existing && state.playlists.byId[playlistId].background)
        || "stars",
      tracks: trackIds
    };
    if (!existing) state.playlists.allIds.push(playlistId);
    publishedIds.push(playlistId);
    report.push({ title: item.title, tracks: trackIds.length,
                  replaced: Boolean(existing) });
  }
  // Плейлисты одной локации идут подряд и в том же порядке, в каком
  // сцены описаны в markdown; сама группа остаётся там, где стояла.
  const others = state.playlists.allIds.filter(id => !publishedIds.includes(id));
  const anchor = Math.min(...publishedIds
    .map(id => state.playlists.allIds.indexOf(id))
    .filter(index => index >= 0));
  const before = state.playlists.allIds
    .slice(0, anchor).filter(id => others.includes(id)).length;
  state.playlists.allIds =
    others.slice(0, before).concat(publishedIds, others.slice(before));

  // Соундборды: та же логика обновления по названию, но звук хранит
  // собственные настройки воспроизведения, и цикличность — часть звука.
  const boardIds = [];
  for (const item of incomingBoards) {
    const existing = boardState.soundboards.allIds
      .find(id => norm(boardState.soundboards.byId[id].title) === norm(item.title));
    const boardId = existing || crypto.randomUUID();
    const soundIds = [];
    for (const sound of item.tracks) {
      let soundId = Object.keys(boardState.sounds)
        .find(id => boardState.sounds[id].url === sound.url);
      if (!soundId) soundId = crypto.randomUUID();
      boardState.sounds[soundId] = {
        id: soundId,
        url: sound.url,
        title: sound.title,
        loop: Boolean(sound.loop),
        volume: 1,
        fadeIn: 100,
        fadeOut: 100
      };
      if (!soundIds.includes(soundId)) soundIds.push(soundId);
    }
    boardState.soundboards.byId[boardId] = {
      id: boardId,
      title: item.title,
      background: item.background
        || (existing && boardState.soundboards.byId[boardId].background)
        || "stars",
      sounds: soundIds
    };
    if (!existing) boardState.soundboards.allIds.push(boardId);
    boardIds.push(boardId);
    report.push({ title: item.title, tracks: soundIds.length,
                  replaced: Boolean(existing), board: true });
  }
  if (boardIds.length) {
    const rest = boardState.soundboards.allIds
      .filter(id => !boardIds.includes(id));
    boardState.soundboards.allIds = rest.concat(boardIds);
  }

  outer.playlists = JSON.stringify(state);
  outer.soundboards = JSON.stringify(boardState);
  localStorage.setItem("persist:player", JSON.stringify(outer));

  // Обновляем живое состояние приложения вместо перезагрузки окна:
  // перезагрузка обрывает воспроизведение, а менять карточки нужно
  // прямо посреди сессии. Store достаём из React-дерева, дальше
  // штатный для redux-persist REHYDRATE перерисовывает интерфейс.
  const findStore = () => {
    const host = document.getElementById("root") || document.body.firstElementChild;
    if (!host) return null;
    const key = Object.keys(host).find(k => k.startsWith("__reactContainer$"));
    if (!key) return null;
    const queue = [host[key]];
    const seen = new Set();
    while (queue.length) {
      const fiber = queue.shift();
      if (!fiber || seen.has(fiber)) continue;
      seen.add(fiber);
      const props = fiber.memoizedProps || fiber.pendingProps;
      if (props && props.store && typeof props.store.dispatch === "function") {
        return props.store;
      }
      if (fiber.child) queue.push(fiber.child);
      if (fiber.sibling) queue.push(fiber.sibling);
      if (fiber.return) queue.push(fiber.return);
    }
    return null;
  };
  const store = findStore();
  if (store && !%s) {
    store.dispatch({
      type: "persist/REHYDRATE",
      key: "player",
      payload: { playlists: state, soundboards: boardState }
    });
  } else {
    setTimeout(() => location.reload(), 300);
  }
  return report;
})()
""" % (payload, removals, boards_payload,
       "true" if reload_window else "false")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown")
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--soundboard", action="append", default=[])
    parser.add_argument("--remove", action="append", default=[])
    parser.add_argument("--remove-title", action="append", default=[])
    parser.add_argument("--background", default=None)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    prefix = args.prefix
    if prefix is None:
        prefix = os.path.splitext(os.path.basename(args.markdown))[0]
    removals = [f"{prefix}{SEPARATOR}{name}" for name in args.remove]
    # Полные названия нужны, когда карточку больше нечем описать через
    # текущий файл: например, markdown переименовали, и старая карточка
    # осталась висеть под прежним именем.
    removals += list(args.remove_title)

    scenes = parse_scenes(args.markdown, args.section)
    if not scenes and not removals:
        print("в файле не найдено ссылок на треки", file=sys.stderr)
        sys.exit(1)
    if args.list:
        for name, items in scenes.items():
            print(f"{name or '(без сцены)'}: {len(items)}")
        return

    wanted = args.scene if (args.scene or args.soundboard or removals) \
        else list(scenes)
    playlists = []
    for name in wanted:
        if name not in scenes:
            print(f"нет сцены: {name}; есть: {', '.join(scenes)}",
                  file=sys.stderr)
            sys.exit(1)
        playlists.append({
            "title": f"{prefix}{SEPARATOR}{name}" if name else prefix,
            "background": args.background,
            # Место ситуации идёт в имя трека: в плейлисте карточки
            # подписаны только названием, и за столом не видно, к чему
            # относится трек. Где места нет (Фон, Бой), имя не трогаем.
            "tracks": [{"title": f"{tail} — {t}" if tail else t, "url": u}
                       for t, u, _loop, tail in scenes[name]],
        })

    # Все точечные звуки локации живут на одной доске: за столом переход
    # между «поставить гул пещеры» и «ударить рыком» не должен требовать
    # смены карточки. Порядок кнопок задаётся здесь: сперва то, что
    # ставят фоном, потом разовое, потом сцены.
    boards = []
    sounds = []
    for name in args.soundboard:
        if name not in scenes:
            print(f"нет сцены: {name}; есть: {', '.join(scenes)}",
                  file=sys.stderr)
            sys.exit(1)
        for title, url, loop, tail in scenes[name]:
            # На кнопке видно около двух десятков символов, поэтому в
            # имени остаётся только то, что отличает её от соседних.
            sound = re.sub(r"^Effect\s*-\s*", "", title).strip()
            if loop:
                # Слово «цикл» уже говорит, что это фоновая петля, —
                # английский префикс файла тут ничего не добавляет.
                rank, label = 0, f"цикл - {sound}"
            elif name == "Эффекты":
                rank, label = 1, f"эффект - {sound}"
            else:
                # Ситуацию Мастер ищет по номеру маркера на карте, а имя
                # трека дальше через дефис: даже обрезанное, оно говорит,
                # что заиграет.
                place = tail or sound
                # Заглавная нужна у названия места, а не у номера маркера.
                place = re.sub(r"^(\d+[.\-–]\s*)?(.)",
                               lambda m: (m.group(1) or "") + m.group(2).upper(),
                               place)
                rank, label = 2, f"{shorten(place)} - {title}"
            sounds.append((rank, {"title": label, "url": url, "loop": loop}))
    if sounds:
        boards.append({
            "title": prefix,
            "background": args.background,
            "tracks": [s for _rank, s in sorted(sounds, key=lambda p: p[0])],
        })

    print(json.dumps(evaluate(build_script(playlists, removals, boards,
                                           args.reload)),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
