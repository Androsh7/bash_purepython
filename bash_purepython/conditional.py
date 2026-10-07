"""Evaluate the ``[[ expression ]]`` conditional command"""

# Standard libraries
import fnmatch
import glob
import re
from collections.abc import Callable
from dataclasses import dataclass

# Project libraries
from bash_purepython.arithmetic import evaluate_arithmetic
from bash_purepython.command.test_command import (
    FILE_COMPARISONS,
    FILE_TESTS,
    INTEGER_COMPARISONS,
    STRING_TESTS,
    modification_time,
)
from bash_purepython.shell_state import ShellState, ShellSyntaxError
from bash_purepython.words import (
    QuoteStyle,
    RunSubstitution,
    Word,
    WordPart,
    expand_text,
    expand_tilde,
    expand_word_unsplit,
    find_balanced_end,
    tokenize_simple_command,
)

OPENING = "[["
CLOSING = "]]"
WHITESPACE = frozenset(" \t\n")
QUOTE_CHARACTERS = frozenset("'\"")
NEGATION = "!"
AND_OPERATOR = "&&"
OR_OPERATOR = "||"
OPENING_PARENTHESIS = "("
CLOSING_PARENTHESIS = ")"
REGEX_OPERATOR = "=~"
VARIABLE_SET_TEST = "-v"
PATTERN_OPERATORS = frozenset({"=", "==", "!="})
ORDER_OPERATORS = frozenset({"<", ">"})
INTEGER_OPERATORS = frozenset(INTEGER_COMPARISONS)
BINARY_OPERATORS = frozenset(
    {*PATTERN_OPERATORS, *ORDER_OPERATORS, *INTEGER_OPERATORS, *FILE_COMPARISONS, REGEX_OPERATOR}
)
UNARY_OPERATORS = frozenset({*STRING_TESTS, *FILE_TESTS, VARIABLE_SET_TEST})
SYNTAX_OPERATORS = (AND_OPERATOR, OR_OPERATOR, OPENING_PARENTHESIS, CLOSING_PARENTHESIS, "<", ">")
PLACEHOLDER_COMMAND = ": "


def conditional_body(command_text: str) -> str | None:
    """Return the text between ``[[`` and ``]]`` when a command is a conditional command

    Args:
        command_text: The text of one simple command

    Raises:
        ShellSyntaxError: If the command opens with ``[[`` and does not end with ``]]``

    Returns:
        The expression text, or None when the command is not a conditional command
    """
    text = command_text.strip()
    if text != OPENING and not (text.startswith(OPENING) and text[len(OPENING)] in WHITESPACE):
        return None
    if not text.endswith(CLOSING) or len(text) < len(OPENING) + len(CLOSING) + 1:
        raise ShellSyntaxError("syntax error in conditional expression: missing `]]'")
    return text[len(OPENING) : -len(CLOSING)]


@dataclass(frozen=True)
class ConditionalToken:
    """Hold one word or operator of a conditional expression, quotes still present"""

    text: str
    is_regex: bool = False


def skip_quoted_or_expansion(text: str, index: int) -> int:
    """Return the index just past the quoted string, escape or expansion starting at a position

    Args:
        text: The expression text
        index: The position of a quote, backslash, backtick or dollar sign

    Raises:
        ShellSyntaxError: If a quote or bracket is never closed

    Returns:
        The index after the construct, or one past the character when it starts none
    """
    character = text[index]
    if character == "\\":
        return min(index + 2, len(text))
    if character == "'":
        closing = text.find("'", index + 1)
        if closing == -1:
            raise ShellSyntaxError(f"unclosed single quote: {text}")
        return closing + 1
    if character == '"':
        position = index + 1
        while position < len(text) and text[position] != '"':
            position = position + 2 if text[position] == "\\" else position + 1
        if position >= len(text):
            raise ShellSyntaxError(f"unclosed double quote: {text}")
        return position + 1
    if character == "`":
        closing = text.find("`", index + 1)
        if closing == -1:
            raise ShellSyntaxError(f"unclosed backtick: {text}")
        return closing + 1
    if text.startswith("$(", index):
        return find_balanced_end(text, index + 1, "(", ")")
    if text.startswith("${", index):
        return find_balanced_end(text, index + 1, "{", "}")
    return index + 1


