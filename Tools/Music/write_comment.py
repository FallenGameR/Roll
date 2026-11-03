# -*- coding: utf-8 -*-
"""Conservative, compare-and-set comment patcher. No remuxing or tag-wide save.

python write_comment.py --patch-path patch.json --backup-directory backups
Add --apply to write; --report-path requires a new file. Set-TrackText uses
--request-stdin with a UTF-8 JSON configuration so no Unicode travels in argv.
"""

import argparse
import base64
import copy
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import uuid
from contextlib import contextmanager

from mutagen.id3 import ID3


FIELDS = ("Situation", "Description", "Measurement", "Note")
# Evidence - прежнее имя Measurement. Пока библиотека не переписана, такую
# секцию надо узнавать: читать как известную, а при записи Measurement
# менять на месте, не оставляя двух секций с замером.
LEGACY = {"Measurement": "Evidence"}
KNOWN = ("Situation", "Description", "Measurement", "Evidence", "Note", "Source")
PARAGRAPH_SEPARATOR = re.compile(r"(?:\r\n|\r|\n)(?:[ \t]*(?:\r\n|\r|\n))+")
PIPE_SEPARATOR = re.compile(r"[ \t]*\|[ \t]*(?=[^\W\d][\w -]*:)", re.UNICODE)
LABEL = re.compile(r"^([^\W\d][\w -]*):[ \t]*", re.UNICODE)
STRUCTURAL_LABEL = re.compile(r"^\s*(?:Situation|Description|Measurement|Evidence|Note|Source)\s*:",
                              re.IGNORECASE)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def comment_hash(comment):
    return sha256(comment.encode("utf-8"))


def unsync_size(raw):
    if len(raw) != 4 or any(byte & 128 for byte in raw):
        raise ValueError("Invalid sync-safe size")
    return sum(byte << shift for byte, shift in zip(raw, (21, 14, 7, 0)))


def sync_size(size):
    if not 0 <= size < 1 << 28:
        raise ValueError("ID3 tag is too large")
    return bytes((size >> shift) & 127 for shift in (21, 14, 7, 0))


def split_tag(data):
    """Keep raw frames, including unknown ones; never rewrite through ID3.save."""
    if len(data) < 10 or data[:3] != b"ID3" or data[3] not in (3, 4):
        raise ValueError("Only existing ID3v2.3/v2.4 tags are supported")
    if data[4] != 0 or data[5] != 0:
        raise ValueError("Unsupported ID3 revision/flags (extended header, unsync or footer)")
    end = 10 + unsync_size(data[6:10])
    if end > len(data):
        raise ValueError("Truncated ID3 tag")
    frames, pos = [], 10
    while pos < end:
        if data[pos] == 0:
            if any(data[pos:end]):
                raise ValueError("Nonzero data after ID3 padding")
            break
        if pos + 10 > end or not re.fullmatch(rb"[A-Z0-9]{4}", data[pos:pos + 4]):
            raise ValueError("Malformed ID3 frame header")
        size_bytes = data[pos + 4:pos + 8]
        size = unsync_size(size_bytes) if data[3] == 4 else int.from_bytes(size_bytes, "big")
        stop = pos + 10 + size
        if size == 0 or stop > end:
            raise ValueError("Malformed/truncated ID3 frame")
        frames.append(data[pos:stop])
        pos = stop
    return frames, end


def decode_frame(raw, version):
    header = b"ID3" + bytes((version, 0, 0)) + sync_size(len(raw))
    tags = ID3(io.BytesIO(header + raw), translate=False)
    if len(tags) != 1:
        raise ValueError("Comment frame cannot be decoded without loss")
    return next(iter(tags.values()))


