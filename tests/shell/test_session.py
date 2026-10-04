"""Tests for running whole command lines"""

# Standard libraries
from pathlib import Path

# Project libraries
from bash_purepython.shell.models import EXIT_CODE_COMMAND_NOT_FOUND, HostCall, Redirect
from bash_purepython.shell.session import ShellSession


def test_run_line_pipes_output_into_the_next_command(session: ShellSession) -> None:
    """Check that | feeds one command's stdout to the next"""
    result = session.run_line("echo abc | tr a b")

    assert result.stdout == "bbc\n"
    assert result.exit_code == 0


def test_run_line_honours_and_and_or_operators(session: ShellSession) -> None:
    """Check that && runs on success and || runs on failure"""
    result = session.run_line("echo a && false || echo b")

    assert result.stdout == "a\nb\n"
    assert result.exit_code == 0


def test_run_line_skips_the_and_branch_after_failure(session: ShellSession) -> None:
    """Check that a failed command stops the && chain"""
    result = session.run_line("false && echo never")

    assert result.stdout == ""
    assert result.exit_code == 1


def test_run_line_exposes_the_previous_exit_code_as_question_mark(session: ShellSession) -> None:
    """Check that $? on the next line is the last exit code"""
    session.run_line("false")

    result = session.run_line("echo $?")

    assert result.stdout == "1\n"


def test_run_line_returns_the_last_pipeline_status(session: ShellSession) -> None:
    """Check that grep finding nothing makes the line fail"""
    result = session.run_line("echo hi | grep x")

    assert result.exit_code == 1
    assert result.stdout == ""


def test_run_line_writes_redirected_output_to_a_file(session: ShellSession, shell_home: Path) -> None:
    """Check that > creates the file and >> appends to it"""
    session.run_line("echo one > out.txt")
    session.run_line("echo two >> out.txt")

    result = session.run_line("cat out.txt")

    assert (shell_home / "out.txt").read_text() == "one\ntwo\n"
    assert result.stdout == "one\ntwo\n"


def test_run_line_redirect_in_a_pipeline_passes_nothing_downstream(session: ShellSession, shell_home: Path) -> None:
    """Check that a redirected stage leaves the next stage with empty input"""
    result = session.run_line("echo hi > mid.txt | wc -c")

    assert (shell_home / "mid.txt").read_text() == "hi\n"
    assert result.stdout.strip() == "0"


def test_run_line_reports_a_missing_redirect_directory(session: ShellSession) -> None:
    """Check that a redirect into a missing directory fails"""
    result = session.run_line("echo hi > missing/out.txt")

    assert result.exit_code == 1
    assert "missing/out.txt" in result.stderr


def test_run_line_reports_an_unknown_command(session: ShellSession) -> None:
    """Check that an unknown name exits 127 with a message"""
    result = session.run_line("frobnicate now")

    assert result.exit_code == EXIT_CODE_COMMAND_NOT_FOUND
    assert "frobnicate" in result.stderr


def test_run_line_returns_a_host_call_for_a_lone_host_command(session: ShellSession) -> None:
    """Check that a host command alone on the line is handed back with its arguments"""
    result = session.run_line("vim notes.txt > log")

    assert result.host_call == HostCall(name="vim", argv=("vim", "notes.txt"), redirect=Redirect("log", append=False))
    assert result.stdout == ""


def test_run_line_rejects_a_host_command_inside_a_pipeline(session: ShellSession, shell_home: Path) -> None:
    """Check that a host command in a pipeline fails and nothing else on the line runs"""
    result = session.run_line("echo hi > touched.txt | vim")

    assert result.exit_code == 1
    assert "vim" in result.stderr
    assert result.host_call is None
    assert not (shell_home / "touched.txt").exists()


def test_run_line_rejects_a_host_command_inside_a_list(session: ShellSession) -> None:
    """Check that a host command joined with && is refused"""
    result = session.run_line("true && python")

    assert result.exit_code == 1
    assert result.host_call is None


def test_run_line_ignores_a_blank_line(session: ShellSession) -> None:
    """Check that whitespace runs nothing and is not remembered"""
    session.run_line("false")

    result = session.run_line("   ")

    assert result.exit_code == 1
    assert session.history == ("false",)


def test_run_line_reports_a_syntax_error(session: ShellSession) -> None:
    """Check that an unterminated quote exits two"""
    result = session.run_line("echo 'oops")

    assert result.exit_code == 2
    assert result.stderr


def test_run_line_keeps_command_errors_out_of_the_pipe(session: ShellSession) -> None:
    """Check that an error message goes to stderr instead of being counted downstream"""
    result = session.run_line("cat missing.txt | wc -l")

    assert result.stdout.strip() == "0"
    assert "missing.txt" in result.stderr


def test_set_last_exit_code_is_visible_as_question_mark(session: ShellSession) -> None:
    """Check that a host-reported exit code feeds $?"""
    session.set_last_exit_code(42)

    result = session.run_line("echo $?")

    assert result.stdout == "42\n"


def test_run_line_terminates_an_endless_pipeline_source(session: ShellSession) -> None:
    """Check that yes piped into head produces only the requested lines"""
    result = session.run_line("yes | head -3")

    assert result.stdout == "y\ny\ny\n"


def test_run_line_passes_binary_data_through_a_pipeline(session: ShellSession, shell_home: Path) -> None:
    """Check that compressed bytes survive a pipe"""
    (shell_home / "data.txt").write_text("hello " * 100)

    result = session.run_line("gzip -c data.txt | wc -c")

    assert int(result.stdout.strip()) > 0
    assert result.exit_code == 0


def test_run_line_records_history_up_to_the_limit(shell_home: Path) -> None:
    """Check that seeding more history than the limit keeps only the newest"""
    session = ShellSession(
        home=str(shell_home),
        host_commands=(),
        environment={},
        history=[f"echo {number}" for number in range(600)],
    )

    assert len(session.history) == 500
    assert session.history[-1] == "echo 599"


def test_run_line_result_carries_the_environment(session: ShellSession) -> None:
    """Check that the environment the shell was seeded with comes back in every result"""
    result = session.run_line("true")

    assert result.environment["USER"] == "guest"
