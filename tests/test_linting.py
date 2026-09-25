"""Unit tests for linting"""

# Standard libraries
import json
import subprocess

# Third-party libraries
import pytest

ENFORCE_RUFF_LINTING_SUGGESTIONS = True


def test_no_ruff_formatting_changes():
    """Every file is formatted the way ruff would format it"""
    subprocess.run("ruff format . --check", shell=True, capture_output=True, check=True)


def test_no_fixable_ruff_fixes():
    """No ruff error is left that ruff could safely fix on its own"""
    result = subprocess.run(
        "ruff check . --show-fixes --output-format=json", shell=True, capture_output=True, check=False
    )
    for fix in json.loads(result.stdout):
        if fix["fix"] is not None and fix["fix"]["applicability"] != "unsafe":
            raise Exception("Fixable ruff error")


def test_no_ruff_suggestions():
    """No ruff suggestions exist"""
    if not ENFORCE_RUFF_LINTING_SUGGESTIONS:
        pytest.skip("Enforcement of ruff linting suggestions is disabled")
    subprocess.run("ruff check . --show-fixes", shell=True, capture_output=True, check=True)
