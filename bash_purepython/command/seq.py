"""Implement the seq command"""

# Standard libraries
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import as_async_iterator

DEFAULT_SEPARATOR = "\n"
MAXIMUM_NUMBER_COUNT = 3


def format_number(value: float, all_integers: bool, width: int) -> str:
    """Return one number as seq prints it

    Args:
        value: The number
        all_integers: Whether every bound was an integer, so the number prints without decimals
        width: The minimum width, padded with leading zeros, or zero for none

    Returns:
        The number as text
    """
    text = str(int(value)) if all_integers else f"{value:g}"
    if width and len(text.lstrip("-")) < width:
        sign = "-" if text.startswith("-") else ""
        text = sign + text.lstrip("-").rjust(width, "0")
    return text


async def count(
    first: float, increment: float, last: float, all_integers: bool, separator: str, width: int
) -> AsyncIterator[str]:
    """Yield the sequence from first to last, each followed by the separator

    Args:
        first: The first number
        increment: The step, never zero
        last: The bound the sequence may not pass
        all_integers: Whether numbers print without decimals
        separator: Text after each number, the last one being followed by a newline instead
        width: The minimum width to pad numbers to, or zero

    Yields:
        Each number with its separator
    """
    current = first
    previous: str | None = None
    while (increment > 0 and current <= last) or (increment < 0 and current >= last):
        if previous is not None:
            yield previous + separator
        previous = format_number(current, all_integers, width)
        current += increment
    if previous is not None:
        yield previous + "\n"


class SeqCommand(Command):
    """Print a sequence of numbers"""

    name = "seq"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a lazy stream of the numbers

        Args:
            invocation: The call to perform

        Returns:
            The stream, or a usage error for bad bounds
        """
        parser = CommandArgumentParser("seq", "Print a sequence of numbers")
        parser.add_argument("-s", "--separator", default=DEFAULT_SEPARATOR, help="separator between numbers")
        parser.add_argument("-w", "--equal-width", action="store_true", help="pad numbers with leading zeros")
        parser.add_argument("numbers", nargs="+", help="LAST, or FIRST LAST, or FIRST INCREMENT LAST")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        try:
            numbers = [float(number) for number in parsed.numbers]
        except ValueError:
            invocation.state.write_error(f"seq: invalid floating point argument: {' '.join(parsed.numbers)}\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        if len(numbers) > MAXIMUM_NUMBER_COUNT:
            invocation.state.write_error("seq: extra operand\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        if len(numbers) == 1:
            first, increment, last = 1.0, 1.0, numbers[0]
        elif len(numbers) == 2:
            first, increment, last = numbers[0], 1.0, numbers[1]
        else:
            first, increment, last = numbers
        if increment == 0:
            invocation.state.write_error("seq: zero increment\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        all_integers = all(number == int(number) for number in (first, increment, last))
        width = 0
        if parsed.equal_width:
            width = max(len(format_number(number, all_integers, 0).lstrip("-")) for number in (first, last))
        stream = count(first, increment, last, all_integers, parsed.separator, width)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
