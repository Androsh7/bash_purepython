"""Test the head command through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.fixture
def numbered_file(tmp_path: Path) -> Path:
    """Write a file holding the numbers one to twenty, one per line"""
    path = tmp_path / "numbers.txt"
    path.write_text("".join(f"{number}\n" for number in range(1, 21)), encoding="utf-8")
    return path


def test_head_defaults_to_ten_lines(shell: ShellHarness, numbered_file: Path) -> None:
    """Check that head without options prints the first ten lines"""
    run = shell.run("head numbers.txt")

    assert run.stdout == "".join(f"{number}\n" for number in range(1, 11))


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("head -n 2 numbers.txt", "1\n2\n"),
        ("head -2 numbers.txt", "1\n2\n"),
        ("head --lines 3 numbers.txt", "1\n2\n3\n"),
        ("head -n 0 numbers.txt", ""),
        ("head -c 3 numbers.txt", "1\n2"),
    ],
    ids=["lines_option", "numeric_shorthand", "long_option", "zero_lines", "characters"],
)
def test_head_limits_output(shell: ShellHarness, numbered_file: Path, script: str, expected: str) -> None:
    """Check each way of asking head for a limit"""
    assert shell.run(script).stdout == expected


def test_head_reads_standard_input(shell: ShellHarness) -> None:
    """Check that piped input is limited"""
    run = shell.run("yes | head -n 4")

    assert run.stdout == "y\ny\ny\ny\n"


def test_head_prints_headers_for_several_files(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that several files get GNU-style headers separated by a blank line"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    run = shell.run("head a.txt b.txt")

    assert run.stdout == "==> a.txt <==\na\n\n==> b.txt <==\nb\n"


def test_head_quiet_suppresses_headers(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -q prints several files without headers"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    run = shell.run("head -q a.txt b.txt")

    assert run.stdout == "a\nb\n"


def test_head_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file fails with a message naming it"""
    run = shell.run("head missing.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr


def test_head_rejects_a_bad_count(shell: ShellHarness) -> None:
    """Check that a non-numeric count is a usage error reported on stderr"""
    run = shell.run("head -n lots")

    assert run.exit_code == 2
    assert run.stderr != ""
    assert run.stdout == ""


def test_head_help_goes_to_stdout(shell: ShellHarness) -> None:
    """Check that --help prints usage on stdout and succeeds"""
    run = shell.run("head --help")

    assert run.exit_code == 0
    assert "usage" in run.stdout.lower()
