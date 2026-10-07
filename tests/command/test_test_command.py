"""Test the test command and its bracket spelling through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.fixture
def paths(tmp_path: Path) -> None:
    """Build a file with content, an empty file and a directory"""
    (tmp_path / "full.txt").write_text("content", encoding="utf-8")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    (tmp_path / "folder").mkdir()


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("a = a", 0),
        ("a = b", 1),
        ("a == a", 0),
        ("a != b", 0),
        ("a != a", 1),
        ('-z ""', 0),
        ("-z text", 1),
        ("-n text", 0),
        ('-n ""', 1),
        ("word", 0),
        ('""', 1),
        ("", 1),
    ],
    ids=[
        "equal",
        "not_equal_is_false",
        "double_equals",
        "differs",
        "differs_is_false",
        "empty_is_zero_length",
        "text_is_not_zero_length",
        "text_is_nonempty",
        "empty_is_not_nonempty",
        "bare_word_is_true",
        "empty_string_is_false",
        "no_expression_is_false",
    ],
)
def test_bracket_compares_strings(shell: ShellHarness, expression: str, expected_exit_code: int) -> None:
    """Check the string comparisons and the empty and non-empty tests"""
    run = shell.run(f"[ {expression} ]")

    assert run.exit_code == expected_exit_code


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("1 -eq 1", 0),
        ("1 -ne 1", 1),
        ("1 -lt 2", 0),
        ("2 -lt 2", 1),
        ("2 -le 2", 0),
        ("3 -gt 2", 0),
        ("2 -ge 3", 1),
        ("-1 -lt 0", 0),
        ("10 -gt 9", 0),
    ],
    ids=["eq", "ne", "lt", "lt_equal_is_false", "le", "gt", "ge", "negative", "numeric_not_text_order"],
)
def test_bracket_compares_integers(shell: ShellHarness, expression: str, expected_exit_code: int) -> None:
    """Check the numeric comparisons, which order by value and not as text"""
    run = shell.run(f"[ {expression} ]")

    assert run.exit_code == expected_exit_code


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("-e full.txt", 0),
        ("-e missing", 1),
        ("-f full.txt", 0),
        ("-f folder", 1),
        ("-d folder", 0),
        ("-d full.txt", 1),
        ("-s full.txt", 0),
        ("-s empty.txt", 1),
        ("! -e missing", 0),
    ],
    ids=[
        "exists",
        "missing",
        "regular_file",
        "directory_is_not_a_file",
        "directory",
        "file_is_not_a_directory",
        "has_content",
        "empty_has_no_content",
        "negated",
    ],
)
def test_bracket_tests_files(shell: ShellHarness, paths: None, expression: str, expected_exit_code: int) -> None:
    """Check the file tests against paths relative to the shell's directory"""
    run = shell.run(f"[ {expression} ]")

    assert run.exit_code == expected_exit_code


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("1 -eq 1 -a 2 -eq 2", 0),
        ("1 -eq 1 -a 2 -eq 3", 1),
        ("1 -eq 2 -o 2 -eq 2", 0),
        ("1 -eq 2 -o 2 -eq 3", 1),
        ("! a = b", 0),
        ("! a = a", 1),
        ("'(' a = a ')'", 0),
        ("! '(' a = b -o a = a ')'", 1),
    ],
    ids=["and", "and_false", "or", "or_false", "not", "not_false", "group", "negated_group"],
)
def test_bracket_combines_expressions(shell: ShellHarness, expression: str, expected_exit_code: int) -> None:
    """Check negation, -a, -o and parenthesised groups"""
    run = shell.run(f"[ {expression} ]")

    assert run.exit_code == expected_exit_code


def test_test_spelling_needs_no_closing_bracket(shell: ShellHarness) -> None:
    """Check that the test command evaluates the same expressions without a bracket"""
    run = shell.run("test 3 -ge 3 && test -n word && echo both")

    assert run.stdout == "both\n"


@pytest.mark.parametrize(
    "script",
    ["[ 1 -eq 1", "[ 1 -lt word ]", "[ 1 -eq 1 extra ]"],
    ids=["missing_closing_bracket", "non_integer_operand", "too_many_arguments"],
)
def test_malformed_expression_exits_two_with_a_message(shell: ShellHarness, script: str) -> None:
    """Check that an expression that cannot be evaluated is a usage error"""
    run = shell.run(script)

    assert run.exit_code == 2
    assert run.stderr != ""


def test_bracket_drives_a_while_loop(shell: ShellHarness) -> None:
    """Check that a counting loop conditioned on a bracket test runs the expected number of times"""
    run = shell.run("i=0; while [ $i -lt 3 ]; do echo $i; i=$((i+1)); done")

    assert run.stdout.split() == ["0", "1", "2"]
