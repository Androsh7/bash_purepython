"""Test the ls command through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.ls import format_size
from tests.conftest import ShellHarness


@pytest.fixture
def listing_tree(tmp_path: Path) -> None:
    """Build a directory with visible, hidden and nested entries"""
    (tmp_path / "b.txt").write_text("bb", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / ".hidden").write_text("h", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("c", encoding="utf-8")


def test_ls_lists_visible_entries_sorted(shell: ShellHarness, listing_tree: None) -> None:
    """Check that hidden entries are skipped and names are sorted"""
    run = shell.run("ls")

    assert run.stdout.split() == ["a.txt", "b.txt", "sub"]


def test_ls_all_includes_hidden_entries(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -a shows dot files"""
    run = shell.run("ls -a")

    assert ".hidden" in run.stdout.split()


def test_ls_long_shows_type_and_size(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -l prints one line per entry with its kind and size"""
    run = shell.run("ls -l")

    assert "f 2 b.txt" in run.stdout.splitlines()
    assert any(line.startswith("d ") and line.endswith(" sub") for line in run.stdout.splitlines())


def test_ls_recursive_lists_descendants(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -R includes nested files with their relative paths"""
    run = shell.run("ls -R")

    assert "sub/c.txt" in run.stdout.split()


def test_ls_missing_path_fails(shell: ShellHarness) -> None:
    """Check that a missing path is reported with exit code one"""
    run = shell.run("ls nowhere")

    assert run.exit_code == 1
    assert "nowhere" in run.stderr


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0"),
        (1023, "1023"),
        (1024, "1.0K"),
        (1536, "1.5K"),
        (10240, "10K"),
        (1048576, "1.0M"),
        (12 * 1048576, "12M"),
    ],
    ids=[
        "zero",
        "under_a_kilobyte",
        "one_kilobyte",
        "one_and_a_half",
        "ten_kilobytes",
        "one_megabyte",
        "twelve_megabytes",
    ],
)
def test_format_size_matches_gnu_short_form(size: int, expected: str) -> None:
    """Check the human-readable size format"""
    assert format_size(size) == expected
