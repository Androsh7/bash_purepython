"""Implement the cp command"""

# Standard libraries
import shutil
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState


def copy_path(source: Path, target: Path, recursive: bool) -> str | None:
    """Copy one file or directory

    Args:
        source: The existing path
        target: Where the copy goes
        recursive: Whether directories may be copied

    Returns:
        An error message, or None on success
    """
    if source.is_dir():
        if not recursive:
            return "-r not specified; omitting directory"
        shutil.copytree(source, target, dirs_exist_ok=True)
        return None
    shutil.copy2(source, target)
    return None


class CpCommand(Command):
    """Copy files and directories"""

    name = "cp"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Copy each source to the destination

        Args:
            invocation: The call to perform

        Returns:
            Verbose output when asked, and exit code one if any copy failed
        """
        parser = CommandArgumentParser("cp", "Copy files and directories")
        parser.add_argument("-r", "-R", "--recursive", action="store_true", help="copy directories recursively")
        parser.add_argument("-f", "--force", action="store_true", help="overwrite existing destinations")
        parser.add_argument("-n", "--no-clobber", action="store_true", help="do not overwrite existing files")
        parser.add_argument("-v", "--verbose", action="store_true", help="print each copied path")
        parser.add_argument("sources", nargs="+", help="source paths")
        parser.add_argument("destination", help="destination path")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        destination = state.resolve_path(parsed.destination)
        if len(parsed.sources) > 1 and not destination.is_dir():
            state.write_error(f"cp: target '{parsed.destination}' is not a directory\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        exit_code = EXIT_CODE_SUCCESS
        lines: list[str] = []
        for source_text in parsed.sources:
            message = self.copy_one(source_text, destination, parsed, state, lines)
            if message is not None:
                state.write_error(f"cp: {message}\n")
                exit_code = EXIT_CODE_FAILURE
        return CommandResult(stdout="".join(lines), exit_code=exit_code)

    def copy_one(
        self, source_text: str, destination: Path, parsed: object, state: ShellState, lines: list[str]
    ) -> str | None:
        """Copy one source, appending a verbose line on success

        Args:
            source_text: The source as written
            destination: The resolved destination, a directory or a target file
            parsed: The parsed options
            state: The shell state for paths
            lines: Where verbose lines are appended

        Returns:
            An error message, or None on success or when -n skipped the copy
        """
        source = state.resolve_path(source_text)
        if not source.exists():
            return f"cannot stat '{source_text}': No such file or directory"
        target = destination / source.name if destination.is_dir() else destination
        if target.exists() and parsed.no_clobber:
            return None
        if target.exists() and target.is_file() and source.is_file() and not parsed.force:
            target.unlink()
        message = copy_path(source, target, parsed.recursive)
        if message is not None:
            return f"{message} '{source_text}'"
        if parsed.verbose:
            lines.append(f"'{source_text}' -> '{parsed.destination}'\n")
        return None
