"""Implement the yes command"""

# Standard libraries
from collections.abc import Iterator

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

DEFAULT_TEXT = "y"


def repeat_forever(line: str) -> Iterator[str]:
    """Yield the same line until the consumer closes the generator

    Args:
        line: The line to repeat, newline included

    Yields:
        The line, endlessly
    """
    while True:
        yield line


class YesCommand(Command):
    """Repeat a line forever"""

    name = "yes"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return an endless stream of the arguments, or of ``y``

        Args:
            invocation: The call to perform

        Returns:
            A lazy stream that only ends when closed
        """
        line = (" ".join(invocation.arguments) or DEFAULT_TEXT) + "\n"
        return CommandResult(stdout=repeat_forever(line), exit_code=EXIT_CODE_SUCCESS)
