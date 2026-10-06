"""Test the parse, plan, execute loop end to end"""

# Standard libraries
from collections.abc import Callable, Generator
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.execute_command import Executor
from bash_purepython.shell_state import (
    EXIT_CODE_COMMAND_NOT_FOUND,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_USAGE_ERROR,
    ShellState,
)
from tests.conftest import ShellHarness

MAXIMUM_LINES_PULLED_FOR_THREE = 8


class CountingYesCommand(Command):
    """Stream endless lines while recording how many were pulled"""

    name = "countingyes"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def __init__(self):
        """Start with nothing pulled"""
        self.pulled = 0
        self.closed = False

    def lines(self) -> Generator[str, None, int]:
        """Yield lines until closed

        Returns:
            Zero, which an endless producer never reaches
        """
        try:
            while True:
                self.pulled += 1
                yield "y\n"
        finally:
            self.closed = True
        return EXIT_CODE_SUCCESS

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return the counting stream

        Args:
            invocation: Ignored

        Returns:
            The stream
        """
        return CommandResult(stdout=self.lines(), exit_code=EXIT_CODE_SUCCESS)


class UpperCommand(Command):
    """Upper-case standard input, accepting only whole text"""

    name = "upper"
    input_kinds = frozenset({InputKind.TEXT})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return the input upper-cased

        Args:
            invocation: The call, whose stdin is text

        Returns:
            The upper-cased text
        """
        return CommandResult(stdout=(invocation.stdin or "").upper(), exit_code=EXIT_CODE_SUCCESS)


