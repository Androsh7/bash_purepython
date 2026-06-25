"""PurePython implementation of the bash date command"""

# Standard libraries
from argparse import ArgumentParser
from datetime import UTC, datetime


def main():
    parser = ArgumentParser(prog="date", description="Print the current date and time")
    parser.add_argument("-u", "--utc", action="store_true", help="Use UTC")
    parser.add_argument("format", nargs="?", default=None, help="strftime format prefixed with '+'")
    args = parser.parse_args()

    now = datetime.now(UTC) if args.utc else datetime.now().astimezone()
    fmt = args.format
    if fmt and fmt.startswith("+"):
        fmt = fmt[1:]
    if not fmt:
        fmt = "%a %b %d %H:%M:%S %Z %Y"
    print(now.strftime(fmt))


if __name__ == "__main__":
    main()
