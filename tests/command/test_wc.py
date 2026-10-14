"""Test the wc command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.wc import WcCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds wc"""
    registry = CommandRegistry()
    registry.register(WcCommand())
    return make_shell(registry)


def test_wc_counts_standard_input_without_a_label(shell: ShellHarness) -> None:
    """Check that piped input gets lines, words and bytes padded to seven and no name"""
    run = shell.run("printf 'one two\\nthree\\n' | wc")

    assert run.stdout == "      2       3      14\n"


def test_wc_single_count_of_standard_input_is_not_padded(shell: ShellHarness) -> None:
    """Check that one count for one input prints bare, as GNU wc does"""
    run = shell.run("printf 'a\\nb\\n' | wc -l")

    assert run.stdout == "2\n"


def test_wc_counts_a_file_with_its_name(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a file's counts are padded to the width of its size and followed by its name"""
    (tmp_path / "words.txt").write_bytes(b"one two\nthree\n")

    run = shell.run("wc words.txt")

    assert run.stdout == " 2  3 14 words.txt\n"


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'a b\\nc\\n' | wc -l", "2\n"),
        ("printf 'a b\\nc\\n' | wc -w", "3\n"),
        ("printf 'a b\\nc\\n' | wc -c", "6\n"),
        ("printf 'h\\xe9\\n' | wc -m", "3\n"),
        ("printf 'ab\\ncdef\\n' | wc -L", "4\n"),
        ("printf 'a b\\nc\\n' | wc -lw", "      2       3\n"),
    ],
    ids=["lines", "words", "bytes", "characters", "longest_line", "two_counts"],
)
def test_wc_option(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each count selection"""
    assert shell.run(script).stdout == expected


def test_wc_counts_bytes_from_a_bytes_producer(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that compressed bytes are counted as bytes rather than decoded text"""
    (tmp_path / "data.txt").write_bytes(b"hello\n")

    run = shell.run("gzip -c data.txt | wc -c")

    assert int(run.stdout) == len((tmp_path / "data.txt").read_bytes()) + 20


def test_wc_totals_several_files(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that several files end with a total row"""
    (tmp_path / "a.txt").write_bytes(b"a\n")
    (tmp_path / "b.txt").write_bytes(b"b c\n")

    run = shell.run("wc -l a.txt b.txt")

    assert run.stdout == "1 a.txt\n1 b.txt\n2 total\n"


def test_wc_reports_a_missing_file_and_continues(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a missing file is reported, the other counted, and the exit code is one"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    run = shell.run("wc -l missing.txt a.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr
    assert "1 a.txt" in run.stdout
