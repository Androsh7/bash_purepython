"""Test the rev command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_rev_reverses_piped_lines(shell: ShellHarness) -> None:
    """Check that each line of standard input is reversed"""
    run = shell.run("printf 'abc\\nde\\n' | rev")

    assert run.stdout == "cba\ned\n"


def test_rev_reads_files_and_reports_missing_ones(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that files are reversed in order and a missing file fails without stopping the others"""
    (tmp_path / "a.txt").write_text("xy\n", encoding="utf-8")

    run = shell.run("rev missing a.txt")

    assert (run.stdout, run.exit_code) == ("yx\n", 1)
    assert "missing" in run.stderr
