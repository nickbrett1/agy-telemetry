import pytest
import datetime
from unittest.mock import patch, MagicMock
from scripts.statusline import iso_to_nanos

def test_iso_to_nanos_valid():
    naive_dt = datetime.datetime.fromisoformat("2023-01-01T00:00:00")
    assert iso_to_nanos("2023-01-01T00:00:00") == int(naive_dt.timestamp() * 1e9)
    assert iso_to_nanos("2023-01-01T00:00:00Z") == 1672531200000000000
    assert iso_to_nanos("2023-01-01T00:00:00+00:00") == 1672531200000000000

@patch('scripts.statusline.datetime')
def test_iso_to_nanos_empty(mock_datetime):
    mock_now = MagicMock()
    mock_now.timestamp.return_value = 12345.0
    mock_datetime.datetime.now.return_value = mock_now
    mock_datetime.timezone = datetime.timezone

    assert iso_to_nanos("") == 12345000000000

@patch('scripts.statusline.datetime')
def test_iso_to_nanos_invalid(mock_datetime):
    mock_now = MagicMock()
    mock_now.timestamp.return_value = 12345.0
    mock_datetime.datetime.now.return_value = mock_now
    mock_datetime.timezone = datetime.timezone
    mock_datetime.datetime.fromisoformat.side_effect = datetime.datetime.fromisoformat

    assert iso_to_nanos("invalid") == 12345000000000

@patch('scripts.statusline.datetime')
def test_iso_to_nanos_none(mock_datetime):
    mock_now = MagicMock()
    mock_now.timestamp.return_value = 12345.0
    mock_datetime.datetime.now.return_value = mock_now
    mock_datetime.timezone = datetime.timezone

    assert iso_to_nanos(None) == 12345000000000
