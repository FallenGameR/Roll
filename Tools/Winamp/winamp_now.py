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

WM_USER = 1024
WM_COMMAND = 273
IPC_ISPLAYING = 104          # 1 играет, 3 пауза, 0 стоп
IPC_GETLISTPOS = 125
IPC_GETPLAYLISTFILEW = 214   # указатель на широкую строку в памяти Winamp
IPC_GETOUTPUTTIME = 105      # wParam 0 - позиция в мс, 1 - длина в секундах
IPC_JUMPTOTIME = 106         # перемотать на указанную миллисекунду
IPC_SETPLAYLISTPOS = 121
IPC_SETVOLUME = 122          # 0-255, либо -666 чтобы узнать текущую
VOLUME_QUERY = -666          # -1 здесь не запрос, а попытка что-то выставить
IPC_GETLISTLENGTH = 124
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
            pointer = ipc(hwnd, index, IPC_GETPLAYLISTFILEW)
            path = ""
            if pointer and kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(pointer), buf, 2048, ctypes.byref(read)):
                path = buf.value
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
    pointer = ipc(hwnd, pos, IPC_GETPLAYLISTFILEW)
    path = ""
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
