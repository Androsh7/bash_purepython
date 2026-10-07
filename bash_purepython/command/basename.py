"""Implement the basename command"""

# Standard libraries
from pathlib import PurePosixPath

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS


def strip_directory_and_suffix(name: str, suffix: str | None) -> str:
    """Return the final component of a path without an optional suffix

    Args:
        name: The path as written
        suffix: A suffix to remove when the name ends with it and is not only the suffix

    Returns:
        The base name
    """
    base = PurePosixPath(name.replace("\\", "/")).name or name
    if suffix and base.endswith(suffix) and base != suffix:
        base = base[: -len(suffix)]
    return base


class BasenameCommand(Command):
    """Strip the directory and an optional suffix from a file name"""

    name = "basename"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print each path's final component

        Args:
            invocation: The call to perform

        Returns:
            One base name per line
        """
        parser = CommandArgumentParser("basename", "Strip directory and optional suffix from a filename")
        parser.add_argument("-s", "--suffix", default=None, help="suffix to remove")
        parser.add_argument("-a", "--multiple", action="store_true", help="support multiple arguments")
        parser.add_argument("name", help="path")
        parser.add_argument("extra", nargs="*", help="suffix, or extra paths with -a")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        names = [parsed.name]
        suffix = parsed.suffix
        if parsed.multiple or parsed.suffix is not None:
            names += parsed.extra
        elif parsed.extra:
            suffix = parsed.extra[0]
        text = "".join(strip_directory_and_suffix(name, suffix) + "\n" for name in names)
        return CommandResult(stdout=text, exit_code=EXIT_CODE_SUCCESS)
