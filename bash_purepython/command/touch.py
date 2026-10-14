"""Implement the touch command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState


def touch_path(path_text: str, create: bool, state: ShellState) -> bool:
    """Create one file, or update the modification time of one that exists

    Args:
        path_text: The path as written on the command line
        create: Whether a missing file is created
        state: The shell state for resolving the path and reporting errors

    Returns:
        True when the path was touched or skipped, False when it was reported as an error
    """
    path = state.resolve_path(path_text)
    if not create and not path.exists():
        return True
    try:
        path.touch(exist_ok=True)
    except FileNotFoundError:
        state.write_error(f"touch: cannot touch '{path_text}': No such file or directory\n")
        return False
    except PermissionError:
        state.write_error(f"touch: cannot touch '{path_text}': Permission denied\n")
        return False
    return True


class TouchCommand(Command):
    """Create files or update their modification time"""

    name = "touch"
    summary = "change file timestamps"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Touch each path in turn

        Args:
            invocation: The call to perform

        Returns:
            No output, with exit code one when any path could not be touched
        """
        parser = CommandArgumentParser("touch", "Update the access and modification times of each file")
        parser.add_argument("-c", "--no-create", action="store_true", help="do not create any files")
        parser.add_argument("-a", action="store_true", help="change only the access time")
        parser.add_argument("-m", action="store_true", help="change only the modification time")
        parser.add_argument("-f", action="store_true", help="ignored")
        parser.add_argument("paths", nargs="+", help="files to create or update")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        results = [touch_path(path_text, not parsed.no_create, invocation.state) for path_text in parsed.paths]
        return CommandResult(stdout="", exit_code=EXIT_CODE_SUCCESS if all(results) else EXIT_CODE_FAILURE)
