"""Implement the env command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS


class EnvCommand(Command):
    """Print the shell's variables"""

    name = "env"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print every variable as name=value

        Args:
            invocation: The call to perform

        Returns:
            One entry per line, or NUL-separated with -0
        """
        parser = CommandArgumentParser("env", "Print the environment")
        parser.add_argument("-0", "--null", dest="null", action="store_true", help="end entries with NUL")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        separator = "\0" if parsed.null else "\n"
        entries = [f"{name}={value}{separator}" for name, value in invocation.state.variables.items()]
        return CommandResult(stdout="".join(entries), exit_code=EXIT_CODE_SUCCESS)
