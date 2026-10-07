"""Test the yes command through the shell"""

# Project libraries
from tests.conftest import ShellHarness


def test_yes_repeats_y_by_default(shell: ShellHarness) -> None:
    """Check that yes without arguments repeats the letter y"""
    run = shell.run("yes | head -n 2")

    assert run.stdout == "y\ny\n"


def test_yes_repeats_its_arguments_joined(shell: ShellHarness) -> None:
    """Check that yes joins its arguments with spaces on every line"""
    run = shell.run("yes a b | head -n 2")

    assert run.stdout == "a b\na b\n"
