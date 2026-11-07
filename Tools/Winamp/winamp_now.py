"""Спрашивает у Winamp, что он сейчас играет.

Заголовок окна даёт только "717. Gears 5 - Fracture", а нам нужен путь к файлу:
одинаковых названий в библиотеке хватает, и тег надо писать в тот самый mp3.
Путь отдаёт IPC-сообщение, но отдаёт его указателем в собственную память
плеера, поэтому строку приходится вычитывать через ReadProcessMemory.
"""

import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading

WM_USER = 1024
WM_COMMAND = 273
IPC_ISPLAYING = 104          # 1 играет, 3 пауза, 0 стоп
IPC_GETLISTPOS = 125
IPC_GETPLAYLISTFILEW = 214   # указатель на широкую строку в памяти Winamp
# Winamp отдаёт имя в своём единственном буфере, и следующий запрос его
# перезаписывает. Сервер страницы многопоточный: без замка current() из
# соседнего потока вклинивался между запросом и чтением, и в списке на чужом
# месте оказывался играющий трек, а список на странице перерисовывался.
FILENAME_LOCK = threading.Lock()
IPC_GETOUTPUTTIME = 105      # wParam 0 - позиция в мс, 1 - длина в секундах
IPC_JUMPTOTIME = 106         # перемотать на указанную миллисекунду
IPC_SETPLAYLISTPOS = 121
IPC_SETVOLUME = 122          # 0-255, либо -666 чтобы узнать текущую
VOLUME_QUERY = -666          # -1 здесь не запрос, а попытка что-то выставить
IPC_GETLISTLENGTH = 124
IPC_DELETE = 101             # очистить список
IPC_GETWND = 260             # окно плеера по номеру: IPC_GETWND_PE - редактор плейлиста
IPC_GETWND_PE = 1
IPC_PE_DELETEINDEX = 104     # редактору плейлиста: удалить трек; это не IPC_ISPLAYING главного окна
IPC_PLAYFILEW = 1100         # через WM_COPYDATA: добавить файл в конец списка
WM_COPYDATA = 0x004A
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

# Команды главного меню плеера: то же, что кнопки на его панели.
COMMANDS = {
    "prev": 40044,
    "play": 40045,
    "pause": 40046,
    "stop": 40047,
    "next": 40048,
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_ssize_t]


def find_window():
    return user32.FindWindowW("Winamp v1.x", None)


def ipc(hwnd, wparam, command):
    return user32.SendMessageW(hwnd, WM_USER, wparam, command)


def control(name):
    """Нажимает кнопку плеера: prev, play, pause, stop, next."""
    hwnd = find_window()
    if not hwnd or name not in COMMANDS:
        return False
    user32.SendMessageW(hwnd, WM_COMMAND, COMMANDS[name], 0)
    return True


def seek(ms):
    """Перематывает текущий трек на указанную миллисекунду."""
    hwnd = find_window()
    if not hwnd:
        return False
    ipc(hwnd, int(ms), IPC_JUMPTOTIME)
    return True


def volume(level=None):
    """Читает громкость 0-255, а с аргументом ставит её."""
    hwnd = find_window()
    if not hwnd:
        return None
    if level is None:
        return ipc(hwnd, VOLUME_QUERY, IPC_SETVOLUME)
    return ipc(hwnd, max(0, min(255, int(level))), IPC_SETVOLUME)


def jump(index):
    """Переводит плеер на трек с этим номером в плейлисте и играет его."""
    hwnd = find_window()
    if not hwnd:
        return False
    ipc(hwnd, int(index), IPC_SETPLAYLISTPOS)
    user32.SendMessageW(hwnd, WM_COMMAND, COMMANDS["play"], 0)
    return True


def playlist_length():
    """Сколько треков в списке - один дешёвый вызов, без чтения имён."""
    hwnd = find_window()
    return ipc(hwnd, 0, IPC_GETLISTLENGTH) if hwnd else 0


def remove(index, path):
    """Удаляет из списка плеера трек с этим номером, если там всё ещё этот путь.

    Отдельного трека главное окно удалять не умеет, это делает окно редактора
    плейлиста. У него порядок аргументов обратный: код команды идёт в wParam,
    параметр в lParam. Путь сверяем, чтобы при сдвинувшемся списке не удалить
    соседний трек.
    """
    hwnd = find_window()
    if not hwnd:
        return False
    index = int(index)
    if not 0 <= index < ipc(hwnd, 0, IPC_GETLISTLENGTH):
        return False
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    with FILENAME_LOCK:
        pointer = ipc(hwnd, index, IPC_GETPLAYLISTFILEW)
        try:
            actual = read_remote_wstring(pid.value, pointer) if pointer else ""
        except OSError:
            return False
    if actual.lower() != str(path).lower():
        return False
    editor = ipc(hwnd, IPC_GETWND_PE, IPC_GETWND)
    if not editor:
        return False
    playing_index = ipc(hwnd, 0, IPC_GETLISTPOS)
    playing = ipc(hwnd, 0, IPC_ISPLAYING) == 1
    user32.SendMessageW(editor, WM_USER, IPC_PE_DELETEINDEX, index)
    # Удалённый трек Winamp доигрывает, а позиция уже стоит на соседе, и
    # непонятно, что звучит. Поэтому сразу переходим на следующий (после
    # последнего - на первый); на паузе только ставим позицию, не играя.
    if index == playing_index:
        left = ipc(hwnd, 0, IPC_GETLISTLENGTH)
        if left:
            target = index if index < left else 0
            if playing:
                jump(target)
            else:
                ipc(hwnd, target, IPC_SETPLAYLISTPOS)
        else:
            control("stop")
    return True


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wt.DWORD), ("lpData", ctypes.c_void_p)]


