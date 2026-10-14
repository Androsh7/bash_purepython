"""Test the uname command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from bash_purepython.command.uname import UnameCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds uname"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), UnameCommand()]))


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("", "Linux\n"),
        ("-s", "Linux\n"),
        ("-n", "androsh7\n"),
        ("-r", "6.1.0\n"),
        ("-m", "wasm32\n"),
        ("-o", "GNU/Linux\n"),
        ("-snm", "Linux androsh7 wasm32\n"),
        ("-m -s", "Linux wasm32\n"),
        ("-a", "Linux androsh7 6.1.0 #1 SMP wasm32 GNU/Linux\n"),
    ],
    ids=["default", "kernel", "node", "release", "machine", "os", "bundled", "fixed order", "all"],
)
def test_uname_prints_the_selected_fields(shell: ShellHarness, options: str, expected: str) -> None:
    """Check that each flag selects its field and the fields keep uname's order"""
    run = shell.run(f"uname {options}")

    assert (run.stdout, run.exit_code) == (expected, 0)


def test_uname_node_name_follows_the_hostname_variable(shell: ShellHarness) -> None:
    """Check that HOSTNAME overrides the node name"""
    run = shell.run("HOSTNAME=box; uname -n")

    assert run.stdout == "box\n"
