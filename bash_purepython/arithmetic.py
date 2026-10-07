"""Evaluate shell arithmetic expressions, as written between ``$((`` and ``))``"""

# Standard libraries
import re
from collections.abc import Callable

# Project libraries
from bash_purepython.shell_state import ExpansionError, ShellState

TOKEN_PATTERN = re.compile(
    r"\s*(?:(?P<number>0[xX][0-9a-fA-F]+|\d+#\w+|\d+)|(?P<name>[A-Za-z_]\w*)"
    r"|(?P<operator><<=|>>=|\*\*|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|[-+*/%<>=!~&|^?:(),]))"
)
HEXADECIMAL_PREFIXES = ("0x", "0X")
OCTAL_BASE = 8
HEXADECIMAL_BASE = 16
BASE_SEPARATOR = "#"
MAX_VARIABLE_DEPTH = 32
INCREMENT_OPERATORS = {"++": 1, "--": -1}
UNARY_OPERATORS: dict[str, Callable[[int], int]] = {
    "!": lambda value: int(value == 0),
    "~": lambda value: ~value,
    "+": lambda value: value,
    "-": lambda value: -value,
}
BINARY_OPERATOR_LEVELS: tuple[frozenset[str], ...] = (
    frozenset({"|"}),
    frozenset({"^"}),
    frozenset({"&"}),
    frozenset({"==", "!="}),
    frozenset({"<", "<=", ">", ">="}),
    frozenset({"<<", ">>"}),
    frozenset({"+", "-"}),
    frozenset({"*", "/", "%"}),
)
ASSIGNMENT_OPERATORS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "|=", "^="})
DIVISION_OPERATORS = frozenset({"/", "%"})


def truncated_division(left: int, right: int) -> int:
    """Return an integer quotient rounded toward zero, as C and bash do

    Args:
        left: The dividend
        right: The divisor, not zero

    Returns:
        The quotient
    """
    quotient = abs(left) // abs(right)
    return quotient if (left < 0) == (right < 0) else -quotient


def apply_binary_operator(operator: str, left: int, right: int) -> int:
    """Return the result of one binary operator on two integers

    Args:
        operator: The operator as written, without any trailing ``=``
        left: The left operand
        right: The right operand

    Raises:
        ExpansionError: If the divisor of a division or remainder is zero, or an exponent is negative

    Returns:
        The result, with comparisons giving one or zero
    """
    if operator in DIVISION_OPERATORS:
        if right == 0:
            raise ExpansionError("division by 0")
        quotient = truncated_division(left, right)
        return quotient if operator == "/" else left - quotient * right
    if operator == "**":
        if right < 0:
            raise ExpansionError("exponent less than 0")
        return left**right
    operations: dict[str, Callable[[], int]] = {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "<<": lambda: left << right,
        ">>": lambda: left >> right,
        "&": lambda: left & right,
        "|": lambda: left | right,
        "^": lambda: left ^ right,
        "==": lambda: int(left == right),
        "!=": lambda: int(left != right),
        "<": lambda: int(left < right),
        "<=": lambda: int(left <= right),
        ">": lambda: int(left > right),
        ">=": lambda: int(left >= right),
    }
    return operations[operator]()


def parse_number(text: str) -> int:
    """Return the value of an integer constant in decimal, octal, hexadecimal or ``base#digits`` form

    Args:
        text: The constant as written

    Raises:
        ExpansionError: If the digits are not valid in the base

    Returns:
        The value
    """
    try:
        if BASE_SEPARATOR in text:
            base, digits = text.split(BASE_SEPARATOR, 1)
            return int(digits, int(base))
        if text.startswith(HEXADECIMAL_PREFIXES):
            return int(text, HEXADECIMAL_BASE)
        if len(text) > 1 and text.startswith("0"):
            return int(text, OCTAL_BASE)
        return int(text)
    except ValueError as error:
        raise ExpansionError(f"{text}: value too great for base") from error


