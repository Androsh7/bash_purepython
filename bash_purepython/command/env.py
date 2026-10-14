"""Implement the env command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_COMMAND_NOT_FOUND, EXIT_CODE_SUCCESS

ASSIGNMENT_SEPARATOR = "="


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
