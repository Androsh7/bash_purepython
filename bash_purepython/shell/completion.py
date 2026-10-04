"""Complete the word under the cursor of a command line"""

# Standard libraries
import os
import re
from collections.abc import Sequence
from pathlib import Path

# Project libraries
from bash_purepython.shell.models import Candidate, CompletionResult, PartialWord, QuoteStyle, WordPosition
from bash_purepython.shell.runner import command_help_text
from bash_purepython.shell.tokenizer import WHITESPACE, WORD_BREAKERS, expand_tilde

UNQUOTED_SPECIAL_CHARACTERS = set(" \t\"'\\>$|;&")
DOUBLE_QUOTED_SPECIAL_CHARACTERS = set('"\\$')
OPTION_NAME = re.compile(r"(?<![\w-])(--?[A-Za-z0-9][\w-]*)")
OPTIONS_SECTION_HEADINGS = ("options:", "optional arguments:")
HELP_COLUMN_SEPARATOR = "  "


def scan_partial_word(line: str, cursor: int) -> PartialWord:
    """Return the word the cursor sits in, honouring the tokenizer's quoting rules

    Args:
        line: The whole command line
        cursor: The position of the cursor within it

    Returns:
        The word's start, its unquoted value so far, the quote still open, and where it sits
    """
    index = 0
    in_word = False
    start = cursor
    value = ""
    quote = QuoteStyle.NONE
    word_count = 0
    after_redirect = False
    command_name = None

    def finish_word() -> None:
        nonlocal word_count, after_redirect, command_name, in_word
        if word_count == 0 and not after_redirect:
            command_name = value
        word_count += 1
        after_redirect = False
        in_word = False

    while index < cursor:
        character = line[index]
        if not in_word:
            if character in WHITESPACE:
                index += 1
                continue
            if character in "|&;":
                index += 2 if line[index : index + 2] in ("||", "&&") else 1
                word_count = 0
                after_redirect = False
                command_name = None
                continue
            if character == ">":
                index += 2 if line[index + 1 : index + 2] == ">" else 1
                after_redirect = True
                continue
            in_word = True
            start = index
            value = ""
            quote = QuoteStyle.NONE
            continue
        if quote == QuoteStyle.SINGLE:
            if character == "'":
                quote = QuoteStyle.NONE
            else:
                value += character
            index += 1
            continue
        if quote == QuoteStyle.DOUBLE:
            if character == '"':
                quote = QuoteStyle.NONE
                index += 1
            elif character == "\\" and index + 1 < cursor:
                value += line[index + 1]
                index += 2
            else:
                value += character
                index += 1
            continue
        if character in "'\"":
            quote = QuoteStyle(character)
            index += 1
            continue
        if character == "\\":
            if index + 1 < cursor:
                value += line[index + 1]
            index += 2 if index + 1 < cursor else 1
            continue
        if character in WORD_BREAKERS:
            finish_word()
            continue
        value += character
        index += 1

    if not in_word:
        start = cursor
        value = ""
        quote = QuoteStyle.NONE
    if after_redirect:
        position = WordPosition.REDIRECT_TARGET
    elif word_count == 0:
        position = WordPosition.COMMAND
    else:
        position = WordPosition.ARGUMENT
    return PartialWord(start=start, value=value, quote=quote, position=position, command_name=command_name)


def render_word(value: str, quote: QuoteStyle, final: bool) -> str:
    """Return a completed value written back in the word's original quoting style

    Args:
        value: The literal text to write
        quote: The quote the word was opened with, if any
        final: Whether the word is complete, which closes the quote and adds a space

    Returns:
        The text to put in the line in place of the partial word
    """
    if quote == QuoteStyle.SINGLE and "'" not in value:
        return f"'{value}' " if final else f"'{value}"
    if quote == QuoteStyle.DOUBLE:
        escaped = "".join(
            f"\\{character}" if character in DOUBLE_QUOTED_SPECIAL_CHARACTERS else character for character in value
        )
        return f'"{escaped}" ' if final else f'"{escaped}'
    tilde = "~" if value.startswith("~") else ""
    escaped = tilde + "".join(
        f"\\{character}" if character in UNQUOTED_SPECIAL_CHARACTERS else character for character in value[len(tilde) :]
    )
    return f"{escaped} " if final else escaped


