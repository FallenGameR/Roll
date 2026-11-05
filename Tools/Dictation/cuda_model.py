"""Whisper целиком на видеокарте NVIDIA через CUDA для ptt.py и bench.py.

В отличие от OpenVINO, где на видеокарту уходит только кодировщик, здесь
CTranslate2 сам считает на CUDA и кодировщик, и декодер, в float16. Ему нужны
cuBLAS 12 и cuDNN 9: Install-Dictation ставит их в venv колёсами
nvidia-cublas-cu12 и nvidia-cudnn-cu12 из requirements-cuda.txt, когда видит
карту NVIDIA, а DLL оттуда подключает add_cuda_dlls.

Замер ноября 2026 на RTX 4090 и Ryzen 9 7950X3D, фраза 12 с: 0.23 с на CUDA
против 3.3 с на 16 ядрах процессора, текст совпал. Модель занимает 2.5 ГБ
видеопамяти.
"""
import os
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
    if not add_cuda_dlls():
        return False
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
    except Exception as exc:  # noqa: BLE001
        log.info("CUDA unavailable: %s", exc)
        return False
    return count > 0


def load_cuda_model(name, log):
    """WhisperModel на CUDA или None, если не поднялась; причина - в лог."""
    from faster_whisper import WhisperModel
    if not add_cuda_dlls():
        log.info("CUDA off: no nvidia-cublas-cu12/nvidia-cudnn-cu12 in venv, run Install-Dictation")
        return None
    try:
        model = WhisperModel(name, device="cuda", compute_type="float16")
        # Первый прогон ловит нехватку cuDNN и видеопамяти сразу, а не на
        # первой фразе Мастера.
        import numpy as np
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")
        list(segments)
        return model
    except Exception as exc:  # noqa: BLE001
        log.info("CUDA model failed, using CPU: %s", exc)
        return None
