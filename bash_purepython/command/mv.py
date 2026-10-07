"""Implement the mv command"""

# Standard libraries
import shutil

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS


class MvCommand(Command):
    """Move or rename files and directories"""

    name = "mv"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Move each source to the destination

        Args:
            invocation: The call to perform

        Returns:
            Verbose output when asked, and exit code one if any move failed
        """
        parser = CommandArgumentParser("mv", "Move or rename files and directories")
        parser.add_argument("-f", "--force", action="store_true", help="overwrite existing destinations")
        parser.add_argument("-n", "--no-clobber", action="store_true", help="do not overwrite existing files")
        parser.add_argument("-v", "--verbose", action="store_true", help="print each moved path")
        parser.add_argument("sources", nargs="+", help="source paths")
        parser.add_argument("destination", help="destination path")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        destination = state.resolve_path(parsed.destination)
        if len(parsed.sources) > 1 and not destination.is_dir():
            state.write_error(f"mv: target '{parsed.destination}' is not a directory\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        exit_code = EXIT_CODE_SUCCESS
        lines: list[str] = []
        for source_text in parsed.sources:
            source = state.resolve_path(source_text)
            if not source.exists():
                state.write_error(f"mv: cannot stat '{source_text}': No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            target = destination / source.name if destination.is_dir() else destination
            if target.exists():
                if parsed.no_clobber:
                    continue
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(source), str(target))
            if parsed.verbose:
                lines.append(f"renamed '{source_text}' -> '{parsed.destination}'\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)
