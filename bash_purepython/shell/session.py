"""Hold the state of one shell and run command lines against it"""

# Standard libraries
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

# Project libraries
from bash_purepython.shell import completion
from bash_purepython.shell.builtins import BUILTINS, BuiltinContext
from bash_purepython.shell.commands import list_command_names
from bash_purepython.shell.models import (
    DEFAULT_TERMINAL_COLUMNS,
    EXIT_CODE_COMMAND_NOT_FOUND,
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_SYNTAX_ERROR,
    HISTORY_LIMIT_ENTRIES,
    ChainOperator,
    CommandKind,
    CommandList,
    CommandNotFoundError,
    CommandOutput,
    CompletionResult,
    HostCall,
    HostCommand,
    HostCommandPlacementError,
    Pipeline,
    RunResult,
    ShellSyntaxError,
    SimpleCommand,
)
from bash_purepython.shell.parser import parse
from bash_purepython.shell.runner import STREAM_ENCODING, OutputCapture, make_stdin, run_command
from bash_purepython.shell.tokenizer import tokenize

SHELL_NAME = "ash7"


class ShellSession:
    """Own the working directory, environment, history and exit status of one shell"""

    def __init__(
        self,
        home: str,
        host_commands: Sequence[HostCommand],
        environment: Mapping[str, str],
        history: Sequence[str] = (),
        columns: int = DEFAULT_TERMINAL_COLUMNS,
    ):
        """Seed the process environment and remember the host's commands

        Args:
            home: The directory ~ and a bare cd refer to
            host_commands: The commands the embedding host runs itself
            environment: Variables to set before the first line runs
            history: Previously run lines, oldest first
            columns: The terminal width used to lay out listings
        """
        self.home = home
        self.host_commands = tuple(host_commands)
        self.columns = columns
        self.last_exit_code = EXIT_CODE_SUCCESS
        self._history = list(history)[-HISTORY_LIMIT_ENTRIES:]
        os.environ.update(environment)
        os.environ.setdefault("HOME", home)
        os.environ.setdefault("PWD", str(Path.cwd()))

    @property
    def history(self) -> tuple[str, ...]:
        """Return every remembered line, oldest first"""
        return tuple(self._history)

    @property
    def host_command_names(self) -> tuple[str, ...]:
        """Return the names of the commands the host runs"""
        return tuple(command.name for command in self.host_commands)

    def all_command_names(self) -> list[str]:
        """Return every name the shell can run, sorted and without duplicates"""
        return sorted({*BUILTINS, *list_command_names(), *self.host_command_names})

    def command_kind(self, name: str) -> CommandKind | None:
        """Return where a command comes from, or None if the shell does not know it

        Args:
            name: The command name to look up
        """
        if name in BUILTINS:
            return CommandKind.BUILTIN
        if name in self.host_command_names:
            return CommandKind.HOST
        if name in list_command_names():
            return CommandKind.PACKAGE
        return None

    def record_history(self, line: str) -> None:
        """Remember a line unless it repeats the previous one, dropping the oldest past the limit

        Args:
            line: The line as typed, already stripped
        """
        if self._history and self._history[-1] == line:
            return
        self._history.append(line)
        del self._history[:-HISTORY_LIMIT_ENTRIES]

    def set_last_exit_code(self, exit_code: int) -> None:
        """Record the exit code of a command the host ran on the shell's behalf

        Args:
            exit_code: The code the host command finished with
        """
        self.last_exit_code = exit_code

    def run_line(self, line: str, columns: int | None = None) -> RunResult:
        """Run one command line and return everything it produced

        Args:
            line: The line as typed
            columns: The current terminal width, if it changed

        Returns:
            The combined output, the final exit code, the resulting cwd and environment, and
            the host call to make instead when the line names a host command
        """
        if columns is not None:
            self.columns = columns
        stripped = line.strip()
        if not stripped:
            return self._result("", "", self.last_exit_code)
        self.record_history(stripped)
        try:
            command_list = parse(tokenize(line, os.environ, self.home, self.last_exit_code))
            host_call = host_call_for(command_list, self.host_command_names)
        except ShellSyntaxError as error:
            self.last_exit_code = EXIT_CODE_SYNTAX_ERROR
            return self._result("", f"{SHELL_NAME}: {error}\n", self.last_exit_code)
        except HostCommandPlacementError as error:
            self.last_exit_code = EXIT_CODE_FAILURE
            return self._result("", f"{SHELL_NAME}: {error}\n", self.last_exit_code)
        if host_call is not None:
            return self._result("", "", self.last_exit_code, host_call)
        stdout_parts: list[bytes] = []
        stderr_parts: list[bytes] = []
        exit_code = self.last_exit_code
        for position, pipeline in enumerate(command_list.pipelines):
            if position > 0 and not should_run_after(command_list.operators[position - 1], exit_code):
                continue
            output = self._run_pipeline(pipeline)
            stdout_parts.append(output.stdout)
            stderr_parts.append(output.stderr)
            exit_code = output.exit_code
        self.last_exit_code = exit_code
        return self._result(decode(b"".join(stdout_parts)), decode(b"".join(stderr_parts)), exit_code)

    def complete(self, line: str, cursor: int) -> CompletionResult:
        """Return the completion for the word under the cursor

        Args:
            line: The whole command line
            cursor: The position of the cursor within it
        """
        return completion.complete(
            line,
            cursor,
            builtin_names=tuple(BUILTINS),
            package_names=list_command_names(),
            host_names=self.host_command_names,
            home=self.home,
        )

    def _result(self, stdout: str, stderr: str, exit_code: int, host_call: HostCall | None = None) -> RunResult:
        """Return a result carrying the current cwd and environment

        Args:
            stdout: Everything the line wrote to standard output
            stderr: Everything the line wrote to standard error
            exit_code: The line's final exit code
            host_call: The host command to run instead, if any
        """
        return RunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            cwd=str(Path.cwd()),
            environment=dict(os.environ),
            host_call=host_call,
        )

    def _run_pipeline(self, pipeline: Pipeline) -> CommandOutput:
        """Run each command with the previous one's output as its input

        Args:
            pipeline: The commands to chain

        Returns:
            The last command's output after redirection, every command's stderr, and the last exit code
        """
        stdin_data = b""
        stderr_parts: list[bytes] = []
        exit_code = EXIT_CODE_SUCCESS
        for command in pipeline.commands:
            output = self._run_simple_command(command, stdin_data)
            stderr_parts.append(output.stderr)
            exit_code = output.exit_code
            stdin_data = output.stdout
            if command.redirect is not None:
                redirect_error = write_redirect(command.redirect.target, command.redirect.append, stdin_data)
                stdin_data = b""
                if redirect_error:
                    stderr_parts.append(redirect_error.encode(STREAM_ENCODING))
                    exit_code = EXIT_CODE_FAILURE
        return CommandOutput(stdout=stdin_data, stderr=b"".join(stderr_parts), exit_code=exit_code)

    def _run_simple_command(self, command: SimpleCommand, stdin_data: bytes) -> CommandOutput:
        """Run one builtin or package command

        Args:
            command: The command and its arguments
            stdin_data: The bytes it reads from standard input

        Returns:
            The command's output, or a command-not-found error with exit code 127
        """
        if command.name in BUILTINS:
            return self._run_builtin(command, stdin_data)
        try:
            return run_command(command.name, command.argv, stdin_data)
        except CommandNotFoundError as error:
            return CommandOutput(
                stdout=b"", stderr=f"{error}\n".encode(STREAM_ENCODING), exit_code=EXIT_CODE_COMMAND_NOT_FOUND
            )

    def _run_builtin(self, command: SimpleCommand, stdin_data: bytes) -> CommandOutput:
        """Run one of the shell's own commands with captured streams

        Args:
            command: The command and its arguments
            stdin_data: The bytes it reads from standard input

        Returns:
            The builtin's output and exit code
        """
        stdout_capture, stderr_capture = OutputCapture(), OutputCapture()
        context = BuiltinContext(
            argv=command.argv,
            stdin=make_stdin(stdin_data),
            stdout=stdout_capture.stream,
            stderr=stderr_capture.stream,
            session=self,
        )
        exit_code = BUILTINS[command.name](context)
        return CommandOutput(stdout=stdout_capture.getvalue(), stderr=stderr_capture.getvalue(), exit_code=exit_code)


