"""Implement the mkdir command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS


class MkdirCommand(Command):
    """Create directories"""

    name = "mkdir"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Create each directory, reporting the ones that cannot be created

        Args:
            invocation: The call to perform

        Returns:
            Verbose output when asked, and exit code one if any directory failed
        """
        parser = CommandArgumentParser("mkdir", "Create directories")
        parser.add_argument("-p", "--parents", action="store_true", help="create parents, no error if existing")
        parser.add_argument("-v", "--verbose", action="store_true", help="print each created directory")
        parser.add_argument("paths", nargs="+", help="directories to create")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        exit_code = EXIT_CODE_SUCCESS
        lines: list[str] = []
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            try:
                path.mkdir(parents=parsed.parents, exist_ok=parsed.parents)
            except FileExistsError:
                state.write_error(f"mkdir: cannot create directory '{path_text}': File exists\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            except FileNotFoundError:
                state.write_error(f"mkdir: cannot create directory '{path_text}': No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            if parsed.verbose:
                lines.append(f"mkdir: created directory '{path_text}'\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)
