"""Parse command arguments without letting argparse exit the process"""

# Standard libraries
from argparse import ArgumentParser, Namespace
from typing import NoReturn

# Project libraries
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR, ShellState


class ArgumentParsingStopped(Exception):  # noqa: N818
    """Signal that argparse wanted to stop, carrying the exit code it would have used"""

    def __init__(self, exit_code: int):
        """Record the exit code

        Args:
            exit_code: The code the command should exit with
        """
        super().__init__(exit_code)
        self.exit_code = exit_code


class CommandArgumentParser(ArgumentParser):
    """Collect argparse messages and raise instead of exiting, with --help as the only help flag so -h stays free"""

    def __init__(self, program_name: str, description: str):
        """Create a parser for one command

        Args:
            program_name: The command name shown in usage and errors
            description: One line describing the command
        """
        super().__init__(prog=program_name, description=description, add_help=False)
        self.add_argument("--help", action="help", help="show this help message and exit")
        self.messages: list[str] = []

    def _print_message(self, message: str, file: object = None) -> None:
        """Collect a message argparse would have printed

        Args:
            message: The text argparse produced
            file: Ignored
        """
        if message:
            self.messages.append(message)

    def exit(self, status: int = EXIT_CODE_SUCCESS, message: str | None = None) -> NoReturn:
        """Raise instead of exiting the process

        Args:
            status: The exit code argparse chose
            message: An optional final message

        Raises:
            ArgumentParsingStopped: Always
        """
        if message:
            self.messages.append(message)
        raise ArgumentParsingStopped(status)

    def error(self, message: str) -> NoReturn:
        """Raise a usage error instead of exiting the process

        Args:
            message: The problem argparse found

        Raises:
            ArgumentParsingStopped: Always, with the usage exit code
        """
        self.messages.append(f"{self.prog}: {message}\n")
        raise ArgumentParsingStopped(EXIT_CODE_USAGE_ERROR)


def parse_command_arguments(parser: CommandArgumentParser, arguments: list[str], state: ShellState) -> Namespace | int:
    """Return the parsed arguments, or the exit code when parsing stopped the command

    Help text goes to standard output and errors to standard error through the state's sinks

    Args:
        parser: The command's parser
        arguments: The arguments after the command name
        state: The shell state whose sinks receive messages

    Returns:
        The namespace on success, otherwise the exit code to return
    """
    try:
        namespace = parser.parse_args(arguments)
    except ArgumentParsingStopped as stopped:
        sink = state.output_sink.write_sync if stopped.exit_code == EXIT_CODE_SUCCESS else state.write_error
        for message in parser.messages:
            sink(message)
        return stopped.exit_code
    return namespace
