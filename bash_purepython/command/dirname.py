"""Implement the dirname command"""

# Standard libraries
from pathlib import PurePosixPath

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

CURRENT_DIRECTORY = "."


def strip_last_component(name: str) -> str:
    """Return a path with its final component removed

    Args:
        name: The path as written

    Returns:
        The parent, or ``.`` when the path has no directory part
    """
    parent = str(PurePosixPath(name.replace("\\", "/")).parent)
    return parent if parent else CURRENT_DIRECTORY


class DirnameCommand(Command):
    """Strip the last component from a file name"""

    name = "dirname"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print each path without its final component

        Args:
            invocation: The call to perform

        Returns:
            One directory per line
        """
        parser = CommandArgumentParser("dirname", "Strip last component from a filename")
        parser.add_argument("names", nargs="+", help="paths")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        text = "".join(strip_last_component(name) + "\n" for name in parsed.names)
        return CommandResult(stdout=text, exit_code=EXIT_CODE_SUCCESS)
