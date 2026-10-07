"""Implement the rm command"""

# Standard libraries
import shutil

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS


class RmCommand(Command):
    """Remove files and directories"""

    name = "rm"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Remove each path, reporting the ones that cannot be removed

        Args:
            invocation: The call to perform

        Returns:
            Verbose output when asked, and exit code one if any path failed
        """
        parser = CommandArgumentParser("rm", "Remove files and directories")
        parser.add_argument(
            "-r", "-R", "--recursive", action="store_true", help="remove directories and their contents"
        )
        parser.add_argument("-f", "--force", action="store_true", help="ignore missing files")
        parser.add_argument("-d", "--dir", action="store_true", help="remove empty directories")
        parser.add_argument("-v", "--verbose", action="store_true", help="print each removed path")
        parser.add_argument("paths", nargs="+", help="paths to remove")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        exit_code = EXIT_CODE_SUCCESS
        lines: list[str] = []
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            if not path.exists() and not path.is_symlink():
                if not parsed.force:
                    state.write_error(f"rm: cannot remove '{path_text}': No such file or directory\n")
                    exit_code = EXIT_CODE_FAILURE
                continue
            if path.is_dir() and not path.is_symlink():
                if parsed.recursive:
                    try:
                        shutil.rmtree(path)
                    except OSError as error:
                        state.write_error(f"rm: cannot remove '{path_text}': {error.strerror}\n")
                        exit_code = EXIT_CODE_FAILURE
                        continue
                elif parsed.dir:
                    try:
                        path.rmdir()
                    except OSError:
                        state.write_error(f"rm: cannot remove '{path_text}': Directory not empty\n")
                        exit_code = EXIT_CODE_FAILURE
                        continue
                else:
                    state.write_error(f"rm: cannot remove '{path_text}': Is a directory\n")
                    exit_code = EXIT_CODE_FAILURE
                    continue
            else:
                try:
                    path.unlink()
                except OSError as error:
                    state.write_error(f"rm: cannot remove '{path_text}': {error.strerror}\n")
                    exit_code = EXIT_CODE_FAILURE
                    continue
            if parsed.verbose:
                lines.append(f"removed '{path_text}'\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)
