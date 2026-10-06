"""Shared fixtures for the shell tests"""

# Standard libraries
import os
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import HostCommand
from bash_purepython.shell.session import ShellSession

HOST_COMMANDS = (
    HostCommand(name="vim", summary="open file in vim.wasm"),
    HostCommand(name="python", summary="run python (REPL with no args)"),
    HostCommand(name="py", summary=""),
)
TEST_USER = "guest"


@pytest.fixture
def shell_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return an empty directory that is both the working directory and home, with the environment isolated"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", os.environ.copy())
    return tmp_path


@pytest.fixture
def host_commands() -> tuple[HostCommand, ...]:
    """Return the host commands every test shell is started with"""
    return HOST_COMMANDS


@pytest.fixture
def session(shell_home: Path) -> ShellSession:
    """Return a shell rooted in the isolated home directory"""
    return ShellSession(
        home=str(shell_home),
        host_commands=HOST_COMMANDS,
        environment={"HOME": str(shell_home), "USER": TEST_USER},
    )
