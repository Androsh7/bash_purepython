"""Implement the help command, which lists every registered command"""

# Standard libraries
from collections.abc import Callable

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

NAME_SEPARATOR = "  "


class HelpCommand(Command):
    """Print the names of every command the shell can run"""

    name = "help"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def __init__(self, list_names: Callable[[], list[str]]):
        """Bind to the registry that knows the names

        Args:
            list_names: Returns every registered command name, sorted
        """
        self.list_names = list_names

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the names on one line

        Args:
            invocation: The call to perform

        Returns:
            The names separated by two spaces
        """
        parser = CommandArgumentParser("help", "List every available command")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        return CommandResult(stdout=NAME_SEPARATOR.join(self.list_names()) + "\n", exit_code=EXIT_CODE_SUCCESS)
