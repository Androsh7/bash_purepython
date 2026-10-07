"""Test the printf command through the shell"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'plain\\n'", "plain\n"),
        ("printf '%s %s\\n' a b", "a b\n"),
        ("printf '%s\\n' a b c", "a\nb\nc\n"),
        ("printf '%s-%s\\n' a b c", "a-b\nc-\n"),
        ("printf '%d\\n' 42", "42\n"),
        ("printf '%5d|%-5d|%05d\\n' 42 42 42", "   42|42   |00042\n"),
        ("printf '%x %X %o\\n' 255 255 8", "ff FF 10\n"),
        ("printf '%.2f\\n' 3.14159", "3.14\n"),
        ("printf '%s\\n'", "\n"),
        ("printf '%d\\n'", "0\n"),
        ("printf 'no newline'", "no newline"),
        ("printf '%%\\n'", "%\n"),
        ("printf 'tab\\there\\n'", "tab\there\n"),
        ("printf '%b\\n' 'esc\\tin arg'", "esc\tin arg\n"),
        ("printf '%s\\n' 'no\\tesc in s'", "no\\tesc in s\n"),
        ("printf '%c\\n' hello", "h\n"),
        ("printf '%5s|%-5s|\\n' ab ab", "   ab|ab   |\n"),
        ("printf '%.2s\\n' abcdef", "ab\n"),
        ("printf '%d %s\\n' 1 a 2 b", "1 a\n2 b\n"),
        ("printf -- '-dash\\n'", "-dash\n"),
        ("printf '\\101\\x42\\n'", "AB\n"),
        ("printf '%*d|\\n' 4 7", "   7|\n"),
        ("printf '%q\\n' 'a b'", "a\\ b\n"),
        ("printf '%i\\n' 0x10", "16\n"),
        ("printf '%d\\n' \"'A\"", "65\n"),
    ],
    ids=[
        "plain",
        "two_strings",
        "format_reused_per_argument",
        "missing_argument_is_empty",
        "integer",
        "width_and_flags",
        "hex_and_octal",
        "float_precision",
        "no_argument_string",
        "no_argument_integer",
        "no_trailing_newline",
        "literal_percent",
        "escape_in_format",
        "escape_in_b_argument",
        "no_escape_in_s_argument",
        "first_character",
        "string_width",
        "string_precision",
        "two_directives_reused",
        "double_dash",
        "octal_and_hex_escapes",
        "star_width",
        "shell_quoting",
        "hex_integer_argument",
        "character_code_argument",
    ],
)
def test_printf_formats_arguments(shell: ShellHarness, script: str, expected: str) -> None:
    """Check printf output for each directive and escape form"""
    assert shell.run(script).stdout == expected


def test_printf_invalid_number_reports_and_fails(shell: ShellHarness) -> None:
    """Check that a non-numeric argument to %d prints zero, complains, and exits one"""
    run = shell.run("printf '%d\\n' notnum")

    assert (run.stdout, run.exit_code) == ("0\n", 1)
    assert "notnum" in run.stderr


def test_printf_without_format_is_a_usage_error(shell: ShellHarness) -> None:
    """Check that printf with no arguments exits two"""
    run = shell.run("printf")

    assert run.exit_code == 2
    assert run.stderr != ""
