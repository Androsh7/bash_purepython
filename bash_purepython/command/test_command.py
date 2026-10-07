"""Implement the test command and its bracket spelling"""

# Standard libraries
import os
from collections.abc import Callable
from pathlib import Path

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR, ShellState

CLOSING_BRACKET = "]"
NEGATION = "!"
AND_OPERATOR = "-a"
OR_OPERATOR = "-o"
OPENING_PARENTHESIS = "("
CLOSING_PARENTHESIS = ")"

STRING_COMPARISONS: dict[str, Callable[[str, str], bool]] = {
    "=": lambda left, right: left == right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
    "<": lambda left, right: left < right,
    ">": lambda left, right: left > right,
}
INTEGER_COMPARISONS: dict[str, Callable[[int, int], bool]] = {
    "-eq": lambda left, right: left == right,
    "-ne": lambda left, right: left != right,
    "-lt": lambda left, right: left < right,
    "-le": lambda left, right: left <= right,
    "-gt": lambda left, right: left > right,
    "-ge": lambda left, right: left >= right,
}
FILE_COMPARISONS = frozenset({"-nt", "-ot", "-ef"})
STRING_TESTS: dict[str, Callable[[str], bool]] = {
    "-z": lambda text: text == "",
    "-n": lambda text: text != "",
}
FILE_TESTS: dict[str, Callable[[Path], bool]] = {
    "-e": lambda path: path.exists(),
    "-f": lambda path: path.is_file(),
    "-d": lambda path: path.is_dir(),
    "-L": lambda path: path.is_symlink(),
    "-h": lambda path: path.is_symlink(),
    "-s": lambda path: path.exists() and path.stat().st_size > 0,
    "-r": lambda path: os.access(path, os.R_OK),
    "-w": lambda path: os.access(path, os.W_OK),
    "-x": lambda path: os.access(path, os.X_OK),
}
BINARY_OPERATORS = frozenset({*STRING_COMPARISONS, *INTEGER_COMPARISONS, *FILE_COMPARISONS})


class TestExpressionError(Exception):
    """Signal an expression test cannot evaluate"""

    __test__ = False


def modification_time(path: Path) -> float | None:
    """Return when a path was last modified, or None when it does not exist

    Args:
        path: The path to look at

    Returns:
        The modification time in seconds, or None
    """
    return path.stat().st_mtime if path.exists() else None


def parse_integer(text: str) -> int:
    """Return an operand of a numeric comparison as an integer

    Args:
        text: The operand as written

    Raises:
        TestExpressionError: If the operand is not an integer

    Returns:
        The integer
    """
    try:
        return int(text.strip())
    except ValueError as error:
        raise TestExpressionError(f"{text}: integer expression expected") from error


