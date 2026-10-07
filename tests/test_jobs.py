"""Test background jobs, the fake ps, kill and wait"""

# Standard libraries
import re

# Project libraries
from bash_purepython.shell_state import EXIT_CODE_KILLED
from tests.conftest import ShellHarness

PS_LINE_PATTERN = re.compile(r"^\s*(\d+) (\w)\s+(.*)$")


def parse_ps(output: str) -> list[tuple[int, str, str]]:
    """Return the pid, status and command of every job line in ps output

    Args:
        output: The text ps printed

    Returns:
        One tuple per job, header excluded
    """
    jobs: list[tuple[int, str, str]] = []
    for line in output.splitlines()[1:]:
        match = PS_LINE_PATTERN.match(line)
        assert match is not None, line
        jobs.append((int(match.group(1)), match.group(2), match.group(3)))
    return jobs


def test_background_job_runs_while_the_foreground_continues(shell: ShellHarness) -> None:
    """Check that a job's output arrives after the foreground command that followed it"""
    run = shell.run("{ sleep 0.05; echo late; } & echo first; wait")

    assert run.stdout == "first\nlate\n"


def test_ps_lists_a_running_job_with_its_pid(shell: ShellHarness) -> None:
    """Check that ps shows the job started with & as running under the pid in $!"""
    run = shell.run("sleep 1 & echo $!; ps; kill $!; wait")

    pid_line, ps_output = run.stdout.split("\n", 1)
    assert parse_ps(ps_output) == [(int(pid_line), "R", "sleep 1")]


def test_kill_marks_the_job_killed_and_wait_returns_its_code(shell: ShellHarness) -> None:
    """Check that a killed job shows as K and wait reports the killed exit code"""
    killed = shell.run("sleep 5 & kill $!; sleep 0.01; ps")
    waited = shell.run("wait $!; echo $?")

    assert parse_ps(killed.stdout)[0][1] == "K"
    assert waited.stdout == f"{EXIT_CODE_KILLED}\n"


def test_wait_reaps_finished_jobs(shell: ShellHarness) -> None:
    """Check that a job disappears from ps after wait"""
    run = shell.run("sleep 0.01 & wait; ps")

    assert parse_ps(run.stdout) == []


def test_wait_without_jobs_succeeds(shell: ShellHarness) -> None:
    """Check that wait with nothing running exits zero"""
    run = shell.run("wait")

    assert (run.stdout, run.exit_code) == ("", 0)


def test_kill_unknown_pid_fails(shell: ShellHarness) -> None:
    """Check that killing a pid that is not a job exits one with a message"""
    run = shell.run("kill 4242")

    assert run.exit_code == 1
    assert "4242" in run.stderr


def test_jobs_persist_across_runs_on_one_harness(shell: ShellHarness) -> None:
    """Check that a job started in one run is still listed and can be waited for in the next"""
    shell.run("sleep 0.05 &")

    later = shell.run("ps; wait; echo done")

    assert parse_ps(later.stdout.split("done")[0])[0][1] == "R"
    assert later.stdout.endswith("done\n")


def test_jobs_builtin_lists_the_running_job(shell: ShellHarness) -> None:
    """Check that jobs prints the bash-style line for a running job"""
    run = shell.run("sleep 1 & jobs; kill $!; wait")

    assert "Running" in run.stdout
    assert "sleep 1 &" in run.stdout


def test_job_exit_code_is_reported_by_wait(shell: ShellHarness) -> None:
    """Check that wait returns the job's own exit code"""
    run = shell.run("false & wait $!; echo $?")

    assert run.stdout == "1\n"


def test_two_jobs_interleave(shell: ShellHarness) -> None:
    """Check that two sleeping jobs finish in duration order, not start order"""
    run = shell.run("{ sleep 0.08; echo slow; } & { sleep 0.02; echo fast; } & wait")

    assert run.stdout == "fast\nslow\n"
