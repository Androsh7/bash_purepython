"""PurePython implementation of the bash tee command"""

# Standard libraries
import sys
from argparse import ArgumentParser
from contextlib import ExitStack
from pathlib import Path

CHUNK_SIZE_BYTES = 8192


def main():
    """Copy stdin to stdout and to each named file"""
    parser = ArgumentParser(prog="tee", description="Copy stdin to stdout and to each file")
    parser.add_argument("-a", "--append", action="store_true", help="Append to files instead of overwriting")
    parser.add_argument("paths", nargs="*", help="Output files")
    args = parser.parse_args()

    mode = "ab" if args.append else "wb"
    with ExitStack() as stack:
        handles = [stack.enter_context(Path(path_str).open(mode)) for path_str in args.paths]
        while True:
            chunk = sys.stdin.buffer.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            for handle in handles:
                handle.write(chunk)


if __name__ == "__main__":
    main()
