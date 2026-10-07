"""Implement the pwd command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS


class PwdCommand(Command):
    """Print the shell's current directory"""

    name = "pwd"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the directory the shell state is in

        Args:
            invocation: The call to perform

        Returns:
            The directory and a newline
        """
        parser = CommandArgumentParser("pwd", "Print the current working directory")
        parser.add_argument("-L", "--logical", action="store_true", help="accepted for compatibility")
        parser.add_argument("-P", "--physical", action="store_true", help="accepted for compatibility")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        return CommandResult(stdout=f"{invocation.state.cwd.as_posix()}\n", exit_code=EXIT_CODE_SUCCESS)
