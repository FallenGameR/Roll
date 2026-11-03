# -*- coding: utf-8 -*-
"""Run with unittest; ROLL_WRITER_TEST_DIRECTORY selects retained test artifacts.

Set ROLL_WRITER_ACTIVE_MP3 to an active track for the real-MP3 copy test.
Original source files are only read, and their full hashes are checked.
Without an artifact override, create a project-local TemporaryDirectory for each
test and clean it automatically. No artifacts are retained in the caller's cwd.
"""

import importlib.util
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

from mutagen.id3 import APIC, COMM, ID3, POPM, TCON, TIT2, TXXX


WRITER_PATH = Path(__file__).resolve().with_name("write_comment.py")
SPEC = importlib.util.spec_from_file_location("write_comment", WRITER_PATH)
writer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(writer)
ROOT = (Path(os.environ["ROLL_WRITER_TEST_DIRECTORY"]).resolve()
        if "ROLL_WRITER_TEST_DIRECTORY" in os.environ else None)
COMMENT = ("A quiet road\n\nDescription: Soft strings\n\nMeasurement: Measured\n\n"
           "Note: Uncertain\n\nSource: https://example.invalid/watch?v=abc")


class WriterTests(unittest.TestCase):
    def setUp(self):
        if ROOT is not None:
            self.directory = ROOT / (self._testMethodName + "-" + uuid.uuid4().hex[:8])
            self.directory.mkdir(parents=True)
        else:
            directory = tempfile.TemporaryDirectory(prefix="writer-test-", dir=WRITER_PATH.parent)
            self.addCleanup(directory.cleanup)
            self.directory = Path(directory.name).resolve()
        self.backups = self.directory / "backups"
        self.path = self.directory / "Музыка Przybyłowicz.mp3"

    def fixture(self, version=4, frame_type="TXXX", encoding=None, comment=COMMENT, padding=2048):
        if encoding is None:
            encoding = 1 if version == 3 else 3
        self.path.write_bytes(b"\xff\xfb\x90\x64" + bytes(range(256)) * 30)
        tags = ID3()
        tags.add(TIT2(encoding=1, text=["Unchanged title"]))
        tags.add(TCON(encoding=1, text=["Intensity:Background Emotion:Haven"]))
        tags.add(POPM(email="player@example.invalid", rating=196, count=19))
        tags.add(APIC(encoding=1, mime="image/png", type=3, desc="cover", data=b"\x89PNG\r\n" * 100))
        tags.add(TXXX(encoding=1, desc="unrelated annotation", text=["Keep me"]))
        if frame_type == "TXXX":
            tags.add(TXXX(encoding=encoding, desc="comment", text=[comment]))
        else:
            tags.add(COMM(encoding=encoding, lang="rus", desc="library note", text=[comment]))
        tags.save(self.path, v2_version=version, v1=0, padding=lambda _: padding)
        with self.path.open("ab") as stream:
            stream.write(b"TAG" + b"original trailing ID3v1".ljust(125, b"\0"))
        return self.path.read_bytes()

    def record(self, fields=None, path=None, expected=None):
        path = path or self.path
        data = path.read_bytes()
        frames, _ = writer.split_tag(data)
        _, frame = writer.select_comment(frames, data[3])
        return {"path": str(path), "expected_comment_sha256": expected or writer.comment_hash(frame.text[0]),
                "fields": fields if fields is not None else {"Situation": "Тихая дорога"}}

    def run_record(self, record=None, apply=True):
        return writer.process_record(record or self.record(), self.backups, apply)

    def assert_preserved(self, original, result):
        self.assertEqual("applied", result["status"], result)
        changed = self.path.read_bytes()
        old_frames, old_end = writer.split_tag(original)
        new_frames, new_end = writer.split_tag(changed)
        old_index, old_frame = writer.select_comment(old_frames, original[3])
        new_index, new_frame = writer.select_comment(new_frames, changed[3])
        self.assertEqual(old_index, new_index)
        self.assertEqual(original[:6], changed[:6])
        self.assertEqual(old_frames[:old_index] + old_frames[old_index + 1:],
                         new_frames[:new_index] + new_frames[new_index + 1:])
        self.assertEqual(writer.sha256(original[old_end:]), writer.sha256(changed[new_end:]))
        self.assertEqual(old_frame.encoding, new_frame.encoding)
        self.assertEqual(old_frame.desc, new_frame.desc)
        self.assertEqual(getattr(old_frame, "lang", None), getattr(new_frame, "lang", None))
        self.assertEqual(result["after"], new_frame.text[0])
        self.assertEqual(original[:old_end], Path(result["backup"]["id3"]).read_bytes())
        metadata = json.loads(Path(result["backup"]["metadata"]).read_text(encoding="utf-8"))
        self.assertEqual(writer.sha256(original), metadata["file_sha256"])
        self.assertEqual([2, original[3], 0], metadata["id3_version"])
        self.assertEqual(writer.sha256(original[old_end:]), metadata["suffix_sha256"])

    def test_versions_frame_types_encodings_unicode_and_growth(self):
        for version, kind, encoding in ((3, "TXXX", 1), (3, "COMM", 1),
                                        (4, "TXXX", 3), (4, "COMM", 1), (4, "COMM", 2)):
            with self.subTest(version=version, frame=kind, encoding=encoding):
                original = self.fixture(version, kind, encoding, padding=0)
                result = self.run_record(self.record({"Situation": "Дорога в лесу",
                                                      "Description": "Струнные и флейта. " * 200}))
                self.assert_preserved(original, result)
                self.assertIn("Source: https://example.invalid/watch?v=abc", result["after"])

    def test_omitted_fields_and_unknown_section_exactly_preserved(self):
        comment = COMMENT.replace("\n\nMeasurement:", "\n\nProvenance:   keep RAW  \n\nMeasurement:")
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Situation": "Лесная дорога"}))
        self.assert_preserved(original, result)
        self.assertEqual(comment[comment.index("\n\n"):], result["after"][result["after"].index("\n\n"):])

    def test_null_empty_clear_optional_source_remains(self):
        original = self.fixture()
        result = self.run_record(self.record({"Note": None, "Measurement": "", "Description": ""}))
        self.assert_preserved(original, result)
        self.assertEqual("A quiet road\n\nSource: https://example.invalid/watch?v=abc", result["after"])

    def test_flat_comment_and_insert_missing_sections(self):
        comment = "Road | Source: https://example.invalid | Custom: KEEP"
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Description": "Струнные", "Measurement": "Замер", "Note": "Оговорка"}))
        self.assert_preserved(original, result)
        self.assertEqual("Road | Description: Струнные | Measurement: Замер | Note: Оговорка"
                         " | Source: https://example.invalid | Custom: KEEP", result["after"])

    def test_crlf_separator_is_preserved(self):
        original = self.fixture(comment=COMMENT.replace("\n", "\r\n"))
        result = self.run_record()
        self.assert_preserved(original, result)
        self.assertIn("\r\n\r\nDescription:", result["after"])

    def test_dry_run_is_default_and_no_backup(self):
        original = self.fixture()
        result = writer.process_record(self.record(), self.backups)
        self.assertEqual("dry_run", result["status"])
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse(self.backups.exists())

    def test_noop_creates_no_backup(self):
        original = self.fixture()
        result = self.run_record(self.record({"Situation": "A quiet road"}))
        self.assertEqual("unchanged", result["status"])
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse(self.backups.exists())

    def test_conflict_preserves_entire_file(self):
        original = self.fixture()
        result = self.run_record(self.record(expected="0" * 64))
        self.assertEqual("error", result["status"])
        self.assertIn("hash conflict", result["errors"][0])
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse(self.backups.exists())

    def test_concurrent_genre_rating_update_before_open_is_retained(self):
        self.fixture()
        record = self.record()
        tags = ID3(self.path)
        tags.setall("TCON", [TCON(encoding=1, text=["Game:Fantasy"])])
        tags.setall("POPM", [POPM(email="new", rating=255, count=1)])
        tags.save(self.path, v2_version=4, v1=0)
        original = self.path.read_bytes()
        result = self.run_record(record)
        self.assert_preserved(original, result)
        self.assertEqual(["Game:Fantasy"], ID3(self.path)["TCON"].text)
        self.assertEqual(255, ID3(self.path).getall("POPM")[0].rating)

    def test_ambiguous_and_missing_comment_frames(self):
        for mode in ("both", "two_comm", "duplicate_txxx", "missing"):
            with self.subTest(mode=mode):
                self.fixture()
                tags = ID3(self.path)
                record = self.record()
                if mode == "both":
                    tags.add(COMM(encoding=3, lang="eng", desc="", text=[COMMENT]))
                elif mode == "two_comm":
                    tags.delall("TXXX:comment")
                    tags.add(COMM(encoding=3, lang="eng", desc="one", text=[COMMENT]))
                    tags.add(COMM(encoding=3, lang="rus", desc="two", text=[COMMENT]))
                elif mode == "missing":
                    tags.delall("TXXX:comment")
                tags.save(self.path, v2_version=4, v1=0)
                if mode == "duplicate_txxx":
                    data = self.path.read_bytes()
                    frames, end = writer.split_tag(data)
                    index, _ = writer.select_comment(frames, data[3])
                    body = b"".join(frames) + frames[index]
                    self.path.write_bytes(data[:6] + writer.sync_size(len(body)) + body + data[end:])
                original = self.path.read_bytes()
                result = self.run_record(record)
                self.assertEqual("error", result["status"], result)
                self.assertEqual(original, self.path.read_bytes())

    def test_malformed_unknown_duplicate_sections_refused(self):
        for comment in ("Road\n\nDescription: music\n\nunlabelled unknown data",
                        "Road | Description: a | Description: b",
                        "Road | Description : bad label",
                        "Road\nSource: must not disappear", "source : must not disappear",
                        " Source: must not disappear", "Road\rDescription: bad separator"):
            with self.subTest(comment=comment):
                original = self.fixture(comment=comment)
                result = self.run_record()
                self.assertEqual("error", result["status"])
                self.assertEqual(original, self.path.read_bytes())

    def test_literal_pipe_in_paragraph_comment_original_and_replacement(self):
        values = (
            "YT: «Deep and Powerful Earthquake Noise | Earth Rumble Sound Effect»",
            "YT: RPG | D&D Ambience - Windmill in the Countryside",
            "Огонь | вода",
        )
        for measurement in values:
            with self.subTest(measurement=measurement):
                comment = ("Road\n\nDescription: Strings\n\nMeasurement: " + measurement
                           + "\n\nSource: https://example.invalid")
                original = self.fixture(comment=comment)
                result = self.run_record(self.record({"Situation": "Лесная дорога"}))
                self.assert_preserved(original, result)
                self.assertIn("\n\nMeasurement: " + measurement, result["after"])
                original = self.fixture()
                result = self.run_record(self.record({"Measurement": measurement}))
                self.assert_preserved(original, result)
                self.assertIn("\n\nMeasurement: " + measurement, result["after"])

    def test_flat_comment_splits_only_labelled_pipe_boundaries(self):
        comment = ("Road | open sky | Description: Strings | Measurement: YT: RPG | D&D Ambience"
                   " | Custom: preserve | plain text | Source: https://example.invalid")
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Measurement": "YT: Земля | Гул землетрясения"}))
        self.assert_preserved(original, result)
        self.assertEqual("Road | open sky | Description: Strings"
                         " | Measurement: YT: Земля | Гул землетрясения"
                         " | Custom: preserve | plain text | Source: https://example.invalid",
                         result["after"])

    def test_paragraph_comments_do_not_split_any_embedded_pipes(self):
        comment = ("Road\n\nDescription: Strings\n\nMeasurement: A title | Note: a subtitle"
                   "\n\nSource: https://example.invalid")
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Situation": "Лесная дорога"}))
        self.assert_preserved(original, result)
        self.assertIn("Measurement: A title | Note: a subtitle", result["after"])

    def test_legacy_evidence_replaced_in_place_by_measurement(self):
        comment = COMMENT.replace("Measurement: Measured", "Evidence: YT: old words")
        for separator in ("\n\n", " | "):
            with self.subTest(separator=separator):
                original = self.fixture(comment=comment.replace("\n\n", separator))
                result = self.run_record(self.record({"Measurement": "Замер: 120 с"}))
                self.assert_preserved(original, result)
                self.assertEqual(separator.join((
                    "A quiet road", "Description: Soft strings", "Measurement: Замер: 120 с",
                    "Note: Uncertain", "Source: https://example.invalid/watch?v=abc")),
                    result["after"])

    def test_legacy_evidence_cleared_by_empty_measurement(self):
        comment = COMMENT.replace("Measurement: Measured", "Evidence: YT: old words")
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Measurement": ""}))
        self.assert_preserved(original, result)
        self.assertNotIn("Evidence", result["after"])
        self.assertEqual("A quiet road\n\nDescription: Soft strings\n\nNote: Uncertain"
                         "\n\nSource: https://example.invalid/watch?v=abc", result["after"])

    def test_legacy_evidence_dropped_when_measurement_already_present(self):
        comment = COMMENT.replace("\n\nNote:", "\n\nEvidence: YT: old words\n\nNote:")
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Measurement": "Новый замер"}))
        self.assert_preserved(original, result)
        self.assertNotIn("Evidence", result["after"])
        self.assertIn("\n\nMeasurement: Новый замер\n\nNote:", result["after"])

    def test_legacy_evidence_untouched_by_other_fields_and_not_writable(self):
        comment = COMMENT.replace("Measurement: Measured", "Evidence: YT: old words")
        original = self.fixture(comment=comment)
        result = self.run_record(self.record({"Description": "Струнные"}))
        self.assert_preserved(original, result)
        self.assertIn("\n\nEvidence: YT: old words\n\n", result["after"])
        result = self.run_record(self.record({"Evidence": "x"}))
        self.assertEqual("error", result["status"], result)

    def test_pipe_section_injection_remains_refused(self):
        for value in ("Title | Source: replaced", "Title | Unknown: injected",
                      "Title | Description : malformed", "Title | note: injected"):
            with self.subTest(value=value):
                original = self.fixture()
                result = self.run_record(self.record({"Measurement": value}))
                self.assertEqual("error", result["status"], result)
                self.assertEqual(original, self.path.read_bytes())

    def test_natural_situation_colons_in_original_and_patch(self):
        situations = (
            "Над отрядом пролетает дракон: слышны рёв и хлопки крыльев.",
            "За дверью рычит запертая тварь: совомедведь или медведь.",
            "Сцена: отряд идёт по лесу.",
            "A dragon flies overhead: wingbeats and roaring.",
        )
        for situation in situations:
            with self.subTest(situation=situation):
                original = self.fixture(comment=situation + "\n\nDescription: Soft strings"
                                        "\n\nSource: https://example.invalid")
                result = self.run_record(self.record({"Note": "Сведения проверены."}))
                self.assert_preserved(original, result)
                self.assertTrue(result["after"].startswith(situation + "\n\n"))
                original = self.fixture()
                result = self.run_record(self.record({"Situation": situation}))
                self.assert_preserved(original, result)
                self.assertTrue(result["after"].startswith(situation + "\n\n"))

    def test_known_situation_labels_rejected_case_and_spacing_variants(self):
        for label in writer.KNOWN:
            for prefix in (label + ": ", "  " + label.lower() + " : ", label.upper() + "\t: "):
                with self.subTest(prefix=prefix):
                    situation = prefix + "must not be interpreted as Situation"
                    original = self.fixture(comment=situation + "\n\nDescription: Strings")
                    result = self.run_record(self.record({"Note": "Checked"}))
                    self.assertEqual("error", result["status"], result)
                    self.assertEqual(original, self.path.read_bytes())
                    original = self.fixture()
                    result = self.run_record(self.record({"Situation": situation}))
                    self.assertEqual("error", result["status"], result)
                    self.assertEqual(original, self.path.read_bytes())

    def test_unknown_raw_frames_and_ape_tag_preserved(self):
        self.fixture()
        data = self.path.read_bytes()
        frames, end = writer.split_tag(data)
        unknown = b"XABC" + writer.sync_size(7) + b"\0\0" + b"opaque!"
        body = b"".join(frames) + unknown
        footer = (b"APETAGEX" + (2000).to_bytes(4, "little")
                  + (32).to_bytes(4, "little") + b"\0" * 16)
        self.path.write_bytes(data[:6] + writer.sync_size(len(body)) + body
                              + data[end:-128] + footer + data[-128:])
        original = self.path.read_bytes()
        result = self.run_record()
        self.assert_preserved(original, result)
        metadata = json.loads(Path(result["backup"]["metadata"]).read_text(encoding="utf-8"))
        self.assertEqual(footer, writer.base64.b64decode(metadata["ape_base64"]))
        self.assertEqual(original[-128:], writer.base64.b64decode(metadata["id3v1_base64"]))

    def test_mixed_batch_reports_each_failure_without_false_success(self):
        original = self.fixture()
        record = self.record()
        bad = {"path": str(self.directory / "missing.mp3"),
               "expected_comment_sha256": "0" * 64, "fields": {"Situation": "Road"}}
        patch = self.write_patch([bad, record])
        process, report = self.cli(patch, apply=True)
        self.assertEqual(1, process.returncode)
        self.assertFalse(report["ok"])
        self.assertEqual(["error", "applied"], [item["status"] for item in report["results"]])
        self.assert_preserved(original, report["results"][1])

    def test_missing_malformed_and_non_mp3_files_refused(self):
        for raw in (b"no ID3", b"ID3\x02\0\0\0\0\0\0", b"ID3\x04\0\0\0\0\1\0"):
            self.path.write_bytes(raw)
            result = self.run_record({"path": str(self.path), "expected_comment_sha256": "0" * 64,
                                      "fields": {"Situation": "Road"}})
            self.assertEqual("error", result["status"])
            self.assertEqual(raw, self.path.read_bytes())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell integration requires pwsh")
    def test_powershell_wrapper_unicode_dry_apply_and_throw(self):
        original = self.fixture()
        patch = self.write_patch([self.record()])
        command_path = WRITER_PATH.parents[2] / "Public" / "Music" / "Set-TrackText.ps1"
        script = (
            ". $env:ROLL_TEXT_COMMAND; "
            "$r = @(Set-TrackText -PatchPath $env:ROLL_TEXT_PATCH "
            "-BackupDirectory $env:ROLL_TEXT_BACKUP); "
            "if ($r.Count -ne 1 -or $r[0].status -ne 'dry_run') {throw 'Dry run failed'}; "
            "$r = @(Set-TrackText -PatchPath $env:ROLL_TEXT_PATCH "
            "-BackupDirectory $env:ROLL_TEXT_BACKUP -Apply -ReportPath $env:ROLL_TEXT_REPORT); "
            "if ($r[0].status -ne 'applied') {throw 'Apply failed'}; "
            "$caught = $false; try {Set-TrackText -PatchPath $env:ROLL_TEXT_PATCH "
            "-BackupDirectory $env:ROLL_TEXT_BACKUP -Apply | Out-Null} catch {$caught = $true}; "
            "if (-not $caught) {throw 'Expected conflict exception'}"
        )
        report_path = self.directory / "результат.json"
        env = {**os.environ, "ROLL_TEXT_COMMAND": str(command_path),
               "ROLL_TEXT_PATCH": str(patch), "ROLL_TEXT_BACKUP": str(self.backups),
               "ROLL_TEXT_REPORT": str(report_path)}
        process = subprocess.run(["pwsh", "-NoProfile", "-Command", script],
                                 capture_output=True, env=env)
        self.assertEqual(0, process.returncode, process.stderr.decode("utf-8", errors="replace"))
        result = json.loads(report_path.read_text(encoding="utf-8"))["results"][0]
        self.assert_preserved(original, result)

    def test_source_and_invalid_fields_cannot_be_written(self):
        for fields in ({"Source": "evil"}, {"Situation": ""}, {"Situation": None},
                       {"Description": 3}, {"Note": "x | Source: evil"},
                       {"Note": "x\n\nSource: evil"}, {"Note": "x\0evil"},
                       {"Situation": "Description: ambiguous"}, {}):
            with self.subTest(fields=fields):
                original = self.fixture()
                result = self.run_record(self.record(fields))
                self.assertEqual("error", result["status"], result)
                self.assertEqual(original, self.path.read_bytes())

    def test_latin1_encoding_is_preserved_or_refused(self):
        original = self.fixture(version=3, encoding=0)
        result = self.run_record(self.record({"Situation": "Another road"}))
        self.assert_preserved(original, result)
        original = self.path.read_bytes()
        result = self.run_record()
        self.assertEqual("error", result["status"])
        self.assertEqual(original, self.path.read_bytes())

    def test_multi_value_comment_refused(self):
        self.fixture()
        tags = ID3(self.path)
        tags["TXXX:comment"].text = [COMMENT, "A second comment"]
        tags.save(self.path, v2_version=4)
        original = self.path.read_bytes()
        result = self.run_record({"path": str(self.path), "expected_comment_sha256": "0" * 64,
                                  "fields": {"Situation": "Road"}})
        self.assertEqual("error", result["status"])
        self.assertEqual(original, self.path.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows exclusive sharing test")
    def test_exclusive_handle_blocks_other_writer(self):
        original = self.fixture()
        with writer.locked_file(self.path, True):
            result = self.run_record({"path": str(self.path), "expected_comment_sha256": "0" * 64,
                                      "fields": {"Situation": "Road"}})
            self.assertEqual("error", result["status"])
            with self.assertRaises(OSError):
                self.path.open("r+b")
        self.assertEqual(original, self.path.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows playback reader sharing test")
    def test_existing_playback_reader_allowed_but_writer_blocked(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        for access in (0x80000000, 0x80000000 | 0x40000000):
            with self.subTest(existing_access=access):
                original = self.fixture()
                record = self.record()
                handle = create(str(self.path), access, 3, None, 3, 0x80, None)
                self.assertNotEqual(ctypes.c_void_p(-1).value, handle,
                                    "Cannot open test playback/competing handle")
                try:
                    result = self.run_record(record)
                    if access == 0x80000000:
                        self.assert_preserved(original, result)
                    else:
                        self.assertEqual("error", result["status"], result)
                        self.assertEqual(original, self.path.read_bytes())
                finally:
                    self.assertTrue(kernel.CloseHandle(handle))

    def test_postwrite_failure_rolls_back(self):
        original = self.fixture()
        record = self.record()
        actual_write = writer.write_bytes
        calls = []

        def fail_once(stream, data):
            actual_write(stream, data)
            calls.append(True)
            if len(calls) == 1:
                raise OSError("Simulated verification/write failure")

        with mock.patch.object(writer, "write_bytes", side_effect=fail_once):
            result = self.run_record(record)
        self.assertEqual("error", result["status"])
        self.assertTrue(result["rolled_back"])
        self.assertEqual(original, self.path.read_bytes())
        self.assertTrue(Path(result["backup"]["id3"]).exists())

    def test_backup_failure_leaves_mp3_untouched(self):
        original = self.fixture()
        self.backups.write_bytes(b"not a directory")
        result = self.run_record()
        self.assertEqual("error", result["status"])
        self.assertEqual(original, self.path.read_bytes())

    def test_flags_and_malformed_frame_refused(self):
        for corruption in ("tag_flags", "frame_flags", "bad_size", "padding"):
            with self.subTest(corruption=corruption):
                self.fixture()
                record = self.record()
                data = bytearray(self.path.read_bytes())
                frames, end = writer.split_tag(data)
                index, _ = writer.select_comment(frames, data[3])
                if corruption == "tag_flags":
                    data[5] = 0x40
                elif corruption == "frame_flags":
                    start = 10 + sum(map(len, frames[:index]))
                    data[start + 8] = 0x10
                elif corruption == "bad_size":
                    data[6] = 255
                else:
                    data[end - 1] = 1
                self.path.write_bytes(data)
                result = self.run_record(record)
                self.assertEqual("error", result["status"])
                self.assertEqual(bytes(data), self.path.read_bytes())

    def write_patch(self, records):
        patch = self.directory / "заплатка.json"
        patch.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        return patch

    def cli(self, patch, apply=False, report=None):
        config = {"patch_path": str(patch), "backup_directory": str(self.backups), "apply": apply}
        if report:
            config["report_path"] = str(report)
        process = subprocess.run([sys.executable, str(WRITER_PATH), "--request-stdin"],
                                 input=json.dumps(config, ensure_ascii=False).encode("utf-8"),
                                 capture_output=True)
        return process, json.loads(process.stdout.decode("utf-8"))

    def test_cli_json_unicode_report_apply_and_failure_exit(self):
        original = self.fixture()
        patch = self.write_patch([self.record()])
        report = self.directory / "отчёт.json"
        process, result = self.cli(patch, report=report)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual(result, json.loads(report.read_text(encoding="utf-8")))
        self.assertEqual(original, self.path.read_bytes())
        process, result = self.cli(patch, apply=True)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assert_preserved(original, result["results"][0])
        process, result = self.cli(patch, apply=True)
        self.assertEqual(1, process.returncode)
        self.assertFalse(result["ok"])
        self.assertEqual("error", result["results"][0]["status"])

    def test_report_cannot_overwrite_mp3_or_existing_file(self):
        original = self.fixture()
        patch = self.write_patch([self.record()])
        process, report = self.cli(patch, apply=True, report=self.path)
        self.assertNotEqual(0, process.returncode)
        self.assertFalse(report["ok"])
        self.assertEqual(original, self.path.read_bytes())

    def test_batch_duplicate_and_missing_hash_are_failures(self):
        original = self.fixture()
        record = self.record()
        patch = self.write_patch([record, record])
        process, report = self.cli(patch, apply=True)
        self.assertEqual(1, process.returncode)
        self.assertFalse(report["ok"])
        self.assertEqual(original, self.path.read_bytes())
        record.pop("expected_comment_sha256")
        patch = self.write_patch([record])
        process, report = self.cli(patch, apply=True)
        self.assertEqual(1, process.returncode)
        self.assertEqual(original, self.path.read_bytes())

    def test_duplicate_json_keys_refused(self):
        original = self.fixture()
        patch = self.write_patch([self.record()])
        text = patch.read_text(encoding="utf-8")
        patch.write_text(text.replace('"fields":', '"fields": {}, "fields":'), encoding="utf-8")
        process, report = self.cli(patch, apply=True)
        self.assertEqual(1, process.returncode)
        self.assertFalse(report["ok"])
        self.assertEqual(original, self.path.read_bytes())

    def test_real_active_mp3_copy(self):
        source = os.environ.get("ROLL_WRITER_ACTIVE_MP3")
        if not source:
            self.skipTest("Set ROLL_WRITER_ACTIVE_MP3 for integration on a source copy")
        source = Path(source)
        source_hash = writer.sha256(source.read_bytes())
        shutil.copyfile(source, self.path)
        original = self.path.read_bytes()
        record = self.record({"Situation": "Тихая разведка или погоня по городским улицам."})
        result = self.run_record(record, apply=False)
        self.assertEqual("dry_run", result["status"], result)
        self.assertEqual(original, self.path.read_bytes())
        result = self.run_record(record)
        self.assert_preserved(original, result)
        self.assertEqual(source_hash, writer.sha256(source.read_bytes()))


if __name__ == "__main__":
    unittest.main()
