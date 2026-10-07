"""Test the cp command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_cp_copies_a_file_to_a_new_name(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the copy has the same content and the source remains"""
    (tmp_path / "a.txt").write_text("content\n", encoding="utf-8")

    run = shell.run("cp a.txt b.txt")

    assert run.exit_code == 0
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "content\n"
    assert (tmp_path / "a.txt").exists()


def test_cp_copies_into_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that several sources land inside a destination directory"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "dest").mkdir()

    run = shell.run("cp a.txt b.txt dest")

    assert run.exit_code == 0
    assert sorted(entry.name for entry in (tmp_path / "dest").iterdir()) == ["a.txt", "b.txt"]


def test_cp_needs_recursive_for_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a directory is skipped without -r and copied with it"""
    (tmp_path / "src" / "inner").mkdir(parents=True)

    without = shell.run("cp src copy1")
    with_flag = shell.run("cp -r src copy2")

    assert (without.exit_code, (tmp_path / "copy1").exists()) == (1, False)
    assert (with_flag.exit_code, (tmp_path / "copy2" / "inner").is_dir()) == (0, True)


def test_cp_no_clobber_keeps_the_existing_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -n leaves an existing destination alone"""
    (tmp_path / "a.txt").write_text("new", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old", encoding="utf-8")

    shell.run("cp -n a.txt b.txt")

    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "old"


def test_cp_missing_source_fails(shell: ShellHarness) -> None:
    """Check that a missing source is reported with exit code one"""
    run = shell.run("cp nothing somewhere")

    assert run.exit_code == 1
    assert "nothing" in run.stderr
