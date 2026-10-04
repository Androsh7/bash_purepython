"""Tests for running whole command lines"""

# Standard libraries
import os
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell import session as session_module
from bash_purepython.shell.models import EXIT_CODE_COMMAND_NOT_FOUND, HostCall, HostCommand, Redirect
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


def test_run_line_reports_a_stage_that_exceeds_the_pipe_limit(
    session: ShellSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that filling the pipe buffer is an error, not a silent truncation"""
    monkeypatch.setattr(session_module, "OUTPUT_LIMIT_BYTES", 1 << 16)

    result = session.run_line("yes")

    assert result.exit_code == 1
    assert "output exceeded" in result.stderr


def test_run_line_still_feeds_a_truncated_stage_downstream(
    session: ShellSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that head gets its lines from a producer that hit the pipe limit"""
    monkeypatch.setattr(session_module, "OUTPUT_LIMIT_BYTES", 1 << 16)

    result = session.run_line("yes | head -3")

    assert result.stdout == "y\ny\ny\n"
    assert "output exceeded" in result.stderr


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


def test_run_line_resolves_question_mark_per_pipeline(session: ShellSession) -> None:
    """Check that $? on the same line sees the command just before it"""
    result = session.run_line("false; echo $?; true; echo $?")

    assert result.stdout == "1\n0\n"


def test_run_line_treats_a_line_that_expands_to_nothing_as_a_no_op(session: ShellSession) -> None:
    """Check that an unset variable alone runs nothing and succeeds"""
    session.run_line("false")

    result = session.run_line("$UNSET_VARIABLE")

    assert result.exit_code == 0
    assert result.stderr == ""


def test_run_line_names_unsupported_stderr_redirection(session: ShellSession) -> None:
    """Check that 2> is refused with a message about stderr rather than a wrong command"""
    result = session.run_line("ls 2>/dev/null")

    assert result.exit_code == 2
    assert "stderr redirection" in result.stderr


def test_run_line_streams_output_to_the_sink_as_it_is_written(shell_home: Path) -> None:
    """Check that with a sink the result carries no text and the sink gets every chunk in order"""
    received: list[tuple[str, str]] = []
    session = ShellSession(
        home=str(shell_home),
        host_commands=(),
        environment={},
        output_sink=lambda kind, text: received.append((kind, text)),
    )

    result = session.run_line("echo one; cat missing.txt; echo two")

    assert result.stdout == ""
    assert result.stderr == ""
    kinds_in_order = [kind for index, (kind, _) in enumerate(received) if index == 0 or received[index - 1][0] != kind]
    assert kinds_in_order == ["stdout", "stderr", "stdout"]
    assert "".join(text for kind, text in received if kind == "stdout") == "one\ntwo\n"
    assert "missing.txt" in "".join(text for kind, text in received if kind == "stderr")


def test_run_line_sends_shell_errors_to_the_sink(shell_home: Path) -> None:
    """Check that a syntax error reaches the sink on stderr when one is set"""
    received: list[tuple[str, str]] = []
    session = ShellSession(
        home=str(shell_home),
        host_commands=(),
        environment={},
        output_sink=lambda kind, text: received.append((kind, text)),
    )

    result = session.run_line("echo 'open")

    assert result.stderr == ""
    assert received[0][0] == "stderr"
    assert "unterminated" in received[0][1]


def test_run_line_only_sends_the_last_stage_to_the_sink(shell_home: Path) -> None:
    """Check that an intermediate stage's output feeds the pipe, not the sink"""
    received: list[str] = []
    session = ShellSession(
        home=str(shell_home), host_commands=(), environment={}, output_sink=lambda _kind, text: received.append(text)
    )

    session.run_line("echo abc | tr a b")

    assert "".join(received) == "bbc\n"


def test_run_line_writes_a_redirect_without_touching_the_sink(shell_home: Path) -> None:
    """Check that a redirected command's output lands only in its file"""
    received: list[str] = []
    session = ShellSession(
        home=str(shell_home), host_commands=(), environment={}, output_sink=lambda _kind, text: received.append(text)
    )

    session.run_line("echo saved > out.txt")

    assert received == []
    assert (shell_home / "out.txt").read_text() == "saved\n"


def test_run_line_result_environment_holds_only_seeded_and_exported_variables(shell_home: Path) -> None:
    """Check that process-level variables and PWD do not leak into the result"""
    session = ShellSession(home=str(shell_home), host_commands=(), environment={"USER": "guest"})
    os.environ["LEAKED_PROCESS_VARIABLE"] = "1"

    session.run_line("export KEPT=yes")
    result = session.run_line("true")

    assert result.environment == {"KEPT": "yes", "USER": "guest"}


def test_run_line_uses_an_exported_home_for_tilde_and_cd(session: ShellSession, shell_home: Path) -> None:
    """Check that changing HOME moves where ~ and a bare cd go"""
    (shell_home / "other").mkdir()
    session.run_line(f"export HOME={shell_home.as_posix()}/other")

    tilde = session.run_line("echo ~")
    session.run_line("cd")

    assert Path(tilde.stdout.strip()) == shell_home / "other"
    assert Path(session.run_line("pwd").stdout.strip()) == shell_home / "other"


def test_run_line_resolves_question_mark_in_a_host_call(shell_home: Path) -> None:
    """Check that a host command's arguments see the last exit code"""
    session = ShellSession(home=str(shell_home), host_commands=(HostCommand("vim", ""),), environment={})
    session.run_line("false")

    result = session.run_line("vim $?")

    assert result.host_call is not None
    assert result.host_call.argv == ("vim", "1")


def test_run_line_skips_an_empty_command_inside_a_list(session: ShellSession) -> None:
    """Check that an unset variable between operators runs nothing and resets the status"""
    result = session.run_line("false; $UNSET_VARIABLE; echo $?")

    assert result.stdout == "0\n"
    assert result.stderr == ""
