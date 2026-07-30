import pytest
from unittest.mock import patch, mock_open, MagicMock
import sys
import os

# Get the absolute path to the directory containing this file
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the absolute path to the parent directory (project root)
parent_dir = os.path.dirname(current_dir)
# Add the project root to sys.path
sys.path.insert(0, parent_dir)

import install

@patch('install.os.path.expanduser')
@patch('install.os.path.exists')
@patch('install.os.makedirs')
@patch('install.urllib.request.urlopen')
@patch('builtins.open', new_callable=mock_open)
@patch('install.json.dump')
def test_install_happy_path(mock_json_dump, mock_file, mock_urlopen, mock_makedirs, mock_exists, mock_expanduser):
    # Setup mocks
    mock_expanduser.return_value = '/home/user'

    # Mock os.path.exists for: target_dir, alt_dir, target_dir (again), settings_path
    mock_exists.side_effect = lambda path: False

    # Mock urlopen
    mock_response = MagicMock()
    mock_response.read.return_value = b"statusline_content"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    # Execute
    install.main()

    # Assertions
    mock_makedirs.assert_called_with(os.path.join('/home/user', '.gemini', 'antigravity-cli'), exist_ok=True)

    # Assert file writing (statusline.py and settings.json)
    assert mock_file.call_count == 2
    mock_file.assert_any_call(os.path.join('/home/user', '.gemini', 'antigravity-cli', 'statusline.py'), 'w', encoding='utf-8')
    mock_file.assert_any_call(os.path.join('/home/user', '.gemini', 'antigravity-cli', 'settings.json'), 'w', encoding='utf-8')

    # Assert json dump was called
    mock_json_dump.assert_called_once()
    args, kwargs = mock_json_dump.call_args
    assert args[0]['statusLine']['type'] == 'command'
    assert 'statusline.py' in args[0]['statusLine']['command']


@patch('install.os.path.expanduser')
@patch('install.os.path.exists')
@patch('install.os.makedirs')
@patch('install.urllib.request.urlopen')
@patch('subprocess.run')
@patch('install.sys.exit')
def test_install_download_failure(mock_exit, mock_subprocess, mock_urlopen, mock_makedirs, mock_exists, mock_expanduser):
    # Setup mocks
    mock_expanduser.return_value = '/home/user'
    mock_exists.return_value = False

    # Simulate urllib failure (needs to be an exception caught in try block)
    import urllib.error
    mock_urlopen.side_effect = urllib.error.URLError("Connection Error")

    # Simulate curl and wget failures
    failed_result = MagicMock()
    failed_result.returncode = 1
    mock_subprocess.return_value = failed_result

    # Mock sys.exit to raise an Exception to break the execution early
    mock_exit.side_effect = SystemExit(1)

    # Execute
    with pytest.raises(SystemExit) as e:
        install.main()

    # Assertions
    assert e.value.code == 1
    mock_exit.assert_called_once_with(1)
