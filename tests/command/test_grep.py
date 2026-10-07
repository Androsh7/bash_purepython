"""Test the grep command through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.fixture
def two_files(tmp_path: Path) -> None:
    """Write two files with overlapping content"""
    (tmp_path / "a.txt").write_text("apple\nbanana\nApple pie\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("cherry\napple tart\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("script", "expected_stdout", "expected_exit_code"),
    [
        ("grep apple a.txt", "apple\n", 0),
        ("grep -i apple a.txt", "apple\nApple pie\n", 0),
        ("grep -v apple a.txt", "banana\nApple pie\n", 0),
        ("grep -n an a.txt", "2:banana\n", 0),
        ("grep -c apple a.txt b.txt", "a.txt:1\nb.txt:1\n", 0),
        ("grep -l cherry a.txt b.txt", "b.txt\n", 0),
        ("grep apple a.txt b.txt", "a.txt:apple\nb.txt:apple tart\n", 0),
        ("grep -h apple a.txt b.txt", "apple\napple tart\n", 0),
        ("grep -H apple a.txt", "a.txt:apple\n", 0),
        ("grep -F 'a.t' a.txt", "", 1),
        ("grep 'a.t' b.txt", "apple tart\n", 0),
        ("grep -e apple -e cherry b.txt", "cherry\napple tart\n", 0),
        ("grep missing a.txt", "", 1),
        ("printf 'x\\ny\\n' | grep y", "y\n", 0),
        ("grep -r cherry .", "./b.txt:cherry\n", 0),
    ],
    ids=[
        "match",
        "ignore_case",
        "invert",
        "line_number",
        "count",
        "files_with_matches",
        "two_files_prefixed",
        "no_filename",
        "with_filename",
        "fixed_string_no_match",
        "regex_dot",
        "two_patterns",
        "no_match_exits_one",
        "stdin",
        "recursive",
    ],
)
def test_grep_selects_lines(
    shell: ShellHarness, two_files: None, script: str, expected_stdout: str, expected_exit_code: int
) -> None:
    """Check matching, prefixes, counts and exit codes"""
    run = shell.run(script)

    assert (run.stdout, run.exit_code) == (expected_stdout, expected_exit_code)


def test_grep_missing_file_exits_two(shell: ShellHarness, two_files: None) -> None:
    """Check that an unreadable file is reported and the exit code is two even when another file matched"""
    run = shell.run("grep apple missing a.txt")

    assert run.exit_code == 2
    assert "missing" in run.stderr
    assert "a.txt:apple" in run.stdout


def test_grep_bad_pattern_exits_two(shell: ShellHarness, two_files: None) -> None:
    """Check that an invalid regular expression is a usage error"""
    run = shell.run("grep '(' a.txt")

    assert run.exit_code == 2
