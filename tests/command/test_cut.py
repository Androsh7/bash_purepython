"""Test the cut command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'a:b:c\\n' | cut -d : -f 2", "b\n"),
        ("printf 'a:b:c\\n' | cut -d : -f 1,3", "a:c\n"),
        ("printf 'a:b:c:d\\n' | cut -d : -f 2-", "b:c:d\n"),
        ("printf 'a:b:c\\n' | cut -d : -f -2", "a:b\n"),
        ("printf 'abcdef\\n' | cut -c 2-4", "bcd\n"),
        ("printf 'abcdef\\n' | cut -b 1,6", "af\n"),
        ("printf 'nodelim\\n' | cut -d : -f 1", "nodelim\n"),
        ("printf 'nodelim\\n' | cut -s -d : -f 1", ""),
    ],
    ids=[
        "field",
        "two_fields",
        "open_range",
        "leading_range",
        "characters",
        "bytes",
        "undelimited_kept",
        "undelimited_skipped",
    ],
)
def test_cut_selects_parts_of_each_line(shell: ShellHarness, script: str, expected: str) -> None:
    """Check field, character and byte selection"""
    assert shell.run(script).stdout == expected


def test_cut_without_a_selection_is_a_usage_error(shell: ShellHarness) -> None:
    """Check that cut with no list option exits two"""
    run = shell.run("printf 'a\\n' | cut")

    assert run.exit_code == 2
