"""Test the xxd command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from bash_purepython.command.xxd import XxdCommand
from tests.conftest import ShellHarness

HELLO_DUMP = "00000000: 6865 6c6c 6f0a" + " " * 27 + "hello.\n"


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds xxd"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), XxdCommand()]))


def test_xxd_dumps_standard_input_in_the_classic_layout(shell: ShellHarness) -> None:
    """Check that the offset, grouped hex padded to a full line, and the text column match xxd exactly"""
    run = shell.run("echo hello | xxd")

    assert (run.stdout, run.exit_code) == (HELLO_DUMP, 0)


def test_xxd_dumps_a_file_over_several_lines(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that sixteen bytes fill a line and the next line's offset advances"""
    (tmp_path / "data.bin").write_bytes(bytes(range(18)))

    run = shell.run("xxd data.bin")

    assert run.stdout == (
        "00000000: 0001 0203 0405 0607 0809 0a0b 0c0d 0e0f  ................\n"
        "00000010: 1011                                     ..\n"
    )


def test_xxd_plain_prints_continuous_hex(shell: ShellHarness) -> None:
    """Check that -p prints only the hex digits"""
    run = shell.run("echo hello | xxd -p")

    assert run.stdout == "68656c6c6f0a\n"


def test_xxd_reverses_a_plain_dump(shell: ShellHarness) -> None:
    """Check that -r -p turns hex back into bytes"""
    run = shell.run("echo 68656c6c6f0a | xxd -r -p")

    assert run.stdout == "hello\n"


def test_xxd_reverses_its_own_dump(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -r restores the original bytes from a classic dump, including a text column of hex letters"""
    (tmp_path / "data.bin").write_bytes(b"abcdef0123456789abcdef0123456789abc")

    run = shell.run("xxd data.bin | xxd -r")

    assert run.stdout == "abcdef0123456789abcdef0123456789abc"


def test_xxd_limits_the_length(shell: ShellHarness) -> None:
    """Check that -l stops after that many bytes"""
    run = shell.run("echo hello | xxd -l 2 -p")

    assert run.stdout == "6865\n"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("-c 4", "00000000: 6865 6c6c  hell\n00000004: 6f0a" + " " * 7 + "o.\n"),
        ("-g 1", "00000000: 68 65 6c 6c 6f 0a" + " " * 32 + "hello.\n"),
        ("-c 8 -g 4", "00000000: 68656c6c 6f0a" + " " * 6 + "hello.\n"),
    ],
    ids=["four columns", "single byte groups", "eight columns in fours"],
)
def test_xxd_columns_and_group_size_shape_the_line(shell: ShellHarness, options: str, expected: str) -> None:
    """Check that -c and -g change the bytes per line and per group with the padding xxd uses"""
    run = shell.run(f"echo hello | xxd {options}")

    assert run.stdout == expected


def test_xxd_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file fails with exit code one"""
    run = shell.run("xxd missing.bin")

    assert run.exit_code == 1
    assert "missing.bin" in run.stderr
