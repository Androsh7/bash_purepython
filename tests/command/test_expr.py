"""Test the expr command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.expr import ExprCommand
from bash_purepython.command.registry import CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness with expr registered"""
    return make_shell(CommandRegistry([ExprCommand()]))


@pytest.mark.parametrize(
    ("script", "expected_stdout", "expected_exit_code"),
    [
        ("expr 1 + 1", "2\n", 0),
        ("expr 2 + 3 \\* 4", "14\n", 0),
        ("expr \\( 2 + 3 \\) \\* 4", "20\n", 0),
        ("expr 7 / 2", "3\n", 0),
        ("expr -7 / 2", "-3\n", 0),
        ("expr 7 % 3", "1\n", 0),
        ("expr -7 % 3", "-1\n", 0),
        ("expr 5 - 5", "0\n", 1),
        ("expr 3 '>' 2", "1\n", 0),
        ("expr 10 '<' 9", "0\n", 1),
        ("expr 10 '>=' 10", "1\n", 0),
        ("expr 10 '<=' 9", "0\n", 1),
        ("expr abc = abc", "1\n", 0),
        ("expr abc != abc", "0\n", 1),
        ("expr 10 '<' 9x", "1\n", 0),
        ("expr 0 '|' 5", "5\n", 0),
        ("expr 3 '|' 5", "3\n", 0),
        ("expr 0 '|' 0", "0\n", 1),
        ("expr 3 '&' 5", "3\n", 0),
        ("expr 3 '&' 0", "0\n", 1),
        ("expr abc : 'a.c'", "3\n", 0),
        ("expr abc : 'b'", "0\n", 1),
        ("expr abc : 'a\\(.\\)c'", "b\n", 0),
        ("expr abc : 'x\\(.\\)'", "\n", 1),
        ("expr match abc 'ab'", "2\n", 0),
        ("expr length hello", "5\n", 0),
        ("expr substr hello 2 3", "ell\n", 0),
        ("expr substr hello 0 3", "\n", 1),
        ("expr substr hello 4 10", "lo\n", 0),
        ("expr index hello lo", "3\n", 0),
        ("expr index hello z", "0\n", 1),
        ("expr + length", "length\n", 0),
        ("expr 1 + 2 \\* 3 - 4", "3\n", 0),
    ],
    ids=[
        "addition",
        "precedence",
        "parentheses",
        "division_truncates",
        "negative_division_truncates_toward_zero",
        "modulo",
        "negative_modulo",
        "zero_exits_one",
        "greater",
        "less_false",
        "greater_or_equal",
        "less_or_equal_false",
        "string_equal",
        "string_not_equal",
        "string_comparison_when_not_both_integers",
        "or_returns_right",
        "or_returns_left",
        "or_both_null",
        "and_returns_left",
        "and_with_null",
        "match_length",
        "match_anchored_at_start",
        "match_group",
        "match_group_no_match",
        "match_keyword",
        "length",
        "substr",
        "substr_bad_position",
        "substr_past_end",
        "index",
        "index_not_found",
        "plus_quotes_keyword",
        "mixed_precedence",
    ],
)
def test_expr_evaluates(shell: ShellHarness, script: str, expected_stdout: str, expected_exit_code: int) -> None:
    """Check arithmetic, comparisons, logic and string functions with their exit codes"""
    run = shell.run(script)

    assert (run.stdout, run.stderr, run.exit_code) == (expected_stdout, "", expected_exit_code)


@pytest.mark.parametrize(
    ("script", "expected_stderr"),
    [
        ("expr 1 +", "expr: syntax error: missing argument after '+'\n"),
        ("expr 1 2", "expr: syntax error: unexpected argument '2'\n"),
        ("expr \\( 1", "expr: syntax error: expecting ')'\n"),
        ("expr 1 + a", "expr: non-integer argument\n"),
        ("expr 1 / 0", "expr: division by zero\n"),
        ("expr", "expr: missing operand\n"),
    ],
    ids=["missing_argument", "extra_argument", "unclosed_parenthesis", "non_integer", "division_by_zero", "no_operand"],
)
def test_expr_reports_errors_and_exits_two(shell: ShellHarness, script: str, expected_stderr: str) -> None:
    """Check that a malformed expression is reported on stderr with exit code two"""
    run = shell.run(script)

    assert (run.stdout, run.stderr, run.exit_code) == ("", expected_stderr, 2)


def test_expr_result_is_usable_in_a_variable(shell: ShellHarness) -> None:
    """Check that command substitution of expr gives the bare value"""
    run = shell.run("count=$(expr 2 + 2); expr $count \\* 2")

    assert run.stdout == "8\n"
