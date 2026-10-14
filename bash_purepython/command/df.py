"""Implement the df command, which reports one fixed in-memory filesystem"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.ls import format_size
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

FILESYSTEM_NAME = "/dev/root"
MOUNT_POINT = "/"
TOTAL_BLOCKS = 10_485_760
USED_BLOCKS = 1_048_576
BLOCK_SIZE_BYTES = 1024
PERCENT_SCALE = 100
FILESYSTEM_WIDTH = 14
BLOCKS_WIDTH = 10
USED_WIDTH = 8
AVAILABLE_WIDTH = 9
HUMAN_WIDTH = 5
PERCENT_WIDTH = 4


def format_table(human_readable: bool) -> str:
    """Return the header and the single filesystem line

    Args:
        human_readable: Whether sizes are printed in short form

    Returns:
        The two lines df prints
    """
    available = TOTAL_BLOCKS - USED_BLOCKS
    use_percent = -(-USED_BLOCKS * PERCENT_SCALE // (USED_BLOCKS + available))
    if human_readable:
        header = (
            f"{'Filesystem':<{FILESYSTEM_WIDTH}} {'Size':>{HUMAN_WIDTH}} {'Used':>{HUMAN_WIDTH}} "
            f"{'Avail':>{HUMAN_WIDTH}} {'Use%':>{PERCENT_WIDTH}} Mounted on\n"
        )
        line = (
            f"{FILESYSTEM_NAME:<{FILESYSTEM_WIDTH}} {format_size(TOTAL_BLOCKS * BLOCK_SIZE_BYTES):>{HUMAN_WIDTH}} "
            f"{format_size(USED_BLOCKS * BLOCK_SIZE_BYTES):>{HUMAN_WIDTH}} "
            f"{format_size(available * BLOCK_SIZE_BYTES):>{HUMAN_WIDTH}} {use_percent:>{PERCENT_WIDTH - 1}}% "
            f"{MOUNT_POINT}\n"
        )
        return header + line
    header = (
        f"{'Filesystem':<{FILESYSTEM_WIDTH}} {'1K-blocks':>{BLOCKS_WIDTH}} {'Used':>{USED_WIDTH}} "
        f"{'Available':>{AVAILABLE_WIDTH}} {'Use%':>{PERCENT_WIDTH}} Mounted on\n"
    )
    line = (
        f"{FILESYSTEM_NAME:<{FILESYSTEM_WIDTH}} {TOTAL_BLOCKS:>{BLOCKS_WIDTH}} {USED_BLOCKS:>{USED_WIDTH}} "
        f"{available:>{AVAILABLE_WIDTH}} {use_percent:>{PERCENT_WIDTH - 1}}% {MOUNT_POINT}\n"
    )
    return header + line


class DfCommand(Command):
    """Report the space on the one filesystem the shell has"""

    name = "df"
    summary = "report filesystem space"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the header and the root filesystem line

        Args:
            invocation: The call to perform

        Returns:
            The table and exit code zero
        """
        parser = CommandArgumentParser(self.name, "Report filesystem space")
        parser.add_argument("-h", "--human-readable", action="store_true", help="sizes like 1.5K")
        parser.add_argument("paths", nargs="*", help="paths whose filesystem to report, all on the one filesystem")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        return CommandResult(stdout=format_table(parsed.human_readable), exit_code=EXIT_CODE_SUCCESS)
