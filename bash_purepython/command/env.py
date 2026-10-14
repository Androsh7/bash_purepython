"""Implement the env command"""

# Standard libraries
from dataclasses import dataclass, field

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_COMMAND_NOT_FOUND, EXIT_CODE_SUCCESS, ShellState

ASSIGNMENT_SEPARATOR = "="
OPTIONS_END = "--"
IGNORE_ENVIRONMENT_OPTIONS = frozenset({"-i", "--ignore-environment", "-"})
UNSET_OPTIONS = frozenset({"-u", "--unset"})
UNSET_LONG_PREFIX = "--unset="
UNSET_SHORT_PREFIX = "-u"


@dataclass
class EnvCommandLine:
    """Hold an ``env`` call that runs a command: the environment changes, then the command and its arguments"""

    command: list[str]
    ignore_environment: bool = False
    unset_names: list[str] = field(default_factory=list)
    assignments: list[tuple[str, str]] = field(default_factory=list)

    def apply(self, state: ShellState) -> None:
        """Change a state's variables and exports to the environment the command should see

        Args:
            state: The private copy of the shell state the command runs against
        """
        if self.ignore_environment:
            state.exported_names.clear()
        for name in self.unset_names:
            state.variables.pop(name, None)
            state.exported_names.discard(name)
        for name, value in self.assignments:
            state.arrays.pop(name, None)
            state.variables[name] = value
            state.exported_names.add(name)


def parse_env_command_line(arguments: list[str]) -> EnvCommandLine | None:
    """Return the parts of an ``env`` call that names a command to run, or None when it only prints

    Args:
        arguments: The arguments after ``env``

    Returns:
        The environment changes and the command, or None when no command follows the options and assignments
    """
    command_line = EnvCommandLine(command=[])
    index = 0
    options_ended = False
    while index < len(arguments):
        argument = arguments[index]
        if not options_ended and argument == OPTIONS_END:
            options_ended = True
        elif not options_ended and argument in IGNORE_ENVIRONMENT_OPTIONS:
            command_line.ignore_environment = True
        elif not options_ended and argument in UNSET_OPTIONS and index + 1 < len(arguments):
            command_line.unset_names.append(arguments[index + 1])
            index += 1
        elif not options_ended and argument.startswith(UNSET_LONG_PREFIX):
            command_line.unset_names.append(argument[len(UNSET_LONG_PREFIX) :])
        elif not options_ended and argument.startswith(UNSET_SHORT_PREFIX) and len(argument) > len(UNSET_SHORT_PREFIX):
            command_line.unset_names.append(argument[len(UNSET_SHORT_PREFIX) :])
        elif not options_ended and argument.startswith("-"):
            return None
        elif ASSIGNMENT_SEPARATOR in argument:
            name, value = argument.split(ASSIGNMENT_SEPARATOR, 1)
            command_line.assignments.append((name, value))
        else:
            command_line.command = arguments[index:]
            return command_line
        index += 1
    return None


class EnvCommand(Command):
    """Print the exported variables"""

    name = "env"
    summary = "print the environment"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print every exported variable as name=value, after applying any assignments given

        Args:
            invocation: The call to perform

        Returns:
            One entry per line, or NUL-separated with -0
        """
        parser = CommandArgumentParser("env", "Print the environment")
        parser.add_argument("-0", "--null", dest="null", action="store_true", help="end entries with NUL")
        parser.add_argument("-i", "--ignore-environment", action="store_true", help="start with an empty environment")
        parser.add_argument(
            "-u", "--unset", action="append", default=[], metavar="NAME", help="remove variable from the environment"
        )
        parser.add_argument("assignments", nargs="*", metavar="NAME=VALUE", help="variables to set first")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        variables = {} if parsed.ignore_environment else invocation.state.exported_variables()
        for name in parsed.unset:
            variables.pop(name, None)
        for assignment in parsed.assignments:
            if ASSIGNMENT_SEPARATOR not in assignment:
                invocation.state.write_error(f"env: '{assignment}': No such file or directory\n")
                return CommandResult(stdout="", exit_code=EXIT_CODE_COMMAND_NOT_FOUND)
            name, value = assignment.split(ASSIGNMENT_SEPARATOR, 1)
            variables[name] = value
        separator = "\0" if parsed.null else "\n"
        entries = [f"{name}={value}{separator}" for name, value in variables.items()]
        return CommandResult(stdout="".join(entries), exit_code=EXIT_CODE_SUCCESS)
