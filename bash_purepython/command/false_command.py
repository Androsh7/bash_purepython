"""Implement the false command"""

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE


class FalseCommand(Command):
    """Fail without output"""

    name = "false"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return failure

        Args:
            invocation: Ignored

        Returns:
            Empty output and exit code one
        """
        return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
