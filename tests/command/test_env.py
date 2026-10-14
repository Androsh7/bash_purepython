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


def test_env_ignore_environment_starts_empty(shell: ShellHarness) -> None:
    """Check that -i prints nothing from the shell's variables"""
    run = shell.run("export A=1; env -i")

    assert (run.stdout, run.exit_code) == ("", 0)


def test_env_ignore_environment_keeps_given_assignments(shell: ShellHarness) -> None:
    """Check that -i followed by assignments prints only those"""
    run = shell.run("export A=1; env -i B=2")

    assert run.stdout == "B=2\n"


def test_env_unset_removes_a_variable(shell: ShellHarness) -> None:
    """Check that -u drops the named variable from the listing"""
    run = shell.run("export A=1 B=2; env -u A")

    assert "A=1" not in run.stdout.splitlines()
    assert "B=2" in run.stdout.splitlines()
