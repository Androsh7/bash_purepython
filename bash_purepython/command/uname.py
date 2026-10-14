"""Implement the uname command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

KERNEL_NAME = "Linux"
DEFAULT_HOSTNAME = "androsh7"
HOSTNAME_VARIABLE_NAME = "HOSTNAME"
KERNEL_RELEASE = "6.1.0"
KERNEL_VERSION = "#1 SMP"
MACHINE = "wasm32"
OPERATING_SYSTEM = "GNU/Linux"


class UnameCommand(Command):
    """Print the fixed system information of the in-browser machine"""

    name = "uname"
    summary = "print system information"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the selected fields in uname's fixed order, the kernel name when none is selected

        Args:
            invocation: The call to perform

        Returns:
            One line of space-separated fields
        """
        parser = CommandArgumentParser(self.name, "Print system information")
        parser.add_argument("-a", "--all", action="store_true", help="print every field")
        parser.add_argument("-s", "--kernel-name", action="store_true", help="print the kernel name")
        parser.add_argument("-n", "--nodename", action="store_true", help="print the host name")
        parser.add_argument("-r", "--kernel-release", action="store_true", help="print the kernel release")
        parser.add_argument("-v", "--kernel-version", action="store_true", help="print the kernel version")
        parser.add_argument("-m", "--machine", action="store_true", help="print the machine hardware name")
        parser.add_argument("-p", "--processor", action="store_true", help="print the processor type")
        parser.add_argument("-i", "--hardware-platform", action="store_true", help="print the hardware platform")
        parser.add_argument("-o", "--operating-system", action="store_true", help="print the operating system")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        hostname = invocation.state.variables.get(HOSTNAME_VARIABLE_NAME) or DEFAULT_HOSTNAME
        selections = [
            (parsed.kernel_name, KERNEL_NAME),
            (parsed.nodename, hostname),
            (parsed.kernel_release, KERNEL_RELEASE),
            (parsed.kernel_version, KERNEL_VERSION),
            (parsed.machine, MACHINE),
            (parsed.processor, MACHINE),
            (parsed.hardware_platform, MACHINE),
            (parsed.operating_system, OPERATING_SYSTEM),
        ]
        if parsed.all:
            fields = [KERNEL_NAME, hostname, KERNEL_RELEASE, KERNEL_VERSION, MACHINE, OPERATING_SYSTEM]
        else:
            fields = [value for selected, value in selections if selected] or [KERNEL_NAME]
        return CommandResult(stdout=" ".join(fields) + "\n", exit_code=EXIT_CODE_SUCCESS)
