"""Push-to-talk dictation: hold the Copilot, Menu or right Win key, speak, release - text is typed at the cursor.

Usage: pythonw ptt.py [model] [--log PATH] [--encoder auto|cuda|gpu|npu|off] [--language auto|ru|en] [--test]
Managed by Start-Dictation / Stop-Dictation / Get-Dictation from the Roll module.
"""
import argparse
import ctypes
import ctypes.wintypes as w
import json
import logging
import os
import queue
import re
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
from language import PROMPTS, detect_pair, load_detector, pick_language
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
parser.add_argument("--mic", default="",
                    help="часть имени микрофона, например Blue; пусто или нет такого - "
                         "микрофон Windows по умолчанию")
parser.add_argument("--language", default="auto", choices=["auto", "ru", "en"],
                    help="язык фраз: auto - русский или английский по каждой фразе, "
                         "см. language.py; ru или en - всегда этот")
args = parser.parse_args()

MODEL = args.model
ACCEPT_INJECTED = args.test
MIN_SECONDS = 0.4
SR = 16000

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
_guard.listen(8)


def _answer_knock():
    # Пульт проверяет, жива ли диктовка, стуком в этот порт: раньше он
    # каждые пять секунд запускал pwsh с WMI-запросом по всем процессам.
    while True:
        try:
            _guard.accept()[0].close()
        except OSError:
            return


threading.Thread(target=_answer_knock, daemon=True).start()

log.info("Loading model %s", MODEL)

STATE_PATH = os.path.join(os.path.dirname(args.log), "state.json")
last_run = {}
state = {}
mic = None
# Чем открывать запись: None - микрофон Windows по умолчанию через MME, как
# раньше, иначе номер устройства WASAPI для микрофона, выбранного --mic.
mic_device = None


def refresh_mic():
    """Перечитывает микрофон и, если он сменился, сообщает пульту.

    С --mic берётся первый микрофон, в имени которого есть эта строка, а
    если такого сейчас нет - микрофон Windows по умолчанию.

    PortAudio запоминает список устройств при старте, и без перезапуска
    запись шла бы с прежнего микрофона, даже когда в Windows выбран новый
    или нужный подключили заново. Сама переинициализация стоит около 30 мс,
        но требует закрыть поток микрофона, а закрыть и открыть его - почти
        секунда. Поэтому делается в простое раз в MIC_REFRESH_EVERY секунд, см.
        Mic. Зовётся только из потока записи и до его запуска: PortAudio
    нельзя трогать, пока открыт поток. Имя берётся из WASAPI: MME обрезает
    названия до 31 знака.
    """
    global mic, mic_device
    try:
        sd._terminate()
        sd._initialize()
        wasapi = next((h for h in sd.query_hostapis() if h["name"] == "Windows WASAPI"), None)
        chosen = None
        if args.mic and wasapi:
            chosen = next((i for i in wasapi["devices"]
                           if sd.query_devices(i)["max_input_channels"] > 0
                           and args.mic.lower() in sd.query_devices(i)["name"].lower()), None)
        mic_device = chosen
        if chosen is not None:
            device = chosen
        elif wasapi and wasapi["default_input_device"] >= 0:
            device = wasapi["default_input_device"]
        else:
            device = sd.default.device[0]
        name = sd.query_devices(device)["name"] if device is not None and device >= 0 else ""
    except Exception as exc:  # noqa: BLE001
        log.info("Microphone lookup failed: %s", exc)
        mic_device = None
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
detector = load_detector(args.threads, log) if args.language == "auto" else None
log.info("Ready. Hold the Copilot, Menu or right Win key to dictate (encoder %s, beam %d, threads %s, language %s).",
         encoder, args.beam, args.threads or "default", args.language)
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


# Ползунок в пульте пишет громкость в этот файл; он важнее --chime-volume и
# перечитывается перед каждым звуком, поэтому перезапуск диктовки не нужен.
CHIME_VOLUME_PATH = os.path.join(os.path.dirname(args.log), "chime-volume.txt")
CHIMES = {}
chime_volume = {"value": None, "mtime": None}


def current_chime_volume():
    try:
        mtime = os.path.getmtime(CHIME_VOLUME_PATH)
    except OSError:
        return args.chime_volume
    if mtime != chime_volume["mtime"]:
        try:
            with open(CHIME_VOLUME_PATH, encoding="utf-8") as f:
                chime_volume["value"] = float(f.read().strip())
        except (OSError, ValueError):
            chime_volume["value"] = args.chime_volume
        chime_volume["mtime"] = mtime
    return chime_volume["value"]


