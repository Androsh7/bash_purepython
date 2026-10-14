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


def test_grep_quiet_prints_nothing_and_exits_zero_on_a_match(shell: ShellHarness, two_files: None) -> None:
    """Check that -q reports a match through the exit code alone"""
    run = shell.run("grep -q apple a.txt")

    assert (run.stdout, run.exit_code) == ("", 0)


def test_grep_quiet_exits_one_without_a_match(shell: ShellHarness, two_files: None) -> None:
    """Check that -q reports no match through the exit code alone"""
    run = shell.run("grep -q zzzzzz a.txt")

    assert (run.stdout, run.exit_code) == ("", 1)


def test_grep_quiet_works_as_an_if_condition_on_piped_input(shell: ShellHarness) -> None:
    """Check that -q reads a pipe and drives a conditional"""
    run = shell.run("if echo needle | grep -q needle; then echo found; fi")

    assert run.stdout == "found\n"


@pytest.fixture
def context_file(tmp_path: Path) -> None:
    """Write a numbered file with two matches far apart and two close together"""
    lines = [f"line{number}" for number in range(1, 13)]
    lines[2] = "match three"
    lines[8] = "match nine"
    lines[10] = "match eleven"
    (tmp_path / "context.txt").write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


@pytest.mark.parametrize(
    ("script", "expected_stdout", "expected_exit_code"),
    [
        ("echo 'cat hat bat' | grep -o '.at'", "cat\nhat\nbat\n", 0),
        ("echo 'cat hat' | grep -o 'z'", "", 1),
        ("grep -o 'an' a.txt", "an\nan\n", 0),
        ("grep -on 'an' a.txt", "2:an\n2:an\n", 0),
        ("grep -o 'pp' a.txt b.txt", "a.txt:pp\na.txt:pp\nb.txt:pp\n", 0),
        ("grep -v -o 'apple' a.txt", "", 0),
        ("echo 'apple pineapple' | grep -ow 'apple'", "apple\n", 0),
        ("grep -w 'apple' a.txt b.txt", "a.txt:apple\nb.txt:apple tart\n", 0),
        ("echo 'pineapple' | grep -w 'apple'", "", 1),
        ("grep -x 'apple' a.txt b.txt", "a.txt:apple\n", 0),
        ("echo 'apple tart' | grep -x 'apple'", "", 1),
    ],
    ids=[
        "only_matching_each_match_on_its_line",
        "only_matching_no_match",
        "only_matching_file",
        "only_matching_with_line_numbers",
        "only_matching_with_filenames",
        "only_matching_with_invert_prints_nothing",
        "only_matching_whole_word",
        "whole_word_files",
        "whole_word_rejects_substring",
        "whole_line",
        "whole_line_rejects_prefix",
    ],
)
def test_grep_only_matching_and_word_options(
    shell: ShellHarness, two_files: None, script: str, expected_stdout: str, expected_exit_code: int
) -> None:
    """Check -o, -w and -x"""
    run = shell.run(script)

    assert (run.stdout, run.exit_code) == (expected_stdout, expected_exit_code)


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("grep -A 1 three context.txt", "match three\nline4\n"),
        ("grep -B 1 three context.txt", "line2\nmatch three\n"),
        ("grep -C 1 three context.txt", "line2\nmatch three\nline4\n"),
        ("grep -1 three context.txt", "line2\nmatch three\nline4\n"),
        ("grep -n -C 1 three context.txt", "2-line2\n3:match three\n4-line4\n"),
        ("grep -A 1 match context.txt", "match three\nline4\n--\nmatch nine\nline10\nmatch eleven\nline12\n"),
        ("grep -A 0 match context.txt", "match three\n--\nmatch nine\n--\nmatch eleven\n"),
        (
            "grep -C 1 match context.txt",
            "line2\nmatch three\nline4\n--\nline8\nmatch nine\nline10\nmatch eleven\nline12\n",
        ),
        ("grep -B 2 nine context.txt", "line7\nline8\nmatch nine\n"),
        ("grep -A 5 eleven context.txt", "match eleven\nline12\n"),
        ("grep -B 5 three context.txt", "line1\nline2\nmatch three\n"),
        ("grep -c -C 2 match context.txt", "3\n"),
        ("grep -H -C 1 three context.txt", "context.txt-line2\ncontext.txt:match three\ncontext.txt-line4\n"),
        (
            "grep -C 1 -v line context.txt",
            "line2\nmatch three\nline4\n--\nline8\nmatch nine\nline10\nmatch eleven\nline12\n",
        ),
    ],
    ids=[
        "after",
        "before",
        "context",
        "numeric_shorthand",
        "context_with_line_numbers_uses_dash",
        "separator_between_distant_groups",
        "zero_context_still_separates_groups",
        "adjacent_groups_merge_without_separator",
        "before_two",
        "after_past_end",
        "before_past_start",
        "count_ignores_context",
        "filename_context_prefix",
        "invert_with_context",
    ],
)
def test_grep_prints_context(shell: ShellHarness, context_file: None, script: str, expected: str) -> None:
    """Check -A, -B, -C and the -- separator between groups"""
    run = shell.run(script)

    assert (run.stdout, run.exit_code) == (expected, 0)


def test_grep_context_separator_between_files(shell: ShellHarness, two_files: None) -> None:
    """Check that groups from different files are separated"""
    run = shell.run("grep -A 1 apple a.txt b.txt")

    assert run.stdout == "a.txt:apple\na.txt-banana\n--\nb.txt:apple tart\n"


def test_grep_recursive_without_a_path_searches_the_current_directory(shell: ShellHarness, two_files: None) -> None:
    """Check that -r alone walks . and labels files without a ./ prefix"""
    run = shell.run("grep -r cherry")

    assert run.stdout == "b.txt:cherry\n"


def test_grep_recursive_walks_nested_directories_with_the_path_prefix(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -R labels nested files with the directory as written and the relative path"""
    (tmp_path / "tree" / "inner").mkdir(parents=True)
    (tmp_path / "tree" / "top.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "tree" / "inner" / "deep.txt").write_text("needle\nhay\n", encoding="utf-8")

    run = shell.run("grep -Rn needle tree")

    assert run.stdout == "tree/inner/deep.txt:1:needle\ntree/top.txt:1:needle\n"


def test_grep_recursive_only_matching_prefixes_each_match(shell: ShellHarness, two_files: None) -> None:
    """Check that -ro combines the path label with each matched part"""
    run = shell.run("grep -ro 'app' .")

    assert run.stdout == "./a.txt:app\n./b.txt:app\n"
