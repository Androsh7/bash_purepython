"""Test the tr command through the shell"""

# Standard libraries
from collections.abc import Callable

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.tr import TrCommand, expand_set
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds tr"""
    registry = CommandRegistry()
    registry.register(TrCommand())
    return make_shell(registry)


@pytest.mark.parametrize(
    ("specification", "expected"),
    [
        ("a-e", "abcde"),
        ("[:digit:]", "0123456789"),
        ("[:upper:]", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        ("\\n\\t\\\\", "\n\t\\"),
        ("a\\-z", "a-z"),
        ("\\101", "A"),
        ("x[:lower:]y", "xabcdefghijklmnopqrstuvwxyzy"),
    ],
    ids=["range", "digit_class", "upper_class", "escapes", "escaped_dash", "octal", "class_in_the_middle"],
)
def test_expand_set(specification: str, expected: str) -> None:
    """Check each piece of set syntax"""
    assert expand_set(specification) == expected


def test_expand_set_rejects_a_reversed_range() -> None:
    """Check that a range whose end comes before its start is refused"""
    with pytest.raises(ValueError, match="reverse"):
        expand_set("z-a")


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo hello | tr a-z A-Z", "HELLO\n"),
        ("echo hello | tr '[:lower:]' '[:upper:]'", "HELLO\n"),
        ("echo hello | tr -d l", "heo\n"),
        ("echo 'a   b' | tr -s ' '", "a b\n"),
        ("echo 'a1b2' | tr -cd '[:digit:]\\n'", "12\n"),
        ("echo 'a1b2' | tr -c '[:digit:]\\n' X", "X1X2\n"),
        ("echo abc | tr abc xy", "xyy\n"),
        ("echo 'aabbcc' | tr -s ab x", "xcc\n"),
        ("printf 'a b\\n' | tr ' ' '\\n'", "a\nb\n"),
        ("echo abc | tr -t abc x", "xbc\n"),
    ],
    ids=[
        "ranges",
        "classes",
        "delete",
        "squeeze",
        "complement_delete",
        "complement_translate",
        "set2_padded_with_last",
        "translate_then_squeeze",
        "newline_escape",
        "truncate_set1",
    ],
)
def test_tr_transforms_input(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each translation mode"""
    assert shell.run(script).stdout == expected


def test_tr_squeezes_across_lines(shell: ShellHarness) -> None:
    """Check that a run spanning a line boundary is squeezed to one newline"""
    run = shell.run("printf 'a\\n\\n\\nb\\n' | tr -s '\\n'")

    assert run.stdout == "a\nb\n"


def test_tr_reports_a_missing_second_set(shell: ShellHarness) -> None:
    """Check that translating with one set fails with exit code one"""
    run = shell.run("echo a | tr a")

    assert run.exit_code == 1
    assert "missing operand" in run.stderr


def test_tr_reports_an_unknown_class(shell: ShellHarness) -> None:
    """Check that an unknown character class fails with exit code one"""
    run = shell.run("echo a | tr '[:nope:]' x")

    assert run.exit_code == 1
    assert "nope" in run.stderr


def test_tr_stops_an_endless_producer(shell: ShellHarness) -> None:
    """Check that tr streams, so a reader that stops early ends the pipeline"""
    run = shell.run("yes | tr y n | head -n 2")

    assert run.stdout == "n\nn\n"
