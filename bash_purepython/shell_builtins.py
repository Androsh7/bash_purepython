"""Implement the builtins that change the shell itself rather than produce output"""

# Standard libraries
import re
import shlex
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Project libraries
from bash_purepython.arithmetic import evaluate_arithmetic
from bash_purepython.command.command import OutputKind
from bash_purepython.shell_state import (
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_USAGE_ERROR,
    ShellOption,
    ShellState,
)
from bash_purepython.streams import as_async_iterator, close_iterator, convert, materialise_text
from bash_purepython.words import decode_ansi_c_escapes, expand_text, field_separators

if TYPE_CHECKING:
    from bash_purepython.execute_command import Executor, StdinValue

DEFAULT_READ_VARIABLE_NAME = "REPLY"
HOME_VARIABLE_NAME = "HOME"
HOME_SHORTHAND = "~"
SHELL_KEYWORDS = frozenset(
    {
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "in",
        "function",
        "select",
        "time",
        "!",
        "[[",
        "]]",
        "{",
        "}",
    }
)
COMMAND_PATH_PREFIX = "/usr/bin/"
BASH_BUILTIN_COMMAND_NAMES = frozenset({"echo", "printf", "test", "[", "pwd", "kill", "true", "false", "help"})
XARGS_FAILURE_EXIT_CODE = 123
XARGS_DEFAULT_COMMAND = "echo"
XARGS_LONG_OPTION_LETTERS = {"--max-args": "n", "--replace": "I", "--delimiter": "d"}
OPTION_LETTERS = {"e": ShellOption.ERREXIT, "u": ShellOption.NOUNSET, "x": ShellOption.XTRACE}
OPTION_NAMES = {
    "errexit": ShellOption.ERREXIT,
    "nounset": ShellOption.NOUNSET,
    "xtrace": ShellOption.XTRACE,
    "pipefail": ShellOption.PIPEFAIL,
}
ALIAS_DEFINITION_PATTERN = re.compile(r"^([^=\s/]+)=(.*)$", re.DOTALL)
NAME_PATTERN = re.compile(r"^[A-Za-z_]\w*$")
NUL_DELIMITER = "\0"
DECLARE_ATTRIBUTE_LETTERS = frozenset("aixrfFgp")
UNSUPPORTED_BUILTINS = ("exec", "trap", "getopts")
BUILTIN_SUMMARIES = {
    "read": "read a line into variables",
    "shift": "drop the first positional arguments",
    "set": "set shell options or the positional arguments",
    "local": "declare variables local to a function",
    "eval": "run the arguments as a script",
    "type": "describe how a name would be run",
    "command": "run a command, ignoring functions and aliases",
    "alias": "define or list aliases",
    "unalias": "remove aliases",
    "pushd": "push the directory stack and change directory",
    "popd": "pop the directory stack and change directory",
    "dirs": "list the directory stack",
    "let": "evaluate arithmetic expressions",
    "declare": "declare variables and attributes",
    "typeset": "declare variables and attributes",
    "readonly": "mark variables read-only",
    "hash": "accepted, nothing is looked up on a path",
    "xargs": "build and run command lines from standard input",
    "exec": "not supported in this shell",
    "trap": "not supported in this shell",
    "getopts": "not supported in this shell",
}


class LineSource:
    """Hand out one line at a time from a stream of text chunks, keeping the rest for later reads"""

    def __init__(self, chunks: AsyncIterator[str]):
        """Wrap one stream

        Args:
            chunks: The text chunks in order
        """
        self.chunks = chunks
        self.buffer = ""
        self.exhausted = False

    async def read_until(self, delimiter: str) -> str | None:
        """Return the text up to and excluding the next delimiter, or None at the end of the input

        Args:
            delimiter: The character that ends a record, or empty to read a single character

        Returns:
            The record, or None when nothing is left; a final record without its delimiter is still returned
        """
        while True:
            if delimiter:
                index = self.buffer.find(delimiter)
                if index != -1:
                    record = self.buffer[:index]
                    self.buffer = self.buffer[index + 1 :]
                    return record
            elif self.buffer:
                record, self.buffer = self.buffer[0], self.buffer[1:]
                return record
            if self.exhausted:
                if not self.buffer:
                    return None
                record, self.buffer = self.buffer, ""
                return record
            try:
                self.buffer += await self.chunks.__anext__()
            except StopAsyncIteration:
                self.exhausted = True

    def __aiter__(self) -> AsyncIterator[str]:
        """Return the unread text as a stream, the buffered part first"""
        return self.remaining()

    async def remaining(self) -> AsyncIterator[str]:
        """Yield what has not been read yet

        Yields:
            The buffered text, then every further chunk
        """
        if self.buffer:
            buffered, self.buffer = self.buffer, ""
            yield buffered
        if self.exhausted:
            return
        async for chunk in self.chunks:
            yield chunk
        self.exhausted = True

    async def aclose(self) -> None:
        """Stop the underlying stream"""
        self.exhausted = True
        await close_iterator(self.chunks)


