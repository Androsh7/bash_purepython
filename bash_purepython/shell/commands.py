"""Discover and load the command modules the package ships"""

# Standard libraries
import functools
import importlib
import pkgutil
from collections.abc import Callable

# Project libraries
import bash_purepython
from bash_purepython.shell.models import CommandNotFoundError


@functools.cache
def list_command_names() -> tuple[str, ...]:
    """Return the name of every command module in the package, sorted

    Subpackages and underscore-prefixed helper modules are not commands. The set is
    fixed for the life of the process, so the package is scanned once

    Returns:
        The command names
    """
    return tuple(
        sorted(
            module.name
            for module in pkgutil.iter_modules(bash_purepython.__path__)
            if not module.ispkg and not module.name.startswith("_")
        )
    )


def load_command_main(name: str) -> Callable[[], object]:
    """Return the main function of one command module

    Args:
        name: The command name, which is also the module name

    Raises:
        CommandNotFoundError: If no such command module exists

    Returns:
        The command's main function, which reads sys.argv itself
    """
    if name not in list_command_names():
        raise CommandNotFoundError(name)
    module = importlib.import_module(f"bash_purepython.{name}")
    return module.main