class BytesCommand(Command):
    """Produce raw bytes"""

    name = "rawbytes"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.BYTES})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return the arguments joined as bytes

        Args:
            invocation: The call

        Returns:
            The bytes
        """
        return CommandResult(stdout=" ".join(invocation.arguments).encode("utf-8") + b"\n", exit_code=EXIT_CODE_SUCCESS)


def test_pipeline_streams_lazily_so_an_endless_producer_terminates(
    make_shell: Callable[[CommandRegistry], ShellHarness],
) -> None:
    """Check that head pulls only what it needs from an endless upstream and the upstream is closed"""
    counting = CountingYesCommand()
    registry = CommandRegistry()
    registry.register(counting)
    shell = make_shell(registry)

    run = shell.run("countingyes | head -n 3")

    assert run.stdout == "y\ny\ny\n"
    assert run.exit_code == EXIT_CODE_SUCCESS
    assert counting.pulled <= MAXIMUM_LINES_PULLED_FOR_THREE
    assert counting.closed


def test_real_yes_into_head_terminates(shell: ShellHarness) -> None:
    """Check that the shipped yes and head commands together produce exactly the requested lines"""
    run = shell.run("yes hello | head -n 2")

    assert run.stdout == "hello\nhello\n"


def test_pipeline_converts_a_stream_for_a_text_only_consumer(
    make_shell: Callable[[CommandRegistry], ShellHarness],
) -> None:
    """Check that a consumer declaring only whole text receives the joined stream"""
    registry = CommandRegistry()
    registry.register(UpperCommand())
    shell = make_shell(registry)

    run = shell.run("yes ab | head -n 2 | upper")

    assert run.stdout == "AB\nAB\n"


def test_pipeline_converts_bytes_to_text_for_a_text_consumer(
    make_shell: Callable[[CommandRegistry], ShellHarness],
) -> None:
    """Check that bytes output is decoded for a text-reading consumer"""
    registry = CommandRegistry()
    registry.register(BytesCommand())
    shell = make_shell(registry)

    run = shell.run("rawbytes hi | cat")

    assert run.stdout == "hi\n"


def test_pipeline_drains_input_for_a_command_that_takes_none(shell: ShellHarness) -> None:
    """Check that piping into echo discards the input and echo still runs"""
    run = shell.run("yes | echo done")

    assert run.stdout == "done\n"


@pytest.mark.parametrize(
    ("script", "expected_stdout", "expected_exit_code"),
    [
        ("echo a | cat | cat", "a\n", 0),
        ("echo $(echo inner)", "inner\n", 0),
        ("echo `echo tick`", "tick\n", 0),
        ("echo $(echo a; echo b)", "a b\n", 0),
        ('echo "$(echo a; echo b)"', "a\nb\n", 0),
        ("true && echo yes || echo no", "yes\n", 0),
        ("false && echo yes || echo no", "no\n", 0),
        ("false || echo no", "no\n", 0),
        ("true || echo skipped", "", 0),
        ("false; echo $?", "1\n", 0),
        ("! true; echo $?", "1\n", 0),
        ("! false", "", 0),
        ("false | true; echo $?", "0\n", 0),
        ("true | false", "", 1),
        ("echo -n no newline", "no newline", 0),
        ("echo -e 'a\\tb'", "a\tb\n", 0),
        ("x=5; echo $x", "5\n", 0),
        ("x=5 y=6; echo $x$y", "56\n", 0),
        ("x='a b'; echo \"$x\" $x", "a b a b\n", 0),
        ("echo $?", "0\n", 0),
        ("nosuch; echo $?", "127\n", 0),
        ("sleep 1 &\necho after", "after\n", 0),
        (":", "", 0),
        ("echo one; exit 3; echo two", "one\n", 3),
    ],
    ids=[
        "three_stage_pipeline",
        "substitution",
        "backtick_substitution",
        "substitution_output_is_split",
        "quoted_substitution_keeps_newlines",
        "and_list",
        "and_or_list_fallback",
        "or_list",
        "or_list_short_circuits",
        "exit_code_variable",
        "negated_true",
        "negated_false",
        "pipeline_exit_code_is_last_stage",
        "pipeline_failing_last_stage",
        "echo_no_newline",
        "echo_escapes",
        "assignment",
        "two_assignments",
        "quoted_versus_unquoted_variable",
        "initial_exit_code",
        "command_not_found_exit_code",
        "background_runs_synchronously",
        "colon_builtin",
        "exit_stops_the_script",
    ],
)
def test_run_simple_scripts(shell: ShellHarness, script: str, expected_stdout: str, expected_exit_code: int) -> None:
    """Check output and exit code of scripts made of simple commands, pipelines and lists"""
    run = shell.run(script)

    assert (run.stdout, run.exit_code) == (expected_stdout, expected_exit_code)


def test_command_not_found_writes_to_stderr(shell: ShellHarness) -> None:
    """Check that an unknown command reports on stderr with exit code 127"""
    run = shell.run("nosuchcommand")

    assert run.exit_code == EXIT_CODE_COMMAND_NOT_FOUND
    assert "nosuchcommand" in run.stderr
    assert run.stdout == ""


def test_syntax_error_stops_the_script_with_usage_exit_code(shell: ShellHarness) -> None:
    """Check that malformed text reports on stderr and the rest of the script does not run"""
    run = shell.run("echo 'open\necho after")

    assert run.exit_code == EXIT_CODE_USAGE_ERROR
    assert run.stdout == ""
    assert run.stderr != ""


@pytest.mark.parametrize(
    ("script", "expected_stdout"),
    [
        ("for name in a b c; do echo $name; done", "a\nb\nc\n"),
        ("for name in a b c; do if [ x ]; then :; fi; echo $name; done", "a\nb\nc\n"),
        ("for name in a b c; do echo $name; break; done", "a\n"),
        ("for name in a b c; do continue; echo $name; done", ""),
        ("x='p q'; for name in $x r; do echo $name; done", "p\nq\nr\n"),
        ("for name in $(echo a b); do echo $name; done", "a\nb\n"),
        ("set_args() { for arg; do echo $arg; done; }; set_args one two", "one\ntwo\n"),
        ("while true; do echo loop; break; done", "loop\n"),
        ("until false; do echo once; break; done", "once\n"),
        ("while false; do echo never; done; echo after", "after\n"),
        ("while ! false; do echo negated; break; done", "negated\n"),
        ("if true; then echo yes; fi", "yes\n"),
        ("if false; then echo yes; fi; echo after", "after\n"),
        ("if false; then echo a; elif true; then echo b; else echo c; fi", "b\n"),
        ("if false; then echo a; elif false; then echo b; else echo c; fi", "c\n"),
        ("if true\nthen\n  echo multi\n  echo line\nfi", "multi\nline\n"),
        ("if true; then if false; then echo inner; else echo nested; fi; fi", "nested\n"),
        ("if echo cond; then echo body; fi", "cond\nbody\n"),
    ],
    ids=[
        "for_words",
        "for_with_unknown_command_in_body",
        "for_break",
        "for_continue",
        "for_expanded_words",
        "for_substituted_words",
        "for_positional_in_function",
        "while_break",
        "until_break",
        "while_false_never_runs",
        "while_with_negated_condition",
        "if_true",
        "if_false_skips",
        "elif",
        "else",
        "if_multi_line",
        "nested_if",
        "condition_output_is_shown",
    ],
)
def test_run_compound_commands(shell: ShellHarness, script: str, expected_stdout: str) -> None:
    """Check that loops and conditionals run their bodies as the conditions dictate"""
    run = shell.run(script)

    assert run.stdout == expected_stdout


def test_functions_take_positional_arguments_and_return_codes(shell: ShellHarness) -> None:
    """Check that a function sees its arguments, returns a code, and restores the caller's arguments"""
    run = shell.run("greet() { echo hi $1 $#; return 4; }\ngreet bob extra; echo $?; echo $#")

    assert (run.stdout, run.exit_code) == ("hi bob 2\n4\n0\n", 0)