def load(paths, play=True):
    """Заменяет список плеера этими файлами и, если надо, играет с первого.

    Список чистит IPC_DELETE, а файлы добавляются по одному через WM_COPYDATA
    с IPC_PLAYFILEW: строка лежит в нашей памяти, и Windows сама копирует её
    плееру. Указатель напрямую, как у чтения, тут не годится.
    """
    hwnd = find_window()
    if not hwnd:
        return False
    # Очистка списка не останавливает уже открытый файл: без стопа Winamp
    # доигрывал трек прежней сцены, хотя в новом списке его нет.
    user32.SendMessageW(hwnd, WM_COMMAND, COMMANDS["stop"], 0)
    ipc(hwnd, 0, IPC_DELETE)
    for path in paths:
        buf = ctypes.create_unicode_buffer(path)
        cds = COPYDATASTRUCT(IPC_PLAYFILEW, ctypes.sizeof(buf),
                             ctypes.cast(buf, ctypes.c_void_p))
        user32.SendMessageW(hwnd, WM_COPYDATA, 0, ctypes.addressof(cds))
    if play and paths:
        ipc(hwnd, 0, IPC_SETPLAYLISTPOS)
        user32.SendMessageW(hwnd, WM_COMMAND, COMMANDS["play"], 0)
    return True


def playlist(limit=5000):
    """Весь список плеера: путь и имя файла по каждому номеру.

    Имена тянутся по одному IPC-вызову на трек, так что список стоит дорого и
    запрашивать его на каждом опросе нельзя - вызывающий кэширует.
    """
    hwnd = find_window()
    if not hwnd:
        return []
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    count = min(ipc(hwnd, 0, IPC_GETLISTLENGTH), limit)

    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
                                  False, pid.value)
    if not handle:
        return []
    try:
        items = []
        buf = ctypes.create_unicode_buffer(1024)
        read = ctypes.c_size_t()
        for index in range(count):
            # Буфер иногда переписывает и сам Winamp, а его замком не
            # остановишь: имя принимаем, только если два чтения подряд совпали.
            path, last = "", None
            for _ in range(4):
                got = ""
                with FILENAME_LOCK:
                    pointer = ipc(hwnd, index, IPC_GETPLAYLISTFILEW)
                    if pointer and kernel32.ReadProcessMemory(
                            handle, ctypes.c_void_p(pointer), buf, 2048, ctypes.byref(read)):
                        got = buf.value
                if got == last:
                    break
                path = last = got
            items.append({"index": index, "path": path,
                          "name": path.rsplit("\\", 1)[-1][:-4] if path else ""})
        return items
    finally:
        kernel32.CloseHandle(handle)


def read_remote_wstring(pid, address, limit=1024):
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        raise OSError(f"OpenProcess не дал доступа к процессу {pid}")
    try:
        buf = ctypes.create_unicode_buffer(limit)
        read = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address),
                                        buf, limit * 2, ctypes.byref(read))
        if not ok:
            raise OSError(f"ReadProcessMemory не смог прочитать {address:#x}")
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def current():
    hwnd = find_window()
    if not hwnd:
        return {"running": False}
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    state = ipc(hwnd, 0, IPC_ISPLAYING)
    pos = ipc(hwnd, 0, IPC_GETLISTPOS)
    path = ""
    with FILENAME_LOCK:
        pointer = ipc(hwnd, pos, IPC_GETPLAYLISTFILEW)
        if pointer:
            try:
                path = read_remote_wstring(pid.value, pointer)
            except OSError as exc:
                return {"running": True, "error": str(exc), "index": pos}

    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    length = ipc(hwnd, 1, IPC_GETOUTPUTTIME)
    elapsed = ipc(hwnd, 0, IPC_GETOUTPUTTIME)
    return {
        "running": True,
        "state": {0: "stopped", 1: "playing", 3: "paused"}.get(state, str(state)),
        "index": pos,
        "path": path,
        # Остановленный плеер отдаёт -1 и 0xFFFFFFFF вместо времени.
        "elapsed_ms": elapsed if 0 <= elapsed < 1 << 31 else 0,
        "length_sec": length if length and length > 0 else 0,
        "window_title": title.value,
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(current(), ensure_ascii=False, indent=1))
