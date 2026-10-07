"""Drive the engine and a Python console for a browser terminal under Pyodide"""

# Standard libraries
import json
import os
import traceback
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, ClassVar, Protocol

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.execute_command import Executor
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState

EXIT_CODE_INTERRUPTED = 130
CD_BUILTIN_NAME = "cd"
HOST_OUTPUT_KIND_STDOUT = "stdout"
HOST_OUTPUT_KIND_STDERR = "stderr"
REPL_STATUS_DONE = "done"
REPL_STATUS_MORE = "more"
REPL_STATUS_ERROR = "error"
REPL_STATUS_EXIT = "exit"
REPL_SYNTAX_INCOMPLETE = "incomplete"
REPL_EXIT_WORDS = frozenset({"exit", "exit()", "quit", "quit()"})
CONSOLE_FILENAME = "<console>"
HOME_VARIABLE = "HOME"
PWD_VARIABLE = "PWD"

TextWriter = Callable[[str], Any]


class HostOutputPiece(Protocol):
    """Describe one piece of output a browser command produced"""

    kind: str
    text: str


class HostCallHandle(Protocol):
    """Describe a running browser command, as the host hands it to the engine"""

    def __aiter__(self) -> AsyncIterator[HostOutputPiece]:
        """Return the pieces of output in the order they were written"""

    def exit_code(self) -> int:
        """Return the exit code once the output is exhausted"""

    def cancel(self) -> None:
        """Tell the host the engine stopped reading, so it can stop the command"""


HostCallStarter = Callable[[str, list[str], str, bool, str | None], HostCallHandle]


