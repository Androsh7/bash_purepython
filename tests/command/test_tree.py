"""Test the tree command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.tree import TreeCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds tree"""
    registry = CommandRegistry()
    registry.register(TreeCommand())
    return make_shell(registry)


@pytest.fixture
def populated_directory(tmp_path: Path) -> Path:
    """Build a small tree with a nested directory, a hidden file and plain files"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "util").mkdir()
    (tmp_path / "src" / "util" / "helper.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / ".hidden").write_text("", encoding="utf-8")
    return tmp_path


def test_tree_draws_connectors_and_summary(shell: ShellHarness, populated_directory: Path) -> None:
    """Check the GNU tree layout for a nested directory"""
    run = shell.run("tree")

    assert run.stdout == (
        ".\n├── README.md\n└── src\n    ├── main.py\n    └── util\n        └── helper.py\n\n2 directories, 3 files\n"
    )


def test_tree_all_includes_hidden_entries(shell: ShellHarness, populated_directory: Path) -> None:
    """Check that -a lists entries whose name starts with a dot"""
    run = shell.run("tree -a -L 1")

    assert run.stdout.splitlines()[1] == "├── .hidden"


def test_tree_directories_only(shell: ShellHarness, populated_directory: Path) -> None:
    """Check that -d omits files and counts only directories in the summary"""
    run = shell.run("tree -d")

    assert run.stdout == ".\n└── src\n    └── util\n\n2 directories\n"


def test_tree_level_limits_depth(shell: ShellHarness, populated_directory: Path) -> None:
    """Check that -L stops descending below the given depth while still counting the directories seen"""
    run = shell.run("tree -L 1")

    assert run.stdout == ".\n├── README.md\n└── src\n\n1 directory, 1 file\n"


def test_tree_lists_a_named_directory(shell: ShellHarness, populated_directory: Path) -> None:
    """Check that the argument is printed as the root label"""
    run = shell.run("tree src/util")

    assert run.stdout == "src/util\n└── helper.py\n\n0 directories, 1 file\n"


def test_tree_reports_a_missing_directory(shell: ShellHarness) -> None:
    """Check that a missing path is marked as unopenable and the exit code is one"""
    run = shell.run("tree missing")

    assert run.exit_code == 1
    assert run.stdout.splitlines()[0] == "missing  [error opening dir]"


def test_tree_rejects_a_zero_level(shell: ShellHarness) -> None:
    """Check that -L 0 fails"""
    run = shell.run("tree -L 0")

    assert run.exit_code == 1
    assert run.stderr != ""
