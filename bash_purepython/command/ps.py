"""Implement a ps command that lists the session's background jobs"""

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

HEADER_LINE = "  PID STAT CMD\n"
PID_WIDTH = 5
STATUS_WIDTH = 4


class PsCommand(Command):
    """List background jobs the way ps lists processes

    The output is a contract: a header line ``  PID STAT CMD`` then one line per job with the pid right-aligned in
    five columns, the status letter (R running, D done, K killed) left-aligned in four, and the command text
    """

    name = "ps"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return the job table as text

        Args:
            invocation: The call, whose options are accepted and ignored

        Returns:
            The listing and exit code zero
        """
        lines = [HEADER_LINE]
        for job in invocation.state.job_table.jobs.values():
            lines.append(f"{job.pid:>{PID_WIDTH}} {job.status.value:<{STATUS_WIDTH}} {job.command_text}\n")
        return CommandResult(stdout="".join(lines), exit_code=EXIT_CODE_SUCCESS)
