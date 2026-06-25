"""PurePython implementation of the bash cat command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_python_utils._io import read_text


def main():
    parser = ArgumentParser(prog="cat", description="Concatenate files and print to stdout")
    parser.add_argument("-n", "--number", action="store_true", help="Number all output lines")
    parser.add_argument("-b", "--number-nonblank", action="store_true", help="Number non-empty output lines")
    parser.add_argument("-s", "--squeeze-blank", action="store_true", help="Suppress repeated empty lines")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    text = read_text(args.paths)
    lines = text.splitlines(keepends=True)

    if args.squeeze_blank:
        squeezed: list[str] = []
        prev_blank = False
        for line in lines:
            blank = line.strip("\n") == ""
            if blank and prev_blank:
                continue
            squeezed.append(line)
            prev_blank = blank
        lines = squeezed

    counter = 0
    for line in lines:
        is_blank = line.strip("\n") == ""
        if args.number_nonblank:
            if not is_blank:
                counter += 1
                sys.stdout.write(f"{counter:>6}\t{line}")
            else:
                sys.stdout.write(line)
        elif args.number:
            counter += 1
            sys.stdout.write(f"{counter:>6}\t{line}")
        else:
            sys.stdout.write(line)


if __name__ == "__main__":
    main()
