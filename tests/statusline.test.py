import pytest
from unittest.mock import patch, MagicMock
import datetime

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.statusline import iso_to_nanos

def test_iso_to_nanos_valid_with_z():
    # 2023-01-01T00:00:00Z -> 1672531200.0
    result = iso_to_nanos("2023-01-01T00:00:00Z")
    assert result == 1672531200000000000

def test_iso_to_nanos_valid_without_z():
    # 2023-01-01T00:00:00+00:00 -> 1672531200.0
    result = iso_to_nanos("2023-01-01T00:00:00+00:00")
    assert result == 1672531200000000000

@patch('scripts.statusline.datetime')
def test_iso_to_nanos_empty(mock_datetime):
    mock_now = MagicMock()
    mock_now.timestamp.return_value = 1000.0
    mock_datetime.datetime.now.return_value = mock_now
    mock_datetime.timezone = datetime.timezone

    assert iso_to_nanos("") == int(1000.0 * 1e9)
    assert iso_to_nanos(None) == int(1000.0 * 1e9)

@patch('scripts.statusline.datetime')
def test_iso_to_nanos_invalid(mock_datetime):
    mock_now = MagicMock()
    mock_now.timestamp.return_value = 1000.0
    mock_datetime.datetime.now.return_value = mock_now
    mock_datetime.timezone = datetime.timezone

    mock_datetime.datetime.fromisoformat.side_effect = ValueError("Invalid iso format")

    assert iso_to_nanos("invalid") == int(1000.0 * 1e9)
