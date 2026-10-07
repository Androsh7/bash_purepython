"""Test the dirname command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("dirname /usr/lib/file.txt", "/usr/lib\n"),
        ("dirname file.txt", ".\n"),
        ("dirname /a /b/c", "/\n/b\n"),
    ],
    ids=["nested", "bare_name", "several"],
)
def test_dirname_strips_last_component(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that the directory part is printed, or a dot when there is none"""
    assert shell.run(script).stdout == expected
