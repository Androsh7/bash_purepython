"""Map command names to the command objects that implement them"""

# Project libraries
from bash_purepython.command.cat import CatCommand
from bash_purepython.command.command import Command
from bash_purepython.command.echo import EchoCommand
from bash_purepython.command.false_command import FalseCommand
from bash_purepython.command.head import HeadCommand
from bash_purepython.command.kill import KillCommand
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.ps import PsCommand
from bash_purepython.command.sleep import SleepCommand
from bash_purepython.command.true_command import TrueCommand
from bash_purepython.command.yes import YesCommand

COMMAND_CLASSES: tuple[type[Command], ...] = (
    CatCommand,
    EchoCommand,
    FalseCommand,
    HeadCommand,
    KillCommand,
    PrintfCommand,
    PsCommand,
    SleepCommand,
    TrueCommand,
    YesCommand,
)


class CommandRegistry:
    """Hold the commands a shell can run, by name"""

    def __init__(self, commands: list[Command] | None = None):
        """Register the given commands, defaulting to every command the package ships

        Args:
            commands: The command objects to register
        """
        self.commands: dict[str, Command] = {}
        for command in commands if commands is not None else [command_class() for command_class in COMMAND_CLASSES]:
            self.register(command)

    def register(self, command: Command) -> None:
        """Add or replace one command

        Args:
            command: The command object, registered under its own name
        """
        self.commands[command.name] = command

    def get(self, name: str) -> Command | None:
        """Return the command registered under a name, or None

        Args:
            name: The command name

        Returns:
            The command object, or None when the name is unknown
        """
        return self.commands.get(name)

    def names(self) -> list[str]:
        """Return every registered name, sorted

        Returns:
            The command names
        """
        return sorted(self.commands)
