import sys
import os
import json
import time
import datetime
import pytest
from unittest.mock import patch, MagicMock, mock_open, ANY

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts import statusline

def test_iso_to_nanos():
    # Test valid date
    dt = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    nanos = int(dt.timestamp() * 1e9)
    assert statusline.iso_to_nanos("2023-01-01T12:00:00Z") == nanos

    # Test empty string / None
    now_nanos = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1e9)
    res_empty = statusline.iso_to_nanos("")
    assert isinstance(res_empty, int)
    assert abs(res_empty - now_nanos) < 1e9 # within 1 second

    res_none = statusline.iso_to_nanos(None)
    assert isinstance(res_none, int)

    # Test invalid string
    res_invalid = statusline.iso_to_nanos("invalid_date")
    assert isinstance(res_invalid, int)

def test_main_invalid_json(capsys):
    with patch('sys.stdin.read', return_value="invalid json"):
        statusline.main()
        captured = capsys.readouterr()
        assert captured.out.strip() == "agy ✦ statusline"

def test_main_otel_unavailable(capsys):
    valid_json = {
        "conversation_id": "123",
        "transcript_path": "/path/to/transcript",
        "model": {"display_name": "TestModel"},
        "context_window": {"current_usage": {"input_tokens": 10, "output_tokens": 20}, "used_percentage": 5.5}
    }
    with patch('sys.stdin.read', return_value=json.dumps(valid_json)):
        with patch('scripts.statusline.OTEL_AVAILABLE', False):
            statusline.main()
            captured = capsys.readouterr()
            assert captured.out.strip() == "agy ✦ TestModel ┃ 📥 10 ┃ 📤 20 ┃ 📊 5.50% ┃ 📡 telemetry: dep_missing"

def test_main_telemetry_off_missing_info(capsys):
    valid_json = {
        "model": {"display_name": "TestModel"},
        "context_window": {"current_usage": {"input_tokens": 10, "output_tokens": 20}, "used_percentage": 5.5}
    }
    with patch('sys.stdin.read', return_value=json.dumps(valid_json)):
        with patch('scripts.statusline.OTEL_AVAILABLE', True):
            statusline.main()
            captured = capsys.readouterr()
            assert captured.out.strip() == "agy ✦ TestModel ┃ 📥 10 ┃ 📤 20 ┃ 📊 5.50% ┃ 📡 telemetry: off"

def test_main_no_logs(capsys):
    valid_json = {
        "conversation_id": "123",
        "transcript_path": "/path/to/transcript",
        "model": {"display_name": "TestModel"}
    }
    with patch('sys.stdin.read', return_value=json.dumps(valid_json)):
        with patch('scripts.statusline.OTEL_AVAILABLE', True):
            with patch('os.path.exists', return_value=False):
                statusline.main()
                captured = capsys.readouterr()
                assert captured.out.strip() == "agy ✦ TestModel ┃ 📥 0 ┃ 📤 0 ┃ 📊 0.00% ┃ 📡 telemetry: no_logs"

def test_main_telemetry_offline_cache(capsys):
    valid_json = {
        "conversation_id": "123",
        "transcript_path": "/path/to/transcript"
    }
    with patch('sys.stdin.read', return_value=json.dumps(valid_json)):
        with patch('scripts.statusline.OTEL_AVAILABLE', True):
            def mock_exists(path):
                if path == "/path/to/transcript": return True
                if "agy_telemetry_cache.json" in path: return True
                return False

            with patch('os.path.exists', side_effect=mock_exists):
                # Mock cache with recent offline timestamp
                mock_cache_data = json.dumps({"telemetry_offline_timestamp": time.time() - 10})
                with patch('builtins.open', mock_open(read_data=mock_cache_data)):
                    statusline.main()
                    captured = capsys.readouterr()
                    assert "📡 telemetry: offline" in captured.out

def test_main_socket_failure(capsys):
    valid_json = {
        "conversation_id": "123",
        "transcript_path": "/path/to/transcript"
    }
    with patch('sys.stdin.read', return_value=json.dumps(valid_json)):
        with patch('scripts.statusline.OTEL_AVAILABLE', True):
            def mock_exists(path):
                return path == "/path/to/transcript"

            with patch('os.path.exists', side_effect=mock_exists):
                with patch('socket.socket') as mock_socket:
                    instance = mock_socket.return_value
                    instance.connect.side_effect = Exception("Connection refused")
                    # mock open so writing cache doesn't crash
                    with patch('builtins.open', mock_open()):
                        statusline.main()
                        captured = capsys.readouterr()
                        assert "📡 telemetry: offline" in captured.out

def test_main_happy_path(capsys):
    valid_json = {
        "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
        "transcript_path": "/path/to/transcript",
        "model": {"display_name": "TestModel"},
        "context_window": {"current_usage": {"input_tokens": 10, "output_tokens": 20}, "used_percentage": 5.5}
    }

    transcript_lines = [
        json.dumps({"type": "USER_INPUT", "created_at": "2023-01-01T12:00:00Z", "step_index": 1, "content": "Hello"}),
        json.dumps({"type": "PLANNER_RESPONSE", "created_at": "2023-01-01T12:00:01Z", "step_index": 2, "content": "Hi"})
    ]

    def side_effect_open(file, *args, **kwargs):
        if file == "/path/to/transcript":
            return mock_open(read_data="\n".join(transcript_lines))()
        return mock_open()()

    with patch('sys.stdin.read', return_value=json.dumps(valid_json)):
        with patch('scripts.statusline.OTEL_AVAILABLE', True):
            def mock_exists(path):
                return path == "/path/to/transcript"

            with patch('os.path.exists', side_effect=mock_exists):
                with patch('socket.socket') as mock_socket:
                    instance = mock_socket.return_value

                    with patch('builtins.open', side_effect=side_effect_open):
                        # Mock the opentelemetry imports in the module namespace since they might not be loaded initially
                        import sys
                        if 'opentelemetry' not in sys.modules:
                            sys.modules['opentelemetry'] = MagicMock()

                        mock_trace = MagicMock()
                        mock_tracer = MagicMock()
                        mock_trace.get_tracer.return_value = mock_tracer

                        with patch.multiple('scripts.statusline',
                                            trace=mock_trace,
                                            TracerProvider=MagicMock(),
                                            OTLPSpanExporter=MagicMock(),
                                            SimpleSpanProcessor=MagicMock(),
                                            Resource=MagicMock(),
                                            NonRecordingSpan=MagicMock(),
                                            SpanContext=MagicMock(),
                                            TraceFlags=MagicMock(),
                                            create=True):
                            statusline.main()

                            captured = capsys.readouterr()
                            assert captured.out.strip() == "agy ✦ TestModel ┃ 📥 10 ┃ 📤 20 ┃ 📊 5.50% ┃ 📡 telemetry: ok"
                            assert mock_tracer.start_span.call_count == 2
