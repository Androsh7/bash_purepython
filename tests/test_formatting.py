"""Unit tests for ruff formatting"""

# Standard libraries
import re
import subprocess


def test_ruff_formatting():
    """Test that ruff formatting has been applied"""
    assert subprocess.run("ruff format . --check", shell=True, capture_output=True, check=True)


def test_ruff_check():
    """Test that all ruff fixes have been applied"""
    result = subprocess.run("ruff check . --show-fixes", shell=True, capture_output=True, check=False)
    assert re.search(r"(\d+ fixable with the)", str(result.stdout)) is None
