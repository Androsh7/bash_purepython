"""PurePython implementation of the bash nl command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_python_utils._io import read_text


def main():
    parser = ArgumentParser(prog="nl", description="Number lines of files")
    parser.add_argument(
        "-b", "--body-numbering", choices=["a", "t", "n"], default="t", help="a=all, t=non-empty (default), n=none"
    )
    parser.add_argument("-s", "--number-separator", default="\t", help="Separator between number and line")
    parser.add_argument("-w", "--number-width", type=int, default=6, help="Width of the number column")
    parser.add_argument("-i", "--line-increment", type=int, default=1, help="Increment between numbers")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    counter = 0
    for line in read_text(args.paths).splitlines():
        is_blank = line.strip() == ""
        number_it = args.body_numbering == "a" or (args.body_numbering == "t" and not is_blank)
        if number_it:
            counter_str = str(counter + args.line_increment).rjust(args.number_width)
            counter += args.line_increment
            sys.stdout.write(f"{counter_str}{args.number_separator}{line}\n")
        else:
            sys.stdout.write(" " * args.number_width + args.number_separator + line + "\n")


if __name__ == "__main__":
    main()
