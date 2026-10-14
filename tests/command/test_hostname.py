"""Test the hostname command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.hostname import HostnameCommand
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds hostname"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), HostnameCommand()]))


def test_hostname_prints_the_default_name(shell: ShellHarness) -> None:
    """Check that the fixed host name is printed"""
    run = shell.run("hostname")

    assert (run.stdout, run.exit_code) == ("androsh7\n", 0)


def test_hostname_follows_the_hostname_variable(shell: ShellHarness) -> None:
    """Check that HOSTNAME overrides the name"""
    run = shell.run("HOSTNAME=box.example.com; hostname")

    assert run.stdout == "box.example.com\n"


def test_hostname_short_stops_at_the_first_dot(shell: ShellHarness) -> None:
    """Check that -s prints only the first label"""
    run = shell.run("HOSTNAME=box.example.com; hostname -s")

    assert run.stdout == "box\n"
