"""Implement the true command"""

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS


class TrueCommand(Command):
    """Succeed without output"""

    name = "true"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return success

        Args:
            invocation: Ignored

        Returns:
            Empty output and exit code zero
        """
        return CommandResult(stdout="", exit_code=EXIT_CODE_SUCCESS)
