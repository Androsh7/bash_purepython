"""Re-chunk streamed text into whole lines"""

# Standard libraries
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# Project libraries
from bash_purepython.command.command import InputKind
from bash_purepython.streams import TEXT_ENCODING, as_async_iterator, close_iterator


async def iterate_lines(chunks: Any) -> AsyncIterator[str]:
    """Yield one line at a time from chunks that may split or join lines arbitrarily

    Args:
        chunks: Text chunks in order, synchronous or asynchronous

    Yields:
        Each line with its newline kept, and a final partial line without one
    """
    source = as_async_iterator(chunks)
    remainder = ""
    try:
        async for chunk in source:
            remainder += chunk
            while True:
                newline_index = remainder.find("\n")
                if newline_index == -1:
                    break
                yield remainder[: newline_index + 1]
                remainder = remainder[newline_index + 1 :]
        if remainder:
            yield remainder
    finally:
        await close_iterator(source)


async def decoded(chunks: Any) -> AsyncIterator[str]:
    """Yield byte chunks decoded as text

    Args:
        chunks: Byte chunks, synchronous or asynchronous

    Yields:
        The decoded text
    """
    async for chunk in as_async_iterator(chunks):
        yield chunk.decode(TEXT_ENCODING, errors="replace")


def stdin_lines(stdin: Any, stdin_kind: InputKind) -> AsyncIterator[str]:
    """Return the lines of a command's standard input whatever kind it arrived in

    Args:
        stdin: The input value
        stdin_kind: The kind the value is in

    Returns:
        An async iterator over the lines, each with its newline kept
    """
    if stdin_kind == InputKind.TEXT:
        return iterate_lines([stdin])
    if stdin_kind == InputKind.BYTES:
        return iterate_lines([stdin.decode(TEXT_ENCODING, errors="replace")])
    if stdin_kind == InputKind.STREAM_BYTES:
        return iterate_lines(decoded(stdin))
    return iterate_lines(stdin)


def file_lines(path: Path) -> AsyncIterator[str]:
    """Return the lines of a file

    Args:
        path: The file to read

    Returns:
        An async iterator over the lines, each with its newline kept
    """
    return iterate_lines([path.read_text(encoding=TEXT_ENCODING, errors="replace")])


async def close_stdin(stdin: Any) -> None:
    """Stop an upstream producer once the consumer needs nothing more from it

    Args:
        stdin: The input value, which is closed when it supports closing
    """
    await close_iterator(stdin)
