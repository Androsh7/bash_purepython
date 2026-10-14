"""Implement the tr command"""

# Standard libraries
import string
from collections.abc import AsyncIterator, Callable

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import close_stdin, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE
from bash_purepython.streams import as_async_iterator, close_iterator

ESCAPE_CHARACTER = "\\"
RANGE_CHARACTER = "-"
CLASS_START = "[:"
CLASS_END = ":]"
OCTAL_DIGITS = "01234567"
MAXIMUM_OCTAL_DIGITS = 3
OCTAL_BASE = 8
ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}
CHARACTER_CLASSES = {
    "alpha": string.ascii_letters,
    "alnum": string.digits + string.ascii_letters,
    "digit": string.digits,
    "lower": string.ascii_lowercase,
    "upper": string.ascii_uppercase,
    "space": string.whitespace,
    "blank": " \t",
    "punct": string.punctuation,
    "print": string.digits + string.ascii_letters + string.punctuation + " ",
    "graph": string.digits + string.ascii_letters + string.punctuation,
    "cntrl": "".join(chr(code) for code in range(0x20)) + chr(0x7F),
    "xdigit": string.hexdigits,
}


def read_escape(specification: str, index: int) -> tuple[str, int]:
    """Return the character a backslash escape names and the index after it

    Args:
        specification: The set as written on the command line
        index: The index of the backslash

    Returns:
        The character and the index of the next unread character
    """
    following = specification[index + 1 :]
    if not following:
        return ESCAPE_CHARACTER, index + 1
    octal = ""
    for digit in following[:MAXIMUM_OCTAL_DIGITS]:
        if digit not in OCTAL_DIGITS:
            break
        octal += digit
    if octal:
        return chr(int(octal, OCTAL_BASE)), index + 1 + len(octal)
    return ESCAPES.get(following[0], following[0]), index + 2


def expand_set(specification: str) -> str:
    """Return every character a set names, in order, with ranges, classes and escapes expanded

    Args:
        specification: The set as written on the command line

    Raises:
        ValueError: If a range runs backwards or a character class is unknown

    Returns:
        The characters of the set
    """
    characters: list[str] = []
    index = 0
    while index < len(specification):
        if specification.startswith(CLASS_START, index):
            class_end = specification.find(CLASS_END, index)
            if class_end != -1:
                class_name = specification[index + len(CLASS_START) : class_end]
                if class_name not in CHARACTER_CLASSES:
                    raise ValueError(f"invalid character class '{class_name}'")
                characters.extend(CHARACTER_CLASSES[class_name])
                index = class_end + len(CLASS_END)
                continue
        if specification[index] == ESCAPE_CHARACTER:
            character, index = read_escape(specification, index)
        else:
            character, index = specification[index], index + 1
        if specification[index : index + 1] == RANGE_CHARACTER and index + 1 < len(specification):
            if specification[index + 1] == ESCAPE_CHARACTER:
                range_end, index = read_escape(specification, index + 1)
            else:
                range_end, index = specification[index + 1], index + 2
            if ord(range_end) < ord(character):
                raise ValueError(
                    f"range-endpoints of '{character}-{range_end}' are in reverse collating sequence order"
                )
            characters.extend(chr(code) for code in range(ord(character), ord(range_end) + 1))
        else:
            characters.append(character)
    return "".join(characters)


def build_translator(set1: str, set2: str, complement: bool) -> Callable[[str], str]:
    """Return the function mapping each character to its translation

    Args:
        set1: The characters to translate, expanded
        set2: The characters to translate them to, expanded, padded with its last character when shorter
        complement: Whether every character not in set1 is translated instead

    Returns:
        A function from one character to one character
    """
    if complement:
        members = set(set1)
        replacement = set2[-1]
        return lambda character: replacement if character not in members else character
    padded = set2 + set2[-1] * max(len(set1) - len(set2), 0)
    table = {character: padded[position] for position, character in enumerate(set1)}
    return lambda character: table.get(character, character)


