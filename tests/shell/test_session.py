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


def test_run_line_names_unsupported_descriptor_redirection(session: ShellSession) -> None:
    """Check that an unsupported descriptor form is refused by name rather than run as a command"""
    result = session.run_line("ls 3>out")

    assert result.exit_code == 2
    assert "file descriptor 3" in result.stderr


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


def test_run_line_rejects_adjacent_operators(session: ShellSession) -> None:
    """Check that ;; is a syntax error rather than a silent success"""
    session.run_line("false")

    result = session.run_line("false ;; echo $?")

    assert result.exit_code == 2
    assert "syntax error" in result.stderr


def test_run_line_expands_variables_per_pipeline(session: ShellSession) -> None:
    """Check that an export earlier on the line is visible to a later command"""
    result = session.run_line("export GREETING=hello; echo $GREETING")

    assert result.stdout == "hello\n"


def test_run_line_sees_a_directory_change_earlier_on_the_line(session: ShellSession, shell_home: Path) -> None:
    """Check that $PWD after cd on the same line names the new directory"""
    (shell_home / "sub").mkdir()

    result = session.run_line("cd sub; echo $PWD")

    assert Path(result.stdout.strip()) == shell_home / "sub"


def test_run_line_does_not_run_a_command_whose_redirect_fails(session: ShellSession, shell_home: Path) -> None:
    """Check that a bad redirect target stops the command before it has side effects"""
    (shell_home / "keep.txt").write_text("x")

    result = session.run_line("rm keep.txt > missing/log")

    assert result.exit_code == 1
    assert (shell_home / "keep.txt").exists()


