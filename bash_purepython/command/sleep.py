"""Implement the sleep command"""

# Standard libraries
import asyncio
import re

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR

DURATION_PATTERN = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)([smhd]?)$")
SECONDS_PER_UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration_s(text: str) -> float | None:
    """Return the number of seconds an argument denotes, or None when it is not a duration

    Args:
        text: A number with an optional s, m, h or d suffix

    Returns:
        The seconds, or None
    """
    match = DURATION_PATTERN.match(text)
    if match is None:
        return None
    return float(match.group(1)) * SECONDS_PER_UNIT[match.group(2)]


class SleepCommand(Command):
    """Pause for a duration without blocking other jobs"""

    name = "sleep"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Sleep for the sum of the arguments

        Args:
            invocation: The call to perform

        Returns:
            Empty output and zero, or a usage error when an argument is not a duration
        """
        if not invocation.arguments:
            invocation.state.write_error("sleep: missing operand\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        total_s = 0.0
        for argument in invocation.arguments:
            duration_s = parse_duration_s(argument)
            if duration_s is None:
                invocation.state.write_error(f"sleep: invalid time interval '{argument}'\n")
                return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
            total_s += duration_s
        await asyncio.sleep(total_s)
        return CommandResult(stdout="", exit_code=EXIT_CODE_SUCCESS)