def parse_array_literal(value: str) -> dict[int, str] | None:
    """Return the elements of a ``(first second)`` value, or None when the value is not one

    Args:
        value: The text after the equals sign of a declaration

    Returns:
        The elements split as shell words, indexed from zero, or None when the value is not a well-formed literal
    """
    if not (value.startswith("(") and value.endswith(")")):
        return None
    try:
        elements = shlex.split(value[1:-1])
    except ValueError:
        return None
    return dict(enumerate(elements))


@dataclass
class ReadOptions:
    """Hold the options of one ``read`` call"""

    raw: bool = False
    prompt: str = ""
    array_name: str | None = None
    delimiter: str = "\n"
    character_count: int | None = None
    names: list[str] = field(default_factory=list)


def parse_read_options(arguments: list[str]) -> ReadOptions | str:
    """Return the options of a ``read`` call, or the message for a bad one

    Args:
        arguments: The arguments after the command name

    Returns:
        The options, or an error message
    """
    options = ReadOptions()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            index += 1
            break
        if not argument.startswith("-") or argument == "-":
            break
        letters = argument[1:]
        letter_index = 0
        while letter_index < len(letters):
            letter = letters[letter_index]
            inline_value = letters[letter_index + 1 :]
            if letter in "pad nNt":
                if inline_value:
                    value = inline_value
                elif index + 1 < len(arguments):
                    index += 1
                    value = arguments[index]
                else:
                    return f"read: -{letter}: option requires an argument"
                if letter == "p":
                    options.prompt = value
                elif letter == "a":
                    options.array_name = value
                elif letter == "d":
                    options.delimiter = value[:1] or NUL_DELIMITER
                elif letter in "nN":
                    if not value.isdigit():
                        return f"read: {value}: invalid number"
                    options.character_count = int(value)
                break
            if letter == "r":
                options.raw = True
            elif letter in "se":
                pass
            else:
                return f"read: -{letter}: invalid option"
            letter_index += 1
        index += 1
    options.names = arguments[index:]
    for name in options.names:
        if NAME_PATTERN.match(name) is None:
            return f"read: `{name}': not a valid identifier"
    return options


def read_characters(text: str, raw: bool) -> list[tuple[str, bool]]:
    """Return each character of a read line paired with whether a backslash protected it

    Without ``-r`` a backslash is dropped and the character after it kept and protected from splitting, and a
    backslash before a newline removes both

    Args:
        text: The raw line
        raw: Whether ``-r`` was given, leaving backslashes as ordinary characters

    Returns:
        The characters of the line, each with True when it was escaped
    """
    if raw:
        return [(character, False) for character in text]
    characters: list[tuple[str, bool]] = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            if text[index + 1] != "\n":
                characters.append((text[index + 1], True))
            index += 2
        else:
            characters.append((text[index], False))
            index += 1
    return characters


def split_read_fields(characters: list[tuple[str, bool]], separators: str, limit: int | None) -> list[str]:
    """Return the fields of a read line, the last one holding everything that remains when there is a limit

    Escaped characters never separate fields. Surrounding ``IFS`` whitespace is dropped, and each separator is
    a run of ``IFS`` whitespace around at most one other ``IFS`` character

    Args:
        characters: The line's characters, each with whether it was escaped
        separators: The ``IFS`` characters
        limit: How many variables receive fields, or None to split the whole line as for ``-a``

    Returns:
        Exactly ``limit`` values padded with empty strings, or every field when there is no limit
    """
    whitespace = {character for character in separators if character in " \t\n"}

    def is_whitespace(position: int) -> bool:
        character, escaped = characters[position]
        return not escaped and character in whitespace

    def is_separator(position: int) -> bool:
        character, escaped = characters[position]
        return not escaped and character in separators

    start = 0
    end = len(characters)
    while start < end and is_whitespace(start):
        start += 1
    while end > start and is_whitespace(end - 1):
        end -= 1
    fields: list[str] = []
    position = start
    while position < end and (limit is None or len(fields) < limit - 1):
        field_start = position
        while position < end and not is_separator(position):
            position += 1
        fields.append("".join(character for character, _ in characters[field_start:position]))
        while position < end and is_whitespace(position):
            position += 1
        if position < end and is_separator(position):
            position += 1
            while position < end and is_whitespace(position):
                position += 1
    if limit is None:
        return fields
    if position < end or len(fields) < limit:
        fields.append("".join(character for character, _ in characters[position:end]))
    return (fields + [""] * limit)[:limit]


@dataclass
class XargsOptions:
    """Hold the options of one ``xargs`` call"""

    batch_size: int | None = None
    replacement: str | None = None
    delimiter: str | None = None
    trace: bool = False
    command: list[str] = field(default_factory=list)


