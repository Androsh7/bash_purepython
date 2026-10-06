"""Re-chunk streamed text into whole lines"""

# Standard libraries
from collections.abc import Iterator
from typing import Any

# Project libraries
from bash_purepython.command.command import InputKind


def iterate_lines(chunks: Iterator[str]) -> Iterator[str]:
    """Yield one line at a time from chunks that may split or join lines arbitrarily

    Args:
        chunks: Text chunks in order

    Yields:
        Each line with its newline kept, and a final partial line without one
    """
    remainder = ""
    for chunk in chunks:
        remainder += chunk
        while True:
            newline_index = remainder.find("\n")
            if newline_index == -1:
                break
            yield remainder[: newline_index + 1]
            remainder = remainder[newline_index + 1 :]
    if remainder:
        yield remainder


def stdin_lines(stdin: Any, stdin_kind: InputKind) -> Iterator[str]:
    """Yield the lines of a command's standard input whatever kind it arrived in

    Args:
        stdin: The input value
        stdin_kind: The kind the value is in

    Yields:
        Each line with its newline kept
    """
    if stdin_kind == InputKind.TEXT:
        yield from iterate_lines(iter([stdin]))
    elif stdin_kind == InputKind.STREAM_TEXT:
        yield from iterate_lines(stdin)
    elif stdin_kind == InputKind.BYTES:
        yield from iterate_lines(iter([stdin.decode("utf-8", errors="replace")]))
    elif stdin_kind == InputKind.STREAM_BYTES:
        yield from iterate_lines(chunk.decode("utf-8", errors="replace") for chunk in stdin)


def close_stdin(stdin: Any) -> None:
    """Stop an upstream producer once the consumer needs nothing more from it

    Args:
        stdin: The input value, which is closed when it supports closing
    """
    close = getattr(stdin, "close", None)
    if close is not None:
        close()
