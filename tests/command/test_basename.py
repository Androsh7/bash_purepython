"""Test the basename command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("basename /usr/lib/file.txt", "file.txt\n"),
        ("basename /usr/lib/file.txt .txt", "file\n"),
        ("basename -s .txt /a/file.txt", "file\n"),
        ("basename -a /a/one /b/two", "one\ntwo\n"),
        ("basename .txt .txt", ".txt\n"),
        ("basename dir/", "dir\n"),
    ],
    ids=["plain", "legacy_suffix", "suffix_option", "multiple", "suffix_only_name_kept", "trailing_slash"],
)
def test_basename_strips_directory_and_suffix(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each way of asking for a base name"""
    assert shell.run(script).stdout == expected