def tokenize_expression(expression: str) -> list[tuple[str, str]]:
    """Split an arithmetic expression into numbers, names and operators

    Args:
        expression: The expression text

    Raises:
        ExpansionError: If a character belongs to no token

    Returns:
        Pairs of the token kind and its text
    """
    tokens: list[tuple[str, str]] = []
    position = 0
    stripped = expression.rstrip()
    while position < len(stripped):
        match = TOKEN_PATTERN.match(stripped, position)
        if match is None:
            raise ExpansionError(f"{expression}: syntax error: invalid arithmetic operator")
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class ArithmeticEvaluator:
    """Evaluate one tokenized expression against the shell's variables

    An operand the result does not depend on, such as the right side of ``0 && x++``, is still parsed but
    with ``skipping`` raised, so it assigns nothing and cannot fail on a division by zero
    """

    def __init__(self, expression: str, state: ShellState, depth: int = 0):
        """Prepare to evaluate one expression

        Args:
            expression: The expression text, used in error messages
            state: The shell state whose variables are read and assigned
            depth: How many variables deep this expression was reached through
        """
        self.expression = expression
        self.state = state
        self.depth = depth
        self.tokens = tokenize_expression(expression)
        self.position = 0
        self.skipping = 0

    def evaluate(self) -> int:
        """Return the value of the whole expression, an empty one being zero

        Raises:
            ExpansionError: If the expression is malformed

        Returns:
            The value
        """
        if not self.tokens:
            return 0
        value = self._comma()
        if self.position < len(self.tokens):
            raise self._syntax_error()
        return value

    def _syntax_error(self) -> ExpansionError:
        """Return the error for a token that cannot appear where it does"""
        return ExpansionError(f"{self.expression}: syntax error in expression")

    def _peek(self, offset: int = 0) -> tuple[str, str] | None:
        """Return the token at an offset from the current one, or None past the end

        Args:
            offset: How many tokens ahead to look

        Returns:
            The token kind and text, or None
        """
        index = self.position + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def _next_is(self, operators: frozenset[str] | set[str]) -> str | None:
        """Return the current token's text when it is one of the given operators

        Args:
            operators: The operators to accept

        Returns:
            The operator, or None
        """
        token = self._peek()
        if token is not None and token[0] == "operator" and token[1] in operators:
            return token[1]
        return None

    def _expect(self, operator: str) -> None:
        """Move past an operator that must be next

        Args:
            operator: The operator required

        Raises:
            ExpansionError: If something else is next
        """
        if self._next_is({operator}) is None:
            raise self._syntax_error()
        self.position += 1

    def _read_variable(self, name: str) -> int:
        """Return a variable's value as an integer, evaluating it as an expression when it is not a number

        Args:
            name: The variable name

        Raises:
            ExpansionError: If variables refer to each other too deeply

        Returns:
            The value, zero for an unset or empty variable
        """
        text = self.state.variables.get(name, "").strip()
        if not text:
            return 0
        if text.lstrip("-").isdigit():
            return int(text)
        if self.depth >= MAX_VARIABLE_DEPTH:
            raise ExpansionError(f"{name}: expression recursion level exceeded")
        return ArithmeticEvaluator(text, self.state, self.depth + 1).evaluate()

    def _assign(self, name: str, value: int) -> None:
        """Store a value in a variable unless this operand is being skipped

        Args:
            name: The variable name
            value: The value to store
        """
        if not self.skipping:
            self.state.variables[name] = str(value)

    def _comma(self) -> int:
        """Return the value of the last of several comma-separated expressions"""
        value = self._assignment()
        while self._next_is({","}):
            self.position += 1
            value = self._assignment()
        return value

    def _assignment(self) -> int:
        """Return the value assigned by ``name = expression`` or a compound assignment, else a conditional"""
        token, following = self._peek(), self._peek(1)
        if (
            token is not None
            and token[0] == "name"
            and following is not None
            and following[0] == "operator"
            and following[1] in ASSIGNMENT_OPERATORS
        ):
            self.position += 2
            right = self._assignment()
            operator = following[1][:-1]
            value = right if not operator else self._apply(operator, self._read_variable(token[1]), right)
            self._assign(token[1], value)
            return value
        return self._conditional()

    def _apply(self, operator: str, left: int, right: int) -> int:
        """Return the result of a binary operator, or zero when this operand is being skipped

        Args:
            operator: The operator
            left: The left operand
            right: The right operand

        Returns:
            The result
        """
        return 0 if self.skipping else apply_binary_operator(operator, left, right)

    def _skipped(self, parse: Callable[[], int], skip: bool) -> int:
        """Parse an operand, without side effects when its value will not be used

        Args:
            parse: Parses the operand and returns its value
            skip: Whether the value is unused

        Returns:
            The operand's value
        """
        self.skipping += int(skip)
        try:
            return parse()
        finally:
            self.skipping -= int(skip)

    def _conditional(self) -> int:
        """Return the chosen branch of ``condition ? first : second``, else a logical or"""
        condition = self._logical_or()
        if not self._next_is({"?"}):
            return condition
        self.position += 1
        first = self._skipped(self._assignment, skip=condition == 0)
        self._expect(":")
        second = self._skipped(self._conditional, skip=condition != 0)
        return first if condition else second

    def _logical_or(self) -> int:
        """Return one when any operand joined by ``||`` is nonzero, not evaluating those after the first"""
        value = self._logical_and()
        while self._next_is({"||"}):
            self.position += 1
            right = self._skipped(self._logical_and, skip=value != 0)
            value = int(value != 0 or right != 0)
        return value

    def _logical_and(self) -> int:
        """Return one when every operand joined by ``&&`` is nonzero, not evaluating those after a zero"""
        value = self._binary(0)
        while self._next_is({"&&"}):
            self.position += 1
            right = self._skipped(lambda: self._binary(0), skip=value == 0)
            value = int(value != 0 and right != 0)
        return value

    def _binary(self, level: int) -> int:
        """Return the value of left-associative binary operators at one precedence level and above

        Args:
            level: The index into the precedence table, lowest precedence first

        Returns:
            The value
        """
        if level == len(BINARY_OPERATOR_LEVELS):
            return self._power()
        value = self._binary(level + 1)
        while (operator := self._next_is(BINARY_OPERATOR_LEVELS[level])) is not None:
            self.position += 1
            value = self._apply(operator, value, self._binary(level + 1))
        return value

    def _power(self) -> int:
        """Return the value of right-associative exponentiation"""
        base = self._unary()
        if not self._next_is({"**"}):
            return base
        self.position += 1
        return self._apply("**", base, self._power())

    def _unary(self) -> int:
        """Return the value of a prefix operator applied to its operand, else a postfix expression"""
        increment = self._next_is(set(INCREMENT_OPERATORS))
        if increment is not None:
            self.position += 1
            name = self._take_name()
            value = self._read_variable(name) + INCREMENT_OPERATORS[increment]
            self._assign(name, value)
            return value
        operator = self._next_is(set(UNARY_OPERATORS))
        if operator is not None:
            self.position += 1
            return UNARY_OPERATORS[operator](self._unary())
        return self._postfix()

    def _take_name(self) -> str:
        """Return the variable name that must be next and move past it

        Raises:
            ExpansionError: If something else is next

        Returns:
            The name
        """
        token = self._peek()
        if token is None or token[0] != "name":
            raise self._syntax_error()
        self.position += 1
        return token[1]

    def _postfix(self) -> int:
        """Return a number, a variable with an optional ``++`` or ``--`` after it, or a parenthesised expression"""
        token = self._peek()
        if token is None:
            raise self._syntax_error()
        kind, text = token
        self.position += 1
        if kind == "number":
            return parse_number(text)
        if kind == "name":
            value = self._read_variable(text)
            increment = self._next_is(set(INCREMENT_OPERATORS))
            if increment is not None:
                self.position += 1
                self._assign(text, value + INCREMENT_OPERATORS[increment])
            return value
        if text == "(":
            value = self._comma()
            self._expect(")")
            return value
        raise self._syntax_error()


def evaluate_arithmetic(expression: str, state: ShellState) -> int:
    """Return the value of an arithmetic expression, assigning any variables it sets

    Args:
        expression: The expression with parameter and command substitutions already performed
        state: The shell state whose variables are read and assigned

    Raises:
        ExpansionError: If the expression is malformed or divides by zero

    Returns:
        The integer value
    """
    return ArithmeticEvaluator(expression, state).evaluate()