class HostCommand(Command):
    """Run a command the host implements, streaming what it prints through the pipeline"""

    input_kinds: ClassVar[frozenset[InputKind]] = frozenset({InputKind.ARGUMENTS, InputKind.TEXT})
    output_kinds: ClassVar[frozenset[OutputKind]] = frozenset({OutputKind.STREAM_TEXT})

    def __init__(self, name: str, start_host_call: HostCallStarter):
        """Bind one host command name to the callback that starts it

        Args:
            name: The command name as typed in the shell
            start_host_call: Takes the name, arguments, current directory, whether the command is
                attached to the terminal, and the standard input piped or redirected into it or None,
                and returns a handle on the running command
        """
        self.name = name
        self.start_host_call = start_host_call

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream that relays the host command's output until it exits

        The shell's current directory travels with the call, since the host resolves relative paths itself and
        the directory may have changed earlier on the same line. So does whether the command is attached to
        the terminal: an attached command may write to the terminal itself as it runs, which is what lets a
        prompt appear before the command blocks reading a line, instead of relaying output through here.
        Input piped or redirected into the command is handed over whole; without any, the host reads the
        terminal

        Args:
            invocation: The arguments and shell state of this call

        Returns:
            A lazy stream of the command's standard output
        """
        piped_input = invocation.stdin if invocation.stdin_kind == InputKind.TEXT else None
        handle = self.start_host_call(
            self.name,
            list(invocation.arguments),
            str(invocation.state.cwd),
            invocation.attached_to_terminal,
            piped_input,
        )
        return CommandResult(stdout=relay_host_output(handle, invocation), exit_code=EXIT_CODE_SUCCESS)


async def relay_host_output(handle: HostCallHandle, invocation: CommandInvocation) -> AsyncIterator[str]:
    """Yield the host command's standard output, forward its errors, then record its exit code

    Args:
        handle: The running command, iterated for its output pieces
        invocation: The call whose exit status receives the exit code

    Yields:
        Each chunk written to standard output
    """
    try:
        async for piece in handle:
            if piece.kind == HOST_OUTPUT_KIND_STDERR:
                invocation.state.write_error(piece.text)
            else:
                yield piece.text
    finally:
        handle.cancel()
    invocation.exit_status.code = int(handle.exit_code())


class PyodideSession:
    """Hold one shell state, one executor and one Python console for the lifetime of a host"""

    def __init__(
        self,
        home: str,
        environment: dict[str, str],
        host_command_names: list[str],
        start_host_call: HostCallStarter,
        write_output: TextWriter,
        write_error: TextWriter,
    ):
        """Build the shell state and register every command

        Args:
            home: The home directory, which is also the starting directory
            environment: The variables the shell starts with
            host_command_names: The commands the host runs itself
            start_host_call: Starts one host command and returns its handle
            write_output: Receives standard output chunks as they are written
            write_error: Receives standard error chunks as they are written
        """
        self.registry = CommandRegistry()
        for name in host_command_names:
            self.registry.register(HostCommand(name, start_host_call))
        self.executor = Executor(self.registry)
        self.executor.builtins[CD_BUILTIN_NAME] = self.change_directory
        self.state = ShellState(
            cwd=Path(home), write_output=write_output, write_error=write_error, variables=dict(environment)
        )
        self.state.variables.setdefault(HOME_VARIABLE, home)
        self.state.variables.setdefault(PWD_VARIABLE, home)
        self.console: Any = None
        self.write_output = write_output
        self.write_error = write_error

    def command_names(self) -> list[str]:
        """Return every command and builtin the shell knows, sorted"""
        return sorted(set(self.registry.names()) | set(self.executor.builtins))

    async def change_directory(self, arguments: list[str], stdin: Any, state: ShellState) -> int:
        """Run the engine's cd, then move the process to the same directory so host-run Python follows the shell

        Args:
            arguments: The arguments given to cd
            stdin: Ignored
            state: The shell state whose directory changes

        Returns:
            The exit code of cd
        """
        exit_code = await Executor.builtin_cd(self.executor, arguments, stdin, state)
        if exit_code == EXIT_CODE_SUCCESS and state.cwd.is_dir():
            os.chdir(state.cwd)
        return exit_code

    async def run(self, script: str) -> str:
        """Run a script and return the exit code, directory and variables as JSON

        A failure inside the engine or a command is reported on standard error rather than raised, so the
        host always learns the directory and variables the shell holds

        Args:
            script: The script text

        Returns:
            A JSON object with ``exit_code``, ``cwd`` and ``environment``
        """
        try:
            exit_code = await self.executor.execute_script(script, self.state)
        except KeyboardInterrupt:
            exit_code = EXIT_CODE_INTERRUPTED
            self.state.last_exit_code = exit_code
        except Exception:
            self.write_error(traceback.format_exc())
            exit_code = EXIT_CODE_FAILURE
            self.state.last_exit_code = exit_code
        return json.dumps(
            {"exit_code": exit_code, "cwd": str(self.state.cwd), "environment": dict(self.state.variables)}
        )

    def repl_start(self) -> str:
        """Open a fresh Python console and return its banner"""
        from pyodide.console import BANNER, PyodideConsole

        self.console = PyodideConsole(
            stdout_callback=self.write_output, stderr_callback=self.write_error, filename=CONSOLE_FILENAME
        )
        return BANNER

    async def repl_feed(self, line: str) -> str:
        """Push one line into the console and return its status as JSON

        Args:
            line: The line typed at the REPL prompt

        Returns:
            A JSON object with ``status`` set to done, more, error or exit
        """
        from pyodide.console import repr_shorten

        console = self.console
        if console is None:
            return json.dumps({"status": REPL_STATUS_EXIT})
        if line.strip() in REPL_EXIT_WORDS and not console.buffer:
            self.console = None
            return json.dumps({"status": REPL_STATUS_EXIT})
        future = console.push(line)
        if future.syntax_check == REPL_SYNTAX_INCOMPLETE:
            return json.dumps({"status": REPL_STATUS_MORE})
        try:
            value = await future
        except SystemExit:
            self.console = None
            return json.dumps({"status": REPL_STATUS_EXIT})
        except BaseException:
            self.write_error(future.formatted_error or "")
            return json.dumps({"status": REPL_STATUS_ERROR})
        if value is not None:
            self.write_output(repr_shorten(value) + "\n")
        return json.dumps({"status": REPL_STATUS_DONE})

    def repl_discard(self) -> None:
        """Forget the lines of a block the console is still waiting to see finished"""
        if self.console is not None:
            self.console.buffer = []

    def repl_complete(self, text: str) -> str:
        """Return the console's completions for the end of a line as JSON

        Args:
            text: The line up to the cursor

        Returns:
            A JSON object with ``candidates`` and ``word_start``
        """
        if self.console is None:
            return json.dumps({"candidates": [], "word_start": len(text)})
        candidates, word_start = self.console.complete(text)
        return json.dumps({"candidates": candidates, "word_start": word_start})