def tokenize_conditional(text: str) -> list[ConditionalToken]:
    """Split a conditional expression into words and operators

    The word after ``=~`` is a regular expression, in which parentheses and bars are ordinary characters

    Args:
        text: The text between ``[[`` and ``]]``

    Returns:
        The tokens in order
    """
    tokens: list[ConditionalToken] = []
    index = 0
    while index < len(text):
        if text[index] in WHITESPACE:
            index += 1
            continue
        expects_regex = bool(tokens) and tokens[-1].text == REGEX_OPERATOR
        operator = next((symbol for symbol in SYNTAX_OPERATORS if text.startswith(symbol, index)), None)
        if operator is not None and not expects_regex:
            tokens.append(ConditionalToken(operator))
            index += len(operator)
            continue
        start = index
        depth = 0
        while index < len(text):
            character = text[index]
            if character in WHITESPACE and depth == 0:
                break
            if not expects_regex and any(text.startswith(symbol, index) for symbol in SYNTAX_OPERATORS):
                break
            if character in "\\'\"`$":
                index = skip_quoted_or_expansion(text, index)
                continue
            if expects_regex and character in "()":
                depth += 1 if character == "(" else -1
            index += 1
        tokens.append(ConditionalToken(text[start:index], is_regex=expects_regex))
    return tokens


def word_of(token: ConditionalToken) -> Word:
    """Return a token as a word with its quoted parts

    Args:
        token: A word token

    Returns:
        The word, whose unquoted parts keep their expansions unexpanded
    """
    if token.is_regex and not any(character in token.text for character in QUOTE_CHARACTERS):
        return Word(parts=[WordPart(text=token.text, quote=QuoteStyle.NONE)])
    words, _, _ = tokenize_simple_command(PLACEHOLDER_COMMAND + token.text)
    return words[1] if len(words) > 1 else Word(parts=[WordPart(text="", quote=QuoteStyle.SINGLE)])