def chime(name):
    # Windows Speech Recognition sounds; async so recording isn't delayed.
    volume = max(0.0, min(current_chime_volume(), 1.0))
    if volume <= 0:
        return
    if CHIMES.get(name, (None,))[0] != volume:
        path = quiet_wav(name, volume)
        CHIMES[name] = (volume, path, wav_samples(path))
        log.info("Chime %s at volume %.2f", name, volume)
    _, path, samples = CHIMES[name]
    if samples is None or not speaker.play(samples):
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)


CHIME_RATE = 44100
# Realtek этого ноутбука засыпает через 5 с тишины (D3, ConservationIdleTime
# в PowerSettings драйвера). Поток Speaker стартует за единицы мс, и начало
# звонка могло уходить в просыпающийся ЦАП: звук выходил смазанным. Поэтому
# спящей карте звонок подаётся с тишиной впереди, а бодрой - сразу: 120 мс
# на каждое нажатие заметны. winsound прятал это сам, открывая устройство
# около 400 мс.
CHIME_LEAD_S = 0.12


def wav_samples(path):
    """Стерео float32 для Speaker или None, если файл не 16-битный 44.1 кГц."""
    try:
        with wave.open(path, "rb") as src:
            p = src.getparams()
            frames = src.readframes(p.nframes)
        if p.sampwidth != 2 or p.framerate != CHIME_RATE:
            return None
        a = np.frombuffer(frames, dtype="<i2").reshape(-1, p.nchannels).astype("float32") / 32768
        return np.repeat(a, 2, axis=1) if p.nchannels == 1 else a[:, :2]
    except Exception:  # noqa: BLE001
        return None


class DevicePower:
    """Состояние питания звуковой карты по её имени: D0 бодра, D3 спит.

    Имя берётся из WASAPI («Speakers (Realtek(R) Audio)»), в скобках стоит
    имя устройства класса MEDIA в диспетчере устройств. Запрос состояния
    через SetupAPI стоит микросекунды.
    """

    MEDIA = "{4d36e96c-e325-11ce-bfc1-08002be10318}"
    PROPS = "{a45c254e-df1c-4efd-8020-67d146a850e0}"  # 14 - имя, 32 - питание

    def __init__(self):
        self.hdev = None
        self.info = None

    @staticmethod
    def _guid(text):
        import uuid
        u = uuid.UUID(text)
        g = _GUID()
        g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
        g.Data4[:] = u.bytes[8:]
        return g

    def _prop(self, info, pid):
        key = _DEVPROPKEY(self._guid(self.PROPS), pid)
        kind, need = ctypes.c_ulong(), ctypes.c_ulong()
        buf = (ctypes.c_ubyte * 512)()
        ok = _setupapi.SetupDiGetDevicePropertyW(self.hdev, ctypes.byref(info), ctypes.byref(key),
                                                ctypes.byref(kind), buf, 512, ctypes.byref(need), 0)
        return bytes(buf[:need.value]) if ok else None

    def find(self, wasapi_name):
        self.close()
        m = re.search(r"\((.+)\)\s*$", wasapi_name or "")
        if not m:
            return
        try:
            self.hdev = _setupapi.SetupDiGetClassDevsW(ctypes.byref(self._guid(self.MEDIA)), None, None, 2)
            i = 0
            while True:
                info = _SP_DEVINFO_DATA()
                info.cbSize = ctypes.sizeof(info)
                if not _setupapi.SetupDiEnumDeviceInfo(self.hdev, i, ctypes.byref(info)):
                    break
                name = self._prop(info, 14)
                if name and name.decode("utf-16-le").rstrip("\0") == m.group(1):
                    self.info = info
                    return
                i += 1
        except Exception as exc:  # noqa: BLE001
            log.info("Speaker power state unavailable: %s", exc)
        self.close()

    def state(self):
        """1 - D0, 4 - D3, None - не знаю."""
        if self.info is None:
            return None
        data = self._prop(self.info, 32)
        return int.from_bytes(data[4:8], "little") if data and len(data) >= 8 else None

    def close(self):
        if self.hdev:
            _setupapi.SetupDiDestroyDeviceInfoList(self.hdev)
        self.hdev, self.info = None, None


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("ClassGuid", _GUID), ("DevInst", ctypes.c_ulong),
                ("Reserved", ctypes.c_size_t)]


_setupapi = ctypes.WinDLL("setupapi")
_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong]
_setupapi.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
_setupapi.SetupDiGetDevicePropertyW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]


