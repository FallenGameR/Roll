"""Язык фразы для ptt.py и bench.py: русский или английский.

Turbo с заданным русским переводит английскую речь на русский, а с
автоопределением сама тратит на выбор языка лишний проход кодировщика:
на NVIDIA T1000 это 2 с на фразу. Поэтому язык выбирает маленькая модель
tiny на процессоре, за 0.3 с, и только из двух языков: среди всех языков
она путает русский с украинским и болгарским. Замер ноября 2026 на пяти
записях: все русские фразы ушли в русский, английская - в английский.

Для каждого языка своя подсказка модели. В русской речи она держит
английские термины латиницей (commit, pull request, GitHub): дальше этот
текст идёт в чат с агентом и в команды. В английской - пишет названия
продуктов как принято.
"""

PROMPTS = {
    "ru": "Сделай commit и открой pull request в GitHub, потом запусти тесты в PowerShell.",
    "en": "Open a pull request in GitHub, then run the tests in PowerShell.",
}
LANGUAGES = tuple(PROMPTS)


def load_detector(threads, log):
    """Модель tiny для выбора языка или None: тогда все фразы идут как русские."""
    try:
        from faster_whisper import WhisperModel
        return WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=threads)
    except Exception as exc:  # noqa: BLE001
        log.info("Language detector unavailable, everything is Russian: %s", exc)
        return None


def pick_language(detector, audio, log):
    """ru или en: какой из двух tiny считает вероятнее."""
    found = detect_pair(detector, audio, log)
    return found[0] if found else "ru"


def detect_pair(detector, audio, log):
    """(язык, уверенность) или None. Уверенность - доля победителя в сумме
    вероятностей ru и en: 0.5 - не знает, 1 - уверена."""
    if detector is None:
        return None
    try:
        _, _, probs = detector.detect_language(audio, vad_filter=True)
    except Exception as exc:  # noqa: BLE001
        log.info("Language detection failed, using Russian: %s", exc)
        return None
    p = dict(probs)
    language = max(LANGUAGES, key=lambda lang: p.get(lang, 0.0))
    pair = p.get("ru", 0.0) + p.get("en", 0.0)
    share = p.get(language, 0.0) / pair if pair else 0.5
    log.info("Language %s %.2f on %.1fs (ru %.2f, en %.2f)",
             language, share, len(audio) / 16000, p.get("ru", 0.0), p.get("en", 0.0))
    return language, share