class ConditionalEvaluator:
    """Evaluate one tokenized conditional expression by recursive descent

    The side of ``&&`` or ``||`` that cannot change the result is parsed with ``skipping`` raised, so its
    words are not expanded and its substitutions do not run
    """

    def __init__(self, tokens: list[ConditionalToken], state: ShellState, run_substitution: RunSubstitution):
        """Prepare to evaluate one expression

        Args:
            tokens: The words and operators of the expression
            state: The shell state for variables and paths
            run_substitution: Runs a script and returns its output
        """
        self.tokens = tokens
        self.state = state
        self.run_substitution = run_substitution
        self.position = 0
        self.skipping = 0

    async def evaluate(self) -> bool:
        """Return whether the whole expression is true

        Raises:
            ShellSyntaxError: If the expression is empty or malformed

        Returns:
            The truth of the expression
        """
        if not self.tokens:
            raise self._syntax_error()
        result = await self._or_expression()
        if self.position < len(self.tokens):
            raise self._syntax_error()
        return result

    def _syntax_error(self) -> ShellSyntaxError:
        """Return the error for a token that cannot appear where it does"""
        return ShellSyntaxError("syntax error in conditional expression")

    def _peek(self, offset: int = 0) -> str | None:
        """Return the text of the token at an offset from the current one, or None past the end

        Args:
            offset: How many tokens ahead to look

        Returns:
            The token text with its quotes, or None
        """
        index = self.position + offset
        return self.tokens[index].text if index < len(self.tokens) else None

    def _take(self) -> ConditionalToken:
        """Return the current token and move past it

        Raises:
            ShellSyntaxError: If there is no token left

        Returns:
            The token
        """
        if self.position >= len(self.tokens):
            raise self._syntax_error()
        token = self.tokens[self.position]
        self.position += 1
        return token

    async def _or_expression(self) -> bool:
        """Return the value of terms joined by ``||``, not evaluating those after a true one"""
        result = await self._and_expression()
        while self._peek() == OR_OPERATOR:
            self.position += 1
            self.skipping += int(result)
            try:
                right = await self._and_expression()
            finally:
                self.skipping -= int(result)
            result = result or right
        return result

    async def _and_expression(self) -> bool:
        """Return the value of terms joined by ``&&``, not evaluating those after a false one"""
        result = await self._negated_expression()
        while self._peek() == AND_OPERATOR:
            self.position += 1
            self.skipping += int(not result)
            try:
                right = await self._negated_expression()
            finally:
                self.skipping -= int(not result)
            result = result and right
        return result

    async def _negated_expression(self) -> bool:
        """Return the value of a term, flipped once for each leading exclamation mark"""
        if self._peek() == NEGATION:
            self.position += 1
            return not await self._negated_expression()
        return await self._primary()

    async def _primary(self) -> bool:
        """Return the value of one group, unary test, binary comparison or bare word"""
        if self._peek() == OPENING_PARENTHESIS:
            self.position += 1
            result = await self._or_expression()
            if self._take().text != CLOSING_PARENTHESIS:
                raise self._syntax_error()
            return result
        following = self._peek(1)
        if self._peek() in UNARY_OPERATORS and following is not None and following not in BINARY_OPERATORS:
            operator = self._take().text
            return await self._unary(operator, self._take())
        left = self._take()
        if left.text in SYNTAX_OPERATORS:
            raise self._syntax_error()
        if self._peek() in BINARY_OPERATORS:
            operator = self._take().text
            return await self._binary(left, operator, self._take())
        return self.skipping > 0 or await self._value(left) != ""

    async def _value(self, token: ConditionalToken) -> str:
        """Return a word expanded to one value, without word splitting or pathname expansion

        Args:
            token: A word token

        Returns:
            The expanded text
        """
        return await expand_word_unsplit(word_of(token), self.state, self.run_substitution)

    async def _pattern(self, token: ConditionalToken, escape_quoted: Callable[[str], str]) -> str:
        """Return a word as a pattern in which only the unquoted characters are special

        Args:
            token: The word holding the pattern
            escape_quoted: Makes quoted text literal for the kind of pattern being built

        Returns:
            The pattern text
        """
        pieces: list[str] = []
        for part_index, part in enumerate(word_of(token).parts):
            if part.quote == QuoteStyle.SINGLE:
                pieces.append(escape_quoted(part.text))
            elif part.quote == QuoteStyle.DOUBLE:
                expanded = await expand_text(part.text, self.state, self.run_substitution, in_double_quotes=True)
                pieces.append(escape_quoted(expanded))
            else:
                text = expand_tilde(part.text, self.state) if part_index == 0 else part.text
                pieces.append(await expand_text(text, self.state, self.run_substitution, in_double_quotes=False))
        return "".join(pieces)

    async def _unary(self, operator: str, operand: ConditionalToken) -> bool:
        """Return the value of a string, variable or file test

        Args:
            operator: The test operator
            operand: The word it applies to

        Returns:
            The truth of the test
        """
        if self.skipping:
            return True
        value = await self._value(operand)
        if operator == VARIABLE_SET_TEST:
            return value in self.state.variables
        if operator in STRING_TESTS:
            return STRING_TESTS[operator](value)
        return FILE_TESTS[operator](self.state.resolve_path(value))

    async def _binary(self, left: ConditionalToken, operator: str, right: ConditionalToken) -> bool:
        """Return the value of one binary comparison

        Args:
            left: The left operand
            operator: The comparison operator
            right: The right operand, a pattern for ``==`` and ``!=`` and a regular expression for ``=~``

        Raises:
            ShellSyntaxError: If the regular expression is invalid

        Returns:
            The truth of the comparison
        """
        if self.skipping:
            return True
        left_value = await self._value(left)
        if operator in PATTERN_OPERATORS:
            matched = fnmatch.fnmatchcase(left_value, await self._pattern(right, glob.escape))
            return matched != (operator == "!=")
        if operator == REGEX_OPERATOR:
            try:
                return re.search(await self._pattern(right, re.escape), left_value) is not None
            except re.error as error:
                raise ShellSyntaxError(f"invalid regular expression: {error}") from error
        right_value = await self._value(right)
        if operator in ORDER_OPERATORS:
            return left_value < right_value if operator == "<" else left_value > right_value
        if operator in INTEGER_OPERATORS:
            left_number = evaluate_arithmetic(left_value, self.state)
            right_number = evaluate_arithmetic(right_value, self.state)
            return INTEGER_COMPARISONS[operator](left_number, right_number)
        left_path, right_path = self.state.resolve_path(left_value), self.state.resolve_path(right_value)
        if operator == "-ef":
            return left_path.exists() and right_path.exists() and left_path.samefile(right_path)
        left_time, right_time = modification_time(left_path), modification_time(right_path)
        newer, older = (left_time, right_time) if operator == "-nt" else (right_time, left_time)
        return newer is not None and (older is None or newer > older)


async def evaluate_conditional(body: str, state: ShellState, run_substitution: RunSubstitution) -> bool:
    """Return whether the expression of a conditional command is true

    Args:
        body: The text between ``[[`` and ``]]``
        state: The shell state for variables and paths
        run_substitution: Runs a script and returns its output

    Raises:
        ShellSyntaxError: If the expression is malformed

    Returns:
        The truth of the expression
    """
    return await ConditionalEvaluator(tokenize_conditional(body), state, run_substitution).evaluate()
