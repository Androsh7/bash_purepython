"""Implement the echo command"""

# Project libraries
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS

ESCAPE_SEQUENCES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    "e": "\x1b",
}
STOP_SEQUENCE = "c"


def interpret_escapes(text: str) -> tuple[str, bool]:
    """Return text with backslash escapes replaced, and whether a backslash-c sequence asked to stop output

    Args:
        text: The joined arguments

    Returns:
        The interpreted text and the stop flag
    """
    pieces: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character != "\\" or index + 1 >= len(text):
            pieces.append(character)
            index += 1
            continue
        escaped = text[index + 1]
        if escaped == STOP_SEQUENCE:
            return "".join(pieces), True
        pieces.append(ESCAPE_SEQUENCES.get(escaped, "\\" + escaped))
        index += 2
    return "".join(pieces), False


class EchoCommand(Command):
    """Write the arguments to standard output"""

    name = "echo"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Write the arguments separated by spaces, honouring -n, -e and -E

        Args:
            invocation: The call to perform

        Returns:
            The text and a success exit code
        """
        arguments = list(invocation.arguments)
        trailing_newline = True
        interpret = False
        while arguments and arguments[0].startswith("-") and len(arguments[0]) > 1:
            flags = arguments[0][1:]
            if any(flag not in "neE" for flag in flags):
                break
            trailing_newline = trailing_newline and "n" not in flags
            if "e" in flags:
                interpret = True
            if "E" in flags:
                interpret = False
            arguments.pop(0)
        text = " ".join(arguments)
        stop = False
        if interpret:
            text, stop = interpret_escapes(text)
        if trailing_newline and not stop:
            text += "\n"
        return CommandResult(stdout=text, exit_code=EXIT_CODE_SUCCESS)
