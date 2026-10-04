"""Provide the streams a command's stdin, stdout and stderr are bound to"""

# Standard libraries
import codecs
import io
from collections.abc import Callable
from typing import TextIO

# Project libraries
from bash_purepython.shell.models import OUTPUT_LIMIT_BYTES, OutputLimitExceededError

STREAM_ENCODING = "utf-8"
OutputSink = Callable[[str, str], None]
STDOUT_KIND = "stdout"
STDERR_KIND = "stderr"


class LimitedBytesIO(io.BytesIO):
    """Hold bytes in memory, refuse to grow past a limit, and remember that it happened"""

    def __init__(self, limit_bytes: int = OUTPUT_LIMIT_BYTES):
        """Start empty with the given limit

        Args:
            limit_bytes: The most bytes the buffer may hold
        """
        super().__init__()
        self._limit_bytes = limit_bytes
        self.overflowed = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        """Append data unless it would push the buffer past the limit

        Args:
            data: The bytes to append

        Raises:
            OutputLimitExceededError: If the buffer would exceed its limit

        Returns:
            The number of bytes written
        """
        if self.tell() + len(data) > self._limit_bytes:
            self.overflowed = True
            raise OutputLimitExceededError(f"output limit of {self._limit_bytes} bytes exceeded")
        return super().write(data)


class OutputCapture:
    """Collect everything a command writes to a text stream or to its byte buffer"""

    def __init__(self, limit_bytes: int = OUTPUT_LIMIT_BYTES):
        """Create an empty capture

        Args:
            limit_bytes: The most bytes the capture may hold
        """
        self._raw = LimitedBytesIO(limit_bytes)
        self.limit_bytes = limit_bytes
        self.stream: TextIO = wrap_binary(self._raw)

    @property
    def overflowed(self) -> bool:
        """Return whether a write was refused for exceeding the limit"""
        return self._raw.overflowed

    def getvalue(self) -> bytes:
        """Return every byte written so far"""
        return self._raw.getvalue()


class SinkWriter(io.RawIOBase):
    """Forward every write to a host callback as text, as soon as it happens"""

    def __init__(self, sink: OutputSink, kind: str):
        """Bind the writer to one sink and one stream kind

        Args:
            sink: The callback receiving (kind, text)
            kind: Which stream this is, stdout or stderr
        """
        super().__init__()
        self._sink = sink
        self._kind = kind
        self._decoder = codecs.getincrementaldecoder(STREAM_ENCODING)(errors="replace")

    def writable(self) -> bool:
        """Return True, since the writer only writes"""
        return True

    def write(self, data: bytes | bytearray | memoryview) -> int:
        """Decode data and hand the text to the sink

        Args:
            data: The bytes a command wrote

        Returns:
            The number of bytes accepted
        """
        text = self._decoder.decode(bytes(data))
        if text:
            self._sink(self._kind, text)
        return len(data)

    def flush(self) -> None:
        """Hand any bytes of an unfinished character to the sink"""
        super().flush()
        text = self._decoder.decode(b"", final=True)
        if text:
            self._sink(self._kind, text)


def wrap_binary(raw: io.IOBase) -> TextIO:
    """Return a text stream over a binary one that also exposes the bytes through .buffer

    Writes pass straight through, so a host sink sees them as they happen and the
    bytes written through .buffer stay in order with the text

    Args:
        raw: The binary stream to wrap

    Returns:
        A text stream with no newline translation
    """
    return io.TextIOWrapper(raw, encoding=STREAM_ENCODING, errors="replace", newline="", write_through=True)


def make_stdin(data: bytes) -> TextIO:
    """Return a readable text stream over data that also exposes the bytes through .buffer

    Args:
        data: The bytes the command reads as its standard input

    Returns:
        A text stream positioned at the start
    """
    return wrap_binary(io.BytesIO(data))


def make_sink_stream(sink: OutputSink, kind: str) -> TextIO:
    """Return a text stream whose writes go straight to the host sink

    Args:
        sink: The callback receiving (kind, text)
        kind: Which stream this is, stdout or stderr

    Returns:
        A writable text stream
    """
    return wrap_binary(SinkWriter(sink, kind))
