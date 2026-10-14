"""Test the fold command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.echo import EchoCommand
from bash_purepython.command.fold import FoldCommand, fold_line
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.registry import CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness], tmp_path: Path) -> ShellHarness:
    """Return a harness with fold registered and a long line on disk"""
    (tmp_path / "long.txt").write_text("abcdefghij\nxy\n", encoding="utf-8")
    return make_shell(CommandRegistry([FoldCommand(), EchoCommand(), PrintfCommand()]))


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("fold -w 4 long.txt", "abcd\nefgh\nij\nxy\n"),
        ("fold -4 long.txt", "abcd\nefgh\nij\nxy\n"),
        ("fold --width 10 long.txt", "abcdefghij\nxy\n"),
        ("echo 'one two three' | fold -w 8", "one two \nthree\n"),
        ("echo 'one two three' | fold -s -w 8", "one two \nthree\n"),
        ("echo 'one two three' | fold -s -w 6", "one \ntwo \nthree\n"),
        ("echo 'abcdefgh' | fold -s -w 3", "abc\ndef\ngh\n"),
        ("printf 'a\\tb\\n' | fold -w 8", "a\t\nb\n"),
        ("printf 'a\\tb\\n' | fold -b -w 8", "a\tb\n"),
        ("printf '' | fold", ""),
        ("echo '' | fold -w 2", "\n"),
    ],
    ids=[
        "width",
        "numeric_shorthand",
        "long_width",
        "cut_mid_word",
        "break_at_space",
        "break_at_each_space",
        "no_space_falls_back_to_cut",
        "tab_counts_to_the_next_stop",
        "bytes_count_tab_as_one",
        "empty_input",
        "empty_line_kept",
    ],
)
def test_fold_wraps_lines(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each way of wrapping"""
    run = shell.run(script)

    assert (run.stdout, run.exit_code) == (expected, 0)


def test_fold_default_width_is_eighty(shell: ShellHarness) -> None:
    """Check that a line of ninety characters breaks after eighty"""
    run = shell.run(f"echo {'x' * 90} | fold")

    assert run.stdout == f"{'x' * 80}\n{'x' * 10}\n"


def test_fold_rejects_a_zero_width(shell: ShellHarness) -> None:
    """Check that a width below one is a usage error"""
    run = shell.run("echo hi | fold -w 0")

    assert run.exit_code == 2
    assert "invalid number of columns" in run.stderr


def test_fold_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file is named and the exit code is one"""
    run = shell.run("fold missing.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr


def test_fold_line_keeps_multibyte_characters_whole() -> None:
    """Check that folding counts characters, never splitting one"""
    assert fold_line("ééééé", 2, break_at_spaces=False, count_bytes=False) == ["éé", "éé", "é"]
