"""Test the diff command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.diff import DiffCommand
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.registry import CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness], tmp_path: Path) -> ShellHarness:
    """Return a harness with diff registered and files that differ in known ways"""
    (tmp_path / "a").write_text("a\n", encoding="utf-8")
    (tmp_path / "b").write_text("b\n", encoding="utf-8")
    (tmp_path / "same").write_text("a\n", encoding="utf-8")
    (tmp_path / "upper").write_text("A\n", encoding="utf-8")
    (tmp_path / "old").write_text("one\ntwo\nthree\nfour\nfive\nsix\nseven\n", encoding="utf-8")
    (tmp_path / "new").write_text("one\ntwo\n3\nfour\nfive\nsix\nseven\neight\n", encoding="utf-8")
    (tmp_path / "nonewline").write_text("a", encoding="utf-8")
    return make_shell(CommandRegistry([DiffCommand(), PrintfCommand()]))


def test_diff_normal_change(shell: ShellHarness) -> None:
    """Check the normal format for one changed line"""
    run = shell.run("diff a b")

    assert (run.stdout, run.exit_code) == ("1c1\n< a\n---\n> b\n", 1)


def test_diff_normal_change_and_addition(shell: ShellHarness) -> None:
    """Check the normal format hunks for a change followed by an appended line"""
    run = shell.run("diff old new")

    assert run.stdout == "3c3\n< three\n---\n> 3\n7a8\n> eight\n"


def test_diff_normal_deletion(shell: ShellHarness) -> None:
    """Check the normal format for lines missing from the second file"""
    run = shell.run("diff new old")

    assert run.stdout == "3c3\n< 3\n---\n> three\n8d7\n< eight\n"


def test_diff_unified(shell: ShellHarness) -> None:
    """Check the unified headers, hunk ranges and context"""
    run = shell.run("diff -u old new")

    assert run.stdout == (
        "--- old\n+++ new\n@@ -1,7 +1,8 @@\n one\n two\n-three\n+3\n four\n five\n six\n seven\n+eight\n"
    )


def test_diff_unified_single_line_files(shell: ShellHarness) -> None:
    """Check that a one-line range is written without a length"""
    run = shell.run("diff -u a b")

    assert run.stdout == "--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b\n"


def test_diff_same_files_print_nothing_and_exit_zero(shell: ShellHarness) -> None:
    """Check that identical files are silent"""
    run = shell.run("diff a same")

    assert (run.stdout, run.exit_code) == ("", 0)


def test_diff_brief_reports_differing_files(shell: ShellHarness) -> None:
    """Check the -q one-line report"""
    run = shell.run("diff -q a b")

    assert (run.stdout, run.exit_code) == ("Files a and b differ\n", 1)


def test_diff_brief_is_silent_for_same_files(shell: ShellHarness) -> None:
    """Check that -q says nothing when the files match"""
    run = shell.run("diff -q a same")

    assert (run.stdout, run.exit_code) == ("", 0)


def test_diff_report_identical_files(shell: ShellHarness) -> None:
    """Check the -s report"""
    run = shell.run("diff -s a same")

    assert (run.stdout, run.exit_code) == ("Files a and same are identical\n", 0)


def test_diff_ignore_case(shell: ShellHarness) -> None:
    """Check that -i treats lines differing only in case as equal"""
    run = shell.run("diff -i a upper")

    assert (run.stdout, run.exit_code) == ("", 0)


def test_diff_missing_file_is_trouble(shell: ShellHarness) -> None:
    """Check that a missing file is named and the exit code is two"""
    run = shell.run("diff a missing")

    assert (run.stdout, run.stderr, run.exit_code) == ("", "diff: missing: No such file or directory\n", 2)


def test_diff_reads_standard_input_for_dash(shell: ShellHarness) -> None:
    """Check that - compares against piped text"""
    run = shell.run("printf 'b\\n' | diff a -")

    assert run.stdout == "1c1\n< a\n---\n> b\n"


def test_diff_marks_a_missing_final_newline(shell: ShellHarness) -> None:
    """Check the marker printed after a last line without a newline"""
    run = shell.run("diff a nonewline")

    assert run.stdout == "1c1\n< a\n---\n> a\n\\ No newline at end of file\n"


def test_diff_requires_two_files(shell: ShellHarness) -> None:
    """Check that one operand is a usage error"""
    run = shell.run("diff a")

    assert run.exit_code == 2
