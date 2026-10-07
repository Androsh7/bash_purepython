"""Open the files or standard input a text command reads, reporting the ones it cannot"""

# Standard libraries
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.command import CommandInvocation, InputKind
from bash_purepython.command.lines import file_lines, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, NULL_DEVICE_PATH
from bash_purepython.streams import as_async_iterator

STDIN_PATH = "-"
STDIN_LABEL = "(standard input)"


def open_source(program: str, path_text: str, invocation: CommandInvocation) -> AsyncIterator[str] | None:
    """Return the lines of one source, or None after reporting why it cannot be read

    A missing or unreadable source sets the invocation's exit status to one

    Args:
        program: The command name used in error messages
        path_text: A file path, ``-`` for standard input, or the null device
        invocation: The call, providing standard input and the shell state

    Returns:
        An async iterator over the lines with newlines kept, or None
    """
    if path_text == STDIN_PATH:
        if invocation.stdin_kind == InputKind.ARGUMENTS:
            return as_async_iterator(())
        return stdin_lines(invocation.stdin, invocation.stdin_kind)
    if path_text == NULL_DEVICE_PATH:
        return as_async_iterator(())
    path = invocation.state.resolve_path(path_text)
    if path.is_dir():
        invocation.state.write_error(f"{program}: {path_text}: Is a directory\n")
        invocation.exit_status.code = EXIT_CODE_FAILURE
        return None
    if not path.exists():
        invocation.state.write_error(f"{program}: {path_text}: No such file or directory\n")
        invocation.exit_status.code = EXIT_CODE_FAILURE
        return None
    return file_lines(path)


def source_paths(invocation: CommandInvocation, paths: list[str]) -> list[str]:
    """Return the sources a command should read: the paths given, or standard input when there are none

    Args:
        invocation: The call, whose input kind says whether standard input exists
        paths: The paths named on the command line

    Returns:
        The paths, or ``-`` alone when nothing was named
    """
    return paths or [STDIN_PATH]


async def input_lines(program: str, invocation: CommandInvocation, paths: list[str]) -> AsyncIterator[str]:
    """Yield every line of every source in order, without trailing newlines

    Args:
        program: The command name used in error messages
        invocation: The call, providing standard input and the shell state
        paths: The paths named on the command line, or none for standard input

    Yields:
        Each line with its newline removed
    """
    for path_text in source_paths(invocation, paths):
        lines = open_source(program, path_text, invocation)
        if lines is None:
            continue
        try:
            async for line in lines:
                yield line.rstrip("\n")
        finally:
            aclose = getattr(lines, "aclose", None)
            if aclose is not None:
                await aclose()
