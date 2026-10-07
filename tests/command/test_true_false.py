"""Test the true and false commands through the shell"""

# Project libraries
from tests.conftest import ShellHarness


def test_true_succeeds_silently(shell: ShellHarness) -> None:
    """Check that true exits zero with no output"""
    run = shell.run("true anything")

    assert (run.stdout, run.stderr, run.exit_code) == ("", "", 0)


def test_false_fails_silently(shell: ShellHarness) -> None:
    """Check that false exits one with no output"""
    run = shell.run("false anything")

    assert (run.stdout, run.stderr, run.exit_code) == ("", "", 1)
