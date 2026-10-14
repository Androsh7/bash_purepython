"""Test the column command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.column import ColumnCommand, format_columns
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.registry import CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness], tmp_path: Path) -> ShellHarness:
    """Return a harness with column registered and a file of uneven fields"""
    (tmp_path / "fields.txt").write_text("name age city\nalice 30 london\nbob 5 rome\n", encoding="utf-8")
    (tmp_path / "csv.txt").write_text("name,age\nalice,30\n", encoding="utf-8")
    return make_shell(CommandRegistry([ColumnCommand(), PrintfCommand()]))


def test_column_table_aligns_fields(shell: ShellHarness) -> None:
    """Check that -t pads every column to its widest field with two spaces between"""
    run = shell.run("column -t fields.txt")

    assert run.stdout == "name   age  city\nalice  30   london\nbob    5    rome\n"


def test_column_table_with_separator_splits_on_it(shell: ShellHarness) -> None:
    """Check that -s names the characters fields are split on"""
    run = shell.run("column -t -s , csv.txt")

    assert run.stdout == "name   age\nalice  30\n"


def test_column_table_skips_blank_lines(shell: ShellHarness) -> None:
    """Check that empty input lines produce no rows"""
    run = shell.run("printf 'a b\\n\\nc d\\n' | column -t")

    assert run.stdout == "a  b\nc  d\n"


def test_column_table_leaves_a_short_row_unpadded(shell: ShellHarness) -> None:
    """Check that a row with fewer fields ends after its last field"""
    run = shell.run("printf 'a b c\\nd\\n' | column -t")

    assert run.stdout == "a  b  c\nd\n"


def test_column_fills_columns_down_then_across(shell: ShellHarness) -> None:
    """Check that without -t short items are laid out in columns ordered down each column first"""
    run = shell.run("printf 'a\\nb\\nc\\nd\\ne\\n' | column")

    assert run.stdout == "a  b  c  d  e\n"


def test_column_ignores_the_output_width_option(shell: ShellHarness) -> None:
    """Check that -c is accepted"""
    run = shell.run("printf 'a\\nb\\n' | column -c 40")

    assert (run.stdout, run.exit_code) == ("a  b\n", 0)


def test_column_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file is named with exit code one"""
    run = shell.run("column missing.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr


def test_format_columns_wraps_to_rows_when_items_exceed_the_width() -> None:
    """Check that items are ordered down the first column before the second"""
    assert format_columns(["aaa", "b", "c", "d", "e"], 16) == "aaa  c    e\nb    d\n"
