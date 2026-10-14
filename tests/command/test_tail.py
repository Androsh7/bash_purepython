"""Test the tail command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.tail import TailCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds tail"""
    registry = CommandRegistry()
    registry.register(TailCommand())
    return make_shell(registry)


@pytest.fixture
def numbered_file(tmp_path: Path) -> Path:
    """Write a file holding the numbers one to twenty, one per line"""
    path = tmp_path / "numbers.txt"
    path.write_text("".join(f"{number}\n" for number in range(1, 21)), encoding="utf-8")
    return path


def test_tail_defaults_to_ten_lines(shell: ShellHarness, numbered_file: Path) -> None:
    """Check that tail without options prints the last ten lines"""
    run = shell.run("tail numbers.txt")

    assert run.stdout == "".join(f"{number}\n" for number in range(11, 21))


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("tail -n 2 numbers.txt", "19\n20\n"),
        ("tail -2 numbers.txt", "19\n20\n"),
        ("tail --lines 3 numbers.txt", "18\n19\n20\n"),
        ("tail -n 0 numbers.txt", ""),
        ("tail -n +19 numbers.txt", "19\n20\n"),
        ("tail -c 3 numbers.txt", "20\n"),
        ("tail -c +49 numbers.txt", "20\n"),
    ],
    ids=["lines_option", "numeric_shorthand", "long_option", "zero_lines", "from_line", "characters", "from_char"],
)
def test_tail_limits_output(shell: ShellHarness, numbered_file: Path, script: str, expected: str) -> None:
    """Check each way of asking tail for a limit"""
    assert shell.run(script).stdout == expected


def test_tail_reads_standard_input(shell: ShellHarness) -> None:
    """Check that piped input is limited"""
    run = shell.run("printf 'a\\nb\\nc\\n' | tail -n 2")

    assert run.stdout == "b\nc\n"


def test_tail_prints_headers_for_several_files(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that several files get GNU-style headers separated by a blank line"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    run = shell.run("tail a.txt b.txt")

    assert run.stdout == "==> a.txt <==\na\n\n==> b.txt <==\nb\n"


def test_tail_quiet_suppresses_headers(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -q prints several files without headers"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    run = shell.run("tail -q a.txt b.txt")

    assert run.stdout == "a\nb\n"


def test_tail_reports_a_missing_file_and_continues(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a missing file is reported, the other file printed, and the exit code is one"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    run = shell.run("tail -q missing.txt a.txt")

    assert (run.stdout, run.exit_code) == ("a\n", 1)
    assert "missing.txt" in run.stderr


def test_tail_rejects_a_bad_count(shell: ShellHarness) -> None:
    """Check that a non-numeric count is a usage error reported on stderr"""
    run = shell.run("tail -n lots")

    assert run.exit_code == 2
    assert run.stderr != ""
