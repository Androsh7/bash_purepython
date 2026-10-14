"""Test the whoami command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.whoami import WhoamiCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds whoami"""
    registry = CommandRegistry()
    registry.register(WhoamiCommand())
    return make_shell(registry)


def test_whoami_prints_the_default_user(shell: ShellHarness) -> None:
    """Check that the name is user when USER is not set"""
    run = shell.run("whoami")

    assert (run.stdout, run.exit_code) == ("user\n", 0)


def test_whoami_prints_the_user_variable(shell: ShellHarness) -> None:
    """Check that USER names the current user"""
    run = shell.run("USER=alice; whoami")

    assert run.stdout == "alice\n"
