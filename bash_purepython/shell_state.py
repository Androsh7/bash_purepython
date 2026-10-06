"""Define the state one shell session carries between commands, plus the errors and control-flow signals"""

# Standard libraries
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXIT_CODE_SUCCESS = 0
EXIT_CODE_FAILURE = 1
EXIT_CODE_USAGE_ERROR = 2
EXIT_CODE_COMMAND_NOT_FOUND = 127
EXIT_CODE_BROKEN_PIPE = 141
EXIT_CODE_MODULUS = 256
NULL_DEVICE_PATH = "/dev/null"


class ShellError(Exception):
    """Signal a failure raised by the shell itself rather than by a command"""


class ShellSyntaxError(ShellError):
    """Signal command text the shell cannot parse"""


class ExpansionError(ShellError):
    """Signal a word expansion the shell cannot perform, which stops the script"""


class UnsupportedBlockError(ShellError):
    """Signal a block type the executor does not handle yet"""

    def __init__(self, block_text: str):
        """Record the text of the unsupported block

        Args:
            block_text: The command text that could not be planned
        """
        super().__init__(f"unsupported command: {block_text}")
        self.block_text = block_text


class CommandNotFoundError(ShellError):
    """Signal a command name the shell does not know"""

    def __init__(self, name: str):
        """Record the unknown command name

        Args:
            name: The command name that was not found
        """
        super().__init__(f"{name}: command not found")
        self.name = name


class OutputLimitExceededError(Exception):
    """Signal that a captured command wrote more than the executor allows"""

    def __init__(self, collector: object, limit_characters: int):
        """Record which collector overflowed

        Args:
            collector: The object that was collecting the output
            limit_characters: The limit that was exceeded
        """
        super().__init__(f"output exceeded {limit_characters} characters")
        self.collector = collector
        self.limit_characters = limit_characters


class ControlFlowSignal(Exception):  # noqa: N818
    """Carry a shell control-flow builtin up to the construct that handles it"""


class BreakLoop(ControlFlowSignal):
    """Leave the innermost loop"""


class ContinueLoop(ControlFlowSignal):
    """Start the next iteration of the innermost loop"""


class ReturnFromFunction(ControlFlowSignal):
    """Leave the current function with an exit code"""

    def __init__(self, exit_code: int):
        """Record the exit code to return

        Args:
            exit_code: The value the function call evaluates to
        """
        super().__init__(exit_code)
        self.exit_code = exit_code


class ExitShell(ControlFlowSignal):
    """Stop the whole script with an exit code"""

    def __init__(self, exit_code: int):
        """Record the exit code to stop with

        Args:
            exit_code: The value the script evaluates to
        """
        super().__init__(exit_code)
        self.exit_code = exit_code


def write_to_stdout(text: str) -> None:
    """Write text to the process standard output

    Args:
        text: The text to write
    """
    sys.stdout.write(text)


def write_to_stderr(text: str) -> None:
    """Write text to the process standard error

    Args:
        text: The text to write
    """
    sys.stderr.write(text)


@dataclass
class ShellState:
    """Hold everything a running script can read or change"""

    cwd: Path
    write_output: Callable[[str], None]
    write_error: Callable[[str], None]
    variables: dict[str, str] = field(default_factory=dict)
    functions: dict[str, str] = field(default_factory=dict)
    positional_arguments: list[str] = field(default_factory=list)
    last_exit_code: int = EXIT_CODE_SUCCESS
    pending_stdin: Any = None
    loop_depth: int = 0
    function_depth: int = 0

    def __post_init__(self):
        """Wrap both sinks so every chunk is recorded as well as streamed to the terminal as it is written"""
        self.stdout_chunks: list[str] = []
        self.stderr_chunks: list[str] = []
        terminal_output = self.write_output
        terminal_error = self.write_error

        def record_and_write_output(text: str) -> None:
            self.stdout_chunks.append(text)
            terminal_output(text)

        def record_and_write_error(text: str) -> None:
            self.stderr_chunks.append(text)
            terminal_error(text)

        self.write_output = record_and_write_output
        self.write_error = record_and_write_error

    @property
    def stdout(self) -> str:
        """Return everything written to standard output so far"""
        return "".join(self.stdout_chunks)

    @property
    def stderr(self) -> str:
        """Return everything written to standard error so far"""
        return "".join(self.stderr_chunks)

    @classmethod
    def for_terminal(cls, cwd: Path | None = None):
        """Return a state that writes straight to the process streams

        Args:
            cwd: The starting directory, defaulting to the process working directory
        """
        return cls(cwd=cwd or Path.cwd(), write_output=write_to_stdout, write_error=write_to_stderr)

    def copy(self):
        """Return an independent copy for a subshell, sharing only the output sinks"""
        return ShellState(
            cwd=self.cwd,
            write_output=self.write_output,
            write_error=self.write_error,
            variables=dict(self.variables),
            functions=dict(self.functions),
            positional_arguments=list(self.positional_arguments),
            last_exit_code=self.last_exit_code,
            loop_depth=self.loop_depth,
            function_depth=self.function_depth,
        )

    def resolve_path(self, path_text: str) -> Path:
        """Return a path made absolute against the current directory

        Args:
            path_text: A path as written on the command line

        Returns:
            The absolute path
        """
        path = Path(path_text).expanduser()
        return path if path.is_absolute() else self.cwd / path
