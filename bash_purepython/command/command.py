"""Define the contract every command implements and the kinds of data it can exchange"""

# Standard libraries
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

# Project libraries
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, ShellState


class OutputKind(StrEnum):
    """Name the shapes a command can produce on standard output"""

    STREAM_TEXT = "stream_text"
    TEXT = "text"
    STREAM_BYTES = "stream_bytes"
    BYTES = "bytes"


class InputKind(StrEnum):
    """Name the shapes a command can accept on standard input, or that it takes none"""

    STREAM_TEXT = "stream_text"
    TEXT = "text"
    STREAM_BYTES = "stream_bytes"
    BYTES = "bytes"
    ARGUMENTS = "arguments"


class ExitStatus:
    """Carry the exit code of a streaming command, which it may change while its output is still being read"""

    def __init__(self, code: int = EXIT_CODE_SUCCESS):
        """Start with a code

        Args:
            code: The exit code to report unless the command changes it
        """
        self.code = code


@dataclass(frozen=True)
class CommandInvocation:
    """Hold one call of a command with its input already in the negotiated kind

    Standard input in a streaming kind is an async iterator. A streaming command reports failure found while
    producing output by setting ``exit_status.code``
    """

    arguments: list[str]
    stdin: Any
    stdin_kind: InputKind
    stdout_kind: OutputKind
    state: ShellState
    exit_status: ExitStatus = field(default_factory=ExitStatus)


@dataclass(frozen=True)
class CommandResult:
    """Hold what one command call produced

    For a streaming output the exit code is provisional: the invocation's exit status, or a synchronous
    generator's return value, replaces it once the stream is exhausted
    """

    stdout: Any
    exit_code: int


class Command(ABC):
    """Declare the kinds a command exchanges and how it runs"""

    name: ClassVar[str]
    input_kinds: ClassVar[frozenset[InputKind]]
    output_kinds: ClassVar[frozenset[OutputKind]]

    @abstractmethod
    def run(self, invocation: CommandInvocation) -> CommandResult | Awaitable[CommandResult]:
        """Run the command once, synchronously or as a coroutine

        Args:
            invocation: The arguments, input, requested output kind, and shell state

        Returns:
            The output in the requested kind and the exit code, directly or through an awaitable
        """
