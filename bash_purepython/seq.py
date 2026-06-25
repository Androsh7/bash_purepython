"""PurePython implementation of the bash seq command"""

# Standard libraries
from argparse import ArgumentParser

# Project libraries
from bash_purepython._color import print_error


def main():
    parser = ArgumentParser(prog="seq", description="Print a sequence of numbers")
    parser.add_argument("-s", "--separator", default="\n", help="Separator (default newline)")
    parser.add_argument("-w", "--equal-width", action="store_true", help="Pad numbers with leading zeros")
    parser.add_argument("numbers", nargs="+", help="LAST | FIRST LAST | FIRST INCREMENT LAST")
    args = parser.parse_args()

    try:
        nums = [float(n) for n in args.numbers]
    except ValueError:
        print_error("invalid number")
        return

    match nums:
        case [last]:
            first, increment = 1.0, 1.0
        case [first, last]:
            increment = 1.0
        case [first, increment, last]:
            pass
        case _:
            print_error("seq takes 1 to 3 numbers")
            return

    if increment == 0:
        print_error("increment must be non-zero")

    all_int = all(n == int(n) for n in (first, increment, last))

    values: list[str] = []
    current = first
    while (increment > 0 and current <= last) or (increment < 0 and current >= last):
        values.append(str(int(current)) if all_int else f"{current:g}")
        current += increment

    if args.equal_width and values:
        width = max(len(v.lstrip("-")) for v in values)
        values = [("-" if v.startswith("-") else "") + v.lstrip("-").rjust(width, "0") for v in values]

    print(args.separator.join(values))


if __name__ == "__main__":
    main()
