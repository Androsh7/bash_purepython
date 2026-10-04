"""Hold the state of one shell and run command lines against it"""

# Standard libraries
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# Project libraries
from bash_purepython.shell import completion
from bash_purepython.shell.builtins import BUILTINS, BuiltinContext
from bash_purepython.shell.commands import list_command_names
from bash_purepython.shell.models import (
    DEFAULT_TERMINAL_COLUMNS,
    EXIT_CODE_COMMAND_NOT_FOUND,
    EXIT_CODE_FAILURE,
    EXIT_CODE_INTERRUPTED,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_SYNTAX_ERROR,
    HISTORY_LIMIT_ENTRIES,
    OUTPUT_LIMIT_BYTES,
    ChainOperator,
    CommandKind,
    CommandList,
    CommandNotFoundError,
    CompletionResult,
    HostCall,
    HostCommand,
    HostCommandPlacementError,
    Pipeline,
    RawPipeline,
    RawWord,
    Redirect,
    RunResult,
    ShellSyntaxError,
    SimpleCommand,
)
from bash_purepython.shell.parser import parse
from bash_purepython.shell.runner import run_command_on_streams
from bash_purepython.shell.streams import (
    STDERR_KIND,
    STDOUT_KIND,
    STREAM_ENCODING,
    OutputCapture,
    OutputSink,
    make_sink_stream,
    make_stdin,
    wrap_binary,
)
from bash_purepython.shell.tokenizer import expand_word, tokenize

SHELL_NAME = "ash7"
SHELL_STATE_VARIABLES = frozenset({"PWD", "OLDPWD"})
HOST_REDIRECT_MESSAGE = "{name}: browser commands support only > and >>"


@dataclass(frozen=True, slots=True)
class StageStreams:
    """Hold the streams one pipeline stage runs with, and the files to close afterwards"""

    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    pipe_capture: OutputCapture | None
    stderr_capture: OutputCapture | None
    files: tuple[TextIO, ...]
    failure: str | None


