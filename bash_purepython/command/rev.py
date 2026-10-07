"""Implement the rev command"""

# Standard libraries
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import input_lines
from bash_purepython.shell_state import EXIT_CODE_SUCCESS
from bash_purepython.streams import as_async_iterator


async def reversed_lines(invocation: CommandInvocation, paths: list[str]) -> AsyncIterator[str]:
    """Yield each input line reversed

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The files to read, or none for standard input

    Yields:
        Each line reversed, with a newline
    """
    async for line in input_lines("rev", invocation, paths):
        yield line[::-1] + "\n"


class RevCommand(Command):
    """Reverse each line of input"""

    name = "rev"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of reversed lines

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream
        """
        parser = CommandArgumentParser("rev", "Reverse each line of input")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        return CommandResult(stdout=reversed_lines(invocation, parsed.paths), exit_code=EXIT_CODE_SUCCESS)
