"""Test the less and more commands through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.pager import LessCommand, MoreCommand
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.registry import CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness], tmp_path: Path) -> ShellHarness:
    """Return a harness with both pagers registered and two files"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    return make_shell(CommandRegistry([LessCommand(), MoreCommand(), PrintfCommand()]))


@pytest.mark.parametrize("program", ["less", "more"], ids=str)
def test_pager_prints_files_in_order(shell: ShellHarness, program: str) -> None:
    """Check that the pager prints every file like cat"""
    run = shell.run(f"{program} a.txt b.txt")

    assert (run.stdout, run.exit_code) == ("a\nb\n", 0)


@pytest.mark.parametrize("program", ["less", "more"], ids=str)
def test_pager_prints_standard_input(shell: ShellHarness, program: str) -> None:
    """Check that piped text is printed"""
    run = shell.run(f"printf 'x\\ny\\n' | {program}")

    assert run.stdout == "x\ny\n"


@pytest.mark.parametrize("program", ["less", "more"], ids=str)
def test_pager_ignores_display_flags(shell: ShellHarness, program: str) -> None:
    """Check that common pager flags are accepted"""
    run = shell.run(f"{program} -N -R a.txt")

    assert (run.stdout, run.exit_code) == ("a\n", 0)


@pytest.mark.parametrize("program", ["less", "more"], ids=str)
def test_pager_reports_a_missing_file(shell: ShellHarness, program: str) -> None:
    """Check that a missing file is named and the exit code is one"""
    run = shell.run(f"{program} missing.txt")

    assert run.exit_code == 1
    assert run.stderr == f"{program}: missing.txt: No such file or directory\n"
