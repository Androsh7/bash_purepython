"""Tests for command discovery"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.commands import list_command_names, load_command_main
from bash_purepython.shell.models import CommandNotFoundError


def test_list_command_names_includes_every_command_module() -> None:
    """Check that the well known commands are discovered"""
    names = list_command_names()

    assert {"ls", "cat", "grep", "echo", "help"} <= set(names)


def test_list_command_names_excludes_helpers_and_subpackages() -> None:
    """Check that the shell subpackage and underscore modules are not commands"""
    names = list_command_names()

    assert "shell" not in names
    assert not any(name.startswith("_") for name in names)


def test_load_command_main_returns_a_callable_for_a_known_command() -> None:
    """Check that a command's main function can be loaded by name"""
    main = load_command_main("echo")

    assert callable(main)


def test_load_command_main_raises_for_an_unknown_command() -> None:
    """Check that an unknown name is reported rather than imported"""
    with pytest.raises(CommandNotFoundError):
        load_command_main("shell")
