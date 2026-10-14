"""Test the du command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.du import DuCommand
from bash_purepython.command.ls import allocated_blocks
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness

LARGE_FILE_SIZE_BYTES = 3000


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds du"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), DuCommand()]))


@pytest.fixture
def usage_tree(tmp_path: Path) -> None:
    """Build a directory holding a file and a nested directory with another file"""
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "a.txt").write_bytes(b"a" * 6)
    (tmp_path / "project" / "sub").mkdir()
    (tmp_path / "project" / "sub" / "b.txt").write_bytes(b"b" * 5)


def usage_by_name(stdout: str) -> dict[str, int]:
    """Return each reported entry's size keyed by its name

    Args:
        stdout: The output of du

    Returns:
        The sizes
    """
    sizes = {}
    for line in stdout.splitlines():
        size, name = line.split("\t")
        sizes[name] = int(size)
    return sizes


def test_du_bytes_of_a_file_are_its_exact_size(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -b on a file prints the apparent size"""
    (tmp_path / "a.txt").write_bytes(b"a" * 6)

    run = shell.run("du -b a.txt")

    assert (run.stdout, run.exit_code) == ("6\ta.txt\n", 0)


def test_du_default_counts_one_kilobyte_blocks(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a file is reported in the blocks it occupies rather than its byte size"""
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * LARGE_FILE_SIZE_BYTES)

    run = shell.run("du big.bin")

    assert run.stdout == f"{allocated_blocks(path.lstat())}\tbig.bin\n"


def test_du_lists_directories_deepest_first(shell: ShellHarness, usage_tree: None) -> None:
    """Check that every directory is reported, each after its children, and no files without -a"""
    run = shell.run("du -b project")

    assert [line.split("\t")[1] for line in run.stdout.splitlines()] == ["project/sub", "project"]


def test_du_all_includes_files(shell: ShellHarness, usage_tree: None) -> None:
    """Check that -a reports files too, before the directory holding them"""
    run = shell.run("du -ab project")

    names = [line.split("\t")[1] for line in run.stdout.splitlines()]
    assert names == ["project/a.txt", "project/sub/b.txt", "project/sub", "project"]
    sizes = usage_by_name(run.stdout)
    assert sizes["project/a.txt"] == 6
    assert sizes["project/sub/b.txt"] == 5


def test_du_directory_totals_include_everything_below(shell: ShellHarness, usage_tree: None) -> None:
    """Check that a directory's size is at least the sum of its files"""
    run = shell.run("du -ab project")

    sizes = usage_by_name(run.stdout)
    assert sizes["project/sub"] >= sizes["project/sub/b.txt"]
    assert sizes["project"] >= sizes["project/a.txt"] + sizes["project/sub"]


def test_du_summarize_prints_one_line_per_argument(shell: ShellHarness, usage_tree: None) -> None:
    """Check that -s reports only the arguments themselves"""
    run = shell.run("du -sb project")

    assert [line.split("\t")[1] for line in run.stdout.splitlines()] == ["project"]


def test_du_max_depth_limits_the_listing(shell: ShellHarness, usage_tree: None) -> None:
    """Check that -d 0 reports only the top level"""
    run = shell.run("du -d 0 project")

    assert [line.split("\t")[1] for line in run.stdout.splitlines()] == ["project"]


def test_du_human_readable_uses_units(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -h prints a size with a unit letter"""
    (tmp_path / "big.bin").write_bytes(b"x" * LARGE_FILE_SIZE_BYTES)

    run = shell.run("du -hb big.bin")

    assert run.stdout == "3.0K\tbig.bin\n"


def test_du_grand_total(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -c adds a total line summing the arguments"""
    (tmp_path / "a.txt").write_bytes(b"a" * 6)
    (tmp_path / "b.txt").write_bytes(b"b" * 4)

    run = shell.run("du -cb a.txt b.txt")

    assert run.stdout.splitlines()[-1] == "10\ttotal"


def test_du_reports_a_missing_path(shell: ShellHarness) -> None:
    """Check that a missing path is reported with exit code one"""
    run = shell.run("du missing")

    assert run.exit_code == 1
    assert "cannot access 'missing'" in run.stderr
