"""Implement the help command, which lists every registered command with its summary"""

# Standard libraries
from collections.abc import Callable

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

NAME_SEPARATOR = "  "
NAME_COLUMN_WIDTH = 12


class HelpCommand(Command):
    """Print the names of every command the shell can run, each with its one-line summary"""

    name = "help"
    summary = "list every available command"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def __init__(self, list_names: Callable[[], list[str]], list_summaries: Callable[[], dict[str, str]] | None = None):
        """Bind to the registry that knows the names

        Args:
            list_names: Returns every registered command name, sorted
            list_summaries: Returns the summary of every registered command by name, or None for names only
        """
        self.list_names = list_names
        self.list_summaries = list_summaries

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print one line per command, or every name on one line with ``-s``

        Args:
            invocation: The call to perform

        Returns:
            The listing and exit code zero
        """
        parser = CommandArgumentParser("help", "List every available command")
        parser.add_argument("-s", "--short", action="store_true", help="print only the names, on one line")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        names = self.list_names()
        summaries = self.list_summaries() if self.list_summaries is not None else {}
        if parsed.short or not any(summaries.get(name) for name in names):
            return CommandResult(stdout=NAME_SEPARATOR.join(names) + "\n", exit_code=EXIT_CODE_SUCCESS)
        lines = [f"{name:<{NAME_COLUMN_WIDTH}}{NAME_SEPARATOR}{summaries.get(name, '')}".rstrip() for name in names]
        return CommandResult(stdout="\n".join(lines) + "\n", exit_code=EXIT_CODE_SUCCESS)
