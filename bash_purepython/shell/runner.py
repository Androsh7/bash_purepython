"""Run one command module in-process against the streams it is given"""

# Standard libraries
import contextlib
import functools
import sys
from collections.abc import Sequence
from typing import TextIO

# Project libraries
from bash_purepython.shell.commands import load_command_main
from bash_purepython.shell.models import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, CommandOutput
from bash_purepython.shell.streams import STREAM_ENCODING, OutputCapture, make_stdin


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


def run_command_on_streams(name: str, argv: Sequence[str], stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    """Run one package command with its standard streams bound to the ones given

    A SystemExit becomes the exit code, a BrokenPipeError is a clean stop, and any
    other exception becomes a one-line error on stderr with exit code one. A
    KeyboardInterrupt propagates after the streams are restored, so the caller can
    abort everything else it meant to run

    Args:
        name: The command module to run
        argv: The full argument vector, the command name first
        stdin: What the command reads
        stdout: Where the command's output goes
        stderr: Where the command's errors go

    Raises:
        CommandNotFoundError: If the package has no such command
        KeyboardInterrupt: If the command was interrupted

    Returns:
        The exit code
    """
    main = load_command_main(name)
    saved_argv, saved_stdin = sys.argv, sys.stdin
    sys.argv = list(argv)
    sys.stdin = stdin
    exit_code = EXIT_CODE_SUCCESS
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            main()
    except SystemExit as exit_request:
        exit_code = exit_code_from_system_exit(exit_request, stderr)
    except BrokenPipeError:
        exit_code = EXIT_CODE_SUCCESS
    except Exception as error:
        stderr.write(f"{name}: {error}\n")
        exit_code = EXIT_CODE_FAILURE
    finally:
        sys.argv, sys.stdin = saved_argv, saved_stdin
        stdout.flush()
        stderr.flush()
    return exit_code


def run_command(name: str, argv: Sequence[str], stdin_data: bytes) -> CommandOutput:
    """Run one package command with argv and stdin, collecting what it wrote

    Args:
        name: The command module to run
        argv: The full argument vector, the command name first
        stdin_data: The bytes the command reads from standard input

    Raises:
        CommandNotFoundError: If the package has no such command

    Returns:
        The captured stdout and stderr bytes and the exit code
    """
    stdout_capture, stderr_capture = OutputCapture(), OutputCapture()
    exit_code = run_command_on_streams(name, argv, make_stdin(stdin_data), stdout_capture.stream, stderr_capture.stream)
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
