"""Test the env command through the shell"""

# Project libraries
from tests.conftest import ShellHarness


def test_env_lists_shell_variables(shell: ShellHarness) -> None:
    """Check that exported variables appear as name=value lines"""
    run = shell.run("export A=1 B=two; env")

    assert set(run.stdout.splitlines()) >= {"A=1", "B=two"}


def test_env_null_separates_entries(shell: ShellHarness) -> None:
    """Check that -0 ends entries with NUL"""
    run = shell.run("export A=1; env -0")

    assert "A=1\0" in run.stdout
