"""Implement a kill command that cancels the session's background jobs"""

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR, JobStatus

SIGNAL_OPTION = "-s"


def split_signal_options(arguments: list[str]) -> list[str]:
    """Return the arguments with any signal option removed, since every signal cancels the job the same way

    Args:
        arguments: The arguments after the command name

    Returns:
        The pids as written
    """
    pids: list[str] = []
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument == SIGNAL_OPTION:
            skip_next = True
            continue
        if argument.startswith("-") and argument != "-":
            continue
        pids.append(argument)
    return pids


class KillCommand(Command):
    """Cancel background jobs by pid"""

    name = "kill"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Cancel every named job

        Args:
            invocation: The call to perform

        Returns:
            Empty output and zero, or one when any pid is unknown or already finished
        """
        pid_texts = split_signal_options(invocation.arguments)
        if not pid_texts:
            invocation.state.write_error("kill: usage: kill [-s sigspec | -signum] pid ...\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        exit_code = EXIT_CODE_SUCCESS
        for pid_text in pid_texts:
            job = invocation.state.job_table.jobs.get(int(pid_text)) if pid_text.isdigit() else None
            if job is None or job.status != JobStatus.RUNNING:
                invocation.state.write_error(f"kill: {pid_text}: no such process\n")
                exit_code = EXIT_CODE_FAILURE
                continue
            job.task.cancel()
        return CommandResult(stdout="", exit_code=exit_code)
