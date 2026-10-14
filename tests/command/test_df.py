"""Test the df command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.df import DfCommand
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds df"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), DfCommand()]))


def test_df_prints_a_header_and_the_root_filesystem(shell: ShellHarness) -> None:
    """Check that the table has the GNU header and one line for the root filesystem in 1K blocks"""
    run = shell.run("df")

    lines = run.stdout.splitlines()
    assert run.exit_code == 0
    assert lines[0].split() == ["Filesystem", "1K-blocks", "Used", "Available", "Use%", "Mounted", "on"]
    assert lines[1].split() == ["/dev/root", "10485760", "1048576", "9437184", "10%", "/"]


def test_df_human_readable_prints_units(shell: ShellHarness) -> None:
    """Check that -h prints the sizes with unit letters"""
    run = shell.run("df -h")

    lines = run.stdout.splitlines()
    assert lines[0].split() == ["Filesystem", "Size", "Used", "Avail", "Use%", "Mounted", "on"]
    assert lines[1].split() == ["/dev/root", "10G", "1.0G", "9.0G", "10%", "/"]


def test_df_accepts_a_path(shell: ShellHarness) -> None:
    """Check that naming a path still reports the one filesystem"""
    run = shell.run("df .")

    assert len(run.stdout.splitlines()) == 2
