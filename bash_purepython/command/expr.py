"""Implement the expr command"""

# Standard libraries
import re
from enum import StrEnum

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sed import translate_regex
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR

INTEGER_PATTERN = re.compile(r"^[+-]?[0-9]+$")
FIRST_POSITION = 1
NOT_FOUND_POSITION = 0
TRUE_TEXT = "1"
FALSE_TEXT = "0"
EMPTY_MATCH_LENGTH = "0"
OR_OPERATOR = "|"
AND_OPERATOR = "&"
MATCH_OPERATOR = ":"
QUOTE_OPERATOR = "+"
OPEN_PARENTHESIS = "("
CLOSE_PARENTHESIS = ")"
COMPARISON_OPERATORS = frozenset({"=", "!=", "<", "<=", ">", ">="})
ADDITIVE_OPERATORS = frozenset({"+", "-"})
MULTIPLICATIVE_OPERATORS = frozenset({"*", "/", "%"})
HELP_OPTION = "--help"


class ExprError(Exception):
    """Signal an expression expr cannot evaluate, with the message that follows the command name"""


class KeywordFunction(StrEnum):
    """Name the string functions expr accepts as keywords"""

    MATCH = "match"
    SUBSTR = "substr"
    INDEX = "index"
    LENGTH = "length"


def is_integer(text: str) -> bool:
    """Return whether a value is an integer in expr's terms

    Args:
        text: The value

    Returns:
        True when it is an optionally signed run of digits
    """
    return INTEGER_PATTERN.match(text) is not None


def is_null(text: str) -> bool:
    """Return whether a value counts as null or zero

    Args:
        text: The value

    Returns:
        True for the empty string and for an integer equal to zero
    """
    return text == "" or (is_integer(text) and int(text) == 0)


def truncated_division(left: int, right: int) -> int:
    """Return the quotient truncated toward zero as C does

    Args:
        left: The dividend
        right: The divisor

    Returns:
        The quotient
    """
    quotient = abs(left) // abs(right)
    return quotient if (left < 0) == (right < 0) else -quotient


def match_regex(text: str, pattern: str) -> str:
    """Return what ``STRING : REGEX`` yields: the first group, or the length of the match anchored at the start

    Args:
        text: The string to match
        pattern: The basic regular expression

    Raises:
        ExprError: If the pattern is invalid

    Returns:
        The group text or the match length, zero or empty when nothing matched
    """
    try:
        regex = re.compile(translate_regex(pattern, extended=False))
    except re.error as error:
        raise ExprError(f"invalid regular expression: {error.msg}") from error
    match = regex.match(text)
    if regex.groups:
        return (match.group(1) or "") if match else ""
    return str(match.end()) if match else EMPTY_MATCH_LENGTH


def substring(text: str, position_text: str, length_text: str) -> str:
    """Return the ``substr`` of a string, one-based, empty when the position or length is out of range

    Args:
        text: The string
        position_text: The one-based start position
        length_text: How many characters to take

    Raises:
        ExprError: If the position or length is not an integer

    Returns:
        The substring
    """
    if not is_integer(position_text) or not is_integer(length_text):
        raise ExprError("non-integer argument")
    position = int(position_text)
    length = int(length_text)
    if position < FIRST_POSITION or length < 1:
        return ""
    return text[position - FIRST_POSITION : position - FIRST_POSITION + length]


def index_of_any(text: str, characters: str) -> str:
    """Return the one-based position of the first character of the string found in the set, or zero

    Args:
        text: The string to search
        characters: The characters to look for

    Returns:
        The position as text
    """
    for offset, character in enumerate(text):
        if character in characters:
            return str(offset + FIRST_POSITION)
    return str(NOT_FOUND_POSITION)


