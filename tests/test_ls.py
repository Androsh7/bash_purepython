"""Tests for the ls command"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.ls import format_size
from bash_purepython.shell.runner import run_command


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [
        (0, "0"),
        (512, "512"),
        (1024, "1.0K"),
        (1025, "1.1K"),
        (1536, "1.5K"),
        (10239, "10K"),
        (10 * 1024, "10K"),
        (1048575, "1.0M"),
        (12 * 1024 * 1024, "12M"),
        (2**60, "1.0E"),
    ],
    ids=[
        "zero",
        "bytes",
        "one-kilobyte",
        "rounds-up",
        "fraction",
        "just-under-ten",
        "ten-kilobytes",
        "just-under-a-megabyte",
        "megabytes",
        "exabyte",
    ],
)
def test_format_size_uses_the_ls_short_form(size_bytes: int, expected: str) -> None:
    """Check that sizes read the way ls -lh prints them"""
    assert format_size(size_bytes) == expected


def test_ls_dash_h_means_human_readable_sizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that -lh prints a unit suffix instead of the help text"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "big.bin").write_bytes(bytes(3 * 1024))

    output = run_command("ls", ["ls", "-lh"], b"")

    assert output.exit_code == 0
    assert "3.0K big.bin" in output.stdout.decode()


def test_ls_long_help_still_prints_usage() -> None:
    """Check that --help survives the -h change"""
    output = run_command("ls", ["ls", "--help"], b"")

    assert output.exit_code == 0
    assert b"usage: ls" in output.stdout


def test_ls_recursive_walks_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that -r lists files below the top level on every supported Python"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.txt").write_text("")

    output = run_command("ls", ["ls", "-r"], b"")

    assert "deep.txt" in output.stdout.decode()
