"""Test the uniq command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.uniq import UniqCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds uniq"""
    registry = CommandRegistry()
    registry.register(UniqCommand())
    return make_shell(registry)


def test_uniq_collapses_adjacent_duplicates_only(shell: ShellHarness) -> None:
    """Check that repeated neighbours collapse while a repeat further down stays"""
    run = shell.run("printf 'a\\na\\nb\\na\\n' | uniq")

    assert run.stdout == "a\nb\na\n"


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'a\\na\\nb\\n' | uniq -c", "      2 a\n      1 b\n"),
        ("printf 'a\\na\\nb\\n' | uniq -d", "a\n"),
        ("printf 'a\\na\\nb\\n' | uniq -u", "b\n"),
        ("printf 'a\\nA\\nb\\n' | uniq -i", "a\nb\n"),
        ("printf '1 x\\n2 x\\n3 y\\n' | uniq -f 1", "1 x\n3 y\n"),
        ("printf 'ax\\nbx\\ncy\\n' | uniq -s 1", "ax\ncy\n"),
    ],
    ids=["count", "repeated", "unique", "ignore_case", "skip_fields", "skip_chars"],
)
def test_uniq_option(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each filtering option"""
    assert shell.run(script).stdout == expected


def test_uniq_reads_a_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a named input file is read"""
    (tmp_path / "in.txt").write_text("x\nx\n", encoding="utf-8")

    run = shell.run("uniq in.txt")

    assert run.stdout == "x\n"


def test_uniq_writes_the_output_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a second operand receives the output instead of standard output"""
    (tmp_path / "in.txt").write_text("x\nx\ny\n", encoding="utf-8")

    run = shell.run("uniq in.txt out.txt")

    assert run.stdout == ""
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "x\ny\n"


def test_uniq_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing input fails with a message naming it"""
    run = shell.run("uniq missing.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr
