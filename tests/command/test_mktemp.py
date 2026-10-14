"""Test the mktemp command through the shell"""

# Standard libraries
import re
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.mktemp import MktempCommand
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness

DEFAULT_NAME_PATTERN = re.compile(r"^tmp\.[A-Za-z0-9]{10}$")


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds mktemp"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), MktempCommand()]))


def test_mktemp_creates_a_file_under_the_given_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -p creates an empty file with the default template and prints its path"""
    run = shell.run("mktemp -p .")

    printed = run.stdout.rstrip("\n")
    assert run.exit_code == 0
    assert printed.startswith("./")
    assert DEFAULT_NAME_PATTERN.match(printed[2:])
    assert (tmp_path / printed[2:]).is_file()


def test_mktemp_uses_the_tmpdir_variable(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that TMPDIR decides where a bare template goes"""
    run = shell.run("TMPDIR=scratch; mktemp")

    printed = run.stdout.rstrip("\n")
    assert printed.startswith("scratch/")
    assert (tmp_path / printed).is_file()


def test_mktemp_creates_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -d creates a directory instead of a file"""
    run = shell.run("mktemp -d -p .")

    printed = run.stdout.rstrip("\n")
    assert (tmp_path / printed[2:]).is_dir()


def test_mktemp_fills_a_custom_template(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the trailing X's of a template are replaced and the prefix kept"""
    run = shell.run("mktemp -p . build.XXXXXX")

    printed = run.stdout.rstrip("\n")
    assert printed.startswith("./build.")
    assert len(printed) == len("./build.XXXXXX")
    assert "X" * 6 not in printed
    assert (tmp_path / printed[2:]).is_file()


def test_mktemp_template_with_a_slash_is_relative_to_the_current_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a template holding a path separator is used as a path rather than placed under /tmp"""
    (tmp_path / "work").mkdir()

    run = shell.run("mktemp work/job.XXXX")

    printed = run.stdout.rstrip("\n")
    assert printed.startswith("work/job.")
    assert (tmp_path / printed).is_file()


def test_mktemp_produces_distinct_names(shell: ShellHarness) -> None:
    """Check that two calls do not collide"""
    run = shell.run("mktemp -p .; mktemp -p .")

    first, second = run.stdout.splitlines()
    assert first != second


def test_mktemp_rejects_a_template_with_too_few_placeholders(shell: ShellHarness) -> None:
    """Check that fewer than three X's is an error"""
    run = shell.run("mktemp -p . short.XX")

    assert run.exit_code == 1
    assert "too few X's" in run.stderr
