"""Test the help command through the shell"""

# Project libraries
from tests.conftest import ShellHarness


def test_help_lists_every_registered_command(shell: ShellHarness) -> None:
    """Check that the listing names the shipped commands including help itself"""
    run = shell.run("help")

    names = set(run.stdout.split())
    assert {"cat", "grep", "ls", "help", "ps"} <= names
