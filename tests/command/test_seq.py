"""Test the seq command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("seq 3", "1\n2\n3\n"),
        ("seq 2 4", "2\n3\n4\n"),
        ("seq 1 2 7", "1\n3\n5\n7\n"),
        ("seq 3 -1 1", "3\n2\n1\n"),
        ("seq -s , 3", "1,2,3\n"),
        ("seq -w 8 10", "08\n09\n10\n"),
        ("seq 0.5 0.5 1.5", "0.5\n1\n1.5\n"),
        ("seq 0", ""),
    ],
    ids=["last_only", "first_last", "increment", "descending", "separator", "equal_width", "floats", "empty"],
)
def test_seq_prints_the_sequence(shell: ShellHarness, script: str, expected: str) -> None:
    """Check every bound form and option"""
    assert shell.run(script).stdout == expected


def test_seq_streams_into_head(shell: ShellHarness) -> None:
    """Check that a long sequence is cut short by its consumer"""
    run = shell.run("seq 1000000 | head -n 2")

    assert run.stdout == "1\n2\n"


def test_seq_rejects_a_non_number(shell: ShellHarness) -> None:
    """Check that a word is a usage error"""
    run = shell.run("seq x")

    assert run.exit_code == 2
