"""Test the id command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.id import IdCommand
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds id"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), IdCommand()]))


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("", "uid=1000(user) gid=1000(user) groups=1000(user)\n"),
        ("-u", "1000\n"),
        ("-g", "1000\n"),
        ("-G", "1000\n"),
        ("-un", "user\n"),
        ("-gn", "user\n"),
    ],
    ids=["default", "uid", "gid", "groups", "user name", "group name"],
)
def test_id_prints_the_fixed_identity(shell: ShellHarness, options: str, expected: str) -> None:
    """Check that each option prints its part of the one identity"""
    run = shell.run(f"id {options}")

    assert (run.stdout, run.exit_code) == (expected, 0)


def test_id_takes_the_name_from_the_user_variable(shell: ShellHarness) -> None:
    """Check that USER changes the name but not the numbers"""
    run = shell.run("USER=alice; id")

    assert run.stdout == "uid=1000(alice) gid=1000(alice) groups=1000(alice)\n"


def test_id_reports_an_unknown_user(shell: ShellHarness) -> None:
    """Check that naming another user fails with exit code one"""
    run = shell.run("id nobody")

    assert run.exit_code == 1
    assert "nobody" in run.stderr
