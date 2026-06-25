"""PurePython implementation of the bash cut command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_purepython._color import print_error
from bash_purepython._io import read_text


def parse_list(spec: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else 10**9
        else:
            start = end = int(part)
        if start < 1 or end < start:
            print_error(f"invalid range: {part}")
        ranges.append((start, end))
    return ranges


def in_ranges(idx: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= idx <= end for start, end in ranges)


def main():
    parser = ArgumentParser(prog="cut", description="Remove sections from each line")
    parser.add_argument("-d", "--delimiter", default="\t", help="Field delimiter (default TAB)")
    parser.add_argument("-f", "--fields", help="Field list")
    parser.add_argument("-c", "--characters", help="Character list (1-indexed)")
    parser.add_argument("-b", "--bytes", help="Byte list (1-indexed)")
    parser.add_argument("-s", "--only-delimited", action="store_true", help="Skip lines with no delimiter")
    parser.add_argument("paths", nargs="*", help="Files to read (stdin if none)")
    args = parser.parse_args()

    chosen = [x for x in (args.fields, args.characters, args.bytes) if x is not None]
    if len(chosen) != 1:
        print_error("specify exactly one of -f, -c, -b")

    text = read_text(args.paths)
    for line in text.splitlines():
        if args.fields is not None:
            ranges = parse_list(args.fields)
            if args.delimiter not in line:
                if not args.only_delimited:
                    sys.stdout.write(line + "\n")
                continue
            cols = line.split(args.delimiter)
            picked = [c for i, c in enumerate(cols, start=1) if in_ranges(i, ranges)]
            sys.stdout.write(args.delimiter.join(picked) + "\n")
        elif args.characters is not None:
            ranges = parse_list(args.characters)
            picked = [c for i, c in enumerate(line, start=1) if in_ranges(i, ranges)]
            sys.stdout.write("".join(picked) + "\n")
        else:
            ranges = parse_list(args.bytes)
            data = line.encode("utf-8")
            picked_b = bytes(b for i, b in enumerate(data, start=1) if in_ranges(i, ranges))
            sys.stdout.write(picked_b.decode("utf-8", errors="replace") + "\n")


if __name__ == "__main__":
    main()