class ExpressionParser:
    """Evaluate expr's grammar over the argument tokens by recursive descent"""

    def __init__(self, tokens: list[str]):
        """Hold the tokens

        Args:
            tokens: The arguments after the command name
        """
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | None:
        """Return the next token without consuming it, or None at the end"""
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        """Return the next token and consume it

        Raises:
            ExprError: If there are no tokens left
        """
        token = self.peek()
        if token is None:
            previous = self.tokens[self.position - 1] if self.position else ""
            raise ExprError(f"syntax error: missing argument after '{previous}'")
        self.position += 1
        return token

    def evaluate(self) -> str:
        """Return the value of the whole expression

        Raises:
            ExprError: If the tokens do not form one expression

        Returns:
            The value as text
        """
        if not self.tokens:
            raise ExprError("missing operand")
        value = self.parse_or()
        if self.peek() is not None:
            raise ExprError(f"syntax error: unexpected argument '{self.peek()}'")
        return value

    def parse_or(self) -> str:
        """Return the value of an ``|`` chain"""
        value = self.parse_and()
        while self.peek() == OR_OPERATOR:
            self.take()
            right = self.parse_and()
            if is_null(value):
                value = right if not is_null(right) else FALSE_TEXT
        return value

    def parse_and(self) -> str:
        """Return the value of an ``&`` chain"""
        value = self.parse_comparison()
        while self.peek() == AND_OPERATOR:
            self.take()
            right = self.parse_comparison()
            if is_null(value) or is_null(right):
                value = FALSE_TEXT
        return value

    def parse_comparison(self) -> str:
        """Return the value of a comparison chain, numeric when both sides are integers"""
        value = self.parse_additive()
        while self.peek() in COMPARISON_OPERATORS:
            operator = self.take()
            right = self.parse_additive()
            if is_integer(value) and is_integer(right):
                left_key: int | str = int(value)
                right_key: int | str = int(right)
            else:
                left_key, right_key = value, right
            results = {
                "=": left_key == right_key,
                "!=": left_key != right_key,
                "<": left_key < right_key,
                "<=": left_key <= right_key,
                ">": left_key > right_key,
                ">=": left_key >= right_key,
            }
            value = TRUE_TEXT if results[operator] else FALSE_TEXT
        return value

    def parse_additive(self) -> str:
        """Return the value of a ``+``/``-`` chain

        Raises:
            ExprError: If either side is not an integer
        """
        value = self.parse_multiplicative()
        while self.peek() in ADDITIVE_OPERATORS:
            operator = self.take()
            right = self.parse_multiplicative()
            if not is_integer(value) or not is_integer(right):
                raise ExprError("non-integer argument")
            value = str(int(value) + int(right) if operator == "+" else int(value) - int(right))
        return value

    def parse_multiplicative(self) -> str:
        """Return the value of a ``*``/``/``/``%`` chain

        Raises:
            ExprError: If either side is not an integer or the divisor is zero
        """
        value = self.parse_match()
        while self.peek() in MULTIPLICATIVE_OPERATORS:
            operator = self.take()
            right = self.parse_match()
            if not is_integer(value) or not is_integer(right):
                raise ExprError("non-integer argument")
            left_number, right_number = int(value), int(right)
            if operator == "*":
                value = str(left_number * right_number)
                continue
            if right_number == 0:
                raise ExprError("division by zero")
            quotient = truncated_division(left_number, right_number)
            value = str(quotient if operator == "/" else left_number - quotient * right_number)
        return value

    def parse_match(self) -> str:
        """Return the value of a ``STRING : REGEX`` chain"""
        value = self.parse_primary()
        while self.peek() == MATCH_OPERATOR:
            self.take()
            value = match_regex(value, self.parse_primary())
        return value

    def parse_primary(self) -> str:
        """Return the value of a parenthesised expression, a keyword function, a quoted token or a literal

        Raises:
            ExprError: If a parenthesis is unmatched or a token is missing
        """
        token = self.take()
        if token == OPEN_PARENTHESIS:
            value = self.parse_or()
            if self.peek() != CLOSE_PARENTHESIS:
                raise ExprError("syntax error: expecting ')'")
            self.take()
            return value
        if token == QUOTE_OPERATOR:
            return self.take()
        if token == KeywordFunction.MATCH:
            return match_regex(self.parse_primary(), self.parse_primary())
        if token == KeywordFunction.SUBSTR:
            return substring(self.parse_primary(), self.parse_primary(), self.parse_primary())
        if token == KeywordFunction.INDEX:
            return index_of_any(self.parse_primary(), self.parse_primary())
        if token == KeywordFunction.LENGTH:
            return str(len(self.parse_primary()))
        if token == CLOSE_PARENTHESIS:
            raise ExprError(f"syntax error: unexpected argument '{token}'")
        return token


class ExprCommand(Command):
    """Evaluate an integer or string expression given as arguments"""

    name = "expr"
    summary = "evaluate expressions"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the value of the expression, exiting one when it is null or zero and two on an error

        Args:
            invocation: The call to perform

        Returns:
            The value with a newline and the exit code
        """
        if invocation.arguments == [HELP_OPTION]:
            parser = CommandArgumentParser("expr", "Print the value of EXPRESSION to standard output")
            parser.add_argument("expression", nargs="*", help="tokens of the expression, one per argument")
            parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
            return CommandResult(stdout="", exit_code=parsed if isinstance(parsed, int) else EXIT_CODE_SUCCESS)
        try:
            value = ExpressionParser(invocation.arguments).evaluate()
        except ExprError as error:
            invocation.state.write_error(f"expr: {error}\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        exit_code = EXIT_CODE_FAILURE if is_null(value) else EXIT_CODE_SUCCESS
        return CommandResult(stdout=f"{value}\n", exit_code=exit_code)