def should_run_after(operator: ChainOperator, previous_exit_code: int) -> bool:
    """Return whether the pipeline after operator runs given the exit code before it

    Args:
        operator: The operator joining the two pipelines
        previous_exit_code: The exit code of everything run so far

    Returns:
        True for a semicolon, for && after success, and for || after failure
    """
    if operator == ChainOperator.AND:
        return previous_exit_code == EXIT_CODE_SUCCESS
    if operator == ChainOperator.OR:
        return previous_exit_code != EXIT_CODE_SUCCESS
    return True


def host_call_for(command_list: CommandList, host_names: Sequence[str]) -> HostCall | None:
    """Return the host call a line asks for, or None when the shell runs the line itself

    Args:
        command_list: The parsed line
        host_names: The commands the host runs

    Raises:
        HostCommandPlacementError: If a host command appears anywhere but alone on the line

    Returns:
        The host command, its arguments and its redirect when the line is just that command
    """
    only_pipeline = command_list.pipelines[0]
    if len(command_list.pipelines) == 1 and len(only_pipeline.commands) == 1:
        only_command = only_pipeline.commands[0]
        if only_command.name in host_names:
            return HostCall(name=only_command.name, argv=only_command.argv, redirect=only_command.redirect)
    for pipeline in command_list.pipelines:
        for command in pipeline.commands:
            if command.name in host_names:
                raise HostCommandPlacementError(command.name)
    return None


def write_redirect(target: str, append: bool, data: bytes) -> str:
    """Write a pipeline's output to its redirect target

    Args:
        target: The file path, relative to the working directory
        append: Whether to add to the file instead of replacing it
        data: The bytes to write

    Returns:
        An error line for stderr, or nothing when the write succeeded
    """
    try:
        with Path(target).open("ab" if append else "wb") as target_file:
            target_file.write(data)
    except OSError as error:
        return f"{SHELL_NAME}: {target}: {error.strerror}\n"
    return ""


def decode(data: bytes) -> str:
    """Return bytes as text, replacing anything that is not valid UTF-8

    Args:
        data: The bytes a command produced
    """
    return data.decode(STREAM_ENCODING, "replace")
