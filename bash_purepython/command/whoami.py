"""Implement the whoami command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

USER_VARIABLE_NAME = "USER"
DEFAULT_USER_NAME = "user"


class WhoamiCommand(Command):
    """Print the name of the current user"""

    name = "whoami"
    summary = "print effective user name"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the USER variable, or the default name when it is not set

        Args:
            invocation: The call to perform

        Returns:
            The user name on one line
        """
        parser = CommandArgumentParser("whoami", "Print the user name associated with the current user")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        user_name = invocation.state.variables.get(USER_VARIABLE_NAME) or DEFAULT_USER_NAME
        return CommandResult(stdout=f"{user_name}\n", exit_code=EXIT_CODE_SUCCESS)
