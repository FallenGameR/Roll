"""Push-to-talk dictation: hold the Copilot, Menu or right Win key, speak, release - text is typed at the cursor.

Usage: pythonw ptt.py [model] [--log PATH] [--encoder auto|cuda|gpu|npu|off] [--test]
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
import wave
import winsound

# pythonw не даёт процессу консоли, и sys.stdout/stderr равны None. Прогресс
# скачивания из huggingface_hub (tqdm) пишет в stderr и падает на первом
# запуске, а OpenVINO из-за этого откатывается на процессор.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

import keyboard
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from cuda_model import load_cuda_model
from ov_encoder import attach_openvino_encoder, pick_device

parser = argparse.ArgumentParser()
parser.add_argument("model", nargs="?", default="turbo")
parser.add_argument("--log", default=os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.dirname(os.path.abspath(__file__))),
    "Roll", "dictation", "dictation.log"))
parser.add_argument("--test", action="store_true",
                    help="let simulated key presses drive the hook and log hook events")
parser.add_argument("--beam", type=int, default=5,
                    help="beam_size: сколько вариантов текста модель держит одновременно. "
                         "1 быстрее всего на 3%%: у turbo время уходит на кодировщик звука")
parser.add_argument("--threads", type=int, default=os.cpu_count() or 0,
                    help="cpu_threads для CTranslate2; по умолчанию все логические ядра, "
                         "Start-Dictation передаёт число физических. Замер bench.py: на 8 "
                         "ядрах все ядра быстрее библиотечных 4 потоков на 6%%, на i9-10900K "
                         "10 потоков быстрее 20 на 20%%")
parser.add_argument("--encoder", default="auto", choices=["auto", "cuda", "gpu", "npu", "off"],
                    help="где считать Whisper: cuda - вся модель на карте NVIDIA, gpu и npu - "
                         "кодировщик в OpenVINO на видеокарте Intel или NPU, off - CTranslate2 "
                         "на процессоре, auto - выбрать по железу, см. pick_device в ov_encoder.py")
parser.add_argument("--chime-volume", type=float, default=0.1,
                    help="громкость звуков начала и конца записи, доля от системных "
                         "Speech On/Off.wav: 1 - как в Windows, 0 - без звука")
args = parser.parse_args()

MODEL = args.model
ACCEPT_INJECTED = args.test
MIN_SECONDS = 0.4
SR = 16000
PROMPT = "Сделай commit и открой pull request в GitHub, потом запусти тесты в PowerShell."

VK_F23 = 0x86  # Copilot key sends Win+Shift+F23
VK_APPS = 0x5D  # Menu key: sits where the Copilot key is on keyboards without one
VK_RWIN = 0x5C  # right Win: on keyboards with neither, Win stays on the left one
HOTKEYS = {VK_F23, VK_APPS, VK_RWIN}
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
state = {}
mic = None


def refresh_mic():
    """Перечитывает микрофон по умолчанию и, если он сменился, сообщает пульту.

    PortAudio запоминает список устройств при старте, и без перезапуска
    запись шла бы с прежнего микрофона, даже когда в Windows выбран новый.
    Переинициализация стоит около 30 мс, поэтому делается перед каждой
    записью и раз в несколько секунд в простое. Зовётся только из потока
    записи и до его запуска: PortAudio нельзя трогать, пока открыт поток.
    Имя берётся из WASAPI: MME обрезает названия до 31 знака.
    """
    global mic
    try:
        sd._terminate()
        sd._initialize()
        device = next((h["default_input_device"] for h in sd.query_hostapis()
                       if h["name"] == "Windows WASAPI" and h["default_input_device"] >= 0),
                      sd.default.device[0])
        name = sd.query_devices(device)["name"] if device is not None and device >= 0 else ""
    except Exception as exc:  # noqa: BLE001
        log.info("Microphone lookup failed: %s", exc)
        name = ""
    if name != mic:
        log.info("Microphone: %s", name or "none")
        mic = name
        if state:
            state["mic"] = name
            write_state(state)


refresh_mic()


def set_state(stage, **extra):
    """Текущая стадия для пульта: loading, ready, recording, preparing, decoding, typing.

    Пульт опрашивает файл раз в полсекунду и сам считает секундомер от since.
    Пишем через временный файл и os.replace, иначе пульт может прочитать
    половину JSON.
    """
    data = {"stage": stage, "since": time.time(), "last": last_run,
            "encoder": globals().get("encoder"), "mic": mic}
    data.update(extra)
    state.clear()
    state.update(data)
    write_state(data)


def write_state(data):
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        return  # пульт - не повод ронять диктовку
    # Пока пульт читает state.json, Windows не даёт его заменить; без повтора
    # стадия застревала до следующей смены, например на "грузит модель".
    for _ in range(20):
        try:
            os.replace(tmp, STATE_PATH)
            return
        except OSError:
            time.sleep(0.02)


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


def load_cpu_model(wanted):
    cpu = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=args.threads)
    return cpu, attach_openvino_encoder(cpu, wanted, log)


disable_power_throttling()
wanted = pick_device(log) if args.encoder == "auto" else args.encoder
model = load_cuda_model(MODEL, log) if wanted == "cuda" else None
if model is not None:
    encoder = "CUDA"
else:
    model, encoder = load_cpu_model("off" if wanted == "cuda" else wanted)
log.info("Ready. Hold the Copilot, Menu or right Win key to dictate (encoder %s, beam %d, threads %s).",
         encoder, args.beam, args.threads or "default")
set_state("ready")
winsound.Beep(1200, 80)

commands = queue.Queue()
held = {"key": None, "cancelled": False}


MEDIA = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media")


def quiet_wav(name, volume):
    # Системные WAV звучат на полной громкости, поэтому сэмплы один раз
    # умножаются на volume, а тихая копия ложится рядом с логом. Из памяти
    # winsound асинхронно играть не умеет, отсюда файлы.
    path = os.path.join(MEDIA, name)
    try:
        with wave.open(path, "rb") as src:
            params = src.getparams()
            frames = src.readframes(params.nframes)
        if params.sampwidth != 2:
            raise ValueError(f"{params.sampwidth * 8}-bit")
        samples = (np.frombuffer(frames, dtype="<i2") * volume).astype("<i2")
        out = os.path.join(os.path.dirname(args.log), "chimes", name)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with wave.open(out, "wb") as dst:
            dst.setparams(params)
            dst.writeframes(samples.tobytes())
        return out
    except Exception as e:
        log.info("Chime %s at full volume: %s", name, e)
        return path


CHIMES = {} if args.chime_volume <= 0 else {
    name: quiet_wav(name, min(args.chime_volume, 1.0)) for name in ("Speech On.wav", "Speech Off.wav")}


def chime(name):
    # Windows Speech Recognition sounds; async so recording isn't delayed.
    if name in CHIMES:
        winsound.PlaySound(CHIMES[name], winsound.SND_FILENAME | winsound.SND_ASYNC)


def recorder():
    while True:
        try:
            cmd = commands.get(timeout=3)
        except queue.Empty:
            refresh_mic()
            continue
        if cmd != "start":
            continue
        refresh_mic()
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
        audio = np.concatenate(chunks).flatten()
        keep_recording(audio)
        transcribe(audio, duration)


RECORDINGS = os.path.join(os.path.dirname(args.log), "recordings")
KEEP_RECORDINGS = 5


def keep_recording(audio):
    """Последние записи - для Tools\\Dictation\\bench.py: сравнивать настройки
    распознавания надо на одном и том же голосе. Старше пятой удаляются."""
    try:
        os.makedirs(RECORDINGS, exist_ok=True)
        name = os.path.join(RECORDINGS, time.strftime("%Y%m%d-%H%M%S") + ".wav")
        with wave.open(name, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        for old in sorted(os.listdir(RECORDINGS))[:-KEEP_RECORDINGS]:
            os.remove(os.path.join(RECORDINGS, old))
    except OSError as exc:
        log.info("Recording not kept: %s", exc)


def recognize(audio, seconds):
    """Возвращает (подготовка, речь, текст, декодирование).

    transcribe() сразу отрезает тишину (VAD) и считает признаки звука, а
    сами слова декодирует лениво. Поэтому время до возврата - подготовка,
    а остальное - декодирование. Прогресса внутри декодирования нет:
    Whisper разбирает звук окнами по 30 с и отдаёт сегменты только после
    целого окна, а фраза почти всегда укладывается в одно окно.
    """
    t = time.time()
    segments, info = model.transcribe(audio, language="ru", initial_prompt=PROMPT,
                                      vad_filter=True, beam_size=args.beam)
    prepared = time.time() - t
    speech = getattr(info, "duration_after_vad", seconds) or seconds
    set_state("decoding", audio=round(seconds, 1), speech=round(speech, 1))
    t = time.time()
    text = " ".join(s.text.strip() for s in segments).strip()
    return prepared, speech, text, time.time() - t


def transcribe(audio, recorded):
    global model, encoder
    seconds = len(audio) / SR
    set_state("preparing", audio=round(seconds, 1))
    try:
        prepared, speech, text, decoded = recognize(audio, seconds)
    except Exception as exc:  # noqa: BLE001
        if encoder != "CUDA":
            raise
        # Видеопамять может забрать игра или драйвер упасть посреди сессии.
        # Тогда до перезапуска считаем на процессоре, а пульт покажет CPU.
        log.info("CUDA failed, back to CPU until restart: %s", exc)
        model, encoder = load_cpu_model("off")
        prepared, speech, text, decoded = recognize(audio, seconds)
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
    if encoder in ("GPU", "NPU") and "encode" not in vars(model):
        encoder = "CPU"  # ov_encoder вернул штатный кодировщик после сбоя, пульт должен это видеть
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
