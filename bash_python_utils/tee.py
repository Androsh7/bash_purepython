"""PurePython implementation of the bash tee command"""

# Standard libraries
import sys
from argparse import ArgumentParser
from pathlib import Path


def main():
    parser = ArgumentParser(prog="tee", description="Copy stdin to stdout and to each file")
    parser.add_argument("-a", "--append", action="store_true", help="Append to files instead of overwriting")
    parser.add_argument("paths", nargs="*", help="Output files")
    args = parser.parse_args()

    mode = "ab" if args.append else "wb"
    handles = [Path(p).open(mode) for p in args.paths]
    try:
        while True:
            chunk = sys.stdin.buffer.read(8192)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            for fp in handles:
                fp.write(chunk)
    finally:
        for fp in handles:
            fp.close()


if __name__ == "__main__":
    main()
