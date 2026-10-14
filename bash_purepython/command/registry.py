"""Map command names to the command objects that implement them"""

# Project libraries
from bash_purepython.command.base64 import Base64Command
from bash_purepython.command.basename import BasenameCommand
from bash_purepython.command.cat import CatCommand
from bash_purepython.command.chmod import ChmodCommand
from bash_purepython.command.column import ColumnCommand
from bash_purepython.command.command import Command
from bash_purepython.command.cp import CpCommand
from bash_purepython.command.cut import CutCommand
from bash_purepython.command.date import DateCommand
from bash_purepython.command.df import DfCommand
from bash_purepython.command.diff import DiffCommand
from bash_purepython.command.dirname import DirnameCommand
from bash_purepython.command.du import DuCommand
from bash_purepython.command.echo import EchoCommand
from bash_purepython.command.env import EnvCommand
from bash_purepython.command.expr import ExprCommand
from bash_purepython.command.false_command import FalseCommand
from bash_purepython.command.file import FileCommand
from bash_purepython.command.find import FindCommand
from bash_purepython.command.fold import FoldCommand
from bash_purepython.command.grep import GrepCommand
from bash_purepython.command.gzip import GunzipCommand, GzipCommand
from bash_purepython.command.hashes import Md5sumCommand, Sha1sumCommand, Sha256sumCommand, Sha512sumCommand
from bash_purepython.command.head import HeadCommand
from bash_purepython.command.help import HelpCommand
from bash_purepython.command.hostname import HostnameCommand
from bash_purepython.command.id import IdCommand
from bash_purepython.command.kill import KillCommand
from bash_purepython.command.ls import LsCommand
from bash_purepython.command.mkdir import MkdirCommand
from bash_purepython.command.mktemp import MktempCommand
from bash_purepython.command.mv import MvCommand
from bash_purepython.command.nl import NlCommand
from bash_purepython.command.od import OdCommand
from bash_purepython.command.pager import LessCommand, MoreCommand
from bash_purepython.command.paste import PasteCommand
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.ps import PsCommand
from bash_purepython.command.pwd import PwdCommand
from bash_purepython.command.realpath import RealpathCommand
from bash_purepython.command.rev import RevCommand
from bash_purepython.command.rm import RmCommand
from bash_purepython.command.rmdir import RmdirCommand
from bash_purepython.command.sed import SedCommand
from bash_purepython.command.seq import SeqCommand
from bash_purepython.command.sleep import SleepCommand
from bash_purepython.command.sort import SortCommand
from bash_purepython.command.stat import StatCommand
from bash_purepython.command.tail import TailCommand
from bash_purepython.command.tar import TarCommand
from bash_purepython.command.tee import TeeCommand
from bash_purepython.command.test_command import BracketCommand, TestCommand
from bash_purepython.command.touch import TouchCommand
from bash_purepython.command.tr import TrCommand
from bash_purepython.command.tree import TreeCommand
from bash_purepython.command.true_command import TrueCommand
from bash_purepython.command.uname import UnameCommand
from bash_purepython.command.uniq import UniqCommand
from bash_purepython.command.unzip import UnzipCommand
from bash_purepython.command.wc import WcCommand
from bash_purepython.command.which import WhichCommand
from bash_purepython.command.whoami import WhoamiCommand
from bash_purepython.command.xxd import XxdCommand
from bash_purepython.command.yes import YesCommand
from bash_purepython.command.zip import ZipCommand

COMMAND_CLASSES: tuple[type[Command], ...] = (
    Base64Command,
    BasenameCommand,
    BracketCommand,
    CatCommand,
    ChmodCommand,
    ColumnCommand,
    CpCommand,
    CutCommand,
    DateCommand,
    DfCommand,
    DiffCommand,
    DirnameCommand,
    DuCommand,
    EchoCommand,
    EnvCommand,
    ExprCommand,
    FalseCommand,
    FileCommand,
    FindCommand,
    FoldCommand,
    GrepCommand,
    GunzipCommand,
    GzipCommand,
    HeadCommand,
    HostnameCommand,
    IdCommand,
    KillCommand,
    LessCommand,
    LsCommand,
    Md5sumCommand,
    MkdirCommand,
    MktempCommand,
    MoreCommand,
    MvCommand,
    NlCommand,
    OdCommand,
    PasteCommand,
    PrintfCommand,
    PsCommand,
    PwdCommand,
    RealpathCommand,
    RevCommand,
    RmCommand,
    RmdirCommand,
    SedCommand,
    SeqCommand,
    Sha1sumCommand,
    Sha256sumCommand,
    Sha512sumCommand,
    SleepCommand,
    SortCommand,
    StatCommand,
    TailCommand,
    TarCommand,
    TeeCommand,
    TestCommand,
    TouchCommand,
    TrCommand,
    TreeCommand,
    TrueCommand,
    UnameCommand,
    UniqCommand,
    UnzipCommand,
    WcCommand,
    WhoamiCommand,
    XxdCommand,
    YesCommand,
    ZipCommand,
)


class CommandRegistry:
    """Hold the commands a shell can run, by name"""

    def __init__(self, commands: list[Command] | None = None):
        """Register the given commands, defaulting to every command the package ships plus help and which

        Args:
            commands: The command objects to register
        """
        self.commands: dict[str, Command] = {}
        for command in commands if commands is not None else [command_class() for command_class in COMMAND_CLASSES]:
            self.register(command)
        if commands is None:
            self.register(HelpCommand(self.names, self.summaries))
            self.register(WhichCommand(self.names))

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

    def summaries(self) -> dict[str, str]:
        """Return the one-line summary of every registered command by name

        Returns:
            Names mapped to summaries, empty for a command that declares none
        """
        return {name: command.summary for name, command in sorted(self.commands.items())}
