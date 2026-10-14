"""Implement the mktemp command"""

# Standard libraries
import secrets
import string
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

DEFAULT_TEMPORARY_DIRECTORY = "/tmp"
TEMPORARY_DIRECTORY_VARIABLE_NAME = "TMPDIR"
DEFAULT_TEMPLATE = "tmp.XXXXXXXXXX"
PLACEHOLDER = "X"
MINIMUM_PLACEHOLDER_COUNT = 3
RANDOM_ALPHABET = string.ascii_letters + string.digits
MAXIMUM_ATTEMPTS = 100
PATH_SEPARATOR = "/"


def placeholder_count(template: str) -> int:
    """Return how many X's end the template

    Args:
        template: The file name template

    Returns:
        The count of trailing X's
    """
    return len(template) - len(template.rstrip(PLACEHOLDER))


def fill_template(template: str) -> str:
    """Return the template with its trailing X's replaced by random characters

    Args:
        template: The file name template

    Returns:
        A fresh name
    """
    count = placeholder_count(template)
    suffix = "".join(secrets.choice(RANDOM_ALPHABET) for _ in range(count))
    return template[: len(template) - count] + suffix


class MktempCommand(Command):
    """Create a temporary file or directory with a unique name and print it"""

    name = "mktemp"
    summary = "create a temporary file or directory"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Create the file or directory and print its path

        Args:
            invocation: The call to perform

        Returns:
            The path on one line, and the exit code
        """
        parser = CommandArgumentParser(self.name, "Create a temporary file or directory")
        parser.add_argument("-d", "--directory", action="store_true", help="create a directory instead of a file")
        parser.add_argument("-p", "--tmpdir", default=None, help="create under this directory")
        parser.add_argument("-u", "--dry-run", action="store_true", help="print a name without creating anything")
        parser.add_argument("-q", "--quiet", action="store_true", help="report no errors")
        parser.add_argument("template", nargs="?", default=None, help="the name, ending in at least three X's")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        template = parsed.template or DEFAULT_TEMPLATE
        if placeholder_count(template) < MINIMUM_PLACEHOLDER_COUNT:
            if not parsed.quiet:
                state.write_error(f"mktemp: too few X's in template '{template}'\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        directory_text = self.directory_text(parsed, template, state.variables)
        if directory_text is not None:
            directory = state.resolve_path(directory_text)
            directory.mkdir(parents=True, exist_ok=True)
        for _ in range(MAXIMUM_ATTEMPTS):
            name = fill_template(template)
            shown = name if directory_text is None else f"{directory_text.rstrip(PATH_SEPARATOR)}{PATH_SEPARATOR}{name}"
            path = state.resolve_path(shown)
            if parsed.dry_run or self.create(path, parsed.directory):
                return CommandResult(stdout=shown + "\n", exit_code=EXIT_CODE_SUCCESS)
        if not parsed.quiet:
            state.write_error(f"mktemp: failed to create {'directory' if parsed.directory else 'file'} via template\n")
        return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)

    def directory_text(self, parsed: object, template: str, variables: dict[str, str]) -> str | None:
        """Return the directory the name goes under, or None when the template is already a path

        Args:
            parsed: The parsed options
            template: The file name template
            variables: The shell variables, for TMPDIR

        Returns:
            The directory as the user would write it, or None
        """
        if parsed.tmpdir is not None:
            return parsed.tmpdir
        if PATH_SEPARATOR in template:
            return None
        return variables.get(TEMPORARY_DIRECTORY_VARIABLE_NAME) or DEFAULT_TEMPORARY_DIRECTORY

    def create(self, path: Path, as_directory: bool) -> bool:
        """Create the path if nothing is there yet

        Args:
            path: Where to create
            as_directory: Whether to create a directory rather than an empty file

        Returns:
            True when created, False when the name was taken
        """
        try:
            if as_directory:
                path.mkdir()
            else:
                path.touch(exist_ok=False)
        except FileExistsError:
            return False
        return True
