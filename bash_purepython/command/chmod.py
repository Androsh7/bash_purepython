"""Implement the chmod command"""

# Standard libraries
import re
import stat
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState

OCTAL_MODE_PATTERN = re.compile(r"^[0-7]{1,4}$")
CLAUSE_PATTERN = re.compile(r"^([ugoa]*)((?:[+\-=](?:[rwxXst]*|[ugo]))+)$")
OPERATION_PATTERN = re.compile(r"([+\-=])([ugo]|[rwxXst]*)")
COPYABLE_PERMISSION_LETTERS = "rwx"
CLAUSE_SEPARATOR = ","
DEFAULT_UMASK = 0o022
ALL_PERMISSION_BITS = 0o777
OCTAL_BASE = 8
WHO_BITS = {
    "u": stat.S_IRWXU | stat.S_ISUID,
    "g": stat.S_IRWXG | stat.S_ISGID,
    "o": stat.S_IRWXO | stat.S_ISVTX,
}
PERMISSION_BITS = {
    "r": stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH,
    "w": stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH,
    "x": stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
    "s": stat.S_ISUID | stat.S_ISGID,
    "t": stat.S_ISVTX,
}
ANY_EXECUTE_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH


def who_mask(who: str) -> int:
    """Return the mode bits a who-list selects, every class when it is empty

    Args:
        who: Letters from ``ugoa``

    Returns:
        The selected bits
    """
    if not who or "a" in who:
        return WHO_BITS["u"] | WHO_BITS["g"] | WHO_BITS["o"]
    mask = 0
    for letter in who:
        mask |= WHO_BITS[letter]
    return mask


def permission_mask(permissions: str, current_mode: int, is_directory: bool) -> int:
    """Return the bits a permission list selects across every class

    Args:
        permissions: Letters from ``rwxXst``
        current_mode: The mode before the change, which decides what ``X`` means
        is_directory: Whether the file is a directory, which also decides what ``X`` means

    Returns:
        The selected bits
    """
    mask = 0
    for letter in permissions:
        if letter == "X":
            if is_directory or current_mode & ANY_EXECUTE_BITS:
                mask |= PERMISSION_BITS["x"]
        else:
            mask |= PERMISSION_BITS[letter]
    return mask


def copied_permission_mask(source_class: str, current_mode: int) -> int:
    """Return the bits across every class matching the permissions one class currently has

    Args:
        source_class: ``u``, ``g`` or ``o``, the class whose permissions are copied
        current_mode: The mode before the change

    Returns:
        The selected bits
    """
    class_bits = current_mode & WHO_BITS[source_class] & ALL_PERMISSION_BITS
    mask = 0
    for letter in COPYABLE_PERMISSION_LETTERS:
        if class_bits & PERMISSION_BITS[letter]:
            mask |= PERMISSION_BITS[letter]
    return mask


def apply_mode(mode_text: str, current_mode: int, is_directory: bool) -> int | None:
    """Return the permission bits a mode argument produces from the current ones

    Args:
        mode_text: An octal number or comma-separated symbolic clauses
        current_mode: The permission bits before the change
        is_directory: Whether the file is a directory

    Returns:
        The new permission bits, or None when the mode is not valid
    """
    if OCTAL_MODE_PATTERN.match(mode_text):
        return int(mode_text, OCTAL_BASE)
    mode = current_mode
    for clause in mode_text.split(CLAUSE_SEPARATOR):
        match = CLAUSE_PATTERN.match(clause)
        if match is None:
            return None
        who, operations = match.groups()
        selected = who_mask(who)
        if not who:
            selected &= ~DEFAULT_UMASK
        for operation, permissions in OPERATION_PATTERN.findall(operations):
            if permissions in WHO_BITS:
                bits = copied_permission_mask(permissions, mode) & selected
            else:
                bits = permission_mask(permissions, mode, is_directory) & selected
            if operation == "+":
                mode |= bits
            elif operation == "-":
                mode &= ~bits
            else:
                mode = (mode & ~who_mask(who)) | bits
    return mode


class ChmodCommand(Command):
    """Change the permission bits of files"""

    name = "chmod"
    summary = "change file permissions"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Apply the mode to each path, and under -R to everything below each directory

        Args:
            invocation: The call to perform

        Returns:
            Nothing, and exit code one if any path was missing or the mode invalid
        """
        parser = CommandArgumentParser(self.name, "Change file permissions")
        parser.add_argument("-R", "--recursive", action="store_true", help="change directories and their contents")
        parser.add_argument("-v", "--verbose", action="store_true", help="report each file changed")
        parser.add_argument("mode", help="an octal mode or symbolic clauses such as u+x,go-w")
        parser.add_argument("paths", nargs="+", help="files to change")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        if apply_mode(parsed.mode, 0, False) is None:
            state.write_error(f"chmod: invalid mode: '{parsed.mode}'\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        exit_code = EXIT_CODE_SUCCESS
        lines: list[str] = []
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            if not path.exists():
                state.write_error(f"chmod: cannot access '{path_text}': No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            targets = [path, *sorted(path.rglob("*"))] if parsed.recursive and path.is_dir() else [path]
            for target in targets:
                shown = path_text if target == path else (Path(path_text) / target.relative_to(path)).as_posix()
                exit_code = max(exit_code, self.change(target, shown, parsed.mode, parsed.verbose, lines, state))
        return CommandResult(stdout="".join(lines), exit_code=exit_code)

    def change(self, path: Path, shown: str, mode_text: str, verbose: bool, lines: list[str], state: ShellState) -> int:
        """Change one file's permission bits

        Args:
            path: The file
            shown: The name to report
            mode_text: The mode argument
            verbose: Whether to append a report line
            lines: Where report lines go
            state: The shell state for errors

        Returns:
            Zero on success, one on failure
        """
        try:
            current_mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            state.write_error(f"chmod: cannot operate on dangling symlink '{shown}'\n")
            return EXIT_CODE_FAILURE
        new_mode = apply_mode(mode_text, current_mode, path.is_dir())
        if new_mode is None:
            return EXIT_CODE_FAILURE
        try:
            path.chmod(new_mode)
        except OSError as error:
            state.write_error(f"chmod: changing permissions of '{shown}': {error.strerror}\n")
            return EXIT_CODE_FAILURE
        if verbose:
            lines.append(
                f"mode of '{shown}' changed from {current_mode:04o} ({stat.filemode(current_mode)[1:]}) "
                f"to {new_mode:04o} ({stat.filemode(new_mode)[1:]})\n"
            )
        return EXIT_CODE_SUCCESS
