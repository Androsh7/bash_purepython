"""Test the tee command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.tee import TeeCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds tee"""
    registry = CommandRegistry()
    registry.register(TeeCommand())
    return make_shell(registry)


def test_tee_copies_input_to_stdout_and_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the input reaches both standard output and the named file"""
    run = shell.run("printf 'one\\ntwo\\n' | tee copy.txt")

    assert run.stdout == "one\ntwo\n"
    assert (tmp_path / "copy.txt").read_text(encoding="utf-8") == "one\ntwo\n"


def test_tee_writes_every_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that several files all receive the input"""
    shell.run("echo hi | tee a.txt b.txt")

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "hi\n"


def test_tee_append_keeps_existing_content(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -a adds to the file instead of truncating it"""
    (tmp_path / "log.txt").write_text("old\n", encoding="utf-8")

    shell.run("echo new | tee -a log.txt")

    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "old\nnew\n"


def test_tee_truncates_without_append(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an existing file is overwritten by default"""
    (tmp_path / "log.txt").write_text("old\n", encoding="utf-8")

    shell.run("echo new | tee log.txt")

    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "new\n"


def test_tee_streams_so_an_endless_producer_terminates(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that tee passes chunks through as they arrive and stops when its reader stops"""
    run = shell.run("yes | tee out.txt | head -n 2")

    assert run.stdout == "y\ny\n"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").startswith("y\ny\n")


def test_tee_reports_an_unwritable_file_and_still_copies(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a file in a missing directory is reported, the input still passes through, and exit code is one"""
    run = shell.run("echo hi | tee missing/out.txt")

    assert (run.stdout, run.exit_code) == ("hi\n", 1)
    assert "missing/out.txt" in run.stderr


def test_tee_without_input_creates_the_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that tee with nothing on standard input still creates an empty file"""
    run = shell.run("tee empty.txt")

    assert (run.stdout, run.exit_code) == ("", 0)
    assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""
