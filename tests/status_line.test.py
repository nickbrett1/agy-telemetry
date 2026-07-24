import sys
import os
import json
import tempfile
from unittest.mock import patch, mock_open, MagicMock, call

# Import main from statusline.py
import importlib.util

spec = importlib.util.spec_from_file_location("statusline_script", os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts/statusline.py')))
statusline = importlib.util.module_from_spec(spec)
sys.modules["statusline_script"] = statusline
spec.loader.exec_module(statusline)
main = statusline.main

def test_file_read_error_logging(capsys):
    input_data = {
        "conversation_id": "test-123",
        "transcript_path": "/tmp/transcript.jsonl",
        "model": {"display_name": "TestModel"},
    }

    error_log_path = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-cli", "agy_telemetry_error.log")

    with patch('sys.stdin.read', return_value=json.dumps(input_data)):
        with patch('os.path.exists', return_value=True):
            with patch('socket.socket'):
                # We need a proper mock for the file handle
                m_open = mock_open()

                with patch('builtins.open') as mock_file:
                    def side_effect(path, *args, **kwargs):
                        if path == "/tmp/transcript.jsonl":
                            raise PermissionError("Access denied")
                        return m_open(path, *args, **kwargs)

                    mock_file.side_effect = side_effect

                    main()

                    # Verify output
                    captured = capsys.readouterr()
                    assert "telemetry: err" in captured.out

                    # Verify error log was written
                    mock_file.assert_any_call(error_log_path, "a")

                    # Check if write was called with expected content
                    write_calls = m_open().write.call_args_list
                    assert any("File read error: Access denied" in call[0][0] for call in write_calls)