def name_candidates(prefix: str, names: Sequence[str]) -> list[Candidate]:
    """Return the names that start with prefix as candidates

    Args:
        prefix: The text typed so far
        names: The names to choose from

    Returns:
        One candidate per matching name, in the order given
    """
    return [Candidate(value=name, display=name, is_directory=False) for name in names if name.startswith(prefix)]


def option_names_from_help(help_text: str) -> list[str]:
    """Return every option name listed in an argparse help text

    Args:
        help_text: The output of a command's --help

    Returns:
        The short and long option names, in order of appearance, without duplicates
    """
    lowered = help_text.lower()
    section_start = max(lowered.rfind(heading) for heading in OPTIONS_SECTION_HEADINGS)
    section = help_text[section_start:] if section_start != -1 else help_text
    names: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        option_part = stripped.split(HELP_COLUMN_SEPARATOR)[0]
        for name in OPTION_NAME.findall(option_part):
            if name not in names:
                names.append(name)
    return names


def flag_candidates(prefix: str, command_name: str) -> list[Candidate]:
    """Return the options of a package command that start with prefix

    Args:
        prefix: The text typed so far, starting with a dash
        command_name: The package command whose help is consulted

    Returns:
        One candidate per matching option name
    """
    return name_candidates(prefix, option_names_from_help(command_help_text(command_name)))


def path_candidates(prefix: str, home: str) -> list[Candidate]:
    """Return the filesystem entries that continue prefix

    A leading ~ is expanded for the lookup and kept in the candidate values

    Args:
        prefix: The path typed so far
        home: The directory a bare ~ stands for

    Returns:
        One candidate per matching entry, directories with a trailing slash
    """
    slash = prefix.rfind("/")
    directory_part = prefix[: slash + 1] if slash != -1 else ""
    base = prefix[slash + 1 :] if slash != -1 else prefix
    listing_directory = Path(expand_tilde(directory_part, home) or ".")
    try:
        entries = sorted(listing_directory.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return []
    candidates: list[Candidate] = []
    for entry in entries:
        if not entry.name.startswith(base):
            continue
        suffix = "/" if entry.is_dir() else ""
        candidates.append(
            Candidate(
                value=directory_part + entry.name + suffix, display=entry.name + suffix, is_directory=entry.is_dir()
            )
        )
    return candidates


def build_completion_result(word: PartialWord, candidates: Sequence[Candidate]) -> CompletionResult:
    """Return what the line editor should do with the candidates for a word

    Args:
        word: The partial word being completed
        candidates: Every value that could complete it

    Returns:
        A replacement when one candidate or a longer common prefix exists, else a listing
    """
    if not candidates:
        return CompletionResult(word_start=word.start, replacement=None, listing=())
    if len(candidates) == 1:
        only = candidates[0]
        return CompletionResult(
            word_start=word.start,
            replacement=render_word(only.value, word.quote, final=not only.is_directory),
            listing=(),
        )
    common = os.path.commonprefix([candidate.value for candidate in candidates])
    if len(common) > len(word.value):
        return CompletionResult(
            word_start=word.start, replacement=render_word(common, word.quote, final=False), listing=()
        )
    return CompletionResult(
        word_start=word.start, replacement=None, listing=tuple(candidate.display for candidate in candidates)
    )


def complete(
    line: str,
    cursor: int,
    builtin_names: Sequence[str],
    package_names: Sequence[str],
    host_names: Sequence[str],
    home: str,
) -> CompletionResult:
    """Return the completion for the word under the cursor

    Command names complete in command position, options complete after a dash on a
    package command, and paths complete everywhere else

    Args:
        line: The whole command line
        cursor: The position of the cursor within it
        builtin_names: The shell's own commands
        package_names: The commands the package ships
        host_names: The commands the embedding host runs
        home: The directory a bare ~ stands for

    Returns:
        A replacement for the word or a listing of candidates
    """
    word = scan_partial_word(line, cursor)
    if word.position == WordPosition.COMMAND:
        candidates = name_candidates(word.value, sorted({*builtin_names, *package_names, *host_names}))
    elif (
        word.position == WordPosition.ARGUMENT
        and word.value.startswith("-")
        and word.command_name in package_names
        and word.command_name not in builtin_names
    ):
        candidates = flag_candidates(word.value, word.command_name)
    else:
        candidates = path_candidates(word.value, home)
    return build_completion_result(word, candidates)
