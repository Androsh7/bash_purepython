"""Implement the printf command"""

# Standard libraries
import re

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR, ShellState

DIRECTIVE_PATTERN = re.compile(r"%([-+ #0]*)(\*|\d+)?(?:\.(\*|\d*))?([a-zA-Z%])")
SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "e": "\x1b",
    "\\": "\\",
    '"': '"',
}
INTEGER_CONVERSIONS = frozenset("diuoxXc")
FLOAT_CONVERSIONS = frozenset("feEgG")
OCTAL_DIGITS = "01234567"
MAXIMUM_OCTAL_ESCAPE_DIGITS = 3
MAXIMUM_HEX_ESCAPE_DIGITS = 2


def interpret_escapes(text: str) -> str:
    """Return text with printf backslash escapes replaced

    Args:
        text: A format string or a ``%b`` argument

    Returns:
        The text with escapes interpreted
    """
    pieces: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character != "\\" or index + 1 >= len(text):
            pieces.append(character)
            index += 1
            continue
        escaped = text[index + 1]
        if escaped in SIMPLE_ESCAPES:
            pieces.append(SIMPLE_ESCAPES[escaped])
            index += 2
        elif escaped in OCTAL_DIGITS:
            digits_end = index + 1
            while digits_end < len(text) and digits_end - (index + 1) < MAXIMUM_OCTAL_ESCAPE_DIGITS:
                if text[digits_end] not in OCTAL_DIGITS:
                    break
                digits_end += 1
            pieces.append(chr(int(text[index + 1 : digits_end], 8)))
            index = digits_end
        elif escaped == "x":
            digits_end = index + 2
            while digits_end < len(text) and digits_end - (index + 2) < MAXIMUM_HEX_ESCAPE_DIGITS:
                if text[digits_end] not in "0123456789abcdefABCDEF":
                    break
                digits_end += 1
            if digits_end == index + 2:
                pieces.append("\\x")
            else:
                pieces.append(chr(int(text[index + 2 : digits_end], 16)))
            index = digits_end
        else:
            pieces.append("\\" + escaped)
            index += 2
    return "".join(pieces)


def parse_integer(text: str, state: ShellState) -> tuple[int, bool]:
    """Return the integer an argument denotes, reporting an invalid one

    Args:
        text: The argument
        state: The shell state whose error sink receives the complaint

    Returns:
        The value, zero when invalid, and whether it was valid
    """
    if text == "":
        return 0, True
    if len(text) >= 2 and text[0] in "'\"":
        return ord(text[1]), True
    try:
        return int(text, 0), True
    except ValueError:
        pass
    try:
        return int(float(text)), False
    except ValueError:
        state.write_error(f"printf: {text}: invalid number\n")
        return 0, False


def parse_float(text: str, state: ShellState) -> tuple[float, bool]:
    """Return the float an argument denotes, reporting an invalid one

    Args:
        text: The argument
        state: The shell state whose error sink receives the complaint

    Returns:
        The value, zero when invalid, and whether it was valid
    """
    if text == "":
        return 0.0, True
    try:
        return float(text), True
    except ValueError:
        state.write_error(f"printf: {text}: invalid number\n")
        return 0.0, False


class PrintfFormatter:
    """Apply one format string to a list of arguments, reusing the format until they run out"""

    def __init__(self, format_text: str, arguments: list[str], state: ShellState):
        """Prepare to format

        Args:
            format_text: The format with its escapes still raw
            arguments: The arguments the directives consume
            state: The shell state whose error sink receives complaints
        """
        self.format_text = format_text
        self.arguments = arguments
        self.state = state
        self.position = 0
        self.exit_code = EXIT_CODE_SUCCESS

    def format_all(self) -> str:
        """Return the formatted output

        Returns:
            The format applied as many times as the arguments require, at least once
        """
        pieces: list[str] = []
        while True:
            consumed_before = self.position
            pieces.append(self.format_once())
            if self.position >= len(self.arguments) or self.position == consumed_before:
                break
        return "".join(pieces)

    def next_argument(self) -> str:
        """Return the next unconsumed argument, or an empty string when none remain"""
        if self.position < len(self.arguments):
            argument = self.arguments[self.position]
            self.position += 1
            return argument
        return ""

    def format_once(self) -> str:
        """Return the format applied one time

        Returns:
            The text, with literal escapes interpreted and directives substituted
        """
        pieces: list[str] = []
        index = 0
        while index < len(self.format_text):
            match = DIRECTIVE_PATTERN.search(self.format_text, index)
            if match is None:
                pieces.append(interpret_escapes(self.format_text[index:]))
                break
            pieces.append(interpret_escapes(self.format_text[index : match.start()]))
            pieces.append(self.format_directive(match))
            index = match.end()
        return "".join(pieces)

    def format_directive(self, match: re.Match[str]) -> str:
        """Return the text for one directive

        Args:
            match: The matched directive

        Returns:
            The formatted argument
        """
        flags, width, precision, conversion = match.group(1), match.group(2), match.group(3), match.group(4)
        if conversion == "%":
            return "%"
        if width == "*":
            width = str(parse_integer(self.next_argument(), self.state)[0])
        if precision == "*":
            precision = str(parse_integer(self.next_argument(), self.state)[0])
        specification = "%" + flags + (width or "") + ("." + precision if precision is not None else "")
        argument = self.next_argument()
        if conversion == "b":
            return (specification + "s") % interpret_escapes(argument)
        if conversion == "s":
            return (specification + "s") % argument
        if conversion == "q":
            return (specification + "s") % quote_for_shell(argument)
        if conversion == "c":
            return (specification + "s") % (argument[:1] if argument else "")
        if conversion in INTEGER_CONVERSIONS:
            value, valid = parse_integer(argument, self.state)
            if not valid:
                self.exit_code = EXIT_CODE_FAILURE
            python_conversion = "d" if conversion in "diu" else conversion
            return (specification + python_conversion) % value
        if conversion in FLOAT_CONVERSIONS:
            value, valid = parse_float(argument, self.state)
            if not valid:
                self.exit_code = EXIT_CODE_FAILURE
            return (specification + conversion) % value
        self.state.write_error(f"printf: %{conversion}: invalid directive\n")
        self.exit_code = EXIT_CODE_FAILURE
        return ""


def quote_for_shell(text: str) -> str:
    """Return text quoted so the shell would read it back as one word

    Args:
        text: The text to quote

    Returns:
        The text with every character the shell would treat specially escaped by a backslash
    """
    if not text:
        return "''"
    return re.sub(r"([^\w@%+=:,./-])", r"\\\1", text)


class PrintfCommand(Command):
    """Format and print arguments"""

    name = "printf"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Apply the first argument as a format to the rest

        Args:
            invocation: The call to perform

        Returns:
            The formatted text and an exit code reflecting any invalid arguments
        """
        arguments = list(invocation.arguments)
        if arguments and arguments[0] == "--":
            arguments.pop(0)
        if not arguments:
            invocation.state.write_error("printf: usage: printf format [arguments]\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        formatter = PrintfFormatter(arguments[0], arguments[1:], invocation.state)
        text = formatter.format_all()
        return CommandResult(stdout=text, exit_code=formatter.exit_code)
