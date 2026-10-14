"""Test the paste command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.paste import PasteCommand, parse_delimiters
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.registry import CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness], tmp_path: Path) -> ShellHarness:
    """Return a harness with paste registered and three small files"""
    (tmp_path / "a.txt").write_text("1\n2\n3\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x\ny\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("p\nq\nr\ns\n", encoding="utf-8")
    return make_shell(CommandRegistry([PasteCommand(), PrintfCommand()]))


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("paste a.txt b.txt", "1\tx\n2\ty\n3\t\n"),
        ("paste a.txt b.txt c.txt", "1\tx\tp\n2\ty\tq\n3\t\tr\n\t\ts\n"),
        ("paste -d , a.txt b.txt", "1,x\n2,y\n3,\n"),
        ("paste -d ',;' a.txt b.txt c.txt", "1,x;p\n2,y;q\n3,;r\n,;s\n"),
        ("paste -d '\\n' a.txt b.txt", "1\nx\n2\ny\n3\n\n"),
        ("paste -d '\\0' a.txt b.txt", "1x\n2y\n3\n"),
        ("paste -s a.txt b.txt", "1\t2\t3\nx\ty\n"),
        ("paste -s -d , a.txt", "1,2,3\n"),
        ("printf 'm\\nn\\n' | paste a.txt -", "1\tm\n2\tn\n3\t\n"),
        ("printf 'm\\nn\\n' | paste", "m\nn\n"),
        ("printf 'm\\nn\\no\\np\\n' | paste - -", "m\tn\no\tp\n"),
        ("printf 'm\\nn\\no\\n' | paste -s -d ' '", "m n o\n"),
        ("paste a.txt", "1\n2\n3\n"),
    ],
    ids=[
        "two_files",
        "three_files_uneven",
        "comma_delimiter",
        "delimiters_cycle",
        "newline_delimiter",
        "empty_delimiter",
        "serial",
        "serial_with_delimiter",
        "file_and_stdin",
        "stdin_alone",
        "stdin_twice_alternates_lines",
        "serial_stdin_joins_lines",
        "single_file",
    ],
)
def test_paste_merges_lines(shell: ShellHarness, script: str, expected: str) -> None:
    """Check parallel and serial merging with every delimiter form"""
    run = shell.run(script)

    assert (run.stdout, run.stderr, run.exit_code) == (expected, "", 0)


def test_paste_reports_a_missing_file_and_pastes_the_rest(shell: ShellHarness) -> None:
    """Check that a missing file is named, skipped and the exit code is one"""
    run = shell.run("paste a.txt missing.txt b.txt")

    assert (run.stdout, run.exit_code) == ("1\tx\n2\ty\n3\t\n", 1)
    assert run.stderr == "paste: missing.txt: No such file or directory\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("\t", ["\t"]), (",;", [",", ";"]), ("\\t\\n", ["\t", "\n"]), ("\\\\", ["\\"]), ("\\0", [""]), ("", [""])],
    ids=["tab", "two", "escapes", "backslash", "empty_escape", "empty_list"],
)
def test_parse_delimiters_resolves_escapes(text: str, expected: list[str]) -> None:
    """Check the delimiter list grammar"""
    assert parse_delimiters(text) == expected