class ShellSession:
    """Own the working directory, environment, history and exit status of one shell"""

    def __init__(
        self,
        home: str,
        host_commands: Sequence[HostCommand],
        environment: Mapping[str, str],
        history: Sequence[str] = (),
        columns: int = DEFAULT_TERMINAL_COLUMNS,
        output_sink: OutputSink | None = None,
    ):
        """Seed the process environment and remember the host's commands

        With an output sink, the last command's stdout and every command's stderr are
        handed to it as they are written and the RunResult carries no text. Without
        one they are collected and returned

        Args:
            home: The directory ~ and a bare cd refer to unless HOME says otherwise
            host_commands: The commands the embedding host runs itself
            environment: Variables to set before the first line runs
            history: Previously run lines, oldest first
            columns: The terminal width used to lay out listings
            output_sink: Where to stream output, or None to collect it
        """
        self._default_home = home
        self.host_commands = tuple(host_commands)
        self.columns = columns
        self.output_sink = output_sink
        self.last_exit_code = EXIT_CODE_SUCCESS
        self._history = list(history)[-HISTORY_LIMIT_ENTRIES:]
        self._exported_names: set[str] = set(environment) - SHELL_STATE_VARIABLES
        os.environ.update({name: value for name, value in environment.items() if name not in SHELL_STATE_VARIABLES})
        os.environ.setdefault("HOME", home)
        os.environ["PWD"] = str(Path.cwd())
        os.environ.pop("OLDPWD", None)

    @property
    def home(self) -> str:
        """Return the directory ~ stands for, HOME if set and the seeded default otherwise"""
        return os.environ.get("HOME") or self._default_home

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

    def register_exported(self, name: str) -> None:
        """Mark a variable as one the host should see and keep

        Args:
            name: The variable name
        """
        self._exported_names.add(name)

    def exported_environment(self) -> dict[str, str]:
        """Return the variables the shell was seeded with or exported since, with their current values"""
        return {name: os.environ[name] for name in sorted(self._exported_names) if name in os.environ}

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

    def resolve_pipeline(self, raw_pipeline: RawPipeline, exit_code: int) -> Pipeline:
        """Expand a pipeline's words against the environment as it is right now

        Args:
            raw_pipeline: The pipeline as parsed
            exit_code: The value $? expands to

        Raises:
            ShellSyntaxError: If a redirect target expands to nothing

        Returns:
            The pipeline with plain argv, commands that expanded to nothing left out
        """
        commands: list[SimpleCommand] = []
        for raw_command in raw_pipeline.commands:
            argv = [
                expanded
                for expanded in (expand_word(word, os.environ, self.home, exit_code) for word in raw_command.words)
                if expanded is not None
            ]
            redirects = raw_command.redirects
            stdout_target = self._expand_target(redirects.stdout_target, exit_code)
            stderr_target = self._expand_target(redirects.stderr_target, exit_code)
            if argv:
                commands.append(
                    SimpleCommand(
                        argv=tuple(argv),
                        redirect=None if stdout_target is None else Redirect(stdout_target, redirects.stdout_append),
                        stderr_redirect=None
                        if stderr_target is None
                        else Redirect(stderr_target, redirects.stderr_append),
                        stderr_to_stdout=redirects.stderr_to_stdout,
                        stdin_path=self._expand_target(redirects.stdin_source, exit_code),
                    )
                )
        return Pipeline(commands=tuple(commands))

    def _expand_target(self, word: RawWord | None, exit_code: int) -> str | None:
        """Expand a redirect target, which must come out as exactly one word

        Args:
            word: The target as parsed, or None when there is no such redirect
            exit_code: The value $? expands to

        Raises:
            ShellSyntaxError: If the target expands to nothing

        Returns:
            The path, or None when there is no redirect
        """
        if word is None:
            return None
        target = expand_word(word, os.environ, self.home, exit_code)
        if target is None:
            raise ShellSyntaxError("ambiguous redirect")
        return target

    def run_line(self, line: str, columns: int | None = None) -> RunResult:
        """Run one command line and return everything it produced

        Args:
            line: The line as typed
            columns: The current terminal width, if it changed

        Returns:
            The collected output when there is no sink, the final exit code, the resulting
            cwd and environment, and the host call to make instead when the line names a
            host command
        """
        if columns is not None:
            self.columns = columns
        stripped = line.strip()
        if not stripped:
            return self._result("", "", self.last_exit_code)
        self.record_history(stripped)
        try:
            command_list = parse(tokenize(line))
            host_call = self._host_call_for(command_list)
        except ShellSyntaxError as error:
            self.last_exit_code = EXIT_CODE_SYNTAX_ERROR
            return self._result("", f"{SHELL_NAME}: {error}\n", self.last_exit_code)
        except HostCommandPlacementError as error:
            self.last_exit_code = EXIT_CODE_FAILURE
            return self._result("", f"{SHELL_NAME}: {error}\n", self.last_exit_code)
        if host_call is not None:
            return self._result("", "", self.last_exit_code, host_call)
        return self._run_command_list(command_list)

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
            environment=os.environ,
        )

    def _host_call_for(self, command_list: CommandList) -> HostCall | None:
        """Return the host call a line asks for, or None when the shell runs the line itself

        Command names are expanded against the current environment for the check

        Args:
            command_list: The parsed line

        Raises:
            HostCommandPlacementError: If a host command appears anywhere but alone on the line

        Returns:
            The host command, its arguments and its redirect when the line is just that command
        """
        host_names = set(self.host_command_names)
        resolved = [self.resolve_pipeline(pipeline, self.last_exit_code) for pipeline in command_list.pipelines]
        if len(resolved) == 1 and len(resolved[0].commands) == 1:
            only_command = resolved[0].commands[0]
            if only_command.name in host_names:
                if only_command.stderr_redirect or only_command.stderr_to_stdout or only_command.stdin_path:
                    raise ShellSyntaxError(HOST_REDIRECT_MESSAGE.format(name=only_command.name))
                return HostCall(name=only_command.name, argv=only_command.argv, redirect=only_command.redirect)
        for pipeline in resolved:
            for command in pipeline.commands:
                if command.name in host_names:
                    raise HostCommandPlacementError(command.name)
        return None

    def _run_command_list(self, command_list: CommandList) -> RunResult:
        """Run the pipelines of a line in order, honouring the operators between them

        Each pipeline is expanded just before it runs, so a variable exported or a
        directory changed earlier on the line is visible to it. An interrupt stops
        the whole line

        Args:
            command_list: The parsed line

        Returns:
            The result of the whole line
        """
        stdout_parts: list[bytes] = []
        stderr_parts: list[bytes] = []
        exit_code = self.last_exit_code
        try:
            for position, raw_pipeline in enumerate(command_list.pipelines):
                if position > 0 and not should_run_after(command_list.operators[position - 1], exit_code):
                    continue
                try:
                    pipeline = self.resolve_pipeline(raw_pipeline, exit_code)
                except ShellSyntaxError as error:
                    stderr_parts.append(f"{SHELL_NAME}: {error}\n".encode(STREAM_ENCODING))
                    exit_code = EXIT_CODE_SYNTAX_ERROR
                    continue
                stdout_bytes, stderr_bytes, exit_code = self._run_pipeline(pipeline)
                stdout_parts.append(stdout_bytes)
                stderr_parts.append(stderr_bytes)
        except KeyboardInterrupt:
            exit_code = EXIT_CODE_INTERRUPTED
        self.last_exit_code = exit_code
        return self._result(decode(b"".join(stdout_parts)), decode(b"".join(stderr_parts)), exit_code)

    def _result(self, stdout: str, stderr: str, exit_code: int, host_call: HostCall | None = None) -> RunResult:
        """Return a result carrying the current cwd and the exported environment

        With a sink, stderr text produced by the shell itself is sent there instead of returned

        Args:
            stdout: Everything the line wrote to standard output
            stderr: Everything the line wrote to standard error
            exit_code: The line's final exit code
            host_call: The host command to run instead, if any
        """
        if self.output_sink is not None and stderr:
            self.output_sink(STDERR_KIND, stderr)
            stderr = ""
        return RunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            cwd=str(Path.cwd()),
            environment=self.exported_environment(),
            host_call=host_call,
        )

    def _run_pipeline(self, pipeline: Pipeline) -> tuple[bytes, bytes, int]:
        """Run each command with the previous one's output as its input

        The last command's stdout and every stderr go to the sink when there is one;
        otherwise they are collected. A redirected command writes straight to its
        file, and is not run at all when the file cannot be opened. A pipeline with
        no commands, because every word expanded to nothing, succeeds without running

        Args:
            pipeline: The commands to chain

        Raises:
            KeyboardInterrupt: If a command was interrupted, after its streams are flushed

        Returns:
            The collected stdout, the collected stderr, and the last exit code
        """
        stdin_data = b""
        stdout_parts: list[bytes] = []
        stderr_parts: list[bytes] = []
        exit_code = EXIT_CODE_SUCCESS
        last_position = len(pipeline.commands) - 1
        for position, command in enumerate(pipeline.commands):
            streams = self._open_stage_streams(command, stdin_data, position == last_position)
            stdin_data = b""
            if streams.failure is not None:
                streams.stderr.write(f"{SHELL_NAME}: {streams.failure}\n")
                streams.stderr.flush()
                exit_code = EXIT_CODE_FAILURE
                if streams.stderr_capture is not None:
                    stderr_parts.append(streams.stderr_capture.getvalue())
                continue
            try:
                exit_code = self._run_simple_command(command, streams.stdin, streams.stdout, streams.stderr)
            finally:
                streams.stdout.flush()
                streams.stderr.flush()
                for opened in streams.files:
                    opened.close()
            if streams.pipe_capture is not None and streams.pipe_capture.overflowed:
                streams.stderr.write(f"{SHELL_NAME}: {command.name}: output exceeded {OUTPUT_LIMIT_BYTES} bytes\n")
                exit_code = EXIT_CODE_FAILURE
            if streams.stderr_capture is not None:
                stderr_parts.append(streams.stderr_capture.getvalue())
                if streams.stderr_capture.overflowed:
                    stderr_parts.append(
                        f"\n{SHELL_NAME}: {command.name}: error output exceeded {OUTPUT_LIMIT_BYTES} bytes\n".encode(
                            STREAM_ENCODING
                        )
                    )
                    exit_code = EXIT_CODE_FAILURE
            if streams.pipe_capture is None:
                continue
            if position == last_position:
                stdout_parts.append(streams.pipe_capture.getvalue())
            else:
                stdin_data = streams.pipe_capture.getvalue()
        return b"".join(stdout_parts), b"".join(stderr_parts), exit_code

    def _open_stage_streams(self, command: SimpleCommand, stdin_data: bytes, is_last: bool) -> StageStreams:
        """Bind one stage's stdin, stdout and stderr according to its redirects

        stdout goes to its file or to the pipe: the capture feeding the next stage or
        the result, or the sink for the last stage. stderr goes to its file, shares
        stdout's file when both name the same one, goes to the pipe for a 2>&1 given
        before any >, or goes to the sink or a capture. stdin comes from its file or
        the previous stage

        Args:
            command: The command whose redirects decide the streams
            stdin_data: What the previous stage produced
            is_last: Whether this is the last stage of the pipeline

        Returns:
            The streams, or a failure message when a redirect target cannot be opened
        """
        files: list[TextIO] = []
        pipe_capture = None
        stderr_capture = None
        # The pipe is where stdout goes unless a file takes it: the next stage, the
        # result, or the terminal for the last stage of a streaming session
        if is_last and self.output_sink is not None:
            pipe = make_sink_stream(self.output_sink, STDOUT_KIND)
        else:
            pipe_capture = OutputCapture(OUTPUT_LIMIT_BYTES)
            pipe = pipe_capture.stream
        if command.redirect is not None:
            opened = open_redirect(command.redirect)
            if opened is None:
                return self._failed_streams(f"{command.redirect.target}: cannot open for writing")
            files.append(opened)
            stdout = opened
        else:
            stdout = pipe
        if command.stderr_redirect is not None and command.stderr_redirect == command.redirect:
            # Both streams name the same file, so they share one handle and one position
            stderr = stdout
        elif command.stderr_redirect is not None:
            opened = open_redirect(command.stderr_redirect)
            if opened is None:
                close_all(files)
                return self._failed_streams(f"{command.stderr_redirect.target}: cannot open for writing")
            files.append(opened)
            stderr = opened
        elif command.stderr_to_stdout:
            stderr = pipe
        elif self.output_sink is not None:
            stderr = make_sink_stream(self.output_sink, STDERR_KIND)
        else:
            stderr_capture = OutputCapture(OUTPUT_LIMIT_BYTES)
            stderr = stderr_capture.stream
        if command.stdin_path is not None:
            opened = open_input(command.stdin_path)
            if opened is None:
                close_all(files)
                return self._failed_streams(f"{command.stdin_path}: cannot open for reading")
            files.append(opened)
            stdin = opened
        else:
            stdin = make_stdin(stdin_data)
        return StageStreams(
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            pipe_capture=pipe_capture,
            stderr_capture=stderr_capture,
            files=tuple(files),
            failure=None,
        )

    def _failed_streams(self, failure: str) -> StageStreams:
        """Return streams that only carry a redirect failure to the normal stderr

        Args:
            failure: The message to report

        Returns:
            Streams whose stderr is the sink or a capture, with the failure set
        """
        stderr_capture = None if self.output_sink else OutputCapture(OUTPUT_LIMIT_BYTES)
        stderr = make_sink_stream(self.output_sink, STDERR_KIND) if self.output_sink else stderr_capture.stream
        return StageStreams(
            stdin=make_stdin(b""),
            stdout=stderr,
            stderr=stderr,
            pipe_capture=None,
            stderr_capture=stderr_capture,
            files=(),
            failure=failure,
        )

    def _run_simple_command(self, command: SimpleCommand, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
        """Run one builtin or package command on the given streams

        Args:
            command: The command and its arguments
            stdin: What the command reads
            stdout: Where its output goes
            stderr: Where its errors go

        Returns:
            The exit code, 127 when the command does not exist
        """
        if command.name in BUILTINS:
            context = BuiltinContext(argv=command.argv, stdin=stdin, stdout=stdout, stderr=stderr, session=self)
            return BUILTINS[command.name](context)
        try:
            return run_command_on_streams(command.name, command.argv, stdin, stdout, stderr)
        except CommandNotFoundError as error:
            stderr.write(f"{error}\n")
            return EXIT_CODE_COMMAND_NOT_FOUND


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


def close_all(files: Sequence[TextIO]) -> None:
    """Close every file opened for a stage that will not run after all

    Args:
        files: The streams to close
    """
    for opened in files:
        opened.close()


def open_input(path: str) -> TextIO | None:
    """Open a file as a command's standard input

    Args:
        path: The file to read, relative to the working directory

    Returns:
        A readable text stream with a byte buffer, or None if the file cannot be opened
    """
    try:
        raw = Path(path).open("rb")  # noqa: SIM115
    except OSError:
        return None
    return wrap_binary(raw)


def open_redirect(redirect: Redirect) -> TextIO | None:
    """Open a redirect target so a command writes straight into it

    Args:
        redirect: The target path and whether to append

    Returns:
        A writable text stream with a byte buffer, or None if the file cannot be opened
    """
    try:
        raw = Path(redirect.target).open("ab" if redirect.append else "wb")  # noqa: SIM115
    except OSError:
        return None
    return wrap_binary(raw)


def decode(data: bytes) -> str:
    """Return bytes as text, replacing anything that is not valid UTF-8

    Args:
        data: The bytes a command produced
    """
    return data.decode(STREAM_ENCODING, "replace")
