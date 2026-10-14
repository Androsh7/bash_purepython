"""Test the chmod command through the shell"""

# Standard libraries
import stat
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.chmod import ChmodCommand, apply_mode
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds chmod"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), ChmodCommand()]))


def is_owner_writable(path: Path) -> bool:
    """Return whether the owner write bit is set

    Args:
        path: The file

    Returns:
        True when the owner may write
    """
    return bool(stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR)


@pytest.mark.parametrize(
    ("mode_text", "current_mode", "expected"),
    [
        ("755", 0o644, 0o755),
        ("0644", 0o777, 0o644),
        ("u+x", 0o644, 0o744),
        ("go-w", 0o666, 0o644),
        ("a=r", 0o777, 0o444),
        ("+x", 0o644, 0o755),
        ("+w", 0o444, 0o644),
        ("u=rwx,g=rx,o=", 0o000, 0o750),
        ("a+X", 0o644, 0o644),
        ("a+X", 0o744, 0o755),
        ("u+s", 0o755, 0o4755),
    ],
    ids=[
        "octal",
        "octal with leading zero",
        "user execute",
        "group other minus write",
        "all equals read",
        "execute under umask",
        "write under umask",
        "several clauses",
        "conditional execute without any",
        "conditional execute with one",
        "setuid",
    ],
)
def test_apply_mode_computes_the_new_bits(mode_text: str, current_mode: int, expected: int) -> None:
    """Check that octal and symbolic modes produce the bits GNU chmod would set on a file"""
    assert apply_mode(mode_text, current_mode, False) == expected


def test_apply_mode_conditional_execute_applies_to_directories() -> None:
    """Check that X adds execute to a directory without any execute bit"""
    assert apply_mode("a+X", 0o644, True) == 0o755


@pytest.mark.parametrize(
    "mode_text",
    ["rwx", "u+q", "9", "u+x,", ""],
    ids=["no operator", "bad letter", "bad digit", "empty clause", "empty"],
)
def test_apply_mode_rejects_an_invalid_mode(mode_text: str) -> None:
    """Check that malformed modes produce None"""
    assert apply_mode(mode_text, 0o644, False) is None


def test_chmod_octal_removes_write_permission(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an octal mode without the owner write bit makes the file read-only"""
    path = tmp_path / "a.txt"
    path.write_bytes(b"a")

    run = shell.run("chmod 444 a.txt")

    assert run.exit_code == 0
    assert not is_owner_writable(path)


def test_chmod_symbolic_restores_write_permission(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that u+w makes a read-only file writable again"""
    path = tmp_path / "a.txt"
    path.write_bytes(b"a")
    shell.run("chmod 444 a.txt")

    run = shell.run("chmod u+w a.txt")

    assert run.exit_code == 0
    assert is_owner_writable(path)


def test_chmod_recursive_reaches_nested_files(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -R applies the mode below a directory"""
    (tmp_path / "dir" / "sub").mkdir(parents=True)
    nested = tmp_path / "dir" / "sub" / "a.txt"
    nested.write_bytes(b"a")

    shell.run("chmod -R a-w dir")

    assert not is_owner_writable(nested)
    shell.run("chmod -R u+w dir")


def test_chmod_reports_a_missing_file(shell: ShellHarness) -> None:
    """Check that a missing file is reported with exit code one"""
    run = shell.run("chmod 644 missing.txt")

    assert run.exit_code == 1
    assert "cannot access 'missing.txt'" in run.stderr


def test_chmod_reports_an_invalid_mode(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a malformed mode is rejected before any file is touched"""
    (tmp_path / "a.txt").write_bytes(b"a")

    run = shell.run("chmod rwx a.txt")

    assert run.exit_code == 1
    assert "invalid mode" in run.stderr