def select_comment(frames, version):
    candidates = []
    for index, raw in enumerate(frames):
        if raw[:4] not in (b"TXXX", b"COMM"):
            continue
        frame = decode_frame(raw, version)
        if raw[:4] == b"COMM" or frame.desc.casefold() == "comment":
            candidates.append((index, frame))
    if len(candidates) != 1:
        raise ValueError("Expected exactly one TXXX:comment or COMM; found %d" % len(candidates))
    index, frame = candidates[0]
    if frames[index][8:10] != b"\0\0":
        raise ValueError("Unsupported comment frame flags")
    if len(frame.text) != 1:
        raise ValueError("Multi-value comment is ambiguous")
    if version == 3 and int(frame.encoding) not in (0, 1):
        raise ValueError("Invalid text encoding for ID3v2.3")
    return index, frame


def parse_sections(comment):
    separator = PARAGRAPH_SEPARATOR if PARAGRAPH_SEPARATOR.search(comment) else PIPE_SEPARATOR
    chunks = separator.split(comment)
    separators = [match.group() for match in separator.finditer(comment)]
    if not chunks or not chunks[0].strip():
        raise ValueError("Missing Situation")
    if any("\r" in chunk or "\n" in chunk or "\0" in chunk for chunk in chunks):
        raise ValueError("Malformed paragraph separators or NUL in comment")
    if STRUCTURAL_LABEL.match(chunks[0]):
        raise ValueError("Situation must be the bare first paragraph")
    sections = [{"name": "Situation", "text": chunks[0], "sep": "", "prefix": ""}]
    seen = {"Situation"}
    for sep, chunk in zip(separators, chunks[1:]):
        match = LABEL.match(chunk)
        if not match:
            raise ValueError("Unlabelled or malformed comment section: %r" % chunk[:60])
        name = match.group(1)
        if name in seen or name == "Situation":
            raise ValueError("Duplicate/labelled section: " + name)
        if name not in KNOWN and name.strip().casefold() in {x.casefold() for x in KNOWN}:
            raise ValueError("Malformed known section label: " + name)
        seen.add(name)
        sections.append({"name": name, "text": chunk, "sep": sep, "prefix": match.group()})
    return sections


def patch_comment(comment, fields):
    if not isinstance(fields, dict) or not fields or set(fields) - set(FIELDS):
        raise ValueError("fields must contain only Situation, Description, Measurement, Note")
    sections = parse_sections(comment)
    default_sep = next((section["sep"] for section in sections[1:]), "\n\n")
    for name, value in fields.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(name + " must be a string or null")
        if value is not None and (any(char in value for char in "\0\r\n")
                                  or PIPE_SEPARATOR.search(value)):
            raise ValueError(name + " must be one paragraph without NUL or section injection")
        if name == "Situation" and (value is None or not value.strip()):
            raise ValueError("Situation cannot be cleared")
        if name == "Situation" and STRUCTURAL_LABEL.match(value):
            raise ValueError("Situation cannot start with a section label")
        existing = next((s for s in sections if s["name"] == name), None)
        legacy = next((s for s in sections if s["name"] == LEGACY.get(name)), None)
        if value is None or not value.strip():
            for section in (existing, legacy):
                if section:
                    sections.remove(section)
        elif existing:
            existing["text"] = existing["prefix"] + value
            if legacy:
                sections.remove(legacy)
        elif legacy:
            legacy.update(name=name, prefix=name + ": ", text=name + ": " + value)
        else:
            section = {"name": name, "text": name + ": " + value,
                       "prefix": name + ": ", "sep": default_sep}
            rank = KNOWN.index(name)
            pos = next((i for i, s in enumerate(sections)
                        if s["name"] in KNOWN and KNOWN.index(s["name"]) > rank), len(sections))
            sections.insert(pos, section)
    after = "".join(section["sep"] + section["text"] for section in sections)
    parse_sections(after)
    return after


