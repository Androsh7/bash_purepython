"""Implement the commands that read or change the shell's own state"""

# Standard libraries
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

# Project libraries
from bash_purepython.shell.models import DEFAULT_TERMINAL_COLUMNS, EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, HostCommand

if TYPE_CHECKING:
    from bash_purepython.shell.session import ShellSession

CLEAR_SCREEN_SEQUENCE = "\x1b[2J\x1b[H"
SYSTEM_NAME = "ash7"
SYSTEM_NAME_ALL = "ash7 androsh7 1.0.0-wasm browser unknown unknown"
COLUMN_GAP = 2
PREVIOUS_DIRECTORY_ARGUMENT = "-"
HELP_NAME_WIDTH = 22
SHELL_HELP_TEXT = """\
shell:
  cd [path]              change directory (no arg = home, - = previous)
  export NAME=value      set an environment variable
  history                show command history
  which <name>...        report where a command comes from
  clear                  clear the screen
  help                   show this message

wildcards:        *  ?  [abc]   (quote them to keep them literal)
pipes and lists:  cmd | cmd    a && b    a || b    a ; b
redirection:      cmd > file   cmd >> file   cmd 2> file   cmd 2>&1   cmd &> file   cmd < file
here-documents:   cmd << EOF, then lines, then EOF on its own line (quote EOF to stop $VAR expanding)
"""


@dataclass(slots=True)
class BuiltinContext:
    """Carry the arguments, streams and session a builtin runs with"""

    argv: tuple[str, ...]
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    session: "ShellSession"


def format_columns(names: Sequence[str], width: int = DEFAULT_TERMINAL_COLUMNS) -> str:
    """Return the names laid out in equal-width columns that fit within width

    Args:
        names: The words to lay out
        width: The number of characters available per row

    Returns:
        The rows joined by newlines, empty if there are no names
    """
    if not names:
        return ""
    cell_width = max(len(name) for name in names) + COLUMN_GAP
    per_row = max(1, width // cell_width)
    rows = [
        "".join(name.ljust(cell_width) for name in names[row_start : row_start + per_row]).rstrip()
        for row_start in range(0, len(names), per_row)
    ]
    return "\n".join(rows)


def format_host_help(host_commands: Sequence[HostCommand]) -> str:
    """Return the help section describing the host's commands

    Args:
        host_commands: The commands the host runs, those without a summary omitted

    Returns:
        A section headed browser, or nothing when no host command has a summary
    """
    lines = [f"  {command.name:<{HELP_NAME_WIDTH}} {command.summary}" for command in host_commands if command.summary]
    if not lines:
        return ""
    return "browser:\n" + "\n".join(lines) + "\n\n"


def change_directory(context: BuiltinContext) -> int:
    """Change the working directory and record PWD and OLDPWD

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero on success, one when the target is missing or not a directory
    """
    if len(context.argv) > 2:
        context.stderr.write("cd: too many arguments\n")
        return EXIT_CODE_FAILURE
    argument = context.argv[1] if len(context.argv) > 1 else context.session.home
    target = argument
    if argument == PREVIOUS_DIRECTORY_ARGUMENT:
        if "OLDPWD" not in os.environ:
            context.stderr.write("cd: OLDPWD not set\n")
            return EXIT_CODE_FAILURE
        target = os.environ["OLDPWD"]
    previous = str(Path.cwd())
    try:
        os.chdir(target)
    except FileNotFoundError:
        context.stderr.write(f"cd: no such file or directory: {argument}\n")
        return EXIT_CODE_FAILURE
    except NotADirectoryError:
        context.stderr.write(f"cd: not a directory: {argument}\n")
        return EXIT_CODE_FAILURE
    except OSError as error:
        context.stderr.write(f"cd: {argument}: {error.strerror}\n")
        return EXIT_CODE_FAILURE
    os.environ["OLDPWD"] = previous
    os.environ["PWD"] = str(Path.cwd())
    return EXIT_CODE_SUCCESS


def export_variables(context: BuiltinContext) -> int:
    """Set environment variables from NAME=value arguments

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero when every argument was valid, one otherwise
    """
    if len(context.argv) < 2:
        context.stderr.write("export: usage: export NAME=value\n")
        return EXIT_CODE_FAILURE
    exit_code = EXIT_CODE_SUCCESS
    for argument in context.argv[1:]:
        name, separator, value = argument.partition("=")
        if not separator or not name.isidentifier():
            context.stderr.write(f"export: invalid: {argument}\n")
            exit_code = EXIT_CODE_FAILURE
            continue
        os.environ[name] = value
        context.session.register_exported(name)
    return exit_code


def print_history(context: BuiltinContext) -> int:
    """Print every remembered line with its number

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero
    """
    entries = context.session.history
    width = len(str(len(entries)))
    for number, entry in enumerate(entries, start=1):
        context.stdout.write(f"{number:>{width}}  {entry}\n")
    return EXIT_CODE_SUCCESS


def locate_commands(context: BuiltinContext) -> int:
    """Report where each named command comes from

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero when every name is known, one otherwise
    """
    if len(context.argv) < 2:
        context.stderr.write("which: usage: which <name>...\n")
        return EXIT_CODE_FAILURE
    exit_code = EXIT_CODE_SUCCESS
    for name in context.argv[1:]:
        kind = context.session.command_kind(name)
        if kind is None:
            context.stderr.write(f"which: no {name} in the shell\n")
            exit_code = EXIT_CODE_FAILURE
            continue
        context.stdout.write(f"{name}: {kind}\n")
    return exit_code


def print_help(context: BuiltinContext) -> int:
    """Print every command name and a summary of the shell's features

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero
    """
    session = context.session
    context.stdout.write("androsh7 virtual terminal\n\ncommands:\n")
    context.stdout.write(format_columns(session.all_command_names(), session.columns) + "\n\n")
    context.stdout.write(
        SHELL_HELP_TEXT.replace("pipes and lists:", format_host_help(session.host_commands) + "pipes and lists:")
    )
    return EXIT_CODE_SUCCESS


def print_system_name(context: BuiltinContext) -> int:
    """Print the system name, or everything with -a

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero
    """
    context.stdout.write((SYSTEM_NAME_ALL if "-a" in context.argv[1:] else SYSTEM_NAME) + "\n")
    return EXIT_CODE_SUCCESS


def clear_screen(context: BuiltinContext) -> int:
    """Write the escape sequence that clears the terminal

    Args:
        context: The arguments, streams and session of this invocation

    Returns:
        Zero
    """
    context.stdout.write(CLEAR_SCREEN_SEQUENCE)
    return EXIT_CODE_SUCCESS


BUILTINS: dict[str, Callable[[BuiltinContext], int]] = {
    "cd": change_directory,
    "export": export_variables,
    "history": print_history,
    "which": locate_commands,
    "help": print_help,
    "uname": print_system_name,
    "clear": clear_screen,
}
