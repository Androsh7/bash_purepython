"""Test the sleep command through the shell"""

# Project libraries
from tests.conftest import ShellHarness


def test_sleep_returns_zero_after_the_duration(shell: ShellHarness) -> None:
    """Check that a short sleep succeeds silently"""
    run = shell.run("sleep 0.01; echo woke")

    assert (run.stdout, run.exit_code) == ("woke\n", 0)


def test_sleep_accepts_a_suffix(shell: ShellHarness) -> None:
    """Check that an s suffix is accepted"""
    run = shell.run("sleep 0.01s")

    assert run.exit_code == 0


def test_sleep_rejects_a_non_duration(shell: ShellHarness) -> None:
    """Check that a word that is not a duration is a usage error"""
    run = shell.run("sleep soon")

    assert run.exit_code == 2
    assert "soon" in run.stderr


def test_sleep_without_operand_is_a_usage_error(shell: ShellHarness) -> None:
    """Check that sleep with no arguments complains"""
    run = shell.run("sleep")

    assert run.exit_code == 2