class Speaker:
    """Динамики для звонков, открытые заранее.

    winsound.PlaySound открывает устройство на каждый звук: на Realtek этого
    ноутбука это около 240 мс плюс 180 мс буфера, и звонок опаздывал почти
    на полсекунды от нажатия. Поток WASAPI с маленьким буфером открыт всё
    время, но не запущен: такой поток не держит устройство и не тратит
    процессор, а запускается за единицы миллисекунд, буфер 20-30 мс. Держать
    его запущенным на тишине нельзя: активный поток не даёт ноутбуку уснуть.
    """

    def __init__(self):
        self.stream = None
        self.data = None
        self.pos = 0
        self.power = DevicePower()

    def _callback(self, out, frames, *_):
        data, n = self.data, 0
        if data is not None:
            n = min(frames, len(data) - self.pos)
            out[:n] = data[self.pos:self.pos + n]
            self.pos += n
        out[n:] = 0
        if data is None or self.pos >= len(data):
            raise sd.CallbackStop

    def open(self):
        if self.stream is not None:
            return
        wasapi = next((h for h in sd.query_hostapis() if h["name"] == "Windows WASAPI"), None)
        if not wasapi or wasapi["default_output_device"] < 0:
            return
        try:
            self.stream = sd.OutputStream(device=wasapi["default_output_device"], samplerate=CHIME_RATE,
                                          channels=2, dtype="float32", latency="low",
                                          extra_settings=sd.WasapiSettings(auto_convert=True),
                                          callback=self._callback)
            self.power.find(sd.query_devices(wasapi["default_output_device"])["name"])
        except Exception as exc:  # noqa: BLE001
            log.info("Speakers not opened, chimes via winsound: %s", exc)

    def play(self, samples):
        if self.stream is None:
            return False
        try:
            state = self.power.state()
            if state is not None and state > 1:
                lead = np.zeros((int(CHIME_RATE * CHIME_LEAD_S), 2), dtype="float32")
                samples = np.concatenate([lead, samples])
                log.info("Speakers asleep (D%d), chime after %d ms of silence", state - 1, CHIME_LEAD_S * 1000)
            self.stream.stop()  # прошлый звонок, если ещё звучит
            self.data, self.pos = samples, 0
            self.stream.start()
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("Chime on speakers failed, winsound instead: %s", exc)
            self.close()
            return False

    def close(self):
        self.power.close()
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.stream = None


speaker = Speaker()