def test_function_keyword_form_and_pipeline_use(shell: ShellHarness) -> None:
    """Check that a keyword-defined function runs and its output can be piped"""
    run = shell.run("function shout { echo loud; }\nshout | cat")

    assert run.stdout == "loud\n"


def test_subshell_does_not_leak_state_but_brace_group_does(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that variables and directory changes escape a brace group but not a subshell"""
    (tmp_path / "sub").mkdir()

    run = shell.run("x=1; (x=2; cd sub); echo $x; { x=3; }; echo $x")

    assert run.stdout == "1\n3\n"
    assert run.state.cwd == tmp_path


def test_brace_group_changes_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that cd inside a brace group changes the live state"""
    (tmp_path / "sub").mkdir()

    run = shell.run("{ cd sub; }")

    assert run.state.cwd == (tmp_path / "sub").resolve()


def test_cd_to_a_missing_directory_fails(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that cd reports a missing directory and leaves the state alone"""
    run = shell.run("cd nowhere")

    assert (run.exit_code, run.state.cwd) == (1, tmp_path)
    assert run.stderr != ""


def test_subshell_output_can_be_piped(shell: ShellHarness) -> None:
    """Check that a subshell's output flows into the next pipeline stage"""
    run = shell.run("(echo a; echo b) | head -n 1")

    assert run.stdout == "a\n"


def test_brace_group_receives_piped_input(shell: ShellHarness) -> None:
    """Check that a command inside a brace group reads the pipeline's input"""
    run = shell.run("echo piped | { cat; }")

    assert run.stdout == "piped\n"


def test_write_redirection_creates_the_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that > writes the output to the file and nothing reaches the sink"""
    run = shell.run("echo hello > out.txt")

    assert (run.stdout, (tmp_path / "out.txt").read_text(encoding="utf-8")) == ("", "hello\n")


def test_append_redirection_keeps_existing_content(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that >> adds to a file written earlier"""
    shell.run("echo one > out.txt; echo two >> out.txt")

    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "one\ntwo\n"


def test_read_redirection_feeds_the_command(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that < supplies the file as standard input"""
    (tmp_path / "in.txt").write_text("from file\n", encoding="utf-8")

    run = shell.run("cat < in.txt")

    assert run.stdout == "from file\n"


def test_group_redirection_captures_every_command(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a redirection after a brace group applies to the whole group"""
    shell.run("{ echo a; echo b; } > both.txt")

    assert (tmp_path / "both.txt").read_text(encoding="utf-8") == "a\nb\n"


def test_stderr_redirection_to_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that 2> sends a command's error output to the file"""
    run = shell.run("cat missing.txt 2> err.txt")

    assert (run.stderr, run.exit_code) == ("", 1)
    assert "missing.txt" in (tmp_path / "err.txt").read_text(encoding="utf-8")


def test_stderr_to_stdout_redirection(shell: ShellHarness) -> None:
    """Check that 2>&1 sends error output to the standard output sink"""
    run = shell.run("cat missing.txt 2>&1")

    assert "missing.txt" in run.stdout
    assert run.stderr == ""


def test_heredoc_expands_unless_delimiter_is_quoted(shell: ShellHarness) -> None:
    """Check that a heredoc body expands variables only when the delimiter is unquoted"""
    run = shell.run("x=7\ncat <<EOF\nvalue $x\nEOF\ncat <<'EOF'\nraw $x\nEOF")

    assert run.stdout == "value 7\nraw $x\n"


def test_heredoc_feeds_a_pipeline(shell: ShellHarness) -> None:
    """Check that a heredoc on the first stage reaches the rest of the pipeline"""
    run = shell.run("cat <<EOF | head -n 1\nfirst\nsecond\nEOF")

    assert run.stdout == "first\n"


def test_here_string_feeds_the_command(shell: ShellHarness) -> None:
    """Check that <<< supplies the word plus a newline"""
    run = shell.run('x=word; cat <<< "$x here"')

    assert run.stdout == "word here\n"


def test_export_and_unset_change_variables(shell: ShellHarness) -> None:
    """Check that export sets a variable and unset removes it"""
    run = shell.run('export A=1; echo $A; unset A; echo "[$A]"')

    assert run.stdout == "1\n[]\n"


def test_assignment_prefix_applies_only_to_that_command(shell: ShellHarness) -> None:
    """Check that NAME=value before a command does not persist afterwards"""
    run = shell.run("x=outer; x=inner echo $x; echo $x")

    assert run.stdout == "outer\nouter\n"


def test_pipe_with_stderr_sends_errors_to_the_output_sink(shell: ShellHarness) -> None:
    """Check that |& routes the first stage's error output alongside standard output"""
    run = shell.run("cat missing.txt |& cat")

    assert "missing.txt" in run.stdout
    assert run.stderr == ""


class InterleavedCommand(Command):
    """Stream lines while writing an error between them"""

    name = "interleaved"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def lines(self, invocation: CommandInvocation) -> Generator[str, None, int]:
        """Yield one line, write an error, yield another line

        Args:
            invocation: The call, whose state receives the error

        Returns:
            Zero
        """
        yield "out one\n"
        invocation.state.write_error("err between\n")
        yield "out two\n"
        return EXIT_CODE_SUCCESS

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return the interleaving stream

        Args:
            invocation: The call

        Returns:
            The stream
        """
        return CommandResult(stdout=self.lines(invocation), exit_code=EXIT_CODE_SUCCESS)


def test_last_command_streams_stdout_and_stderr_incrementally(tmp_path: Path) -> None:
    """Check that the terminal receives each stdout and stderr chunk in the order written, not all at the end"""
    registry = CommandRegistry()
    registry.register(InterleavedCommand())
    arrivals: list[tuple[str, str]] = []
    state = ShellState(
        cwd=tmp_path,
        write_output=lambda text: arrivals.append(("stdout", text)),
        write_error=lambda text: arrivals.append(("stderr", text)),
    )

    Executor(registry).execute_script("yes | head -n 2 | interleaved", state)

    assert arrivals == [("stdout", "out one\n"), ("stderr", "err between\n"), ("stdout", "out two\n")]


def test_state_records_stdout_and_stderr_separately(tmp_path: Path) -> None:
    """Check that the state keeps everything written to each stream as well as streaming it"""
    state = ShellState(cwd=tmp_path, write_output=lambda text: None, write_error=lambda text: None)

    Executor().execute_script("echo shown; cat missing.txt; echo more", state)

    assert state.stdout == "shown\nmore\n"
    assert "missing.txt" in state.stderr


def test_recorded_output_excludes_captured_substitutions(tmp_path: Path) -> None:
    """Check that output consumed by a substitution or a redirection is not recorded as terminal output"""
    state = ShellState(cwd=tmp_path, write_output=lambda text: None, write_error=lambda text: None)

    Executor().execute_script("echo $(echo inner); echo hidden > out.txt", state)

    assert state.stdout == "inner\n"


@pytest.mark.parametrize(
    ("script", "expected_stdout", "expected_exit_code"),
    [
        ("x=$(false); echo $?", "1\n", 0),
        ("x=$(nosuch 2>/dev/null); echo $?", "127\n", 0),
        ("x=5; echo $?", "0\n", 0),
        ("(exit 3); echo $?", "3\n", 0),
        ("x=$(exit 4); echo $?", "4\n", 0),
        ("f() { exit 3; }; (f); echo $?", "3\n", 0),
        ("break; echo after", "after\n", 0),
        ("continue; echo after", "after\n", 0),
        ("return; echo after", "after\n", 0),
        ("f() { break; echo in; }; for i in 1 2; do f; echo $i; done", "in\n1\nin\n2\n", 0),
        ("for i in 1 2; do echo $i; done > out; cat out", "1\n2\n", 0),
        ("if true; then echo a; fi > out; cat out", "a\n", 0),
        ("while true; do echo w; break; done >> out; cat out", "w\n", 0),
        ("if true; then cat; fi <<EOF\nfed\nEOF", "fed\n", 0),
        ("cat missing 2>&1 | head -c 3", "cat", 0),
        ("cat missing |& head -c 3", "cat", 0),
        ("cat missing &> both; head -c 3 both", "cat", 0),
        ("{ echo a; cat missing; } 2>&1 | head -n 1", "a\n", 0),
        ("cat missing 2>/dev/null; echo $?", "1\n", 0),
        ("cat missing >/dev/null 2>&1; echo $?", "1\n", 0),
        ("echo a > /dev/null; echo $?", "0\n", 0),
        ("cat /dev/null; echo $?", "0\n", 0),
        ("f() { cat; }; f < /dev/null; echo end", "end\n", 0),
        ("cat <<< $(echo sub)", "sub\n", 0),
        ("yes '' | head -n 2 | cat -n", "     1\t\n     2\t\n", 0),
        ("x=1; (x=2; (x=3; echo $x); echo $x); echo $x", "3\n2\n1\n", 0),
        ("f() { return 300; }; f; echo $?", "44\n", 0),
        ("echo a | false; echo $?", "1\n", 0),
        ("false; x=$?; echo $x", "1\n", 0),
    ],
    ids=[
        "assignment_takes_substitution_exit_code",
        "assignment_takes_command_not_found_code",
        "plain_assignment_succeeds",
        "exit_in_subshell_only_leaves_subshell",
        "exit_in_substitution_only_leaves_substitution",
        "exit_in_function_in_subshell",
        "break_outside_loop_is_ignored",
        "continue_outside_loop_is_ignored",
        "return_outside_function_is_ignored",
        "break_in_function_does_not_leave_caller_loop",
        "for_loop_redirection",
        "if_redirection",
        "while_append_redirection",
        "heredoc_into_if",
        "stderr_to_stdout_enters_the_pipe",
        "pipe_ampersand_enters_the_pipe",
        "both_redirection_to_file",
        "group_stderr_to_stdout_enters_the_pipe",
        "stderr_to_null_device",
        "stdout_and_stderr_to_null_device",
        "stdout_to_null_device",
        "read_null_device",
        "function_stdin_from_null_device",
        "here_string_with_substitution",
        "yes_with_empty_argument",
        "nested_subshell_scopes",
        "return_code_wraps_at_256",
        "pipeline_exit_code_from_failing_consumer",
        "exit_code_captured_into_variable",
    ],
)
def test_run_scripts_matching_bash_behaviour(
    shell: ShellHarness, script: str, expected_stdout: str, expected_exit_code: int
) -> None:
    """Check scripts whose expected output was confirmed against real bash"""
    run = shell.run(script)

    assert (run.stdout, run.exit_code) == (expected_stdout, expected_exit_code)


def test_stray_double_semicolon_is_a_syntax_error(shell: ShellHarness) -> None:
    """Check that ;; outside a case statement stops the script with a usage error"""
    run = shell.run("echo a;;echo b")

    assert (run.stdout, run.exit_code) == ("", EXIT_CODE_USAGE_ERROR)


def test_bad_substitution_stops_the_script(shell: ShellHarness) -> None:
    """Check that an unparseable parameter expansion stops the script with exit code one"""
    run = shell.run("echo ${}; echo after")

    assert (run.stdout, run.exit_code) == ("", 1)
    assert run.stderr != ""


def test_nested_group_does_not_hide_piped_input(shell: ShellHarness) -> None:
    """Check that a command inside a group inside a group still reads what was piped into the outer group"""
    run = shell.run("echo in | { if true; then cat; fi; }")

    assert run.stdout == "in\n"


def test_piped_input_is_read_once_by_the_first_reader(shell: ShellHarness) -> None:
    """Check that commands which take no input leave the piped input for the first command that reads it"""
    run = shell.run("echo in | { true; echo skip; cat; cat; }")

    assert run.stdout == "skip\nin\n"


def test_endless_producer_inside_a_group_hits_the_output_limit(tmp_path: Path) -> None:
    """Check that a group that never stops writing is cut off with an error instead of hanging"""
    pieces: list[str] = []
    errors: list[str] = []
    state = ShellState(cwd=tmp_path, write_output=pieces.append, write_error=errors.append)
    executor = Executor(output_limit_characters=1000)

    exit_code = executor.execute_script("( yes ) | head -n 2; echo after", state)

    assert "".join(pieces) == "y\ny\nafter\n"
    assert exit_code == 0
    assert errors != []
