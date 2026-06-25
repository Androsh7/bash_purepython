"""Shared I/O helpers for text-processing commands"""

# Standard libraries
import sys
from collections.abc import Iterator
from pathlib import Path

# Project libraries
from bash_python_utils.color import print_error


def iter_lines(paths: list[str]) -> Iterator[tuple[str, str]]:
    """Yield (source_label, line) for every line in paths, or stdin if empty.

    Lines retain their trailing newline when present.
    """
    if not paths:
        for line in sys.stdin:
            yield "-", line
        return
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print_error(f"{path}: No such file or directory")
        if path.is_dir():
            print_error(f"{path}: Is a directory")
        with path.open("r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                yield path_str, line


def read_text(paths: list[str]) -> str:
    """Read the concatenation of paths, or stdin if no paths."""
    if not paths:
        return sys.stdin.read()
    chunks: list[str] = []
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print_error(f"{path}: No such file or directory")
        if path.is_dir():
            print_error(f"{path}: Is a directory")
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "".join(chunks)


def read_bytes(paths: list[str]) -> bytes:
    """Read the concatenation of paths as bytes, or stdin if no paths."""
    if not paths:
        return sys.stdin.buffer.read()
    chunks: list[bytes] = []
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print_error(f"{path}: No such file or directory")
        if path.is_dir():
            print_error(f"{path}: Is a directory")
        chunks.append(path.read_bytes())
    return b"".join(chunks)