class TestExpression:
    """Evaluate the arguments of one test call by recursive descent"""

    __test__ = False

    def __init__(self, arguments: list[str], state: ShellState):
        """Prepare to evaluate one expression

        Args:
            arguments: The words of the expression
            state: The shell state file operands are resolved against
        """
        self.arguments = arguments
        self.state = state
        self.position = 0

    def evaluate(self) -> bool:
        """Return whether the whole expression is true, an empty one being false

        Raises:
            TestExpressionError: If the expression is malformed

        Returns:
            The truth of the expression
        """
        if not self.arguments:
            return False
        result = self._or_expression()
        if self.position < len(self.arguments):
            raise TestExpressionError("too many arguments")
        return result

    def _peek(self, offset: int = 0) -> str | None:
        """Return the word at an offset from the current one, or None past the end

        Args:
            offset: How many words ahead to look

        Returns:
            The word, or None
        """
        index = self.position + offset
        return self.arguments[index] if index < len(self.arguments) else None

    def _take(self) -> str:
        """Return the current word and move past it

        Raises:
            TestExpressionError: If there is no word left

        Returns:
            The word
        """
        word = self._peek()
        if word is None:
            raise TestExpressionError("argument expected")
        self.position += 1
        return word

    def _or_expression(self) -> bool:
        """Return the value of terms joined by -o"""
        result = self._and_expression()
        while self._peek() == OR_OPERATOR:
            self.position += 1
            right = self._and_expression()
            result = result or right
        return result

    def _and_expression(self) -> bool:
        """Return the value of terms joined by -a"""
        result = self._negated_expression()
        while self._peek() == AND_OPERATOR:
            self.position += 1
            right = self._negated_expression()
            result = result and right
        return result

    def _negated_expression(self) -> bool:
        """Return the value of a term, flipped once for each leading exclamation mark"""
        if self._peek() == NEGATION and self._peek(1) is not None and self._peek(1) not in BINARY_OPERATORS:
            self.position += 1
            return not self._negated_expression()
        return self._primary()

    def _primary(self) -> bool:
        """Return the value of one comparison, file test, string test, group or bare word"""
        following = self._peek(1)
        if following in BINARY_OPERATORS and self._peek(2) is not None:
            left = self._take()
            operator = self._take()
            return self._compare(left, operator, self._take())
        word = self._take()
        if word == OPENING_PARENTHESIS and self._peek() is not None:
            result = self._or_expression()
            if self._take() != CLOSING_PARENTHESIS:
                raise TestExpressionError("`)' expected")
            return result
        if word in STRING_TESTS and self._peek() is not None:
            return STRING_TESTS[word](self._take())
        if word in FILE_TESTS and self._peek() is not None:
            return FILE_TESTS[word](self.state.resolve_path(self._take()))
        return word != ""

    def _compare(self, left: str, operator: str, right: str) -> bool:
        """Return the value of one binary comparison

        Args:
            left: The left operand
            operator: The comparison operator
            right: The right operand

        Returns:
            The truth of the comparison
        """
        if operator in STRING_COMPARISONS:
            return STRING_COMPARISONS[operator](left, right)
        if operator in INTEGER_COMPARISONS:
            return INTEGER_COMPARISONS[operator](parse_integer(left), parse_integer(right))
        left_path, right_path = self.state.resolve_path(left), self.state.resolve_path(right)
        if operator == "-ef":
            return left_path.exists() and right_path.exists() and left_path.samefile(right_path)
        left_time, right_time = modification_time(left_path), modification_time(right_path)
        newer, older = (left_time, right_time) if operator == "-nt" else (right_time, left_time)
        return newer is not None and (older is None or newer > older)


def run_test(command_name: str, arguments: list[str], state: ShellState) -> CommandResult:
    """Evaluate a test expression and return its exit code with no output

    Args:
        command_name: The name errors are reported under
        arguments: The words of the expression
        state: The shell state for paths and errors

    Returns:
        Exit code zero when true, one when false, two when the expression is malformed
    """
    try:
        truth = TestExpression(arguments, state).evaluate()
    except TestExpressionError as error:
        state.write_error(f"bash: {command_name}: {error}\n")
        return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
    return CommandResult(stdout="", exit_code=EXIT_CODE_SUCCESS if truth else EXIT_CODE_FAILURE)


class TestCommand(Command):
    """Evaluate a conditional expression"""

    __test__ = False
    name = "test"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return exit code zero when the expression is true

        Args:
            invocation: The call to perform

        Returns:
            No output, and exit code zero, one or two
        """
        return run_test(self.name, invocation.arguments, invocation.state)


class BracketCommand(Command):
    """Evaluate a conditional expression written between square brackets"""

    name = "["
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return exit code zero when the expression before the closing bracket is true

        Args:
            invocation: The call to perform

        Returns:
            No output, and exit code zero, one or two
        """
        arguments = invocation.arguments
        if not arguments or arguments[-1] != CLOSING_BRACKET:
            invocation.state.write_error("bash: [: missing `]'\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        return run_test(self.name, arguments[:-1], invocation.state)
