"""Implement the which command, which locates the commands the shell knows"""

# Standard libraries
from collections.abc import Callable

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

COMMAND_DIRECTORY = "/usr/bin"


class WhichCommand(Command):
    """Print the path each named command would run from"""

    name = "which"
    summary = "locate a command"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def __init__(self, list_names: Callable[[], list[str]]):
        """Bind to the registry that knows the names

        Args:
            list_names: Returns every registered command name
        """
        self.list_names = list_names

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print one path per known name, failing when any name is unknown

        Args:
            invocation: The call to perform

        Returns:
            The paths, and exit code one when any name was not found
        """
        parser = CommandArgumentParser("which", "Locate a command")
        parser.add_argument("-a", "--all", action="store_true", help="print all matching pathnames of each argument")
        parser.add_argument("-s", "--silent", action="store_true", help="print nothing, only return an exit status")
        parser.add_argument("names", nargs="+", help="the commands to locate")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        known = set(self.list_names())
        found = [name for name in parsed.names if name in known]
        exit_code = EXIT_CODE_SUCCESS if len(found) == len(parsed.names) else EXIT_CODE_FAILURE
        if parsed.silent:
            return CommandResult(stdout="", exit_code=exit_code)
        return CommandResult(stdout="".join(f"{COMMAND_DIRECTORY}/{name}\n" for name in found), exit_code=exit_code)
