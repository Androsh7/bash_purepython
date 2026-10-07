"""Implement the realpath command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS


class RealpathCommand(Command):
    """Print the resolved absolute form of each path"""

    name = "realpath"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Resolve each path against the shell's directory

        Args:
            invocation: The call to perform

        Returns:
            One absolute path per line, and exit code one when -e found a missing path
        """
        parser = CommandArgumentParser("realpath", "Print the resolved absolute path")
        parser.add_argument("-e", "--canonicalize-existing", action="store_true", help="all components must exist")
        parser.add_argument("paths", nargs="+", help="paths to resolve")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        exit_code = EXIT_CODE_SUCCESS
        lines: list[str] = []
        for path_text in parsed.paths:
            path = invocation.state.resolve_path(path_text)
            if parsed.canonicalize_existing and not path.exists():
                invocation.state.write_error(f"realpath: {path_text}: No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            lines.append(path.resolve().as_posix() + "\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)
