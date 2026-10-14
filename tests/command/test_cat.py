"""Test the cat command through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


def test_cat_concatenates_files_in_order(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that files are output one after another"""
    (tmp_path / "a.txt").write_text("a1\na2\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b1\n", encoding="utf-8")

    run = shell.run("cat a.txt b.txt")

    assert (run.stdout, run.exit_code) == ("a1\na2\nb1\n", 0)


def test_cat_reads_standard_input_when_no_file_is_named(shell: ShellHarness) -> None:
    """Check that piped input is passed through"""
    run = shell.run("echo piped | cat")

    assert run.stdout == "piped\n"


def test_cat_mixes_standard_input_with_files(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a dash reads standard input at that position"""
    (tmp_path / "a.txt").write_text("file\n", encoding="utf-8")

    run = shell.run("echo piped | cat a.txt - a.txt")

    assert run.stdout == "file\npiped\nfile\n"


def test_cat_numbers_lines(shell: ShellHarness) -> None:
    """Check that -n prefixes each line with a right-aligned number"""
    run = shell.run("echo a | cat -n")

    assert run.stdout.split("\t") == ["     1", "a\n"]


def test_cat_reports_a_missing_file_and_continues(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a missing file is reported on stderr, other files are still output, and the exit code is one"""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    run = shell.run("cat missing.txt a.txt")

    assert (run.stdout, run.exit_code) == ("a\n", 1)
    assert "missing.txt" in run.stderr


def test_cat_reports_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that naming a directory fails"""
    (tmp_path / "dir").mkdir()

    run = shell.run("cat dir")

    assert run.exit_code == 1
    assert "dir" in run.stderr


def test_cat_without_input_or_files_outputs_nothing(shell: ShellHarness) -> None:
    """Check that cat with no input and no files produces nothing rather than blocking"""
    run = shell.run("cat")

    assert (run.stdout, run.exit_code) == ("", 0)


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'a\\tb\\x01\\n' | cat -v", "a\tb^A\n"),
        ("printf 'a\\tb\\n' | cat -T", "a^Ib\n"),
        ("printf 'a\\n' | cat -E", "a$\n"),
        ("printf 'a\\tb\\x7f\\n' | cat -A", "a^Ib^?$\n"),
        ("printf 'a\\x01\\n' | cat -e", "a^A$\n"),
        ("printf 'a\\t\\x01\\n' | cat -t", "a^I^A\n"),
        ("printf 'h\\xe9\\n' | cat -v", "hM-CM-)\n"),
        ("printf 'a\\n\\n\\n\\nb\\n' | cat -s", "a\n\nb\n"),
    ],
    ids=[
        "show_nonprinting",
        "show_tabs",
        "show_ends",
        "show_all",
        "ends_and_nonprinting",
        "tabs_and_nonprinting",
        "high_bytes_as_meta",
        "squeeze_blank",
    ],
)
def test_cat_display_option(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each display option"""
    assert shell.run(script).stdout == expected


def test_cat_numbers_only_nonblank_lines(shell: ShellHarness) -> None:
    """Check that -b skips empty lines when numbering"""
    run = shell.run("printf 'a\\n\\nb\\n' | cat -b")

    assert [line.split("\t")[0].strip() for line in run.stdout.splitlines()] == ["1", "", "2"]
