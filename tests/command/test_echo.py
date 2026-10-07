"""Test the echo command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo", "\n"),
        ("echo hello world", "hello world\n"),
        ("echo -n hello", "hello"),
        ("echo -e 'a\\nb'", "a\nb\n"),
        ("echo -E 'a\\nb'", "a\\nb\n"),
        ("echo -ne 'a\\tb'", "a\tb"),
        ("echo -e 'stop\\chere'", "stop"),
        ("echo -x", "-x\n"),
        ("echo -- -n", "-- -n\n"),
        ("echo 'a\\nb'", "a\\nb\n"),
    ],
    ids=[
        "empty",
        "words",
        "no_newline",
        "escapes",
        "escapes_disabled",
        "combined_flags",
        "stop_sequence",
        "unknown_flag_is_text",
        "double_dash_is_text",
        "escapes_off_by_default",
    ],
)
def test_echo_writes_its_arguments(shell: ShellHarness, script: str, expected: str) -> None:
    """Check echo output for its flags and plain words"""
    assert shell.run(script).stdout == expected
