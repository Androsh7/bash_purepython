"""Test the od command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.od import OdCommand
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds od"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), OdCommand()]))


def test_od_prints_octal_shorts_by_default(shell: ShellHarness) -> None:
    """Check that the default dump is little-endian two-byte octal units with octal offsets"""
    run = shell.run("echo hello | od")

    assert (run.stdout, run.exit_code) == ("0000000 062550 066154 005157\n0000006\n", 0)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("-c", "0000000   h   e   l   l   o  \\n\n0000006\n"),
        ("-x", "0000000 6568 6c6c 0a6f\n0000006\n"),
        ("-tx1", "0000000 68 65 6c 6c 6f 0a\n0000006\n"),
        ("-An -tx1", " 68 65 6c 6c 6f 0a\n"),
        ("-A x -tx1", "000000 68 65 6c 6c 6f 0a\n000006\n"),
        ("-A d -tx1", "0000000 68 65 6c 6c 6f 0a\n0000006\n"),
        ("-td1", "0000000  104  101  108  108  111   10\n0000006\n"),
        ("-tu2", "0000000 25960 27756  2671\n0000006\n"),
        ("-b", "0000000 150 145 154 154 157 012\n0000006\n"),
    ],
    ids=[
        "characters",
        "hex shorts",
        "hex bytes",
        "no address",
        "hex address",
        "decimal address",
        "signed",
        "unsigned shorts",
        "octal bytes",
    ],
)
def test_od_formats_match_gnu(shell: ShellHarness, options: str, expected: str) -> None:
    """Check that each format and address radix prints what GNU od prints"""
    run = shell.run(f"echo hello | od {options}")

    assert run.stdout == expected


def test_od_dumps_a_file_over_several_lines(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that sixteen bytes fill a line and the offsets advance in octal"""
    (tmp_path / "data.bin").write_bytes(bytes(range(17)))

    run = shell.run("od -tx1 data.bin")

    assert run.stdout == ("0000000 00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f\n0000020 10\n0000021\n")


def test_od_skips_and_limits_bytes(shell: ShellHarness) -> None:
    """Check that -j skips bytes and -N stops after a count, with offsets counted from the skip"""
    run = shell.run("echo hello | od -j 1 -N 3 -tx1")

    assert run.stdout == "0000001 65 6c 6c\n0000004\n"


def test_od_collapses_repeated_lines(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that identical full lines are replaced by a star unless -v is given"""
    (tmp_path / "zeros.bin").write_bytes(bytes(48))

    collapsed = shell.run("od -tx1 zeros.bin")
    verbose = shell.run("od -v -tx1 zeros.bin")

    assert collapsed.stdout.splitlines()[1] == "*"
    assert len(verbose.stdout.splitlines()) == 4


def test_od_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file fails with exit code one"""
    run = shell.run("od missing.bin")

    assert run.exit_code == 1
    assert "missing.bin" in run.stderr