def parse_xargs_options(arguments: list[str]) -> XargsOptions | str:
    """Return the options of an ``xargs`` call, or the message for a bad one

    Args:
        arguments: The arguments after the command name

    Returns:
        The options, or an error message
    """
    options = XargsOptions()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            index += 1
            break
        if not argument.startswith("-") or argument == "-":
            break
        if argument in ("-0", "--null"):
            options.delimiter = "\0"
        elif argument in ("-t", "--verbose"):
            options.trace = True
        elif argument in ("-r", "--no-run-if-empty"):
            pass
        elif argument in XARGS_LONG_OPTION_LETTERS or argument[1] in "nId":
            letter = XARGS_LONG_OPTION_LETTERS.get(argument, argument[1])
            if argument not in XARGS_LONG_OPTION_LETTERS and len(argument) > 2:
                value = argument[2:]
            elif index + 1 < len(arguments):
                index += 1
                value = arguments[index]
            else:
                return f"option requires an argument -- '{letter}'"
            if letter == "n":
                if not value.isdigit() or int(value) < 1:
                    return f"invalid number for -n option: {value}"
                options.batch_size = int(value)
            elif letter == "I":
                options.replacement = value
            else:
                options.delimiter = decode_ansi_c_escapes(value)[:1] or "\n"
        else:
            return f"invalid option -- '{argument[1]}'"
        index += 1
    options.command = arguments[index:]
    return options


def split_xargs_items(text: str, options: XargsOptions) -> list[str]:
    """Return the items ``xargs`` reads from its input

    With ``-I`` each line is one item; with a delimiter the text is cut at it; otherwise it is split at
    blanks with quotes grouping words, as xargs does

    Args:
        text: The whole input
        options: The call's options

    Returns:
        The items in order
    """
    if options.replacement is not None:
        return [line for line in text.split("\n") if line.strip()]
    if options.delimiter is not None:
        items = text.split(options.delimiter)
        if items and items[-1] == "":
            items.pop()
        return items
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def shorten_home(path: Path, state: ShellState) -> str:
    """Return a path with the home directory replaced by a tilde, as pushd and dirs print it

    Args:
        path: The path to print
        state: The shell state holding ``HOME``

    Returns:
        The shortened text
    """
    home = state.variables.get(HOME_VARIABLE_NAME)
    text = path.as_posix()
    if home and (text == Path(home).as_posix() or text.startswith(Path(home).as_posix().rstrip("/") + "/")):
        return HOME_SHORTHAND + text[len(Path(home).as_posix().rstrip("/")) :]
    return text


