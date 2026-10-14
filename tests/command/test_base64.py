"""Test the base64 command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.base64 import Base64Command
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness

LONG_INPUT_LENGTH = 100
GNU_WRAP_COLUMNS = 76


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds base64"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), Base64Command()]))


def test_base64_encodes_standard_input(shell: ShellHarness) -> None:
    """Check that piped text is encoded with a trailing newline"""
    run = shell.run("echo hello | base64")

    assert (run.stdout, run.exit_code) == ("aGVsbG8K\n", 0)


def test_base64_decodes_standard_input(shell: ShellHarness) -> None:
    """Check that -d turns encoded text back into the original"""
    run = shell.run("echo aGVsbG8K | base64 -d")

    assert run.stdout == "hello\n"


def test_base64_encodes_a_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a named file is encoded"""
    (tmp_path / "data.bin").write_bytes(b"\x00\xff")

    run = shell.run("base64 data.bin")

    assert run.stdout == "AP8=\n"


def test_base64_wraps_at_seventy_six_columns_by_default(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that long output is broken into lines of the GNU default width"""
    (tmp_path / "long.txt").write_bytes(b"a" * LONG_INPUT_LENGTH)

    run = shell.run("base64 long.txt")

    lines = run.stdout.splitlines()
    assert len(lines) > 1
    assert all(len(line) <= GNU_WRAP_COLUMNS for line in lines)
    assert len(lines[0]) == GNU_WRAP_COLUMNS


def test_base64_wrap_zero_disables_wrapping(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -w 0 prints one line however long the input"""
    (tmp_path / "long.txt").write_bytes(b"a" * LONG_INPUT_LENGTH)

    run = shell.run("base64 -w 0 long.txt")

    assert "\n" not in run.stdout
    assert len(run.stdout) > LONG_INPUT_LENGTH


def test_base64_round_trips_binary_through_gzip(shell: ShellHarness) -> None:
    """Check that bytes survive encoding and decoding inside a pipeline"""
    run = shell.run("printf 'round trip' | gzip | base64 | base64 -d | gunzip")

    assert run.stdout == "round trip"


def test_base64_reports_invalid_input(shell: ShellHarness) -> None:
    """Check that decoding text that is not base64 fails with exit code one"""
    run = shell.run("echo 'not base64!' | base64 -d")

    assert run.exit_code == 1
    assert "invalid input" in run.stderr


def test_base64_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file is reported on stderr"""
    run = shell.run("base64 missing.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr
