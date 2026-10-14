"""Test the stat command through the shell"""

# Standard libraries
import re
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from bash_purepython.command.stat import StatCommand
from tests.conftest import ShellHarness

TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{9} [+-]\d{4}$")


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds stat"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), StatCommand()]))


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    """Write a six-byte file"""
    path = tmp_path / "a.txt"
    path.write_bytes(b"hello\n")
    return path


def test_stat_default_block_describes_the_file(shell: ShellHarness, sample_file: Path) -> None:
    """Check that the multi-line block names the file, its size, type, owner and link count"""
    run = shell.run("stat a.txt")

    lines = run.stdout.splitlines()
    assert run.exit_code == 0
    assert lines[0] == "  File: a.txt"
    assert lines[1].startswith("  Size: 6 ")
    assert lines[1].endswith("regular file")
    assert "Links: 1" in lines[2]
    assert "Uid: ( 1000/    user)   Gid: ( 1000/    user)" in lines[3]
    assert lines[7] == " Birth: -"


def test_stat_format_prints_size_name_and_type(shell: ShellHarness, sample_file: Path) -> None:
    """Check that -c substitutes %s, %n and %F"""
    run = shell.run("stat -c '%s %n %F' a.txt")

    assert run.stdout == "6 a.txt regular file\n"


def test_stat_format_owner_group_and_links(shell: ShellHarness, sample_file: Path) -> None:
    """Check that %U, %G and %h print the fixed owner and link count"""
    run = shell.run("stat -c '%U %G %h' a.txt")

    assert run.stdout == "user user 1\n"


def test_stat_format_modification_time(shell: ShellHarness, sample_file: Path) -> None:
    """Check that %y prints the GNU timestamp and %Y the same time in seconds"""
    run = shell.run("stat -c '%y|%Y' a.txt")

    timestamp, seconds = run.stdout.rstrip("\n").split("|")
    assert TIMESTAMP_PATTERN.match(timestamp)
    assert int(seconds) == int(sample_file.stat().st_mtime)


def test_stat_format_permissions_and_inode(shell: ShellHarness, sample_file: Path) -> None:
    """Check that %a is octal, %A is the symbolic mode and %i the inode"""
    run = shell.run("stat -c '%a %A %i' a.txt")

    octal, symbolic, inode = run.stdout.split()
    assert int(octal, 8) == sample_file.stat().st_mode & 0o7777
    assert symbolic.startswith("-")
    assert len(symbolic) == len("-rw-r--r--")
    assert int(inode) == sample_file.stat().st_ino


def test_stat_format_types_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a directory is typed as one and an empty file as regular empty file"""
    (tmp_path / "dir").mkdir()
    (tmp_path / "empty").write_bytes(b"")

    run = shell.run("stat -c '%F' dir empty")

    assert run.stdout == "directory\nregular empty file\n"


def test_stat_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file is reported with exit code one"""
    run = shell.run("stat missing.txt")

    assert run.exit_code == 1
    assert "cannot stat 'missing.txt'" in run.stderr
