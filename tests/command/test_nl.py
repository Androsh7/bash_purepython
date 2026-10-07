"""Test the nl command through the shell"""

# Project libraries
from tests.conftest import ShellHarness


def test_nl_numbers_non_empty_lines_by_default(shell: ShellHarness) -> None:
    """Check that blank lines are padded but not numbered"""
    run = shell.run("printf 'a\\n\\nb\\n' | nl")

    assert run.stdout.splitlines() == ["     1\ta", "      \t", "     2\tb"]


def test_nl_options_change_numbering(shell: ShellHarness) -> None:
    """Check width, separator, increment and numbering every line"""
    run = shell.run("printf 'a\\n\\n' | nl -b a -w 2 -s ': ' -i 5")

    assert run.stdout == " 5: a\n10: \n"
