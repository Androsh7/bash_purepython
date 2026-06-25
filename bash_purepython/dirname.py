"""PurePython implementation of the bash dirname command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import PurePosixPath


def main():
    parser = ArgumentParser(prog="dirname", description="Strip last component from a filename")
    parser.add_argument("names", nargs="+", help="Paths")
    args = parser.parse_args()

    for name in args.names:
        parent = PurePosixPath(name.replace("\\", "/")).parent
        print(str(parent) if str(parent) else ".")


if __name__ == "__main__":
    main()
