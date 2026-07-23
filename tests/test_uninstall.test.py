import os
import json
import shutil
import pytest
from unittest.mock import patch

import uninstall

@patch("uninstall.os.path.expanduser")
def test_no_target_dirs(mock_expanduser, tmp_path):
    mock_expanduser.return_value = str(tmp_path)
    # The directories don't exist, so it should just return early for each loop iteration.
    # No exceptions should be raised.
    uninstall.main()

@patch("uninstall.os.path.expanduser")
def test_target_dirs_exist_but_empty(mock_expanduser, tmp_path):
    mock_expanduser.return_value = str(tmp_path)

    # Create the directories
    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    alt_dir = tmp_path / ".gemini" / "antigravity"
    cli_dir.mkdir(parents=True)
    alt_dir.mkdir(parents=True)

    # No files exist inside, so nothing should be removed.
    uninstall.main()

    # Directories should still exist
    assert cli_dir.exists()
    assert alt_dir.exists()

@patch("uninstall.os.path.expanduser")
def test_happy_path(mock_expanduser, tmp_path):
    mock_expanduser.return_value = str(tmp_path)

    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True)

    # Create settings.json
    settings_path = cli_dir / "settings.json"
    settings_data = {"statusLine": "some_config", "otherKey": "value"}
    settings_path.write_text(json.dumps(settings_data))

    # Create statusline.py
    statusline_path = cli_dir / "statusline.py"
    statusline_path.write_text("print('status')")

    # Create telemetry_lib
    lib_path = cli_dir / "telemetry_lib"
    lib_path.mkdir()
    (lib_path / "lib.py").write_text("print('lib')")

    uninstall.main()

    # Verify statusLine is removed from settings.json
    with open(settings_path, "r") as f:
        new_settings = json.load(f)
    assert "statusLine" not in new_settings
    assert new_settings["otherKey"] == "value"

    # Verify statusline.py is removed
    assert not statusline_path.exists()

    # Verify telemetry_lib is removed
    assert not lib_path.exists()

@patch("uninstall.os.path.expanduser")
def test_settings_without_statusline(mock_expanduser, tmp_path):
    mock_expanduser.return_value = str(tmp_path)

    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True)

    settings_path = cli_dir / "settings.json"
    settings_data = {"otherKey": "value"}
    settings_path.write_text(json.dumps(settings_data))

    uninstall.main()

    with open(settings_path, "r") as f:
        new_settings = json.load(f)
    assert "statusLine" not in new_settings
    assert new_settings["otherKey"] == "value"

@patch("uninstall.os.path.expanduser")
def test_settings_error(mock_expanduser, tmp_path):
    mock_expanduser.return_value = str(tmp_path)

    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True)

    settings_path = cli_dir / "settings.json"
    settings_path.write_text("invalid json")

    # Should handle the json.decoder.JSONDecodeError gracefully
    uninstall.main()

    # File should remain untouched (still invalid json)
    assert settings_path.read_text() == "invalid json"

@patch("uninstall.os.remove")
@patch("uninstall.os.path.expanduser")
def test_remove_file_error(mock_expanduser, mock_remove, tmp_path):
    mock_expanduser.return_value = str(tmp_path)

    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True)

    statusline_path = cli_dir / "statusline.py"
    statusline_path.write_text("print('status')")

    # Make os.remove raise an exception
    mock_remove.side_effect = PermissionError("Permission denied")

    # Should handle exception gracefully
    uninstall.main()

    assert statusline_path.exists()

@patch("uninstall.shutil.rmtree")
@patch("uninstall.os.path.expanduser")
def test_remove_dir_error(mock_expanduser, mock_rmtree, tmp_path):
    mock_expanduser.return_value = str(tmp_path)

    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True)

    lib_path = cli_dir / "telemetry_lib"
    lib_path.mkdir()

    # Make shutil.rmtree raise an exception
    mock_rmtree.side_effect = PermissionError("Permission denied")

    # Should handle exception gracefully
    uninstall.main()

    assert lib_path.exists()
