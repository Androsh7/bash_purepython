"""PurePython implementation of the bash uniq command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_purepython._io import read_text


def main():
    parser = ArgumentParser(prog="uniq", description="Filter adjacent matching lines")
    parser.add_argument("-c", "--count", action="store_true", help="Prefix lines with their count")
    parser.add_argument("-d", "--repeated", action="store_true", help="Only output duplicated lines")
    parser.add_argument("-u", "--unique", action="store_true", help="Only output non-duplicated lines")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="Fold case when comparing")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    text = read_text(args.paths)
    lines = text.splitlines()

    groups: list[tuple[str, int]] = []
    for line in lines:
        key = line.casefold() if args.ignore_case else line
        if groups and (groups[-1][0].casefold() if args.ignore_case else groups[-1][0]) == key:
            groups[-1] = (groups[-1][0], groups[-1][1] + 1)
        else:
            groups.append((line, 1))

    for line, n in groups:
        is_dup = n > 1
        if args.repeated and not is_dup:
            continue
        if args.unique and is_dup:
            continue
        if args.count:
            sys.stdout.write(f"{n:>7} {line}\n")
        else:
            sys.stdout.write(f"{line}\n")


if __name__ == "__main__":
    main()