def quote_for_declare(value: str) -> str:
    """Return a value quoted the way ``declare -p`` prints it

    Args:
        value: The text to quote

    Returns:
        The text in double quotes with the characters special inside them escaped
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


class ShellBuiltins:
    """Group the builtins that need the executor, each taking the arguments, standard input and state"""

    def __init__(self, executor: "Executor"):
        """Bind to one executor

        Args:
            executor: The executor whose scripts the builtins run and whose registry they consult
        """
        self.executor = executor

    def table(self) -> dict[str, Callable[[list[str], "StdinValue | None", ShellState], Awaitable[int]]]:
        """Return every builtin by name"""
        return {
            "read": self.read,
            "shift": self.shift,
            "set": self.set_options,
            "local": self.local,
            "eval": self.eval,
            "type": self.type,
            "command": self.command,
            "alias": self.alias,
            "unalias": self.unalias,
            "pushd": self.pushd,
            "popd": self.popd,
            "dirs": self.dirs,
            "let": self.let,
            "declare": self.declare,
            "typeset": self.declare,
            "readonly": self.readonly,
            "hash": self.hash,
            "xargs": self.xargs,
            **{name: self.unsupported_builtin(name) for name in UNSUPPORTED_BUILTINS},
        }

    async def read(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Read one line into variables, from the piped or redirected input or else from the terminal

        Args:
            arguments: Options and the variable names, ``REPLY`` when none are given
            stdin: Input piped or redirected into this call, or None
            state: The shell state whose variables receive the fields

        Returns:
            Zero when a line was read, one at the end of the input, two for a bad option
        """
        options = parse_read_options(arguments)
        if isinstance(options, str):
            state.write_error(f"bash: {options}\n")
            return EXIT_CODE_USAGE_ERROR
        targets = [options.array_name] if options.array_name is not None else options.names
        for name in targets or [DEFAULT_READ_VARIABLE_NAME]:
            if name in state.readonly_names:
                state.write_error(f"bash: {name}: readonly variable\n")
                return EXIT_CODE_FAILURE
        line = await self.read_record(options, stdin, state)
        if line is None:
            return EXIT_CODE_FAILURE
        text, finished = line
        characters = read_characters(text, options.raw)
        separators = field_separators(state)
        if options.array_name is not None:
            state.variables.pop(options.array_name, None)
            state.arrays[options.array_name] = dict(enumerate(split_read_fields(characters, separators, None)))
        elif not options.names:
            self.assign(DEFAULT_READ_VARIABLE_NAME, "".join(character for character, _ in characters), state)
        else:
            values = split_read_fields(characters, separators, len(options.names))
            for name, value in zip(options.names, values, strict=True):
                self.assign(name, value, state)
        return EXIT_CODE_SUCCESS if finished else EXIT_CODE_FAILURE

    def assign(self, name: str, value: str, state: ShellState) -> None:
        """Store a scalar, replacing an array of the same name

        Args:
            name: The variable name
            value: The value
            state: The shell state to change
        """
        state.arrays.pop(name, None)
        state.variables[name] = value

    async def read_record(
        self, options: ReadOptions, stdin: "StdinValue | None", state: ShellState
    ) -> tuple[str, bool] | None:
        """Return the next record of the input and whether its delimiter was seen, or None at the end

        Args:
            options: The call's options, giving the delimiter and character count
            stdin: Input piped or redirected into this call, or None
            state: The shell state holding any input the enclosing command received and the terminal reader

        Returns:
            The text and whether it ended with the delimiter rather than the end of the input, or None
        """
        source = stdin if stdin is not None else state.pending_stdin
        if source is None:
            return await self.read_terminal_record(options, state)
        if not isinstance(source.value, LineSource):
            chunks = as_async_iterator(await convert(source.value, source.kind, OutputKind.STREAM_TEXT))
            source = self.executor.stdin_value(LineSource(chunks), OutputKind.STREAM_TEXT)
            if stdin is None:
                state.pending_stdin = source
        line_source: LineSource = source.value
        try:
            return await self.read_from_source(line_source, options)
        finally:
            if stdin is not None:
                await line_source.aclose()

    async def read_from_source(self, line_source: LineSource, options: ReadOptions) -> tuple[str, bool] | None:
        """Return the next record of a line source and whether its delimiter was seen, or None at the end

        Args:
            line_source: The input being read
            options: The call's options, giving the delimiter and character count

        Returns:
            The text and whether it ended with the delimiter rather than the end of the input, or None
        """
        if options.character_count is not None:
            pieces: list[str] = []
            for _ in range(options.character_count):
                character = await line_source.read_until("")
                if character is None:
                    break
                pieces.append(character)
            return ("".join(pieces), bool(pieces)) if pieces or not line_source.exhausted else None
        record = await line_source.read_until(options.delimiter)
        if record is None:
            return None
        delimited = not line_source.exhausted or bool(line_source.buffer)
        if not options.raw:
            while record.endswith("\\") and not record.endswith("\\\\"):
                more = await line_source.read_until(options.delimiter)
                if more is None:
                    break
                record = record[:-1] + more
        return record, delimited

    async def read_terminal_record(self, options: ReadOptions, state: ShellState) -> tuple[str, bool] | None:
        """Return a line typed at the terminal, or None when the host provides no input

        Args:
            options: The call's options, giving the prompt
            state: The shell state holding the host's line reader

        Returns:
            The line without its newline and True, or None at the end of input
        """
        if state.read_line is None:
            return None
        if options.prompt:
            state.write_error(options.prompt)
        line: Any = state.read_line()
        if hasattr(line, "__await__"):
            line = await line
        if line is None:
            return None
        text = str(line).removesuffix("\n")
        if options.character_count is not None:
            text = text[: options.character_count]
        return text, True

    async def shift(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Drop the first positional arguments

        Args:
            arguments: How many to drop, one by default
            stdin: Ignored
            state: The shell state whose positional arguments change

        Returns:
            Zero, or one when there are not enough arguments to drop
        """
        count = 1
        if arguments:
            if not arguments[0].lstrip("-").isdigit():
                state.write_error(f"bash: shift: {arguments[0]}: numeric argument required\n")
                return EXIT_CODE_FAILURE
            count = int(arguments[0])
        if count < 0 or count > len(state.positional_arguments):
            return EXIT_CODE_FAILURE
        state.positional_arguments = state.positional_arguments[count:]
        return EXIT_CODE_SUCCESS

    async def set_options(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Change shell options or the positional arguments, or list every variable

        Args:
            arguments: ``-e``, ``-u``, ``-x``, ``-o name`` and their ``+`` forms, or ``--`` and the new arguments
            stdin: Ignored
            state: The shell state to change

        Returns:
            Zero, or two for an unknown option
        """
        if not arguments:
            for name in sorted(state.variables):
                await state.output_sink.write(f"{name}={state.variables[name]}\n")
            return EXIT_CODE_SUCCESS
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--":
                state.positional_arguments = arguments[index + 1 :]
                return EXIT_CODE_SUCCESS
            if argument in ("-", "+") or not argument.startswith(("-", "+")):
                state.positional_arguments = arguments[index:]
                return EXIT_CODE_SUCCESS
            enable = argument[0] == "-"
            for letter in argument[1:]:
                if letter == "o":
                    index += 1
                    if index >= len(arguments):
                        await self.print_options(state)
                        return EXIT_CODE_SUCCESS
                    option = OPTION_NAMES.get(arguments[index])
                    if option is None:
                        state.write_error(f"bash: set: {arguments[index]}: invalid option name\n")
                        return EXIT_CODE_USAGE_ERROR
                    self.apply_option(option, enable, state)
                elif letter in OPTION_LETTERS:
                    self.apply_option(OPTION_LETTERS[letter], enable, state)
                elif letter in "fhvnBCHP":
                    pass
                else:
                    state.write_error(f"bash: set: {argument[0]}{letter}: invalid option\n")
                    return EXIT_CODE_USAGE_ERROR
            index += 1
        return EXIT_CODE_SUCCESS

    def apply_option(self, option: ShellOption, enable: bool, state: ShellState) -> None:
        """Turn one option on or off

        Args:
            option: The option
            enable: True to turn it on
            state: The shell state holding the options
        """
        if enable:
            state.options.add(option)
        else:
            state.options.discard(option)

    async def print_options(self, state: ShellState) -> None:
        """Print every known option with its current setting

        Args:
            state: The shell state holding the options
        """
        for name, option in OPTION_NAMES.items():
            setting = "on" if option in state.options else "off"
            await state.output_sink.write(f"{name:<15} {setting}\n")

    async def local(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Declare variables that are restored when the current function returns

        Args:
            arguments: Names, ``name=value`` assignments, and ``-a`` for arrays
            stdin: Ignored
            state: The shell state holding the function's scope

        Returns:
            Zero, or one outside any function or when a name is readonly
        """
        if not state.local_scopes:
            state.write_error("bash: local: can only be used in a function\n")
            return EXIT_CODE_FAILURE
        make_array = False
        exit_code = EXIT_CODE_SUCCESS
        for argument in arguments:
            if argument.startswith("-"):
                make_array = "a" in argument
                continue
            name, separator, value = argument.partition("=")
            if NAME_PATTERN.match(name) is None:
                state.write_error(f"bash: local: `{argument}': not a valid identifier\n")
                return EXIT_CODE_FAILURE
            if name in state.readonly_names:
                state.write_error(f"bash: local: {name}: readonly variable\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            self.remember_outer_value(name, state)
            elements = parse_array_literal(value) if separator else None
            if make_array or elements is not None:
                state.variables.pop(name, None)
                if elements is not None:
                    state.arrays[name] = elements
                else:
                    state.arrays[name] = {0: value} if separator else {}
            elif separator:
                state.arrays.pop(name, None)
                state.variables[name] = value
            else:
                state.variables.pop(name, None)
                state.arrays.pop(name, None)
        return exit_code

    def remember_outer_value(self, name: str, state: ShellState) -> None:
        """Record a variable's value from before the function changed it, once per scope

        Args:
            name: The variable name
            state: The shell state holding the function's scope
        """
        scope = state.local_scopes[-1]
        if name not in scope:
            elements = state.arrays.get(name)
            scope[name] = (state.variables.get(name), None if elements is None else dict(elements))

    async def eval(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Run the arguments joined by spaces as a script

        Args:
            arguments: The pieces of script text
            stdin: Ignored
            state: The shell state to run against

        Returns:
            The script's exit code
        """
        script = " ".join(arguments)
        if not script.strip():
            return EXIT_CODE_SUCCESS
        return await self.executor.run_script(script, state)

    async def type(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Describe how each name would be interpreted as a command

        Args:
            arguments: ``-t`` for the kind alone, ``-p`` for the path alone, ``-a`` accepted, then the names
            stdin: Ignored
            state: The shell state holding aliases and functions

        Returns:
            Zero, or one when any name is unknown
        """
        kind_only = False
        path_only = False
        names: list[str] = []
        for argument in arguments:
            if argument.startswith("-") and len(argument) > 1 and not names:
                kind_only = kind_only or "t" in argument
                path_only = path_only or "p" in argument or "P" in argument
            else:
                names.append(argument)
        exit_code = EXIT_CODE_SUCCESS
        for name in names:
            kind, description = self.describe(name, state)
            if kind is None:
                if not kind_only and not path_only:
                    state.write_error(f"bash: type: {name}: not found\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            if kind_only:
                await state.output_sink.write(f"{kind}\n")
            elif path_only:
                if kind == "file":
                    await state.output_sink.write(f"{COMMAND_PATH_PREFIX}{name}\n")
            else:
                await state.output_sink.write(description + "\n")
        return exit_code

    def describe(self, name: str, state: ShellState) -> tuple[str | None, str]:
        """Return the kind of command a name is and the sentence ``type`` prints for it

        Args:
            name: The command name
            state: The shell state holding aliases and functions

        Returns:
            The kind (``alias``, ``keyword``, ``function``, ``builtin``, ``file`` or None) and the description
        """
        if name in state.aliases:
            return "alias", f"{name} is aliased to `{state.aliases[name]}'"
        if name in SHELL_KEYWORDS:
            return "keyword", f"{name} is a shell keyword"
        if name in state.functions:
            return "function", f"{name} is a function\n{name} () \n{state.functions[name]}"
        if (
            name in self.executor.builtins
            or name in self.executor.script_command_names
            or name in BASH_BUILTIN_COMMAND_NAMES
        ):
            return "builtin", f"{name} is a shell builtin"
        if self.executor.registry.get(name) is not None:
            return "file", f"{name} is {COMMAND_PATH_PREFIX}{name}"
        return None, ""

    async def command(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Run a command bypassing functions and aliases, or describe it with ``-v`` or ``-V``

        Args:
            arguments: Options then the command and its arguments
            stdin: Standard input for the command, or None
            state: The shell state to run against

        Returns:
            The command's exit code, or one when a name to describe is unknown
        """
        describe = False
        verbose = False
        index = 0
        while index < len(arguments) and arguments[index].startswith("-") and len(arguments[index]) > 1:
            describe = describe or "v" in arguments[index] or "V" in arguments[index]
            verbose = verbose or "V" in arguments[index]
            index += 1
        rest = arguments[index:]
        if describe:
            exit_code = EXIT_CODE_SUCCESS
            for name in rest:
                kind, description = self.describe(name, state)
                if kind is None:
                    exit_code = EXIT_CODE_FAILURE
                elif verbose:
                    await state.output_sink.write(description + "\n")
                elif kind == "alias":
                    await state.output_sink.write(f"alias {name}='{state.aliases[name]}'\n")
                elif kind == "file":
                    await state.output_sink.write(f"{COMMAND_PATH_PREFIX}{name}\n")
                else:
                    await state.output_sink.write(f"{name}\n")
            return exit_code
        if not rest:
            return EXIT_CODE_SUCCESS
        return await self.executor.run_bypassing_functions(rest[0], rest[1:], stdin, state)

    async def alias(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Define aliases, or print the ones named or every one

        Args:
            arguments: ``name=value`` definitions or names to print
            stdin: Ignored
            state: The shell state holding the aliases

        Returns:
            Zero, or one when a name to print is not an alias
        """
        if not arguments or arguments == ["-p"]:
            for name in sorted(state.aliases):
                await state.output_sink.write(f"alias {name}='{state.aliases[name]}'\n")
            return EXIT_CODE_SUCCESS
        exit_code = EXIT_CODE_SUCCESS
        for argument in arguments:
            if argument == "-p":
                continue
            match = ALIAS_DEFINITION_PATTERN.match(argument)
            if match is not None:
                state.aliases[match.group(1)] = match.group(2)
            elif argument in state.aliases:
                await state.output_sink.write(f"alias {argument}='{state.aliases[argument]}'\n")
            else:
                state.write_error(f"bash: alias: {argument}: not found\n")
                exit_code = EXIT_CODE_FAILURE
        return exit_code

    async def unalias(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Remove aliases by name, or every one with ``-a``

        Args:
            arguments: The names, or ``-a``
            stdin: Ignored
            state: The shell state holding the aliases

        Returns:
            Zero, or one when a name is not an alias
        """
        if "-a" in arguments:
            state.aliases.clear()
            return EXIT_CODE_SUCCESS
        exit_code = EXIT_CODE_SUCCESS
        for name in arguments:
            if state.aliases.pop(name, None) is None:
                state.write_error(f"bash: unalias: {name}: not found\n")
                exit_code = EXIT_CODE_FAILURE
        return exit_code

    async def pushd(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Push the current directory and change to another, or swap the top two without arguments

        Args:
            arguments: The directory to change to, or nothing
            stdin: Ignored
            state: The shell state whose directory and stack change

        Returns:
            Zero, or one when the directory does not exist or the stack is too short
        """
        if not arguments:
            if not state.directory_stack:
                state.write_error("bash: pushd: no other directory\n")
                return EXIT_CODE_FAILURE
            target = state.directory_stack.pop()
            state.directory_stack.append(state.cwd)
        else:
            target = state.resolve_path(arguments[0])
            if not target.is_dir():
                state.write_error(f"bash: pushd: {arguments[0]}: No such file or directory\n")
                return EXIT_CODE_FAILURE
            state.directory_stack.append(state.cwd)
        self.executor.change_directory(target, state)
        await self.print_directory_stack(state)
        return EXIT_CODE_SUCCESS

    async def popd(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Change to the directory on top of the stack and drop it

        Args:
            arguments: Ignored
            stdin: Ignored
            state: The shell state whose directory and stack change

        Returns:
            Zero, or one when the stack is empty
        """
        if not state.directory_stack:
            state.write_error("bash: popd: directory stack empty\n")
            return EXIT_CODE_FAILURE
        target = state.directory_stack.pop()
        self.executor.change_directory(target, state)
        await self.print_directory_stack(state)
        return EXIT_CODE_SUCCESS

    async def dirs(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Print the directory stack, clear it with ``-c``, or print one entry per line with ``-v``

        Args:
            arguments: ``-c`` or ``-v``
            stdin: Ignored
            state: The shell state holding the stack

        Returns:
            Zero
        """
        if "-c" in arguments:
            state.directory_stack.clear()
            return EXIT_CODE_SUCCESS
        entries = [state.cwd, *reversed(state.directory_stack)]
        if "-v" in arguments:
            for index, entry in enumerate(entries):
                await state.output_sink.write(f"{index:>2}  {shorten_home(entry, state)}\n")
            return EXIT_CODE_SUCCESS
        await self.print_directory_stack(state)
        return EXIT_CODE_SUCCESS

    async def print_directory_stack(self, state: ShellState) -> None:
        """Print the current directory followed by the stack, newest first, on one line

        Args:
            state: The shell state holding the stack
        """
        entries = [state.cwd, *reversed(state.directory_stack)]
        await state.output_sink.write(" ".join(shorten_home(entry, state) for entry in entries) + "\n")

    async def let(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Evaluate each argument as an arithmetic expression

        Args:
            arguments: The expressions
            stdin: Ignored
            state: The shell state whose variables are read and assigned

        Returns:
            Zero when the last expression is nonzero, otherwise one
        """
        if not arguments:
            state.write_error("bash: let: expression expected\n")
            return EXIT_CODE_FAILURE
        value = 0
        for expression in arguments:
            expanded = await expand_text(
                expression, state, self.executor.substitution_runner(state), in_double_quotes=False
            )
            value = evaluate_arithmetic(expanded, state)
        return EXIT_CODE_SUCCESS if value != 0 else EXIT_CODE_FAILURE

    async def declare(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Declare variables with attributes, or print declarations with ``-p``

        Inside a function a declaration is local unless ``-g`` is given, as in bash

        Args:
            arguments: Attribute options then names or ``name=value`` assignments
            stdin: Ignored
            state: The shell state to change

        Returns:
            Zero, or one when a name is invalid or not found
        """
        attributes: set[str] = set()
        names: list[str] = []
        for argument in arguments:
            if argument.startswith(("-", "+")) and len(argument) > 1 and not names:
                attributes.update(letter for letter in argument[1:] if argument[0] == "-")
            else:
                names.append(argument)
        if "f" in attributes or "F" in attributes:
            return await self.print_functions(names, "F" in attributes, state)
        if "p" in attributes:
            return await self.print_declarations(names, state)
        exit_code = EXIT_CODE_SUCCESS
        for argument in names:
            name, separator, value = argument.partition("=")
            index_text = None
            if name.endswith("]") and "[" in name:
                name, index_text = name[: name.index("[")], name[name.index("[") + 1 : -1]
            if NAME_PATTERN.match(name) is None:
                state.write_error(f"bash: declare: `{argument}': not a valid identifier\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            creates_local = bool(state.local_scopes) and "g" not in attributes and name not in state.local_scopes[-1]
            if name in state.readonly_names and (separator or creates_local):
                state.write_error(f"bash: declare: {name}: readonly variable\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            if creates_local:
                self.remember_outer_value(name, state)
                state.variables.pop(name, None)
                state.arrays.pop(name, None)
            if "i" in attributes and separator:
                expanded = await expand_text(
                    value, state, self.executor.substitution_runner(state), in_double_quotes=False
                )
                value = str(evaluate_arithmetic(expanded, state))
            if "a" in attributes or index_text is not None:
                elements = state.arrays.setdefault(
                    name, {0: state.variables.pop(name)} if name in state.variables else {}
                )
                literal_elements = parse_array_literal(value) if separator else None
                if index_text is not None:
                    elements[evaluate_arithmetic(index_text, state)] = value
                elif literal_elements is not None:
                    elements.clear()
                    elements.update(literal_elements)
            elif separator:
                state.arrays.pop(name, None)
                state.variables[name] = value
            elif name not in state.variables and name not in state.arrays and "i" in attributes:
                state.variables[name] = "0"
            if "x" in attributes:
                state.exported_names.add(name)
            if "r" in attributes:
                state.readonly_names.add(name)
        return exit_code

    async def print_functions(self, names: list[str], names_only: bool, state: ShellState) -> int:
        """Print function definitions, or just their names with ``-F``

        Args:
            names: The functions to print, or every one when empty
            names_only: Whether to print ``declare -f name`` lines instead of bodies
            state: The shell state holding the functions

        Returns:
            Zero, or one when a name is not a function
        """
        exit_code = EXIT_CODE_SUCCESS
        for name in names or sorted(state.functions):
            body = state.functions.get(name)
            if body is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            if names_only:
                await state.output_sink.write(f"declare -f {name}\n")
            else:
                await state.output_sink.write(f"{name} () \n{body}\n")
        return exit_code

    async def print_declarations(self, names: list[str], state: ShellState) -> int:
        """Print ``declare`` lines that would recreate the named variables, or every variable

        Args:
            names: The variables to print, or every one when empty
            state: The shell state holding the variables

        Returns:
            Zero, or one when a name is not set
        """
        exit_code = EXIT_CODE_SUCCESS
        for name in names or sorted(set(state.variables) | set(state.arrays)):
            flags = (
                "".join(
                    [
                        "a" if name in state.arrays else "",
                        "x" if name in state.exported_names else "",
                        "r" if name in state.readonly_names else "",
                    ]
                )
                or "-"
            )
            if name in state.arrays:
                elements = " ".join(
                    f"[{index}]={quote_for_declare(value)}" for index, value in sorted(state.arrays[name].items())
                )
                await state.output_sink.write(f"declare -{flags} {name}=({elements})\n")
            elif name in state.variables:
                await state.output_sink.write(f"declare -{flags} {name}={quote_for_declare(state.variables[name])}\n")
            else:
                state.write_error(f"bash: declare: {name}: not found\n")
                exit_code = EXIT_CODE_FAILURE
        return exit_code

    async def readonly(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Mark variables read-only, setting those given as ``name=value``

        Args:
            arguments: Names or assignments, or ``-p`` to list the read-only variables
            stdin: Ignored
            state: The shell state to change

        Returns:
            Zero, or one when a name is already read-only and given a new value
        """
        if not arguments or arguments == ["-p"]:
            for name in sorted(state.readonly_names):
                value = quote_for_declare(state.variables.get(name, ""))
                await state.output_sink.write(f"declare -r {name}={value}\n")
            return EXIT_CODE_SUCCESS
        for argument in arguments:
            if argument.startswith("-"):
                continue
            name, separator, value = argument.partition("=")
            if separator:
                if name in state.readonly_names:
                    state.write_error(f"bash: readonly: {name}: readonly variable\n")
                    return EXIT_CODE_FAILURE
                elements = parse_array_literal(value)
                if elements is not None:
                    state.variables.pop(name, None)
                    state.arrays[name] = elements
                else:
                    state.arrays.pop(name, None)
                    state.variables[name] = value
            state.readonly_names.add(name)
        return EXIT_CODE_SUCCESS

    async def hash(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Accept the command and do nothing, since nothing is looked up on a path

        Args:
            arguments: Ignored
            stdin: Ignored
            state: Ignored

        Returns:
            Zero
        """
        return EXIT_CODE_SUCCESS

    async def xargs(self, arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
        """Run a command with arguments taken from standard input

        Args:
            arguments: ``-n N``, ``-I replacement``, ``-0``, ``-d delimiter``, ``-t``, then the command and its
                leading arguments, ``echo`` when none is given
            stdin: The input the arguments come from, or None
            state: The shell state to run against

        Returns:
            Zero, 123 when any invocation failed, or two for a bad option
        """
        options = parse_xargs_options(arguments)
        if isinstance(options, str):
            state.write_error(f"xargs: {options}\n")
            return EXIT_CODE_USAGE_ERROR
        source = stdin if stdin is not None else state.pending_stdin
        state.pending_stdin = None
        text = "" if source is None else await materialise_text(source.value, source.kind)
        items = split_xargs_items(text, options)
        command = options.command or [XARGS_DEFAULT_COMMAND]
        if options.replacement is not None:
            batches = [[item] for item in items]
        elif options.batch_size is not None and items:
            batches = [items[start : start + options.batch_size] for start in range(0, len(items), options.batch_size)]
        else:
            batches = [items]
        exit_code = EXIT_CODE_SUCCESS
        for batch in batches:
            if options.replacement is not None:
                command_arguments = [argument.replace(options.replacement, batch[0]) for argument in command[1:]]
            else:
                command_arguments = [*command[1:], *batch]
            if options.trace:
                state.write_error(" ".join([command[0], *command_arguments]) + "\n")
            code = await self.executor.run_named_command(command[0], command_arguments, state)
            if code != EXIT_CODE_SUCCESS:
                exit_code = XARGS_FAILURE_EXIT_CODE
        return exit_code

    def unsupported_builtin(self, name: str) -> Callable[[list[str], "StdinValue | None", ShellState], Awaitable[int]]:
        """Return a builtin that reports the named one is not provided by this shell

        Args:
            name: The builtin's name, used in the message

        Returns:
            A builtin that writes the message and fails
        """

        async def unsupported(arguments: list[str], stdin: "StdinValue | None", state: ShellState) -> int:
            state.write_error(f"bash: {name}: not supported in this shell\n")
            return EXIT_CODE_FAILURE

        return unsupported
