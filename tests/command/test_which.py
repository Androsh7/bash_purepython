"""Test the which command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.which import WhichCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds which, bound to that registry's names"""
    registry = CommandRegistry()
    registry.register(WhichCommand(registry.names))
    return make_shell(registry)


def test_which_prints_the_path_of_a_known_command(shell: ShellHarness) -> None:
    """Check that a registered command resolves under /usr/bin"""
    run = shell.run("which cat")

    assert (run.stdout, run.exit_code) == ("/usr/bin/cat\n", 0)


def test_which_prints_every_known_name(shell: ShellHarness) -> None:
    """Check that several names are each resolved on their own line"""
    run = shell.run("which cat grep")

    assert run.stdout == "/usr/bin/cat\n/usr/bin/grep\n"


def test_which_fails_for_an_unknown_command(shell: ShellHarness) -> None:
    """Check that an unknown name prints nothing and exits one"""
    run = shell.run("which nosuchcommand")

    assert (run.stdout, run.exit_code) == ("", 1)


def test_which_fails_when_any_name_is_unknown(shell: ShellHarness) -> None:
    """Check that the known names still print but the exit code is one"""
    run = shell.run("which cat nosuchcommand")

    assert (run.stdout, run.exit_code) == ("/usr/bin/cat\n", 1)


def test_which_finds_itself(shell: ShellHarness) -> None:
    """Check that which is among the names it answers from"""
    run = shell.run("which which")

    assert run.stdout == "/usr/bin/which\n"
