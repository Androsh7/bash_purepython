"""Test arithmetic expansion and the arithmetic command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo $((2+3*4)) $(( (2+3)*4 ))", "14 20"),
        ("echo $((7/2)) $((-7/2)) $((7%3)) $((-7%3))", "3 -3 1 -1"),
        ("echo $((2**10)) $((2**3**2)) $((-2**2))", "1024 512 4"),
        ("echo $((1<<4)) $((256>>2)) $((6&3)) $((6|3)) $((6^3)) $((~5))", "16 64 2 7 5 -6"),
        ("echo $((5>3)) $((5==3)) $((5!=3)) $((3<=3)) $((!5)) $((!0))", "1 0 1 1 0 1"),
        ("echo $((1&&0)) $((1||0)) $((1?10:20)) $((0?10:20))", "0 1 10 20"),
        ("echo $((0x1f)) $((010)) $((2#101)) $((16#ff))", "31 8 5 255"),
        ("echo $((1+1, 2+2))", "4"),
        ("echo $((missing+1)) $(( ))", "1 0"),
    ],
    ids=[
        "precedence",
        "division_truncates_toward_zero",
        "power_is_right_associative",
        "bitwise",
        "comparison_and_not",
        "logical_and_conditional",
        "number_bases",
        "comma",
        "unset_and_empty_are_zero",
    ],
)
def test_arithmetic_expansion_evaluates_operators(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that an expression between $(( and )) is replaced by its value"""
    run = shell.run(script)

    assert run.stdout.split() == expected.split()


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("x=5; echo $((x++)) $x", "5 6"),
        ("x=5; echo $((++x)) $x", "6 6"),
        ("x=5; echo $((x--)) $((--x)) $x", "5 3 3"),
        ("x=5; echo $((x+=10)) $((x*=2)) $((x%=7)) $x", "15 30 2 2"),
        ("echo $((y=4)) $y", "4 4"),
        ("a=3; b=4; echo $(($a*$b)) $((a*b)) $(( $(echo 6) * 7 ))", "12 12 42"),
        ("x=3; y=x; echo $((y+1))", "4"),
    ],
    ids=[
        "post_increment",
        "pre_increment",
        "decrement",
        "compound_assignment",
        "assignment_creates_variable",
        "dollar_names_and_substitution",
        "variable_holding_a_name",
    ],
)
def test_arithmetic_expansion_reads_and_assigns_variables(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that variables are read by name and that assignments persist in the shell"""
    run = shell.run(script)

    assert run.stdout.split() == expected.split()


def test_operand_that_is_not_needed_has_no_side_effect(shell: ShellHarness) -> None:
    """Check that the untaken side of &&, || and ?: assigns nothing and cannot divide by zero"""
    run = shell.run("x=1; echo $((0&&(x=99))) $((1||(x=99))) $((1?5:(x=99))) $((0&&1/0)) $x")

    assert run.stdout.split() == ["0", "1", "5", "0", "1"]


def test_division_by_zero_is_an_error(shell: ShellHarness) -> None:
    """Check that dividing by zero prints nothing for the command and reports failure"""
    run = shell.run("echo $((1/0))")

    assert (run.stdout, run.exit_code) == ("", 1)
    assert run.stderr != ""


def test_dollar_paren_holding_a_subshell_is_still_a_command_substitution(shell: ShellHarness) -> None:
    """Check that a substitution whose command starts with a subshell is not taken for arithmetic"""
    run = shell.run("echo $( (echo inner) )")

    assert run.stdout == "inner\n"


@pytest.mark.parametrize(
    ("script", "expected_exit_code"),
    [("((5>3))", 0), ("((5<3))", 1), ("((0))", 1), ("((2-1))", 0)],
    ids=["true_comparison", "false_comparison", "zero", "nonzero"],
)
def test_arithmetic_command_succeeds_when_the_value_is_nonzero(
    shell: ShellHarness, script: str, expected_exit_code: int
) -> None:
    """Check that (( )) exits zero for a nonzero value and one for zero"""
    run = shell.run(script)

    assert run.exit_code == expected_exit_code


def test_arithmetic_command_assigns_in_the_current_shell(shell: ShellHarness) -> None:
    """Check that a loop counter kept with (( )) is seen by the commands around it"""
    run = shell.run("i=0; while ((i<3)); do echo $i; ((i++)); done; echo end $i")

    assert run.stdout.split() == ["0", "1", "2", "end", "3"]


def test_spaced_parentheses_are_nested_subshells_not_arithmetic(shell: ShellHarness) -> None:
    """Check that ( ( command ) ) still runs the command"""
    run = shell.run("( ( echo nested ) )")

    assert run.stdout == "nested\n"
