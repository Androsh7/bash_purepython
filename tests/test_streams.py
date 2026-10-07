"""Test lazy streams and conversion between output kinds"""

# Standard libraries
import asyncio
from collections.abc import AsyncIterator, Generator

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.command import ExitStatus, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_BROKEN_PIPE
from bash_purepython.streams import TextStream, choose_kinds, convert


class CountingProducer:
    """Yield numbered lines forever while counting how many were pulled and whether it was closed"""

    def __init__(self):
        """Start with nothing pulled"""
        self.pulled = 0
        self.closed = False

    async def lines(self) -> AsyncIterator[str]:
        """Yield lines until closed

        Yields:
            Numbered lines
        """
        try:
            while True:
                self.pulled += 1
                yield f"{self.pulled}\n"
        finally:
            self.closed = True


def finite_lines(count: int, exit_code: int) -> Generator[str, None, int]:
    """Yield a fixed number of lines then return an exit code

    Args:
        count: How many lines to yield
        exit_code: The value to return

    Returns:
        The exit code
    """
    for line_number in range(1, count + 1):
        yield f"{line_number}\n"
    return exit_code


async def take(stream: TextStream, count: int) -> list[str]:
    """Return the first chunks of a stream without exhausting it

    Args:
        stream: The stream to pull from
        count: How many chunks to take

    Returns:
        The chunks
    """
    taken: list[str] = []
    async for chunk in stream:
        taken.append(chunk)
        if len(taken) >= count:
            break
    return taken


def test_text_stream_pulls_lazily_and_closes_the_source_when_closed() -> None:
    """Check that a consumer taking three lines pulls only three and closing stops the producer"""
    producer = CountingProducer()
    stream = TextStream(producer.lines())

    async def scenario() -> list[str]:
        taken = await take(stream, 3)
        await stream.aclose()
        return taken

    taken = asyncio.run(scenario())

    assert (taken, producer.pulled, producer.closed) == (["1\n", "2\n", "3\n"], 3, True)


def test_text_stream_reports_broken_pipe_when_closed_early() -> None:
    """Check that closing before exhaustion sets the broken-pipe exit code"""
    stream = TextStream(finite_lines(5, exit_code=0))

    async def scenario() -> None:
        await take(stream, 1)
        await stream.aclose()

    asyncio.run(scenario())

    assert stream.exit_code == EXIT_CODE_BROKEN_PIPE


def test_text_stream_takes_exit_code_from_sync_generator_return() -> None:
    """Check that a synchronous generator's return value becomes the exit code once exhausted"""
    stream = TextStream(finite_lines(2, exit_code=3), provisional_exit_code=0)

    text = asyncio.run(stream.read_all())

    assert (text, stream.exit_code, stream.finished) == ("1\n2\n", 3, True)


def test_text_stream_takes_exit_code_from_exit_status() -> None:
    """Check that an async producer reports failure by changing the shared exit status"""
    status = ExitStatus(0)

    async def failing_lines() -> AsyncIterator[str]:
        yield "partial\n"
        status.code = 1

    stream = TextStream(failing_lines(), exit_status=status)

    text = asyncio.run(stream.read_all())

    assert (text, stream.exit_code) == ("partial\n", 1)


def test_text_stream_closes_its_upstream_when_it_finishes() -> None:
    """Check that a stream feeding another is closed when the downstream one is exhausted"""
    producer = CountingProducer()
    upstream = TextStream(producer.lines())
    downstream = TextStream(finite_lines(1, exit_code=0))
    downstream.upstream = upstream

    async def scenario() -> None:
        await take(upstream, 1)
        await downstream.read_all()

    asyncio.run(scenario())

    assert (producer.closed, upstream.finished) == (True, True)


def test_text_stream_runs_its_close_hook() -> None:
    """Check that closing early awaits the hook that stops a producer task"""
    stopped: list[bool] = []

    async def stop() -> None:
        stopped.append(True)

    stream = TextStream(finite_lines(5, exit_code=0), on_close=stop)

    async def scenario() -> None:
        await take(stream, 1)
        await stream.aclose()

    asyncio.run(scenario())

    assert stopped == [True]