class Squeezer:
    """Collapse runs of a repeated character into one, remembering the last character across chunks"""

    def __init__(self, characters: str, complement: bool):
        """Record which characters are squeezed

        Args:
            characters: The characters whose runs collapse
            complement: Whether every character not listed is squeezed instead
        """
        self.members = set(characters)
        self.complement = complement
        self.previous: str | None = None

    def squeeze(self, text: str) -> str:
        """Return the text with runs collapsed, continuing any run left from the previous call

        Args:
            text: The next chunk

        Returns:
            The chunk with repeated squeezable characters collapsed
        """
        kept: list[str] = []
        for character in text:
            squeezable = (character in self.members) != self.complement
            if squeezable and character == self.previous:
                continue
            kept.append(character)
            self.previous = character
        return "".join(kept)


async def transform_input(invocation: CommandInvocation, transform: Callable[[str], str]) -> AsyncIterator[str]:
    """Yield each chunk of standard input transformed, then close the input

    Args:
        invocation: The call, providing standard input
        transform: Maps one chunk to its output

    Yields:
        Each transformed chunk
    """
    if invocation.stdin_kind == InputKind.ARGUMENTS:
        chunks: AsyncIterator[str] = as_async_iterator(())
    else:
        chunks = stdin_lines(invocation.stdin, invocation.stdin_kind)
    try:
        async for chunk in chunks:
            yield transform(chunk)
    finally:
        await close_iterator(chunks)
        await close_stdin(invocation.stdin)


class TrCommand(Command):
    """Translate, squeeze or delete characters of standard input"""

    name = "tr"
    summary = "translate or delete characters"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of the input with its characters translated, deleted or squeezed

        Args:
            invocation: The call to perform

        Returns:
            A lazy stream of the transformed input
        """
        parser = CommandArgumentParser("tr", "Translate, squeeze, and/or delete characters from standard input")
        parser.add_argument("-c", "-C", "--complement", action="store_true", help="use the complement of SET1")
        parser.add_argument("-d", "--delete", action="store_true", help="delete characters in SET1, do not translate")
        parser.add_argument("-s", "--squeeze-repeats", action="store_true", help="replace each run with one occurrence")
        parser.add_argument("-t", "--truncate-set1", action="store_true", help="first truncate SET1 to length of SET2")
        parser.add_argument("set1", help="the characters to act on")
        parser.add_argument("set2", nargs="?", default=None, help="the characters to translate to")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        try:
            transform = self.build_transform(parsed)
        except ValueError as error:
            invocation.state.write_error(f"tr: {error}\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_FAILURE)
        return CommandResult(stdout=transform_input(invocation, transform), exit_code=invocation.exit_status.code)

    def build_transform(self, parsed: object) -> Callable[[str], str]:
        """Return the function applying the parsed options to one chunk

        Args:
            parsed: The parsed options

        Raises:
            ValueError: If an operand is missing, extra, or malformed

        Returns:
            The chunk transformer
        """
        set1 = expand_set(parsed.set1)
        set2 = expand_set(parsed.set2) if parsed.set2 is not None else None
        if parsed.delete and set2 is not None and not parsed.squeeze_repeats:
            raise ValueError(
                f"extra operand '{parsed.set2}'\nOnly one string may be given when deleting without squeezing repeats"
            )
        if not parsed.delete and set2 is None and not parsed.squeeze_repeats:
            raise ValueError(f"missing operand after '{parsed.set1}'\nTwo strings must be given when translating")
        if set2 is not None and not set2 and not parsed.delete:
            raise ValueError("when not truncating set1, string2 must be non-empty")
        if parsed.truncate_set1 and set2 is not None:
            set1 = set1[: len(set2)]
        steps: list[Callable[[str], str]] = []
        if parsed.delete:
            deleted = set(set1)
            complement = parsed.complement
            steps.append(lambda text: "".join(char for char in text if (char in deleted) == complement))
        elif set2:
            steps.append(self.translate_step(set1, set2, parsed.complement))
        if parsed.squeeze_repeats:
            squeeze_complement = parsed.complement and set2 is None
            squeezer = Squeezer(set2 if set2 else set1, squeeze_complement)
            steps.append(squeezer.squeeze)

        def transform(text: str) -> str:
            for step in steps:
                text = step(text)
            return text

        return transform

    def translate_step(self, set1: str, set2: str, complement: bool) -> Callable[[str], str]:
        """Return the step translating each character of a chunk

        Args:
            set1: The characters to translate, expanded
            set2: The characters to translate them to, expanded
            complement: Whether every character not in set1 is translated instead

        Returns:
            The chunk transformer
        """
        translator = build_translator(set1, set2, complement)
        return lambda text: "".join(translator(character) for character in text)
