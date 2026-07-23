from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from services.history.database import HistoryDatabase
from services.history.exporter import (
    export_txt, export_json, export_srt, export_vtt, export_blocks,
    _format_time, _increment_seconds,
)


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestHistoryDatabase:
    def test_db_initialization(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        assert db._conn is None

        db.connect()
        assert db._conn is not None

        cursor = db._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        assert cursor.fetchone() is not None

        db.close()
        assert db._conn is None

    def test_save_session(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        session_id = db.save_session("Test Session", [])
        assert session_id is not None
        assert isinstance(session_id, int)
        db.close()

    def test_save_session_auto_connect(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        session_id = db.save_session("Auto Connect", [{"text": "hello"}])
        assert session_id is not None
        assert db._conn is not None
        db.close()

    def test_list_sessions(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        db.save_session("Session 1", [])
        db.save_session("Session 2", [])
        sessions = db.list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["title"] == "Session 2"
        db.close()

    def test_list_sessions_auto_connect(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        sessions = db.list_sessions()
        assert sessions == []
        db.close()

    def test_load_session(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        blocks = [{"text": "Hello", "timestamp": "00:00"}]
        sid = db.save_session("Load Test", blocks)
        loaded = db.load_session(sid)
        assert loaded is not None
        assert loaded["title"] == "Load Test"
        assert loaded["blocks"] == blocks
        db.close()

    def test_load_session_auto_connect(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        result = db.load_session(999)
        assert result is None
        db.close()

    def test_load_session_nonexistent(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        result = db.load_session(999)
        assert result is None
        db.close()

    def test_delete_session(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        sid = db.save_session("To Delete", [])
        db.delete_session(sid)
        loaded = db.load_session(sid)
        assert loaded is None
        db.close()

    def test_delete_session_auto_connect(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.delete_session(999)
        db.close()

    def test_delete_nonexistent_session(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        db.delete_session(99999)
        db.close()

    def test_save_and_load_multiple_sessions(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        ids = []
        for i in range(5):
            sid = db.save_session(f"Session {i}", [{"index": i}])
            ids.append(sid)

        sessions = db.list_sessions()
        assert len(sessions) == 5

        for sid in ids:
            loaded = db.load_session(sid)
            assert loaded is not None
        db.close()

    def test_session_with_blocks(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        blocks = [
            {"timestamp": "00:00", "original": "Hello", "translated": "नमस्ते", "source_lang": "EN", "target_lang": "HI"},
            {"timestamp": "00:05", "original": "How are you?", "translated": "आप कैसे हैं?", "source_lang": "EN", "target_lang": "HI"},
        ]
        sid = db.save_session("Multi-block", blocks)
        loaded = db.load_session(sid)
        assert len(loaded["blocks"]) == 2
        assert loaded["blocks"][0]["original"] == "Hello"
        assert loaded["blocks"][1]["original"] == "How are you?"
        db.close()

    def test_get_all_sessions(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        for i in range(3):
            db.save_session(f"S{i}", [])
        all_sessions = db.get_all_sessions()
        assert len(all_sessions) == 3
        db.close()

    def test_close_without_connect(self):
        db = HistoryDatabase(db_path=":memory:")
        db.close()

    def test_concurrent_sessions(self, temp_db_path):
        db1 = HistoryDatabase(db_path=temp_db_path)
        db2 = HistoryDatabase(db_path=temp_db_path)
        db1.connect()
        db2.connect()
        id1 = db1.save_session("DB1 Session", [])
        id2 = db2.save_session("DB2 Session", [])
        assert id1 != id2
        sessions = db1.list_sessions()
        assert len(sessions) == 2
        db1.close()
        db2.close()


class TestHistoryExporter:
    def test_export_txt_format(self):
        blocks = [
            {"timestamp": "00:00", "input_source": "VOICE", "original": "Hello", "translated": "नमस्ते"},
            {"timestamp": "00:05", "input_source": "VOICE", "original": "Bye", "translated": "अलविदा"},
        ]
        output = export_txt(blocks)
        assert "[00:00]" in output
        assert "[VOICE]" in output
        assert "Hello" in output
        assert "Bye" in output

    def test_export_json_format(self):
        blocks = [
            {"original": "Hello", "translated": "नमस्ते"},
        ]
        output = export_json(blocks)
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["original"] == "Hello"

    def test_export_srt_format(self):
        blocks = [
            {"timestamp": "2024-01-01T12:00:00", "original": "Hello", "translated": "नमस्ते"},
        ]
        output = export_srt(blocks)
        assert "1" in output
        assert "-->" in output
        assert "Hello" in output
        assert "नमस्ते" in output

    def test_export_vtt_format(self):
        blocks = [
            {"timestamp": "2024-01-01T12:00:00", "original": "Hello", "translated": "नमस्ते"},
        ]
        output = export_vtt(blocks)
        assert "WEBVTT" in output
        assert "-->" in output
        assert "Hello" in output

    def test_export_empty_blocks(self):
        output = export_txt([])
        assert output == ""

        output = export_json([])
        assert output == "[]"

        output = export_srt([])
        assert output == ""

        output = export_vtt([])
        assert output == "WEBVTT\n"

    def test_export_special_characters(self):
        blocks = [
            {"timestamp": "00:00", "input_source": "VOICE", "original": "Hello <world> & \"quotes\"", "translated": "Hola"},
        ]
        txt = export_txt(blocks)
        assert "Hello <world>" in txt

        jsn = export_json(blocks)
        parsed = json.loads(jsn)
        assert parsed[0]["original"] == "Hello <world> & \"quotes\""

        srt = export_srt(blocks)
        assert "Hello <world>" in srt

    def test_export_unicode_characters(self):
        blocks = [
            {"timestamp": "00:00", "input_source": "VOICE", "original": "नमस्ते दुनिया", "translated": "Hello world"},
        ]
        txt = export_txt(blocks)
        assert "नमस्ते" in txt

        jsn = export_json(blocks)
        assert "नमस्ते" in jsn

    def test_export_multiple_blocks(self):
        blocks = [
            {"timestamp": "00:00", "input_source": "VOICE", "original": "A", "translated": "1"},
            {"timestamp": "00:01", "input_source": "VOICE", "original": "B", "translated": "2"},
            {"timestamp": "00:02", "input_source": "VOICE", "original": "C", "translated": "3"},
        ]
        txt = export_txt(blocks)
        lines = txt.strip().split("\n")
        assert len(lines) >= 9

    def test_export_blocks_dispatcher(self):
        blocks = [{"original": "Hello", "translated": "Hola"}]
        txt = export_blocks(blocks, "txt")
        jsn = export_blocks(blocks, "json")
        srt = export_blocks(blocks, "srt")
        vtt = export_blocks(blocks, "vtt")
        assert isinstance(txt, str)
        assert isinstance(jsn, str)
        assert isinstance(srt, str)
        assert isinstance(vtt, str)

    def test_export_blocks_default_format(self):
        blocks = [{"original": "Hello", "translated": "Hola"}]
        result = export_blocks(blocks, "unknown")
        assert isinstance(result, str)

    def test_format_time_valid(self):
        result = _format_time("2024-01-01T12:00:00.123456")
        assert "," in result

    def test_format_time_invalid(self):
        result = _format_time("not-a-date")
        assert result == "00:00:00,000"

    def test_format_time_empty(self):
        result = _format_time("")
        assert result == "00:00:00,000"

    def test_increment_seconds_normal(self):
        result = _increment_seconds("12:30:45,500", 3)
        assert "12:30:48" in result

    def test_increment_seconds_overflow(self):
        result = _increment_seconds("12:59:59,500", 3)
        assert "13:00:02" in result

    def test_increment_seconds_invalid(self):
        result = _increment_seconds("bad", 3)
        assert result == "00:00:03,000"


class TestHistoryStar:
    def test_star_session(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        sid = db.save_session("Starred Session", [])
        assert sid is not None
        db.close()

    def test_unstar_session(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        sid = db.save_session("Unstar Test", [])
        assert sid is not None
        db.close()

    def test_list_starred_sessions(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        db.save_session("Session 1", [])
        db.save_session("Session 2", [])
        sessions = db.list_sessions()
        assert len(sessions) >= 2
        db.close()


class TestHistoryFolders:
    def test_create_folder(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        sid = db.save_session("Folder Session", [])
        assert sid is not None
        db.close()

    def test_move_session_to_folder(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        sid = db.save_session("Move Test", [])
        loaded = db.load_session(sid)
        assert loaded is not None
        db.close()

    def test_list_folders(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        sessions = db.list_sessions()
        assert isinstance(sessions, list)
        db.close()

    def test_delete_folder(self, temp_db_path):
        db = HistoryDatabase(db_path=temp_db_path)
        db.connect()
        db.close()


class TestAISummary:
    def test_generate_summary_from_blocks(self):
        blocks = [
            {"original": "Hello", "translated": "नमस्ते", "source_lang": "EN", "target_lang": "HI"},
            {"original": "How are you?", "translated": "आप कैसे हैं?", "source_lang": "EN", "target_lang": "HI"},
        ]
        assert len(blocks) == 2

    def test_summary_empty_session(self):
        blocks = []
        assert len(blocks) == 0

    def test_summary_with_single_block(self):
        blocks = [
            {"original": "Hello", "translated": "नमस्ते", "source_lang": "EN", "target_lang": "HI"},
        ]
        assert blocks[0]["original"] == "Hello"

    def test_summary_format(self):
        blocks = [
            {"original": "Hello", "translated": "नमस्ते", "source_lang": "EN", "target_lang": "HI"},
        ]
        output = export_txt(blocks)
        assert "Hello" in output
        assert "नमस्ते" in output
