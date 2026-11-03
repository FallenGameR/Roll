"""Push-to-talk dictation: hold the Copilot key, speak, release - text is typed at the cursor.

Usage: pythonw ptt.py [model] [--log PATH] [--test]
Managed by Start-Dictation / Stop-Dictation / Get-Dictation from the Roll module.
"""
import argparse
import ctypes
import ctypes.wintypes as w
import json
import logging
import os
import queue
import socket
import sys
import threading
import time
import winsound

import keyboard
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

parser = argparse.ArgumentParser()
parser.add_argument("model", nargs="?", default="turbo")
parser.add_argument("--log", default=os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.dirname(os.path.abspath(__file__))),
    "Roll", "dictation", "dictation.log"))
parser.add_argument("--test", action="store_true",
                    help="let simulated key presses drive the hook and log hook events")
args = parser.parse_args()

MODEL = args.model
ACCEPT_INJECTED = args.test
MIN_SECONDS = 0.4
SR = 16000
PROMPT = "Сделай commit и открой pull request в GitHub, потом запусти тесты в PowerShell."

VK_F23 = 0x86  # Copilot key sends Win+Shift+F23
HOTKEYS = {VK_F23}
COPILOT_MODIFIERS = {0x5B, 0x10, 0xA0, 0xA1}  # Win, Shift — repeated by the Copilot key while held
KEYDOWN = {0x100, 0x104}
LLKHF_INJECTED = 0x10

os.makedirs(os.path.dirname(args.log), exist_ok=True)
logging.basicConfig(filename=args.log, level=logging.INFO,
                    format="%(asctime)s %(message)s", encoding="utf-8")
log = logging.getLogger()

_guard = socket.socket()
try:
    _guard.bind(("127.0.0.1", 47811))
except OSError:
    log.info("Another instance holds port 47811, exiting")
    sys.exit("Already running")

log.info("Loading model %s", MODEL)

STATE_PATH = os.path.join(os.path.dirname(args.log), "state.json")
last_run = {}


def set_state(stage, **extra):
    """Текущая стадия для пульта: loading, ready, recording, preparing, decoding, typing.

    Пульт опрашивает файл раз в полсекунду и сам считает секундомер от since.
    Пишем через временный файл и os.replace, иначе пульт может прочитать
    половину JSON.
    """
    data = {"stage": stage, "since": time.time(), "last": last_run}
    data.update(extra)
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass  # пульт - не повод ронять диктовку


set_state("loading", model=MODEL)


def disable_power_throttling():
    # На батарее Windows включает EcoQoS для фоновых процессов без окна, и
    # pythonw распознаёт втрое медленнее. Отказываемся от этого явно.
    class State(ctypes.Structure):
        _fields_ = [("Version", w.ULONG), ("ControlMask", w.ULONG), ("StateMask", w.ULONG)]

    execution_speed = 0x1
    state = State(1, execution_speed, 0)
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = w.HANDLE
    kernel32.SetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel32.SetProcessInformation.restype = w.BOOL
    ok = kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), 4,  # ProcessPowerThrottling
                                        ctypes.byref(state), ctypes.sizeof(state))
    log.info("Power throttling %s", "disabled" if ok else "left as is")


disable_power_throttling()
model = WhisperModel(MODEL, device="cpu", compute_type="int8")
log.info("Ready. Hold the Copilot key to dictate.")
set_state("ready")
winsound.Beep(1200, 80)

commands = queue.Queue()
held = {"key": None, "cancelled": False}


MEDIA = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media")


def chime(name):
    # Windows Speech Recognition sounds; async so recording isn't delayed.
    winsound.PlaySound(os.path.join(MEDIA, name), winsound.SND_FILENAME | winsound.SND_ASYNC)


def recorder():
    while True:
        cmd = commands.get()
        if cmd != "start":
            continue
        chunks = []
        start = time.time()
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                callback=lambda data, *_: chunks.append(data.copy()))
        stream.start()
        log.info("Recording...")
        set_state("recording")
        chime("Speech On.wav")
        while commands.get() != "stop":
            pass
        stream.stop()
        stream.close()
        duration = time.time() - start
        if held["cancelled"] or duration < MIN_SECONDS or not chunks:
            log.info("Skipped (cancelled=%s, %.1fs)", held["cancelled"], duration)
            set_state("ready", skipped="отменено" if held["cancelled"] else "слишком коротко")
            continue
        chime("Speech Off.wav")
        transcribe(np.concatenate(chunks).flatten(), duration)


def transcribe(audio, recorded):
    seconds = len(audio) / SR
    set_state("preparing", audio=round(seconds, 1))
    t = time.time()
    # transcribe() сразу отрезает тишину (VAD) и считает признаки звука, а
    # сами слова декодирует лениво. Поэтому время до возврата - подготовка,
    # а остальное - декодирование. Прогресса внутри декодирования нет:
    # Whisper разбирает звук окнами по 30 с и отдаёт сегменты только после
    # целого окна, а фраза почти всегда укладывается в одно окно.
    segments, info = model.transcribe(audio, language="ru", initial_prompt=PROMPT,
                                      vad_filter=True, beam_size=5)
    prepared = time.time() - t
    speech = getattr(info, "duration_after_vad", seconds) or seconds
    set_state("decoding", audio=round(seconds, 1), speech=round(speech, 1))
    t = time.time()
    text = " ".join(s.text.strip() for s in segments).strip()
    decoded = time.time() - t
    log.info("%.1fs audio -> %.1fs: %s", seconds, prepared + decoded, text)
    typed = 0.0
    if text:
        set_state("typing", chars=len(text))
        t = time.time()
        keyboard.write(text + " ")
        typed = time.time() - t
    last_run.clear()
    last_run.update(at=time.time(), record=round(recorded, 1), prepare=round(prepared, 1),
                    decode=round(decoded, 1), type=round(typed, 1), chars=len(text),
                    speech=round(speech, 1))
    set_state("ready", skipped="" if text else "тишина")


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vk", w.DWORD), ("scan", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("extra", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, w.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT))
user32 = ctypes.windll.user32
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT)]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK


@HOOKPROC
def hook(n, msg, data):
    # Keep this fast: Windows drops slow low-level hooks. Real work happens in the recorder thread.
    if n == 0 and (ACCEPT_INJECTED or not data.contents.flags & LLKHF_INJECTED):
        vk = data.contents.vk
        down = msg in KEYDOWN
        if vk in HOTKEYS:
            if ACCEPT_INJECTED:
                log.info("hook vk=%#x msg=%#x held=%s", vk, msg, held["key"])
            if down and held["key"] is None:
                held.update(key=vk, cancelled=False)
                commands.put("start")
            elif not down and held["key"] == vk:
                held["key"] = None
                commands.put("stop")
            return 1  # swallow so Windows doesn't launch Copilot/Search/Start
        if held["key"] is not None and down and vk not in COPILOT_MODIFIERS:
            held["cancelled"] = True  # hotkey used as part of a shortcut
            if ACCEPT_INJECTED:
                log.info("cancel by vk=%#x scan=%#x flags=%#x", vk, data.contents.scan, data.contents.flags)
    return user32.CallNextHookEx(None, n, msg, data)


threading.Thread(target=recorder, daemon=True).start()
if not user32.SetWindowsHookExW(13, hook, None, 0):
    sys.exit("Failed to install keyboard hook")
msg = w.MSG()
while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    pass
