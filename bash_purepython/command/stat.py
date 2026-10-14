"""Implement the stat command"""

# Standard libraries
import math
import os
import re
import stat
import time

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

OWNER_NAME = "user"
OWNER_ID = 1000
LINK_COUNT = 1
BLOCK_SIZE_BYTES = 512
IO_BLOCK_SIZE_BYTES = 4096
DEVICE_ID = 2049
DEVICE_HEX = "801h"
NANOSECONDS_PER_SECOND = 1_000_000_000
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIMEZONE_FORMAT = "%z"
DIRECTIVE_PATTERN = re.compile(r"%(.)")
ESCAPES = {"\\n": "\n", "\\t": "\t", "\\\\": "\\"}
ESCAPE_PATTERN = re.compile(r"\\[nt\\]")
MISSING_BIRTH_TIME = "-"


def file_type_name(status: os.stat_result) -> str:
    """Return the kind of file as stat names it

    Args:
        status: The file's status

    Returns:
        ``regular file``, ``regular empty file``, ``directory``, ``symbolic link`` or ``special file``
    """
    mode = status.st_mode
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symbolic link"
    if stat.S_ISREG(mode):
        return "regular empty file" if status.st_size == 0 else "regular file"
    return "special file"


def format_timestamp(seconds: float, nanoseconds: int) -> str:
    """Return a time as stat prints it, with nanoseconds and the zone offset

    Args:
        seconds: The time in seconds since the epoch
        nanoseconds: The same time in nanoseconds since the epoch

    Returns:
        The local date and time
    """
    moment = time.localtime(seconds)
    fraction = nanoseconds % NANOSECONDS_PER_SECOND
    return f"{time.strftime(TIME_FORMAT, moment)}.{fraction:09d} {time.strftime(TIMEZONE_FORMAT, moment)}"


def allocated_blocks(status: os.stat_result) -> int:
    """Return the 512-byte blocks a file takes, estimated from its size where the platform does not say

    Args:
        status: The file's status

    Returns:
        The block count
    """
    stat_blocks = getattr(status, "st_blocks", None)
    if stat_blocks is not None:
        return stat_blocks
    return math.ceil(status.st_size / IO_BLOCK_SIZE_BYTES) * (IO_BLOCK_SIZE_BYTES // BLOCK_SIZE_BYTES)


def directive_value(directive: str, name: str, status: os.stat_result) -> str:
    """Return what one ``%`` directive of a stat format stands for

    Args:
        directive: The character after the percent sign
        name: The file name as written
        status: The file's status

    Returns:
        The value, or the directive itself when it is not one stat knows
    """
    values = {
        "n": name,
        "s": str(status.st_size),
        "b": str(allocated_blocks(status)),
        "B": str(BLOCK_SIZE_BYTES),
        "o": str(IO_BLOCK_SIZE_BYTES),
        "F": file_type_name(status),
        "a": f"{stat.S_IMODE(status.st_mode):o}",
        "A": stat.filemode(status.st_mode),
        "f": f"{status.st_mode:x}",
        "d": str(DEVICE_ID),
        "D": DEVICE_HEX.rstrip("h"),
        "i": str(status.st_ino),
        "h": str(LINK_COUNT),
        "u": str(OWNER_ID),
        "U": OWNER_NAME,
        "g": str(OWNER_ID),
        "G": OWNER_NAME,
        "x": format_timestamp(status.st_atime, status.st_atime_ns),
        "X": str(int(status.st_atime)),
        "y": format_timestamp(status.st_mtime, status.st_mtime_ns),
        "Y": str(int(status.st_mtime)),
        "z": format_timestamp(status.st_ctime, status.st_ctime_ns),
        "Z": str(int(status.st_ctime)),
        "w": MISSING_BIRTH_TIME,
        "W": "0",
        "%": "%",
    }
    return values.get(directive, f"%{directive}")


def apply_format(format_text: str, name: str, status: os.stat_result) -> str:
    """Return a -c format filled in for one file

    Args:
        format_text: The format with ``%`` directives and backslash escapes
        name: The file name as written
        status: The file's status

    Returns:
        The text, with a newline added
    """
    expanded = DIRECTIVE_PATTERN.sub(lambda match: directive_value(match.group(1), name, status), format_text)
    return ESCAPE_PATTERN.sub(lambda match: ESCAPES[match.group(0)], expanded) + "\n"


def default_block(name: str, status: os.stat_result) -> str:
    """Return the multi-line description stat prints without -c

    Args:
        name: The file name as written
        status: The file's status

    Returns:
        The block of lines
    """
    permissions = f"({stat.S_IMODE(status.st_mode):04o}/{stat.filemode(status.st_mode)})"
    owner = f"({OWNER_ID:>5}/{OWNER_NAME:>8})"
    return (
        f"  File: {name}\n"
        f"  Size: {status.st_size:<10}\tBlocks: {allocated_blocks(status):<10} IO Block: {IO_BLOCK_SIZE_BYTES:<6} "
        f"{file_type_name(status)}\n"
        f"Device: {DEVICE_HEX}/{DEVICE_ID}d\tInode: {status.st_ino:<11} Links: {LINK_COUNT}\n"
        f"Access: {permissions}  Uid: {owner}   Gid: {owner}\n"
        f"Access: {format_timestamp(status.st_atime, status.st_atime_ns)}\n"
        f"Modify: {format_timestamp(status.st_mtime, status.st_mtime_ns)}\n"
        f"Change: {format_timestamp(status.st_ctime, status.st_ctime_ns)}\n"
        f" Birth: {MISSING_BIRTH_TIME}\n"
    )


class StatCommand(Command):
    """Print the status of files"""

    name = "stat"
    summary = "print file status"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Describe each file, in the default block or a -c format

        Args:
            invocation: The call to perform

        Returns:
            The descriptions, and exit code one if any file was missing
        """
        parser = CommandArgumentParser(self.name, "Print file status")
        parser.add_argument("-c", "--format", default=None, help="print this format instead of the default")
        parser.add_argument("-L", "--dereference", action="store_true", help="follow links")
        parser.add_argument("paths", nargs="+", help="files to describe")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        pieces: list[str] = []
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            try:
                status = path.stat() if parsed.dereference else path.lstat()
            except FileNotFoundError:
                state.write_error(f"stat: cannot stat '{path_text}': No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            if parsed.format is None:
                pieces.append(default_block(path_text, status))
            else:
                pieces.append(apply_format(parsed.format, path_text, status))
        return CommandResult(stdout="".join(pieces), exit_code=exit_code)
