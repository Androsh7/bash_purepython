"""Carry command output lazily between pipeline stages and convert it between kinds"""

# Standard libraries
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

# Project libraries
from bash_purepython.command.command import ExitStatus, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_BROKEN_PIPE, EXIT_CODE_SUCCESS

TEXT_ENCODING = "utf-8"
STREAM_KINDS = frozenset({OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES})
BYTE_KINDS = frozenset({OutputKind.BYTES, OutputKind.STREAM_BYTES})
KIND_PREFERENCE = (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES, OutputKind.TEXT, OutputKind.BYTES)


def is_async_iterable(value: Any) -> bool:
    """Return whether a value is iterated with ``async for``

    Args:
        value: Any object

    Returns:
        True for async iterators and async iterables
    """
    return hasattr(value, "__aiter__")


async def iterate_sync(source: Iterator[Any], exit_status: ExitStatus) -> AsyncIterator[Any]:
    """Yield from a synchronous iterator, recording a generator's return value as the exit code

    Args:
        source: The synchronous iterator
        exit_status: Receives the generator's integer return value, if it returns one

    Yields:
        Each item of the source
    """
    try:
        while True:
            try:
                item = next(source)
            except StopIteration as stop:
                if isinstance(stop.value, int):
                    exit_status.code = stop.value
                return
            yield item
    finally:
        close = getattr(source, "close", None)
        if close is not None:
            close()


class TextStream:
    """Wrap a lazy source of text chunks, synchronous or asynchronous, and remember how it finished"""

    def __init__(
        self,
        source: Any,
        provisional_exit_code: int = EXIT_CODE_SUCCESS,
        exit_status: ExitStatus | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ):
        """Wrap one source

        Args:
            source: An iterator or async iterator of chunks, pulled only as the consumer asks for them
            provisional_exit_code: The exit code reported until the source finishes
            exit_status: Where the producer records its final exit code, if it has one
            on_close: Awaited when the stream is closed early, to stop the producer
        """
        self.exit_status = exit_status if exit_status is not None else ExitStatus(provisional_exit_code)
        self._source: AsyncIterator[Any] = (
            source.__aiter__() if is_async_iterable(source) else iterate_sync(iter(source), self.exit_status)
        )
        self.finished = False
        self.upstream: TextStream | None = None
        self.on_close = on_close

    @property
    def exit_code(self) -> int:
        """Return the exit code known so far"""
        return self.exit_status.code

    def __aiter__(self) -> AsyncIterator[str]:
        """Return the stream itself as its iterator"""
        return self

    async def __anext__(self) -> str:
        """Pull the next chunk, closing the upstream once the source is exhausted

        Raises:
            StopAsyncIteration: When the source has no more chunks
        """
        if self.finished:
            raise StopAsyncIteration
        try:
            return await self._source.__anext__()
        except StopAsyncIteration:
            self.finished = True
            await self._close_upstream()
            raise

    async def aclose(self) -> None:
        """Stop pulling from the source and mark the stream as cut short"""
        if self.finished:
            return
        self.finished = True
        self.exit_status.code = EXIT_CODE_BROKEN_PIPE
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            await aclose()
        if self.on_close is not None:
            await self.on_close()
        await self._close_upstream()

    async def _close_upstream(self) -> None:
        """Stop the stream feeding this one, if any"""
        if self.upstream is not None:
            upstream, self.upstream = self.upstream, None
            await upstream.aclose()

    async def read_all(self) -> str:
        """Return every remaining chunk joined into one string"""
        pieces = [chunk async for chunk in self]
        return "".join(pieces)


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


def as_async_iterator(value: Any) -> AsyncIterator[Any]:
    """Return a value as an async iterator, wrapping a synchronous iterator when needed

    Args:
        value: An iterator, iterable, async iterator or async iterable

    Returns:
        An async iterator over the same items
    """
    if is_async_iterable(value):
        return value.__aiter__()
    return iterate_sync(iter(value), ExitStatus())


async def decode_chunks(chunks: Any) -> AsyncIterator[str]:
    """Yield each byte chunk decoded as text

    Args:
        chunks: The byte chunks to decode, synchronous or asynchronous

    Yields:
        The decoded text
    """
    source = as_async_iterator(chunks)
    try:
        async for chunk in source:
            yield chunk.decode(TEXT_ENCODING, errors="replace")
    finally:
        await close_iterator(source)


async def encode_chunks(chunks: Any) -> AsyncIterator[bytes]:
    """Yield each text chunk encoded as bytes

    Args:
        chunks: The text chunks to encode, synchronous or asynchronous

    Yields:
        The encoded bytes
    """
    source = as_async_iterator(chunks)
    try:
        async for chunk in source:
            yield chunk.encode(TEXT_ENCODING)
    finally:
        await close_iterator(source)


async def single_chunk(value: Any) -> AsyncIterator[Any]:
    """Yield one value as a stream of one chunk

    Args:
        value: The whole output

    Yields:
        The value, once
    """
    yield value


async def close_iterator(source: Any) -> None:
    """Stop a producer the consumer needs nothing more from

    Args:
        source: An iterator, async iterator, or anything else, which is closed when it can be
    """
    aclose = getattr(source, "aclose", None)
    if aclose is not None:
        await aclose()
        return
    close = getattr(source, "close", None)
    if close is not None:
        close()


async def join_stream(chunks: Any, as_bytes: bool) -> Any:
    """Return every chunk of a stream joined together

    Args:
        chunks: The stream, synchronous or asynchronous
        as_bytes: Whether the chunks are bytes rather than text

    Returns:
        The joined bytes or text
    """
    pieces = [chunk async for chunk in as_async_iterator(chunks)]
    return b"".join(pieces) if as_bytes else "".join(pieces)


async def convert(value: Any, from_kind: OutputKind, to_kind: OutputKind) -> Any:
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
        joined = await join_stream(value, as_bytes=from_kind == OutputKind.STREAM_BYTES)
        static_kind = OutputKind.BYTES if from_kind == OutputKind.STREAM_BYTES else OutputKind.TEXT
        return await convert(joined, static_kind, to_kind)
    if to_kind in STREAM_KINDS:
        static_kind = OutputKind.BYTES if to_kind == OutputKind.STREAM_BYTES else OutputKind.TEXT
        return single_chunk(await convert(value, from_kind, static_kind))
    if to_kind == OutputKind.BYTES:
        return value.encode(TEXT_ENCODING)
    return value.decode(TEXT_ENCODING, errors="replace")


async def materialise_text(value: Any, kind: OutputKind) -> str:
    """Return the whole output as one string

    Args:
        value: The output in its kind
        kind: The kind the value is in

    Returns:
        The output decoded and joined
    """
    return await convert(value, kind, OutputKind.TEXT)
