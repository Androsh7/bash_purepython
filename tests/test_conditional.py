"""Test the [[ ]] conditional command through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("a == a", 0),
        ("a = a", 0),
        ("a == b", 1),
        ("a != b", 0),
        ("abc == a*", 0),
        ("abc == a?c", 0),
        ("abc == [xa]bc", 0),
        ("abc == x*", 1),
        ('abc == "a*"', 1),
        ("abc == a'*'", 1),
        ("abc != x*", 0),
        ("b > a", 0),
        ("a > b", 1),
        ("a < b", 0),
    ],
    ids=[
        "equal",
        "single_equals",
        "different",
        "not_equal",
        "star_pattern",
        "question_pattern",
        "bracket_pattern",
        "pattern_mismatch",
        "double_quoted_pattern_is_literal",
        "single_quoted_star_is_literal",
        "not_matching_pattern",
        "sorts_after",
        "sorts_after_false",
        "sorts_before",
    ],
)
def test_conditional_compares_strings_and_patterns(
    shell: ShellHarness, expression: str, expected_exit_code: int
) -> None:
    """Check string equality, pattern matching on the right side, and ordering"""
    run = shell.run(f"[[ {expression} ]]")

    assert run.exit_code == expected_exit_code


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("abc =~ ^a.c$", 0),
        ("abc =~ ^a(b|x)c$", 0),
        ("abc =~ b", 0),
        ("abc =~ ^b", 1),
        ('a.c =~ "a.c"', 0),
        ('abc =~ "a.c"', 1),
    ],
    ids=["anchored", "group_with_alternatives", "anywhere", "anchored_mismatch", "quoted_literal", "quoted_dot"],
)
def test_conditional_matches_regular_expressions(shell: ShellHarness, expression: str, expected_exit_code: int) -> None:
    """Check that =~ searches with a regular expression whose quoted parts are literal"""
    run = shell.run(f"[[ {expression} ]]")

    assert run.exit_code == expected_exit_code


@pytest.mark.parametrize(
    ("script", "expected_exit_code"),
    [
        ("[[ 10 -gt 9 ]]", 0),
        ("[[ 2 -lt 1 ]]", 1),
        ("x=5; [[ x -eq 5 ]]", 0),
        ("x=5; [[ $x -eq 2+3 ]]", 0),
        ("[[ -1 -lt 0 ]]", 0),
    ],
    ids=["greater", "less_false", "bare_variable_name", "expression_operand", "negative"],
)
def test_conditional_compares_integers_arithmetically(
    shell: ShellHarness, script: str, expected_exit_code: int
) -> None:
    """Check that numeric operators evaluate their operands as arithmetic"""
    run = shell.run(script)

    assert run.exit_code == expected_exit_code


@pytest.mark.parametrize(
    ("expression", "expected_exit_code"),
    [
        ("a == a && b == b", 0),
        ("a == a && b == c", 1),
        ("a == b || b == b", 0),
        ("a == b || b == c", 1),
        ("! a == b", 0),
        ("! ( a == b || a == a )", 1),
        ("( a == b || a == a ) && c == c", 0),
    ],
    ids=["and", "and_false", "or", "or_false", "not", "negated_group", "group_then_and"],
)
def test_conditional_combines_expressions(shell: ShellHarness, expression: str, expected_exit_code: int) -> None:
    """Check &&, ||, negation and parentheses inside the brackets"""
    run = shell.run(f"[[ {expression} ]]")

    assert run.exit_code == expected_exit_code


def test_conditional_does_not_split_an_unquoted_variable(shell: ShellHarness) -> None:
    """Check that a value holding spaces is one operand without quotes"""
    run = shell.run('value="two words"; [[ $value == "two words" ]]')

    assert run.exit_code == 0


def test_conditional_does_not_expand_wildcards_into_file_names(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a star on the right is a pattern for the left operand, not a list of files"""
    (tmp_path / "anything.txt").write_text("x", encoding="utf-8")

    run = shell.run("[[ report.txt == *.txt ]]")

    assert run.exit_code == 0


def test_conditional_tests_strings_files_and_variables(shell: ShellHarness, tmp_path: Path) -> None:
    """Check the unary tests for empty strings, files, directories and set variables"""
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    run = shell.run(
        'set_name=1; [[ -n text && -z "" && -f file.txt && ! -d file.txt && -e . && -v set_name && ! -v unset_name ]]'
    )

    assert run.exit_code == 0


def test_conditional_skips_the_side_that_cannot_change_the_result(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a command substitution after a decided && or || does not run"""
    shell.run("[[ a == b && $(echo ran > and.txt) == x ]]; [[ a == a || $(echo ran > or.txt) == x ]]")

    assert not (tmp_path / "and.txt").exists()
    assert not (tmp_path / "or.txt").exists()


def test_conditional_drives_if_and_while(shell: ShellHarness) -> None:
    """Check that the command works as the condition of compound commands"""
    run = shell.run('n=3; while [[ $n -gt 0 ]]; do n=$((n-1)); done; if [[ $n -eq 0 && -z "" ]]; then echo done; fi')

    assert run.stdout == "done\n"


def test_conditional_operators_do_not_split_the_command_list(shell: ShellHarness) -> None:
    """Check that && inside the brackets belongs to the expression and && after them to the shell"""
    run = shell.run("[[ a == a && b == b ]] && echo both; [[ a == a && b == c ]] || echo not_both")

    assert run.stdout.split() == ["both", "not_both"]


def test_double_brackets_as_arguments_are_ordinary_words(shell: ShellHarness) -> None:
    """Check that [[ is only a command when it starts one"""
    run = shell.run("echo [[ plain ]]")

    assert run.stdout == "[[ plain ]]\n"


def test_unclosed_conditional_is_a_syntax_error(shell: ShellHarness) -> None:
    """Check that a missing closing bracket pair stops with a usage error"""
    run = shell.run("[[ a == a")

    assert run.exit_code == 2
    assert run.stderr != ""
