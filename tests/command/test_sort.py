"""Test the sort command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.sort import SortCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds sort"""
    registry = CommandRegistry()
    registry.register(SortCommand())
    return make_shell(registry)


def test_sort_orders_lines_by_byte_value(shell: ShellHarness) -> None:
    """Check that lines are ordered as plain strings, upper case before lower"""
    run = shell.run("printf 'banana\\napple\\nCherry\\n' | sort")

    assert run.stdout == "Cherry\napple\nbanana\n"


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'b\\na\\nc\\n' | sort -r", "c\nb\na\n"),
        ("printf 'b\\na\\nb\\na\\n' | sort -u", "a\nb\n"),
        ("printf '10\\n9\\n100\\n' | sort -n", "9\n10\n100\n"),
        ("printf 'x\\n2\\n-1\\n' | sort -n", "-1\nx\n2\n"),
        ("printf 'b\\nA\\nc\\n' | sort -f", "A\nb\nc\n"),
        ("printf '1G\\n500M\\n2K\\n3\\n' | sort -h", "3\n2K\n500M\n1G\n"),
        ("printf '  b\\na\\n' | sort -b", "a\n  b\n"),
    ],
    ids=["reverse", "unique", "numeric", "numeric_treats_text_as_zero", "fold_case", "human", "ignore_blanks"],
)
def test_sort_option(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each ordering option"""
    assert shell.run(script).stdout == expected


def test_sort_by_key_field(shell: ShellHarness) -> None:
    """Check that -k sorts on the given whitespace-separated field"""
    run = shell.run("printf 'x 3\\ny 1\\nz 2\\n' | sort -k 2")

    assert run.stdout == "y 1\nz 2\nx 3\n"


def test_sort_by_key_field_with_separator(shell: ShellHarness) -> None:
    """Check that -t changes the field separator and a key modifier applies numeric comparison"""
    run = shell.run("printf 'a:10\\nb:9\\nc:100\\n' | sort -t : -k 2n")

    assert run.stdout == "b:9\na:10\nc:100\n"


def test_sort_key_without_end_runs_to_end_of_line(shell: ShellHarness) -> None:
    """Check that -k 2 compares from field two to the end of the line, as GNU sort does"""
    run = shell.run("printf 'q b z\\nq b a\\n' | sort -k 2")

    assert run.stdout == "q b a\nq b z\n"


def test_sort_reads_files(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the lines of every named file are merged"""
    (tmp_path / "a.txt").write_text("c\na\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    run = shell.run("sort a.txt b.txt")

    assert run.stdout == "a\nb\nc\n"


def test_sort_adds_a_missing_final_newline(shell: ShellHarness) -> None:
    """Check that a last line without a newline is still terminated"""
    run = shell.run("printf 'b\\na' | sort")

    assert run.stdout == "a\nb\n"


def test_sort_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file fails with a message naming it"""
    run = shell.run("sort missing.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr


def test_sort_rejects_a_bad_key(shell: ShellHarness) -> None:
    """Check that a key naming field zero is a usage error"""
    run = shell.run("echo a | sort -k 0")

    assert run.exit_code == 2
    assert run.stderr != ""


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("printf 'b 2\\na 10\\nc 1\\n' | sort -k2,2nr", "a 10\nb 2\nc 1\n"),
        ("printf 'b 2\\na 10\\nc 1\\n' | sort -k2nr", "a 10\nb 2\nc 1\n"),
        ("printf 'x b\\ny a\\nz c\\n' | sort -k2r", "z c\nx b\ny a\n"),
        ("printf '1 b\\n1 a\\n2 c\\n' | sort -k1,1nr -k2,2", "2 c\n1 a\n1 b\n"),
    ],
    ids=["numeric_reverse_bounded", "numeric_reverse_open", "text_reverse", "mixed_directions"],
)
def test_sort_key_reverse_modifier(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that the r modifier reverses one key without touching the others"""
    run = shell.run(script)

    assert run.stdout == expected
