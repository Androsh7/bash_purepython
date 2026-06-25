"""PurePython implementation of the bash wc command"""

# Standard libraries
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def count(data: bytes, text: str) -> tuple[int, int, int, int]:
    lines = data.count(b"\n")
    words = len(text.split())
    chars = len(text)
    nbytes = len(data)
    return lines, words, chars, nbytes


def main():
    parser = ArgumentParser(prog="wc", description="Print line, word, and byte counts")
    parser.add_argument("-l", "--lines", action="store_true", help="Print line count")
    parser.add_argument("-w", "--words", action="store_true", help="Print word count")
    parser.add_argument("-c", "--bytes", action="store_true", help="Print byte count")
    parser.add_argument("-m", "--chars", action="store_true", help="Print char count")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    show_lines = args.lines
    show_words = args.words
    show_bytes = args.bytes
    show_chars = args.chars
    if not (show_lines or show_words or show_bytes or show_chars):
        show_lines = show_words = show_bytes = True

    totals = [0, 0, 0, 0]
    sources: list[tuple[str, bytes]] = []
    if not args.paths:
        sources.append(("", sys.stdin.buffer.read()))
    else:
        for path_str in args.paths:
            path = Path(path_str)
            if not path.exists():
                print_error(f"{path}: No such file or directory")
            if path.is_dir():
                print_error(f"{path}: Is a directory")
            sources.append((path_str, path.read_bytes()))

    def emit(label: str, vals: tuple[int, int, int, int]):
        parts: list[str] = []
        if show_lines:
            parts.append(f"{vals[0]:>8}")
        if show_words:
            parts.append(f"{vals[1]:>8}")
        if show_chars:
            parts.append(f"{vals[2]:>8}")
        if show_bytes:
            parts.append(f"{vals[3]:>8}")
        if label:
            parts.append(label)
        print(" ".join(parts))

    for label, data in sources:
        text = data.decode("utf-8", errors="replace")
        vals = count(data, text)
        for i, v in enumerate(vals):
            totals[i] += v
        emit(label, vals)

    if len(sources) > 1:
        emit("total", tuple(totals))


if __name__ == "__main__":
    main()
