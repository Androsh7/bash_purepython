"""Test the gzip and gunzip commands through the shell"""

# Standard libraries
import gzip
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_gzip_compresses_a_file_in_place(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the file is replaced by its gzip form"""
    (tmp_path / "data.txt").write_bytes(b"hello\n")

    run = shell.run("gzip data.txt")

    assert run.exit_code == 0
    assert not (tmp_path / "data.txt").exists()
    assert gzip.decompress((tmp_path / "data.txt.gz").read_bytes()) == b"hello\n"


def test_gunzip_restores_the_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that gunzip undoes gzip"""
    (tmp_path / "data.txt").write_text("round trip\n", encoding="utf-8")

    shell.run("gzip data.txt; gunzip data.txt.gz")

    assert (tmp_path / "data.txt").read_text(encoding="utf-8") == "round trip\n"
    assert not (tmp_path / "data.txt.gz").exists()


def test_gzip_keep_leaves_the_source(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -k keeps the input file"""
    (tmp_path / "data.txt").write_text("keep\n", encoding="utf-8")

    shell.run("gzip -k data.txt")

    assert (tmp_path / "data.txt").exists()
    assert (tmp_path / "data.txt.gz").exists()


def test_gzip_through_a_pipeline(shell: ShellHarness) -> None:
    """Check that bytes flow from gzip to gunzip and back to text"""
    run = shell.run("printf 'piped\\n' | gzip | gunzip")

    assert run.stdout == "piped\n"


def test_gzip_refuses_to_overwrite_without_force(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an existing output is kept unless -f is given"""
    (tmp_path / "data.txt").write_text("new\n", encoding="utf-8")
    (tmp_path / "data.txt.gz").write_bytes(b"old")

    run = shell.run("gzip data.txt")

    assert run.exit_code == 1
    assert (tmp_path / "data.txt.gz").read_bytes() == b"old"


def test_gunzip_reports_a_file_that_is_not_gzip(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that decompressing plain text fails with exit code one"""
    (tmp_path / "plain.gz").write_text("not gzip\n", encoding="utf-8")

    run = shell.run("gunzip plain.gz")

    assert run.exit_code == 1
    assert "plain.gz" in run.stderr
