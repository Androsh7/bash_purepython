"""PurePython implementation of the bash sort command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_purepython._color import print_error
from bash_purepython._io import read_text


def numeric_key(value: str) -> tuple[int, float, str]:
    stripped = value.strip()
    try:
        return (0, float(stripped), value)
    except ValueError:
        return (1, 0.0, value)


def main():
    parser = ArgumentParser(prog="sort", description="Sort lines of text")
    parser.add_argument("-r", "--reverse", action="store_true", help="Reverse the result")
    parser.add_argument("-u", "--unique", action="store_true", help="Output only unique lines")
    parser.add_argument("-n", "--numeric-sort", action="store_true", help="Sort numerically")
    parser.add_argument("-f", "--ignore-case", action="store_true", help="Fold case")
    parser.add_argument("-k", "--key", type=int, default=None, help="Sort on whitespace-split column (1-indexed)")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    if args.key is not None and args.key < 1:
        print_error("key column must be >= 1")

    text = read_text(args.paths)
    lines = text.splitlines()

    def key_fn(line: str):
        if args.key is not None:
            cols = line.split()
            target = cols[args.key - 1] if len(cols) >= args.key else ""
        else:
            target = line
        if args.ignore_case:
            target = target.casefold()
        if args.numeric_sort:
            return numeric_key(target)
        return (0, 0.0, target)

    lines.sort(key=key_fn, reverse=args.reverse)
    if args.unique:
        seen: set[str] = set()
        deduped: list[str] = []
        for line in lines:
            marker = line.casefold() if args.ignore_case else line
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(line)
        lines = deduped

    sys.stdout.write("\n".join(lines))
    if lines:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
