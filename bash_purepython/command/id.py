"""Implement the id command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

USER_ID = 1000
GROUP_ID = 1000
DEFAULT_USER_NAME = "user"
USER_VARIABLE_NAME = "USER"


class IdCommand(Command):
    """Print the identity of the one user the shell has"""

    name = "id"
    summary = "print user and group ids"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the full identity, or one of its parts under -u, -g or -G

        Args:
            invocation: The call to perform

        Returns:
            The identity on one line
        """
        parser = CommandArgumentParser(self.name, "Print user and group ids")
        parser.add_argument("-u", "--user", action="store_true", help="print only the user id")
        parser.add_argument("-g", "--group", action="store_true", help="print only the group id")
        parser.add_argument("-G", "--groups", action="store_true", help="print only the group ids")
        parser.add_argument("-n", "--name", action="store_true", help="print names instead of numbers")
        parser.add_argument("-r", "--real", action="store_true", help="print the real id, which is the same")
        parser.add_argument("user_name", nargs="?", default=None, help="the user to describe")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        user_name = state.variables.get(USER_VARIABLE_NAME) or DEFAULT_USER_NAME
        if parsed.user_name is not None and parsed.user_name != user_name:
            state.write_error(f"id: '{parsed.user_name}': no such user\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        if parsed.user:
            value = user_name if parsed.name else str(USER_ID)
        elif parsed.group or parsed.groups:
            value = user_name if parsed.name else str(GROUP_ID)
        elif parsed.name:
            state.write_error("id: cannot print only names or real IDs in default format\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        else:
            value = f"uid={USER_ID}({user_name}) gid={GROUP_ID}({user_name}) groups={GROUP_ID}({user_name})"
        return CommandResult(stdout=value + "\n", exit_code=EXIT_CODE_SUCCESS)
