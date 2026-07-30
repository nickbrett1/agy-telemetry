import sys
import os
import pytest
from unittest.mock import patch

# Add the parent directory to sys.path so we can import from scripts
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import scripts.statusline as statusline

def test_preset_id_generator_preset_trace_id():
    generator = statusline.PresetIdGenerator()
    generator.trace_id = 12345
    assert generator.generate_trace_id() == 12345

def test_preset_id_generator_random_trace_id():
    generator = statusline.PresetIdGenerator()
    with patch('secrets.randbits', return_value=987654321) as mock_randbits:
        assert generator.generate_trace_id() == 987654321
        mock_randbits.assert_called_once_with(128)

def test_preset_id_generator_preset_span_id():
    generator = statusline.PresetIdGenerator()
    generator.span_id = 54321
    assert generator.generate_span_id() == 54321

def test_preset_id_generator_random_span_id():
    generator = statusline.PresetIdGenerator()
    with patch('secrets.randbits', return_value=123456789) as mock_randbits:
        assert generator.generate_span_id() == 123456789
        mock_randbits.assert_called_once_with(64)
