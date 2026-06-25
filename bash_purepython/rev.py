"""PurePython implementation of the bash rev command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_python_utils._io import read_text


def main():
    parser = ArgumentParser(prog="rev", description="Reverse each line of input")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    for line in read_text(args.paths).splitlines():
        sys.stdout.write(line[::-1] + "\n")


if __name__ == "__main__":
    main()
