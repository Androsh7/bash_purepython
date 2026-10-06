"""Carry command output lazily between pipeline stages and convert it between kinds"""

# Standard libraries
from collections.abc import Generator, Iterator
from typing import Any

# Project libraries
from bash_purepython.command.command import InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_BROKEN_PIPE, EXIT_CODE_SUCCESS

TEXT_ENCODING = "utf-8"
STREAM_KINDS = frozenset({OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES})
BYTE_KINDS = frozenset({OutputKind.BYTES, OutputKind.STREAM_BYTES})
KIND_PREFERENCE = (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES, OutputKind.TEXT, OutputKind.BYTES)


class TextStream:
    """Wrap a lazy iterator of text chunks and remember how it finished"""

    def __init__(self, source: Iterator[str], provisional_exit_code: int = EXIT_CODE_SUCCESS):
        """Wrap one iterator

        Args:
            source: The chunks, pulled only as the consumer asks for them
            provisional_exit_code: The exit code reported until the source finishes
        """
        self._source = source
        self.exit_code = provisional_exit_code
        self.finished = False
        self.upstream: TextStream | None = None

    def __iter__(self) -> Iterator[str]:
        """Yield every chunk, recording the generator's return value as the exit code"""
        if self.finished:
            return
        try:
            while True:
                try:
                    chunk = next(self._source)
                except StopIteration as stop:
                    if isinstance(stop.value, int):
                        self.exit_code = stop.value
                    self.finished = True
                    self._close_upstream()
                    return
                yield chunk
        finally:
            if not self.finished:
                self.close()

    def close(self) -> None:
        """Stop pulling from the source and mark the stream as cut short"""
        if self.finished:
            return
        self.finished = True
        self.exit_code = EXIT_CODE_BROKEN_PIPE
        close = getattr(self._source, "close", None)
        if close is not None:
            close()
        self._close_upstream()

    def _close_upstream(self) -> None:
        """Stop the stream feeding this one, if any"""
        if self.upstream is not None:
            self.upstream.close()
            self.upstream = None

    def read_all(self) -> str:
        """Return every remaining chunk joined into one string"""
        return "".join(self)


def choose_kinds(
    producer_kinds: frozenset[OutputKind], consumer_kinds: frozenset[InputKind]
) -> tuple[OutputKind, InputKind]:
    """Return the output kind the producer should emit and the input kind the consumer should receive

    A kind both sides support is chosen first, streaming before static. Otherwise the producer's most
    streamable kind is paired with the consumer's most streamable kind and converted between

    Args:
        producer_kinds: The kinds the upstream command can emit
        consumer_kinds: The kinds the downstream command can accept

    Returns:
        The producer's output kind and the consumer's input kind
    """
    consumer_output_kinds = {OutputKind(kind) for kind in consumer_kinds if kind != InputKind.ARGUMENTS}
    for kind in KIND_PREFERENCE:
        if kind in producer_kinds and kind in consumer_output_kinds:
            return kind, InputKind(kind)
    producer_kind = next(kind for kind in KIND_PREFERENCE if kind in producer_kinds)
    consumer_kind = next(kind for kind in KIND_PREFERENCE if kind in consumer_output_kinds)
    return producer_kind, InputKind(consumer_kind)


def decode_chunks(chunks: Iterator[bytes]) -> Generator[str, None, int]:
    """Yield each byte chunk decoded as text

    Args:
        chunks: The byte chunks to decode

    Returns:
        The exit code of the source, if it was a generator that returned one
    """
    exit_code = yield from (chunk.decode(TEXT_ENCODING, errors="replace") for chunk in chunks)
    return exit_code if isinstance(exit_code, int) else EXIT_CODE_SUCCESS


def encode_chunks(chunks: Iterator[str]) -> Generator[bytes, None, int]:
    """Yield each text chunk encoded as bytes

    Args:
        chunks: The text chunks to encode

    Returns:
        The exit code of the source, if it was a generator that returned one
    """
    exit_code = yield from (chunk.encode(TEXT_ENCODING) for chunk in chunks)
    return exit_code if isinstance(exit_code, int) else EXIT_CODE_SUCCESS


def convert(value: Any, from_kind: OutputKind, to_kind: OutputKind) -> Any:
    """Return the value re-shaped into another kind

    Args:
        value: The output in its current kind
        from_kind: The kind the value is in
        to_kind: The kind the value is needed in

    Returns:
        The same data in the requested kind, lazily where both kinds stream
    """
    if from_kind == to_kind:
        return value
    if from_kind in STREAM_KINDS and to_kind in STREAM_KINDS:
        return decode_chunks(value) if from_kind == OutputKind.STREAM_BYTES else encode_chunks(value)
    if from_kind in STREAM_KINDS:
        joined = b"".join(value) if from_kind == OutputKind.STREAM_BYTES else "".join(value)
        return convert(joined, OutputKind.BYTES if from_kind == OutputKind.STREAM_BYTES else OutputKind.TEXT, to_kind)
    if to_kind in STREAM_KINDS:
        static_kind = OutputKind.BYTES if to_kind == OutputKind.STREAM_BYTES else OutputKind.TEXT
        return iter([convert(value, from_kind, static_kind)])
    if to_kind == OutputKind.BYTES:
        return value.encode(TEXT_ENCODING)
    return value.decode(TEXT_ENCODING, errors="replace")


def materialise_text(value: Any, kind: OutputKind) -> str:
    """Return the whole output as one string

    Args:
        value: The output in its kind
        kind: The kind the value is in

    Returns:
        The output decoded and joined
    """
    return convert(value, kind, OutputKind.TEXT)
