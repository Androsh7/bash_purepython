"""Test the md5sum, sha1sum, sha256sum and sha512sum commands through the shell"""

# Standard libraries
import hashlib
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.hashes import Md5sumCommand, Sha1sumCommand, Sha256sumCommand, Sha512sumCommand
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness

HELLO_SHA256 = "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds the four checksum commands"""
    commands = [command_class() for command_class in COMMAND_CLASSES]
    commands.extend([Md5sumCommand(), Sha1sumCommand(), Sha256sumCommand(), Sha512sumCommand()])
    return make_shell(CommandRegistry(commands))


def test_sha256sum_prints_the_digest_and_name_of_a_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the output is the GNU ``<hex>  <name>`` line"""
    (tmp_path / "a.txt").write_bytes(b"hello\n")

    run = shell.run("sha256sum a.txt")

    assert (run.stdout, run.exit_code) == (f"{HELLO_SHA256}  a.txt\n", 0)


def test_sha256sum_names_standard_input_with_a_dash(shell: ShellHarness) -> None:
    """Check that piped input is hashed and labelled -"""
    run = shell.run("echo hello | sha256sum")

    assert run.stdout == f"{HELLO_SHA256}  -\n"


@pytest.mark.parametrize(
    ("command_name", "algorithm"),
    [("md5sum", "md5"), ("sha1sum", "sha1"), ("sha256sum", "sha256"), ("sha512sum", "sha512")],
    ids=["md5", "sha1", "sha256", "sha512"],
)
def test_each_command_uses_its_own_algorithm(
    shell: ShellHarness, tmp_path: Path, command_name: str, algorithm: str
) -> None:
    """Check that every checksum command prints the digest of its algorithm"""
    (tmp_path / "a.txt").write_bytes(b"payload")

    run = shell.run(f"{command_name} a.txt")

    assert run.stdout == f"{hashlib.new(algorithm, b'payload').hexdigest()}  a.txt\n"


def test_sha256sum_hashes_several_files_in_order(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that one line is printed per file in the order given"""
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "b.txt").write_bytes(b"b")

    run = shell.run("sha256sum b.txt a.txt")

    assert [line.split("  ")[1] for line in run.stdout.splitlines()] == ["b.txt", "a.txt"]


def test_sha256sum_check_verifies_a_checksum_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -c reports OK for a matching file and FAILED for a changed one"""
    (tmp_path / "a.txt").write_bytes(b"hello\n")
    (tmp_path / "b.txt").write_bytes(b"hello\n")
    shell.run("sha256sum a.txt b.txt > sums.txt")
    (tmp_path / "b.txt").write_bytes(b"changed\n")

    run = shell.run("sha256sum -c sums.txt")

    assert run.stdout == "a.txt: OK\nb.txt: FAILED\n"
    assert run.exit_code == 1


def test_sha256sum_reports_a_missing_file_and_continues(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a missing file is reported and the others are still hashed"""
    (tmp_path / "a.txt").write_bytes(b"hello\n")

    run = shell.run("sha256sum missing.txt a.txt")

    assert run.exit_code == 1
    assert "missing.txt" in run.stderr
    assert run.stdout == f"{HELLO_SHA256}  a.txt\n"
