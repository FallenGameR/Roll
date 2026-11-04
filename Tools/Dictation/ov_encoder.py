"""Кодировщик Whisper в OpenVINO на встроенной видеокарте или NPU для ptt.py и bench.py.

Whisper состоит из двух половин. Кодировщик перемалывает 30-секундное окно звука,
это тяжёлая матричная работа, и видеокарта делает её в разы быстрее процессора.
Декодер выписывает слова по одному, и его оставляем CTranslate2 на процессоре.
Подменяется только WhisperModel.encode, поэтому VAD, подсказка и beam остаются
прежними.

Замер ноября 2026 на Core Ultra 7, 773 с звука: весь корпус за 58 с вместо 414,
живая фраза 4-21 с распознаётся за 0.4-0.8 с вместо 5-6, WER на FLEURS 2.2%
против 2.6%. Память процесса 2.5 ГБ вместо 1.0. NPU в полтора раза медленнее
видеокарты, а первая сборка на нём идёт около 2.5 минут.

Если OpenVINO не установлен, устройство недоступно или вызов упал, функция
пишет причину в лог и оставляет штатный кодировщик CTranslate2.
"""
import os
import time

import numpy as np

MODEL_REPO = "OpenVINO/whisper-large-v3-turbo-int8-ov"
FILES = ["openvino_encoder_model.*", "config.json"]


def _download():
    from huggingface_hub import snapshot_download
    try:
        # Без сети диктовка тоже должна стартовать: сперва кэш.
        return snapshot_download(MODEL_REPO, allow_patterns=FILES, local_files_only=True)
    except Exception:  # noqa: BLE001
        return snapshot_download(MODEL_REPO, allow_patterns=FILES)


def pick_device(log):
    """Выбор для --encoder auto: gpu, npu или off по железу, без замеров.

    Видеокарта Arc есть в Core Ultra, на ней кодировщик в разы быстрее
    процессора. Старая встроенная графика UHD считает его медленнее
    процессора: на i9-10900K с UHD 630 окно уходит за 7.1 с против 6.1 с у
    CTranslate2 на 10 ядрах, поэтому такая видеокарта не в счёт. Без Arc
    берём NPU, если он есть, иначе процессор.
    """
    try:
        import openvino as ov
        core = ov.Core()
        names = {d: core.get_property(d, "FULL_DEVICE_NAME") for d in core.available_devices}
    except Exception as exc:  # noqa: BLE001
        log.info("Encoder auto: OpenVINO unavailable (%s), using CPU", exc)
        return "off"
    gpus = [n for d, n in names.items() if d.startswith("GPU") and "arc" in n.lower()]
    if gpus:
        choice = "gpu"
    elif any(d.startswith("NPU") for d in names):
        choice = "npu"
    else:
        choice = "off"
    log.info("Encoder auto: %s from %s", choice, "; ".join(f"{d}={n}" for d, n in names.items()))
    return choice


def attach_openvino_encoder(model, device, log, cache_root=None):
    """Возвращает имя устройства, на котором работает кодировщик: GPU, NPU или CPU."""
    if not device or device.lower() == "off":
        return "CPU"
    device = device.upper()
    try:
        import ctranslate2
        import openvino as ov
    except ImportError as exc:
        log.info("OpenVINO encoder off: %s", exc)
        return "CPU"

    cache_root = cache_root or os.path.join(os.environ["LOCALAPPDATA"], "Roll", "dictation", "openvino")
    try:
        t = time.time()
        path = _download()
        core = ov.Core()
        encoder = core.read_model(os.path.join(path, "openvino_encoder_model.xml"))
        encoder.reshape({encoder.inputs[0]: [1, 128, 3000]})
        compiled = core.compile_model(encoder, device, {"CACHE_DIR": os.path.join(cache_root, device)})
        del encoder
        request = compiled.create_infer_request()
        output = compiled.outputs[0]
        log.info("OpenVINO encoder on %s ready in %.1fs", device, time.time() - t)
    except Exception as exc:  # noqa: BLE001 - без ускорения, но работаем
        log.info("OpenVINO encoder on %s failed, using CTranslate2: %s", device, exc)
        return "CPU"

    original = model.encode

    def encode(features):
        try:
            x = features if features.ndim == 3 else np.expand_dims(features, 0)
            hidden = request.infer({0: np.ascontiguousarray(x, dtype=np.float32)})[output]
            return ctranslate2.StorageView.from_array(np.ascontiguousarray(hidden, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            log.info("OpenVINO encode failed, back to CTranslate2 until restart: %s", exc)
            del model.encode  # снова штатный метод класса; ptt.py так и узнаёт об откате
            return original(features)

    model.encode = encode
    return device