def test_run_line_aborts_the_rest_of_the_line_on_interrupt(
    session: ShellSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that an interrupted command stops the list with exit code 130"""
    # Standard libraries
    import bash_purepython.sleep as sleep_module

    def interrupted() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(sleep_module, "main", interrupted)

    result = session.run_line("sleep 100; echo still-ran")

    assert result.exit_code == 130
    assert "still-ran" not in result.stdout


def test_run_line_reports_stderr_that_exceeds_the_limit(session: ShellSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that overflowing stderr is an error, not a silent truncation with exit 0"""
    monkeypatch.setattr(session_module, "OUTPUT_LIMIT_BYTES", 64)
    # Standard libraries
    import sys

    import bash_purepython.sleep as sleep_module

    def noisy() -> None:
        sys.stderr.write("e" * 200)

    monkeypatch.setattr(sleep_module, "main", noisy)

    result = session.run_line("sleep 1")

    assert result.exit_code == 1
    assert "error output exceeded" in result.stderr


def test_run_line_resolves_a_variable_in_a_host_call(shell_home: Path) -> None:
    """Check that a host command's arguments are expanded"""
    session = ShellSession(home=str(shell_home), host_commands=(HostCommand("vim", ""),), environment={"F": "a.txt"})

    result = session.run_line("vim $F")

    assert result.host_call is not None
    assert result.host_call.argv == ("vim", "a.txt")


def test_run_line_sends_stderr_to_its_file(session: ShellSession, shell_home: Path) -> None:
    """Check that 2> keeps the error off the screen and in the file"""
    result = session.run_line("cat missing.txt 2>err.txt")

    assert result.stderr == ""
    assert "missing.txt" in (shell_home / "err.txt").read_text()
    assert result.exit_code == 1


def test_run_line_appends_stderr_with_double_arrow(session: ShellSession, shell_home: Path) -> None:
    """Check that 2>> adds to the file instead of replacing it"""
    session.run_line("cat one.txt 2>err.txt")

    session.run_line("cat two.txt 2>>err.txt")

    text = (shell_home / "err.txt").read_text()
    assert "one.txt" in text
    assert "two.txt" in text


def test_run_line_joins_stderr_into_the_pipe(session: ShellSession) -> None:
    """Check that 2>&1 lets the next stage see the error text"""
    result = session.run_line("cat missing.txt 2>&1 | grep -c missing")

    assert result.stdout.strip() == "1"
    assert result.stderr == ""


def test_run_line_sends_both_streams_to_one_file(session: ShellSession, shell_home: Path) -> None:
    """Check that &> writes stdout and stderr into the same file"""
    session.run_line("echo fine; cat missing.txt &>all.txt")

    text = (shell_home / "all.txt").read_text()
    assert "missing.txt" in text


def test_run_line_reads_stdin_from_a_file(session: ShellSession, shell_home: Path) -> None:
    """Check that < feeds a file to a command that reads standard input"""
    (shell_home / "in.txt").write_bytes(b"abc\n")

    result = session.run_line("tr a-z A-Z <in.txt")

    assert result.stdout == "ABC\n"


def test_run_line_does_not_run_a_command_whose_input_is_missing(session: ShellSession, shell_home: Path) -> None:
    """Check that a missing input file is reported and the command is skipped"""
    (shell_home / "keep.txt").write_text("x")

    result = session.run_line("rm keep.txt <nothing.txt")

    assert result.exit_code == 1
    assert "nothing.txt" in result.stderr
    assert (shell_home / "keep.txt").exists()


def test_run_line_refuses_extra_redirects_on_a_host_command(shell_home: Path) -> None:
    """Check that a browser command may only redirect stdout"""
    session = ShellSession(home=str(shell_home), host_commands=(HostCommand("vim", ""),), environment={})

    result = session.run_line("vim a.txt 2>err.txt")

    assert result.exit_code == 2
    assert "browser commands" in result.stderr
    assert result.host_call is None


def test_run_line_keeps_stderr_on_the_pipe_when_joined_before_stdout_moves(
    session: ShellSession, shell_home: Path
) -> None:
    """Check that 2>&1 >out sends the error down the pipe and nothing into out"""
    result = session.run_line("cat missing.txt 2>&1 >out.txt | grep -c missing")

    assert result.stdout.strip() == "1"
    assert (shell_home / "out.txt").read_bytes() == b""


def test_run_line_shares_one_file_when_both_streams_name_it(session: ShellSession, shell_home: Path) -> None:
    """Check that >both 2>&1 does not let one stream overwrite the other"""
    result = session.run_line("which cd nothing >both.txt 2>&1")

    text = (shell_home / "both.txt").read_text()
    assert "shell builtin" in text
    assert "no nothing" in text
    assert result.stdout == ""
    assert result.stderr == ""


def test_run_line_removes_every_match_of_a_wildcard(session: ShellSession, shell_home: Path) -> None:
    """Check that rm * deletes the files in the directory"""
    for name in ("a.txt", "b.txt"):
        (shell_home / name).write_text("")

    result = session.run_line("rm *")

    assert result.exit_code == 0
    assert not list(shell_home.glob("*.txt"))


def test_run_line_does_not_expand_wildcards_in_a_redirect_target(session: ShellSession, shell_home: Path) -> None:
    """Check that > keeps a literal name even when it looks like a pattern"""
    (shell_home / "x.txt").write_text("")

    session.run_line("echo hi > [x].txt")

    assert (shell_home / "[x].txt").exists()
    assert (shell_home / "x.txt").read_text() == ""


def test_run_line_feeds_a_here_document_to_the_command(session: ShellSession) -> None:
    """Check that cat << EOF prints the lines between"""
    result = session.run_line("cat << EOF\nThis is line one\nThis is line two\nEOF")

    assert result.stdout == "This is line one\nThis is line two\n"
    assert result.exit_code == 0


def test_run_line_expands_variables_in_an_unquoted_here_document(session: ShellSession) -> None:
    """Check that $VAR expands in the body unless the delimiter was quoted"""
    session.run_line("export WHO=world")

    plain = session.run_line("cat << EOF\nhello $WHO\nEOF")
    quoted = session.run_line("cat << 'EOF'\nhello $WHO\nEOF")

    assert plain.stdout == "hello world\n"
    assert quoted.stdout == "hello $WHO\n"


def test_run_line_accepts_a_quoted_string_spanning_lines(session: ShellSession) -> None:
    """Check that a newline inside double quotes is part of the argument"""
    result = session.run_line('echo "first\nsecond"')

    assert result.stdout == "first\nsecond\n"


def test_run_line_joins_a_backslash_continued_line(session: ShellSession) -> None:
    """Check that a backslash before the newline continues the command"""
    result = session.run_line("echo one \\\ntwo")

    assert result.stdout == "one two\n"


def test_needs_more_recognises_unfinished_input(session: ShellSession) -> None:
    """Check that an open here-document or quote asks for more while complete lines do not"""
    assert session.needs_more("cat << EOF\nline")
    assert session.needs_more('echo "open')
    assert session.needs_more("echo one \\")
    assert not session.needs_more("cat << EOF\nline\nEOF")
    assert not session.needs_more("echo done")
    assert not session.needs_more("ls 3>out")


def test_run_line_refuses_a_here_document_on_a_host_command(shell_home: Path) -> None:
    """Check that a browser command cannot take a here-document"""
    session = ShellSession(home=str(shell_home), host_commands=(HostCommand("python", ""),), environment={})

    result = session.run_line("python << EOF\nprint(1)\nEOF")

    assert result.exit_code == 2
    assert "browser commands" in result.stderr


def test_run_line_keeps_a_here_document_when_a_redirect_follows_it(session: ShellSession, shell_home: Path) -> None:
    """Check that << survives a > given after it on the same command"""
    result = session.run_line("cat << 'EOF' > quoted.txt\nhi $WHO\nEOF")

    assert result.exit_code == 0
    assert (shell_home / "quoted.txt").read_text() == "hi $WHO\n"


def test_needs_more_sees_a_here_document_followed_by_a_redirect(session: ShellSession) -> None:
    """Check that a line ending in << EOF > file still waits for the body"""
    assert session.needs_more("cat << 'EOF' > quoted.txt")
