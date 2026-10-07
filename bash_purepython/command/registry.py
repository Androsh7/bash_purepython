"""Map command names to the command objects that implement them"""

# Project libraries
from bash_purepython.command.basename import BasenameCommand
from bash_purepython.command.cat import CatCommand
from bash_purepython.command.command import Command
from bash_purepython.command.cp import CpCommand
from bash_purepython.command.cut import CutCommand
from bash_purepython.command.date import DateCommand
from bash_purepython.command.dirname import DirnameCommand
from bash_purepython.command.echo import EchoCommand
from bash_purepython.command.env import EnvCommand
from bash_purepython.command.false_command import FalseCommand
from bash_purepython.command.find import FindCommand
from bash_purepython.command.grep import GrepCommand
from bash_purepython.command.gzip import GunzipCommand, GzipCommand
from bash_purepython.command.head import HeadCommand
from bash_purepython.command.help import HelpCommand
from bash_purepython.command.kill import KillCommand
from bash_purepython.command.ls import LsCommand
from bash_purepython.command.mkdir import MkdirCommand
from bash_purepython.command.mv import MvCommand
from bash_purepython.command.nl import NlCommand
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.ps import PsCommand
from bash_purepython.command.pwd import PwdCommand
from bash_purepython.command.realpath import RealpathCommand
from bash_purepython.command.rev import RevCommand
from bash_purepython.command.rm import RmCommand
from bash_purepython.command.rmdir import RmdirCommand
from bash_purepython.command.seq import SeqCommand
from bash_purepython.command.sleep import SleepCommand
from bash_purepython.command.true_command import TrueCommand
from bash_purepython.command.yes import YesCommand

COMMAND_CLASSES: tuple[type[Command], ...] = (
    BasenameCommand,
    CatCommand,
    CpCommand,
    CutCommand,
    DateCommand,
    DirnameCommand,
    EchoCommand,
    EnvCommand,
    FalseCommand,
    FindCommand,
    GrepCommand,
    GunzipCommand,
    GzipCommand,
    HeadCommand,
    KillCommand,
    LsCommand,
    MkdirCommand,
    MvCommand,
    NlCommand,
    PrintfCommand,
    PsCommand,
    PwdCommand,
    RealpathCommand,
    RevCommand,
    RmCommand,
    RmdirCommand,
    SeqCommand,
    SleepCommand,
    TrueCommand,
    YesCommand,
)


class CommandRegistry:
    """Hold the commands a shell can run, by name"""

    def __init__(self, commands: list[Command] | None = None):
        """Register the given commands, defaulting to every command the package ships plus help

        Args:
            commands: The command objects to register
        """
        self.commands: dict[str, Command] = {}
        for command in commands if commands is not None else [command_class() for command_class in COMMAND_CLASSES]:
            self.register(command)
        if commands is None:
            self.register(HelpCommand(self.names))

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
