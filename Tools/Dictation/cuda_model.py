"""Whisper целиком на видеокарте NVIDIA через CUDA для ptt.py и bench.py.

В отличие от OpenVINO, где на видеокарту уходит только кодировщик, здесь
CTranslate2 сам считает на CUDA и кодировщик, и декодер. Ему нужны
cuBLAS 12 и cuDNN 9: Install-Dictation ставит их в venv колёсами
nvidia-cublas-cu12 и nvidia-cudnn-cu12 из requirements-cuda.txt, когда видит
карту NVIDIA, а DLL оттуда подключает add_cuda_dlls.

Замер ноября 2026 на RTX 4090 и Ryzen 9 7950X3D, фраза 12 с: 0.23 с на CUDA
в float16 против 3.3 с на 16 ядрах процессора, текст совпал. Модель занимает
2.5 ГБ видеопамяти.

float16 быстр только на картах с тензорными ядрами. У NVIDIA T1000 (чип TU117,
как у GTX 16xx, T400, T600) их нет: на пяти записях, 35 с звука, float16 шёл
35.4 с, медленнее процессора i9-10900K (23.4 с), а int8_float16 - 8.5 с при
том же тексте. Поэтому compute_type выбирает cuda_compute_type по имени карты.
"""
import os
import re
import subprocess
import sys

DLL_DIRS = ("cublas", "cudnn", "cuda_nvrtc")


def add_cuda_dlls():
    """Подключает DLL CUDA из колёс nvidia-* в venv. True, если cuBLAS и cuDNN на месте."""
    base = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    found = []
    for sub in DLL_DIRS:
        path = os.path.join(base, sub, "bin")
        if os.path.isdir(path):
            os.add_dll_directory(path)
            # CTranslate2 грузит cuDNN по имени, а cuDNN свои части - через PATH.
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
            found.append(sub)
    return {"cublas", "cudnn"} <= set(found)


def cuda_available(log):
    """Есть ли карта, которую видит CTranslate2, и библиотеки к ней."""
    have_libs = add_cuda_dlls()
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
    except Exception as exc:  # noqa: BLE001
        log.info("CUDA unavailable: %s", exc)
        return False
    # Карту CTranslate2 видит и без cuBLAS и cuDNN. Без них auto молча уходил
    # на процессор, поэтому причина пишется в лог явно.
    if count and not have_libs:
        log.info("CUDA: NVIDIA card found, but no nvidia-cublas-cu12/nvidia-cudnn-cu12 "
                 "in venv - run Install-Dictation and restart dictation")
        return False
    return count > 0


def cuda_compute_type(log):
    """float16 для карт с тензорными ядрами, int8_float16 для остальных."""
    try:
        name = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader", "-i", "0"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    tensor = bool(re.search(r"\bRTX\b|\b(V100|T4|A\d+|H\d+|L\d+)\b", name))
    compute = "float16" if tensor else "int8_float16"
    log.info("CUDA card: %s, compute %s", name or "unknown", compute)
    return compute


def load_cuda_model(name, log):
    """WhisperModel на CUDA или None, если не поднялась; причина - в лог."""
    from faster_whisper import WhisperModel
    if not add_cuda_dlls():
        log.info("CUDA off: no nvidia-cublas-cu12/nvidia-cudnn-cu12 in venv, run Install-Dictation")
        return None
    try:
        model = WhisperModel(name, device="cuda", compute_type=cuda_compute_type(log))
        # Первый прогон ловит нехватку cuDNN и видеопамяти сразу, а не на
        # первой фразе Мастера.
        import numpy as np
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")
        list(segments)
        return model
    except Exception as exc:  # noqa: BLE001
        log.info("CUDA model failed, using CPU: %s", exc)
        return None
