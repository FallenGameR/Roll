"""Find the repeat period of a looped ambience track and cut one cycle out of it.

YouTube "1 hour of music and ambience" uploads are a short source pasted end to
end. Keeping the whole hour in the library is useless: in a playlist it eats the
whole random draw. This tool measures the period of the repeat and cuts a single
cycle, losslessly, keeping ID3 tags and cover art.

    python loop-trim.py report <file-or-folder> [--json out.json]
    python loop-trim.py apply  <file-or-folder> [--min-score 0.40]

Why it does not compare waveforms. These uploads are not a file pasted on
itself: a looping music bed is mixed under a continuous wind or machinery layer
that never repeats, and the mix is resampled on the way out. Sample by sample
the hour correlates with itself at zero on every lag, including the right one.
What does repeat is the spectral shape, so the analysis runs on a coarse
log-band spectrogram.

1. ffmpeg decodes the head of the file to mono 8 kHz (analysis only).
2. A 16-band log spectrogram at 20 frames per second becomes the feature.
3. Autocorrelation of that feature gives the candidate lags. The fundamental
   and its multiples score alike, so the smallest near-top lag wins.
4. Confidence is how far the peak stands out of its own background, in standard
   deviations, plus the same check one period further out. A loop shows a sharp
   peak at L and 2L; a track that merely sounds uniform shows neither.
5. If the file opens with a fade-in, the first cycle is skipped and the second
   one is cut instead.

The cut is `-c copy`, so the audio is not re-encoded; the boundary lands on an
mp3 frame, which is under 27 ms off. Nothing here is played on repeat, it is
played once in a playlist, so that is inaudible and worth far more than sample
accuracy.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

SR = 8000
HOP = 400            # 50 ms feature hop
WIN = 1024
BANDS = 16
ANALYZE_SECONDS = 1500
MIN_PERIOD = 25.0
MAX_PERIOD = 900.0
RATE = SR / HOP      # feature frames per second


def ffmpeg_bin():
    return os.environ.get("FFMPEG", "ffmpeg")


def decode(path, seconds=ANALYZE_SECONDS):
    cmd = [
        ffmpeg_bin(), "-v", "error", "-i", path, "-t", str(seconds),
        "-ac", "1", "-ar", str(SR), "-f", "f32le", "-",
    ]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def duration(path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return float(out.stdout.strip())


def features(x):
    """Log-energy in BANDS logarithmic bands, one column per HOP."""
    n = (len(x) - WIN) // HOP
    if n < 2:
        return np.zeros((BANDS, 0))
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(WIN)[None, :]
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    edges = np.unique(np.geomspace(1, spec.shape[1] - 1, BANDS + 1).astype(int))
    cols = [spec[:, edges[i]:edges[i + 1]].mean(axis=1) for i in range(len(edges) - 1)]
    f = np.log10(np.stack(cols, axis=0) + 1e-10)
    return f - f.mean(axis=1, keepdims=True)


def autocorr_rows(f):
    """Mean normalized autocorrelation over feature rows."""
    m = f.shape[1]
    n = 1 << (2 * m - 1).bit_length()
    spec = np.fft.rfft(f, n, axis=1)
    ac = np.fft.irfft(spec * np.conj(spec), n, axis=1)[:, :m]
    zero = ac[:, :1].copy()
    zero[zero <= 0] = 1.0
    return (ac / zero).mean(axis=0)


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    den = np.sqrt(a.dot(a) * b.dot(b))
    return float(a.dot(b) / den) if den > 0 else 0.0


def segment_score(f, lag_frames):
    """Similarity of one cycle with the next, over the feature rows."""
    a = min(f.shape[1] // 6, int(30 * RATE))
    span = min(int(120 * RATE), f.shape[1] - a - lag_frames)
    if span < int(20 * RATE):
        return 0.0
    left = f[:, a: a + span].ravel()
    right = f[:, a + lag_frames: a + lag_frames + span].ravel()
    return ncc(left, right)


def analyze(path):
    total = duration(path)
    x = decode(path)
    f = features(x)
    if f.shape[1] < MIN_PERIOD * 2 * RATE:
        return {"file": path, "duration": round(total, 2), "period": None,
                "score": 0.0, "reason": "analysis window shorter than two periods"}

    ac = autocorr_rows(f)
    lo = int(MIN_PERIOD * RATE)
    hi = min(int(MAX_PERIOD * RATE), len(ac) // 2)
    if hi <= lo:
        return {"file": path, "duration": round(total, 2), "period": None,
                "score": 0.0, "reason": "analysis window too short"}

    band = ac[lo:hi]
    base = float(np.median(band))
    sd = float(band.std()) or 1e-9
    peak = band.max()
    # The fundamental and its multiples all score near the top; take the first.
    good = np.flatnonzero(band >= peak * 0.9)
    lag = int(good[0] + lo) if len(good) else int(band.argmax() + lo)
    # Sharpen: the true peak is the local maximum next to that coarse hit.
    win = max(2, int(1.5 * RATE))
    left, right = max(lo, lag - win), min(hi, lag + win + 1)
    lag = int(np.argmax(ac[left:right])) + left

    z = (ac[lag] - base) / sd
    harmonic = (ac[2 * lag] - base) / sd if 2 * lag < len(ac) else 0.0
    seg = segment_score(f, lag)
    period = lag / RATE

    # A lag pinned to the edge of the search band means there was no peak to
    # find: the search just returned its own boundary.
    if lag <= lo + int(1.0 * RATE):
        return {"file": path, "duration": round(total, 2), "period": None,
                "score": round(seg, 3), "z": round(float(z), 2),
                "reason": "лаг упёрся в нижнюю границу поиска, пика нет"}

    start = 0.0
    head = min(int(10 * RATE), lag // 2)
    if head > int(2 * RATE) and 2 * lag + head < f.shape[1]:
        first = ncc(f[:, :head].ravel(), f[:, lag: lag + head].ravel())
        second = ncc(f[:, lag: lag + head].ravel(), f[:, 2 * lag: 2 * lag + head].ravel())
        if second - first > 0.15:
            start = period

    return {
        "file": path,
        "duration": round(total, 2),
        "period": round(period, 2),
        "start": round(start, 2),
        "score": round(seg, 3),
        "z": round(float(z), 2),
        "z2": round(float(harmonic), 2),
        "cycles": round(total / period, 2) if period else None,
    }


def cut(path, start, period):
    fd, tmp = tempfile.mkstemp(suffix=".mp3", dir=os.path.dirname(path))
    os.close(fd)
    cmd = [
        ffmpeg_bin(), "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", path,
        "-t", f"{period:.3f}", "-map", "0", "-c", "copy",
        "-id3v2_version", "3", tmp,
    ]
    try:
        subprocess.run(cmd, check=True)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def targets(path):
    if os.path.isfile(path):
        return [path]
    found = []
    for root, _, files in os.walk(path):
        for name in files:
            if name.lower().endswith(".mp3"):
                found.append(os.path.join(root, name))
    return sorted(found)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["report", "apply"])
    ap.add_argument("path")
    ap.add_argument("--json")
    ap.add_argument("--min-score", type=float, default=0.40,
                    help="cycle-to-cycle similarity required to cut")
    ap.add_argument("--min-z", type=float, default=3.5,
                    help="how far the peak must stand out of its background")
    ap.add_argument("--min-duration", type=float, default=600.0,
                    help="leave files shorter than this alone")
    args = ap.parse_args()

    results = []
    for path in targets(args.path):
        try:
            if duration(path) < args.min_duration:
                results.append({"file": path, "period": None,
                                "reason": "shorter than --min-duration"})
                continue
            r = analyze(path)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            r = {"file": path, "period": None, "score": 0.0, "reason": str(exc)}
        ok = (r.get("period") and r.get("score", 0) >= args.min_score
              and r.get("z", 0) >= args.min_z and r.get("z2", 0) >= args.min_z * 0.6)
        r["ok"] = bool(ok)
        if args.mode == "apply" and ok:
            cut(path, r.get("start", 0.0), r["period"])
            r["applied"] = True
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
    if args.mode == "apply":
        skipped = [r for r in results if not r.get("applied")]
        if skipped:
            print(f"# untouched: {len(skipped)} of {len(results)}", file=sys.stderr)


if __name__ == "__main__":
    main()
