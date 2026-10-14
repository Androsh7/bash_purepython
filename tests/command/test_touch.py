"""Test the touch command through the shell"""

# Standard libraries
import os
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.touch import TouchCommand
from tests.conftest import ShellHarness

OLD_TIMESTAMP_S = 1_000_000_000


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds touch"""
    registry = CommandRegistry()
    registry.register(TouchCommand())
    return make_shell(registry)


def test_touch_creates_a_missing_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a file that does not exist is created empty"""
    run = shell.run("touch new.txt")

    assert run.exit_code == 0
    assert (tmp_path / "new.txt").read_bytes() == b""


def test_touch_creates_every_file_named(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that several paths are all created"""
    shell.run("touch a.txt b.txt")

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()


def test_touch_updates_the_modification_time(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an existing file keeps its content and gets a newer modification time"""
    path = tmp_path / "old.txt"
    path.write_text("content\n", encoding="utf-8")
    os.utime(path, (OLD_TIMESTAMP_S, OLD_TIMESTAMP_S))

    shell.run("touch old.txt")

    assert path.read_text(encoding="utf-8") == "content\n"
    assert path.stat().st_mtime > OLD_TIMESTAMP_S


def test_touch_no_create_leaves_a_missing_file_absent(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -c does not create a file and still succeeds"""
    run = shell.run("touch -c absent.txt")

    assert run.exit_code == 0
    assert not (tmp_path / "absent.txt").exists()


def test_touch_reports_a_missing_parent_directory(shell: ShellHarness) -> None:
    """Check that a path whose directory does not exist fails with a message naming it"""
    run = shell.run("touch missing/new.txt")

    assert run.exit_code == 1
    assert "missing/new.txt" in run.stderr


def test_touch_requires_a_path(shell: ShellHarness) -> None:
    """Check that touch with no operand is a usage error"""
    run = shell.run("touch")

    assert run.exit_code == 2
