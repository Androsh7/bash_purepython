"""PurePython implementation of the bash head command"""

# Standard libraries
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def main():
    parser = ArgumentParser(prog="head", description="Print the first lines of files")
    parser.add_argument("-n", "--lines", type=int, default=10, help="Number of lines to print")
    parser.add_argument("-c", "--bytes", type=int, default=None, help="Number of bytes to print")
    parser.add_argument("-q", "--quiet", action="store_true", help="Never print headers")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    sources: list[tuple[str, bytes]] = []
    if not args.paths:
        sources.append(("-", sys.stdin.buffer.read()))
    else:
        for path_str in args.paths:
            path = Path(path_str)
            if not path.exists():
                print_error(f"{path}: No such file or directory")
            if path.is_dir():
                print_error(f"{path}: Is a directory")
            sources.append((path_str, path.read_bytes()))

    show_header = len(sources) > 1 and not args.quiet
    for idx, (label, data) in enumerate(sources):
        if show_header:
            if idx:
                sys.stdout.write("\n")
            sys.stdout.write(f"==> {label} <==\n")
        if args.bytes is not None:
            sys.stdout.buffer.write(data[: args.bytes])
        else:
            kept: list[bytes] = []
            count = 0
            for line in data.splitlines(keepends=True):
                if count >= args.lines:
                    break
                kept.append(line)
                count += 1
            sys.stdout.buffer.write(b"".join(kept))


if __name__ == "__main__":
    main()
