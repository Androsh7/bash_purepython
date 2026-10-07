"""Implement the date command"""

# Standard libraries
from datetime import UTC, datetime

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

DEFAULT_FORMAT = "%a %b %d %H:%M:%S %Z %Y"
FORMAT_PREFIX = "+"


class DateCommand(Command):
    """Print the current date and time"""

    name = "date"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Format the current time

        Args:
            invocation: The call to perform

        Returns:
            The formatted time and a newline
        """
        parser = CommandArgumentParser("date", "Print the current date and time")
        parser.add_argument("-u", "--utc", action="store_true", help="use UTC")
        parser.add_argument("format", nargs="?", default=None, help="strftime format prefixed with +")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        now = datetime.now(UTC) if parsed.utc else datetime.now().astimezone()
        format_text = parsed.format.removeprefix(FORMAT_PREFIX) if parsed.format else DEFAULT_FORMAT
        return CommandResult(stdout=now.strftime(format_text or DEFAULT_FORMAT) + "\n", exit_code=EXIT_CODE_SUCCESS)
