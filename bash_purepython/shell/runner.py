"""Run one command module in-process with its standard streams captured"""

# Standard libraries
import contextlib
import functools
import io
import sys
from collections.abc import Sequence
from typing import TextIO

# Project libraries
from bash_purepython.shell.commands import load_command_main
from bash_purepython.shell.models import (
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    OUTPUT_LIMIT_BYTES,
    CommandOutput,
    OutputLimitExceededError,
)

STREAM_ENCODING = "utf-8"


class LimitedBytesIO(io.BytesIO):
    """Hold bytes in memory and refuse to grow past a limit"""

    def __init__(self, limit_bytes: int = OUTPUT_LIMIT_BYTES):
        """Start empty with the given limit

        Args:
            limit_bytes: The most bytes the buffer may hold
        """
        super().__init__()
        self._limit_bytes = limit_bytes

    def write(self, data: bytes | bytearray | memoryview) -> int:
        """Append data unless it would push the buffer past the limit

        Args:
            data: The bytes to append

        Raises:
            OutputLimitExceededError: If the buffer would exceed its limit

        Returns:
            The number of bytes written
        """
        if self.tell() + len(data) > self._limit_bytes:
            raise OutputLimitExceededError(f"output limit of {self._limit_bytes} bytes exceeded")
        return super().write(data)


class OutputCapture:
    """Collect everything a command writes to a text stream or to its byte buffer"""

    def __init__(self, limit_bytes: int = OUTPUT_LIMIT_BYTES):
        """Create an empty capture

        Args:
            limit_bytes: The most bytes the capture may hold
        """
        self._raw = LimitedBytesIO(limit_bytes)
        self.stream: TextIO = io.TextIOWrapper(
            self._raw, encoding=STREAM_ENCODING, errors="replace", newline="", write_through=True
        )

    def getvalue(self) -> bytes:
        """Return every byte written so far"""
        return self._raw.getvalue()


def make_stdin(data: bytes) -> TextIO:
    """Return a text stream over data that also exposes the bytes through .buffer

    Args:
        data: The bytes the command reads as its standard input

    Returns:
        A readable text stream positioned at the start
    """
    return io.TextIOWrapper(io.BytesIO(data), encoding=STREAM_ENCODING, errors="replace", newline="")


def exit_code_from_system_exit(exit_request: SystemExit, stderr: TextIO) -> int:
    """Return the exit code a SystemExit stands for, printing a message code to stderr

    Args:
        exit_request: The SystemExit a command raised
        stderr: Where a string exit code is written as a message

    Returns:
        Zero for None, the integer itself, or one after printing a string
    """
    if exit_request.code is None:
        return EXIT_CODE_SUCCESS
    if isinstance(exit_request.code, int):
        return exit_request.code
    stderr.write(f"{exit_request.code}\n")
    return EXIT_CODE_FAILURE


def run_command(name: str, argv: Sequence[str], stdin_data: bytes) -> CommandOutput:
    """Run one package command with argv and stdin, collecting what it wrote

    A SystemExit becomes the exit code, a BrokenPipeError is a clean stop, and any
    other exception becomes a one-line error on stderr with exit code one

    Args:
        name: The command module to run
        argv: The full argument vector, the command name first
        stdin_data: The bytes the command reads from standard input

    Raises:
        CommandNotFoundError: If the package has no such command

    Returns:
        The captured stdout and stderr bytes and the exit code
    """
    main = load_command_main(name)
    stdout_capture, stderr_capture = OutputCapture(), OutputCapture()
    saved_argv, saved_stdin = sys.argv, sys.stdin
    sys.argv = list(argv)
    sys.stdin = make_stdin(stdin_data)
    exit_code = EXIT_CODE_SUCCESS
    try:
        with contextlib.redirect_stdout(stdout_capture.stream), contextlib.redirect_stderr(stderr_capture.stream):
            main()
    except SystemExit as exit_request:
        exit_code = exit_code_from_system_exit(exit_request, stderr_capture.stream)
    except BrokenPipeError:
        exit_code = EXIT_CODE_SUCCESS
    except Exception as error:
        stderr_capture.stream.write(f"{name}: {error}\n")
        exit_code = EXIT_CODE_FAILURE
    finally:
        sys.argv, sys.stdin = saved_argv, saved_stdin
    return CommandOutput(stdout=stdout_capture.getvalue(), stderr=stderr_capture.getvalue(), exit_code=exit_code)


@functools.cache
def command_help_text(name: str) -> str:
    """Return the --help output of a package command

    Args:
        name: The command to ask

    Raises:
        CommandNotFoundError: If the package has no such command

    Returns:
        The help text argparse printed, decoded as text
    """
    output = run_command(name, [name, "--help"], b"")
    return output.stdout.decode(STREAM_ENCODING, "replace")