class Mic:
    """Поток микрофона, открытый заранее и запускаемый только на время фразы.

    Открыть поток WASAPI стоит 250-350 мс, закрыть - около 500 мс (замер на
    Intel Smart Sound, ноябрь 2026). Когда поток открывался по нажатию и
    закрывался по отпусканию, на столько же опаздывали и звук начала, и
    распознавание. Теперь по клавишам только start и stop, это единицы мс.
    """

    def __init__(self):
        self.stream = None
        self.chunks = []

    def _callback(self, data, *_):
        self.chunks.append(data.copy())

    def open(self):
        if self.stream is not None:
            return
        # WASAPI в общем режиме не даёт 16 кГц, если микрофон работает на
        # 48 кГц: auto_convert просит Windows пересчитать частоту.
        extra = sd.WasapiSettings(auto_convert=True) if mic_device is not None else None
        try:
            self.stream = sd.InputStream(device=mic_device, samplerate=SR, channels=1, dtype="float32",
                                         extra_settings=extra, callback=self._callback)
        except Exception as exc:  # noqa: BLE001
            log.info("Microphone %s failed, using Windows default: %s", mic, exc)
            self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                         callback=self._callback)

    def close(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.stream = None

    def reopen(self):
        # refresh_mic перезапускает PortAudio, а это можно только без
        # открытых потоков, поэтому заодно переоткрываются и динамики:
        # так подхватываются и сменённые в Windows наушники.
        self.close()
        speaker.close()
        refresh_mic()
        self.open()
        speaker.open()


# Как часто в простое перечитывать микрофон: смена микрофона в Windows
# подхватывается с такой задержкой. Нажатие, пришедшее как раз во время
# перечитывания, подождёт его, это до секунды.
MIC_REFRESH_EVERY = 10


def recorder():
    mic_stream = Mic()
    refreshed = 0.0
    while True:
        try:
            cmd = commands.get(timeout=3)
        except queue.Empty:
            if time.time() - refreshed >= MIC_REFRESH_EVERY or mic_stream.stream is None:
                try:
                    mic_stream.reopen()
                except Exception as exc:  # noqa: BLE001
                    log.info("Microphone not opened: %s", exc)
                refreshed = time.time()
            continue
        if cmd != "start":
            continue
        chunks = mic_stream.chunks = []
        start = time.time()
        try:
            mic_stream.open()
            mic_stream.stream.start()
        except Exception as exc:  # noqa: BLE001
            # Микрофон отключили, пока поток ждал: открываем заново.
            log.info("Microphone stream lost, reopening: %s", exc)
            mic_stream.reopen()
            refreshed = time.time()
            mic_stream.stream.start()
        log.info("Recording...")
        set_state("recording")
        chime("Speech On.wav")
        early = EarlyLanguage(chunks)
        while commands.get() != "stop":
            pass
        try:
            mic_stream.stream.stop()
        except Exception as exc:  # noqa: BLE001
            log.info("Microphone stop failed: %s", exc)
            mic_stream.close()
        early.stop()
        duration = time.time() - start
        if held["cancelled"] or duration < MIN_SECONDS or not chunks:
            log.info("Skipped (cancelled=%s, %.1fs)", held["cancelled"], duration)
            set_state("ready", skipped="отменено" if held["cancelled"] else "слишком коротко")
            continue
        chime("Speech Off.wav")
        audio = np.concatenate(chunks).flatten()
        keep_recording(audio)
        transcribe(audio, duration, early.result())


# Язык фразы выбирается, пока она ещё звучит: tiny на процессоре раз в
# секунду переопределяет его по всему, что уже записано, и при отпускании
# клавиши берётся последний ответ, если он уверенный. Первые секунды часто
# одно "Ну, ..." - по 2.5 с русская фраза выходила английской, по 4.5 с уже
# верно. Неуверенный ответ или фраза короче DETECT_AFTER - язык по всей
# записи после отпускания, это около 0.3 с.
DETECT_AFTER = 2.5
DETECT_EVERY = 1.0
SURE = 0.9


class EarlyLanguage:
    def __init__(self, chunks):
        self.chunks = chunks
        self.done = threading.Event()
        self.found = None
        self.thread = None
        if detector is not None:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def run(self):
        checked = 0
        while not self.done.wait(0.1):
            heard = list(self.chunks)
            size = sum(len(c) for c in heard)
            if size >= DETECT_AFTER * SR and size - checked >= DETECT_EVERY * SR:
                checked = size
                self.found = detect_pair(detector, np.concatenate(heard).flatten(), log)

    def stop(self):
        self.done.set()

    def result(self):
        # Не ждём прогон, который идёт прямо сейчас: последний готовый ответ
        # отстаёт от конца фразы меньше чем на секунду.
        found = self.found
        if found and found[1] >= SURE:
            return found[0]
        return None


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


def recognize(audio, seconds, language=None):
    """Возвращает (подготовка, речь, текст, декодирование).

    transcribe() сразу отрезает тишину (VAD) и считает признаки звука, а
    сами слова декодирует лениво. Поэтому время до возврата - подготовка,
    а остальное - декодирование. Прогресса внутри декодирования нет:
    Whisper разбирает звук окнами по 30 с и отдаёт сегменты только после
    целого окна, а фраза почти всегда укладывается в одно окно.
    """
    t = time.time()
    if args.language != "auto":
        language = args.language
    elif language is None:
        language = pick_language(detector, audio, log)
    segments, info = model.transcribe(audio, language=language, initial_prompt=PROMPTS[language],
                                      vad_filter=True, beam_size=args.beam)
    prepared = time.time() - t
    speech = getattr(info, "duration_after_vad", seconds) or seconds
    set_state("decoding", audio=round(seconds, 1), speech=round(speech, 1))
    t = time.time()
    text = " ".join(s.text.strip() for s in segments).strip()
    return prepared, speech, text, time.time() - t


def transcribe(audio, recorded, language=None):
    global model, encoder
    seconds = len(audio) / SR
    set_state("preparing", audio=round(seconds, 1))
    try:
        prepared, speech, text, decoded = recognize(audio, seconds, language)
    except Exception as exc:  # noqa: BLE001
        if encoder != "CUDA":
            raise
        # Видеопамять может забрать игра или драйвер упасть посреди сессии.
        # Тогда до перезапуска считаем на процессоре, а пульт покажет CPU.
        log.info("CUDA failed, back to CPU until restart: %s", exc)
        model, encoder = load_cpu_model("off")
        prepared, speech, text, decoded = recognize(audio, seconds, language)
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
