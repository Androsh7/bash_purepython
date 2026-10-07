"""Test the find command through the shell"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.fixture
def tree(tmp_path: Path) -> None:
    """Build a small tree with files at several depths"""
    (tmp_path / "root" / "sub").mkdir(parents=True)
    (tmp_path / "root" / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "root" / "sub" / "b.TXT").write_text("b", encoding="utf-8")
    (tmp_path / "root" / "sub" / "c.log").write_text("c", encoding="utf-8")


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("find root", {"root", "root/a.txt", "root/sub", "root/sub/b.TXT", "root/sub/c.log"}),
        ("find root -name '*.txt'", {"root/a.txt"}),
        ("find root -iname '*.txt'", {"root/a.txt", "root/sub/b.TXT"}),
        ("find root -type d", {"root", "root/sub"}),
        ("find root -type f -maxdepth 1", {"root/a.txt"}),
        ("find root -mindepth 2", {"root/sub/b.TXT", "root/sub/c.log"}),
    ],
    ids=["everything", "name", "iname", "directories", "maxdepth", "mindepth"],
)
def test_find_filters_paths(shell: ShellHarness, tree: None, script: str, expected: set[str]) -> None:
    """Check each filter against the tree"""
    run = shell.run(script)

    assert set(run.stdout.splitlines()) == expected


def test_find_default_root_is_the_current_directory(shell: ShellHarness, tree: None) -> None:
    """Check that find without a root lists from dot"""
    run = shell.run("cd root; find -name a.txt")

    assert run.stdout == "./a.txt\n"


def test_find_missing_root_fails(shell: ShellHarness) -> None:
    """Check that a missing root is reported with exit code one"""
    run = shell.run("find nowhere")

    assert (run.stdout, run.exit_code) == ("", 1)
    assert "nowhere" in run.stderr