def serialize_comment(frame, comment, version):
    encoding = int(frame.encoding)
    # Mutagen silently replaces characters for Latin-1. Refuse instead.
    comment.encode({0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[encoding])
    updated = copy.deepcopy(frame)
    updated.text = [comment]
    tags = ID3()
    tags.add(updated)
    stream = io.BytesIO()
    tags.save(stream, v2_version=version, v1=0, padding=lambda _: 0)
    frames, _ = split_tag(stream.getvalue())
    if len(frames) != 1:
        raise ValueError("Serialization did not produce exactly one frame")
    decoded = decode_frame(frames[0], version)
    if (decoded.text != [comment] or decoded.encoding != frame.encoding
            or decoded.desc != frame.desc or getattr(decoded, "lang", None) != getattr(frame, "lang", None)):
        raise ValueError("Serialization changed comment text or frame attributes")
    return frames[0]


@contextmanager
def locked_file(path, apply):
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        access = 0x80000000 | (0x40000000 if apply else 0)
        # Readers may coexist if they allow writes. Competing write/delete
        # handles are excluded for the entire compare, backup and save.
        handle = create(str(path), access, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, (os.O_RDWR if apply else os.O_RDONLY) | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(fd, "r+b" if apply else "rb") as stream:
            yield stream
    else:
        import fcntl
        with open(path, "r+b" if apply else "rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX if apply else fcntl.LOCK_SH)
            yield stream


def trailing_metadata(suffix):
    result = {"suffix_bytes": len(suffix), "suffix_sha256": sha256(suffix)}
    end = len(suffix)
    if len(suffix) >= 128 and suffix[-128:-125] == b"TAG":
        result["id3v1_base64"] = base64.b64encode(suffix[-128:]).decode("ascii")
        end -= 128
    if end >= 32 and suffix[end - 32:end - 24] == b"APETAGEX":
        footer = suffix[end - 32:end]
        size = int.from_bytes(footer[12:16], "little")
        flags = int.from_bytes(footer[20:24], "little")
        start = end - size - (32 if flags & (1 << 31) else 0)
        if start < 0 or size < 32:
            raise ValueError("Malformed trailing APE tag")
        result["ape_base64"] = base64.b64encode(suffix[start:end]).decode("ascii")
    return result


def save_backup(directory, path, original, tag_end, frame):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex
    raw_path, meta_path = directory / (stem + ".id3"), directory / (stem + ".json")
    metadata = {
        "path": str(path), "file_bytes": len(original), "file_sha256": sha256(original),
        "id3_version": [2, original[3], original[4]], "id3_bytes": tag_end,
        "id3_sha256": sha256(original[:tag_end]), "raw_id3_path": str(raw_path),
        "frame_type": frame.FrameID, "encoding": int(frame.encoding),
        "description": frame.desc, "language": getattr(frame, "lang", None),
        "comment_sha256": comment_hash(frame.text[0]), **trailing_metadata(original[tag_end:]),
    }
    for target, data in ((raw_path, original[:tag_end]),
                         (meta_path, json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"))):
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return {"id3": str(raw_path), "metadata": str(meta_path)}


def write_bytes(stream, data):
    stream.seek(0)
    if stream.write(data) != len(data):
        raise OSError("Short write")
    stream.truncate(len(data))
    stream.flush()
    os.fsync(stream.fileno())


def process_record(record, backup_directory, apply=False):
    result = {"path": record.get("path") if isinstance(record, dict) else None,
              "status": "error", "before": None, "after": None, "errors": []}
    try:
        if not isinstance(record, dict) or set(record) != {"path", "expected_comment_sha256", "fields"}:
            raise ValueError("Record requires exactly path, expected_comment_sha256, fields")
        if not isinstance(record["path"], str) or not Path(record["path"]).is_absolute():
            raise ValueError("path must be absolute")
        path = Path(record["path"])
        if path.suffix.lower() != ".mp3":
            raise ValueError("Only .mp3 files are supported")
        expected = record["expected_comment_sha256"]
        if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
            raise ValueError("expected_comment_sha256 must be 64 hex characters")
        with locked_file(path, apply) as stream:
            original = stream.read()
            frames, tag_end = split_tag(original)
            index, frame = select_comment(frames, original[3])
            before = frame.text[0]
            result["before"] = before
            result["before_comment_sha256"] = comment_hash(before)
            if comment_hash(before) != expected.lower():
                raise ValueError("Comment hash conflict; file was not modified")
            after = patch_comment(before, record["fields"])
            result["after"] = after
            result["after_comment_sha256"] = comment_hash(after)
            if after == before:
                result["status"] = "unchanged"
                return result
            updated_frames = list(frames)
            updated_frames[index] = serialize_comment(frame, after, original[3])
            body = b"".join(updated_frames)
            body_size = max(tag_end - 10, len(body))
            if body_size > tag_end - 10:
                body_size = ((body_size + 1023) // 1024) * 1024
            new_tag = original[:6] + sync_size(body_size) + body + b"\0" * (body_size - len(body))
            rewritten = new_tag + original[tag_end:]
            result["suffix_sha256"] = sha256(original[tag_end:])
            if not apply:
                result["status"] = "dry_run"
                return result
            result["backup"] = save_backup(backup_directory, path, original, tag_end, frame)
            stream.seek(0)
            if stream.read() != original:
                raise ValueError("File changed while preparing write; refusing to overwrite")
            try:
                write_bytes(stream, rewritten)
                stream.seek(0)
                verified = stream.read()
                if verified != rewritten:
                    raise OSError("Read-back byte verification failed")
                checked_frames, checked_end = split_tag(verified)
                checked_index, checked = select_comment(checked_frames, verified[3])
                if (checked_index != index or checked.text != [after]
                        or checked_frames != updated_frames or verified[checked_end:] != original[tag_end:]):
                    raise OSError("Frame/audio verification failed")
            except BaseException:
                try:
                    write_bytes(stream, original)
                    stream.seek(0)
                    if stream.read() != original:
                        raise OSError("Rollback verification failed")
                    result["rolled_back"] = True
                except BaseException as rollback_error:
                    result["rolled_back"] = False
                    result["errors"].append("ROLLBACK FAILED: " + str(rollback_error))
                raise
            result["status"] = "applied"
    except Exception as exc:
        result["status"] = "error"
        result["errors"].append(type(exc).__name__ + ": " + str(exc))
    return result


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def run_batch(config):
    with open(config["patch_path"], encoding="utf-8-sig") as stream:
        records = json.load(stream, object_pairs_hook=unique_json_object)
    if not isinstance(records, list) or not records:
        raise ValueError("Patch must be a non-empty JSON array")
    seen = set()
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            key = os.path.normcase(os.path.realpath(record["path"]))
            if key in seen:
                raise ValueError("Duplicate path in batch: " + record["path"])
            seen.add(key)
    results = [process_record(record, config["backup_directory"], config.get("apply", False))
               for record in records]
    return {"ok": all(result["status"] != "error" for result in results),
            "apply": config.get("apply", False), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-stdin", action="store_true")
    parser.add_argument("--patch-path")
    parser.add_argument("--backup-directory")
    parser.add_argument("--report-path")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report_stream = None
    try:
        config = (json.loads(sys.stdin.buffer.read().decode("utf-8"), object_pairs_hook=unique_json_object)
                  if args.request_stdin else vars(args))
        if not isinstance(config.get("apply", False), bool):
            raise ValueError("apply must be a JSON boolean")
        if not config.get("patch_path") or not config.get("backup_directory"):
            raise ValueError("patch_path and backup_directory are required")
        # Reserve the report before any writes; never overwrite a patch or MP3.
        if config.get("report_path"):
            report_stream = open(config["report_path"], "x", encoding="utf-8", newline="\n")
        report = run_batch(config)
    except Exception as exc:
        report = {"ok": False, "results": [], "errors": [type(exc).__name__ + ": " + str(exc)]}
    try:
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if report_stream:
            report_stream.write(text + "\n")
            report_stream.flush()
            os.fsync(report_stream.fileno())
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    finally:
        if report_stream:
            report_stream.close()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
