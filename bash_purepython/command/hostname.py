"""Implement the hostname command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

DEFAULT_HOSTNAME = "androsh7"
HOSTNAME_VARIABLE_NAME = "HOSTNAME"
DOMAIN_SEPARATOR = "."


class HostnameCommand(Command):
    """Print the name of the in-browser machine"""

    name = "hostname"
    summary = "print the host name"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the host name, taken from the HOSTNAME variable when it is set

        Args:
            invocation: The call to perform

        Returns:
            The name on one line
        """
        parser = CommandArgumentParser(self.name, "Print the host name")
        parser.add_argument("-s", "--short", action="store_true", help="print the name up to the first dot")
        parser.add_argument("-f", "--fqdn", action="store_true", help="print the full name")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        hostname = invocation.state.variables.get(HOSTNAME_VARIABLE_NAME) or DEFAULT_HOSTNAME
        if parsed.short:
            hostname = hostname.split(DOMAIN_SEPARATOR, 1)[0]
        return CommandResult(stdout=hostname + "\n", exit_code=EXIT_CODE_SUCCESS)
