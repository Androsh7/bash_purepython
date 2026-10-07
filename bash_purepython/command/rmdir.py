"""Implement the rmdir command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS


class RmdirCommand(Command):
    """Remove empty directories"""

    name = "rmdir"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Remove each directory, reporting the ones that cannot be removed

        Args:
            invocation: The call to perform

        Returns:
            No output, and exit code one if any directory failed
        """
        parser = CommandArgumentParser("rmdir", "Remove empty directories")
        parser.add_argument("-p", "--parents", action="store_true", help="remove empty parent directories too")
        parser.add_argument("paths", nargs="+", help="directories to remove")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            if not path.exists():
                state.write_error(f"rmdir: failed to remove '{path_text}': No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            if not path.is_dir():
                state.write_error(f"rmdir: failed to remove '{path_text}': Not a directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            try:
                path.rmdir()
            except OSError:
                state.write_error(f"rmdir: failed to remove '{path_text}': Directory not empty\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            if parsed.parents:
                parent = path.parent
                while parent != parent.parent and parent != state.cwd:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        return CommandResult(stdout="", exit_code=exit_code)
