"""Implement the less and more commands, which print their input since the terminal has no paging"""

# Standard libraries
from collections.abc import AsyncIterator
from typing import ClassVar

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import open_source, source_paths
from bash_purepython.shell_state import EXIT_CODE_SUCCESS
from bash_purepython.streams import as_async_iterator, close_iterator

IGNORED_FLAGS = ("-N", "-R", "-S", "-F", "-X", "-e", "-E", "-q", "-i", "-r", "-M", "-m", "-s", "-c", "-d", "-f")


async def page_sources(program: str, invocation: CommandInvocation, paths: list[str]) -> AsyncIterator[str]:
    """Yield every line of every source in order

    Args:
        program: The command name used in error messages
        invocation: The call, providing standard input and the shell state
        paths: The files to read, or none for standard input

    Yields:
        Each line with its newline kept
    """
    for path_text in source_paths(invocation, paths):
        lines = open_source(program, path_text, invocation)
        if lines is None:
            continue
        try:
            async for line in lines:
                yield line
        finally:
            await close_iterator(lines)


class PagerCommand(Command):
    """Print files or standard input in full, as a pager does when the output is not a terminal"""

    name: ClassVar[str]
    summary: ClassVar[str]
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of every source in order, ignoring the display flags a real pager takes

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream
        """
        parser = CommandArgumentParser(self.name, f"Print files, since {self.name} cannot page in this terminal")
        for flag in IGNORED_FLAGS:
            parser.add_argument(flag, action="store_true", dest=f"ignored_{flag[1:]}", help="accepted and ignored")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        stream = page_sources(self.name, invocation, parsed.paths)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)


class LessCommand(PagerCommand):
    """Print files or standard input in place of paging them"""

    name = "less"
    summary = "print files, paging is not available"


class MoreCommand(PagerCommand):
    """Print files or standard input in place of paging them"""

    name = "more"
    summary = "print files, paging is not available"
