"""Tests for the shell's own commands, run through a session"""

# Standard libraries
from pathlib import Path

# Project libraries
from bash_purepython.shell.builtins import CLEAR_SCREEN_SEQUENCE, format_columns
from bash_purepython.shell.models import CommandKind, HostCommand
from bash_purepython.shell.session import ShellSession


def test_cd_changes_the_working_directory_and_pwd(session: ShellSession, shell_home: Path) -> None:
    """Check that cd moves the session and records PWD"""
    (shell_home / "sub").mkdir()

    result = session.run_line("cd sub")

    assert result.exit_code == 0
    assert Path(result.cwd) == shell_home / "sub"
    assert Path(session.run_line("echo $PWD").stdout.strip()) == shell_home / "sub"


def test_cd_without_arguments_goes_home(session: ShellSession, shell_home: Path) -> None:
    """Check that a bare cd returns to the home directory"""
    (shell_home / "sub").mkdir()
    session.run_line("cd sub")

    result = session.run_line("cd")

    assert Path(result.cwd) == shell_home


def test_cd_dash_returns_to_the_previous_directory(session: ShellSession, shell_home: Path) -> None:
    """Check that cd - swaps back to where the session came from"""
    (shell_home / "sub").mkdir()
    session.run_line("cd sub")

    result = session.run_line("cd -")

    assert Path(result.cwd) == shell_home


def test_cd_dash_fails_before_any_directory_change(session: ShellSession, shell_home: Path) -> None:
    """Check that cd - with no previous directory is an error and stays put"""
    result = session.run_line("cd -")

    assert result.exit_code == 1
    assert "OLDPWD" in result.stderr
    assert Path(result.cwd) == shell_home


def test_cd_reports_a_missing_directory_and_stays_put(session: ShellSession, shell_home: Path) -> None:
    """Check that cd to a missing path fails without moving"""
    result = session.run_line("cd nowhere")

    assert result.exit_code == 1
    assert "nowhere" in result.stderr
    assert Path(result.cwd) == shell_home


def test_cd_rejects_a_file(session: ShellSession, shell_home: Path) -> None:
    """Check that cd to a regular file fails"""
    (shell_home / "plain.txt").write_text("x")

    result = session.run_line("cd plain.txt")

    assert result.exit_code == 1
    assert Path(result.cwd) == shell_home


def test_export_sets_a_variable_visible_to_later_commands(session: ShellSession) -> None:
    """Check that an exported variable expands on the next line and appears in the result"""
    session.run_line("export GREETING=hello")

    result = session.run_line("echo $GREETING")

    assert result.stdout == "hello\n"
    assert result.environment["GREETING"] == "hello"


def test_export_rejects_an_argument_without_an_equals_sign(session: ShellSession) -> None:
    """Check that export needs NAME=value"""
    result = session.run_line("export GREETING")

    assert result.exit_code == 1
    assert "GREETING" in result.stderr


def test_export_without_arguments_prints_usage(session: ShellSession) -> None:
    """Check that a bare export is an error"""
    result = session.run_line("export")

    assert result.exit_code == 1


def test_history_lists_lines_in_order_without_consecutive_duplicates(session: ShellSession) -> None:
    """Check that history numbers every distinct line, collapsing repeats"""
    session.run_line("echo one")
    session.run_line("echo one")
    session.run_line("echo two")

    result = session.run_line("history")

    entries = [line.split(maxsplit=1)[1] for line in result.stdout.splitlines()]
    assert entries == ["echo one", "echo two", "history"]


def test_which_reports_where_each_command_comes_from(session: ShellSession) -> None:
    """Check that builtins, package commands and host commands are told apart"""
    result = session.run_line("which cd ls vim")

    kinds = dict(line.split(": ", maxsplit=1) for line in result.stdout.splitlines())
    assert kinds == {"cd": CommandKind.BUILTIN, "ls": CommandKind.PACKAGE, "vim": CommandKind.HOST}
    assert result.exit_code == 0


def test_which_fails_for_an_unknown_command(session: ShellSession) -> None:
    """Check that an unknown name goes to stderr with exit code one"""
    result = session.run_line("which nothing")

    assert result.exit_code == 1
    assert "nothing" in result.stderr


def test_help_lists_every_kind_of_command_and_the_host_summaries(
    session: ShellSession, host_commands: tuple[HostCommand, ...]
) -> None:
    """Check that help covers builtins, package commands and host commands with their summaries"""
    result = session.run_line("help")

    assert result.exit_code == 0
    assert "cd" in result.stdout
    assert "grep" in result.stdout
    assert host_commands[0].name in result.stdout
    assert host_commands[0].summary in result.stdout


def test_uname_prints_the_system_name(session: ShellSession) -> None:
    """Check that uname and uname -a both print the system name"""
    short = session.run_line("uname")
    long = session.run_line("uname -a")

    assert short.stdout.strip() == "ash7"
    assert long.stdout.startswith("ash7 ")


def test_clear_writes_the_clear_screen_sequence(session: ShellSession) -> None:
    """Check that clear emits the escape sequence the terminal understands"""
    result = session.run_line("clear")

    assert result.stdout == CLEAR_SCREEN_SEQUENCE


def test_format_columns_fits_every_name_within_the_width() -> None:
    """Check that no row is wider than the terminal"""
    names = [f"name{number}" for number in range(20)]

    rows = format_columns(names, width=30).splitlines()

    assert all(len(row) <= 30 for row in rows)
    assert set(" ".join(rows).split()) == set(names)
