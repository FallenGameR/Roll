"""Сравнивает настройки распознавания на сохранённых записях диктовки.

Usage (из venv диктовки):
    %LOCALAPPDATA%\\Roll\\dictation\\venv\\Scripts\\python.exe bench.py [--encoders gpu,off] [--beams 5,1] [--threads 0,4,8]

Записи берёт из %LOCALAPPDATA%\\Roll\\dictation\\recordings: ptt.py хранит там
пять последних. Каждая настройка прогоняется на всех записях, первым
проходом модель прогревается и в счёт не идёт. Эталон текста - первая
настройка в списке (по умолчанию кодировщик на видеокарте, beam 5, все ядра,
как в ptt.py), и для остальных печатаются расхождения слово в слово.
"""
import argparse
import difflib
import glob
import itertools
import logging
import os
import time
import wave

import numpy as np
from faster_whisper import WhisperModel

from cuda_model import load_cuda_model
from ov_encoder import attach_openvino_encoder

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="turbo")
ap.add_argument("--encoders", default="gpu,off", help="cuda, gpu, npu, off - как --encoder в ptt.py")
ap.add_argument("--beams", default="5")
ap.add_argument("--threads", default="0")
args = ap.parse_args()

DIR = os.path.join(os.environ["LOCALAPPDATA"], "Roll", "dictation", "recordings")
PROMPT = "Сделай commit и открой pull request в GitHub, потом запусти тесты в PowerShell."


def load(path):
    with wave.open(path) as f:
        return np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768


def disable_power_throttling():
    # Как в ptt.py: без этого Windows считает фоновый процесс без окна
    # кандидатом на EcoQoS, и замер выходит втрое медленнее живой диктовки.
    import ctypes
    import ctypes.wintypes as w

    class State(ctypes.Structure):
        _fields_ = [("Version", w.ULONG), ("ControlMask", w.ULONG), ("StateMask", w.ULONG)]

    state = State(1, 0x1, 0)
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = w.HANDLE
    kernel32.SetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state))


disable_power_throttling()


files = sorted(glob.glob(os.path.join(DIR, "*.wav")))
if not files:
    raise SystemExit(f"Нет записей в {DIR}: надиктуйте пару фраз с запущенной диктовкой.")
audio = [(os.path.basename(f), load(f)) for f in files]
print(f"записей {len(audio)}, звука {sum(len(a) for _, a in audio) / 16000:.1f} с")

log = logging.getLogger("bench")
logging.basicConfig(level=logging.WARNING, format="  %(message)s")
log.setLevel(logging.INFO)
reference = None
for encoder_wanted, threads in itertools.product(args.encoders.split(","),
                                                 [int(t) for t in args.threads.split(",")]):
    model = load_cuda_model(args.model, log) if encoder_wanted == "cuda" else None
    if model is not None:
        encoder = "CUDA"
    else:
        model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=threads)
        encoder = attach_openvino_encoder(model, encoder_wanted, log)
    for beam in [int(b) for b in args.beams.split(",")]:
        def run(a):
            segments, _ = model.transcribe(a, language="ru", initial_prompt=PROMPT,
                                           vad_filter=True, beam_size=beam)
            return " ".join(s.text.strip() for s in segments).strip()

        run(audio[0][1])
        t = time.time()
        texts = [run(a) for _, a in audio]
        took = time.time() - t
        label = f"encoder {encoder}, threads {threads or 'default'}, beam {beam}"
        print(f"\n{label}: {took:.1f} с")
        if reference is None:
            reference = texts
            continue
        for (name, _), ref, got in zip(audio, reference, texts):
            if ref != got:
                diff = [d for d in difflib.ndiff(ref.split(), got.split()) if d[0] in "+-"]
                print(f"  {name}: {' '.join(diff)}")
print("\nэталон:")
for (name, _), text in zip(audio, reference):
    print(f"  {name}: {text}")