@pytest.mark.parametrize(
    ("producer_kinds", "consumer_kinds", "expected"),
    [
        (
            frozenset({OutputKind.STREAM_TEXT}),
            frozenset({InputKind.STREAM_TEXT, InputKind.TEXT}),
            (OutputKind.STREAM_TEXT, InputKind.STREAM_TEXT),
        ),
        (
            frozenset({OutputKind.TEXT, OutputKind.STREAM_TEXT}),
            frozenset({InputKind.TEXT}),
            (OutputKind.TEXT, InputKind.TEXT),
        ),
        (
            frozenset({OutputKind.TEXT}),
            frozenset({InputKind.STREAM_TEXT}),
            (OutputKind.TEXT, InputKind.STREAM_TEXT),
        ),
        (
            frozenset({OutputKind.STREAM_BYTES}),
            frozenset({InputKind.STREAM_TEXT, InputKind.ARGUMENTS}),
            (OutputKind.STREAM_BYTES, InputKind.STREAM_TEXT),
        ),
    ],
    ids=[
        "shared_stream_wins",
        "shared_static_when_consumer_cannot_stream",
        "convert_static_to_stream",
        "bytes_to_text",
    ],
)
def test_choose_kinds_prefers_a_shared_streaming_kind(
    producer_kinds: frozenset[OutputKind], consumer_kinds: frozenset[InputKind], expected: tuple[OutputKind, InputKind]
) -> None:
    """Check that negotiation picks a shared kind, streaming first, and otherwise converts"""
    assert choose_kinds(producer_kinds, consumer_kinds) == expected


async def collect(value: object) -> object:
    """Return a converted value with any stream drained into a list

    Args:
        value: The result of a conversion

    Returns:
        The value, or the list of its chunks when it streams
    """
    if hasattr(value, "__aiter__"):
        return [chunk async for chunk in value]
    return value


@pytest.mark.parametrize(
    ("value", "from_kind", "to_kind", "expected"),
    [
        ("ab", OutputKind.TEXT, OutputKind.BYTES, b"ab"),
        (b"ab", OutputKind.BYTES, OutputKind.TEXT, "ab"),
        (["a", "b"], OutputKind.STREAM_TEXT, OutputKind.TEXT, "ab"),
        ([b"a", b"b"], OutputKind.STREAM_BYTES, OutputKind.TEXT, "ab"),
        ("ab", OutputKind.TEXT, OutputKind.STREAM_TEXT, ["ab"]),
        (["a", "b"], OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES, [b"a", b"b"]),
        ([b"a", b"\xff"], OutputKind.STREAM_BYTES, OutputKind.STREAM_TEXT, ["a", "�"]),
    ],
    ids=[
        "text_to_bytes",
        "bytes_to_text",
        "stream_text_to_text",
        "stream_bytes_to_text",
        "text_to_stream",
        "stream_text_to_stream_bytes",
        "stream_bytes_to_stream_text_replaces_bad_bytes",
    ],
)
def test_convert_reshapes_between_kinds(
    value: object, from_kind: OutputKind, to_kind: OutputKind, expected: object
) -> None:
    """Check that every supported conversion yields the same data in the new kind"""

    async def scenario() -> object:
        return await collect(await convert(value, from_kind, to_kind))

    assert asyncio.run(scenario()) == expected


def test_convert_between_streams_stays_lazy() -> None:
    """Check that converting a stream of text to bytes pulls nothing until the result is iterated"""
    producer = CountingProducer()

    async def scenario() -> bytes:
        converted = await convert(producer.lines(), OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES)
        first = await converted.__anext__()
        await converted.aclose()
        return first

    first = asyncio.run(scenario())

    assert (first, producer.pulled) == (b"1\n", 1)
